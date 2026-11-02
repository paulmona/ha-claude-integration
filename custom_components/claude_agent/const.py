"""Constants for the Claude Agent integration."""

DOMAIN = "claude_agent"
CONF_SERVER_URL = "server_url"
DEFAULT_SERVER_URL = "http://127.0.0.1:8790"

# Shared secret sent as a bearer token; must match HA_VOICE_TOKEN on the agent
# host. Kept in options so it can be rotated without re-adding the integration.
CONF_AUTH_TOKEN = "auth_token"


def auth_headers(entry) -> dict:
    """Authorization header for requests to the channel server."""
    token = entry.options.get(CONF_AUTH_TOKEN) or entry.data.get(CONF_AUTH_TOKEN, "")
    return {"Authorization": f"Bearer {token}"}

# How long the agent has to reply before the satellite gives up on this turn.
# Sent to the agent so it can choose between answering inline and acknowledging
# now, then announcing the real answer later via the ha/tts/speak automation.
CONF_FAST_PATH_SECONDS = "fast_path_seconds"
DEFAULT_FAST_PATH_SECONDS = 15
