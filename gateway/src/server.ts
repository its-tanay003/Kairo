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

  if (toolId === "kali.exec.v1") {
    if (!args || typeof args !== "object") {
      return { valid: false, error: "kali.exec.v1 requires an arguments object" };
    }
    if (!args.command || typeof args.command !== "string" || args.command.trim().length === 0) {
      return { valid: false, error: "kali.exec.v1 parameter 'command' must be a non-empty string" };
    }
    if (args.args !== undefined && !Array.isArray(args.args)) {
      return { valid: false, error: "kali.exec.v1 parameter 'args' must be an array of strings" };
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

  if (url.pathname === "/model-center" || url.pathname === "/models") {
    try {
      const response = await fetch(`${ORCHESTRATOR_URL}/model-center`);
      const data = await response.json();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Failed to connect to orchestrator model-center", details: err.message }));
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

  // VM Sandbox routes: /vm/status, /vm/snapshots, /vm/snapshot, /vm/rollback, /vm/execute
  if (url.pathname.startsWith("/vm/")) {
    const subpath = url.pathname.replace("/vm/", "");
    try {
      if (req.method === "GET") {
        const response = await fetch(`${ORCHESTRATOR_URL}/vm/${subpath}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      } else if (req.method === "POST") {
        const body = await parseJsonBody(req);
        const response = await fetch(`${ORCHESTRATOR_URL}/vm/${subpath}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      }
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `VM Gateway Proxy error: ${err.message}` }));
      return;
    }
  }

  // Process routes: /process/pause/:id, /process/resume/:id, /process/stop/:id, /process/retry/:id, /process/tree/:id, /process/poll/:id
  if (url.pathname.startsWith("/process/")) {
    const subpath = url.pathname.replace("/process/", "");
    try {
      if (req.method === "GET") {
        const response = await fetch(`${ORCHESTRATOR_URL}/process/${subpath}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      } else if (req.method === "POST") {
        const body = await parseJsonBody(req);
        const response = await fetch(`${ORCHESTRATOR_URL}/process/${subpath}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      }
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `Process Proxy error: ${err.message}` }));
      return;
    }
  }

  // Artifacts routes: /artifacts/:taskId, /artifacts/verify
  if (url.pathname.startsWith("/artifacts")) {
    try {
      if (req.method === "GET") {
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      } else if (req.method === "POST") {
        const body = await parseJsonBody(req);
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      }
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `Artifacts Proxy error: ${err.message}` }));
      return;
    }
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

/**
 * Periodically polls new output chunks and process tree updates from orchestrator
 * and pushes them over WebSocket in real-time.
 */
function startStreamBroadcaster(taskId: string, targetWs?: WebSocket) {
  let seq = 0;
  let pollCount = 0;
  const maxPolls = 600; // 60s max polling duration

  const interval = setInterval(async () => {
    pollCount++;
    try {
      const resp = await fetch(`${ORCHESTRATOR_URL}/process/poll/${taskId}?since=${seq}`);
      if (!resp.ok) {
        if (pollCount > maxPolls) clearInterval(interval);
        return;
      }
      const data = (await resp.json()) as any;
      if (data.chunks && data.chunks.length > 0) {
        for (const chunk of data.chunks) {
          seq = Math.max(seq, chunk.seq);
          const msg = JSON.stringify({
            type: "terminal_stream",
            taskId,
            stream: chunk.stream,
            text: chunk.text,
            seq: chunk.seq,
            timestamp: chunk.timestamp,
          });
          if (targetWs && targetWs.readyState === WebSocket.OPEN) {
            targetWs.send(msg);
          } else {
            for (const s of sessions.values()) {
              if (s.ws.readyState === WebSocket.OPEN) s.ws.send(msg);
            }
          }
        }
      }

      if (data.tree) {
        const treeMsg = JSON.stringify({
          type: "process_tree_update",
          taskId,
          status: data.status,
          tree: data.tree,
          timestamp: new Date().toISOString(),
        });
        if (targetWs && targetWs.readyState === WebSocket.OPEN) {
          targetWs.send(treeMsg);
        } else {
          for (const s of sessions.values()) {
            if (s.ws.readyState === WebSocket.OPEN) s.ws.send(treeMsg);
          }
        }
      }

      if (data.completed || pollCount > maxPolls) {
        clearInterval(interval);
      }
    } catch {
      if (pollCount > maxPolls) clearInterval(interval);
    }
  }, 100);
}

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

      // Process Supervisor Controls via WebSocket: { type: "process_control", action: "pause"|"resume"|"stop"|"retry", taskId: "..." }
      if (payload.type === "process_control") {
        const action = payload.action;
        const taskId = payload.taskId || payload.task_id;
        if (!action || !taskId) {
          ws.send(JSON.stringify({ type: "error", error: "Missing action or taskId for process_control" }));
          return;
        }

        try {
          const ctrlResp = await fetch(`${ORCHESTRATOR_URL}/process/${action}/${taskId}`, { method: "POST" });
          const ctrlData = await ctrlResp.json();

          // If retried, re-start stream broadcaster for the task
          if (action === "retry") {
            startStreamBroadcaster(taskId, ws);
          }

          // Broadcast result
          const ctrlMsg = JSON.stringify({
            type: "process_control_result",
            action,
            taskId,
            result: ctrlData,
            timestamp: new Date().toISOString(),
          });
          for (const s of sessions.values()) {
            if (s.ws.readyState === WebSocket.OPEN) s.ws.send(ctrlMsg);
          }
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to issue process control ${action}: ${err.message}` }));
        }
        return;
      }

      // Query Process Tree via WebSocket: { type: "get_process_tree", taskId: "..." }
      if (payload.type === "get_process_tree" || payload.type === "process_tree") {
        const taskId = payload.taskId || payload.task_id || "";
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/process/tree/${taskId}`);
          const treeData = (await resp.json()) as any;
          ws.send(
            JSON.stringify({
              type: "process_tree_update",
              taskId: treeData.task_id || taskId,
              status: treeData.status,
              tree: treeData.nodes || [],
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to fetch process tree: ${err.message}` }));
        }
        return;
      }

      // Execute in Kali with live terminal streaming: { type: "kali_exec", command: "...", args: [...], taskId: "..." }
      if (payload.type === "kali_exec") {
        const taskId = payload.taskId || `task_kali_${randomUUID().slice(0, 8)}`;
        const command = payload.command || "uname";
        const args = payload.args || ["-a"];
        const cwd = payload.cwd || "/home/kali";
        const timeoutMs = payload.timeout_ms || 30000;
        const snapshotBefore = Boolean(payload.snapshot_before);

        ws.send(
          JSON.stringify({
            type: "status",
            status: "executing_kali_command",
            sessionId,
            taskId,
            text: `Executing '${command} ${args.join(" ")}' in Kali VM...`,
          })
        );

        // Start stream broadcaster immediately
        startStreamBroadcaster(taskId, ws);

        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/vm/execute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              task_id: taskId,
              session_id: sessionId,
              command,
              args,
              cwd,
              timeout_ms: timeoutMs,
              snapshot_before: snapshotBefore,
              rollback_after: Boolean(payload.rollback_after),
              rollback_on_failure: Boolean(payload.rollback_on_failure),
              resource_limits: payload.resource_limits,
              artifact_dir: payload.artifact_dir,
            }),
          });
          const result = (await resp.json()) as any;
          ws.send(
            JSON.stringify({
              type: "agent_response",
              sessionId,
              reply: `Kali VM execution of '${command}' completed (exit ${result.exit_code})`,
              toolExecuted: { id: "kali.exec.v1", name: "Kali VM Exec", version: "1.0.0" },
              execution: result,
              durationMs: result.duration_ms,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Kali exec failed: ${err.message}` }));
        }
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

        // Start live stream broadcaster for this tool execution
        startStreamBroadcaster(taskId, ws);

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

      if (payload.type === "get_model_center" || payload.type === "model_center") {
        try {
          const response = await fetch(`${ORCHESTRATOR_URL}/model-center`);
          const data = (await response.json()) as any;
          ws.send(
            JSON.stringify({
              type: "model_center_status",
              data,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to fetch model center status: ${err.message}`,
            })
          );
        }
        return;
      }

      if (payload.type === "get_vm_status" || payload.type === "vm_status") {
        try {
          const response = await fetch(`${ORCHESTRATOR_URL}/vm/status`);
          const data = (await response.json()) as any;
          ws.send(
            JSON.stringify({
              type: "vm_status",
              data,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to fetch VM status: ${err.message}`,
            })
          );
        }
        return;
      }

      if (payload.type === "vm_snapshot") {
        try {
          const response = await fetch(`${ORCHESTRATOR_URL}/vm/snapshot`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: payload.name, description: payload.description || "" }),
          });
          const data = (await response.json()) as any;
          ws.send(
            JSON.stringify({
              type: "vm_snapshot_result",
              data,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to create VM snapshot: ${err.message}`,
            })
          );
        }
        return;
      }

      if (payload.type === "vm_rollback") {
        try {
          const response = await fetch(`${ORCHESTRATOR_URL}/vm/rollback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: payload.name || "kairo_worker_ready" }),
          });
          const data = (await response.json()) as any;
          ws.send(
            JSON.stringify({
              type: "vm_rollback_result",
              data,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to rollback VM: ${err.message}`,
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
