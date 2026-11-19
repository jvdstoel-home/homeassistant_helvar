"""Rain detection from the Helvar 942 analogue input."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helvar_inputs import AnalogueInput, async_get_coordinators, convert
from .sensor import weather_device_info


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the rain sensor."""
    router = hass.data[DOMAIN][entry.entry_id]

    async def _add():
        coordinators = await async_get_coordinators(hass, entry, {"rain"})
        async_add_entities(
            HelvarRainSensor(coordinator, entry, item)
            for coordinator in coordinators
            for item in coordinator.inputs
        )

    router.async_when_ready(_add)


class HelvarRainSensor(CoordinatorEntity, BinarySensorEntity):
    """Rain yes/no."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator, entry, item: AnalogueInput) -> None:
        super().__init__(coordinator)
        self._item = item
        self._attr_name = item.name
        self._attr_unique_id = f"{item.address}-input-{item.key}"
        self._attr_device_info = weather_device_info(entry)

    @property
    def _raw(self):
        return (self.coordinator.data or {}).get(self._item.address)

    @property
    def available(self) -> bool:
        raw = self._raw
        return super().available and raw is not None and raw >= 0

    @property
    def is_on(self):
        return convert(self._item.kind, self._raw)

    @property
    def extra_state_attributes(self):
        return {"helvar_address": f"@{self._item.address}", "raw_level": self._raw}
