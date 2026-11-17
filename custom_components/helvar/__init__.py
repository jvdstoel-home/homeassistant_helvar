"""The HelvarNet integration."""
from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from . import aiohelvar_patches
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN
from .router import HelvarRouter

PLATFORMS = ["light", "select", "sensor", "binary_sensor"]

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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        router = hass.data[DOMAIN].pop(entry.entry_id, None)
        if router is not None:
            await router.async_close()

    return unload_ok
