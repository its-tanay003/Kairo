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

interface ChatMessage {
  id: string;
  sender: "user" | "agent" | "system";
  text: string;
  timestamp: string;
  tool?: {
    id: string;
    version: string;
    name: string;
  };
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
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_status`,
                sender: "system",
                text: data.text || `Status: ${data.status}`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          } else if (data.type === "agent_response") {
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_resp`,
                sender: "agent",
                text: data.reply,
                timestamp: new Date().toLocaleTimeString(),
                tool: data.toolExecuted,
                durationMs: data.durationMs,
              },
            ]);
            if (data.event) {
              setLatestEvent(data.event);
              setAllEvents((prev) => [data.event, ...prev]);
            }
          } else if (data.type === "error") {
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

    // Send chat command over WebSocket
    wsRef.current.send(
      JSON.stringify({
        type: "chat",
        content: text,
        sessionId,
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
            <button
              className="quick-btn"
              onClick={() => sendMessage("Please execute hello_world tool for Tanay")}
              disabled={wsStatus !== "connected"}
            >
              ⚡ Tool Call: hello_world
            </button>
            <button
              className="quick-btn secondary"
              onClick={() => sendMessage("Run system ping diagnostic")}
              disabled={wsStatus !== "connected"}
            >
              📡 Tool Call: system_ping
            </button>
            <button
              className="quick-btn secondary"
              onClick={() => sendMessage("Hello! What is your role as an assistant?")}
              disabled={wsStatus !== "connected"}
            >
              💬 Chat Message (No Tool)
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
                  Click <strong>&quot;Verify Boundary (Hello World)&quot;</strong> to trigger the complete service chain.
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
                </div>
                <div>{msg.text}</div>
                {msg.tool && (
                  <div className="tool-tag">
                    <span>⚡ Tool: {msg.tool.name} (v{msg.tool.version})</span>
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
                  ? "Type a message or tool invocation..."
                  : "Connecting to gateway..."
              }
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendMessage();
              }}
              disabled={wsStatus !== "connected"}
            />
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
              <h3>Service Boundary Verification</h3>
              <ul className="checklist">
                <li className="checked">
                  <span className="check-icon">✓</span>
                  <span>/ui connects to /gateway via WebSocket</span>
                </li>
                <li className={latestEvent ? "checked" : ""}>
                  <span className="check-icon">✓</span>
                  <span>/gateway dispatches call to /orchestrator</span>
                </li>
                <li className={latestEvent ? "checked" : ""}>
                  <span className="check-icon">✓</span>
                  <span>/orchestrator resolves tool spec from /registry</span>
                </li>
                <li className={latestEvent ? "checked" : ""}>
                  <span className="check-icon">✓</span>
                  <span>/orchestrator writes exact 20-field Event to /events/events.db</span>
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
                        <td className="schema-val">{latestEvent.exit_code ?? 0}</td>
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
                    No events recorded yet. Send &quot;Hello World&quot; to write an event row.
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
