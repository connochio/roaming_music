from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEFAULT_VOLUME,
    CONF_FADE_CURVE,
    CONF_FADE_DURATION,
    CONF_OCCUPIED_STATES,
    CONF_PRESENCE_SENSORS,
    CONF_SPEAKERS,
    DEFAULT_FADE_CURVE,
    DEFAULT_FADE_DURATION,
    DEFAULT_VOLUME,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    FADE_CURVES,
)

_LOGGER = logging.getLogger(__name__)

ROOM_STEP_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})

_EXCLUDED_STATES = frozenset({"unknown", "unavailable"})

def _is_binary_sensor(entity_id: str) -> bool:
    return entity_id.split(".")[0] == "binary_sensor"

def _build_multi_state_validator(known_states: list[str]) -> Any:
    if not known_states:
        return [str]
    return [vol.In(known_states)]

def _get_known_states(hass: Any, entity_id: str) -> list[str]:
    state_obj = hass.states.get(entity_id)
    if state_obj is None:
        return []
    raw: list[str] = [state_obj.state] + list(state_obj.attributes.get("options", []))
    seen: set[str] = set()
    result: list[str] = []
    for s in raw:
        if s not in _EXCLUDED_STATES and s not in seen:
            seen.add(s)
            result.append(s)
    return result

OPTIONS_STEP_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SPEAKERS, default=[]): [str],
        vol.Optional(CONF_PRESENCE_SENSORS, default=[]): [str],
    }
)
GLOBAL_ENTRY_TITLE = "Roaming Music"

try:
    from homeassistant.helpers import selector as ha_selector
except ImportError:
    ha_selector = None

def _build_options_step_schema(
    current_speakers: list[str],
    current_sensors: list[str],
    current_default: float = DEFAULT_VOLUME,
    current_fade_duration: float = DEFAULT_FADE_DURATION,
    current_fade_curve: str = DEFAULT_FADE_CURVE,
) -> vol.Schema:
    if ha_selector is not None:
        try:
            return vol.Schema(
                {
                    vol.Optional(CONF_SPEAKERS, default=current_speakers): ha_selector.selector(
                        {
                            "entity": {
                                "domain": "media_player",
                                "multiple": True,
                            }
                        }
                    ),
                    vol.Optional(CONF_PRESENCE_SENSORS, default=current_sensors): ha_selector.selector(
                        {
                            "entity": {
                                "multiple": True,
                            }
                        }
                    ),
                    vol.Optional(CONF_DEFAULT_VOLUME, default=current_default): ha_selector.selector(
                        {
                            "number": {
                                "min": 0,
                                "max": 1,
                                "step": 0.01,
                                "mode": "slider",
                            }
                        }
                    ),
                    vol.Optional(CONF_FADE_DURATION, default=current_fade_duration): ha_selector.selector(
                        {"number": {"min": 1.0, "max": 30.0, "step": 0.5, "mode": "slider", "unit_of_measurement": "s"}}
                    ),
                    vol.Optional(CONF_FADE_CURVE, default=current_fade_curve): ha_selector.selector(
                        {"select": {"options": list(FADE_CURVES)}}
                    ),
                }
            )
        except Exception:
            pass

    return vol.Schema(
        {
            vol.Optional(CONF_SPEAKERS, default=current_speakers): [str],
            vol.Optional(CONF_PRESENCE_SENSORS, default=current_sensors): [str],
            vol.Optional(CONF_DEFAULT_VOLUME, default=current_default): vol.All(
                vol.Coerce(float),
                vol.Range(min=0.0, max=1.0),
            ),
            vol.Optional(CONF_FADE_DURATION, default=current_fade_duration): vol.All(
                vol.Coerce(float),
                vol.Range(min=1.0, max=30.0),
            ),
            vol.Optional(CONF_FADE_CURVE, default=current_fade_curve): vol.In(FADE_CURVES),
        }
    )

class RoamingMusicConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        existing = self._async_current_entries()
        global_exists = any(
            entry.data.get("type") == ENTRY_TYPE_GLOBAL for entry in existing
        )

        if not global_exists:
            _LOGGER.debug(
                "Creating global config entry (title: %s)",
                GLOBAL_ENTRY_TITLE,
            )
            return self.async_create_entry(
                title=GLOBAL_ENTRY_TITLE,
                data={"type": ENTRY_TYPE_GLOBAL},
            )

        return await self.async_step_room()

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_room_name = user_input.get(CONF_NAME, "")
            room_name = raw_room_name.strip() if isinstance(raw_room_name, str) else ""
            existing_names = [
                e.title
                for e in self._async_current_entries()
                if e.data.get("type") == ENTRY_TYPE_ROOM
            ]
            if not room_name:
                errors[CONF_NAME] = "name_empty"
            elif room_name == GLOBAL_ENTRY_TITLE:
                errors[CONF_NAME] = "name_reserved"
            elif room_name in existing_names:
                errors[CONF_NAME] = "name_already_in_use"
            else:
                _LOGGER.debug("Creating room config entry: name=%s", room_name)
                return self.async_create_entry(
                    title=room_name,
                    data={"type": ENTRY_TYPE_ROOM, "name": room_name},
                )

        return self.async_show_form(
            step_id="room",
            data_schema=ROOM_STEP_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        if config_entry.data.get("type") == ENTRY_TYPE_GLOBAL:
            return _GlobalNoOpOptionsFlow(config_entry)
        return RoamingMusicOptionsFlow(config_entry)

class _GlobalNoOpOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_abort(reason="global_no_options")

class RoamingMusicOptionsFlow(OptionsFlow):

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._pending_speakers: list[str] = []
        self._pending_sensors: list[str] = []
        self._pending_default_volume: float = DEFAULT_VOLUME
        self._pending_fade_duration: float = DEFAULT_FADE_DURATION
        self._pending_fade_curve: str = DEFAULT_FADE_CURVE

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            speakers = user_input.get(CONF_SPEAKERS, [])
            sensors = user_input.get(CONF_PRESENCE_SENSORS, [])
            default_volume = float(user_input.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME))
            fade_duration = float(user_input.get(CONF_FADE_DURATION, DEFAULT_FADE_DURATION))
            fade_curve = str(user_input.get(CONF_FADE_CURVE, DEFAULT_FADE_CURVE))
            self._pending_fade_duration = fade_duration
            self._pending_fade_curve = fade_curve

            if not 0.0 <= default_volume <= 1.0:
                errors[CONF_DEFAULT_VOLUME] = "default_volume_out_of_range"

            for entity_id in speakers:
                if entity_id.split(".")[0] != "media_player":
                    errors[CONF_SPEAKERS] = "speaker_wrong_domain"
                    break
                if self.hass.states.get(entity_id) is None:
                    errors[CONF_SPEAKERS] = "entity_not_found"
                    break

            for entity_id in sensors:
                if self.hass.states.get(entity_id) is None:
                    errors[CONF_PRESENCE_SENSORS] = "entity_not_found"
                    break

            if not errors:
                if not sensors:
                    _LOGGER.debug(
                        "Room options saved (no sensors): room=%s speakers=%s",
                        self._entry.title,
                        speakers,
                    )
                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_SPEAKERS: speakers,
                            CONF_PRESENCE_SENSORS: [],
                            CONF_OCCUPIED_STATES: {},
                            CONF_DEFAULT_VOLUME: default_volume,
                            CONF_FADE_DURATION: fade_duration,
                            CONF_FADE_CURVE: fade_curve,
                        },
                    )
                self._pending_speakers = speakers
                self._pending_sensors = sensors
                self._pending_default_volume = default_volume
                return await self.async_step_sensor_states()

        current_speakers = self._entry.options.get(CONF_SPEAKERS, [])
        current_sensors = self._entry.options.get(CONF_PRESENCE_SENSORS, [])
        current_default = self._entry.options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)
        current_fade_duration = self._entry.options.get(CONF_FADE_DURATION, DEFAULT_FADE_DURATION)
        current_fade_curve = self._entry.options.get(CONF_FADE_CURVE, DEFAULT_FADE_CURVE)
        data_schema = _build_options_step_schema(current_speakers, current_sensors, current_default, current_fade_duration, current_fade_curve)

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_sensor_states(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            occupied_states: dict[str, list[str]] = {}
            for entity_id in self._pending_sensors:
                if _is_binary_sensor(entity_id):
                    val = user_input.get(entity_id, "on")
                    occupied_states[entity_id] = [val] if isinstance(val, str) else list(val)
                else:
                    occupied_states[entity_id] = list(user_input.get(entity_id, []))

            _LOGGER.debug(
                "Room state mapping saved: room=%s occupied_states=%s",
                self._entry.title,
                occupied_states,
            )
            return self.async_create_entry(
                title="",
                data={
                    CONF_SPEAKERS: self._pending_speakers,
                    CONF_PRESENCE_SENSORS: self._pending_sensors,
                    CONF_OCCUPIED_STATES: occupied_states,
                    CONF_DEFAULT_VOLUME: self._pending_default_volume,
                    CONF_FADE_DURATION: self._pending_fade_duration,
                    CONF_FADE_CURVE: self._pending_fade_curve,
                },
            )

        existing_occupied: dict[str, list[str]] = self._entry.options.get(CONF_OCCUPIED_STATES, {})
        schema_dict: dict[Any, Any] = {}
        sensors_with_no_states: list[str] = []
        for entity_id in self._pending_sensors:
            existing = existing_occupied.get(entity_id, [])
            if _is_binary_sensor(entity_id):
                _LOGGER.debug(
                    "Building sensor state mapping field: sensor=%s type=binary",
                    entity_id,
                )
                default_val = existing[0] if existing else "on"
                schema_dict[vol.Optional(entity_id, default=default_val)] = vol.In(["on", "off"])
            else:
                known = _get_known_states(self.hass, entity_id)
                _LOGGER.debug(
                    "Building sensor state mapping field: sensor=%s type=non_binary known_states=%s",
                    entity_id,
                    known,
                )
                if not known:
                    _LOGGER.warning(
                        "Sensor %s has no selectable states for state mapping",
                        entity_id,
                    )
                    sensors_with_no_states.append(entity_id)
                schema_dict[vol.Optional(entity_id, default=existing)] = _build_multi_state_validator(known)

        no_states_warning = ""
        if sensors_with_no_states:
            no_states_warning = (
                "\n\n"
                "Warning: One or more sensors have no selectable states and will not trigger "
                "occupancy until states are known."
            )

        return self.async_show_form(
            step_id="sensor_states",
            data_schema=vol.Schema(schema_dict),
            errors={},
            description_placeholders={"no_states_warning": no_states_warning},
        )
