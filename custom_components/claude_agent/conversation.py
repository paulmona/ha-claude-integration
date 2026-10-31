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

from .const import (
    DOMAIN,
    CONF_SERVER_URL,
    CONF_FAST_PATH_SECONDS,
    DEFAULT_FAST_PATH_SECONDS,
    auth_headers,
)

_LOGGER = logging.getLogger(__name__)

# Grace on top of the agent's deadline so the channel server's own timeout
# fires first and we get its error rather than a bare client disconnect.
HTTP_GRACE_SECONDS = 5


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
    def _fast_path_seconds(self) -> int:
        """Seconds the agent has to answer before this turn is abandoned."""
        return self.entry.options.get(
            CONF_FAST_PATH_SECONDS, DEFAULT_FAST_PATH_SECONDS
        )

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages."""
        return ["en"]

    def _get_exposed_entities(self) -> list[dict]:
        """Get entities exposed to conversation agents with their current state."""
        entity_registry = er.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        exposed = []

        for entity_entry in entity_registry.entities.values():
            # Check if entity is exposed to conversation agents
            options = entity_entry.options.get("conversation", {})
            if not options.get("should_expose", False):
                continue

            state = self.hass.states.get(entity_entry.entity_id)
            if state is None:
                continue

            # Most entities inherit their area from their device rather than
            # carrying area_id themselves, so fall back to the device.
            area_id = entity_entry.area_id
            if area_id is None and entity_entry.device_id:
                device = device_registry.async_get(entity_entry.device_id)
                if device:
                    area_id = device.area_id

            area_name = None
            if area_id:
                area = area_registry.async_get_area(area_id)
                if area:
                    area_name = area.name

            entry = {
                "entity_id": entity_entry.entity_id,
                "name": entity_entry.name or entity_entry.original_name or entity_entry.entity_id,
                "state": state.state,
                "domain": entity_entry.domain,
                "area": area_name,
            }

            # A script is the one exposed entity that takes arguments, and the
            # agent has no other way to learn their names. Without this it sees
            # only "script.set_alarm (script, off)" and has to guess what to
            # pass, which silently produces a script run that does nothing.
            if entity_entry.domain == "script":
                description = state.attributes.get("description")
                if description:
                    entry["description"] = description

                fields = state.attributes.get("fields") or {}
                if fields:
                    entry["fields"] = {
                        name: {
                            k: v
                            for k, v in (
                                ("description", spec.get("description")),
                                ("example", spec.get("example")),
                                ("required", spec.get("required")),
                            )
                            if v is not None
                        }
                        for name, spec in fields.items()
                    }

            exposed.append(entry)

        return exposed

    def _resolve_satellite(self, device_id: str | None) -> str | None:
        """Find the assist_satellite entity for the device that made the request."""
        if not device_id:
            return None
        entity_registry = er.async_get(self.hass)
        for entry in er.async_entries_for_device(entity_registry, device_id):
            if entry.domain == "assist_satellite":
                return entry.entity_id
        return None

    async def _request_response(self, payload: dict) -> tuple[str, bool]:
        """POST to the channel server, return (spoken response, keep listening)."""
        _LOGGER.debug("Sending to channel server: %s", payload)
        http_timeout = payload["deadline_seconds"] + HTTP_GRACE_SECONDS
        try:
            session = async_get_clientsession(self.hass)
            async with session.post(
                f"{self._server_url}/message",
                json=payload,
                headers=auth_headers(self.entry),
                timeout=aiohttp.ClientTimeout(total=http_timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response_text = data.get("response", "I didn't get a response.")
                    _LOGGER.debug("Received response: %s", response_text)
                    return response_text, bool(data.get("continue_conversation"))
                _LOGGER.error("Channel server error: %s %s", resp.status, await resp.text())
                return "Sorry, the agent is not responding.", False
        except TimeoutError:
            _LOGGER.error("Channel server timeout after %ds", http_timeout)
            return "Sorry, the agent is taking too long to respond.", False
        except aiohttp.ClientError as err:
            _LOGGER.error("Channel server connection error: %s", err)
            return "Sorry, I cannot reach the agent.", False

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
            # Lets the agent choose between answering inline and acknowledging
            # now, then announcing the real answer via ha/tts/speak.
            "deadline_seconds": self._fast_path_seconds,
            "satellite": self._resolve_satellite(user_input.device_id),
            "conversation_id": user_input.conversation_id,
        }

        response_text, continue_conversation = await self._request_response(payload)

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(response_text)
        return ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
            continue_conversation=continue_conversation,
        )
