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
    CONF_AUTH_TOKEN,
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
        """Handle the initial step - configure channel server URL and token."""
        errors = {}
        server_url = DEFAULT_SERVER_URL

        if user_input is not None:
            server_url = user_input[CONF_SERVER_URL].rstrip("/")
            token = user_input[CONF_AUTH_TOKEN]

            parsed = urlparse(server_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                errors["base"] = "invalid_url"
            else:
                errors["base"] = await self._test_connection(server_url, token)
                if errors["base"] is None:
                    return self.async_create_entry(
                        title="Claude Agent",
                        data={CONF_SERVER_URL: server_url, CONF_AUTH_TOKEN: token},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVER_URL, default=server_url): str,
                    vol.Required(CONF_AUTH_TOKEN): str,
                }
            ),
            errors=errors,
        )

    async def _test_connection(self, server_url, token):
        """Return an error key, or None if the server accepted the token."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{server_url}/health",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 401:
                    return "invalid_auth"
                if resp.status == 200 and (await resp.json()).get("status") == "ok":
                    return None
        except (aiohttp.ClientError, TimeoutError):
            pass
        return "cannot_connect"


class ClaudeAgentOptionsFlow(config_entries.OptionsFlow):
    """Handle tuning of the response deadline after setup."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        current = options.get(CONF_FAST_PATH_SECONDS, DEFAULT_FAST_PATH_SECONDS)
        token = options.get(CONF_AUTH_TOKEN) or self.config_entry.data.get(
            CONF_AUTH_TOKEN, ""
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FAST_PATH_SECONDS, default=current
                    ): vol.All(vol.Coerce(int), vol.Range(min=3, max=120)),
                    vol.Required(CONF_AUTH_TOKEN, default=token): str,
                }
            ),
        )
