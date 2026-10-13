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
  const [isAdvancedWide, setIsAdvancedWide] = useState<boolean>(false);
  const [advancedTab, setAdvancedTab] = useState<
    "system" | "events" | "terminal" | "screen" | "graph" | "benchmarks" | "audit" | "devtools"
  >("system");
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [showStatusTooltip, setShowStatusTooltip] = useState<boolean>(false);
  const [showScopePopover, setShowScopePopover] = useState<boolean>(false);
  const [copiedSession, setCopiedSession] = useState<boolean>(false);
  const [eventSearch, setEventSearch] = useState<string>("");
  const [eventFilterMode, setEventFilterMode] = useState<"all" | "success" | "error">("all");
  const [expandedEventId, setExpandedEventId] = useState<number | null>(null);
  const [devCustomCmd, setDevCustomCmd] = useState<string>("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});
  const [selectedModel, setSelectedModel] = useState<string>("Kairo 3.7 (Cyber-Ops Sonnet)");
  const [showModelMenu, setShowModelMenu] = useState<boolean>(false);

  const toggleThinking = (id: string) => {
    setExpandedThinking((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const openToolInConsole = (toolId?: string) => {
    if (!toolId) {
      setAdvancedTab("events");
    } else if (toolId.includes("terminal") || toolId.includes("kali") || toolId.includes("shell") || toolId.includes("exec")) {
      setAdvancedTab("terminal");
    } else if (toolId.includes("novnc") || toolId.includes("screen") || toolId.includes("gui") || toolId.includes("desktop")) {
      setAdvancedTab("screen");
    } else if (toolId.includes("planner") || toolId.includes("graph") || toolId.includes("decompose")) {
      setAdvancedTab("graph");
    } else if (toolId.includes("audit") || toolId.includes("evidence") || toolId.includes("cve")) {
      setAdvancedTab("audit");
    } else {
      setAdvancedTab("events");
    }
    setIsAdvancedOpen(true);
  };

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

  // Keyboard Escape listener to close Advanced drawer
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isAdvancedOpen) {
        setIsAdvancedOpen(false);
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [isAdvancedOpen]);

  // Copy session ID with feedback
  const handleCopySession = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(sessionId);
      setCopiedSession(true);
      setTimeout(() => setCopiedSession(false), 2000);
    }
  };

  // Filtered SQLite events for Event Log tab
  const filteredEvents = useMemo(() => {
    return allEvents.filter((ev) => {
      if (eventFilterMode === "success" && ev.exit_code !== 0 && ev.exit_code !== undefined) {
        return false;
      }
      if (eventFilterMode === "error" && (ev.exit_code === 0 || ev.exit_code === undefined)) {
        return false;
      }
      if (!eventSearch.trim()) return true;
      const term = eventSearch.toLowerCase();
      const matchTool = (ev.tool_id || "").toLowerCase().includes(term);
      const matchActor = (ev.actor || "").toLowerCase().includes(term);
      const matchArgs = (ev.requested_args || "").toLowerCase().includes(term);
      const matchSummary = (ev.result_summary || "").toLowerCase().includes(term);
      return matchTool || matchActor || matchArgs || matchSummary;
    });
  }, [allEvents, eventFilterMode, eventSearch]);

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
      {/* 1. TOP BAR (Claude Minimalist Style) */}
      <header className="top-bar">
        <div className="top-bar-left">
          <button
            className="sidebar-toggle-btn"
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            aria-label="Toggle Sessions Sidebar"
            title={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M9 3v18" />
            </svg>
          </button>
          <button
            className="mobile-hamburger-btn"
            onClick={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
            aria-label="Toggle Sessions Sidebar"
          >
            ☰
          </button>
          <div className="wordmark-container" onClick={handleNewSession}>
            <svg className="wordmark-spark" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
            </svg>
            <span className="wordmark">Kairo</span>
            <span className="wordmark-badge">Claude v3.0</span>
          </div>
        </div>

        {/* Center: Claude Model Selector */}
        <div className="top-bar-center">
          <div className="model-picker-container">
            <button
              className="claude-model-pill"
              onClick={() => setShowModelMenu(!showModelMenu)}
              aria-label="Select Model"
            >
              <span className="model-pill-spark">✦</span>
              <span>{selectedModel}</span>
              <span className="model-pill-chevron">{showModelMenu ? "▲" : "▼"}</span>
            </button>
            {showModelMenu && (
              <div className="model-dropdown-menu">
                <button
                  className={`model-dropdown-item ${selectedModel.includes("Sonnet") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("Kairo 3.7 (Cyber-Ops Sonnet)"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>Kairo 3.7 (Sonnet Tier)</span>
                    <span className="wordmark-badge">Default</span>
                  </div>
                  <span className="model-item-desc">High-capability autonomous planning & Kali VM reasoning</span>
                </button>
                <button
                  className={`model-dropdown-item ${selectedModel.includes("Haiku") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("Kairo 3.5 (Haiku Fast)"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>Kairo 3.5 (Haiku Fast)</span>
                    <span style={{ fontSize: "10px", color: "var(--accent-green)" }}>⚡ Low Latency</span>
                  </div>
                  <span className="model-item-desc">High-speed port discovery & initial banner reconnaissance</span>
                </button>
                <button
                  className={`model-dropdown-item ${selectedModel.includes("Llama") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("Llama-3-70B Pentest SFT"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>Llama-3-70B Pentest SFT</span>
                    <span style={{ fontSize: "10px", color: "var(--accent-blue)" }}>Fine-Tuned</span>
                  </div>
                  <span className="model-item-desc">Local 70B cyber-ops weights with strict grammar constraints</span>
                </button>
                <button
                  className={`model-dropdown-item ${selectedModel.includes("DeepSeek") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("DeepSeek-R1 Reasoner"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>DeepSeek-R1 Reasoner</span>
                    <span style={{ fontSize: "10px", color: "var(--accent-amber)" }}>Thinking</span>
                  </div>
                  <span className="model-item-desc">Deep chain-of-thought mathematical and exploit analysis</span>
                </button>
              </div>
            )}
          </div>
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
              <div key="status-tooltip" className="status-tooltip">
                <div className="status-tooltip-row">
                  <span>Model Engine</span>
                  <strong>{modelCenter?.model_id || selectedModel}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Kali Worker VM</span>
                  <strong>{vmStatus?.worker_online ? "Online" : "Offline"}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Scope Boundary</span>
                  <strong>{scopeInfo.target}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Session Hash</span>
                  <strong>{sessionId.slice(0, 12)}</strong>
                </div>
              </div>
            )}
          </div>

          {/* Claude Split Console / Artifacts Button */}
          <button
            className="console-btn"
            onClick={() => setIsAdvancedOpen(true)}
            aria-label="Open Console and Artifacts"
            title="Open Console, Artifacts, and Subsystem Telemetry"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <line x1="15" x2="15" y1="3" y2="21" />
            </svg>
            <span>⚙ Advanced</span>
          </button>
        </div>
      </header>

      {/* 2. MAIN BODY LAYOUT (TWO-COLUMN) */}
      <div className="main-layout">
        {/* Mobile Backdrop */}
        {isMobileSidebarOpen && (
          <div
            key="mobile-backdrop"
            className="mobile-backdrop"
            onClick={() => setIsMobileSidebarOpen(false)}
            aria-label="Close sidebar overlay"
          />
        )}

        {/* Sidebar (Claude-styled 260px) */}
        <aside className={`sidebar ${isSidebarCollapsed ? "collapsed" : ""} ${isMobileSidebarOpen ? "mobile-open" : ""}`}>
          <div className="sidebar-mobile-header">
            <div className="wordmark-container">
              <svg className="wordmark-spark" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
              </svg>
              <span className="wordmark">Kairo</span>
            </div>
            <button
              className="ghost-btn"
              onClick={() => setIsMobileSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              ✕
            </button>
          </div>

          <button className="new-session-btn" onClick={handleNewSession}>
            <div className="new-session-left">
              <span className="new-session-spark">✦</span>
              <span>New session</span>
            </div>
            <span className="new-session-shortcut">Ctrl K</span>
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

          {/* Bottom Operator Profile Card */}
          <div className="sidebar-profile-card">
            <div className="profile-avatar">OP</div>
            <div className="profile-info">
              <span className="profile-name">Security Operator</span>
              <span className="profile-tier">Airgap · Tier 2 Authorized</span>
            </div>
          </div>
        </aside>

        {/* Central Chat Area */}
        <main className="chat-container">
          <div className="messages-scroll-area">
            <div className="messages-inner">
              {messages.length === 0 ? (
                /* Claude Welcome Screen with 4 Starter Cards */
                <div className="claude-welcome-container">
                  <svg className="claude-welcome-spark" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
                  </svg>
                  <h1 className="claude-welcome-title">What would you like to investigate today?</h1>
                  <p className="claude-welcome-subtitle">
                    Kairo is your autonomous cyber defense cockpit. Select an operational template or describe a security directive in plain language below.
                  </p>

                  <div className="claude-starter-grid">
                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setInputVal("Perform comprehensive reconnaissance and port discovery against 192.168.1.0/24");
                        textareaRef.current?.focus();
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">🔍</span>
                        <span className="claude-starter-title">Reconnaissance &amp; Scan</span>
                      </div>
                      <p className="claude-starter-desc">Map attack surface and identify open ports on target subnet</p>
                    </div>

                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setInputVal("Conduct comprehensive penetration test against 192.168.1.50 with parallel decomposition");
                        textareaRef.current?.focus();
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">⚡</span>
                        <span className="claude-starter-title">Autonomous DAG Plan</span>
                      </div>
                      <p className="claude-starter-desc">Decompose multi-stage penetration test into ordered tasks</p>
                    </div>

                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setInputVal("Launch isolated Kali Linux terminal session to inspect network interfaces and services");
                        textareaRef.current?.focus();
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">💻</span>
                        <span className="claude-starter-title">Kali Terminal Session</span>
                      </div>
                      <p className="claude-starter-desc">Launch isolated CLI sandbox environment with live audit</p>
                    </div>

                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setInputVal("Inspect verified vulnerability findings, evidence store, and generate compliance report");
                        textareaRef.current?.focus();
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">🛡️</span>
                        <span className="claude-starter-title">Audit Findings &amp; CVEs</span>
                      </div>
                      <p className="claude-starter-desc">Inspect verified vulnerability findings and evidence store</p>
                    </div>
                  </div>
                </div>
              ) : (
                messages.map((m) => (
                  <div key={m.id} className={`turn-wrapper ${m.sender}`}>
                    {m.sender === "user" ? (
                      <div className="user-bubble">{m.text}</div>
                    ) : m.sender === "agent" ? (
                      <div className="agent-document">
                        <div className="agent-header">
                          <div className="agent-avatar">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                              <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
                            </svg>
                          </div>
                          <span className="agent-name">Kairo</span>
                          <span className="agent-model-badge">Sonnet-Grade</span>
                          <span className="agent-timestamp">{m.timestamp || "Just now"}</span>
                        </div>

                        {/* Claude 3.7 Extended Thinking Accordion */}
                        {(m.toolSelection || m.recovery_path || m.durationMs) && (
                          <div className="claude-thinking-block">
                            <button className="claude-thinking-toggle" onClick={() => toggleThinking(m.id)}>
                              <div className="thinking-left">
                                <span className="thinking-spark">✦</span>
                                <span>Thought for {m.durationMs ? `${(m.durationMs / 1000).toFixed(1)}s` : "1.4s"}</span>
                              </div>
                              <span className="thinking-chevron">{expandedThinking[m.id] ? "▲" : "▼"}</span>
                            </button>
                            {expandedThinking[m.id] && (
                              <div className="claude-thinking-content">
                                <div style={{ marginBottom: "6px" }}>
                                  <strong style={{ color: "var(--text-primary)" }}>Cognitive Evaluation:</strong> Evaluated goal requirements against Scope Contract <code>{scopeInfo.target}</code> and tool safety tier.
                                </div>
                                {m.toolSelection?.selection_reason && (
                                  <div style={{ marginBottom: "6px" }}>
                                    <strong style={{ color: "var(--text-primary)" }}>Tool Selection Rationale:</strong> {m.toolSelection.selection_reason}
                                  </div>
                                )}
                                {m.recovery_narrative && (
                                  <div>
                                    <strong style={{ color: "var(--status-warning)" }}>Self-Healing Recovery:</strong> {m.recovery_narrative}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}

                        {m.text && <div className="agent-body-text">{m.text}</div>}

                        {/* Claude Artifact / Tool Execution Card */}
                        {m.tool && (
                          <div
                            className={`tool-card ${
                              m.execution && m.execution.exit_code !== 0 ? "failed" : ""
                            }`}
                          >
                            <div className="tool-card-header">
                              <div className="tool-card-left">
                                <span className="artifact-pill">Artifact</span>
                                <span className="tool-card-title">
                                  {m.tool.name || m.tool.id}
                                </span>
                                <div className="tool-card-status">
                                  <span
                                    className={`status-dot ${
                                      m.execution?.exit_code === 0 ? "success" : "error"
                                    }`}
                                  />
                                  <span>
                                    {m.execution?.exit_code === 0 ? "Verified" : "Failed"}
                                    {m.durationMs ? ` (${(m.durationMs / 1000).toFixed(1)}s)` : ""}
                                  </span>
                                </div>
                              </div>
                              <div className="tool-card-actions">
                                <button
                                  className="open-console-btn"
                                  onClick={() => openToolInConsole(m.tool?.id)}
                                  title="Inspect in Advanced Console"
                                >
                                  Open in Console ↗
                                </button>
                                <button
                                  className="tool-card-toggle"
                                  onClick={() => toggleCard(m.id)}
                                >
                                  {expandedCards[m.id] ? "▲ Details" : "▼ Details"}
                                </button>
                              </div>
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
                                  <div className="tool-section-label">Command &amp; Telemetry</div>
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

          {/* Claude Floating Composer & Bottom Controls */}
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
                <div key="scope-popover" className="scope-popover">
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

              {/* Claude Rounded Composer */}
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
                      ? "Reply to Kairo or enter an autonomous cyber security directive…"
                      : "Connecting to Kairo Gateway…"
                  }
                  disabled={wsStatus !== "connected"}
                />
                <div className="composer-actions-bottom">
                  <div className="composer-tools-left">
                    <span
                      className="composer-model-pill"
                      style={{ cursor: "pointer" }}
                      onClick={() => setShowModelMenu(true)}
                    >
                      ✦ {selectedModel.split(" ")[0]}
                    </span>
                  </div>
                  <button
                    className="send-btn"
                    onClick={handleSend}
                    disabled={!inputVal.trim() || wsStatus !== "connected"}
                    aria-label="Send Directive"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="12" y1="19" x2="12" y2="5" />
                      <polyline points="5 12 12 5 19 12" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </footer>
        </main>
      </div>

      {/* 3. ADVANCED DRAWER */}
      {isAdvancedOpen && (
        <div key="drawer-backdrop" className="drawer-backdrop" onClick={() => setIsAdvancedOpen(false)}>
          <div
            className={`drawer-container ${isAdvancedWide ? "wide" : ""}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-header">
              <div className="drawer-header-left">
                <span className="drawer-title">Advanced</span>
                <span className="drawer-subtitle">
                  {advancedTab.toUpperCase()} · {sessionId.slice(0, 14)}
                </span>
              </div>
              <div className="drawer-header-actions">
                <button
                  className="ghost-btn"
                  style={{ padding: "4px 8px", fontSize: "12px" }}
                  onClick={() => setIsAdvancedWide(!isAdvancedWide)}
                  title={isAdvancedWide ? "Standard Width (520px)" : "Expand Console (840px)"}
                >
                  {isAdvancedWide ? "🗗 Standard" : "⛶ Expand"}
                </button>
                <button
                  className="ghost-btn"
                  style={{ padding: "4px 8px" }}
                  onClick={() => setIsAdvancedOpen(false)}
                  aria-label="Close Advanced Drawer"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="drawer-body">
              {/* Categorized Left Nav Rail */}
              <nav className="drawer-nav-rail">
                <div className="drawer-nav-group-label">Core</div>
                <button
                  className={`drawer-nav-item ${advancedTab === "system" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("system")}
                >
                  <span>System</span>
                  <span
                    className={`status-dot ${
                      modelCenter?.server_status === "running" ? "success" : "error"
                    }`}
                  />
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "events" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("events")}
                >
                  <span>Event Log</span>
                  <span className="drawer-nav-badge">{allEvents.length}</span>
                </button>

                <div className="drawer-nav-group-label">Operations</div>
                <button
                  className={`drawer-nav-item ${advancedTab === "terminal" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("terminal")}
                >
                  <span>Terminal</span>
                  <span className="drawer-nav-badge">CLI</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "screen" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("screen")}
                >
                  <span>Screen (VNC)</span>
                  <span className="drawer-nav-badge">GUI</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "graph" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("graph")}
                >
                  <span>Task Graph</span>
                  <span className="drawer-nav-badge">DAG</span>
                </button>

                <div className="drawer-nav-group-label">Security</div>
                <button
                  className={`drawer-nav-item ${advancedTab === "audit" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("audit")}
                >
                  <span>Audit</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "benchmarks" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("benchmarks")}
                >
                  <span>Benchmarks</span>
                </button>

                <div className="drawer-nav-group-label">Testing</div>
                <button
                  className={`drawer-nav-item ${advancedTab === "devtools" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("devtools")}
                >
                  <span>Dev tools</span>
                  <span style={{ fontSize: "11px" }}>⚠️</span>
                </button>
              </nav>

              {/* Right Content Pane */}
              <div className="drawer-content-pane">
                {advancedTab === "system" && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <h3>System &amp; Hardware Telemetry</h3>
                    </div>

                    <div className="drawer-quick-actions">
                      <button className="action-pill-btn" onClick={fetchTelemetry} title="Poll latest orchestrator telemetry">
                        ↻ Refresh Telemetry
                      </button>
                      <button
                        className={`action-pill-btn ${copiedSession ? "success" : ""}`}
                        onClick={handleCopySession}
                        title="Copy session identifier"
                      >
                        {copiedSession ? "✓ Copied!" : "📋 Copy Session ID"}
                      </button>
                    </div>

                    <div className="detail-table">
                      <div className="detail-row">
                        <span className="detail-row-label">Active Model</span>
                        <span className="detail-row-val">{modelCenter?.model_id || "None loaded"}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Model Server</span>
                        <span className="detail-row-val">
                          <span
                            className={`status-dot ${
                              modelCenter?.server_status === "running" ? "success" : "error"
                            }`}
                          />
                          {modelCenter?.server_status || "offline"}
                        </span>
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
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          {modelCenter?.vram && (
                            <div className="gauge-container">
                              <div className="gauge-track">
                                <div
                                  className="gauge-fill"
                                  style={{ width: `${Math.min(modelCenter.vram.utilization_pct || 0, 100)}%` }}
                                />
                              </div>
                            </div>
                          )}
                          <span className="detail-row-val">
                            {modelCenter?.vram
                              ? `${modelCenter.vram.used_mb}MB / ${modelCenter.vram.total_mb}MB`
                              : "Integrated / CPU"}
                          </span>
                        </div>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Kali VM Worker</span>
                        <span className="detail-row-val">
                          <span
                            className={`status-dot ${
                              vmStatus?.worker_online ? "success" : "warning"
                            }`}
                          />
                          {vmStatus?.worker_online ? "Online" : "Offline"} ({vmStatus?.vm_state || "poweroff"})
                        </span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-row-label">Gateway WebSocket</span>
                        <span className="detail-row-val">
                          <span
                            className={`status-dot ${
                              wsStatus === "connected" ? "success" : "error"
                            }`}
                          />
                          {wsStatus}
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {advancedTab === "events" && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <h3>SQLite Operational Event Log</h3>
                      <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                        {filteredEvents.length} of {allEvents.length} events
                      </span>
                    </div>

                    <div className="event-filter-bar">
                      <input
                        type="text"
                        className="event-search-input"
                        placeholder="Search events by tool, actor, or arguments..."
                        value={eventSearch}
                        onChange={(e) => setEventSearch(e.target.value)}
                      />
                      <div className="event-filter-pills">
                        <button
                          className={`event-filter-pill ${eventFilterMode === "all" ? "active" : ""}`}
                          onClick={() => setEventFilterMode("all")}
                        >
                          All ({allEvents.length})
                        </button>
                        <button
                          className={`event-filter-pill ${eventFilterMode === "success" ? "active" : ""}`}
                          onClick={() => setEventFilterMode("success")}
                        >
                          Success ({allEvents.filter((e) => (e.exit_code ?? 0) === 0).length})
                        </button>
                        <button
                          className={`event-filter-pill ${eventFilterMode === "error" ? "active" : ""}`}
                          onClick={() => setEventFilterMode("error")}
                        >
                          Failures ({allEvents.filter((e) => (e.exit_code ?? 0) !== 0).length})
                        </button>
                      </div>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                      {filteredEvents.slice(0, 30).map((ev, i) => {
                        const evId = typeof ev.id === "number" ? ev.id : i;
                        const isExpanded = expandedEventId === evId;
                        return (
                          <div key={`evt_${ev.id ?? "idx"}_${i}`} className="event-card">
                            <div
                              className="event-card-header"
                              onClick={() => setExpandedEventId(isExpanded ? null : evId)}
                            >
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  className={`status-dot ${
                                    (ev.exit_code ?? 0) === 0 ? "success" : "error"
                                  }`}
                                />
                                <strong style={{ color: "var(--text-primary)" }}>
                                  {ev.tool_id || ev.actor || "event"}
                                </strong>
                                <span style={{ color: "var(--text-muted)", fontSize: "11px" }}>
                                  {ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : ""}
                                </span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  style={{
                                    fontSize: "11px",
                                    fontFamily: "var(--font-mono)",
                                    color:
                                      (ev.exit_code ?? 0) === 0
                                        ? "var(--status-success)"
                                        : "var(--status-error)",
                                  }}
                                >
                                  exit {ev.exit_code ?? 0}
                                </span>
                                <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                                  {isExpanded ? "▲" : "▼"}
                                </span>
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="event-card-details">
                                {ev.task_id && <div><strong>Task ID:</strong> {ev.task_id}</div>}
                                {ev.requested_args && (
                                  <div>
                                    <strong>Args:</strong> {ev.requested_args}
                                  </div>
                                )}
                                {ev.result_summary && (
                                  <div>
                                    <strong>Summary:</strong> {ev.result_summary}
                                  </div>
                                )}
                                {ev.stdout_ref && <div><strong>Stdout Ref:</strong> {ev.stdout_ref}</div>}
                              </div>
                            )}
                          </div>
                        );
                      })}

                      {filteredEvents.length === 0 && (
                        <div style={{ color: "var(--text-muted)", fontSize: "12px", padding: "16px 0", textAlign: "center" }}>
                          No operational events match current filter.
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {advancedTab === "terminal" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <div style={{ flex: 1, minHeight: "450px" }}>
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
                    <div style={{ flex: 1, minHeight: "450px" }}>
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
                    <div style={{ flex: 1, minHeight: "450px" }}>
                      <TaskGraphView ws={wsInstance} activeSessionId={sessionId} />
                    </div>
                  </div>
                )}

                {advancedTab === "benchmarks" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <h3>Leaderboard &amp; Training</h3>
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
                      These actions are developer fixtures for validating sandbox isolation, process timeouts,
                      and fault-tolerance recovery workflows.
                    </p>

                    {/* Interactive Sandbox Command Runner */}
                    <div className="dev-group-card">
                      <span className="dev-group-title">Interactive Sandbox Runner</span>
                      <form
                        className="dev-cmd-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          if (devCustomCmd.trim()) {
                            triggerDevAction("tool_call", {
                              tool: "kali.exec.v1",
                              args: { command: devCustomCmd.trim() },
                            });
                            setDevCustomCmd("");
                          }
                        }}
                      >
                        <input
                          type="text"
                          className="dev-cmd-input"
                          placeholder="Command to exec (e.g. whoami, id, uptime)..."
                          value={devCustomCmd}
                          onChange={(e) => setDevCustomCmd(e.target.value)}
                        />
                        <button
                          type="submit"
                          className="action-pill-btn"
                          style={{ padding: "6px 14px", color: "var(--accent)" }}
                        >
                          Execute
                        </button>
                      </form>
                    </div>

                    {/* Preset Worker Checks */}
                    <div className="dev-group-card">
                      <span className="dev-group-title">Environment Validation Checks</span>
                      <button
                        className="dev-action-btn"
                        onClick={() =>
                          triggerDevAction("tool_call", {
                            tool: "kali.exec.v1",
                            args: { command: "uname", args: ["-a"] },
                          })
                        }
                      >
                        ▶ Execute `kali.exec.v1: uname -a` (OS Architecture)
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
                        ▶ Execute `shell.run.v1: date` (Host Clock Verification)
                      </button>
                    </div>

                    {/* Fault Tolerance and Kill Switch */}
                    <div className="dev-group-card">
                      <span className="dev-group-title">Fault Tolerance &amp; Process Control</span>
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
                        ⏱️ Trigger Simulated Timeout (800ms limit test)
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
