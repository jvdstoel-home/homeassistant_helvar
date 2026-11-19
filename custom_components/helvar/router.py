"""Helvar Router."""
import asyncio
import logging
import time

import aiohelvar

from homeassistant.helpers.event import async_call_later

from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_EXTRA_ROUTERS, CONF_HOST, CONF_PORT

_LOGGER = logging.getLogger(__name__)


class HelvarRouter:
    """Manages a Helvar Router."""

    def __init__(self, hass, config_entry):
        """Initialize the system."""
        self.config_entry = config_entry
        self.hass = hass
        self.available = True
        self.api = None
        self.ready = False
        self._ready_jobs = []

    @property
    def host(self):
        """Return the host of this router."""
        return self.config_entry.data[CONF_HOST]

    @property
    def port(self):
        """Return the host of this router."""
        return self.config_entry.data[CONF_PORT]

    async def async_connect(self):
        """Open the connection to the router (fast). Discovery runs later."""
        host = self.host
        port = self.port
        extra = self.config_entry.options.get(
            CONF_EXTRA_ROUTERS, self.config_entry.data.get(CONF_EXTRA_ROUTERS, [])
        )
        router = aiohelvar.Router(host, port, extra_router_ids=extra)
        try:
            await router.connect()
        except (ConnectionError, OSError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error connecting to the Helvar router at %s", host)
            raise ConfigEntryNotReady from err
        self.api = router

    def async_when_ready(self, job) -> None:
        """Run job (an async function) once discovery has finished."""
        if self.ready:
            self.hass.async_create_task(job())
        else:
            self._ready_jobs.append(job)

    async def async_initialize(self):
        """Discover groups, devices and scenes in the background, then add entities."""
        host = self.host
        started = time.monotonic()
        try:
            await self.api.initialize()
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Helvar discovery on %s failed; reloading the integration in 60 s", host
            )
            entry_id = self.config_entry.entry_id
            async_call_later(
                self.hass,
                60,
                lambda _now: self.hass.config_entries.async_schedule_reload(entry_id),
            )
            return

        router = self.api
        _LOGGER.info(
            "Helvar router %s ready after %.0f s: routers %s, %s groups, %s devices, %s scenes",
            host,
            time.monotonic() - started,
            router.router_ids,
            len(router.groups.groups),
            len(router.devices.devices),
            len(router.scenes.scenes),
        )
        self.ready = True
        jobs, self._ready_jobs = self._ready_jobs, []
        for job in jobs:
            try:
                await job()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Adding Helvar entities failed")

    async def async_close(self):
        """PATCH: close the connection on unload."""
        if self.api is not None and self.api.connected:
            try:
                await self.api.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error while disconnecting", exc_info=True)
