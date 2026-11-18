"""Helvar 490 Blinds Controller channels as covers (screens).

Commands follow the button panels (see blinds.py): C:18 per channel with
P:-1 = up, P:0 = down, stop = the opposite direction while still running.
The position cannot be read, so the state is the last commanded direction.
"""
from __future__ import annotations

import logging
import time

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .blinds import DOWN, RUN_TIME, STOPPED, UP, get_blind_state
from .const import DOMAIN
from .device_kinds import is_blind

_LOGGER = logging.getLogger(__name__)

# Display names where the Designer name is misleading.
NAME_OVERRIDES = {
    "@1.7.1.36": "Screen zuid ouders/badkamer",
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Helvar screens."""
    router = hass.data[DOMAIN][entry.entry_id]
    covers = [
        HelvarCover(device, router)
        for device in router.api.devices.devices.values()
        if is_blind(device)
    ]
    _LOGGER.info("Adding %s helvar screens", len(covers))
    async_add_entities(covers)


class HelvarCover(CoverEntity):
    """One channel of a 490 Blinds Controller."""

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_assumed_state = True

    def __init__(self, device, router) -> None:
        self.router = router
        self.device = device
        self._address = str(device.address)
        self._attr_unique_id = f"{device.address}-cover"
        self._blinds = get_blind_state(router.api)
        self._unsub_timer = None

    async def async_added_to_hass(self) -> None:
        self._blinds.listeners.append(self._on_change)

    async def async_will_remove_from_hass(self) -> None:
        if self._on_change in self._blinds.listeners:
            self._blinds.listeners.remove(self._on_change)
        if self._unsub_timer:
            self._unsub_timer()

    @callback
    def _on_change(self) -> None:
        if self.hass is None:
            return
        self.async_write_ha_state()
        # Re-render when the run time is over (opening/closing -> open/closed).
        if self._unsub_timer:
            self._unsub_timer()
        self._unsub_timer = async_call_later(self.hass, RUN_TIME + 1, self._timer_done)

    @callback
    def _timer_done(self, _now) -> None:
        self._unsub_timer = None
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def name(self):
        return NAME_OVERRIDES.get(self._address, self.device.name)

    @property
    def available(self) -> bool:
        return bool(getattr(self.router.api, "connected", True))

    def _last(self):
        return self._blinds.device_state(self._address)

    def _running(self) -> bool:
        last = self._last()
        return bool(last) and last[0] != STOPPED and time.monotonic() - last[1] < RUN_TIME

    @property
    def is_closed(self):
        last = self._last()
        if not last or last[0] == STOPPED:
            return None
        return last[0] == DOWN

    @property
    def is_closing(self) -> bool:
        return self._running() and self._last()[0] == DOWN

    @property
    def is_opening(self) -> bool:
        return self._running() and self._last()[0] == UP

    def _scene_levels(self) -> dict:
        """Levels this channel has in its scene table (blocks 1-8), '*' (ignore) left out."""
        levels = list(getattr(self.device, "levels", None) or [])
        result = {}
        for block in range(1, 9):
            for scene in range(1, 17):
                index = (block - 1) * 16 + scene - 1
                if index < len(levels) and str(levels[index]) not in ("*", "", "None"):
                    result[f"{block}.{scene}"] = levels[index]
        return result

    @property
    def extra_state_attributes(self):
        last = self._last()
        return {
            "helvar_address": self._address,
            "helvar_name": self.device.name,
            "last_command": last[0] if last else None,
            "scene_levels": self._scene_levels(),
            "scene_levels_raw_count": len(getattr(self.device, "levels", None) or []),
        }

    async def async_open_cover(self, **kwargs) -> None:
        await self._blinds.move_device(self._address, UP)

    async def async_close_cover(self, **kwargs) -> None:
        await self._blinds.move_device(self._address, DOWN)

    async def async_stop_cover(self, **kwargs) -> None:
        await self._blinds.stop_device(self._address)
