"""Roaming Music config flow — global entry creation, room entries, and menu-style options flow."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEFAULT_VOLUME,
    CONF_EMPTY_ROOMS_ACTION,
    CONF_EMPTY_ROOMS_GRACE_PERIOD,
    CONF_FADE_DURATION,
    CONF_OCCUPIED_STATES,
    CONF_PAUSE_TARGET_ENTITIES,
    CONF_PAUSE_TARGET_MODE,
    CONF_PRESENCE_SENSORS,
    CONF_SPEAKERS,
    DEFAULT_EMPTY_ACTION,
    DEFAULT_EMPTY_GRACE_PERIOD,
    DEFAULT_FADE_DURATION,
    DEFAULT_PAUSE_TARGET_MODE,
    DEFAULT_VOLUME,
    DOMAIN,
    EMPTY_ACTION_MUTE,
    EMPTY_ACTIONS,
    EMPTY_GRACE_PERIOD_MAX,
    EMPTY_GRACE_PERIOD_MIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    PAUSE_TARGET_MODE_MANUAL,
    PAUSE_TARGET_MODES,
)

_LOGGER = logging.getLogger(__name__)

ROOM_STEP_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})

_EXCLUDED_STATES = frozenset({"unknown", "unavailable"})

def _is_binary_sensor(entity_id: str) -> bool:
    """Return True when ``entity_id`` belongs to the ``binary_sensor`` domain."""
    return entity_id.split(".")[0] == "binary_sensor"

def _build_multi_state_validator(known_states: list[str]) -> Any:
    """
    Build a voluptuous validator for a multi-select state field.
    :param known_states: States to constrain the selector to; empty list falls back to free-form ``str``.
    """
    if not known_states:
        return [str]
    return [vol.In(known_states)]

def _get_known_states(hass: Any, entity_id: str) -> list[str]:
    """Collect the selectable states for a sensor, excluding ``unknown``/``unavailable``."""
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


def _get_entity_display_name(hass: Any, entity_id: str) -> str:
    """Return a friendly display name for an entity, falling back to ``entity_id``."""
    state_obj = hass.states.get(entity_id)
    if state_obj is None:
        return entity_id
    friendly = state_obj.attributes.get("friendly_name")
    if isinstance(friendly, str) and friendly.strip():
        return friendly
    return entity_id


def _entity_is_available(hass: Any, entity_id: str) -> bool:
    """Return True when the entity exists and is not currently unknown/unavailable."""
    state_obj = hass.states.get(entity_id)
    if state_obj is None:
        return False
    return state_obj.state not in _EXCLUDED_STATES

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

def _build_speakers_volume_schema(
    current_speakers: list[str],
    current_default: float = DEFAULT_VOLUME,
    current_fade_duration: float = DEFAULT_FADE_DURATION,
) -> vol.Schema:
    """
    Build the voluptuous schema for the "Speakers & Volume" options sub-page.
    The ``current_*`` parameters are used as the form's pre-populated defaults.
    A selector-based schema is returned when ``ha_selector`` is available, otherwise plain types.
    """
    # Try selector-based schema first (richer UI); fall back to plain voluptuous if unavailable.
    if ha_selector is not None:
        try:
            return vol.Schema(
                {
                    vol.Optional(CONF_SPEAKERS, default=current_speakers): ha_selector.selector(
                        {"entity": {"domain": "media_player", "multiple": True}}
                    ),
                    vol.Optional(CONF_DEFAULT_VOLUME, default=current_default): ha_selector.selector(
                        {"number": {"min": 0, "max": 1, "step": 0.01, "mode": "slider"}}
                    ),
                    vol.Optional(CONF_FADE_DURATION, default=current_fade_duration): ha_selector.selector(
                        {"number": {"min": 1.0, "max": 30.0, "step": 0.5, "mode": "slider", "unit_of_measurement": "s"}}
                    ),
                }
            )
        except Exception:
            pass

    return vol.Schema(
        {
            vol.Optional(CONF_SPEAKERS, default=current_speakers): [str],
            vol.Optional(CONF_DEFAULT_VOLUME, default=current_default): vol.All(
                vol.Coerce(float),
                vol.Range(min=0.0, max=1.0),
            ),
            vol.Optional(CONF_FADE_DURATION, default=current_fade_duration): vol.All(
                vol.Coerce(float),
                vol.Range(min=1.0, max=30.0),
            ),
        }
    )


def _build_global_options_schema(
    current_action: str = DEFAULT_EMPTY_ACTION,
    current_grace_period: float | int = DEFAULT_EMPTY_GRACE_PERIOD,
    current_mode: str = DEFAULT_PAUSE_TARGET_MODE,
    current_entities: list[str] | None = None,
) -> vol.Schema:
    """
    Build the voluptuous schema for the global Roaming Music options flow.
    The ``current_*`` parameters are used as the form's pre-populated defaults.
    A selector-based schema is returned when ``ha_selector`` is available, otherwise plain types.
    """
    if current_entities is None:
        current_entities = []

    if ha_selector is not None:
        try:
            return vol.Schema(
                {
                    vol.Optional(CONF_EMPTY_ROOMS_ACTION, default=current_action): ha_selector.selector(
                        {"select": {"options": list(EMPTY_ACTIONS)}}
                    ),
                    vol.Optional(CONF_EMPTY_ROOMS_GRACE_PERIOD, default=current_grace_period): ha_selector.selector(
                        {
                            "number": {
                                "min": EMPTY_GRACE_PERIOD_MIN,
                                "max": EMPTY_GRACE_PERIOD_MAX,
                                "step": 1,
                                "mode": "box",
                                "unit_of_measurement": "s",
                            }
                        }
                    ),
                    vol.Optional(CONF_PAUSE_TARGET_MODE, default=current_mode): ha_selector.selector(
                        {"select": {"options": list(PAUSE_TARGET_MODES)}}
                    ),
                    vol.Optional(CONF_PAUSE_TARGET_ENTITIES, default=current_entities): ha_selector.selector(
                        {"entity": {"domain": "media_player", "multiple": True}}
                    ),
                }
            )
        except Exception:
            pass

    return vol.Schema(
        {
            vol.Optional(CONF_EMPTY_ROOMS_ACTION, default=current_action): vol.In(EMPTY_ACTIONS),
            vol.Optional(CONF_EMPTY_ROOMS_GRACE_PERIOD, default=current_grace_period): vol.All(
                vol.Coerce(float),
                vol.Range(min=EMPTY_GRACE_PERIOD_MIN, max=EMPTY_GRACE_PERIOD_MAX),
            ),
            vol.Optional(CONF_PAUSE_TARGET_MODE, default=current_mode): vol.In(PAUSE_TARGET_MODES),
            vol.Optional(CONF_PAUSE_TARGET_ENTITIES, default=current_entities): [str],
        }
    )


def _build_presence_sensors_schema(current_sensors: list[str]) -> vol.Schema:
    """Build the first-pass schema for the "Presence Sensors" sub-page (sensor multi-select only)."""
    if ha_selector is not None:
        try:
            return vol.Schema(
                {
                    vol.Optional(CONF_PRESENCE_SENSORS, default=current_sensors): ha_selector.selector(
                        {"entity": {"multiple": True}}
                    ),
                }
            )
        except Exception:
            pass
    return vol.Schema({vol.Optional(CONF_PRESENCE_SENSORS, default=current_sensors): [str]})


def _build_presence_sensors_with_states_schema(
    pending_sensors: list[str],
    hass: Any,
    existing_occupied: dict[str, list[str]],
) -> tuple[vol.Schema, str, dict[str, str]]:
    """
    Build the second-pass presence sensors schema — sensor multi-select plus per-sensor state mapping.
    :param pending_sensors: Sensor entity IDs chosen in the first pass; one state-mapping field is added per sensor.
    :param existing_occupied: Previously saved occupied-state mapping, keyed by entity ID.
    :return: ``(schema, no_states_warning, field_map)`` — the voluptuous schema, a user-facing warning
        string when any sensor lacked selectable states, and a mapping from form field label to entity ID.
    """
    sensors_with_no_states: list[str] = []
    schema_dict: dict[Any, Any] = {}
    field_map: dict[str, str] = {}
    used_labels: set[str] = set()

    # Sensor multi-select: use ha_selector entity picker when available
    if ha_selector is not None:
        try:
            schema_dict[vol.Optional(CONF_PRESENCE_SENSORS, default=pending_sensors)] = (
                ha_selector.selector({"entity": {"multiple": True}})
            )
        except Exception:
            schema_dict[vol.Optional(CONF_PRESENCE_SENSORS, default=pending_sensors)] = [str]
    else:
        schema_dict[vol.Optional(CONF_PRESENCE_SENSORS, default=pending_sensors)] = [str]

    # Per-sensor state mapping fields (plain voluptuous for reliable validator introspection)
    for entity_id in pending_sensors:
        base_label = _get_entity_display_name(hass, entity_id)
        field_label = base_label
        suffix = 2
        while field_label in used_labels:
            field_label = f"{base_label} ({suffix})"
            suffix += 1
        used_labels.add(field_label)
        field_map[field_label] = entity_id

        existing = existing_occupied.get(entity_id, [])
        if _is_binary_sensor(entity_id):
            binary_default = existing if existing else ["on"]
            _LOGGER.debug(
                "Building sensor state mapping field: sensor=%s type=binary",
                entity_id,
            )
            if ha_selector is not None:
                try:
                    schema_dict[vol.Optional(field_label, default=binary_default)] = ha_selector.selector(
                        {"select": {"options": ["on", "off"], "multiple": True}}
                    )
                except Exception:
                    schema_dict[vol.Optional(field_label, default=binary_default)] = _build_multi_state_validator(["on", "off"])
            else:
                schema_dict[vol.Optional(field_label, default=binary_default)] = _build_multi_state_validator(["on", "off"])
        else:
            known = _get_known_states(hass, entity_id)
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
            if ha_selector is not None and known:
                try:
                    schema_dict[vol.Optional(field_label, default=existing)] = ha_selector.selector(
                        {"select": {"options": known, "multiple": True}}
                    )
                except Exception:
                    schema_dict[vol.Optional(field_label, default=existing)] = _build_multi_state_validator(known)
            else:
                schema_dict[vol.Optional(field_label, default=existing)] = _build_multi_state_validator(known)

    no_states_warning = (
        "\n\nWarning: One or more sensors have no selectable states and will not trigger "
        "occupancy until states are known."
    ) if sensors_with_no_states else ""

    return vol.Schema(schema_dict), no_states_warning, field_map

class RoamingMusicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow that auto-creates the singleton global entry and, thereafter, per-room entries."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Entry point for user-initiated setup. The first invocation creates the singleton global entry;
        subsequent invocations forward to the room step.
        """
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
        """Collect a room name and create a room config entry."""
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
        """Return the global all-rooms-empty options flow for global entries, room options flow otherwise."""
        if config_entry.data.get("type") == ENTRY_TYPE_GLOBAL:
            return RoamingMusicGlobalOptionsFlow(config_entry)
        return RoamingMusicOptionsFlow(config_entry)

class RoamingMusicGlobalOptionsFlow(OptionsFlow):
    """Options flow for the global config entry. Configures all-rooms-empty behaviour."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render the global options form."""
        return await self.async_step_global(user_input)

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render and process the global options form (action, grace period, target mode/entities)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.get(CONF_EMPTY_ROOMS_ACTION, DEFAULT_EMPTY_ACTION)
            try:
                grace_period = float(
                    user_input.get(
                        CONF_EMPTY_ROOMS_GRACE_PERIOD, DEFAULT_EMPTY_GRACE_PERIOD
                    )
                )
            except (TypeError, ValueError):
                grace_period = float(DEFAULT_EMPTY_GRACE_PERIOD)
                errors[CONF_EMPTY_ROOMS_GRACE_PERIOD] = "grace_period_out_of_range"

            if not EMPTY_GRACE_PERIOD_MIN <= grace_period <= EMPTY_GRACE_PERIOD_MAX:
                errors[CONF_EMPTY_ROOMS_GRACE_PERIOD] = "grace_period_out_of_range"

            mode = user_input.get(CONF_PAUSE_TARGET_MODE, DEFAULT_PAUSE_TARGET_MODE)
            entities = list(user_input.get(CONF_PAUSE_TARGET_ENTITIES, []))

            # Manual entities are only required when an action that dispatches playback
            # (pause/stop) is selected; ``mute`` skips the resolver entirely.
            if (
                action != EMPTY_ACTION_MUTE
                and mode == PAUSE_TARGET_MODE_MANUAL
                and not entities
            ):
                errors[CONF_PAUSE_TARGET_ENTITIES] = "pause_target_entities_required"

            if not errors:
                _LOGGER.debug(
                    "Global options saved: action=%s grace=%s mode=%s entities=%s",
                    action,
                    grace_period,
                    mode,
                    entities,
                )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_EMPTY_ROOMS_ACTION: action,
                        CONF_EMPTY_ROOMS_GRACE_PERIOD: grace_period,
                        CONF_PAUSE_TARGET_MODE: mode,
                        CONF_PAUSE_TARGET_ENTITIES: entities,
                    },
                )

        data_schema = _build_global_options_schema(
            self._entry.options.get(CONF_EMPTY_ROOMS_ACTION, DEFAULT_EMPTY_ACTION),
            self._entry.options.get(
                CONF_EMPTY_ROOMS_GRACE_PERIOD, DEFAULT_EMPTY_GRACE_PERIOD
            ),
            self._entry.options.get(CONF_PAUSE_TARGET_MODE, DEFAULT_PAUSE_TARGET_MODE),
            list(self._entry.options.get(CONF_PAUSE_TARGET_ENTITIES, [])),
        )
        return self.async_show_form(
            step_id="global",
            data_schema=data_schema,
            errors=errors,
        )

class RoamingMusicOptionsFlow(OptionsFlow):
    """Menu-style options flow for room entries with Speakers & Volume and Presence Sensors sub-pages."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        # The "fade_curve" key is intentionally omitted — coordinator-triggered fades
        # always use logarithmic; the exposed fade_volume service still accepts a curve parameter.
        self._accumulated_options: dict[str, Any] = {
            CONF_SPEAKERS: list(config_entry.options.get(CONF_SPEAKERS, [])),
            CONF_PRESENCE_SENSORS: list(config_entry.options.get(CONF_PRESENCE_SENSORS, [])),
            CONF_OCCUPIED_STATES: dict(config_entry.options.get(CONF_OCCUPIED_STATES, {})),
            CONF_DEFAULT_VOLUME: config_entry.options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME),
            CONF_FADE_DURATION: config_entry.options.get(CONF_FADE_DURATION, DEFAULT_FADE_DURATION),
        }
        self._pending_sensors: list[str] = []
        self._show_state_mapping: bool = False
        self._menu_notice: str = ""
        self._state_field_map: dict[str, str] = {}

    def _persist_options(self) -> None:
        """Persist accumulated room options immediately without ending the flow."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=dict(self._accumulated_options),
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render the menu of options sub-pages and surface any pending save-confirmation notice."""
        notice = self._menu_notice
        self._menu_notice = ""
        return self.async_show_menu(
            step_id="init",
            menu_options=["speakers_volume", "presence_sensors"],
            description_placeholders={"save_notice": notice},
        )

    async def async_step_speakers_volume(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render and process the "Speakers & Volume" sub-page."""
        errors: dict[str, str] = {}

        if user_input is not None:
            speakers = user_input.get(CONF_SPEAKERS, [])
            try:
                default_volume = float(user_input.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME))
            except (TypeError, ValueError):
                default_volume = DEFAULT_VOLUME
                errors[CONF_DEFAULT_VOLUME] = "default_volume_out_of_range"

            try:
                fade_duration = float(user_input.get(CONF_FADE_DURATION, DEFAULT_FADE_DURATION))
            except (TypeError, ValueError):
                fade_duration = DEFAULT_FADE_DURATION
                errors[CONF_FADE_DURATION] = "fade_duration_out_of_range"

            if not 0.0 <= default_volume <= 1.0:
                errors[CONF_DEFAULT_VOLUME] = "default_volume_out_of_range"

            if not 1.0 <= fade_duration <= 30.0:
                errors[CONF_FADE_DURATION] = "fade_duration_out_of_range"

            for entity_id in speakers:
                if entity_id.split(".")[0] != "media_player":
                    errors[CONF_SPEAKERS] = "speaker_wrong_domain"
                    break
                if not _entity_is_available(self.hass, entity_id):
                    errors[CONF_SPEAKERS] = "entity_not_found"
                    break

            if not errors:
                self._accumulated_options[CONF_SPEAKERS] = speakers
                self._accumulated_options[CONF_DEFAULT_VOLUME] = default_volume
                self._accumulated_options[CONF_FADE_DURATION] = fade_duration
                _LOGGER.debug(
                    "Speakers & volume saved: room=%s speakers=%s default_volume=%s",
                    self._entry.title,
                    speakers,
                    default_volume,
                )
                self._persist_options()
                self._menu_notice = "\n\nConfiguration updated."
                return await self.async_step_init()

        data_schema = _build_speakers_volume_schema(
            self._accumulated_options.get(CONF_SPEAKERS, []),
            self._accumulated_options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME),
            self._accumulated_options.get(CONF_FADE_DURATION, DEFAULT_FADE_DURATION),
        )
        return self.async_show_form(
            step_id="speakers_volume",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_presence_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render and process the "Presence Sensors" sub-page as a two-pass form."""
        # First pass collects sensor entity IDs; second pass adds per-sensor occupied-state mapping fields
        # that are rebuilt whenever the selected sensor list changes.
        errors: dict[str, str] = {}

        if user_input is not None:
            if not self._show_state_mapping:
                # First pass: sensor selection only
                sensors = user_input.get(CONF_PRESENCE_SENSORS, [])
                for entity_id in sensors:
                    if not _entity_is_available(self.hass, entity_id):
                        errors[CONF_PRESENCE_SENSORS] = "entity_not_found"
                        break

                if not errors:
                    if not sensors:
                        # AC 6: no sensors shortcut — save empty and return to menu
                        self._accumulated_options[CONF_PRESENCE_SENSORS] = []
                        self._accumulated_options[CONF_OCCUPIED_STATES] = {}
                        self._state_field_map = {}
                        self._persist_options()
                        self._menu_notice = "\n\nConfiguration updated."
                        return await self.async_step_init()

                    # Sensors provided — set up second-pass re-render with state mapping
                    self._pending_sensors = sensors
                    self._show_state_mapping = True
                    # Fall through to render section for second-pass form
            else:
                # Second pass: sensors + state mapping fields submitted
                submitted_sensors = list(
                    user_input.get(CONF_PRESENCE_SENSORS, self._pending_sensors)
                )

                if not errors and not submitted_sensors:
                    self._accumulated_options[CONF_PRESENCE_SENSORS] = []
                    self._accumulated_options[CONF_OCCUPIED_STATES] = {}
                    self._pending_sensors = []
                    self._show_state_mapping = False
                    self._state_field_map = {}
                    self._persist_options()
                    self._menu_notice = "\n\nConfiguration updated."
                    return await self.async_step_init()

                sensors_changed = submitted_sensors != self._pending_sensors

                if not errors and sensors_changed:
                    # Re-render with the newly selected sensors to keep inline mapping in sync.
                    self._pending_sensors = submitted_sensors

                if errors or sensors_changed:
                    existing_occupied: dict[str, list[str]] = self._accumulated_options.get(
                        CONF_OCCUPIED_STATES, {}
                    )
                    data_schema, no_states_warning, field_map = _build_presence_sensors_with_states_schema(
                        self._pending_sensors, self.hass, existing_occupied
                    )
                    self._state_field_map = field_map
                    return self.async_show_form(
                        step_id="presence_sensors",
                        data_schema=data_schema,
                        errors=errors,
                        description_placeholders={"no_states_warning": no_states_warning},
                    )

                if not self._state_field_map:
                    existing_occupied: dict[str, list[str]] = self._accumulated_options.get(
                        CONF_OCCUPIED_STATES, {}
                    )
                    _, _, field_map = _build_presence_sensors_with_states_schema(
                        self._pending_sensors, self.hass, existing_occupied
                    )
                    self._state_field_map = field_map

                occupied_states: dict[str, list[str]] = {}
                for field_key, entity_id in self._state_field_map.items():
                    raw_val = user_input.get(field_key, [])
                    if isinstance(raw_val, str):
                        occupied_states[entity_id] = [raw_val]
                    else:
                        occupied_states[entity_id] = list(raw_val)

                _LOGGER.debug(
                    "Room presence sensors saved: room=%s sensors=%s occupied_states=%s",
                    self._entry.title,
                    self._pending_sensors,
                    occupied_states,
                )
                self._accumulated_options[CONF_PRESENCE_SENSORS] = self._pending_sensors
                self._accumulated_options[CONF_OCCUPIED_STATES] = occupied_states
                self._show_state_mapping = False
                self._pending_sensors = []
                self._state_field_map = {}
                self._persist_options()
                self._menu_notice = "\n\nConfiguration updated."
                return await self.async_step_init()

        # Render section
        if not self._show_state_mapping:
            # First render or error re-render: sensor multi-select only
            data_schema = _build_presence_sensors_schema(
                self._accumulated_options.get(CONF_PRESENCE_SENSORS, [])
            )
            return self.async_show_form(
                step_id="presence_sensors",
                data_schema=data_schema,
                errors=errors,
                description_placeholders={"no_states_warning": ""},
            )

        # Second-pass render: include inline state mapping fields
        existing_occupied: dict[str, list[str]] = self._accumulated_options.get(
            CONF_OCCUPIED_STATES, {}
        )
        data_schema, no_states_warning, field_map = _build_presence_sensors_with_states_schema(
            self._pending_sensors, self.hass, existing_occupied
        )
        self._state_field_map = field_map
        return self.async_show_form(
            step_id="presence_sensors",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"no_states_warning": no_states_warning},
        )
