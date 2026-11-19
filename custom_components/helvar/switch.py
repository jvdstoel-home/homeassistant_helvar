"""Virtual Helvar on/off devices (e.g. "V: Status Weerstation") as switches."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .device_kinds import is_virtual_switch


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Helvar virtual switches."""
    router = hass.data[DOMAIN][entry.entry_id]

    async def _add():
        router = hass.data[DOMAIN][entry.entry_id]
        async_add_entities(
            HelvarSwitch(device, router)
            for device in router.api.devices.devices.values()
            if is_virtual_switch(device)
        )

    router.async_when_ready(_add)


class HelvarSwitch(SwitchEntity):
    """A virtual Helvar device used as an on/off status."""

    def __init__(self, device, router) -> None:
        self.router = router
        self.device = device
        self._attr_unique_id = f"{device.address}-switch"

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
    def is_on(self):
        level = self.device.load_level
        return None if level is None else float(level) > 0

    @property
    def extra_state_attributes(self):
        return {"helvar_address": str(self.device.address), "helvar_level": self.device.load_level}

    async def async_turn_on(self, **kwargs) -> None:
        await self.router.api.devices.set_device_load_level(self.device.address, "100", 0)

    async def async_turn_off(self, **kwargs) -> None:
        await self.router.api.devices.set_device_load_level(self.device.address, "0", 0)
