"""Roaming Music fade engine — async volume transitions with speaker availability awareness."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .const import VOLUME_SET_CALL_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_STEPS_PER_SECOND: int = 4
_STEP_INTERVAL: float = 0.25

@dataclass
class FadeResult:
    """
    Summary of a completed (or aborted) fade, for coordinator diagnostics and error reporting.
    :param commanded_speakers: Entity IDs that received at least one ``volume_set`` call.
    :param skipped_speakers: ``(entity_id, reason)`` tuples for speakers skipped due to unavailability.
    :param call_timeouts: Number of individual ``volume_set`` calls that timed out during the fade.
    """

    commanded_speakers: list[str]
    skipped_speakers: list[tuple[str, str]]
    call_timeouts: int = 0

    @property
    def all_unavailable(self) -> bool:
        """Return True when no speaker ever received a volume command during the fade."""
        return not self.commanded_speakers

async def fade_volume(
    hass: HomeAssistant,
    entity_ids: list[str],
    target_volume: float,
    duration: float,
    curve: str,
    room_name: str | None = None,
    volume_set_timeout: float = VOLUME_SET_CALL_TIMEOUT,
) -> FadeResult:
    """
    Fade one or more media players from their current volume toward ``target_volume``.
    :param target_volume: Final volume level in the range ``0.0``–``1.0``.
    :param duration: Fade duration in seconds; ``<= 0`` performs a single immediate ``volume_set``.
    :param curve: Fade curve name — ``"logarithmic"``, ``"bezier"``, or ``"linear"``.
    :param room_name: Optional room label included in diagnostic log messages.
    :param volume_set_timeout: Per-call timeout (seconds) for individual ``volume_set`` service calls.
    :return: :class:`FadeResult` describing commanded speakers, skipped speakers, and timeout count.
    """
    room_label = room_name or "unknown"
    commanded: set[str] = set()
    skipped_by_entity: dict[str, str] = {}
    warned_skips: set[tuple[str, str]] = set()
    call_timeouts: int = 0

    def _record_skips(skipped: list[tuple[str, str]]) -> None:
        # Log each (entity_id, reason) pair once per fade to avoid per-step log spam.
        for entity_id, reason in skipped:
            skipped_by_entity[entity_id] = reason
            key = (entity_id, reason)
            if key in warned_skips:
                continue
            warned_skips.add(key)
            _LOGGER.warning(
                "Skipping unavailable speaker: room=%s entity_id=%s reason=%s",
                room_label,
                entity_id,
                reason,
            )

    if not entity_ids:
        return FadeResult(commanded_speakers=[], skipped_speakers=[])

    available_entities, skipped_entities = _classify_speakers(hass, entity_ids)
    _record_skips(skipped_entities)
    if not available_entities:
        _LOGGER.warning(
            "All speakers unavailable for room=%s; skipping fade",
            room_label,
        )
        return FadeResult(commanded_speakers=[], skipped_speakers=list(skipped_by_entity.items()))

    # Duration <= 0: single immediate volume_set, no fade loop.
    if duration <= 0:
        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": available_entities, "volume_level": target_volume},
                    blocking=True,
                ),
                timeout=volume_set_timeout,
            )
            commanded.update(available_entities)
        except asyncio.TimeoutError:
            call_timeouts += 1
            _LOGGER.warning(
                "volume_set call timed out: room=%s entities=%s timeout=%.1fs",
                room_label,
                available_entities,
                volume_set_timeout,
            )
        return FadeResult(
            commanded_speakers=sorted(commanded),
            skipped_speakers=list(skipped_by_entity.items()),
            call_timeouts=call_timeouts,
        )

    start_volume = _get_current_volume(hass, available_entities[0])
    total_steps = max(int(_STEPS_PER_SECOND * duration), 1)

    _LOGGER.debug(
        "Fade starting: entities=%s start_vol=%.3f target=%.3f duration=%.1fs steps=%d curve=%s",
        available_entities,
        start_volume,
        target_volume,
        duration,
        total_steps,
        curve,
    )

    # Stepped fade loop — re-classify each step so newly-unavailable speakers are dropped mid-fade.
    for idx in range(total_steps):
        step_entities, skipped_entities = _classify_speakers(hass, entity_ids)
        _record_skips(skipped_entities)
        if not step_entities:
            _LOGGER.warning(
                "All speakers unavailable for room=%s; stopping fade early",
                room_label,
            )
            break

        t = (idx + 1) / total_steps
        factor = _compute_curve_factor(t, curve)
        vol_level = start_volume + factor * (target_volume - start_volume)
        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": step_entities, "volume_level": vol_level},
                    blocking=True,
                ),
                timeout=volume_set_timeout,
            )
            commanded.update(step_entities)
        except asyncio.TimeoutError:
            call_timeouts += 1
            _LOGGER.warning(
                "volume_set call timed out: room=%s entities=%s timeout=%.1fs",
                room_label,
                step_entities,
                volume_set_timeout,
            )
        await asyncio.sleep(_STEP_INTERVAL)

    # Final pin to exact target (guards against floating-point drift accumulated in the step loop).
    final_entities, skipped_entities = _classify_speakers(hass, entity_ids)
    _record_skips(skipped_entities)
    if final_entities:
        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": final_entities, "volume_level": target_volume},
                    blocking=True,
                ),
                timeout=volume_set_timeout,
            )
            commanded.update(final_entities)
        except asyncio.TimeoutError:
            call_timeouts += 1
            _LOGGER.warning(
                "volume_set call timed out: room=%s entities=%s timeout=%.1fs",
                room_label,
                final_entities,
                volume_set_timeout,
            )
    else:
        _LOGGER.warning(
            "All speakers unavailable for room=%s; skipping final volume pin",
            room_label,
        )

    _LOGGER.debug(
        "Fade complete: entities=%s final_vol=%.3f",
        sorted(commanded),
        target_volume,
    )

    return FadeResult(
        commanded_speakers=sorted(commanded),
        skipped_speakers=list(skipped_by_entity.items()),
        call_timeouts=call_timeouts,
    )

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _classify_speakers(
    hass: HomeAssistant,
    entity_ids: list[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Partition speaker entity IDs into available and skipped lists based on their HA state.
    :return: ``(available, skipped)`` where ``skipped`` is a list of ``(entity_id, reason)`` tuples.
    """
    available: list[str] = []
    skipped: list[tuple[str, str]] = []
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None:
            skipped.append((entity_id, "missing_state"))
            continue
        if state.state == "unavailable":
            skipped.append((entity_id, "state_unavailable"))
            continue
        if state.state == "unknown":
            skipped.append((entity_id, "state_unknown"))
            continue
        available.append(entity_id)
    return available, skipped

def _get_current_volume(hass: HomeAssistant, entity_id: str) -> float:
    """Read the current ``volume_level`` attribute for a media player, defaulting to 0.0."""
    state = hass.states.get(entity_id)
    if state is None:
        return 0.0
    try:
        return float(state.attributes.get("volume_level", 0.0))
    except (TypeError, ValueError):
        return 0.0

def _compute_curve_factor(t: float, curve: str) -> float:
    """
    Map a normalized time ``t`` in ``[0, 1]`` to a curve factor in ``[0, 1]`` for fade interpolation.
    :param t: Normalized fade progress (``(step_index + 1) / total_steps``).
    :param curve: Curve name — ``"logarithmic"``, ``"bezier"``, or any other value for linear.
    """
    if curve == "logarithmic":
        return t / (1 + (1 - t))
    if curve == "bezier":
        return t * t * (3 - 2 * t)
    return t
