from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

try:
    from homeassistant.components.number import NumberMode
except (ImportError, AttributeError):
    NumberMode = None

from .const import (
    CONF_DEFAULT_VOLUME,
    CONF_FADE_DURATION,
    DEFAULT_FADE_DURATION,
    DEFAULT_VOLUME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    slugify_room_name,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    if entry.data.get("type") != ENTRY_TYPE_ROOM:
        return

    room_slug = slugify_room_name(entry.title)
    async_add_entities([
        RoamingRoomVolume(entry, room_slug),
        RoamingRoomFadeDuration(entry, room_slug),
    ])

class RoamingRoomVolume(NumberEntity, RestoreEntity):

    _attr_has_entity_name = True
    _attr_translation_key = "default_volume"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1.0
    _attr_native_step = 0.01

    def __init__(self, entry: ConfigEntry, room_slug: str) -> None:
        self._entry = entry
        self._room_slug = room_slug
        self._room_name = entry.title
        self._attr_unique_id = f"roaming_music_{room_slug}_default_volume"
        self._attr_native_value: float = entry.options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)
        try:
            self._attr_mode = NumberMode.SLIDER
        except Exception:
            pass

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                self._attr_native_value = DEFAULT_VOLUME
        coordinator = self.hass.data[DOMAIN]["coordinator"]
        coordinator.update_room_default_volume(self._entry.entry_id, self._attr_native_value)
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        coordinator = self.hass.data[DOMAIN]["coordinator"]
        coordinator.update_room_default_volume(self._entry.entry_id, value)
        self.async_write_ha_state()
        _LOGGER.debug(
            "Room default volume updated: room=%s value=%s",
            self._room_name,
            value,
        )

class RoamingRoomFadeDuration(NumberEntity, RestoreEntity):

    _attr_has_entity_name = True
    _attr_translation_key = "fade_duration"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 30.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "s"

    def __init__(self, entry: ConfigEntry, room_slug: str) -> None:
        self._entry = entry
        self._room_slug = room_slug
        self._room_name = entry.title
        self._attr_unique_id = f"roaming_music_{room_slug}_fade_duration"
        self._attr_native_value: float = entry.options.get(
            CONF_FADE_DURATION, DEFAULT_FADE_DURATION
        )
        try:
            self._attr_mode = NumberMode.SLIDER
        except Exception:
            pass

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                restored = float(last_state.state)
                self._attr_native_value = max(1.0, min(30.0, restored))
            except (ValueError, TypeError):
                self._attr_native_value = DEFAULT_FADE_DURATION
        coordinator = self.hass.data[DOMAIN]["coordinator"]
        coordinator.update_room_fade_duration(
            self._entry.entry_id, self._attr_native_value
        )
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        coordinator = self.hass.data[DOMAIN]["coordinator"]
        coordinator.update_room_fade_duration(self._entry.entry_id, value)
        self.async_write_ha_state()
        _LOGGER.debug(
            "Room fade duration updated: room=%s value=%s",
            self._room_name,
            value,
        )
