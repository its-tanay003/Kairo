import http from "http";
import { WebSocketServer, WebSocket } from "ws";
import { randomUUID } from "crypto";

const PORT = parseInt(process.env.PORT || "4000", 10);
const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://127.0.0.1:8000";

// HTTP server for health checks & CORS
const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url || "/", `http://${req.headers.host}`);

  if (url.pathname === "/health" || url.pathname === "/") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        service: "session-gateway",
        status: "healthy",
        wsPort: PORT,
        orchestratorUrl: ORCHESTRATOR_URL,
        activeClients: wss.clients.size,
      })
    );
    return;
  }

  if (url.pathname === "/events") {
    try {
      const response = await fetch(`${ORCHESTRATOR_URL}/events`);
      const data = await response.json();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Failed to connect to orchestrator", details: err.message }));
    }
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not Found" }));
});

// WebSocket Server attached to the HTTP server
const wss = new WebSocketServer({ server });

interface ClientSession {
  ws: WebSocket;
  sessionId: string;
  connectedAt: string;
}

const sessions = new Map<WebSocket, ClientSession>();

wss.on("connection", (ws: WebSocket, req) => {
  const url = new URL(req.url || "/", `http://${req.headers.host}`);
  const reqSessionId = url.searchParams.get("sessionId");
  const sessionId = reqSessionId || `sess_${randomUUID().slice(0, 8)}`;

  const session: ClientSession = {
    ws,
    sessionId,
    connectedAt: new Date().toISOString(),
  };

  sessions.set(ws, session);
  console.log(`[Gateway] Client connected (Session: ${sessionId}, Active: ${sessions.size})`);

  // Send initial session handshake
  ws.send(
    JSON.stringify({
      type: "handshake",
      sessionId,
      message: `Connected to Gateway WebSocket server. Orchestrator target: ${ORCHESTRATOR_URL}`,
      timestamp: new Date().toISOString(),
    })
  );

  ws.on("message", async (data: Buffer | string) => {
    try {
      const rawText = data.toString();
      const payload = JSON.parse(rawText);

      console.log(`[Gateway] Received message from ${sessionId}:`, payload);

      if (payload.type === "ping") {
        ws.send(
          JSON.stringify({
            type: "pong",
            timestamp: new Date().toISOString(),
          })
        );
        return;
      }

      if (payload.type === "chat" || payload.type === "message") {
        const content = payload.content || payload.text || payload.message || "Hello World";
        const customSessionId = payload.sessionId || sessionId;

        // Notify client that request was forwarded
        ws.send(
          JSON.stringify({
            type: "status",
            status: "dispatching_to_orchestrator",
            sessionId: customSessionId,
            text: `Calling agent orchestrator at ${ORCHESTRATOR_URL}...`,
          })
        );

        try {
          const orchestratorResponse = await fetch(`${ORCHESTRATOR_URL}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: customSessionId,
              message: content,
              task_id: payload.taskId,
              parent_event: payload.parentEvent,
            }),
          });

          if (!orchestratorResponse.ok) {
            throw new Error(`Orchestrator returned HTTP ${orchestratorResponse.status}`);
          }

          const result = await orchestratorResponse.json();

          // Stream orchestrator response and confirmed SQLite event back to client
          ws.send(
            JSON.stringify({
              type: "agent_response",
              sessionId: customSessionId,
              reply: result.reply,
              toolExecuted: result.tool_executed,
              eventId: result.event_id,
              event: result.event,
              durationMs: result.duration_ms,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          console.error(`[Gateway] Error calling orchestrator:`, err.message);
          ws.send(
            JSON.stringify({
              type: "error",
              sessionId: customSessionId,
              error: `Gateway failed to reach orchestrator: ${err.message}`,
              timestamp: new Date().toISOString(),
            })
          );
        }
        return;
      }

      if (payload.type === "get_events") {
        try {
          const response = await fetch(`${ORCHESTRATOR_URL}/events?session_id=${sessionId}`);
          const data = await response.json();
          ws.send(
            JSON.stringify({
              type: "events_list",
              events: data.events,
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to fetch events: ${err.message}`,
            })
          );
        }
        return;
      }

      // Default fallback echo
      ws.send(
        JSON.stringify({
          type: "echo",
          sessionId,
          payload,
          timestamp: new Date().toISOString(),
        })
      );
    } catch (err: any) {
      console.error("[Gateway] Message error:", err);
      ws.send(
        JSON.stringify({
          type: "error",
          error: "Malformed JSON message",
          details: err.message,
        })
      );
    }
  });

  ws.on("close", () => {
    sessions.delete(ws);
    console.log(`[Gateway] Client disconnected (${sessionId}). Active: ${sessions.size}`);
  });

  ws.on("error", (err) => {
    console.error(`[Gateway] WebSocket error (${sessionId}):`, err);
  });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[Gateway] Session Gateway listening on http://0.0.0.0:${PORT} (WS: ws://localhost:${PORT})`);
  console.log(`[Gateway] Orchestrator target configured as: ${ORCHESTRATOR_URL}`);
});
