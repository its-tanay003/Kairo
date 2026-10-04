# /gateway - Session Gateway (TypeScript)

Provides client connection management, session state tracking, and protocol translation between browser WebSockets and backend orchestrator services.

## Ports
- WebSocket & HTTP endpoint: `ws://localhost:4000` / `http://localhost:4000`

## Protocol
- **Client -> Gateway**:
  - `{ "type": "chat", "content": "Hello World", "sessionId": "..." }`
  - `{ "type": "ping" }`
  - `{ "type": "get_events" }`
- **Gateway -> Client**:
  - `{ "type": "handshake", "sessionId": "..." }`
  - `{ "type": "status", "status": "dispatching_to_orchestrator" }`
  - `{ "type": "agent_response", "reply": "...", "eventId": 12, "event": { ... } }`

## Commands
```bash
npm install
npm run dev
```
