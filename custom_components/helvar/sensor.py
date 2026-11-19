"""Weather station values from the Helvar 942 analogue inputs."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import LIGHT_LUX, UnitOfSpeed, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helvar_inputs import AnalogueInput, async_get_coordinators, convert

SENSOR_KINDS = {"wind", "light", "temperature"}

DEVICE_CLASS = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "wind": SensorDeviceClass.WIND_SPEED,
    "light": SensorDeviceClass.ILLUMINANCE,
}
UNIT = {
    "temperature": UnitOfTemperature.CELSIUS,
    "wind": UnitOfSpeed.METERS_PER_SECOND,
    "light": LIGHT_LUX,
}


def weather_device_info(entry) -> DeviceInfo:
    """Device that groups the weather station entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}-weatherstation")},
        name="Helvar weerstation",
        manufacturer="Thies / Siemens via Helvar 942",
        model="Clima Sensor D 4.9100.00.061 + QAC3161",
    )


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the weather station sensors."""
    router = hass.data[DOMAIN][entry.entry_id]

    async def _add():
        coordinators = await async_get_coordinators(hass, entry, SENSOR_KINDS)
        async_add_entities(
            HelvarInputSensor(coordinator, entry, item)
            for coordinator in coordinators
            for item in coordinator.inputs
        )

    router.async_when_ready(_add)


class HelvarInputSensor(CoordinatorEntity, SensorEntity):
    """One analogue input shown as a measurement."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, item: AnalogueInput) -> None:
        super().__init__(coordinator)
        self._item = item
        self._attr_name = item.name
        self._attr_unique_id = f"{item.address}-input-{item.key}"
        self._attr_device_class = DEVICE_CLASS[item.kind]
        self._attr_native_unit_of_measurement = UNIT[item.kind]
        self._attr_device_info = weather_device_info(entry)
        if item.kind == "light":
            self._attr_suggested_display_precision = 0

    @property
    def _raw(self):
        return (self.coordinator.data or {}).get(self._item.address)

    @property
    def available(self) -> bool:
        raw = self._raw
        return super().available and raw is not None and raw >= 0

    @property
    def native_value(self):
        return convert(self._item.kind, self._raw)

    @property
    def extra_state_attributes(self):
        return {"helvar_address": f"@{self._item.address}", "raw_level": self._raw}
