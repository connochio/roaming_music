"""Roaming Music integration — setup/teardown for the global and per-room config entries."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from . import fade_engine
from .const import (
    CONF_EMPTY_ROOMS_ACTION,
    CONF_EMPTY_ROOMS_GRACE_PERIOD,
    CONF_PAUSE_TARGET_MODE,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    FADE_CURVE_LOGARITHMIC,
    FADE_CURVES,
    FADE_TIMEOUT_BUFFER,
)
from .coordinator import RoamingCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: tuple[str, ...] = ("switch", "sensor")

_FADE_VOLUME_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required("target_volume"): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        vol.Required("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional("curve", default=FADE_CURVE_LOGARITHMIC): vol.In(FADE_CURVES),
    }
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up a Roaming Music config entry. ``entry.data["type"]`` selects the global vs. room branch.
    Returns True on successful setup, False when a room entry cannot find its global coordinator.
    """
    entry_type = entry.data.get("type")

    if entry_type == ENTRY_TYPE_GLOBAL:
        coordinator = RoamingCoordinator(hass)
        hass.data.setdefault(DOMAIN, {})["coordinator"] = coordinator
        coordinator.set_global_options(dict(entry.options))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.debug(
            "Roaming Music global entry setup complete: type=%s title=%s entry_id=%s",
            entry_type,
            entry.title,
            entry.entry_id,
        )

        async def _async_global_options_updated(
            hass: HomeAssistant, updated_entry: ConfigEntry
        ) -> None:
            coord = hass.data.get(DOMAIN, {}).get("coordinator")
            if coord is not None:
                coord.set_global_options(dict(updated_entry.options))
                _LOGGER.debug(
                    "Global options updated: action=%s grace=%s mode=%s",
                    updated_entry.options.get(CONF_EMPTY_ROOMS_ACTION),
                    updated_entry.options.get(CONF_EMPTY_ROOMS_GRACE_PERIOD),
                    updated_entry.options.get(CONF_PAUSE_TARGET_MODE),
                )

        entry.async_on_unload(entry.add_update_listener(_async_global_options_updated))

        async def svc_fade_volume(call: ServiceCall) -> None:
            # Service handler wraps fade_engine.fade_volume in a timeout-bounded background task so
            # the caller's service call returns immediately and a stuck fade can't hold the loop.
            entity_ids: list[str] = call.data["entity_id"]
            target_volume: float = float(call.data["target_volume"])
            duration: float = float(call.data["duration"])
            curve: str = call.data.get("curve", FADE_CURVE_LOGARITHMIC)
            fade_timeout = duration + FADE_TIMEOUT_BUFFER

            _LOGGER.debug(
                "fade_volume service call received: entity_ids=%s target=%.2f duration=%.1f curve=%s",
                entity_ids,
                target_volume,
                duration,
                curve,
            )

            async def _run_service_fade() -> None:
                try:
                    await asyncio.wait_for(
                        fade_engine.fade_volume(
                            hass,
                            entity_ids,
                            target_volume,
                            duration,
                            curve,
                        ),
                        timeout=fade_timeout,
                    )
                    _LOGGER.debug(
                        "fade_volume service completed: entity_ids=%s target=%.2f",
                        entity_ids,
                        target_volume,
                    )
                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        "fade_volume service timed out: entity_ids=%s duration=%.1f timeout=%.1f",
                        entity_ids,
                        duration,
                        fade_timeout,
                    )

            hass.async_create_task(_run_service_fade())
            _LOGGER.debug(
                "fade_volume service task dispatched: entity_ids=%s",
                entity_ids,
            )

        hass.services.async_register(DOMAIN, "fade_volume", svc_fade_volume, schema=_FADE_VOLUME_SCHEMA)
        entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "fade_volume"))

    elif entry_type == ENTRY_TYPE_ROOM:
        coordinator = hass.data.get(DOMAIN, {}).get("coordinator")
        if coordinator is None:
            _LOGGER.warning(
                "Room entry setup failed — coordinator not found: "
                "ensure global entry is loaded first: %s",
                entry.entry_id,
            )
            return False
        coordinator.register_room(entry)

        async def _async_options_updated(
            hass: HomeAssistant, updated_entry: ConfigEntry
        ) -> None:
            coord = hass.data.get(DOMAIN, {}).get("coordinator")
            if coord is not None:
                coord.register_room(updated_entry)
                _LOGGER.debug(
                    "Room re-registered after options update: %s (entry_id=%s)",
                    updated_entry.title,
                    updated_entry.entry_id,
                )

        entry.async_on_unload(entry.add_update_listener(_async_options_updated))

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Roaming Music",
            model="Room",
        )
        await hass.config_entries.async_forward_entry_setups(entry, ["number"])
        _LOGGER.debug(
            "Room entry setup complete: %s (entry_id=%s)",
            entry.title,
            entry.entry_id,
        )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a Roaming Music config entry — tears down the coordinator for global entries and
    unregisters the room for room entries. Returns False if a platform unload fails.
    """
    entry_type = entry.data.get("type")

    if entry_type == ENTRY_TYPE_GLOBAL:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            return False

        coordinator: RoamingCoordinator | None = hass.data.get(DOMAIN, {}).pop(
            "coordinator", None
        )
        if coordinator is not None:
            await coordinator.async_teardown()
        _LOGGER.debug(
            "Roaming Music global entry unload complete: type=%s title=%s entry_id=%s",
            entry_type,
            entry.title,
            entry.entry_id,
        )

    elif entry_type == ENTRY_TYPE_ROOM:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, ["number"])
        if not unload_ok:
            return False
        coordinator: RoamingCoordinator | None = hass.data.get(DOMAIN, {}).get("coordinator")
        if coordinator is not None:
            coordinator.unregister_room(entry.entry_id)
        _LOGGER.debug(
            "Room entry unload complete: %s (entry_id=%s)",
            entry.title,
            entry.entry_id,
        )

    return True
