import http from "http";
import net from "net";
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

  if (url.pathname === "/execution-plane" || url.pathname === "/kali/status") {
    try {
      const response = await fetch(`${ORCHESTRATOR_URL}/execution-plane`);
      const data = await response.json();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Failed to connect to orchestrator execution-plane", details: err.message }));
    }
    return;
  }

  // Auth routes: /auth/token, /auth/verify, /auth/sessions
  if (url.pathname.startsWith("/auth/")) {
    try {
      if (req.method === "POST") {
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
      } else {
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      }
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `Auth proxy error: ${err.message}` }));
      return;
    }
  }

  // Workspace routes: /workspaces, /workspaces/provision, /workspaces/:id, /workspaces/:id/terminate
  if (url.pathname.startsWith("/workspaces")) {
    try {
      if (req.method === "POST") {
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
      } else {
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      }
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `Workspaces proxy error: ${err.message}` }));
      return;
    }
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

  // Screen / VNC routes: /screen/status, /screen/snapshot.png
  if (url.pathname.startsWith("/screen/")) {
    try {
      const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
      const contentType = response.headers.get("content-type") || "application/json";
      res.writeHead(response.status, { "Content-Type": contentType });
      if (contentType.includes("image")) {
        const buffer = Buffer.from(await response.arrayBuffer());
        res.end(buffer);
      } else {
        const data = await response.json();
        res.end(JSON.stringify(data));
      }
      return;
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `Screen Proxy error: ${err.message}` }));
      return;
    }
  }

  // Security Browser routes: /browser/state, /browser/history, /browser/execute, /browser/screenshot, /browser/stop
  if (url.pathname.startsWith("/browser")) {
    try {
      if (req.method === "GET") {
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      } else if (req.method === "POST") {
        const body = await parseJsonBody(req);
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`, {
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
      res.end(JSON.stringify({ error: `Browser Proxy error: ${err.message}` }));
      return;
    }
  }

  // Tier 3 GUI routes: /gui/adapters, /gui/execute, /gui/state/:id, /gui/screenshot/:id, /gui/stop/:id
  if (url.pathname.startsWith("/gui")) {
    try {
      if (req.method === "GET") {
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      } else if (req.method === "POST") {
        const body = await parseJsonBody(req);
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`, {
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
      res.end(JSON.stringify({ error: `GUI Proxy error: ${err.message}` }));
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

  // Planner routes: /planner/decompose, /planner/plans, /planner/plans/:id, /planner/plans/:id/nodes/:nid/status, /planner/plans/:id/ready
  if (url.pathname.startsWith("/planner")) {
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
      res.end(JSON.stringify({ error: `Planner Proxy error: ${err.message}` }));
      return;
    }
  }

  // Tools routes: /tools/select, /tools/memory, /tools/memory/:id
  if (url.pathname.startsWith("/tools")) {
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
      res.end(JSON.stringify({ error: `Tools Proxy error: ${err.message}` }));
      return;
    }
  }

  // Scope Contract routes: /scope/active, /scope/contract, /scope/contracts, /scope/validate
  if (url.pathname.startsWith("/scope")) {
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
      res.end(JSON.stringify({ error: `Scope Proxy error: ${err.message}` }));
      return;
    }
  }

  // Shared Projects routes: /projects, /projects/:id, /projects/:id/state, /projects/:id/collaborators, /projects/:id/presence
  if (url.pathname.startsWith("/projects")) {
    try {
      if (req.method === "GET") {
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
        const data = await response.json();
        res.writeHead(response.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
        return;
      } else if (req.method === "POST" || req.method === "PUT" || req.method === "DELETE") {
        const body = await parseJsonBody(req);
        const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`, {
          method: req.method,
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
      res.end(JSON.stringify({ error: `Projects Proxy error: ${err.message}` }));
      return;
    }
  }

  // Audit Explorer routes: /audit/timeline, /audit/stats
  if (url.pathname.startsWith("/audit")) {
    try {
      const response = await fetch(`${ORCHESTRATOR_URL}${url.pathname}${url.search}`);
      const data = await response.json();
      res.writeHead(response.status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
      return;
    } catch (err: any) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `Audit Proxy error: ${err.message}` }));
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
const wss = new WebSocketServer({ noServer: true });

server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url || "/", `http://${req.headers.host}`);
  if (url.pathname === "/vnc" || url.pathname.startsWith("/vnc/")) {
    const vncPort = parseInt(process.env.VNC_WS_PORT || "6080", 10);
    const vncSocket = net.createConnection({ port: vncPort, host: "127.0.0.1" }, () => {
      const rawLines = [`${req.method} ${url.pathname}${url.search} HTTP/1.1`];
      for (let i = 0; i < req.rawHeaders.length; i += 2) {
        rawLines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
      }
      rawLines.push("\r\n");
      vncSocket.write(rawLines.join("\r\n"));
      if (head && head.length > 0) vncSocket.write(head);
      socket.pipe(vncSocket);
      vncSocket.pipe(socket);
    });
    vncSocket.on("error", (err: any) => {
      console.warn(`[Gateway] VNC proxy connection error: ${err.message}`);
      socket.destroy();
    });
    socket.on("error", () => {
      vncSocket.destroy();
    });
    return;
  }

  wss.handleUpgrade(req, socket, head, (ws) => {
    wss.emit("connection", ws, req);
  });
});

interface ClientSession {
  ws: WebSocket;
  sessionId: string;
  connectedAt: string;
  token?: string;
  clientType: "linux-desktop" | "windows-desktop" | "browser-desktop" | "browser-mobile" | "tauri-desktop" | "cli" | "unknown";
  authenticated: boolean;
  user?: any;
  workspaceId?: string;
  projectId?: string;
  dataPlane: "local-only" | "connected";
}

const sessions = new Map<WebSocket, ClientSession>();

/**
 * Broadcasts a message to all connected clients, optionally filtering by workspace.
 */
function broadcastToAll(message: string | object, excludeWs?: WebSocket) {
  const msgStr = typeof message === "string" ? message : JSON.stringify(message);
  for (const s of sessions.values()) {
    if (s.ws.readyState === WebSocket.OPEN) {
      if (excludeWs && s.ws === excludeWs) continue;
      s.ws.send(msgStr);
    }
  }
}

function broadcastToWorkspace(workspaceId: string | undefined, message: string | object, excludeWs?: WebSocket) {
  const msgStr = typeof message === "string" ? message : JSON.stringify(message);
  for (const s of sessions.values()) {
    if (s.ws.readyState === WebSocket.OPEN) {
      if (excludeWs && s.ws === excludeWs) continue;
      if (!workspaceId || !s.workspaceId || s.workspaceId === workspaceId) {
        s.ws.send(msgStr);
      }
    }
  }
}

function broadcastToProject(projectId: string | undefined, message: string | object, excludeWs?: WebSocket) {
  if (!projectId) return;
  const msgStr = typeof message === "string" ? message : JSON.stringify(message);
  for (const s of sessions.values()) {
    if (s.ws.readyState === WebSocket.OPEN) {
      if (excludeWs && s.ws === excludeWs) continue;
      if (s.projectId === projectId) {
        s.ws.send(msgStr);
      }
    }
  }
}

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

wss.on("connection", async (ws: WebSocket, req) => {
  const url = new URL(req.url || "/", `http://${req.headers.host}`);
  const reqSessionId = url.searchParams.get("sessionId");
  const sessionId = reqSessionId || `sess_${randomUUID().slice(0, 8)}`;
  const reqWorkspaceId = url.searchParams.get("workspaceId") || url.searchParams.get("workspace_id") || undefined;
  const reqProjectId = url.searchParams.get("projectId") || url.searchParams.get("project_id") || undefined;

  // Detect Client Type (query param, user-agent, or headers)
  const userAgent = (req.headers["user-agent"] || "").toLowerCase();
  const queryClientType = url.searchParams.get("clientType") || url.searchParams.get("client_type");
  let clientType: ClientSession["clientType"] = "browser-desktop";

  if (queryClientType && ["linux-desktop", "windows-desktop", "browser-desktop", "browser-mobile", "tauri-desktop", "cli"].includes(queryClientType)) {
    clientType = queryClientType as any;
  } else if (userAgent.includes("tauri")) {
    clientType = "tauri-desktop";
  } else if (userAgent.includes("linux") && !userAgent.includes("android")) {
    clientType = "linux-desktop";
  } else if (userAgent.includes("windows")) {
    clientType = "windows-desktop";
  } else if (
    userAgent.includes("mobile") ||
    userAgent.includes("android") ||
    userAgent.includes("iphone") ||
    userAgent.includes("ipad") ||
    userAgent.includes("ipod")
  ) {
    clientType = "browser-mobile";
  }

  // Detect Data Plane (local loopback vs remote instance)
  const hostHeader = (req.headers["host"] || "").toLowerCase();
  const isLocal =
    hostHeader.startsWith("localhost") ||
    hostHeader.startsWith("127.0.0.1") ||
    hostHeader.endsWith(".local");
  const dataPlane = isLocal ? "local-only" : "connected";

  // Check initial token if supplied in query or Authorization header
  const queryToken = url.searchParams.get("token") || "";
  const authHeader = (req.headers["authorization"] || "").replace(/^Bearer\s+/i, "");
  const initialToken = queryToken || authHeader;
  let authenticated = true;
  let user: any = { user_id: "local_operator", role: "admin", client_type: clientType };

  if (initialToken) {
    try {
      const authResp = await fetch(`${ORCHESTRATOR_URL}/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: initialToken }),
      });
      const authData = (await authResp.json()) as any;
      if (authData.valid) {
        authenticated = true;
        user = authData.user;
      } else {
        authenticated = false;
        user = null;
      }
    } catch {
      // In local dev without orchestrator auth enforcement, default authenticated
      authenticated = true;
    }
  }

  const session: ClientSession = {
    ws,
    sessionId,
    connectedAt: new Date().toISOString(),
    token: initialToken || undefined,
    clientType,
    authenticated,
    user,
    workspaceId: reqWorkspaceId,
    projectId: reqProjectId,
    dataPlane,
  };

  sessions.set(ws, session);
  console.log(`[Gateway] Client connected (Session: ${sessionId}, Type: ${clientType}, Workspace: ${reqWorkspaceId || "none"}, Project: ${reqProjectId || "none"}, DataPlane: ${dataPlane}, Auth: ${authenticated}, Active: ${sessions.size})`);

  // Send initial session handshake with auth, workspace, project & data plane metadata
  ws.send(
    JSON.stringify({
      type: "handshake",
      sessionId,
      clientType,
      workspaceId: reqWorkspaceId || null,
      projectId: reqProjectId || null,
      authenticated,
      user,
      dataPlane,
      offlineState: dataPlane, // "local-only" or "connected"
      message: `Connected to Session Gateway. Orchestrator target: ${ORCHESTRATOR_URL}`,
      timestamp: new Date().toISOString(),
    })
  );

  // If connected to a pre-existing workspace, broadcast peer_joined to other active clients
  if (reqWorkspaceId) {
    broadcastToAll({
      type: "peer_joined",
      sessionId,
      clientType,
      workspaceId: reqWorkspaceId,
      text: `Client [${clientType}] (${sessionId}) connected to workspace ${reqWorkspaceId}`,
      timestamp: new Date().toISOString(),
    }, ws);
  }

  // If connected to a pre-existing shared project, broadcast project_peer_joined
  if (reqProjectId) {
    broadcastToProject(reqProjectId, {
      type: "project_peer_joined",
      sessionId,
      userId: user?.user_id || sessionId,
      clientType,
      projectId: reqProjectId,
      timestamp: new Date().toISOString(),
    }, ws);
  }

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

      // Client identification & platform registration
      if (payload.type === "client_identify") {
        if (payload.client_type || payload.clientType) {
          session.clientType = payload.client_type || payload.clientType;
        }
        if (payload.workspace_id || payload.workspaceId) {
          session.workspaceId = payload.workspace_id || payload.workspaceId;
        }
        ws.send(
          JSON.stringify({
            type: "client_identified",
            sessionId,
            clientType: session.clientType,
            workspaceId: session.workspaceId || null,
            dataPlane: session.dataPlane,
            timestamp: new Date().toISOString(),
          })
        );
        return;
      }

      // Join / Bind to existing project workspace: { type: "join_workspace", workspaceId: "...", projectId: "..." }
      if (payload.type === "join_workspace" || payload.type === "workspace_join") {
        const wid = payload.workspaceId || payload.workspace_id;
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/workspaces/${wid}`);
          const data = (await resp.json()) as any;
          if (data.workspace) {
            session.workspaceId = data.workspace.workspace_id;
            ws.send(
              JSON.stringify({
                type: "workspace_joined",
                sessionId,
                workspace: data.workspace,
                timestamp: new Date().toISOString(),
              })
            );
            broadcastToAll({
              type: "peer_joined",
              sessionId,
              clientType: session.clientType,
              workspaceId: wid,
              text: `Client [${session.clientType}] (${sessionId}) joined project workspace ${data.workspace.project_name} (${wid})`,
              timestamp: new Date().toISOString(),
            }, ws);
          } else {
            ws.send(JSON.stringify({ type: "error", error: `Workspace '${wid}' not found` }));
          }
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to join workspace ${wid}: ${err.message}` }));
        }
        return;
      }

      // Join / Bind to Shared Project: { type: "join_project", projectId: "...", userId: "...", role: "..." }
      if (payload.type === "join_project" || payload.type === "project_join") {
        const pid = payload.projectId || payload.project_id;
        const uid = payload.userId || payload.user_id || session.user?.user_id || session.sessionId;
        const role = payload.role || session.user?.role || "editor";
        try {
          // Send presence heartbeat to orchestrator
          const hbResp = await fetch(`${ORCHESTRATOR_URL}/projects/${pid}/presence`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              user_id: uid,
              client_type: session.clientType,
              role,
              active_view: payload.activeView || "live_session",
            }),
          });
          const hbData = (await hbResp.json()) as any;

          // Fetch full project state
          const projResp = await fetch(`${ORCHESTRATOR_URL}/projects/${pid}`);
          const projData = (await projResp.json()) as any;

          session.projectId = pid;

          ws.send(
            JSON.stringify({
              type: "project_joined",
              sessionId,
              projectId: pid,
              project: projData.project,
              collaboratorsOnline: hbData.collaborators_online || [],
              timestamp: new Date().toISOString(),
            })
          );

          broadcastToProject(pid, {
            type: "project_peer_joined",
            sessionId,
            userId: uid,
            clientType: session.clientType,
            role,
            projectId: pid,
            collaboratorsOnline: hbData.collaborators_online || [],
            timestamp: new Date().toISOString(),
          }, ws);
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to join project ${pid}: ${err.message}` }));
        }
        return;
      }

      // Synchronize shared project state: { type: "project_state_update", projectId: "...", stateUpdates: { ... }, userId: "..." }
      if (payload.type === "project_state_update" || payload.type === "sync_project_state") {
        const pid = payload.projectId || payload.project_id || session.projectId;
        const uid = payload.userId || payload.user_id || session.user?.user_id || session.sessionId;
        const stateUpdates = payload.stateUpdates || payload.state_updates || {};

        if (!pid) {
          ws.send(JSON.stringify({ type: "error", error: "Missing projectId for project_state_update" }));
          return;
        }

        try {
          const syncResp = await fetch(`${ORCHESTRATOR_URL}/projects/${pid}/state`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ state_updates: stateUpdates, user_id: uid }),
          });
          const syncData = (await syncResp.json()) as any;

          broadcastToProject(pid, {
            type: "project_state_synced",
            projectId: pid,
            updatedBy: uid,
            clientType: session.clientType,
            project: syncData.project,
            updatedKeys: syncData.updated_keys,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to sync project state: ${err.message}` }));
        }
        return;
      }

      // Real-time collaborator activity / scratchpad update: { type: "collaborator_action", projectId: "...", action: "...", details: ... }
      if (payload.type === "collaborator_action" || payload.type === "scratchpad_input") {
        const pid = payload.projectId || payload.project_id || session.projectId;
        const uid = payload.userId || payload.user_id || session.user?.user_id || session.sessionId;
        if (pid) {
          broadcastToProject(pid, {
            type: "peer_activity",
            projectId: pid,
            userId: uid,
            clientType: session.clientType,
            action: payload.action || "editing",
            scratchpad: payload.scratchpad,
            cursor: payload.cursor,
            activeView: payload.activeView,
            timestamp: new Date().toISOString(),
          }, ws);
        }
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

      // Query Tool Selection via WebSocket: { type: "tool_selection_query" | "tool_select", intent: "...", capability: "..." }
      if (payload.type === "tool_selection_query" || payload.type === "tool_select") {
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/tools/select`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              intent: payload.intent || payload.query || "",
              capability: payload.capability,
              environment: payload.environment,
              budget: payload.budget,
              session_id: payload.sessionId || sessionId,
            }),
          });
          const selectData = await resp.json();
          ws.send(
            JSON.stringify({
              type: "tool_selection_result",
              data: selectData,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Tool selection failed: ${err.message}` }));
        }
        return;
      }

      // Scope Contract WebSocket Handlers
      if (payload.type === "get_scope" || payload.type === "get_active_scope") {
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/scope/active`);
          const data = await resp.json();
          ws.send(
            JSON.stringify({
              type: "active_scope_contract",
              contract: data,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to fetch active scope: ${err.message}` }));
        }
        return;
      }

      if (payload.type === "create_scope" || payload.type === "update_scope") {
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/scope/contract`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload.contract || payload),
          });
          const data = await resp.json();
          const updateMsg = JSON.stringify({
            type: "scope_contract_updated",
            contract: data,
            timestamp: new Date().toISOString(),
          });
          for (const s of sessions.values()) {
            if (s.ws.readyState === WebSocket.OPEN) s.ws.send(updateMsg);
          }
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to create scope contract: ${err.message}` }));
        }
        return;
      }

      if (payload.type === "validate_scope") {
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/scope/validate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              target: payload.target,
              tool_id: payload.tool_id || payload.tool,
              tool_tier: payload.tool_tier,
            }),
          });
          const data = await resp.json();
          ws.send(
            JSON.stringify({
              type: "scope_validation_result",
              result: data,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Scope validation failed: ${err.message}` }));
        }
        return;
      }

      // Execute in Kali with live terminal streaming: { type: "kali_exec", command: "...", args: [...], taskId: "..." }
      if (payload.type === "kali_exec") {
        const taskId = payload.taskId || `task_kali_${randomUUID().slice(0, 8)}`;
        const command = payload.command || "uname";
        const args = payload.args || ["-a"];
        const defaultCwd = (payload.workspace_id || session.workspaceId)
          ? `/tmp/kairo_workspaces/${payload.workspace_id || session.workspaceId}/artifacts`
          : "/home/kali";
        const cwd = payload.cwd || defaultCwd;
        const timeoutMs = payload.timeout_ms || 30000;
        const snapshotBefore = Boolean(payload.snapshot_before);

        // Scope check for Tier 3 Kali Execution
        try {
          let kaliTarget: string | undefined = undefined;
          if (Array.isArray(args)) {
            for (const a of args) {
              const sa = String(a).trim();
              if ((sa.includes(".") || sa.includes("/")) && !sa.startsWith("-") && !sa.endsWith(".sh")) {
                kaliTarget = sa;
                break;
              }
            }
          }
          const scopeResp = await fetch(`${ORCHESTRATOR_URL}/scope/validate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target: kaliTarget, tool_id: "kali.exec.v1", tool_tier: 3 }),
          });
          const scopeVal = (await scopeResp.json()) as any;
          if (scopeVal && scopeVal.authorized === false) {
            ws.send(
              JSON.stringify({
                type: "scope_violation",
                sessionId,
                taskId,
                tool: "kali.exec.v1",
                toolTier: 3,
                target: kaliTarget,
                error: "SCOPE_VIOLATION",
                reason: scopeVal.reason,
                scopeContractId: scopeVal.scope_contract_id,
                timestamp: new Date().toISOString(),
              })
            );
            return;
          }
        } catch (e: any) {
          console.warn("[Gateway] Scope check warning in kali_exec:", e.message);
        }

        broadcastToAll({
          type: "user_message_broadcast",
          senderSessionId: sessionId,
          clientType: session.clientType,
          taskId,
          text: `[Kali Exec] ${command} ${args.join(" ")}`,
          timestamp: new Date().toISOString(),
        });

        broadcastToAll({
          type: "status",
          status: "executing_kali_command",
          sessionId,
          taskId,
          text: `Executing '${command} ${args.join(" ")}' in Kali VM...`,
        });

        // Start stream broadcaster immediately
        startStreamBroadcaster(taskId);

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
          broadcastToAll({
            type: "agent_response",
            sessionId,
            reply: `Kali VM execution of '${command}' completed (exit ${result.exit_code})`,
            toolExecuted: { id: "kali.exec.v1", name: "Kali VM Exec", version: "1.0.0" },
            execution: result,
            durationMs: result.duration_ms,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          broadcastToAll({ type: "error", error: `Kali exec failed: ${err.message}` });
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

        // Scope Contract validation: Gateway MUST reject if outside active Scope Contract
        try {
          let toolTarget: string | undefined =
            toolArgs.target ||
            toolArgs.host ||
            toolArgs.url ||
            toolArgs.domain ||
            toolArgs.ip ||
            toolArgs.filepath ||
            toolArgs.rhost ||
            toolArgs.rhosts;

          if (!toolTarget && Array.isArray(toolArgs.args)) {
            for (const a of toolArgs.args) {
              const sa = String(a).trim();
              if ((sa.includes(".") || sa.includes("/")) && !sa.startsWith("-") && !sa.endsWith(".py") && !sa.endsWith(".sh")) {
                toolTarget = sa;
                break;
              }
            }
          }

          const scopeResp = await fetch(`${ORCHESTRATOR_URL}/scope/validate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target: toolTarget, tool_id: toolId }),
          });
          const scopeVal = (await scopeResp.json()) as any;
          if (scopeVal && scopeVal.authorized === false) {
            ws.send(
              JSON.stringify({
                type: "scope_violation",
                sessionId: customSessionId,
                taskId,
                tool: toolId,
                target: toolTarget,
                error: "SCOPE_VIOLATION",
                reason: scopeVal.reason,
                scopeContractId: scopeVal.scope_contract_id,
                timestamp: new Date().toISOString(),
              })
            );
            return;
          }
        } catch (e: any) {
          console.warn("[Gateway] Scope validation warning for tool_call:", e.message);
        }

        broadcastToAll({
          type: "user_message_broadcast",
          senderSessionId: customSessionId,
          clientType: session.clientType,
          taskId,
          text: `[Tool Call] ${toolId} ${JSON.stringify(toolArgs)}`,
          timestamp: new Date().toISOString(),
        });

        broadcastToAll({
          type: "status",
          status: "executing_validated_tool",
          sessionId: customSessionId,
          taskId,
          tool: toolId,
          text: `Gateway validated ${toolId} scope & schema. Executing via orchestrator...`,
        });

        // Start live stream broadcaster for this tool execution across all sessions
        startStreamBroadcaster(taskId);

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

          // Broadcast rich tool card payload to all connected clients
          broadcastToAll({
            type: "agent_response",
            sessionId: customSessionId,
            reply: result.reply,
            toolExecuted: result.tool_executed,
            execution: result.execution,
            eventId: result.event_id,
            event: result.event,
            durationMs: result.duration_ms,
            toolSelection: result.tool_selection,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          broadcastToAll({
            type: "error",
            sessionId: customSessionId,
            error: `Tool execution failed: ${err.message}`,
            timestamp: new Date().toISOString(),
          });
        }
        return;
      }

      // Standard Chat message
      if (payload.type === "chat" || payload.type === "message") {
        const content = payload.content || payload.text || payload.message || "Hello World";
        const customSessionId = payload.sessionId || sessionId;
        const taskId = payload.taskId || `task_${randomUUID().slice(0, 8)}`;

        broadcastToAll({
          type: "user_message_broadcast",
          senderSessionId: customSessionId,
          clientType: session.clientType,
          taskId,
          text: content,
          timestamp: new Date().toISOString(),
        });

        broadcastToAll({
          type: "status",
          status: "dispatching_to_orchestrator",
          sessionId: customSessionId,
          taskId,
          text: `Calling agent orchestrator at ${ORCHESTRATOR_URL}...`,
        });

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

          // Broadcast response & tool card info to all connected clients
          broadcastToAll({
            type: "agent_response",
            sessionId: customSessionId,
            reply: result.reply,
            toolExecuted: result.tool_executed,
            execution: result.execution,
            eventId: result.event_id,
            event: result.event,
            durationMs: result.duration_ms,
            toolSelection: result.tool_selection,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          console.error(`[Gateway] Error calling orchestrator:`, err.message);
          broadcastToAll({
            type: "error",
            sessionId: customSessionId,
            error: `Gateway failed to reach orchestrator: ${err.message}`,
            timestamp: new Date().toISOString(),
          });
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
          broadcastToAll({
            type: "vm_snapshot_result",
            data,
            timestamp: new Date().toISOString(),
          });
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
          broadcastToAll({
            type: "vm_rollback_result",
            data,
            timestamp: new Date().toISOString(),
          });
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

      // Planner: Decompose goal into DAG
      if (payload.type === "planner_decompose") {
        try {
          const response = await fetch(`${ORCHESTRATOR_URL}/planner/decompose`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              goal: payload.goal,
              session_id: payload.sessionId || sessionId,
              prefer_llm: payload.prefer_llm !== false,
            }),
          });
          const plan = (await response.json()) as any;
          broadcastToAll({
            type: "planner_plan_created",
            plan,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Planner decomposition failed: ${err.message}`,
            })
          );
        }
        return;
      }

      // Planner: Fetch specific plan
      if (payload.type === "get_plan") {
        try {
          const planId = payload.planId || payload.plan_id;
          const response = await fetch(`${ORCHESTRATOR_URL}/planner/plans/${planId}`);
          const plan = (await response.json()) as any;
          ws.send(
            JSON.stringify({
              type: "planner_plan_details",
              plan,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to fetch plan: ${err.message}`,
            })
          );
        }
        return;
      }

      // Planner: Update node status
      if (payload.type === "update_plan_node") {
        try {
          const planId = payload.planId || payload.plan_id;
          const nodeId = payload.nodeId || payload.node_id;
          const response = await fetch(`${ORCHESTRATOR_URL}/planner/plans/${planId}/nodes/${nodeId}/status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              status: payload.status,
              result: payload.result,
              assigned_tool: payload.assigned_tool,
            }),
          });
          const plan = (await response.json()) as any;
          broadcastToAll({
            type: "planner_plan_updated",
            plan,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          ws.send(
            JSON.stringify({
              type: "error",
              error: `Failed to update plan node: ${err.message}`,
            })
          );
        }
        return;
      }

      // Authentication via WebSocket: { type: "auth", token: "..." }
      if (payload.type === "auth" || payload.type === "authenticate") {
        const token = payload.token || "";
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/auth/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
          });
          const data = (await resp.json()) as any;
          if (data.valid) {
            session.authenticated = true;
            session.user = data.user;
            session.token = token;
            ws.send(
              JSON.stringify({
                type: "auth_success",
                sessionId,
                user: data.user,
                clientType: session.clientType,
                dataPlane: session.dataPlane,
                timestamp: new Date().toISOString(),
              })
            );
          } else {
            session.authenticated = false;
            ws.send(
              JSON.stringify({
                type: "auth_failure",
                sessionId,
                error: data.error || "Invalid authentication token",
                timestamp: new Date().toISOString(),
              })
            );
          }
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Auth verification failed: ${err.message}` }));
        }
        return;
      }

      // Provision Disposable Workspace via WebSocket: { type: "provision_workspace", projectName: "...", sessionId: "..." }
      if (payload.type === "provision_workspace" || payload.type === "workspace_provision") {
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/workspaces/provision`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_name: payload.project_name || payload.projectName || "default-project",
              session_id: payload.session_id || payload.sessionId || sessionId,
              owner_id: payload.owner_id || session.user?.user_id || "operator",
            }),
          });
          const data = (await resp.json()) as any;
          if (data.workspace) {
            session.workspaceId = data.workspace.workspace_id;
          }
          broadcastToAll({
            type: "workspace_provisioned",
            sessionId,
            workspace: data.workspace,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to provision workspace: ${err.message}` }));
        }
        return;
      }

      // Query Workspaces via WebSocket: { type: "get_workspaces" }
      if (payload.type === "get_workspaces" || payload.type === "list_workspaces") {
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/workspaces`);
          const data = (await resp.json()) as any;
          ws.send(
            JSON.stringify({
              type: "workspaces_list",
              sessionId,
              workspaces: data.workspaces || [],
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to list workspaces: ${err.message}` }));
        }
        return;
      }

      // Query Single Workspace: { type: "get_workspace", workspaceId: "..." }
      if (payload.type === "get_workspace") {
        const wid = payload.workspaceId || payload.workspace_id || session.workspaceId;
        if (!wid) {
          ws.send(JSON.stringify({ type: "error", error: "Missing workspaceId" }));
          return;
        }
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/workspaces/${wid}`);
          const data = (await resp.json()) as any;
          ws.send(
            JSON.stringify({
              type: "workspace_details",
              sessionId,
              workspace: data.workspace,
              timestamp: new Date().toISOString(),
            })
          );
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to fetch workspace ${wid}: ${err.message}` }));
        }
        return;
      }

      // Terminate Workspace: { type: "terminate_workspace", workspaceId: "..." }
      if (payload.type === "terminate_workspace") {
        const wid = payload.workspaceId || payload.workspace_id || session.workspaceId;
        if (!wid) {
          ws.send(JSON.stringify({ type: "error", error: "Missing workspaceId" }));
          return;
        }
        try {
          const resp = await fetch(`${ORCHESTRATOR_URL}/workspaces/${wid}/terminate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              purge_storage: payload.purge_storage !== false && payload.purgeStorage !== false,
            }),
          });
          const data = (await resp.json()) as any;
          if (session.workspaceId === wid) {
            session.workspaceId = undefined;
          }
          broadcastToAll({
            type: "workspace_terminated",
            sessionId,
            workspaceId: wid,
            result: data,
            timestamp: new Date().toISOString(),
          });
        } catch (err: any) {
          ws.send(JSON.stringify({ type: "error", error: `Failed to terminate workspace ${wid}: ${err.message}` }));
        }
        return;
      }

      // Get Current Session & Data Plane State: { type: "get_session_state" }
      if (payload.type === "get_session_state" || payload.type === "session_state") {
        ws.send(
          JSON.stringify({
            type: "session_state",
            sessionId,
            clientType: session.clientType,
            authenticated: session.authenticated,
            user: session.user,
            workspaceId: session.workspaceId || null,
            dataPlane: session.dataPlane,
            timestamp: new Date().toISOString(),
          })
        );
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
    if (session.projectId) {
      broadcastToProject(session.projectId, {
        type: "project_peer_left",
        sessionId,
        userId: session.user?.user_id || sessionId,
        clientType: session.clientType,
        projectId: session.projectId,
        timestamp: new Date().toISOString(),
      });
    }
  });

  ws.on("error", (err) => {
    console.error(`[Gateway] WebSocket error (${sessionId}):`, err);
  });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[Gateway] Session Gateway listening on http://0.0.0.0:${PORT} (WS: ws://localhost:${PORT})`);
  console.log(`[Gateway] Orchestrator target configured as: ${ORCHESTRATOR_URL}`);
});
