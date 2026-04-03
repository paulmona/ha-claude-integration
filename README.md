# Claude Agent - Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

A Home Assistant custom integration that connects HA voice assistants to [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents running in [The Hive](https://github.com/paulmona/thehive). Talk to your AI assistant through any HA voice device, and it can control your smart home, answer questions, and run complex workflows.

## Important: Cloud-Based AI

This integration uses **Anthropic's Claude** as the AI backend. It is **not local** - voice requests are processed by Claude's cloud API.

**You will need:**
- A [Claude account](https://claude.ai) with an active subscription
- Claude Code authenticates via OAuth on first run - no API key needed

**What you get in return:** Claude is a full-featured AI with tool use. Any integrations you've connected to your Claude account (email, calendar, Notion, etc.) are available to your voice agent. Your agent isn't limited to smart home commands - it can check your calendar, send emails, search the web, and run multi-step workflows, all by voice.

## How It Works

```
Voice Device -> Home Assistant -> Claude Agent Integration -> Hive Agent (Docker)
                                       |                          |
                                  HTTP POST to               Processes request,
                                  ha-voice endpoint           controls devices,
                                  (port 8790)                 returns response
```

1. You speak to a Home Assistant voice device (phone, tablet, smart speaker)
2. HA routes the text to this integration's conversation entity
3. The integration sends the text + exposed device list to the Hive agent's ha-voice endpoint
4. The agent processes the request (can control devices, check data, run skills)
5. The response is spoken back through the voice device

The voice endpoint (ha-voice) is built into [The Hive](https://github.com/paulmona/thehive) Docker image. You only need a single container running your agent - the voice server, MQTT, and memory are all included.

## Permissions and Security

The agent runs with `--dangerously-skip-permissions` ("yolo mode") because there is no way to approve tool calls via voice. This is safe because:

- The container is hardened: no package managers at runtime, non-root user, resource limits
- The agent can only control HA devices you explicitly expose
- All agent behavior is governed by its CLAUDE.md and agent definition files
- The agent runs in an isolated Docker container with a persistent but sandboxed home directory

If you're uncomfortable with this, review the [security model](https://github.com/paulmona/thehive#security) in The Hive docs.

## Prerequisites

- **Home Assistant** 2024.1.0 or later
- **A Claude account** with an active subscription (Pro, Team, or Enterprise)
- **[The Hive](https://github.com/paulmona/thehive)** - one Docker container running your agent with `HA_URL` and `HA_TOKEN` configured
- **[Agent config](https://github.com/paulmona/hive-agent-sample)** deployed to your Hive agent

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
3. Enter the URL of your Hive agent's ha-voice endpoint (default: `http://127.0.0.1:8790`)

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

The sample agent config includes MQTT support for inter-agent messaging. You can also use MQTT to send commands to your agent from HA automations, Node-RED, or other systems. Configure `MQTT_BROKER_URL` in your Hive agent's environment to enable this.

## Hive Agent Setup

Your Hive agent needs the ha-voice endpoint enabled. In your agent's Vault config (or env vars):

| Variable | Description |
|---|---|
| `HA_URL` | Your Home Assistant URL (e.g. `http://192.168.1.100:8123`) |
| `HA_TOKEN` | A Home Assistant long-lived access token |

The agent's container needs port 8790 exposed and reachable from Home Assistant.

For agent personality and voice response guidelines, see the [sample agent config](https://github.com/paulmona/hive-agent-sample).

## Troubleshooting

**"Sorry, I cannot reach the agent"** - Check that the Hive container is running and port 8790 is accessible from HA. Test with `curl http://<agent-host>:8790/health`.

**"Sorry, the agent is taking too long to respond"** - The default timeout is 120 seconds. Complex requests (tool use, API calls) can take time. Check the agent's logs.

**Agent can't control devices** - Make sure the devices are exposed in HA's Voice Assistants settings. The agent can only see and control entities you explicitly expose.

## License

MIT - See [LICENSE](LICENSE) for details.
