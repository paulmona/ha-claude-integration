"""Config flow for Claude Agent integration."""

import aiohttp
from urllib.parse import urlparse
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_SERVER_URL,
    DEFAULT_SERVER_URL,
    CONF_FAST_PATH_SECONDS,
    DEFAULT_FAST_PATH_SECONDS,
)


class ClaudeAgentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Claude Agent."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return ClaudeAgentOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step - configure channel server URL."""
        errors = {}

        if user_input is not None:
            server_url = user_input[CONF_SERVER_URL].rstrip("/")

            # Validate URL scheme
            parsed = urlparse(server_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                errors["base"] = "invalid_url"
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                CONF_SERVER_URL, default=server_url
                            ): str,
                        }
                    ),
                    errors=errors,
                )

            # Test the connection
            try:
                session = async_get_clientsession(self.hass)
                async with session.get(
                    f"{server_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "ok":
                            return self.async_create_entry(
                                title="Claude Agent",
                                data={CONF_SERVER_URL: server_url},
                            )
                    errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERVER_URL, default=DEFAULT_SERVER_URL
                    ): str,
                }
            ),
            errors=errors,
        )


class ClaudeAgentOptionsFlow(config_entries.OptionsFlow):
    """Handle tuning of the response deadline after setup."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_FAST_PATH_SECONDS, DEFAULT_FAST_PATH_SECONDS
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FAST_PATH_SECONDS, default=current
                    ): vol.All(vol.Coerce(int), vol.Range(min=3, max=120)),
                }
            ),
        )
