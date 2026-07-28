"""Constants for the Claude Agent integration."""

DOMAIN = "claude_agent"
CONF_SERVER_URL = "server_url"
DEFAULT_SERVER_URL = "http://127.0.0.1:8790"

# How long the agent has to reply before the satellite gives up on this turn.
# Sent to the agent so it can choose between answering inline and acknowledging
# now, then announcing the real answer later via the ha/tts/speak automation.
CONF_FAST_PATH_SECONDS = "fast_path_seconds"
DEFAULT_FAST_PATH_SECONDS = 15
