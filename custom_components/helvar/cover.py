"""Helvar 490 Blinds Controller channels as covers (screens)."""
from __future__ import annotations

import logging

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .const import DOMAIN
from .device_kinds import (
    BLIND_CLOSE_LEVEL,
    BLIND_OPEN_LEVEL,
    BLIND_STOP_LEVEL,
    is_blind,
)

_LOGGER = logging.getLogger(__name__)


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

    def __init__(self, device, router) -> None:
        self.router = router
        self.device = device
        self._attr_unique_id = f"{device.address}-cover"

        async def _updated(_device):
            if self.hass is not None:
                self.async_write_ha_state()

        router.api.devices.register_subscription(device.address, _updated)

    @property
    def name(self):
        return self.device.name

    @property
    def available(self) -> bool:
        return bool(getattr(self.router.api, "connected", True))

    @property
    def is_closed(self):
        """Last known command: max = open, min = closed, off = stopped (unknown)."""
        level = self.device.load_level
        if level is None:
            return None
        level = float(level)
        if level >= BLIND_OPEN_LEVEL:
            return False
        if 0 < level <= BLIND_CLOSE_LEVEL:
            return True
        return None

    @property
    def extra_state_attributes(self):
        return {"helvar_address": str(self.device.address), "helvar_level": self.device.load_level}

    async def _send(self, level: int) -> None:
        await self.router.api.devices.set_device_load_level(
            self.device.address, str(level), 0
        )

    async def async_open_cover(self, **kwargs) -> None:
        await self._send(BLIND_OPEN_LEVEL)

    async def async_close_cover(self, **kwargs) -> None:
        await self._send(BLIND_CLOSE_LEVEL)

    async def async_stop_cover(self, **kwargs) -> None:
        await self._send(BLIND_STOP_LEVEL)
