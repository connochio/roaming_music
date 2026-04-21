"""Roaming Music constants — config keys, fade curve options, defaults, device info."""

from __future__ import annotations

import re
import unicodedata

DOMAIN = "roaming_music"

# Entry type constants
ENTRY_TYPE_GLOBAL = "global"
ENTRY_TYPE_ROOM = "room"

# Config key constants
CONF_SPEAKERS = "speakers"
CONF_PRESENCE_SENSORS = "presence_sensors"
CONF_OCCUPIED_STATES = "occupied_states"
CONF_DEFAULT_VOLUME = "default_volume"
CONF_FADE_DURATION = "fade_duration"
CONF_FADE_CURVE = "fade_curve"

# Sensor state value constants
ROAMING_STATE_IDLE = "idle"
ROAMING_STATE_ACTIVE = "active"
ROAMING_STATE_FADING = "fading"
ROAMING_STATE_ERROR = "error"

# Dispatcher signal
SIGNAL_STATE_CHANGED = f"{DOMAIN}_state_changed"

# Fade curve options
FADE_CURVE_LOGARITHMIC = "logarithmic"
FADE_CURVE_BEZIER = "bezier"
FADE_CURVE_LINEAR = "linear"
FADE_CURVES = (FADE_CURVE_LOGARITHMIC, FADE_CURVE_BEZIER, FADE_CURVE_LINEAR)

# Defaults
DEFAULT_FADE_DURATION = 2.0
DEFAULT_FADE_CURVE = FADE_CURVE_LOGARITHMIC
DEFAULT_VOLUME = 0.2
FADE_TIMEOUT_BUFFER = 30.0
VOLUME_SET_CALL_TIMEOUT = 10.0

# Device info
DEVICE_INFO = {
    "identifiers": {(DOMAIN, "roaming_music_global")},
    "name": "Roaming Music",
    "manufacturer": "Roaming Music",
    "model": "Integration",
}

def slugify_room_name(name: str) -> str:
    """
    Produce an ASCII slug suitable for unique_id construction from a user-provided room name.
    Returns ``"room"`` when the input slugifies to an empty string.
    """
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")
    return slug or "room"
