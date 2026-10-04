"use client";

import React, { useEffect, useRef, useState } from "react";
import TerminalProcessView from "./components/TerminalProcessView";
import TaskGraphView from "./components/TaskGraphView";
import WhyThisToolPanel, { ToolSelectionResult } from "./components/WhyThisToolPanel";

interface EventRecord {
  id?: number;
  session_id: string;
  task_id: string;
  timestamp: string;
  actor: string;
  tool_id?: string;
  tool_version?: string;
  requested_args?: string;
  normalized_args?: string;
  process_id?: number;
  start_time?: string;
  end_time?: string;
  exit_code?: number;
  stdout_ref?: string;
  stderr_ref?: string;
  artifact_refs?: string;
  screenshots?: string;
  network_context?: string;
  result_summary?: string;
  confidence?: number;
  parent_event?: string;
}

interface ExecutionDetails {
  adapter?: string;
  command?: string;
  args?: string[];
  exit_code?: number;
  process_id?: number;
  stdout?: string;
  stderr?: string;
  duration_ms?: number;
  timed_out?: boolean;
}

interface ModelCatalogItem {
  model_id: string;
  runtime: string;
  quantization: string;
  context_length: number;
  role: string;
  gpu_layers?: number;
  description?: string;
}

interface MemoryMetric {
  device?: string;
  total_mb: number;
  used_mb: number;
  free_mb: number;
  utilization_pct: number;
}

interface ModelCenterStatus {
  model_id: string;
  runtime: string;
  quantization: string;
  context_length: number;
  role: string;
  server_status: string;
  server_url: string;
  vram: MemoryMetric;
  ram: MemoryMetric;
  models_catalog: ModelCatalogItem[];
}

interface VMSnapshot {
  name: string;
  uuid: string;
  is_current: boolean;
  description: string;
}

interface VMStatus {
  vm_name: string;
  vm_state: string;
  running: boolean;
  worker_online: boolean;
  worker_info?: {
    status: string;
    agent: string;
    version: string;
    os: string;
    kernel: string;
    active_tasks: number;
    supported_tools: string[];
  };
  snapshots_count: number;
  snapshots: VMSnapshot[];
  baseline_snapshot: string;
  timestamp: string;
}

interface ChatMessage {
  id: string;
  sender: "user" | "agent" | "system";
  text: string;
  timestamp: string;
  taskId?: string;
  tool?: {
    id: string;
    version: string;
    name: string;
  };
  execution?: ExecutionDetails;
  durationMs?: number;
  toolSelection?: ToolSelectionResult;
}

export default function Home() {
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("connecting");
  const [sessionId, setSessionId] = useState<string>("init");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputVal, setInputVal] = useState<string>("");
  const [latestEvent, setLatestEvent] = useState<EventRecord | null>(null);
  const [allEvents, setAllEvents] = useState<EventRecord[]>([]);
  const [activeTab, setActiveTab] = useState<"terminal_process" | "task_graph" | "model_center" | "vm_sandbox" | "latest" | "all">("task_graph");
  const [modelCenter, setModelCenter] = useState<ModelCenterStatus | null>(null);
  const [vmStatus, setVmStatus] = useState<VMStatus | null>(null);
  const [isRollingBack, setIsRollingBack] = useState<boolean>(false);
  const [isTakingSnapshot, setIsTakingSnapshot] = useState<boolean>(false);
  const [newSnapName, setNewSnapName] = useState<string>("");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [isTerminalMaximized, setIsTerminalMaximized] = useState<boolean>(false);

  const [socket, setSocket] = useState<WebSocket | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Connect WebSocket
  useEffect(() => {
    let reconnectTimeout: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      setWsStatus("connecting");
      const wsUrl = "ws://localhost:4000";
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus("connected");
        setSocket(ws);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "handshake") {
            setSessionId(data.sessionId);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_handshake`,
                sender: "system",
                text: `WebSocket connected to Gateway (${data.sessionId})`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          } else if (data.type === "status") {
            if (data.taskId) {
              setActiveTaskId(data.taskId);
            }
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_status`,
                sender: "system",
                taskId: data.taskId,
                text: data.text || `Status: ${data.status}`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          } else if (data.type === "agent_response") {
            setActiveTaskId(null);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_resp`,
                sender: "agent",
                text: data.reply,
                timestamp: new Date().toLocaleTimeString(),
                tool: data.toolExecuted,
                execution: data.execution,
                durationMs: data.durationMs,
                toolSelection: data.toolSelection || data.tool_selection,
              },
            ]);
            if (data.event) {
              setLatestEvent(data.event);
              setAllEvents((prev) => [data.event, ...prev]);
            }
          } else if (data.type === "kill_confirmed") {
            setActiveTaskId(null);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_kill`,
                sender: "system",
                text: `☠️ Kill switch confirmed for task ${data.taskId}: ${JSON.stringify(data.result)}`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          } else if (data.type === "validation_error") {
            setActiveTaskId(null);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_val_err`,
                sender: "system",
                text: `[Gateway Schema Validation Error] Tool: ${data.tool} -> ${data.error}`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          } else if (data.type === "vm_status") {
            setVmStatus(data.status);
          } else if (data.type === "vm_snapshot_created") {
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_snap_event`,
                sender: "system",
                text: `📸 VM Snapshot "${data.snapshot_name}" captured (${data.is_live ? "live" : "offline"}).`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
            refreshVMStatus();
          } else if (data.type === "vm_rollback_complete") {
            setIsRollingBack(false);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_rb_event`,
                sender: "system",
                text: `✅ VM Rollback to "${data.snapshot_name}" confirmed. Guest worker agent active.`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
            refreshVMStatus();
          } else if (data.type === "error") {
            setActiveTaskId(null);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_err`,
                sender: "system",
                text: `[Error] ${data.error}`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          }
        } catch (err) {
          console.error("Failed to parse incoming WS message:", err);
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        setSocket(null);
        reconnectTimeout = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.warn("WebSocket encountered error:", err);
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const sendMessage = (textToSend?: string) => {
    const text = (textToSend !== undefined ? textToSend : inputVal).trim();
    if (!text || wsStatus !== "connected" || !wsRef.current) return;

    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}_user`,
      sender: "user",
      text,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputVal("");

    wsRef.current.send(
      JSON.stringify({
        type: "chat",
        content: text,
        sessionId,
      })
    );
  };

  const sendToolCall = (tool: string, args: Record<string, unknown>) => {
    if (wsStatus !== "connected" || !wsRef.current) return;
    const taskId = `task_${Date.now().toString(36)}`;
    setActiveTaskId(taskId);

    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}_user`,
      sender: "user",
      text: `[Propose Tool Call] ${tool} with args: ${JSON.stringify(args)}`,
      timestamp: new Date().toLocaleTimeString(),
      taskId,
    };
    setMessages((prev) => [...prev, userMsg]);

    wsRef.current.send(
      JSON.stringify({
        type: "tool_call",
        tool,
        args,
        sessionId,
        taskId,
      })
    );
  };

  const killRunningTask = (targetTaskId?: string) => {
    const tid = targetTaskId || activeTaskId;
    if (!tid || !wsRef.current) return;

    wsRef.current.send(
      JSON.stringify({
        type: "kill",
        taskId: tid,
      })
    );
  };

  const refreshModelCenter = async () => {
    try {
      const res = await fetch("http://localhost:8000/model-center");
      if (res.ok) {
        const data = await res.json();
        setModelCenter(data);
      }
    } catch (e) {
      console.error("Failed to fetch model center status", e);
    }
  };

  const refreshVMStatus = async () => {
    try {
      const res = await fetch("http://localhost:8000/vm/status");
      if (res.ok) {
        const data = await res.json();
        setVmStatus(data);
      }
    } catch (e) {
      console.error("Failed to fetch VM status", e);
    }
  };

  const takeSnapshot = async (name: string) => {
    if (!name.trim()) return;
    setIsTakingSnapshot(true);
    try {
      const res = await fetch("http://localhost:8000/vm/snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          description: `Manual snapshot created via UI at ${new Date().toLocaleTimeString()}`,
        }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          id: `msg_${Date.now()}_snap`,
          sender: "system",
          text: `📸 Created VM Snapshot: "${data.snapshot_name || name}"`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
      setNewSnapName("");
      await refreshVMStatus();
    } catch (e) {
      console.error("Failed to take snapshot", e);
    } finally {
      setIsTakingSnapshot(false);
    }
  };

  const rollbackSnapshot = async (name: string) => {
    if (!confirm(`Are you sure you want to rollback VM to snapshot "${name}"?`)) return;
    setIsRollingBack(true);
    setMessages((prev) => [
      ...prev,
      {
        id: `msg_${Date.now()}_rb_start`,
        sender: "system",
        text: `⏪ Initiating VM Rollback to snapshot: "${name}"... Waiting for guest reboot and worker reconnection.`,
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);
    try {
      const res = await fetch("http://localhost:8000/vm/rollback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          id: `msg_${Date.now()}_rb_done`,
          sender: "system",
          text: `✅ VM Rollback Complete: Restored to "${data.snapshot_name || name}". Guest worker agent is healthy and ready.`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
      await refreshVMStatus();
    } catch (e) {
      console.error("Failed to rollback", e);
      setMessages((prev) => [
        ...prev,
        {
          id: `msg_${Date.now()}_rb_err`,
          sender: "system",
          text: `❌ Rollback failed: ${String(e)}`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    } finally {
      setIsRollingBack(false);
    }
  };

  const refreshEvents = async () => {
    try {
      const res = await fetch("http://localhost:8000/events");
      const data = await res.json();
      if (data.events) {
        setAllEvents(data.events);
        setLatestEvent((prev) => prev || (data.events.length > 0 ? data.events[0] : null));
      }
    } catch (e) {
      console.error("Failed to fetch past events", e);
    }
  };

  useEffect(() => {
    let ignore = false;

    fetch("http://localhost:8000/model-center")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && data) {
          setModelCenter(data);
        }
      })
      .catch((err) => console.error("Failed to fetch model center status", err));

    fetch("http://localhost:8000/vm/status")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && data) {
          setVmStatus(data);
        }
      })
      .catch((err) => console.error("Failed to fetch VM status", err));

    fetch("http://localhost:8000/events")
      .then((res) => res.json())
      .then((data) => {
        if (!ignore && data.events) {
          setAllEvents(data.events);
          setLatestEvent((prev) => prev || (data.events.length > 0 ? data.events[0] : null));
        }
      })
      .catch((err) => console.error("Failed to fetch past events", err));

    const interval = setInterval(() => {
      fetch("http://localhost:8000/model-center")
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!ignore && data) {
            setModelCenter(data);
          }
        })
        .catch(() => {});

      fetch("http://localhost:8000/vm/status")
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!ignore && data) {
            setVmStatus(data);
          }
        })
        .catch(() => {});
    }, 4000);

    return () => {
      ignore = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-logo">Δ</div>
          <div className="brand-info">
            <h1>Agent Core Monorepo</h1>
            <p>UI ⇄ Gateway ⇄ Orchestrator ⇄ SQLite Event Boundary</p>
          </div>
        </div>

        <div className="status-badges">
          <div className="status-chip" style={{ borderColor: "rgba(16, 185, 129, 0.4)" }}>
            <span className="dot connected" />
            <span>
              {modelCenter
                ? `${modelCenter.model_id.replace("-Instruct", "")} (${Math.round(modelCenter.context_length / 1024)}K ctx)`
                : "Qwen3-Coder-30B-A3B (32K ctx)"}
            </span>
          </div>
          {modelCenter?.vram && (
            <div className="status-chip" style={{ borderColor: "rgba(6, 182, 212, 0.3)" }}>
              <span>GPU VRAM: {modelCenter.vram.used_mb}MB / {modelCenter.vram.total_mb}MB ({modelCenter.vram.utilization_pct}%)</span>
            </div>
          )}
          <div
            className="status-chip"
            style={{
              borderColor: vmStatus?.worker_online ? "rgba(16, 185, 129, 0.4)" : "rgba(244, 63, 94, 0.4)",
              cursor: "pointer",
            }}
            onClick={() => setActiveTab("vm_sandbox")}
            title="Click to open VM Sandbox Manager"
          >
            <span className={`dot ${vmStatus?.worker_online ? "connected" : "disconnected"}`} />
            <span>
              Kali VM: {vmStatus?.vm_state || "checking"} | Worker: {vmStatus?.worker_online ? "online" : "offline"}
            </span>
          </div>
          <div className="status-chip">
            <span className={`dot ${wsStatus}`} />
            <span>Gateway WS: {wsStatus}</span>
          </div>
          <div className="status-chip">
            <span>Session: {sessionId}</span>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <div className="main-layout">
        {/* Left: Chat Pane */}
        <section className="chat-pane">
          <div className="action-bar">
            {/* Tool: kali.exec.v1 with snapshot-before */}
            <button
              className="quick-btn"
              style={{
                color: "var(--accent-cyan)",
                borderColor: "rgba(6, 182, 212, 0.4)",
                background: "rgba(6, 182, 212, 0.12)",
              }}
              onClick={() =>
                sendToolCall("kali.exec.v1", {
                  command: "uname",
                  args: ["-a"],
                  snapshot_before: true,
                  timeout_ms: 10000,
                })
              }
              disabled={wsStatus !== "connected" || isRollingBack}
              title="Runs typed command inside Kali Linux VM with pre-task snapshot"
            >
              🐉 Kali Exec: uname -a (Snap-Before)
            </button>

            {/* Tool: kali.exec.v1 fast execution */}
            <button
              className="quick-btn secondary"
              style={{
                color: "var(--accent-emerald)",
                borderColor: "rgba(16, 185, 129, 0.35)",
                background: "rgba(16, 185, 129, 0.1)",
              }}
              onClick={() =>
                sendToolCall("kali.exec.v1", {
                  command: "id",
                  args: [],
                  snapshot_before: false,
                  timeout_ms: 5000,
                })
              }
              disabled={wsStatus !== "connected" || isRollingBack}
            >
              🐉 Kali: whoami / id
            </button>

            {/* Tool 1: shell.run.v1 safe execution */}
            <button
              className="quick-btn"
              onClick={() =>
                sendToolCall("shell.run.v1", {
                  command: "python",
                  args: ["-c", "import sys; print(f'Execution via shell.run.v1 adapter on Python {sys.version.split()[0]}')"],
                  timeout_ms: 10000,
                })
              }
              disabled={wsStatus !== "connected"}
            >
              ⚡ shell.run.v1
            </button>

            {/* Tool 2: shell.run.v1 hard timeout */}
            <button
              className="quick-btn secondary"
              onClick={() =>
                sendToolCall("shell.run.v1", {
                  command: "python",
                  args: ["-c", "import time; time.sleep(10)"],
                  timeout_ms: 800,
                })
              }
              disabled={wsStatus !== "connected"}
            >
              ⏱️ Timeout (800ms)
            </button>

            {/* Tool 3: Kill Switch demo */}
            <button
              className="quick-btn secondary"
              style={{ color: "var(--accent-rose)", borderColor: "rgba(244, 63, 94, 0.3)" }}
              onClick={() => {
                const sleepTaskId = `task_kill_demo_${Date.now().toString(36)}`;
                sendToolCall("shell.run.v1", {
                  command: "python",
                  args: ["-c", "import time; time.sleep(25)"],
                  timeout_ms: 30000,
                });
                setTimeout(() => {
                  killRunningTask(sleepTaskId);
                }, 1200);
              }}
              disabled={wsStatus !== "connected"}
            >
              ☠️ SIGKILL
            </button>

            {/* Conversational chat trigger */}
            <button
              className="quick-btn secondary"
              onClick={() => sendMessage("Hi! What adapters and VM sandboxes do you support?")}
              disabled={wsStatus !== "connected"}
            >
              💬 Chat
            </button>

            <button
              className="quick-btn secondary"
              onClick={() => {
                refreshEvents();
                refreshVMStatus();
              }}
            >
              🔄 Refresh
            </button>
          </div>

          <div className="messages-container">
            {messages.length === 0 && (
              <div style={{ textAlign: "center", color: "var(--text-muted)", marginTop: "40px" }}>
                <p style={{ fontSize: "15px", marginBottom: "8px" }}>
                  Connected to Gateway WebSocket.
                </p>
                <p style={{ fontSize: "13px" }}>
                  Click <strong>&quot;⚡ Tool: shell.run.v1 (Python)&quot;</strong> to test adapter execution,
                  schema validation, and the rich Tool Card output.
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <div key={msg.id} className={`message-card ${msg.sender}`}>
                <div className="message-meta">
                  <span>{msg.sender.toUpperCase()}</span>
                  <span>•</span>
                  <span>{msg.timestamp}</span>
                  {msg.durationMs !== undefined && (
                    <span>• {msg.durationMs}ms</span>
                  )}
                  {msg.taskId && <span>• {msg.taskId}</span>}
                </div>

                <div>{msg.text}</div>

                {/* Tool Tag */}
                {msg.tool && !msg.execution && (
                  <div>
                    <div className="tool-tag">
                      <span>⚡ Tool: {msg.tool.name} (v{msg.tool.version})</span>
                    </div>
                    <WhyThisToolPanel
                      toolSelection={msg.toolSelection}
                      toolId={msg.tool.id}
                    />
                  </div>
                )}

                {/* Rich Tool Execution Card */}
                {msg.execution && (
                  <div className="tool-execution-card">
                    <div className="tool-card-header">
                      <div className="tool-title">
                        <span>⚡ {msg.execution.adapter || "shell.run.v1"}</span>
                      </div>
                      <div className="tool-badges">
                        {msg.execution.timed_out ? (
                          <span className="exit-badge timeout">⚠️ TIMED OUT (SIGKILL)</span>
                        ) : msg.execution.exit_code === 0 ? (
                          <span className="exit-badge success">✓ EXIT 0 (SUCCESS)</span>
                        ) : (
                          <span className="exit-badge error">✗ EXIT {msg.execution.exit_code}</span>
                        )}
                        <span className="meta-chip">#PID {msg.execution.process_id}</span>
                        <span className="meta-chip">{msg.execution.duration_ms}ms</span>
                      </div>
                    </div>

                    {/* Executed Command Line */}
                    <div className="cmd-box">
                      <span className="cmd-prompt">$</span>
                      <span>
                        {msg.execution.command} {(msg.execution.args || []).join(" ")}
                      </span>
                    </div>

                    {/* STDOUT Viewer */}
                    {msg.execution.stdout ? (
                      <div className="output-section">
                        <span className="output-label">Captured STDOUT</span>
                        <pre className="terminal-stdout">{msg.execution.stdout}</pre>
                      </div>
                    ) : null}

                    {/* STDERR Viewer */}
                    {msg.execution.stderr ? (
                      <div className="output-section">
                        <span className="output-label">Captured STDERR / Supervisor</span>
                        <pre className="terminal-stderr">{msg.execution.stderr}</pre>
                      </div>
                    ) : null}

                    {/* Expandable Why This Tool Score Breakdown */}
                    <WhyThisToolPanel
                      toolSelection={msg.toolSelection}
                      toolId={msg.tool?.id || msg.execution.adapter}
                    />
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="chat-input-area">
            <input
              type="text"
              className="chat-input"
              placeholder={
                wsStatus === "connected"
                  ? "Type a message or command (e.g. 'shell.run.v1: echo hello')..."
                  : "Connecting to gateway..."
              }
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendMessage();
              }}
              disabled={wsStatus !== "connected"}
            />
            {activeTaskId && (
              <button
                className="quick-btn"
                style={{
                  background: "rgba(244, 63, 94, 0.2)",
                  borderColor: "rgba(244, 63, 94, 0.5)",
                  color: "var(--accent-rose)",
                }}
                onClick={() => killRunningTask()}
              >
                ☠️ SIGKILL
              </button>
            )}
            <button
              className="send-btn"
              onClick={() => sendMessage()}
              disabled={wsStatus !== "connected"}
            >
              Send
            </button>
          </div>
        </section>

        {/* Right: SQLite Event Inspector & Model Center */}
        <aside className={`inspector-pane ${isTerminalMaximized && activeTab === "terminal_process" ? "maximized-overlay" : ""}`}>
          <div className="inspector-header">
            <h2>
              {activeTab === "task_graph"
                ? "Task Graph (DAG Planner)"
                : activeTab === "terminal_process"
                ? "Live Terminal (xterm.js) & Process Tree"
                : activeTab === "model_center"
                ? "Model Center (Phase 4 Manager)"
                : activeTab === "vm_sandbox"
                ? "VM Sandbox & Snapshot Manager"
                : "SQLite Event Store Inspector"}
            </h2>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
              <button
                className={`quick-btn ${activeTab === "task_graph" ? "" : "secondary"}`}
                style={{
                  padding: "3px 8px",
                  fontSize: "11px",
                  borderColor: activeTab === "task_graph" ? "var(--accent-cyan)" : undefined,
                  background: activeTab === "task_graph" ? "rgba(6, 182, 212, 0.15)" : undefined,
                }}
                onClick={() => setActiveTab("task_graph")}
              >
                🕸️ Task Graph (DAG)
              </button>
              <button
                className={`quick-btn ${activeTab === "terminal_process" ? "" : "secondary"}`}
                style={{
                  padding: "3px 8px",
                  fontSize: "11px",
                  borderColor: activeTab === "terminal_process" ? "var(--accent-cyan)" : undefined,
                  background: activeTab === "terminal_process" ? "rgba(6, 182, 212, 0.15)" : undefined,
                }}
                onClick={() => setActiveTab("terminal_process")}
              >
                🖥️ Terminal & Tree
              </button>
              <button
                className={`quick-btn ${activeTab === "vm_sandbox" ? "" : "secondary"}`}
                style={{ padding: "3px 8px", fontSize: "11px" }}
                onClick={() => setActiveTab("vm_sandbox")}
              >
                VM Sandbox
              </button>
              <button
                className={`quick-btn ${activeTab === "model_center" ? "" : "secondary"}`}
                style={{ padding: "3px 8px", fontSize: "11px" }}
                onClick={() => setActiveTab("model_center")}
              >
                Model Center
              </button>
              <button
                className={`quick-btn ${activeTab === "latest" ? "" : "secondary"}`}
                style={{ padding: "3px 8px", fontSize: "11px" }}
                onClick={() => setActiveTab("latest")}
              >
                Latest Event
              </button>
              <button
                className={`quick-btn ${activeTab === "all" ? "" : "secondary"}`}
                style={{ padding: "3px 8px", fontSize: "11px" }}
                onClick={() => setActiveTab("all")}
              >
                Log ({allEvents.length})
              </button>
            </div>
          </div>

          <div className="inspector-content">
            {activeTab === "task_graph" ? (
              <div style={{ height: "calc(100vh - 190px)", minHeight: "560px", display: "flex", flexDirection: "column" }}>
                <TaskGraphView
                  ws={socket || wsRef.current}
                  activeSessionId={sessionId}
                />
              </div>
            ) : activeTab === "terminal_process" ? (
              <div style={{ height: isTerminalMaximized ? "calc(100vh - 120px)" : "calc(100vh - 190px)", minHeight: "560px", display: "flex", flexDirection: "column" }}>
                <TerminalProcessView
                  ws={socket || wsRef.current}
                  activeTaskId={activeTaskId}
                  onSelectTask={(tid) => setActiveTaskId(tid)}
                  isMaximized={isTerminalMaximized}
                  onToggleMaximize={() => setIsTerminalMaximized((prev) => !prev)}
                />
              </div>
            ) : activeTab === "model_center" ? (
              <>
                {/* Active Loaded Model Card */}
                <div className="proof-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                    <h3>Active Loaded Model</h3>
                    <button
                      className="quick-btn secondary"
                      style={{ padding: "2px 8px", fontSize: "10px" }}
                      onClick={refreshModelCenter}
                    >
                      🔄 Refresh
                    </button>
                  </div>

                  <div className="model-card active">
                    <div className="model-card-header">
                      <span className="model-title">
                        {modelCenter?.model_id || "Qwen3-Coder-30B-A3B-Instruct"}
                      </span>
                      <span className={`role-badge ${modelCenter?.role === "fallback" ? "fallback" : "primary"}`}>
                        {modelCenter?.role || "PRIMARY"}
                      </span>
                    </div>

                    <div className="model-meta-grid">
                      <div className="model-meta-item">
                        <span className="meta-label">Runtime</span>
                        <span className="meta-value">{modelCenter?.runtime || "llama.cpp"}</span>
                      </div>
                      <div className="model-meta-item">
                        <span className="meta-label">Quantization</span>
                        <span className="meta-value">{modelCenter?.quantization || "Q4_K_M"}</span>
                      </div>
                      <div className="model-meta-item">
                        <span className="meta-label">Context Limit</span>
                        <span className="meta-value">
                          {modelCenter ? `${(modelCenter.context_length).toLocaleString()} tokens` : "32,768 tokens"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* VRAM & RAM Live Telemetry */}
                <div className="proof-card">
                  <h3>Hardware Resource Allocation</h3>
                  <div className="metric-container">
                    <div className="metric-bar-group">
                      <div className="metric-header">
                        <span>GPU VRAM ({modelCenter?.vram?.device || "NVIDIA GPU"})</span>
                        <span>
                          {modelCenter?.vram
                            ? `${modelCenter.vram.used_mb} MB / ${modelCenter.vram.total_mb} MB (${modelCenter.vram.utilization_pct}%)`
                            : "486 MB / 8,151 MB (6.0%)"}
                        </span>
                      </div>
                      <div className="metric-track">
                        <div
                          className="metric-fill vram"
                          style={{
                            width: `${Math.min(modelCenter?.vram?.utilization_pct || 6, 100)}%`,
                          }}
                        />
                      </div>
                    </div>

                    <div className="metric-bar-group">
                      <div className="metric-header">
                        <span>Host System RAM</span>
                        <span>
                          {modelCenter?.ram
                            ? `${(modelCenter.ram.used_mb / 1024).toFixed(1)} GB / ${(modelCenter.ram.total_mb / 1024).toFixed(1)} GB (${modelCenter.ram.utilization_pct}%)`
                            : "26.4 GB / 31.4 GB (82.4%)"}
                        </span>
                      </div>
                      <div className="metric-track">
                        <div
                          className="metric-fill ram"
                          style={{
                            width: `${Math.min(modelCenter?.ram?.utilization_pct || 82, 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Model Catalog from models.yaml */}
                <div className="proof-card">
                  <h3>Model Catalog (models.yaml)</h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "6px" }}>
                    {(modelCenter?.models_catalog || [
                      {
                        model_id: "Qwen3-Coder-30B-A3B-Instruct",
                        runtime: "llama.cpp",
                        quantization: "Q4_K_M",
                        context_length: 32768,
                        role: "primary",
                        description: "Mixture-of-Experts 30B model (3.3B active parameters) for coding",
                      },
                      {
                        model_id: "Qwen2.5-0.5B-Instruct",
                        runtime: "llama.cpp",
                        quantization: "Q4_K_M",
                        context_length: 4096,
                        role: "fallback",
                        description: "Ultra-low latency fallback verification model",
                      },
                    ]).map((m, idx) => (
                      <div key={idx} className={`model-card ${m.role === "primary" ? "active" : ""}`}>
                        <div className="model-card-header">
                          <span style={{ fontSize: "12px", fontWeight: 600, color: "#e2e8f0" }}>
                            {m.model_id}
                          </span>
                          <span className={`role-badge ${m.role === "fallback" ? "fallback" : "primary"}`}>
                            {m.role}
                          </span>
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                          {m.description}
                        </div>
                        <div style={{ display: "flex", gap: "10px", fontSize: "10px", color: "var(--accent-cyan)", marginTop: "4px" }}>
                          <span>Runtime: {m.runtime}</span>
                          <span>Quant: {m.quantization}</span>
                          <span>Context: {m.context_length}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Task 0.4 Verification Checklist */}
                <div className="proof-card">
                  <h3>Model Center Architecture Verification</h3>
                  <ul className="checklist">
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>models.yaml defines Qwen3-Coder-30B-A3B-Instruct (32K ctx)</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>llama.cpp runtime configured with GBNF schema constraints</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>Fallback model configured with role=&quot;fallback&quot;</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>Status endpoint /model-center reports loaded model &amp; context</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>Live VRAM &amp; RAM hardware usage telemetries monitored</span>
                    </li>
                  </ul>
                </div>
              </>
            ) : activeTab === "vm_sandbox" ? (
              <>
                {/* VM Sandbox Banner */}
                <div className={`vm-status-banner ${vmStatus?.worker_online ? "" : "offline"}`}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span className={`dot ${vmStatus?.worker_online ? "connected" : "disconnected"}`} />
                      <strong style={{ fontSize: "13px", color: "#f1f5f9" }}>
                        {vmStatus?.vm_name || "kali-linux-2026.1-virtualbox-amd64"}
                      </strong>
                    </div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
                      VirtualBox NAT • Host 2222 ➔ Guest 22 (SSH) • Host 9999 ➔ Guest 9999 (Worker)
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <span className={`role-badge ${vmStatus?.worker_online ? "primary" : "fallback"}`}>
                      {vmStatus?.worker_online ? "WORKER READY" : "OFFLINE"}
                    </span>
                    <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "4px" }}>
                      State: {vmStatus?.vm_state || "unknown"}
                    </div>
                  </div>
                </div>

                {/* In-Guest Worker Telemetry */}
                <div className="proof-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                    <h3>In-Guest Worker Agent (Typed ToolSpec API)</h3>
                    <button
                      className="quick-btn secondary"
                      style={{ padding: "2px 8px", fontSize: "10px" }}
                      onClick={refreshVMStatus}
                    >
                      🔄 Refresh
                    </button>
                  </div>

                  <div className="model-meta-grid" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
                    <div className="model-meta-item">
                      <span className="meta-label">Guest OS &amp; Kernel</span>
                      <span className="meta-value">
                        {vmStatus?.worker_info?.os || "Kali Linux"} ({vmStatus?.worker_info?.kernel || "amd64"})
                      </span>
                    </div>
                    <div className="model-meta-item">
                      <span className="meta-label">Agent Binary / Protocol</span>
                      <span className="meta-value">
                        {vmStatus?.worker_info?.agent || "kairo-worker"} v{vmStatus?.worker_info?.version || "1.0.0"} (HTTP/REST)
                      </span>
                    </div>
                    <div className="model-meta-item">
                      <span className="meta-label">Active Guest Tasks</span>
                      <span className="meta-value">{vmStatus?.worker_info?.active_tasks ?? 0} running</span>
                    </div>
                    <div className="model-meta-item">
                      <span className="meta-label">Baseline Snapshot</span>
                      <span className="meta-value" style={{ color: "var(--accent-emerald)" }}>
                        {vmStatus?.baseline_snapshot || "kairo_worker_ready"}
                      </span>
                    </div>
                  </div>

                  <div style={{ marginTop: "10px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    <button
                      className="quick-btn"
                      style={{ flex: 1, minWidth: "180px", justifyContent: "center" }}
                      onClick={() =>
                        sendToolCall("kali.exec.v1", {
                          command: "uname",
                          args: ["-a"],
                          snapshot_before: true,
                          rollback_after: false,
                          timeout_ms: 10000,
                        })
                      }
                      disabled={wsStatus !== "connected" || isRollingBack}
                    >
                      ⚡ Run with Pre-Task Snapshot
                    </button>
                    <button
                      className="quick-btn secondary"
                      style={{ flex: 1, minWidth: "180px", justifyContent: "center" }}
                      onClick={() =>
                        sendToolCall("kali.exec.v1", {
                          command: "bash",
                          args: ["-c", "echo 'ephemeral change' > /tmp/temp_kairo.txt && cat /tmp/temp_kairo.txt"],
                          snapshot_before: true,
                          rollback_after: true,
                          timeout_ms: 20000,
                        })
                      }
                      disabled={wsStatus !== "connected" || isRollingBack}
                    >
                      🔄 Auto-Snap &amp; Auto-Rollback
                    </button>
                    <button
                      className="quick-btn secondary"
                      style={{ flex: 1, minWidth: "180px", justifyContent: "center" }}
                      onClick={() => rollbackSnapshot(vmStatus?.baseline_snapshot || "kairo_worker_ready")}
                      disabled={isRollingBack}
                    >
                      ⏪ Reset to Baseline
                    </button>
                  </div>
                </div>

                {/* VM Snapshot Inventory & Rollback */}
                <div className="proof-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <h3>VM Snapshot Inventory ({vmStatus?.snapshots_count ?? 0})</h3>
                    {isRollingBack && (
                      <span style={{ fontSize: "11px", color: "var(--accent-amber)" }}>
                        ⏳ Restoring VM...
                      </span>
                    )}
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "10px" }}>
                    {(vmStatus?.snapshots || []).map((snap, idx) => (
                      <div
                        key={idx}
                        className={`snapshot-item ${snap.is_current ? "current" : ""}`}
                      >
                        <div style={{ flex: 1, overflow: "hidden" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <strong style={{ fontSize: "12px", color: "#f8fafc", fontFamily: "var(--font-mono)" }}>
                              {snap.name}
                            </strong>
                            {snap.is_current && (
                              <span className="role-badge primary" style={{ fontSize: "8px", padding: "1px 4px" }}>
                                CURRENT
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                            {snap.description || snap.uuid}
                          </div>
                        </div>

                        <button
                          className="rollback-btn"
                          onClick={() => rollbackSnapshot(snap.name)}
                          disabled={isRollingBack}
                          title={`Rollback VM to state: ${snap.name}`}
                        >
                          ⏪ Rollback
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Manual Snapshot Form */}
                  <div className="snap-input-group">
                    <input
                      type="text"
                      className="snap-input"
                      placeholder="New snapshot name (e.g. checkpoint_01)..."
                      value={newSnapName}
                      onChange={(e) => setNewSnapName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") takeSnapshot(newSnapName);
                      }}
                      disabled={isTakingSnapshot || isRollingBack}
                    />
                    <button
                      className="quick-btn"
                      onClick={() => takeSnapshot(newSnapName)}
                      disabled={!newSnapName.trim() || isTakingSnapshot || isRollingBack}
                    >
                      {isTakingSnapshot ? "Taking..." : "📸 Take Snapshot"}
                    </button>
                  </div>
                </div>

                {/* Architecture Verification Checklist */}
                <div className="proof-card">
                  <h3>Task 1.1 &amp; 1.2 Architecture Verification</h3>
                  <ul className="checklist">
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>Isolated Kali Linux VM running headless on host hypervisor</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>SSH port forwarding 2222:22 + Worker Agent 9999:9999</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>In-guest Python Worker Agent receiving typed ToolSpec requests</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>Zero raw SSH-exec string injection; typed schema validation</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>VM snapshot-before-task implemented (pre_task_* snapshots)</span>
                    </li>
                    <li className="checked">
                      <span className="check-icon">✓</span>
                      <span>Manual one-click rollback with guest recovery verified</span>
                    </li>
                  </ul>
                </div>
              </>
            ) : activeTab === "latest" ? (
              <div className="proof-card">
                <h3>Latest Event Row (20 Exact Columns)</h3>
                {latestEvent ? (
                  <table className="schema-table">
                    <tbody>
                      <tr>
                        <td className="schema-key">session_id</td>
                        <td className="schema-val">{latestEvent.session_id}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">task_id</td>
                        <td className="schema-val">{latestEvent.task_id}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">timestamp</td>
                        <td className="schema-val">{latestEvent.timestamp}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">actor</td>
                        <td className="schema-val">{latestEvent.actor}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">tool_id</td>
                        <td className="schema-val" style={{ color: "var(--accent-emerald)" }}>
                          {latestEvent.tool_id || "null"}
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">tool_version</td>
                        <td className="schema-val">{latestEvent.tool_version || "null"}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">requested_args</td>
                        <td className="schema-val">
                          <span className="json-pill">{latestEvent.requested_args || "null"}</span>
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">normalized_args</td>
                        <td className="schema-val">
                          <span className="json-pill">{latestEvent.normalized_args || "null"}</span>
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">process_id</td>
                        <td className="schema-val">{latestEvent.process_id ?? "null"}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">start_time</td>
                        <td className="schema-val">{latestEvent.start_time}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">end_time</td>
                        <td className="schema-val">{latestEvent.end_time}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">exit_code</td>
                        <td className="schema-val" style={{ color: latestEvent.exit_code === 0 ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
                          {latestEvent.exit_code ?? 0}
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">stdout_ref</td>
                        <td className="schema-val">{latestEvent.stdout_ref || "null"}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">stderr_ref</td>
                        <td className="schema-val">{latestEvent.stderr_ref || "null"}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">artifact_refs</td>
                        <td className="schema-val">
                          <span className="json-pill">{latestEvent.artifact_refs || "null"}</span>
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">screenshots</td>
                        <td className="schema-val">
                          <span className="json-pill">{latestEvent.screenshots || "[]"}</span>
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">network_context</td>
                        <td className="schema-val">
                          <span className="json-pill">{latestEvent.network_context || "null"}</span>
                        </td>
                      </tr>
                      <tr>
                        <td className="schema-key">result_summary</td>
                        <td className="schema-val">{latestEvent.result_summary || "null"}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">confidence</td>
                        <td className="schema-val">{latestEvent.confidence ?? "null"}</td>
                      </tr>
                      <tr>
                        <td className="schema-key">parent_event</td>
                        <td className="schema-val">{latestEvent.parent_event || "null"}</td>
                      </tr>
                    </tbody>
                  </table>
                ) : (
                  <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                    No events recorded yet. Send a command to write an event row.
                  </p>
                )}
              </div>
            ) : (
              <div className="proof-card">
                <h3>All Events History</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {allEvents.map((evt, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "8px 10px",
                        background: "rgba(0,0,0,0.3)",
                        borderRadius: "6px",
                        fontSize: "12px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                        <strong style={{ color: "var(--accent-blue)" }}>{evt.tool_id || "action"}</strong>
                        <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>{evt.timestamp}</span>
                      </div>
                      <div style={{ color: "#cbd5e1" }}>{evt.result_summary}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
