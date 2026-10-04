import http from "http";
import { WebSocketServer, WebSocket } from "ws";
import { randomUUID } from "crypto";

const PORT = parseInt(process.env.PORT || "4000", 10);
const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://127.0.0.1:8000";

/**
 * Validates tool calls against minimal ToolSpec schemas before execution.
 */
function validateToolCall(toolId: string, args: any): { valid: boolean; error?: string } {
  if (toolId === "shell.run.v1") {
    if (!args || typeof args !== "object") {
      return { valid: false, error: "shell.run.v1 requires an arguments object" };
    }
    if (!args.command || typeof args.command !== "string" || args.command.trim().length === 0) {
      return { valid: false, error: "shell.run.v1 parameter 'command' must be a non-empty string" };
    }
    if (args.args !== undefined && !Array.isArray(args.args)) {
      return { valid: false, error: "shell.run.v1 parameter 'args' must be an array of strings" };
    }
    if (Array.isArray(args.args)) {
      for (const item of args.args) {
        if (typeof item !== "string" && typeof item !== "number") {
          return { valid: false, error: "shell.run.v1 args items must be strings" };
        }
      }
    }
    if (args.timeout_ms !== undefined && (typeof args.timeout_ms !== "number" || args.timeout_ms <= 0)) {
      return { valid: false, error: "shell.run.v1 parameter 'timeout_ms' must be a positive number" };
    }
    return { valid: true };
  }

  if (toolId === "hello_world") {
    return { valid: true };
  }

  if (toolId === "system_ping") {
    return { valid: true };
  }

  return { valid: true };
}

// HTTP server for health checks, kill switch & CORS
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

  // Kill switch HTTP proxy endpoint: POST /kill or /kill/:taskId
  if (req.method === "POST" && (url.pathname === "/kill" || url.pathname.startsWith("/kill/"))) {
    let taskId = "";
    if (url.pathname.startsWith("/kill/")) {
      taskId = url.pathname.replace("/kill/", "");
    } else {
      const body = await parseJsonBody(req);
      taskId = body.task_id || body.taskId || "";
    }

    if (!taskId) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Missing required parameter 'task_id'" }));
      return;
    }

    try {
      const killResp = await fetch(`${ORCHESTRATOR_URL}/kill/${taskId}`, { method: "POST" });
      const data = await killResp.json();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Kill switch error communicating with orchestrator", details: err.message }));
    }
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

function parseJsonBody(req: http.IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

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

      // Kill Switch via WebSocket: { type: "kill", taskId: "..." }
      if (payload.type === "kill") {
        const taskId = payload.taskId || payload.task_id;
        if (!taskId) {
          ws.send(JSON.stringify({ type: "error", error: "Missing taskId for kill switch" }));
          return;
        }

        try {
          const killResp = await fetch(`${ORCHESTRATOR_URL}/kill/${taskId}`, { method: "POST" });
          const killData = await killResp.json();
          ws.send(
            JSON.stringify({
              type: "kill_confirmed",
              taskId,
              result: killData,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to issue kill switch: ${err.message}` }));
        }
        return;
      }

      // Tool Call Execution: { type: "tool_call", tool: "shell.run.v1", args: {...} }
      if (payload.type === "tool_call") {
        const toolId = payload.tool || payload.tool_id;
        const toolArgs = payload.args || {};
        const customSessionId = payload.sessionId || sessionId;
        const taskId = payload.taskId || `task_${randomUUID().slice(0, 8)}`;

        // Gateway schema validation
        const valRes = validateToolCall(toolId, toolArgs);
        if (!valRes.valid) {
          ws.send(
            JSON.stringify({
              type: "validation_error",
              sessionId: customSessionId,
              tool: toolId,
              error: valRes.error,
              timestamp: new Date().toISOString(),
            })
          );
          return;
        }

        ws.send(
          JSON.stringify({
            type: "status",
            status: "executing_validated_tool",
            sessionId: customSessionId,
            taskId,
            tool: toolId,
            text: `Gateway validated ${toolId} schema. Executing via orchestrator...`,
          })
        );

        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: customSessionId,
              message: `Explicit tool invocation: ${toolId}`,
              task_id: taskId,
              explicit_tool: toolId,
              explicit_args: toolArgs,
            }),
          });

          if (!resp.ok) {
            throw new Error(`Orchestrator returned HTTP ${resp.status}`);
          }

          const result = (await resp.json()) as any;

          // Stream back rich tool card payload
          ws.send(
            JSON.stringify({
              type: "agent_response",
              sessionId: customSessionId,
              reply: result.reply,
              toolExecuted: result.tool_executed,
              execution: result.execution,
              eventId: result.event_id,
              event: result.event,
              durationMs: result.duration_ms,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              sessionId: customSessionId,
              error: `Tool execution failed: ${err.message}`,
              timestamp: new Date().toISOString(),
            })
          );
        }
        return;
      }

      // Standard Chat message
      if (payload.type === "chat" || payload.type === "message") {
        const content = payload.content || payload.text || payload.message || "Hello World";
        const customSessionId = payload.sessionId || sessionId;
        const taskId = payload.taskId || `task_${randomUUID().slice(0, 8)}`;

        ws.send(
          JSON.stringify({
            type: "status",
            status: "dispatching_to_orchestrator",
            sessionId: customSessionId,
            taskId,
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
              task_id: taskId,
              parent_event: payload.parentEvent,
            }),
          });

          if (!orchestratorResponse.ok) {
            throw new Error(`Orchestrator returned HTTP ${orchestratorResponse.status}`);
          }

          const result = (await orchestratorResponse.json()) as any;

          // Stream response & tool card info back to client
          ws.send(
            JSON.stringify({
              type: "agent_response",
              sessionId: customSessionId,
              reply: result.reply,
              toolExecuted: result.tool_executed,
              execution: result.execution,
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
          const data = (await response.json()) as any;
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
