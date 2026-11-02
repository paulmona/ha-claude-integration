"""Notify platform for Claude Agent - send events from HA automations to the agent."""

import aiohttp
import logging

from homeassistant.components.notify import (
    BaseNotificationService,
    ATTR_DATA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, CONF_SERVER_URL, auth_headers

_LOGGER = logging.getLogger(__name__)

# Shorter timeout for notifications - they're fire-and-forget from HA's perspective
NOTIFY_TIMEOUT = 10


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> "ClaudeNotifyService | None":
    """Get the notification service."""
    if discovery_info is None:
        return None

    entry_id = discovery_info.get("entry_id")
    if not entry_id or entry_id not in hass.data.get(DOMAIN, {}):
        _LOGGER.error("Invalid or missing entry_id in discovery_info")
        return None

    entry = hass.config_entries.async_get_entry(entry_id)
    return ClaudeNotifyService(hass, entry)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> None:
    """Set up the notify platform from a config entry."""
    await hass.config_entries.async_forward_entry_setup(config_entry, "notify")


class ClaudeNotifyService(BaseNotificationService):
    """Send event notifications to the Claude agent via channel server."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the service."""
        self.hass = hass
        self._entry = entry
        self._server_url = entry.data[CONF_SERVER_URL]

    async def async_send_message(self, message: str = "", **kwargs) -> None:
        """Send a notification event to the agent.

        Usage in automations:
          service: notify.claude_agent
          data:
            message: "Sleep mode activated"
            data:
              event_type: mode_change
              entity_id: input_boolean.sleep_mode
              state: "on"
        """
        extra_data = kwargs.get(ATTR_DATA) or {}

        payload = {
            "type": "event",
            "source": "ha-automation",
            "message": message,
            "event_data": extra_data,
        }

        _LOGGER.debug("Sending event to channel server: %s", payload)

        try:
            session = async_get_clientsession(self.hass)
            async with session.post(
                f"{self._server_url}/event",
                json=payload,
                headers=auth_headers(self._entry),
                timeout=aiohttp.ClientTimeout(total=NOTIFY_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    _LOGGER.debug("Event delivered successfully")
                else:
                    _LOGGER.error(
                        "Channel server rejected event: %s %s",
                        resp.status,
                        await resp.text(),
                    )
        except TimeoutError:
            _LOGGER.error("Channel server timeout sending event")
        except aiohttp.ClientError as err:
            _LOGGER.error("Channel server connection error: %s", err)
