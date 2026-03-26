"""Claude Agent - AI Conversation Agent & Notification Service for Home Assistant."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery

from .const import DOMAIN

PLATFORMS = ["conversation"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Claude Agent from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Set up conversation platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up notify platform via discovery (notify uses a different pattern)
    hass.async_create_task(
        discovery.async_load_platform(
            hass,
            "notify",
            DOMAIN,
            {"entry_id": entry.entry_id},
            {},
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
