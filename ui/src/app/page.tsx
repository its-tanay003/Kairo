"use client";

import React, { useEffect, useRef, useState, useMemo } from "react";
import TerminalProcessView from "./components/TerminalProcessView";
import TaskGraphView from "./components/TaskGraphView";
import ScreenPanel from "./components/ScreenPanel";
import AuditExplorer from "./components/AuditExplorer";
import DatasetCurationPanel from "./components/DatasetCurationPanel";
import BenchmarkLeaderboard from "./components/BenchmarkLeaderboard";

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

export interface RecoveryHistoryStep {
  attempt?: number;
  tool?: string;
  args?: Record<string, unknown> | string[];
  status?: string;
  exit_code?: number;
  failure_reason?: string;
  duration_s?: number;
  duration_ms?: number;
  action_taken?: string;
  event_id?: string;
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
  recovery_narrative?: string;
  recovery_path?: RecoveryHistoryStep[];
  attempts?: number;
  event_id?: string;
  parent_event?: string;
}

interface DimensionScore {
  name: string;
  weight: number;
  weight_pct: number;
  score: number;
  score_pct: number;
  weighted_score: number;
  raw_signal: string;
}

interface ToolSelectionCandidate {
  tool_id: string;
  tool_name: string;
  version: string;
  category: string;
  rank: number;
  total_score: number;
  score_pct: number;
  summary_rationale: string;
  dimension_scores: DimensionScore[];
}

interface ToolSelectionResult {
  selected_tool: ToolSelectionCandidate;
  candidates: ToolSelectionCandidate[];
  selection_reason: string;
  evaluated_count: number;
  task_goal: string;
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
  recovery_narrative?: string;
  recovery_path?: RecoveryHistoryStep[];
}

interface ModelCenterStatus {
  model_id: string;
  runtime: string;
  quantization: string;
  context_length: number;
  role: string;
  server_status: string;
  server_url: string;
  vram?: {
    total_mb: number;
    used_mb: number;
    free_mb: number;
    utilization_pct: number;
  };
  ram?: {
    total_mb: number;
    used_mb: number;
    free_mb: number;
    utilization_pct: number;
  };
}

interface VMStatus {
  name: string;
  running: boolean;
  vm_state: string;
  worker_online: boolean;
  snapshots_count?: number;
  snapshots?: Array<{ name: string; timestamp?: string }>;
}

export default function Home() {
  // Connection and Session State
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("connecting");
  const [sessionId, setSessionId] = useState<string>("sess_main_01");
  const [sessions, setSessions] = useState<Array<{ id: string; title: string; time: string }>>([
    { id: "sess_main_01", title: "Autonomous Security Audit", time: "Just now" },
  ]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [runningToolName, setRunningToolName] = useState<string | null>(null);

  // Messages and Input
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputVal, setInputVal] = useState<string>("");

  // Drawer and Dialogs State
  const [isAdvancedOpen, setIsAdvancedOpen] = useState<boolean>(false);
  const [advancedTab, setAdvancedTab] = useState<
    "system" | "events" | "terminal" | "screen" | "graph" | "benchmarks" | "audit" | "devtools"
  >("system");
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [showStatusTooltip, setShowStatusTooltip] = useState<boolean>(false);
  const [showScopePopover, setShowScopePopover] = useState<boolean>(false);

  // System & Telemetry Data
  const [modelCenter, setModelCenter] = useState<ModelCenterStatus | null>(null);
  const [vmStatus, setVmStatus] = useState<VMStatus | null>(null);
  const [allEvents, setAllEvents] = useState<EventRecord[]>([]);
  const [expandedCards, setExpandedCards] = useState<Record<string, boolean>>({});

  // Active Scope Contract info
  const [scopeInfo] = useState<{
    target: string;
    cidrAllowed: string[];
    cidrExcluded: string[];
    maxTier: string;
    status: string;
  }>({
    target: "192.168.1.0/24",
    cidrAllowed: ["192.168.1.0/24", "10.0.0.0/8"],
    cidrExcluded: ["192.168.1.1", "10.0.0.1"],
    maxTier: "Tier 2 (Active CLI)",
    status: "Active",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const [wsInstance, setWsInstance] = useState<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Auto-scroll chat on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize composer textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [inputVal]);

  // Fetch initial telemetry
  const fetchTelemetry = () => {
    fetch("http://localhost:8000/model-center")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setModelCenter(data))
      .catch(() => {});

    fetch("http://localhost:8000/vm/status")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setVmStatus(data))
      .catch(() => {});

    fetch("http://localhost:8000/events")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data?.events && setAllEvents(data.events))
      .catch(() => {});
  };

  useEffect(() => {
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 6000);
    return () => clearInterval(interval);
  }, []);

  // WebSocket lifecycle
  useEffect(() => {
    let reconnectTimeout: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      setWsStatus("connecting");
      const wsUrl = `ws://localhost:4000/?sessionId=${sessionId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus("connected");
        setWsInstance(ws);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "handshake") {
            if (data.sessionId) setSessionId(data.sessionId);
          } else if (data.type === "status") {
            if (data.taskId) {
              setActiveTaskId(data.taskId);
              setRunningToolName(data.tool || "task");
            }
          } else if (data.type === "agent_response") {
            setActiveTaskId(null);
            setRunningToolName(null);
            const msgId = `msg_${Date.now()}_resp`;
            setMessages((prev) => [
              ...prev,
              {
                id: msgId,
                sender: "agent",
                text: data.reply || "",
                timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                tool: data.toolExecuted,
                execution: data.execution,
                durationMs: data.durationMs,
                toolSelection: data.toolSelection,
                recovery_narrative: data.execution?.recovery_narrative,
                recovery_path: data.execution?.recovery_path,
              },
            ]);

            // If execution failed, auto-expand tool card
            if (data.execution && data.execution.exit_code !== 0) {
              setExpandedCards((prev) => ({ ...prev, [msgId]: true }));
            }

            if (data.event) {
              setAllEvents((prev) => [data.event, ...prev]);
            }
          } else if (data.type === "scope_violation") {
            setActiveTaskId(null);
            setRunningToolName(null);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_scope_err`,
                sender: "agent",
                text: `Scope Violation Blocked: Tool "${data.tool || "tool"}" targeting ${data.target || "host"} is outside the authorized CIDR scope contract. ${data.reason || ""}`,
                timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
              },
            ]);
          } else if (data.type === "error") {
            setActiveTaskId(null);
            setRunningToolName(null);
            setMessages((prev) => [
              ...prev,
              {
                id: `msg_${Date.now()}_err`,
                sender: "system",
                text: `Error: ${data.error}`,
                timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
              },
            ]);
          }
        } catch (err) {
          console.error("WS Parse error:", err);
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        setWsInstance(null);
        reconnectTimeout = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout);
      setWsInstance(null);
      wsRef.current?.close();
    };
  }, [sessionId]);

  // Send human operator chat message
  const handleSend = () => {
    const text = inputVal.trim();
    if (!text || wsStatus !== "connected" || !wsRef.current) return;

    const taskId = `task_${Date.now().toString(36)}`;
    setActiveTaskId(taskId);
    setRunningToolName(null);

    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}_user`,
      sender: "user",
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      taskId,
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputVal("");

    // Update active session preview
    setSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, title: text.slice(0, 32) } : s))
    );

    wsRef.current.send(
      JSON.stringify({
        type: "chat",
        content: text,
        sessionId,
        taskId,
      })
    );
  };

  // Keyboard shortcut (Enter to send, Shift+Enter for newline)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Start a new session
  const handleNewSession = () => {
    const newId = `sess_${Date.now().toString(36)}`;
    setSessionId(newId);
    setMessages([]);
    setActiveTaskId(null);
    setSessions((prev) => [
      { id: newId, title: "New Security Session", time: "Just now" },
      ...prev,
    ]);
    setIsMobileSidebarOpen(false);
  };

  // Toggle tool card details
  const toggleCard = (msgId: string) => {
    setExpandedCards((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  // Dev tools helper actions
  const triggerDevAction = (type: string, payload: Record<string, unknown>) => {
    if (!wsRef.current || wsStatus !== "connected") return;
    const taskId = `task_dev_${Date.now().toString(36)}`;
    setActiveTaskId(taskId);
    wsRef.current.send(
      JSON.stringify({
        type,
        ...payload,
        sessionId,
        taskId,
      })
    );
  };

  // Compute status pill state
  const statusInfo = useMemo(() => {
    if (wsStatus === "connecting") {
      return { dotClass: "warning", text: "Connecting…" };
    }
    if (wsStatus === "disconnected") {
      return { dotClass: "error", text: "Disconnected" };
    }
    if (activeTaskId) {
      return { dotClass: "running", text: `Running ${runningToolName || "scan"}…` };
    }
    if (modelCenter && modelCenter.server_status !== "running") {
      return { dotClass: "error", text: "No model loaded" };
    }
    return { dotClass: "success", text: "Ready" };
  }, [wsStatus, activeTaskId, runningToolName, modelCenter]);

  return (
    <div className="app-shell">
      {/* 1. TOP BAR (56px) */}
      <header className="top-bar">
        <div className="top-bar-left">
          <button
            className="mobile-hamburger-btn"
            onClick={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
            aria-label="Toggle Sessions Sidebar"
          >
            ☰
          </button>
          <span className="wordmark">Kairo</span>
        </div>

        <div className="top-bar-right">
          {/* Single Status Pill */}
          <div className="status-pill-container">
            <button
              className="status-pill"
              onClick={() => setShowStatusTooltip(!showStatusTooltip)}
              onMouseEnter={() => setShowStatusTooltip(true)}
              onMouseLeave={() => setShowStatusTooltip(false)}
            >
              <span className={`status-dot ${statusInfo.dotClass}`} />
              <span>{statusInfo.text}</span>
            </button>

            {showStatusTooltip && (
              <div className="status-tooltip">
                <div className="status-tooltip-row">
                  <span>Model</span>
                  <strong>{modelCenter?.model_id || "None loaded"}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Kali Worker</span>
                  <strong>{vmStatus?.worker_online ? "Online" : "Offline"}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Session</span>
                  <strong>{sessionId.slice(0, 12)}</strong>
                </div>
              </div>
            )}
          </div>

          {/* Single Advanced Button */}
          <button
            className="ghost-btn"
            onClick={() => setIsAdvancedOpen(true)}
            aria-label="Open Advanced Panel"
          >
            ⚙ Advanced
          </button>
        </div>
      </header>

      {/* 2. MAIN BODY LAYOUT (TWO-COLUMN) */}
      <div className="main-layout">
        {/* Mobile Backdrop */}
        {isMobileSidebarOpen && (
          <div
            className="mobile-backdrop"
            onClick={() => setIsMobileSidebarOpen(false)}
            aria-label="Close sidebar overlay"
          />
        )}

        {/* Sidebar (260px) */}
        <aside className={`sidebar ${isMobileSidebarOpen ? "mobile-open" : ""}`}>
          <div className="sidebar-mobile-header">
            <span className="wordmark">Kairo</span>
            <button
              className="ghost-btn"
              onClick={() => setIsMobileSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              ✕
            </button>
          </div>

          <button className="new-session-btn" onClick={handleNewSession}>
            + New session
          </button>

          <div className="sidebar-section-label">Recent</div>
          <div className="session-list">
            {sessions.map((s) => (
              <button
                key={s.id}
                className={`session-item ${s.id === sessionId ? "active" : ""}`}
                onClick={() => {
                  setSessionId(s.id);
                  setIsMobileSidebarOpen(false);
                }}
              >
                <span className="session-title">{s.title}</span>
                <span className="session-time">{s.time}</span>
              </button>
            ))}
          </div>
        </aside>

        {/* Central Chat Area */}
        <main className="chat-container">
          <div className="messages-scroll-area">
            <div className="messages-inner">
              {messages.length === 0 ? (
                <div className="chat-empty-state">
                  <div className="chat-empty-icon">🛡️</div>
                  <p className="chat-empty-text">
                    Describe a security task in plain language to get started.
                  </p>
                </div>
              ) : (
                messages.map((m) => (
                  <div key={m.id} className={`turn-wrapper ${m.sender}`}>
                    {m.sender === "user" ? (
                      <div className="user-bubble">{m.text}</div>
                    ) : m.sender === "agent" ? (
                      <div className="agent-document">
                        {m.text && <p>{m.text}</p>}

                        {/* Inline Tool Execution Card */}
                        {m.tool && (
                          <div
                            className={`tool-card ${
                              m.execution && m.execution.exit_code !== 0 ? "failed" : ""
                            }`}
                          >
                            <div className="tool-card-header" onClick={() => toggleCard(m.id)}>
                              <div className="tool-card-left">
                                <span className="tool-card-title">
                                  🔧 {m.tool.name || m.tool.id}
                                </span>
                                <div className="tool-card-status">
                                  <span
                                    className={`status-dot ${
                                      m.execution?.exit_code === 0 ? "success" : "error"
                                    }`}
                                  />
                                  <span>
                                    {m.execution?.exit_code === 0 ? "success" : "failed"}
                                    {m.durationMs ? ` (${(m.durationMs / 1000).toFixed(1)}s)` : ""}
                                  </span>
                                </div>
                              </div>
                              <button className="tool-card-toggle">
                                {expandedCards[m.id] ? "▲ Details" : "▼ Details"}
                              </button>
                            </div>

                            {expandedCards[m.id] && (
                              <div className="tool-card-body">
                                {/* 1. Plain Language Summary */}
                                <div>
                                  <div className="tool-section-label">Summary</div>
                                  <div className="tool-summary-text">
                                    {m.execution?.exit_code === 0
                                      ? `Execution succeeded for ${m.tool.id}. Results verified against declared schema.`
                                      : `Execution failed with exit code ${m.execution?.exit_code || 1}.`}
                                  </div>
                                </div>

                                {/* 2. Why This Tool Scoring */}
                                {m.toolSelection?.selected_tool && (
                                  <div>
                                    <div className="tool-section-label">Why This Tool</div>
                                    <div className="scoring-bars-container">
                                      {m.toolSelection.selected_tool.dimension_scores.map((dim) => (
                                        <div key={dim.name} className="score-row">
                                          <div className="score-row-meta">
                                            <span>{dim.name.replace("_", " ")}</span>
                                            <span>{dim.score_pct}%</span>
                                          </div>
                                          <div className="score-bar-track">
                                            <div
                                              className="score-bar-fill"
                                              style={{ width: `${dim.score_pct}%` }}
                                            />
                                          </div>
                                          <span className="score-row-reason">
                                            {dim.raw_signal}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* 3. Command & Output */}
                                <div>
                                  <div className="tool-section-label">Command & Telemetry</div>
                                  <div className="code-block">
                                    {m.execution?.command && (
                                      <div>
                                        $ {m.execution.command} {m.execution.args?.join(" ")}
                                      </div>
                                    )}
                                    {m.execution?.stdout && <div>{m.execution.stdout}</div>}
                                    {m.execution?.stderr && (
                                      <div style={{ color: "var(--status-error)" }}>
                                        {m.execution.stderr}
                                      </div>
                                    )}
                                    {!m.execution?.stdout && !m.execution?.command && (
                                      <div>No stdout recorded.</div>
                                    )}
                                  </div>
                                </div>

                                {/* 4. Recovery Path */}
                                {m.recovery_path && m.recovery_path.length > 0 && (
                                  <div>
                                    <div className="tool-section-label">Recovery Path</div>
                                    <ul className="recovery-list">
                                      {m.recovery_path.map((step, idx) => (
                                        <li key={idx} className="recovery-step">
                                          <strong>{idx + 1}.</strong>
                                          <span>
                                            Tried {step.tool || "tool"} — {step.failure_reason || "failed"}.{" "}
                                            {step.action_taken || ""}
                                          </span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="system-notice">{m.text}</div>
                    )}
                  </div>
                ))
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Composer & Bottom Controls */}
          <footer className="chat-footer">
            <div className="chat-footer-inner">
              {/* Scope & Notice bar */}
              <div className="scope-indicator-bar">
                <button
                  className="scope-pill"
                  onClick={() => setShowScopePopover(!showScopePopover)}
                  title="Click to view Scope Contract details"
                >
                  🔒 Scope: {scopeInfo.target} · {scopeInfo.status}
                </button>

                {modelCenter && modelCenter.server_status !== "running" && (
                  <div className="offline-notice">
                    <span>No model is loaded.</span>
                    <a
                      onClick={() => {
                        setAdvancedTab("system");
                        setIsAdvancedOpen(true);
                      }}
                    >
                      Open Advanced → System to load one
                    </a>
                  </div>
                )}
              </div>

              {/* Scope Contract Popover */}
              {showScopePopover && (
                <div className="scope-popover">
                  <div className="scope-popover-title">
                    <span>Scope Contract</span>
                    <button
                      className="ghost-btn"
                      style={{ padding: "0 4px" }}
                      onClick={() => setShowScopePopover(false)}
                    >
                      ✕
                    </button>
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Target:</strong> {scopeInfo.target}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Allowed CIDRs:</strong>{" "}
                    {scopeInfo.cidrAllowed.join(", ")}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Excluded Hosts:</strong>{" "}
                    {scopeInfo.cidrExcluded.join(", ")}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Max Tool Tier:</strong>{" "}
                    {scopeInfo.maxTier}
                  </div>
                </div>
              )}

              {/* Composer Input Row */}
              <div className="composer-row">
                <textarea
                  ref={textareaRef}
                  className="composer-input"
                  rows={1}
                  value={inputVal}
                  onChange={(e) => setInputVal(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    wsStatus === "connected"
                      ? "Describe what you want to do…"
                      : "Connecting to Kairo…"
                  }
                  disabled={wsStatus !== "connected"}
                />
                <button
                  className="send-btn"
                  onClick={handleSend}
                  disabled={!inputVal.trim() || wsStatus !== "connected"}
                  aria-label="Send Message"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </button>
              </div>
            </div>
          </footer>
        </main>
      </div>

      {/* 3. ADVANCED DRAWER (480px) */}
      {isAdvancedOpen && (
        <div className="drawer-backdrop" onClick={() => setIsAdvancedOpen(false)}>
          <div className="drawer-container" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <span className="drawer-title">Advanced</span>
              <button
                className="ghost-btn"
                style={{ padding: "4px 8px" }}
                onClick={() => setIsAdvancedOpen(false)}
                aria-label="Close Advanced Drawer"
              >
                ✕
              </button>
            </div>

            <div className="drawer-body">
              {/* Left Nav Rail */}
              <nav className="drawer-nav-rail">
                {[
                  { id: "system", label: "System" },
                  { id: "events", label: "Event Log" },
                  { id: "terminal", label: "Terminal" },
                  { id: "screen", label: "Screen (VNC)" },
                  { id: "graph", label: "Task Graph" },
                  { id: "benchmarks", label: "Benchmarks" },
                  { id: "audit", label: "Audit" },
                  { id: "devtools", label: "Dev tools" },
                ].map((item) => (
                  <button
                    key={item.id}
                    className={`drawer-nav-item ${advancedTab === item.id ? "active" : ""}`}
                    onClick={() => setAdvancedTab(item.id as typeof advancedTab)}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>

              {/* Right Content Pane */}
              <div className="drawer-content-pane">
                {advancedTab === "system" && (
                  <div>
                    <h3>System & Hardware Telemetry</h3>
                    <div className="detail-table">
                      <div className="detail-row">
                        <span className="detail-row-label">Active Model</span>
                        <span className="detail-row-val">{modelCenter?.model_id || "None loaded"}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Model Server</span>
                        <span className="detail-row-val">{modelCenter?.server_status || "offline"}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Runtime Engine</span>
                        <span className="detail-row-val">{modelCenter?.runtime || "llama.cpp"}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Quantization</span>
                        <span className="detail-row-val">{modelCenter?.quantization || "Q4_K_M"}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Context Size</span>
                        <span className="detail-row-val">{modelCenter?.context_length || 4096} tokens</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">GPU VRAM</span>
                        <span className="detail-row-val">
                          {modelCenter?.vram ? `${modelCenter.vram.used_mb}MB / ${modelCenter.vram.total_mb}MB` : "Integrated"}
                        </span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Kali VM Worker</span>
                        <span className="detail-row-val">
                          {vmStatus?.worker_online ? "Online" : "Offline"} ({vmStatus?.vm_state || "unknown"})
                        </span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Gateway WebSocket</span>
                        <span className="detail-row-val">{wsStatus}</span>
                      </div>
                    </div>
                  </div>
                )}

                {advancedTab === "events" && (
                  <div>
                    <h3>SQLite Event Log</h3>
                    <div className="detail-table">
                      {allEvents.slice(0, 15).map((ev, i) => (
                        <div key={ev.id || i} className="detail-row">
                          <span className="detail-row-label">
                            {ev.tool_id || ev.actor || "event"}
                          </span>
                          <span className="detail-row-val" style={{ fontSize: "11px" }}>
                            exit {ev.exit_code ?? 0}
                          </span>
                        </div>
                      ))}
                      {allEvents.length === 0 && (
                        <div style={{ color: "var(--text-muted)", fontSize: "12px", padding: "8px 0" }}>
                          No operational events committed yet.
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {advancedTab === "terminal" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <h3>Live Kali Terminal Stream</h3>
                    <div style={{ flex: 1, minHeight: "400px" }}>
                      <TerminalProcessView
                        ws={wsInstance}
                        activeTaskId={activeTaskId}
                        onSelectTask={() => {}}
                        isMaximized={false}
                        onToggleMaximize={() => {}}
                      />
                    </div>
                  </div>
                )}

                {advancedTab === "screen" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <h3>Kali Desktop Stream (RFB/noVNC)</h3>
                    <div style={{ flex: 1, minHeight: "400px" }}>
                      <ScreenPanel
                        ws={wsInstance}
                        activeSessionId={sessionId}
                        isMaximized={false}
                        onToggleMaximize={() => {}}
                      />
                    </div>
                  </div>
                )}

                {advancedTab === "graph" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <h3>Task Graph (DAG Planner)</h3>
                    <div style={{ flex: 1, minHeight: "400px" }}>
                      <TaskGraphView ws={wsInstance} activeSessionId={sessionId} />
                    </div>
                  </div>
                )}

                {advancedTab === "benchmarks" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <h3>Leaderboard & Training</h3>
                    <BenchmarkLeaderboard />
                    <DatasetCurationPanel />
                  </div>
                )}

                {advancedTab === "audit" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <h3>Audit Explorer</h3>
                    <AuditExplorer />
                  </div>
                )}

                {advancedTab === "devtools" && (
                  <div className="dev-tools-container">
                    <h3>Internal Debug Actions</h3>
                    <p className="dev-notice">
                      These actions are developer fixtures for validating the VirtualBox worker,
                      process isolation, and timeout limits.
                    </p>

                    <button
                      className="dev-action-btn"
                      onClick={() =>
                        triggerDevAction("tool_call", {
                          tool: "kali.exec.v1",
                          args: { command: "uname", args: ["-a"] },
                        })
                      }
                    >
                      ▶ Execute `kali.exec.v1: uname -a`
                    </button>

                    <button
                      className="dev-action-btn"
                      onClick={() =>
                        triggerDevAction("tool_call", {
                          tool: "shell.run.v1",
                          args: { command: "date" },
                        })
                      }
                    >
                      ▶ Execute `shell.run.v1: date`
                    </button>

                    <button
                      className="dev-action-btn"
                      onClick={() =>
                        triggerDevAction("tool_call", {
                          tool: "kali.exec.v1",
                          args: { command: "sleep", args: ["5"] },
                          timeout_ms: 800,
                        })
                      }
                    >
                      ▶ Trigger Simulated Timeout (800ms limit)
                    </button>

                    <button
                      className="dev-action-btn danger"
                      onClick={() => {
                        if (activeTaskId && wsRef.current) {
                          wsRef.current.send(JSON.stringify({ type: "kill", taskId: activeTaskId }));
                        }
                      }}
                    >
                      ☠️ Emergency SIGKILL Active Task
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
