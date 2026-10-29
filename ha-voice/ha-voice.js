#!/usr/bin/env node
/**
 * HA Voice Endpoint - HTTP channel server for Home Assistant Assist integration.
 *
 * Receives voice text from HA's conversation agent via HTTP POST,
 * pushes it into Claude's context as a channel event, and waits for
 * Claude to respond via the ha_voice_reply tool.
 *
 * Endpoints:
 *   POST /message  - voice input from HA Assist (waits for agent response)
 *   GET  /health   - health check for HA config validation
 *
 * Environment:
 *   HA_VOICE_PORT  - listen port (default: 8790)
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { createServer } from 'http';

const PORT = parseInt(process.env.HA_VOICE_PORT || '8790', 10);
// Fallback only. HA sends deadline_seconds per request; that value wins.
const DEFAULT_TIMEOUT_MS = 60_000;
const HA_URL = process.env.HA_URL || ''; // e.g. http://<ha-host>:8123
const HA_TOKEN = process.env.HA_TOKEN || ''; // Long-lived access token

const log = (msg) => process.stderr.write(`[ha-voice] ${msg}\n`);

// Exposed entities from the most recent voice request, keyed by request_id.
// Deliberately outlives both the reply and the deadline: the agent is told to
// acknowledge first and act afterwards, so the entities it is allowed to touch
// must still be there once the satellite has stopped listening.
const exposedEntities = new Map();
const ENTITY_TTL_MS = 10 * 60 * 1000;

// Pending requests waiting for agent responses
const pending = new Map();

// ── MCP Server ──────────────────────────────────────────────────────────────

const mcp = new Server(
  { name: 'ha-voice', version: '0.1.0' },
  {
    capabilities: {
      experimental: { 'claude/channel': {} },
      tools: {},
    },
    instructions: [
      'The user speaks to you through a Home Assistant voice satellite. They read',
      'nothing in this session. Anything you want them to hear MUST go through the',
      'ha_voice_reply tool - your transcript output never reaches them.',
      '',
      'Voice input arrives as <channel source="ha-voice" request_id="..." device="..." area="...">.',
      'Every voice message must end in exactly one ha_voice_reply call carrying that',
      'request_id. Answering in the transcript instead leaves the user in silence',
      'until the request times out and the speaker says the agent is not responding.',
      'Keep responses brief and conversational - this is voice, not text.',
      'Do NOT use markdown formatting in voice replies.',
      '',
      'deadline_seconds is how long you have before the satellite gives up and',
      'the user hears an error. Decide up front which path you are on:',
      '  - Answerable within the deadline: just call ha_voice_reply.',
      '  - Needs slow work (Notion, Garmin, web): call ha_voice_reply NOW with a',
      '    short spoken acknowledgement, do the work, then publish the real answer',
      '    to the MQTT topic ha/tts/speak as {"message": "..."} to speak it aloud.',
      'Never let the deadline pass in silence - an ack beats nothing.',
      '',
      'Set continue_conversation true when your reply asks the user something, so',
      'the satellite reopens the microphone without needing the wake word.',
      '',
      'The message may include [Available devices] with entity IDs you can control.',
      'To control a device, use the ha_call_service tool with the entity_id from the list.',
      'Match the user\'s request to the closest device name. If no match, say so.',
    ].join('\n'),
  },
);

// ── Tools ───────────────────────────────────────────────────────────────────

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'ha_voice_reply',
      description: 'Reply to a Home Assistant voice request. The response will be spoken via TTS.',
      inputSchema: {
        type: 'object',
        properties: {
          request_id: {
            type: 'string',
            description: 'The request_id from the incoming voice message',
          },
          text: {
            type: 'string',
            description: 'Your spoken response (plain text, no markdown)',
          },
          continue_conversation: {
            type: 'boolean',
            description:
              'True if your reply asks the user something, so the satellite reopens the mic without a wake word',
          },
        },
        required: ['request_id', 'text'],
      },
    },
    {
      name: 'ha_call_service',
      description:
        'Control a Home Assistant device. Only works for entities exposed in the current voice request.',
      inputSchema: {
        type: 'object',
        properties: {
          request_id: {
            type: 'string',
            description: 'The request_id from the incoming voice message',
          },
          domain: {
            type: 'string',
            description: 'HA service domain (e.g. light, switch, cover, climate, media_player)',
          },
          service: {
            type: 'string',
            description: 'Service to call (e.g. turn_on, turn_off, toggle, set_temperature)',
          },
          entity_id: {
            type: 'string',
            description: 'Entity ID to control (e.g. light.living_room)',
          },
          service_data: {
            type: 'object',
            description:
              'Optional service data (e.g. { "brightness": 128 } for lights, { "temperature": 21 } for climate)',
          },
        },
        required: ['request_id', 'domain', 'service', 'entity_id'],
      },
    },
  ],
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name === 'ha_voice_reply') {
    const { request_id, text, continue_conversation } = req.params.arguments ?? {};

    // A missing/blank text used to crash this handler on .substring, which
    // resolved the HTTP request with undefined before throwing. Reject it
    // instead so the agent gets a usable error and the request stays open.
    if (typeof text !== 'string' || text.trim() === '') {
      return {
        content: [{ type: 'text', text: 'ha_voice_reply requires a non-empty text argument.' }],
        isError: true,
      };
    }

    const entry = pending.get(request_id);
    if (!entry) {
      return {
        content: [{ type: 'text', text: `No pending request with id: ${request_id}` }],
        isError: true,
      };
    }

    pending.delete(request_id);
    log(`Replied to ${request_id}: ${text.substring(0, 80)}`);
    entry.resolve({ text, continueConversation: continue_conversation === true });

    return {
      content: [{ type: 'text', text: 'Voice response sent.' }],
    };
  }

  if (req.params.name === 'ha_call_service') {
    const { request_id, domain, service, entity_id, service_data } = req.params.arguments;

    // Validate HA connection is configured
    if (!HA_URL || !HA_TOKEN) {
      return {
        content: [{ type: 'text', text: 'HA_URL and HA_TOKEN are not configured.' }],
        isError: true,
      };
    }

    // Validate entity is in the exposed list for this request
    const entities = exposedEntities.get(request_id);
    if (!entities) {
      return {
        content: [{ type: 'text', text: `No exposed entities found for request: ${request_id}` }],
        isError: true,
      };
    }

    const allowed = entities.find((e) => e.entity_id === entity_id);
    if (!allowed) {
      return {
        content: [
          {
            type: 'text',
            text: `Entity ${entity_id} is not in the exposed device list. Available: ${entities.map((e) => e.entity_id).join(', ')}`,
          },
        ],
        isError: true,
      };
    }

    // Call HA REST API
    const url = `${HA_URL}/api/services/${domain}/${service}`;
    const payload = { entity_id, ...(service_data || {}) };

    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${HA_TOKEN}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const body = await resp.text();
        log(`HA service call failed: ${resp.status} ${body}`);
        return {
          content: [{ type: 'text', text: `HA returned ${resp.status}: ${body}` }],
          isError: true,
        };
      }

      log(`HA service OK: ${domain}.${service} -> ${entity_id}`);
      return {
        content: [
          {
            type: 'text',
            text: `Called ${domain}.${service} on ${allowed.name || entity_id} (was: ${allowed.state})`,
          },
        ],
      };
    } catch (err) {
      log(`HA service call error: ${err.message}`);
      return {
        content: [{ type: 'text', text: `Failed to reach HA: ${err.message}` }],
        isError: true,
      };
    }
  }

  return {
    content: [{ type: 'text', text: `Unknown tool: ${req.params.name}` }],
    isError: true,
  };
});

// ── HTTP Server ─────────────────────────────────────────────────────────────

function parseBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString()));
      } catch (e) {
        reject(new Error('Invalid JSON'));
      }
    });
    req.on('error', reject);
  });
}

let requestCounter = 0;
const startedAt = Date.now().toString(36);

const httpServer = createServer(async (req, res) => {
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // Health check
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', service: 'ha-voice' }));
    return;
  }

  // Voice message from HA conversation agent
  if (req.method === 'POST' && req.url === '/message') {
    let body;
    try {
      body = await parseBody(req);
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid JSON' }));
      return;
    }

    const text = body.text || '';
    const device = body.device || 'unknown';
    const area = body.area || 'unknown';
    const entities = body.entities || [];
    const deadlineMs = body.deadline_seconds
      ? body.deadline_seconds * 1000
      : DEFAULT_TIMEOUT_MS;
    // Counter alone restarts at 1 with the container, colliding with ids the
    // agent may still be holding from before the restart.
    const requestId = `voice-${startedAt}-${++requestCounter}`;

    log(`[${requestId}] ${area}/${device}: ${text} (${entities.length} entities exposed, ${deadlineMs}ms deadline)`);

    // Store exposed entities for validation by ha_call_service. Expiry is on its
    // own clock, not the deadline's, so control still works after an ack.
    if (entities.length > 0) {
      exposedEntities.set(requestId, entities);
      setTimeout(() => exposedEntities.delete(requestId), ENTITY_TTL_MS).unref();
    }

    // Restated on every request rather than left to the server instructions,
    // which are read once at connect. The agent otherwise answers into its own
    // session, where the speaker cannot hear it.
    let content = [
      `[HA Voice request ${requestId}. You have ${Math.round(deadlineMs / 1000)}s.]`,
      `The user is speaking and CANNOT see this session. Answer by calling the`,
      `ha_voice_reply tool with request_id "${requestId}". Text written here is`,
      `never spoken and the user will hear silence, then an error.`,
      '',
      text,
    ].join('\n');
    if (entities.length > 0) {
      const entityList = entities.map(e => {
        const line = `${e.entity_id} "${e.name}" (${e.domain}, ${e.state}${e.area ? `, ${e.area}` : ''})`;

        // Scripts are the only exposed entity that takes arguments, and the
        // agent has no other way to learn their names. Without this it sees a
        // bare entity_id and has to guess what to pass, which produces a script
        // run that succeeds and does nothing.
        const extra = [];
        if (e.description) extra.push(`    ${e.description}`);
        for (const [name, spec] of Object.entries(e.fields ?? {})) {
          const parts = [
            spec.required ? 'required' : 'optional',
            spec.description,
            spec.example ? `e.g. ${spec.example}` : null,
          ].filter(Boolean);
          extra.push(`    - ${name}: ${parts.join(', ')}`);
        }

        return extra.length ? `${line}\n${extra.join('\n')}` : line;
      }).join('\n');
      content += `\n\n[Available devices]\n${entityList}`;
    }

    // Create a promise that the reply tool will resolve
    const responsePromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        reject(new Error('Response timeout'));
      }, deadlineMs);

      pending.set(requestId, {
        resolve: (response) => {
          clearTimeout(timer);
          resolve(response);
        },
      });
    });

    // Push the voice message into Claude's context
    try {
      await mcp.notification({
        method: 'notifications/claude/channel',
        params: {
          content,
          meta: {
            source: 'ha-voice',
            request_id: requestId,
            device,
            area,
          },
        },
      });
    } catch (e) {
      log(`Failed to push notification: ${e}`);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Failed to reach agent' }));
      return;
    }

    // Wait for the agent to respond via ha_voice_reply
    try {
      const { text: response, continueConversation } = await responsePromise;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ response, continue_conversation: continueConversation }));
    } catch {
      log(`[${requestId}] Timed out waiting for agent response`);
      res.writeHead(504, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Agent did not respond in time' }));
    }
    return;
  }

  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

// ── Start ───────────────────────────────────────────────────────────────────

await mcp.connect(new StdioServerTransport());

httpServer.listen(PORT, '0.0.0.0', () => {
  log(`Voice endpoint listening on port ${PORT}`);
  log('MCP channel ready');
});

// Graceful shutdown
process.on('SIGTERM', () => {
  log('Shutting down...');
  for (const [id, entry] of pending) {
    entry.resolve({
      text: 'Agent is restarting, please try again.',
      continueConversation: false,
    });
    pending.delete(id);
  }
  httpServer.close();
  process.exit(0);
});
