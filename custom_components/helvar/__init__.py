"""The HelvarNet integration."""
from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from . import aiohelvar_patches
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN
from .router import HelvarRouter

SERVICE_RECALL_SCENE = "recall_scene"
RECALL_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required("group"): vol.All(vol.Coerce(int), vol.Range(min=1, max=16383)),
        vol.Optional("block", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
        vol.Required("scene"): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
        vol.Optional("fade_time"): vol.All(vol.Coerce(float), vol.Range(min=0, max=600)),
    }
)


SERVICE_SCREENS = "screens"
SCREENS_SCHEMA = vol.Schema(
    {
        vol.Required("group"): vol.All(vol.Coerce(int), vol.Range(min=1, max=16383)),
        vol.Required("action"): vol.In(["open", "close", "stop"]),
    }
)


def _async_register_services(hass: HomeAssistant) -> None:
    """helvar.recall_scene: recall any scene of a group, also scenes without a name."""
    if hass.services.has_service(DOMAIN, SERVICE_RECALL_SCENE):
        return

    async def _recall_scene(call: ServiceCall) -> None:
        routers = list(hass.data.get(DOMAIN, {}).values())
        if not routers:
            raise HomeAssistantError("Helvar router is not loaded")
        import aiohelvar

        address = aiohelvar.SceneAddress(
            call.data["group"], call.data["block"], call.data["scene"]
        )
        kwargs = {}
        if "fade_time" in call.data:
            # HelvarNet fade time is in 1/100 s.
            kwargs["fade_time"] = int(round(call.data["fade_time"] * 100))
        await routers[0].api.groups.set_scene(address, **kwargs)

    hass.services.async_register(
        DOMAIN, SERVICE_RECALL_SCENE, _recall_scene, schema=RECALL_SCENE_SCHEMA
    )

    async def _screens(call: ServiceCall) -> None:
        routers = list(hass.data.get(DOMAIN, {}).values())
        if not routers:
            raise HomeAssistantError("Helvar router is not loaded")
        from .blinds import DOWN, UP, get_blind_state

        state = get_blind_state(routers[0].api)
        group = call.data["group"]
        action = call.data["action"]
        if action == "open":
            await state.move_group(group, UP)
        elif action == "close":
            await state.move_group(group, DOWN)
        else:
            await state.stop_group(group)

    hass.services.async_register(
        DOMAIN, SERVICE_SCREENS, _screens, schema=SCREENS_SCHEMA
    )

PLATFORMS = ["light", "cover", "switch", "select", "sensor", "binary_sensor"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up the Helvar platform."""

    hass.data.setdefault(DOMAIN, {})
    aiohelvar_patches.apply()
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HelvarNet from a config entry."""

    aiohelvar_patches.apply()
    hass.data.setdefault(DOMAIN, {})

    router = HelvarRouter(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = router

    if not await router.async_setup():
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return False

    # PATCH: forward platforms here and await them (required by current HA).
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Scene recalls and device faults as events for the logbook.
    from .helvar_events import async_setup_events

    entry.async_on_unload(await async_setup_events(hass, entry, router))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        router = hass.data[DOMAIN].pop(entry.entry_id, None)
        if router is not None:
            await router.async_close()

    return unload_ok
