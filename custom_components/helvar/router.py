"""Helvar Router."""
import logging

import aiohelvar

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

    @property
    def host(self):
        """Return the host of this router."""
        return self.config_entry.data[CONF_HOST]

    @property
    def port(self):
        """Return the host of this router."""
        return self.config_entry.data[CONF_PORT]

    async def async_setup(self, tries=0):
        """Set up a helvar router based on host parameter."""
        host = self.host
        port = self.port
        hass = self.hass

        extra = self.config_entry.options.get(
            CONF_EXTRA_ROUTERS, self.config_entry.data.get(CONF_EXTRA_ROUTERS, [])
        )
        router = aiohelvar.Router(host, port, extra_router_ids=extra)

        try:
            await router.connect()
            await router.initialize()

        except ConnectionError as err:
            _LOGGER.error("Error connecting to the Helvar router at %s", host)
            raise ConfigEntryNotReady from err

        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unknown error connecting with Helvar router at %s", host)
            return False

        self.api = router
        _LOGGER.info(
            "Helvar router %s ready: routers %s, %s groups, %s devices, %s scenes",
            host,
            router.router_ids,
            len(router.groups.groups),
            len(router.devices.devices),
            len(router.scenes.scenes),
        )
        return True

    async def async_close(self):
        """PATCH: close the connection on unload."""
        if self.api is not None and self.api.connected:
            try:
                await self.api.disconnect()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Error while disconnecting", exc_info=True)
