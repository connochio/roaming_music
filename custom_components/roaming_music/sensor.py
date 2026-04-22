"""Roaming Music sensor platform — global-entry roaming state and active-room-count sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .const import DEVICE_INFO, DOMAIN, ENTRY_TYPE_GLOBAL, SIGNAL_STATE_CHANGED
from .coordinator import RoamingCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Install the global-entry diagnostic sensors; no-op for room entries."""
    if entry.data.get("type") != ENTRY_TYPE_GLOBAL:
        return

    coordinator: RoamingCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([
        RoamingStateSensor(coordinator),
        ActiveRoomsSensor(coordinator),
        ActiveSpeakerCountSensor(coordinator),
    ])

class RoamingStateSensor(SensorEntity):
    """Aggregate roaming state sensor — mirrors :attr:`RoamingCoordinator.roaming_state`."""

    _attr_has_entity_name = True
    _attr_translation_key = "roaming_state"
    _attr_unique_id = "roaming_music_roaming_state"

    def __init__(self, coordinator: RoamingCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_native_value = coordinator.roaming_state

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**DEVICE_INFO)

    async def async_added_to_hass(self) -> None:
        unsub = async_dispatcher_connect(
            self.hass, SIGNAL_STATE_CHANGED, self._handle_state_update
        )
        self.async_on_remove(unsub)

    @callback
    def _handle_state_update(self) -> None:
        self._attr_native_value = self._coordinator.roaming_state
        self.async_write_ha_state()
        _LOGGER.debug("RoamingStateSensor updated: state=%s", self._attr_native_value)

class ActiveRoomsSensor(SensorEntity):
    """Count of currently-occupied rooms, with the room list and per-room errors in attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_rooms"
    _attr_unique_id = "roaming_music_active_rooms"

    def __init__(self, coordinator: RoamingCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_native_value = len(coordinator.active_room_names)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**DEVICE_INFO)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "room_list": self._coordinator.active_room_names,
            "last_errors": self._coordinator.per_room_errors,
        }

    async def async_added_to_hass(self) -> None:
        unsub = async_dispatcher_connect(
            self.hass, SIGNAL_STATE_CHANGED, self._handle_state_update
        )
        self.async_on_remove(unsub)

    @callback
    def _handle_state_update(self) -> None:
        self._attr_native_value = len(self._coordinator.active_room_names)
        self.async_write_ha_state()
        _LOGGER.debug(
            "ActiveRoomsSensor updated: count=%s rooms=%s",
            self._attr_native_value,
            self._coordinator.active_room_names,
        )


class ActiveSpeakerCountSensor(SensorEntity):
    """Count of configured speakers across currently-occupied rooms."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_speakers"
    _attr_unique_id = "roaming_music_active_speakers"
    _attr_native_unit_of_measurement = "speakers"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RoamingCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_native_value = coordinator.active_speaker_count

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**DEVICE_INFO)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "per_room": self._coordinator.per_room_speaker_counts,
            "roaming_enabled": self._coordinator.roaming_enabled,
        }

    async def async_added_to_hass(self) -> None:
        unsub = async_dispatcher_connect(
            self.hass, SIGNAL_STATE_CHANGED, self._handle_state_update
        )
        self.async_on_remove(unsub)

    @callback
    def _handle_state_update(self) -> None:
        count = self._coordinator.active_speaker_count
        self._attr_native_value = count
        self.async_write_ha_state()
        _LOGGER.debug(
            "ActiveSpeakerCountSensor updated: count=%s per_room=%s",
            count,
            self._coordinator.per_room_speaker_counts,
        )
