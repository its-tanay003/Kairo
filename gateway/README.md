# /gateway - Session Gateway & Real-Time Protocol Multiplexer

The `/gateway` subsystem is a high-performance **Node.js / TypeScript** session broker. Positioned between client applications (Next.js web browser, Tauri desktop, mobile clients) and backend orchestrator services, it multiplexes WebSocket streams, tracks operator presence, validates authentication tokens, and bridges real-time terminal and desktop video sessions.

---

## Service Endpoints & Configuration

- **Default Port**: `4000`
- **WebSocket URL**: `ws://localhost:4000`
- **HTTP URL**: `http://localhost:4000`
- **Backend Orchestrator Target**: `http://localhost:8000`
- **VNC Desktop Proxy**: `ws://localhost:6080`

---

## Real-Time WebSocket Protocol

### 1. Connection & Session Handshake
Upon WebSocket connection, the Gateway establishes a cryptographically bound session token:
```json
// Gateway -> Client (Handshake)
{
  "type": "handshake",
  "sessionId": "sess_20261017_01",
  "authToken": "kairo_token_9f81a7b8e19c",
  "timestamp": "2026-10-17T14:30:00.000Z"
}
```

### 2. Client-to-Gateway Messages
| Message `type` | Payload Keys | Description |
| :--- | :--- | :--- |
| `chat` | `content`, `sessionId`, `modelId?` | Submits an operational directive or prompt to the agent loop. |
| `tool_call` | `tool`, `args`, `sessionId` | Directly invokes a specific ToolSpec, bypassing the LLM planner. |
| `subscribe_terminal`| `taskId` | Streams real-time ANSI terminal output for an active process. |
| `terminal_input` | `taskId`, `input` | Sends stdin characters to an active process supervisor. |
| `subscribe_screen` | `sessionId` | Connects to the low-latency RFB desktop stream for GUI tools. |
| `presence_heartbeat`| `projectId`, `userId` | Emits operator cursor/active tab state for multi-user collaboration. |
| `ping` | — | Keep-alive heartbeat message. |

### 3. Gateway-to-Client Messages
| Message `type` | Payload Keys | Description |
| :--- | :--- | :--- |
| `agent_thought` | `thought`, `duration_ms` | Streams Claude 3.7 extended thinking blocks in real time. |
| `agent_response` | `reply`, `eventId`, `event` | Final synthesized response text, accompanied by audit event metadata. |
| `status` | `status`, `stage`, `nodeId` | Operational state updates (e.g., `planning`, `executing_tool`, `verifying`). |
| `terminal_data` | `taskId`, `data` | Raw VT100 stdout/stderr chunk for terminal rendering. |
| `presence_update` | `projectId`, `users` | Active collaborator list and view status. |
| `error` | `message`, `code`, `details` | Structured error envelopes with actionable diagnostic codes. |

---

## Authentication & Multi-Client Scoping

The Gateway generates and verifies scoped Bearer tokens:
- **Desktop Operator Token**: Full access to all tool tiers (Tier 1 CLI, Tier 2 Network, Tier 3 GUI).
- **Mobile Read-Only Token**: Constrained to event observation, terminal viewing, and plan status monitoring.
- **Revocation**: Instant token invalidation via `/auth/revoke` without service restart.

---

## Developer Commands

```bash
cd gateway
npm install
npm run dev      # Runs with tsx in watch mode
npm run build    # Compiles to /dist via tsc
```
