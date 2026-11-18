"""Describe Helvar events in the logbook."""
from __future__ import annotations

from homeassistant.core import callback

from .const import DOMAIN
from .helvar_events import EVENT_CONTROL, EVENT_DEVICE_STATE, EVENT_SCENE


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

    @callback
    def describe_control(event):
        data = event.data
        if data.get("group_name") or data.get("group") is not None:
            name = data.get("group_name") or f"groep {data.get('group')}"
        else:
            name = data.get("device_name") or data.get("address") or "router"
        message = data.get("description") or f"commando {data.get('command')}"
        if data.get("level") is not None:
            message += f", niveau {data['level']} %"
        elif data.get("proportion") is not None:
            message += f", {data['proportion']} %"
        elif data.get("scene") is not None:
            message += f", scène {data.get('block')}.{data['scene']}"
        return {"name": f"Helvar {name}", "message": message}

    async_describe_event(DOMAIN, EVENT_SCENE, describe_scene)
    async_describe_event(DOMAIN, EVENT_CONTROL, describe_control)
    async_describe_event(DOMAIN, EVENT_DEVICE_STATE, describe_state)
