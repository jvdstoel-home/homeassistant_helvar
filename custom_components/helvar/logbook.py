"""Describe Helvar events in the logbook."""
from __future__ import annotations

from homeassistant.core import callback

from .const import DOMAIN
from .helvar_events import EVENT_DEVICE_STATE, EVENT_SCENE


@callback
def async_describe_events(hass, async_describe_event):
    """Describe logbook events."""

    @callback
    def describe_scene(event):
        data = event.data
        group = data.get("group_name") or f"groep {data.get('group')}"
        message = f"scène {data.get('block')}.{data.get('scene')} gekozen"
        if data.get("scene_name"):
            message += f" ({data['scene_name']})"
        return {"name": f"Helvar {group}", "message": message}

    @callback
    def describe_state(event):
        data = event.data
        name = data.get("name") or data.get("address")
        faults = data.get("faults") or []
        message = "meldt: " + ", ".join(faults) if faults else "storing opgelost"
        return {"name": f"Helvar {name}", "message": message}

    async_describe_event(DOMAIN, EVENT_SCENE, describe_scene)
    async_describe_event(DOMAIN, EVENT_DEVICE_STATE, describe_state)
