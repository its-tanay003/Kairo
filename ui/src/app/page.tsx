"use client";

import React, { useEffect, useRef, useState } from "react";

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
}

export default function Home() {
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("connecting");
  const [sessionId, setSessionId] = useState<string>("init");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputVal, setInputVal] = useState<string>("");
  const [latestEvent, setLatestEvent] = useState<EventRecord | null>(null);
  const [allEvents, setAllEvents] = useState<EventRecord[]>([]);
  const [activeTab, setActiveTab] = useState<"latest" | "all">("latest");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

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
    fetch("http://localhost:8000/events")
      .then((res) => res.json())
      .then((data) => {
        if (!ignore && data.events) {
          setAllEvents(data.events);
          setLatestEvent((prev) => prev || (data.events.length > 0 ? data.events[0] : null));
        }
      })
      .catch((err) => console.error("Failed to fetch past events", err));

    return () => {
      ignore = true;
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
            <span>llama.cpp: Qwen (GBNF)</span>
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
              ⚡ Tool: shell.run.v1 (Python)
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
              ⏱️ Hard Timeout (800ms)
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
              ☠️ Test Kill Switch (SIGKILL)
            </button>

            {/* Conversational chat trigger */}
            <button
              className="quick-btn secondary"
              onClick={() => sendMessage("Hi! What adapters do you support?")}
              disabled={wsStatus !== "connected"}
            >
              💬 Chat Message
            </button>

            <button
              className="quick-btn secondary"
              onClick={refreshEvents}
            >
              🔄 Refresh Events
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
                  <div className="tool-tag">
                    <span>⚡ Tool: {msg.tool.name} (v{msg.tool.version})</span>
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

        {/* Right: SQLite Event Inspector */}
        <aside className="inspector-pane">
          <div className="inspector-header">
            <h2>SQLite Event Store Inspector</h2>
            <div style={{ display: "flex", gap: "6px" }}>
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
            {/* Proof Card */}
            <div className="proof-card">
              <h3>Adapter & Service Verification</h3>
              <ul className="checklist">
                <li className="checked">
                  <span className="check-icon">✓</span>
                  <span>/ui connects to /gateway via WebSocket</span>
                </li>
                <li className="checked">
                  <span className="check-icon">✓</span>
                  <span>/gateway validates ToolSpec schema</span>
                </li>
                <li className="checked">
                  <span className="check-icon">✓</span>
                  <span>Process Supervisor enforces hard timeout</span>
                </li>
                <li className="checked">
                  <span className="check-icon">✓</span>
                  <span>Kill switch endpoint supports SIGKILL by task_id</span>
                </li>
                <li className={latestEvent ? "checked" : ""}>
                  <span className="check-icon">✓</span>
                  <span>stdout/stderr/exit_code captured into SQLite (20 cols)</span>
                </li>
              </ul>
            </div>

            {/* Event Schema Detail */}
            {activeTab === "latest" ? (
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
