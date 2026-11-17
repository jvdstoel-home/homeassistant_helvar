"""Read the analogue inputs (942 units) of the Helvar router.

The weather station (Thies Clima Sensor D) and the outdoor temperature sensor
(Siemens QAC3161) are connected to 0-10 V inputs of two 942 units. The router
returns their level with HelvarNet command 151 (Query Inputs) as 0-255.

Queries go over the integration's own TCP session to the router: the router
drops that session when a second TCP connection from the same host is opened,
and it does not answer these queries over UDP.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiohelvar_patches import query_input
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

RAW_MAX = 255


@dataclass(frozen=True)
class AnalogueInput:
    """One analogue input of a 942 unit."""

    address: str  # Helvar subdevice address, e.g. "1.7.2.62.2"
    key: str
    name: str
    kind: str  # rain | wind | light | temperature
    interval: int  # seconds


# Wiring of this installation (checked against Designer on 17 Nov 2026).
INPUTS: tuple[AnalogueInput, ...] = (
    AnalogueInput("1.7.2.62.1", "rain", "Regen", "rain", 60),
    AnalogueInput("1.7.2.62.2", "wind_speed", "Windsnelheid", "wind", 60),
    AnalogueInput("1.7.2.62.3", "light_east", "Licht oost", "light", 60),
    AnalogueInput("1.7.2.62.4", "light_south", "Licht zuid", "light", 60),
    AnalogueInput("1.7.2.63.1", "light_west", "Licht west", "light", 60),
    AnalogueInput("1.7.2.63.2", "temperature", "Buitentemperatuur", "temperature", 300),
)


def convert(kind: str, raw: int | None):
    """Convert a 0-255 input level to a physical value."""
    if raw is None or raw < 0:
        return None
    fraction = min(raw, RAW_MAX) / RAW_MAX  # 0..1 = 0..10 V
    if kind == "temperature":  # QAC3161: 0-10 V = -50..+50 degC
        return round(fraction * 100 - 50, 1)
    if kind == "wind":  # Clima Sensor D: 0-10 V = 0..40 m/s
        return round(fraction * 40, 1)
    if kind == "light":  # Clima Sensor D: 0-10 V = 0..100 klux
        return round(fraction * 100000)
    if kind == "rain":  # Clima Sensor D: 0 V dry, 10 V rain
        return fraction > 0.5
    return raw


class HelvarInputCoordinator(DataUpdateCoordinator[dict[str, int | None]]):
    """Poll a set of analogue inputs at one interval."""

    def __init__(self, hass, entry, inputs: list[AnalogueInput], interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Helvar inputs ({interval}s)",
            update_interval=timedelta(seconds=interval),
        )
        self.inputs = inputs

    async def _async_update_data(self) -> dict[str, int | None]:
        router = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        api = getattr(router, "api", None)
        if api is None or not api.connected:
            raise UpdateFailed("Helvar router not connected")
        result: dict[str, int | None] = {}
        for item in self.inputs:
            try:
                result[item.address] = await query_input(api, item.address)
            except asyncio.TimeoutError:
                result[item.address] = None
            except ConnectionError as err:
                raise UpdateFailed(f"Helvar router not connected: {err}") from err
        if all(value is None for value in result.values()):
            raise UpdateFailed("No answer from the Helvar router for the inputs")
        return result


async def async_get_coordinators(hass, entry, kinds: set[str]) -> list[HelvarInputCoordinator]:
    """Create and refresh one coordinator per poll interval for the given kinds."""
    by_interval: dict[int, list[AnalogueInput]] = {}
    for item in INPUTS:
        if item.kind in kinds:
            by_interval.setdefault(item.interval, []).append(item)
    coordinators = []
    for interval, inputs in sorted(by_interval.items()):
        coordinator = HelvarInputCoordinator(hass, entry, inputs, interval)
        await coordinator.async_refresh()  # do not block setup if the router is slow
        coordinators.append(coordinator)
    return coordinators
