"""Helvar events for Home Assistant's logbook.

- helvar_scene_recalled: every scene recall the router reports (wall switch,
  schedule, sequence or Home Assistant itself).
- helvar_device_state: a lamp/device reports a fault, or a fault is cleared.
  Device states are polled every 5 minutes over the main session.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

EVENT_SCENE = "helvar_scene_recalled"
EVENT_DEVICE_STATE = "helvar_device_state"
EVENT_CONTROL = "helvar_control"
STATE_POLL_INTERVAL = timedelta(minutes=5)

# HelvarNet device state flags (C:110), Dutch text for the logbook.
STATE_FLAGS = {
    0x00000001: "uitgeschakeld",
    0x00000002: "lamp defect",
    0x00000004: "ontbreekt",
    0x00000008: "storing",
    0x00000010: "wordt opnieuw gezocht",
    0x00000100: "noodverlichting rust",
    0x00000400: "noodverlichting actief (geen netspanning)",
    0x00000800: "noodverlichting verlengd",
    0x00001000: "noodverlichting functietest bezig",
    0x00002000: "noodverlichting duurtest bezig",
    0x00010000: "duurtest gepland",
    0x00020000: "functietest gepland",
    0x00040000: "accu noodverlichting defect",
    0x00200000: "noodverlichting geblokkeerd",
    0x00400000: "functietest aangevraagd",
    0x00800000: "duurtest aangevraagd",
    0x01000000: "noodverlichting status onbekend",
    0x02000000: "te warm",
    0x04000000: "te hoge stroom",
    0x08000000: "communicatiefout",
    0x10000000: "ernstige storing",
    0x20000000: "ongeldig antwoord",
    0x80000000: "verkeerd type apparaat",
}


def describe_state(flags: int) -> list[str]:
    """Readable list of the faults in a device state value."""
    return [text for bit, text in STATE_FLAGS.items() if flags & bit]


def _scene_name(router, scene_address) -> str | None:
    scene = router.scenes.get_scene(scene_address)
    name = getattr(scene, "name", None)
    return name or None


async def async_setup_events(hass: HomeAssistant, entry, helvar_router):
    """Start firing Helvar events. Returns a function that stops it."""
    from aiohelvar.parser.command import Command
    from aiohelvar.parser.command_type import CommandType, MessageType

    api = helvar_router.api

    @callback
    def on_scene_recall(scene_address, fade_time) -> None:
        group = api.groups.groups.get(scene_address.group)
        hass.bus.async_fire(
            EVENT_SCENE,
            {
                "group": scene_address.group,
                "group_name": getattr(group, "name", None),
                "block": scene_address.block,
                "scene": scene_address.scene,
                "scene_name": _scene_name(api, scene_address),
                "fade_time": fade_time,
            },
        )

    listeners = getattr(api, "_scene_listeners", None)
    if listeners is None:
        listeners = api._scene_listeners = []
    listeners.append(on_scene_recall)

    @callback
    def on_control(cmd, description, params, address) -> None:
        group_id = params.get("G")
        group = None
        if group_id is not None:
            try:
                group = api.groups.groups.get(int(group_id))
            except ValueError:
                group = None
        device = None
        if address:
            device = next(
                (d for a, d in api.devices.devices.items() if str(a) == f"@{address}"),
                None,
            )
        hass.bus.async_fire(
            EVENT_CONTROL,
            {
                "command": cmd,
                "description": description,
                "group": int(group_id) if group_id and group_id.isdigit() else None,
                "group_name": getattr(group, "name", None),
                "address": address,
                "device_name": getattr(device, "name", None),
                "level": params.get("L"),
                "proportion": params.get("P"),
                "scene": params.get("S"),
                "block": params.get("B"),
                "fade_time": params.get("F"),
            },
        )

    control_listeners = getattr(api, "_control_listeners", None)
    if control_listeners is None:
        control_listeners = api._control_listeners = []
    control_listeners.append(on_control)

    last_state: dict[str, int] = {}

    async def poll_states(_now=None) -> None:
        if not api.connected:
            return
        for address, device in list(api.devices.devices.items()):
            if not device.is_load:
                continue
            try:
                response = await api._send_command_task(
                    Command(CommandType.QUERY_DEVICE_STATE, command_address=address)
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("State query for %s failed: %r", address, err)
                continue
            if response is None or response.command_message_type != MessageType.REPLY:
                continue
            try:
                flags = int(response.result)
            except (TypeError, ValueError):
                continue
            key = str(address)
            previous = last_state.get(key)
            last_state[key] = flags
            if previous == flags or (previous is None and flags == 0):
                continue
            hass.bus.async_fire(
                EVENT_DEVICE_STATE,
                {
                    "address": key,
                    "name": device.name,
                    "state": flags,
                    "faults": describe_state(flags),
                    "previous_state": previous,
                },
            )

    unsub_timer = async_track_time_interval(hass, poll_states, STATE_POLL_INTERVAL)
    hass.async_create_background_task(poll_states(), "helvar_initial_state_poll")

    def stop() -> None:
        unsub_timer()
        if on_scene_recall in listeners:
            listeners.remove(on_scene_recall)
        if on_control in control_listeners:
            control_listeners.remove(on_control)

    return stop
