"""Conversation platform for Claude Agent - routes voice to channel server."""

import aiohttp
import logging

from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import (
    device_registry as dr,
    area_registry as ar,
    entity_registry as er,
    intent,
)

from .const import DOMAIN, CONF_SERVER_URL

_LOGGER = logging.getLogger(__name__)

# Timeout for waiting on agent response (agents may use tools, think, etc.)
RESPONSE_TIMEOUT = 120


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the conversation entity."""
    agent = ClaudeConversationEntity(hass, config_entry)
    async_add_entities([agent])


class ClaudeConversationEntity(ConversationEntity):
    """Conversation entity that routes voice input to a Claude agent via channel server."""

    _attr_has_entity_name = True
    _attr_name = "Claude Agent"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self.hass = hass
        self.entry = entry
        self._server_url = entry.data[CONF_SERVER_URL]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages."""
        return ["en"]

    def _get_exposed_entities(self) -> list[dict]:
        """Get entities exposed to conversation agents with their current state."""
        entity_registry = er.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        exposed = []

        for entity_entry in entity_registry.entities.values():
            # Check if entity is exposed to conversation agents
            options = entity_entry.options.get("conversation", {})
            if not options.get("should_expose", False):
                continue

            state = self.hass.states.get(entity_entry.entity_id)
            if state is None:
                continue

            # Get area name if available
            area_name = None
            if entity_entry.area_id:
                area = area_registry.async_get_area(entity_entry.area_id)
                if area:
                    area_name = area.name

            exposed.append({
                "entity_id": entity_entry.entity_id,
                "name": entity_entry.name or entity_entry.original_name or entity_entry.entity_id,
                "state": state.state,
                "domain": entity_entry.domain,
                "area": area_name,
            })

        return exposed

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Process a voice input - send to channel server and return response."""
        text = user_input.text

        # Resolve the device and area for location context
        device_name = None
        area_name = None

        if user_input.device_id:
            device_registry = dr.async_get(self.hass)
            device = device_registry.async_get(user_input.device_id)
            if device:
                device_name = device.name_by_user or device.name
                if device.area_id:
                    area_registry = ar.async_get(self.hass)
                    area = area_registry.async_get_area(device.area_id)
                    if area:
                        area_name = area.name

        # Get exposed entities for the agent
        exposed_entities = self._get_exposed_entities()

        payload = {
            "type": "voice",
            "source": "ha-assist",
            "text": text,
            "device": device_name,
            "area": area_name,
            "entities": exposed_entities,
        }

        _LOGGER.debug("Sending to channel server: %s", payload)

        try:
            session = async_get_clientsession(self.hass)
            async with session.post(
                f"{self._server_url}/message",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=RESPONSE_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response_text = data.get("response", "I didn't get a response.")
                    _LOGGER.debug("Received response: %s", response_text)
                else:
                    response_text = "Sorry, the agent is not responding."
                    _LOGGER.error("Channel server error: %s %s", resp.status, await resp.text())
        except TimeoutError:
            response_text = "Sorry, the agent is taking too long to respond."
            _LOGGER.error("Channel server timeout after %ds", RESPONSE_TIMEOUT)
        except aiohttp.ClientError as err:
            response_text = "Sorry, I cannot reach the agent."
            _LOGGER.error("Channel server connection error: %s", err)

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(response_text)
        return ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
        )
