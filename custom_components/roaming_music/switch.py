"""Roaming Music switch platform — master roaming-enabled switch on the global entry."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_INFO, DOMAIN, ENTRY_TYPE_GLOBAL
from .coordinator import RoamingCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
	hass: HomeAssistant,
	entry: ConfigEntry,
	async_add_entities,
) -> None:
	"""Install the master switch on the global config entry; no-op for room entries."""
	if entry.data.get("type") != ENTRY_TYPE_GLOBAL:
		return

	coordinator: RoamingCoordinator = hass.data[DOMAIN]["coordinator"]
	async_add_entities([RoamingMasterSwitch(coordinator)])

class RoamingMasterSwitch(SwitchEntity, RestoreEntity):
	"""Master switch that gates all roaming volume actions; restored on restart."""

	_attr_has_entity_name = True
	_attr_translation_key = "master_switch"
	_attr_unique_id = "roaming_music_master_switch"

	def __init__(self, coordinator: RoamingCoordinator) -> None:
		self._coordinator = coordinator
		self._is_on = True

	@property
	def device_info(self) -> DeviceInfo:
		return DeviceInfo(**DEVICE_INFO)

	@property
	def is_on(self) -> bool:
		return self._is_on

	async def async_added_to_hass(self) -> None:
		last_state = await self.async_get_last_state()
		if last_state is not None and last_state.state in ("on", "off"):
			self._is_on = last_state.state == "on"
			_LOGGER.debug("Master switch restored to state=%s", last_state.state)
		self._coordinator.set_roaming_enabled(self._is_on)
		self.async_write_ha_state()

	async def async_turn_on(self, **kwargs: Any) -> None:
		self._is_on = True
		self._coordinator.set_roaming_enabled(True)
		self.async_write_ha_state()
		_LOGGER.debug("Master switch turned on")

	async def async_turn_off(self, **kwargs: Any) -> None:
		self._is_on = False
		self._coordinator.set_roaming_enabled(False)
		self.async_write_ha_state()
		_LOGGER.debug("Master switch turned off")
