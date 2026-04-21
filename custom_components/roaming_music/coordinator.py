"""Roaming Music coordinator — room registry, presence handling, and fade task dispatch."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import fade_engine
from .const import (
    CONF_DEFAULT_VOLUME,
    CONF_FADE_DURATION,
    CONF_OCCUPIED_STATES,
    CONF_PRESENCE_SENSORS,
    CONF_SPEAKERS,
    DEFAULT_FADE_DURATION,
    DEFAULT_VOLUME,
    FADE_CURVE_LOGARITHMIC,
    FADE_TIMEOUT_BUFFER,
    ROAMING_STATE_ACTIVE,
    ROAMING_STATE_ERROR,
    ROAMING_STATE_FADING,
    ROAMING_STATE_IDLE,
    SIGNAL_STATE_CHANGED,
    VOLUME_SET_CALL_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class RoomState:
    """
    Per-room runtime state tracked by the coordinator.
    :param entry_id: Config entry ID this room corresponds to.
    :param name: User-facing room name.
    :param occupied: Latest OR-evaluated occupancy across the room's presence sensors.
    :param fade_active: True while a fade task is in flight for this room.
    :param target_volume: Current target volume for occupied fades (driven by the per-room number entity).
    :param fade_duration: Current fade duration in seconds (driven by the per-room number entity).
    :param options: Snapshot of the config entry options used for fade dispatch and occupancy evaluation.
    :param last_error: Most recent human-readable error string, or ``None`` if the room is healthy.
    :param last_error_time: UTC timestamp the last error was recorded, paired with ``last_error``.
    """

    entry_id: str
    name: str
    occupied: bool = False
    fade_active: bool = False
    target_volume: float = 0.5
    fade_duration: float = 2.0
    options: dict[str, Any] | None = None
    last_error: str | None = None
    last_error_time: datetime | None = None

class RoamingCoordinator:
    """Central coordinator owning room state, presence listeners, and per-room fade tasks."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._rooms: dict[str, RoomState] = {}
        self._room_listeners: dict[str, list[Callable[[], None]]] = {}
        self.roaming_enabled = True
        self._fade_tasks: dict[str, asyncio.Task] = {}
        _LOGGER.debug("RoamingCoordinator initialized")

    def set_roaming_enabled(self, enabled: bool) -> None:
        """Update the global roaming-enabled flag; no-op when the value is unchanged."""
        previous = self.roaming_enabled
        if enabled == previous:
            return
        self.roaming_enabled = enabled
        _LOGGER.debug(
            "Roaming enabled updated: previous=%s new=%s",
            previous,
            enabled,
        )

    @property
    def roaming_state(self) -> str:
        """Return the aggregate roaming state (``error``/``fading``/``active``/``idle``) across all rooms."""
        rooms = self._rooms.values()
        if any(r.last_error is not None for r in rooms):
            return ROAMING_STATE_ERROR
        if any(r.fade_active for r in rooms):
            return ROAMING_STATE_FADING
        if any(r.occupied for r in rooms):
            return ROAMING_STATE_ACTIVE
        return ROAMING_STATE_IDLE

    @property
    def active_room_names(self) -> list[str]:
        """Return the names of currently-occupied rooms."""
        return [r.name for r in self._rooms.values() if r.occupied]

    @property
    def per_room_errors(self) -> dict[str, str]:
        """Return a ``{room_name: last_error}`` map for rooms currently reporting an error."""
        return {
            r.name: r.last_error
            for r in self._rooms.values()
            if r.last_error is not None
        }

    def dispatch_state_update(self) -> None:
        """Fire the integration's dispatcher signal so global sensors refresh their native values."""
        async_dispatcher_send(self._hass, SIGNAL_STATE_CHANGED)
        _LOGGER.debug("Dispatcher signal fired: %s", SIGNAL_STATE_CHANGED)

    def dispatch_fade(self, entry_id: str, target_volume: float) -> None:
        """
        Start (or restart) a fade task for a room, cancelling any in-flight fade for that room.
        :param target_volume: Target volume level in the range ``0.0``–``1.0``.
        """
        room = self._rooms.get(entry_id)
        if room is None:
            return

        existing_task = self._fade_tasks.get(entry_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
            _LOGGER.debug(
                "dispatch_fade: cancelled existing task for room=%s",
                room.name,
            )

        options = room.options or {}
        speakers = list(options.get(CONF_SPEAKERS, []))
        if not speakers:
            _LOGGER.debug(
                "dispatch_fade: no speakers configured for room=%s, skipping",
                room.name,
            )
            return

        fade_duration = room.fade_duration
        # Coordinator-triggered fades always use logarithmic. The exposed ``fade_volume`` service still accepts a curve parameter.
        fade_curve = FADE_CURVE_LOGARITHMIC

        room.fade_active = True
        self.dispatch_state_update()

        _LOGGER.debug(
            "dispatch_fade: room=%s target_volume=%.2f duration=%.1f curve=%s speakers=%s",
            room.name,
            target_volume,
            fade_duration,
            fade_curve,
            speakers,
        )

        async def _run_fade() -> None:
            try:
                fade_result = await asyncio.wait_for(
                    fade_engine.fade_volume(
                        self._hass,
                        speakers,
                        target_volume,
                        fade_duration,
                        fade_curve,
                        room.name,
                        volume_set_timeout=VOLUME_SET_CALL_TIMEOUT,
                    ),
                    timeout=fade_duration + FADE_TIMEOUT_BUFFER,
                )

                skipped_speakers: list[tuple[str, str]] = []
                commanded_speakers: list[str] = []

                result_skips = getattr(fade_result, "skipped_speakers", None)
                if isinstance(result_skips, list):
                    skipped_speakers = [
                        item
                        for item in result_skips
                        if isinstance(item, tuple) and len(item) == 2
                    ]

                result_commanded = getattr(fade_result, "commanded_speakers", None)
                if isinstance(result_commanded, list):
                    commanded_speakers = [
                        item for item in result_commanded if isinstance(item, str)
                    ]

                if skipped_speakers:
                    skip_details = ", ".join(
                        f"{entity_id}({reason})" for entity_id, reason in skipped_speakers
                    )
                    room.last_error = f"speakers skipped: {skip_details}"
                    room.last_error_time = dt_util.utcnow()
                    _LOGGER.warning(
                        "dispatch_fade: speakers skipped: room=%s skipped=%s commanded=%s",
                        room.name,
                        skip_details,
                        commanded_speakers,
                    )
                elif room.last_error and room.last_error.startswith("speakers skipped:"):
                    room.last_error = None
                    room.last_error_time = None

                call_timeouts = getattr(fade_result, "call_timeouts", 0)
                if call_timeouts > 0:
                    timeout_note = f"volume_set timed out: {call_timeouts} call(s)"
                    if room.last_error:
                        room.last_error = f"{room.last_error}; {timeout_note}"
                    else:
                        room.last_error = timeout_note
                    room.last_error_time = dt_util.utcnow()
                    _LOGGER.warning(
                        "dispatch_fade: volume_set calls timed out: room=%s count=%d",
                        room.name,
                        call_timeouts,
                    )
                elif room.last_error and room.last_error.startswith("volume_set timed out:"):
                    room.last_error = None
                    room.last_error_time = None

                _LOGGER.debug(
                    "dispatch_fade: completed: room=%s target_volume=%.2f status=success",
                    room.name,
                    target_volume,
                )
            except asyncio.CancelledError:
                _LOGGER.debug(
                    "dispatch_fade: cancelled: room=%s",
                    room.name,
                )
                raise
            except asyncio.TimeoutError:
                room.last_error = f"fade timed out after {fade_duration + FADE_TIMEOUT_BUFFER:.1f}s"
                room.last_error_time = dt_util.utcnow()
                _LOGGER.warning(
                    "dispatch_fade: timed out: room=%s duration=%.1f timeout=%.1f",
                    room.name,
                    fade_duration,
                    fade_duration + FADE_TIMEOUT_BUFFER,
                )
            except Exception as err:
                room.last_error = f"fade failed: {err}"
                room.last_error_time = dt_util.utcnow()
                _LOGGER.warning(
                    "dispatch_fade: error: room=%s error=%s",
                    room.name,
                    err,
                )
            finally:
                room.fade_active = False
                self._fade_tasks.pop(entry_id, None)
                self.dispatch_state_update()

        task = self._hass.async_create_task(_run_fade())
        self._fade_tasks[entry_id] = task

    def _cancel_listeners(
        self, entry_id: str, listeners: list[Callable[[], None]]) -> None:
        """
        Invoke each state-change listener cancel callback, logging (but not raising) per-listener errors.
        :param listeners: Cancel callbacks returned by :func:`async_track_state_change_event`.
        """
        for cancel_fn in listeners:
            try:
                cancel_fn()
            except Exception as err:
                _LOGGER.warning(
                    "Listener cancel failed: entry_id=%s error=%s",
                    entry_id,
                    err,
                )

    def register_room(self, entry: ConfigEntry) -> None:
        """
        Register or re-register a room entry — replaces prior ``RoomState``, cancels stale listeners,
        and installs a fresh presence listener bound to the room's configured sensors.
        """
        existing_listeners = self._room_listeners.pop(entry.entry_id, [])
        if existing_listeners:
            self._cancel_listeners(entry.entry_id, existing_listeners)
        configured_volume = entry.options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)
        try:
            target_volume = float(configured_volume)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Invalid default volume in options for room=%s value=%s; using default=%s",
                entry.title,
                configured_volume,
                DEFAULT_VOLUME,
            )
            target_volume = DEFAULT_VOLUME
        target_volume = max(0.0, min(1.0, target_volume))
        configured_fade = entry.options.get(CONF_FADE_DURATION, DEFAULT_FADE_DURATION)
        try:
            fade_duration = float(configured_fade)
        except (TypeError, ValueError):
            fade_duration = DEFAULT_FADE_DURATION
        fade_duration = max(1.0, min(30.0, fade_duration))
        self._rooms[entry.entry_id] = RoomState(
            entry_id=entry.entry_id,
            name=entry.title,
            options=dict(entry.options),
            target_volume=target_volume,
            fade_duration=fade_duration,
        )
        sensors = list(entry.options.get(CONF_PRESENCE_SENSORS, []))
        if sensors:
            def _on_sensor_change(event: Any) -> None:
                self.handle_presence_change(
                    entry.entry_id,
                    event.data.get("new_state"),
                    event.data.get("old_state"),
                )
            cancel = async_track_state_change_event(self._hass, sensors, _on_sensor_change)
            self._room_listeners[entry.entry_id] = [cancel]
        else:
            self._room_listeners[entry.entry_id] = []
        _LOGGER.info("Room registered: %s (%s)", entry.title, entry.entry_id)
        _LOGGER.debug("Room listeners registered: room=%s sensors=%s", entry.title, sensors)
        _LOGGER.debug("RoamingCoordinator: %d room(s) registered", len(self._rooms))

    def unregister_room(self, entry_id: str) -> None:
        """Unregister a room — cancel its presence listeners and active fade task, then drop state."""
        listeners = self._room_listeners.pop(entry_id, [])
        self._cancel_listeners(entry_id, listeners)
        if listeners:
            _LOGGER.debug("Room listeners cancelled: %s", entry_id)
        task = self._fade_tasks.pop(entry_id, None)
        if task is not None and not task.done():
            task.cancel()
            _LOGGER.debug("Room fade task cancelled on unregister: %s", entry_id)
        room = self._rooms.pop(entry_id, None)
        if room:
            _LOGGER.info("Room unregistered: %s (%s)", room.name, entry_id)

    def handle_presence_change(
        self,
        entry_id: str,
        new_state: Any,
        old_state: Any,
    ) -> None:
        """React to a presence sensor state change — update occupancy and dispatch a fade when enabled."""
        room = self._rooms.get(entry_id)
        if room is None:
            return
        if new_state is None:
            return
        changed_entity_id = new_state.entity_id
        new_state_value = new_state.state

        if new_state_value in ("unavailable", "unknown"):
            error_msg = f"sensor {changed_entity_id} unavailable"
            if room.last_error != error_msg:
                room.last_error = error_msg
                room.last_error_time = dt_util.utcnow()
                _LOGGER.warning(
                    "Presence sensor unavailable: room=%s sensor=%s state=%s",
                    room.name,
                    changed_entity_id,
                    new_state_value,
                )
            occupied = self._evaluate_room_occupancy(room, changed_entity_id, new_state_value)
            room.occupied = occupied
            _LOGGER.debug(
                "Presence change: room=%s sensor=%s state=%s occupied=%s (sensor unavailable) roaming_enabled=%s",
                room.name,
                changed_entity_id,
                new_state_value,
                occupied,
                self.roaming_enabled,
            )
            if not self.roaming_enabled:
                _LOGGER.debug(
                    "Presence change: roaming disabled, no volume action for room=%s",
                    room.name,
                )
            else:
                if occupied:
                    self.dispatch_fade(entry_id, room.target_volume)
                else:
                    self.dispatch_fade(entry_id, 0.0)
            self.dispatch_state_update()
            return
        
        if room.last_error == f"sensor {changed_entity_id} unavailable":
            room.last_error = None
            room.last_error_time = None
            _LOGGER.debug(
                "Presence sensor recovered: room=%s sensor=%s state=%s",
                room.name,
                changed_entity_id,
                new_state_value,
            )

        occupied = self._evaluate_room_occupancy(room, changed_entity_id, new_state_value)
        room.occupied = occupied
        _LOGGER.debug(
            "Presence change: room=%s sensor=%s old_state=%s new_state=%s occupancy=%s roaming_enabled=%s",
            room.name,
            changed_entity_id,
            old_state.state if old_state else None,
            new_state_value,
            occupied,
            self.roaming_enabled,
        )
        if not self.roaming_enabled:
            _LOGGER.debug(
                "Presence change: roaming disabled, no volume action for room=%s",
                room.name,
            )
        else:
            if occupied:
                self.dispatch_fade(entry_id, room.target_volume)
            else:
                self.dispatch_fade(entry_id, 0.0)
        self.dispatch_state_update()

    def _evaluate_room_occupancy(
        self,
        room: RoomState,
        changed_entity_id: str,
        changed_state: str,
    ) -> bool:
        """
        Evaluate OR-logic occupancy across a room's presence sensors. The ``changed_entity_id`` /
        ``changed_state`` pair is treated as authoritative for that sensor (bypasses the HA state read).
        Returns True when any configured sensor reports an occupied state per the saved mapping.
        """
        options = room.options or {}
        presence_sensors = options.get(CONF_PRESENCE_SENSORS, [])
        occupied_states_map = options.get(CONF_OCCUPIED_STATES, {})
        for sensor_id in presence_sensors:
            if sensor_id == changed_entity_id:
                current_state = changed_state
            else:
                state_obj = self._hass.states.get(sensor_id)
                current_state = state_obj.state if state_obj is not None else None
            if current_state is not None and current_state in occupied_states_map.get(sensor_id, []):
                return True
        return False

    def update_room_default_volume(self, entry_id: str, volume: float) -> None:
        """
        Update a room's current target volume (driven by the per-room number entity).
        :param volume: New target volume in the range ``0.0``–``1.0``.
        """
        room = self._rooms.get(entry_id)
        if room is None:
            return
        room.target_volume = volume
        _LOGGER.debug(
            "Room default volume updated: room=%s value=%s",
            room.name,
            volume,
        )

    def update_room_fade_duration(self, entry_id: str, duration: float) -> None:
        """
        Update a room's current fade duration (driven by the per-room number entity).
        :param duration: New fade duration in seconds.
        """
        room = self._rooms.get(entry_id)
        if room is None:
            return
        room.fade_duration = duration
        _LOGGER.debug(
            "Room fade duration updated: room=%s value=%s",
            room.name,
            duration,
        )

    async def async_teardown(self) -> None:
        """Cancel all presence listeners and fade tasks and clear coordinator state."""
        listener_count = sum(len(listeners) for listeners in self._room_listeners.values())
        active_fade_count = sum(1 for task in self._fade_tasks.values() if not task.done())
        _LOGGER.debug(
            "RoamingCoordinator teardown starting: rooms=%d listeners=%d active_fades=%d",
            len(self._rooms),
            listener_count,
            active_fade_count,
        )
        for entry_id, listeners in self._room_listeners.items():
            self._cancel_listeners(entry_id, listeners)
        self._room_listeners.clear()
        _LOGGER.debug("RoamingCoordinator teardown: listeners cleared")
        for task in list(self._fade_tasks.values()):
            if not task.done():
                task.cancel()
        _LOGGER.debug("RoamingCoordinator teardown: fade tasks cancelled")
        self._fade_tasks.clear()
        self._rooms.clear()
        _LOGGER.debug("RoamingCoordinator torn down")
