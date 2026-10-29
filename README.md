# Claude Agent - Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

A Home Assistant custom integration that connects HA voice assistants to a long-running [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) agent, letting you control your smart home, answer questions, and run complex workflows by voice.

The repository has both halves:

- `custom_components/claude_agent/`: the Home Assistant integration (installed through HACS)
- `ha-voice/`: the voice endpoint, a small Node.js MCP channel server that runs next to the Claude Code agent, receives requests from Home Assistant, and pushes them into the agent's session

It is in daily use in [hive](https://github.com/paulmona/hive), a fleet of Claude Code agents where the coordinator agent handles voice across the house.

## Important: Cloud-Based AI

This integration uses **Anthropic's Claude** as the AI backend. It is **not local** - voice requests are processed by Claude's cloud API.

**You will need:**
- A [Claude account](https://claude.ai) with an active subscription (Pro, Team, or Enterprise)
- A host running Claude Code as a long-lived process, with `ha-voice` from this repo
- Claude Code authenticates via OAuth on first run - no API key needed

**What you get in return:** Claude is a full-featured AI with tool use. Any integrations you've connected to your Claude account (email, calendar, Notion, etc.) are available to your voice agent. Your agent isn't limited to smart home commands - it can check your calendar, send emails, search the web, and run multi-step workflows, all by voice.


## How It Works

```
Voice Device -> Home Assistant -> Claude Agent Integration -> ha-voice + Claude Code
                                       |                          |
                                  HTTP POST to               Processes request,
                                  ha-voice endpoint           controls devices,
                                  (port 8790)                 returns response
```

1. You speak to a Home Assistant voice device (phone, tablet, smart speaker)
2. HA routes the text to this integration's conversation entity
3. The integration sends the text + exposed device list to the agent's ha-voice endpoint
4. The agent processes the request (can control devices, check data, run skills)
5. The response is spoken back through the voice device

`ha-voice` holds each HTTP request open until the agent answers through its `ha_voice_reply` tool, and gives the agent an `ha_call_service` tool limited to the entities listed in that request.

## Permissions and Security

The agent runs with `--dangerously-skip-permissions` because there is no way to approve a tool call by voice. That makes the agent's instructions and the host the controls, so:

- **Run the agent as a dedicated, unprivileged user.** It should not be able to change the host or read other users' files.
- **Expose only the entities you want voice to control.** `ha_call_service` is limited to the entities Home Assistant sends with each request.
- **Use a Home Assistant token scoped to what the agent needs.**
- **Write the agent's rules down.** Its CLAUDE.md and agent definition are the only brake on what it does with its other tools.

## Limitations

- **Channel acknowledgement on every restart** - `ha-voice` uses Claude Code's preview "channels" feature, loaded with `--dangerously-load-development-channels`. Claude Code asks for confirmation on every start, so someone (or a small script, as in [hive](https://github.com/paulmona/hive/blob/main/tools/dev-channels-watcher)) has to answer it.
- **No proactive HA control** - The agent can currently only control Home Assistant devices in response to voice requests. It cannot independently send commands to HA via MQTT or other channels (e.g. "turn on the porch light at sunset"). This is planned for a future release.
- **Cloud dependency** - All voice processing goes through Claude's cloud API. No internet, no agent.

## Prerequisites

- **Home Assistant** 2024.1.0 or later
- **A Claude account** with an active subscription (Pro, Team, or Enterprise)
- **Claude Code** running as a long-lived process (for example in tmux under systemd), with Node.js 18+ for `ha-voice`

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) and select **Custom repositories**
3. Add `https://github.com/paulmona/ha-claude-integration` with category **Integration**
4. Search for "Claude Agent" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/claude_agent` directory into your HA `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for "Claude Agent"
3. Enter the URL of your agent's ha-voice endpoint (default: `http://127.0.0.1:8790`)

## Exposing Devices

The integration sends a list of exposed entities to the agent with each voice request. The agent can only control devices you explicitly expose:

1. Go to **Settings > Voice Assistants**
2. Select the Claude Agent conversation entity
3. Choose which entities to expose

The agent receives each entity's id, name, state, domain, and area.

## Notification Service

The integration registers a `notify.claude_agent` service, allowing HA automations to send messages to your agent:

```yaml
service: notify.claude_agent
data:
  message: "The front door was left open for 10 minutes"
```

This is useful for wiring the agent into your existing automations. For example, you could notify the agent when motion is detected, when a door is left open, or when a sensor crosses a threshold - and let the agent decide how to respond.

## Using MQTT for Automations

If the agent also loads an MQTT channel (for example [claude-code-mqtt](https://github.com/mattstein111/claude-code-mqtt)), HA automations, Node-RED, or other systems can send it commands over MQTT too.

## Voice Endpoint Setup

On the host that runs Claude Code:

```bash
cd ha-voice && npm ci
claude mcp add -s user ha-voice -- node /path/to/ha-voice/ha-voice.js
claude --dangerously-skip-permissions --dangerously-load-development-channels server:ha-voice
```

`ha-voice` reads its settings from the environment Claude Code is started with:

| Variable | Description |
|---|---|
| `HA_URL` | Your Home Assistant URL (e.g. `http://192.168.1.100:8123`) |
| `HA_TOKEN` | A Home Assistant long-lived access token |
| `HA_VOICE_PORT` | Listen port, default `8790` |

Port 8790 must be reachable from Home Assistant.

For an example of agent instructions written for voice (short, spoken, no markdown), see Sunday's [CLAUDE.md](https://github.com/paulmona/hive/blob/main/agents/sunday/CLAUDE.md) in hive.

## Troubleshooting

**"Sorry, I cannot reach the agent"** - Check that the agent is running with `ha-voice` loaded and port 8790 is accessible from HA. Test with `curl http://<agent-host>:8790/health`.

**"Sorry, the agent is taking too long to respond"** - The default timeout is 120 seconds. Complex requests (tool use, API calls) can take time. Check the agent's logs.

**Agent can't control devices** - Make sure the devices are exposed in HA's Voice Assistants settings. The agent can only see and control entities you explicitly expose.

## Created By

Built by [ViewBridge AI](https://viewbridge.ai) - AI consulting and development for businesses.

## License

MIT - See [LICENSE](LICENSE) for details.
