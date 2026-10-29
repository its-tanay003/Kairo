"use client";

import React, { useEffect, useRef, useState, useMemo, useCallback } from "react";
import TerminalProcessView from "./components/TerminalProcessView";
import TaskGraphView from "./components/TaskGraphView";
import ScreenPanel from "./components/ScreenPanel";
import AuditExplorer from "./components/AuditExplorer";
import DatasetCurationPanel from "./components/DatasetCurationPanel";
import BenchmarkLeaderboard from "./components/BenchmarkLeaderboard";
import ModelEvolutionPanel from "./components/ModelEvolutionPanel";
import ToolKnowledgeCenter from "./components/ToolKnowledgeCenter";
import UpdatesPanel from "./components/UpdatesPanel";
import AdvancedSettingsPanel from "./components/AdvancedSettingsPanel";
import ClaudeOutputCard, {
  ClaudeSynthesisPayload,
  ClaudeToolSelectionMeta,
  ClaudeTaskPlan,
  ClaudeStepProvenanceItem,
  ClaudeNextStepRec,
} from "./components/ClaudeOutputCard";

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
  synthesis?: ClaudeSynthesisPayload;
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
  eventId?: string | number;
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
  synthesis?: ClaudeSynthesisPayload;
  modelId?: string;
  modelRole?: string;
  modelVerification?: {
    selected_model?: string;
    actual_model_id?: string;
    inference_runtime?: string;
    processed_by_selected_model?: boolean;
    structured_output?: {
      action: string;
      content: string;
      tool_call?: {
        name: string;
        arguments: Record<string, unknown>;
      };
    };
    selected_tool?: string;
    validated_args?: Record<string, unknown> | unknown[];
    fallback_used?: boolean;
    fallback_reason?: string;
    local_only?: boolean;
    timestamp?: string;
  };
  selectedModel?: string;
  actualModelId?: string;
  inferenceRuntime?: string;
  processedBySelectedModel?: boolean;
  structuredOutput?: Record<string, unknown>;
  selectedTool?: string;
  validatedArgs?: Record<string, unknown> | unknown[];
  fallbackUsed?: boolean;
  fallbackReason?: string;
  intent?: string;
  planOnly?: boolean;
  plan?: ClaudeTaskPlan;
  stepProvenance?: ClaudeStepProvenanceItem[];
  handledByCustomModel?: boolean;
  handledByFallback?: boolean;
  nextStepRecommendations?: ClaudeNextStepRec[];
  next_step_recommendations?: ClaudeNextStepRec[];
}

export interface ModelOption {
  id: string;
  name: string;
  shortName: string;
  badge?: string;
  badgeClass?: string;
  badgeColor?: string;
  desc: string;
  role: string;
}

const AVAILABLE_MODELS: ModelOption[] = [
  {
    id: "kairo-scale-2b",
    name: "Kairo Scale 2B (Custom Primary)",
    shortName: "Kairo Scale 2B",
    badge: "Custom Model",
    badgeClass: "wordmark-badge",
    desc: "Locally-trained 2B causal architecture with GRPO alignment",
    role: "primary-custom-scaled-tier-c",
  },
  {
    id: "Qwen2.5-0.5B-Instruct",
    name: "Qwen2.5-0.5B (Local Fallback)",
    shortName: "Qwen2.5-0.5B Fallback",
    badge: "⚡ Fast GGUF",
    badgeColor: "var(--accent-green)",
    desc: "Lightweight quantized GGUF local model for fast offline triage",
    role: "fallback",
  },
  {
    id: "kairo-scale-2b-grpo",
    name: "Kairo GRPO Final (Reasoner)",
    shortName: "Kairo GRPO Reasoner",
    badge: "RL Aligned",
    badgeColor: "var(--accent-amber)",
    desc: "Kairo 2B checkpoint reinforced with Schema and Verifier rewards",
    role: "primary-custom-scaled-grpo",
  },
  {
    id: "Qwen3-Coder-30B-A3B-Instruct",
    name: "Qwen3-Coder-30B (MoE Base)",
    shortName: "Qwen3-Coder-30B",
    badge: "Advanced",
    badgeColor: "var(--accent-blue)",
    desc: "Large local Mixture-of-Experts coder model for advanced exploit generation",
    role: "primary",
  },
];

interface ModelCenterStatus {
  model_id: string;
  runtime: string;
  quantization: string;
  context_length: number;
  role: string;
  server_status: string;
  server_url: string;
  ready?: boolean;
  is_primary_custom?: boolean;
  real_backend_status?: {
    active_model_id: string;
    runtime: string;
    role: string;
    ready: boolean;
    is_primary_custom: boolean;
    custom_primary_ready: boolean;
    fallback_ready: boolean;
    fallback_model_id: string;
    local_only: boolean;
    cloud_prevented: boolean;
  };
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

let msgCounter = 0;
function createUniqueMsgId(prefix: string, explicitId?: string): string {
  msgCounter = (msgCounter + 1) % 1000000;
  const rand = Math.random().toString(36).substring(2, 8);
  const ts = Date.now();
  if (explicitId && typeof explicitId === "string" && explicitId.trim()) {
    return `${explicitId.trim()}_${ts}_${msgCounter}_${rand}`;
  }
  return `msg_${ts}_${msgCounter}_${rand}_${prefix}`;
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
  const [latestPlan, setLatestPlan] = useState<ClaudeTaskPlan | null>(null);

  // Drawer and Dialogs State
  const [isAdvancedOpen, setIsAdvancedOpen] = useState<boolean>(false);
  const [isAdvancedWide, setIsAdvancedWide] = useState<boolean>(false);
  const [advancedTab, setAdvancedTab] = useState<
    "system" | "events" | "terminal" | "screen" | "graph" | "benchmarks" | "audit" | "devtools" | "evolution" | "knowledge" | "updates" | "settings"
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
  const [selectedModel, setSelectedModel] = useState<string>("Kairo Scale 2B (Custom Primary)");
  const [selectedModelId, setSelectedModelId] = useState<string>("kairo-scale-2b");
  const [showModelMenu, setShowModelMenu] = useState<boolean>(false);

  const handleSelectModel = (modelId: string, modelName: string) => {
    setSelectedModel(modelName);
    setSelectedModelId(modelId);
    setShowModelMenu(false);

    // 1. Notify Gateway WebSocket clients
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "select_model",
          modelId,
          sessionId,
        })
      );
    }

    // 2. Trigger Orchestrator backend model switch immediately
    fetch("http://localhost:8000/model-center/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.active_model) {
          setModelCenter((prev) =>
            prev ? { ...prev, model_id: data.active_model.model_id, role: data.active_model.role } : null
          );
        }
        fetchTelemetry();
      })
      .catch(() => {
        // Fallback through Gateway proxy
        fetch("http://localhost:4000/model-center/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: modelId }),
        })
          .then((res) => (res.ok ? res.json() : null))
          .then(() => fetchTelemetry())
          .catch((err) => console.error("Model select error:", err));
      });
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

  const handleUsePromptInChat = (promptText: string) => {
    setInputVal(promptText);
    setIsAdvancedOpen(false);
    setTimeout(() => {
      const textarea = document.querySelector(".claude-composer-input") as HTMLTextAreaElement | null;
      if (textarea) {
        textarea.focus();
      }
    }, 100);
  };

  // System & Telemetry Data
  const [modelCenter, setModelCenter] = useState<ModelCenterStatus | null>(null);
  const [vmStatus, setVmStatus] = useState<VMStatus | null>(null);
  const [allEvents, setAllEvents] = useState<EventRecord[]>([]);

  // Active Scope Contract info
  const [scopeInfo, setScopeInfo] = useState<{
    target: string;
    cidrAllowed: string[];
    cidrExcluded: string[];
    authorizationMode: string;
    status: string;
    contractId?: string;
    signatureValid?: boolean;
    secondsRemaining?: number;
  }>({
    target: "192.168.1.0/24",
    cidrAllowed: ["192.168.1.0/24", "10.0.0.0/8"],
    cidrExcluded: ["192.168.1.1", "10.0.0.1"],
    authorizationMode: "Unified Access (ADR-004)",
    status: "Active",
  });

  const fetchActiveScope = useCallback(() => {
    fetch("http://localhost:4000/scope/active")
      .then((res) => (res.ok ? res.json() : null))
      .then((contract) => {
        if (contract && (contract.targets || contract.contract_id)) {
          setScopeInfo({
            target: (contract.targets && contract.targets[0]) || "127.0.0.1",
            cidrAllowed: contract.targets || ["127.0.0.1"],
            cidrExcluded: contract.metadata?.excluded_targets || ["192.168.1.1"],
            authorizationMode: "Unified Access (ADR-004)",
            status: contract.is_expired ? "Expired" : "Active",
            contractId: contract.contract_id,
            signatureValid: contract.signature_valid ?? true,
            secondsRemaining: contract.seconds_remaining,
          });
        }
      })
      .catch(() => {
        fetch("http://localhost:8000/scope/active")
          .then((res) => (res.ok ? res.json() : null))
          .then((contract) => {
            if (contract && (contract.targets || contract.contract_id)) {
              setScopeInfo({
                target: (contract.targets && contract.targets[0]) || "127.0.0.1",
                cidrAllowed: contract.targets || ["127.0.0.1"],
                cidrExcluded: contract.metadata?.excluded_targets || ["192.168.1.1"],
                authorizationMode: "Unified Access (ADR-004)",
                status: contract.is_expired ? "Expired" : "Active",
                contractId: contract.contract_id,
                signatureValid: contract.signature_valid ?? true,
                secondsRemaining: contract.seconds_remaining,
              });
            }
          })
          .catch(() => {});
      });
  }, []);

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
      .then((data) => {
        if (data) {
          setModelCenter(data);
          if (data.model_id) {
            setSelectedModelId(data.model_id);
            const found = AVAILABLE_MODELS.find(
              (m) => m.id === data.model_id || m.role === data.role
            );
            if (found) {
              setSelectedModel(found.name);
            }
          }
        }
      })
      .catch(() => {
        fetch("http://localhost:4000/model-center")
          .then((res) => (res.ok ? res.json() : null))
          .then((data) => {
            if (data) {
              setModelCenter(data);
              if (data.model_id) {
                setSelectedModelId(data.model_id);
                const found = AVAILABLE_MODELS.find(
                  (m) => m.id === data.model_id || m.role === data.role
                );
                if (found) {
                  setSelectedModel(found.name);
                }
              }
            }
          })
          .catch(() => {});
      });

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
    fetchActiveScope();
    const interval = setInterval(() => {
      fetchTelemetry();
      fetchActiveScope();
    }, 6000);
    return () => clearInterval(interval);
  }, [fetchActiveScope]);

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
    let isMounted = true;
    let reconnectTimeout: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      if (!isMounted) return;
      setWsStatus("connecting");
      const wsUrl = `ws://localhost:4000/?sessionId=${sessionId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMounted) {
          if (ws.readyState === WebSocket.OPEN) {
            ws.close();
          }
          return;
        }
        setWsStatus("connected");
        setWsInstance(ws);
        try {
          ws.send(JSON.stringify({ type: "get_active_scope" }));
        } catch {
          // ignore
        }
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data);

          if (data.type === "handshake") {
            if (data.sessionId) setSessionId(data.sessionId);
          } else if (data.type === "status") {
            if (data.taskId) {
              setActiveTaskId(data.taskId);
              setRunningToolName(data.tool || "task");
            }
          } else if (data.type === "active_scope_contract" || data.type === "scope_contract_updated") {
            const contract = data.contract || data.scope_contract || data;
            if (contract && (contract.targets || contract.contract_id)) {
              setScopeInfo({
                target: (contract.targets && contract.targets[0]) || "127.0.0.1",
                cidrAllowed: contract.targets || ["127.0.0.1"],
                cidrExcluded: contract.metadata?.excluded_targets || ["192.168.1.1"],
                authorizationMode: "Unified Access (ADR-004)",
                status: contract.is_expired ? "Expired" : "Active",
                contractId: contract.contract_id,
                signatureValid: contract.signature_valid ?? true,
                secondsRemaining: contract.seconds_remaining,
              });
            }
          } else if (data.type === "model_switched") {
            const switchedId = data.model_id || data.model?.model_id;
            if (switchedId) {
              setSelectedModelId(switchedId);
              const found = AVAILABLE_MODELS.find(
                (m) => m.id === switchedId || m.role === data.model?.role
              );
              if (found) {
                setSelectedModel(found.name);
              }
            }
            fetchTelemetry();
          } else if (data.type === "agent_response") {
            setActiveTaskId(null);
            setRunningToolName(null);
            if (data.plan) {
              setLatestPlan(data.plan);
            }
            if (data.modelId) {
              const found = AVAILABLE_MODELS.find((m) => m.id === data.modelId);
              if (found) {
                setSelectedModelId(data.modelId);
                setSelectedModel(found.name);
              }
            }
            const msgId = createUniqueMsgId("resp", data.id || data.messageId);
            const responseMsg: ChatMessage = {
              id: msgId,
              eventId: data.eventId,
              sender: "agent",
              text: data.reply || "",
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
              tool: data.toolExecuted,
              execution: data.execution,
              durationMs: data.durationMs,
              toolSelection: data.toolSelection,
              recovery_narrative: data.execution?.recovery_narrative,
              recovery_path: data.execution?.recovery_path,
              synthesis: data.synthesis || data.execution?.synthesis,
              modelId: data.modelId,
              modelRole: data.modelRole,
              modelVerification: data.modelVerification,
              selectedModel: data.selectedModel,
              actualModelId: data.actualModelId || data.modelId,
              inferenceRuntime: data.inferenceRuntime,
              processedBySelectedModel: data.processedBySelectedModel,
              structuredOutput: data.structuredOutput,
              selectedTool: data.selectedTool,
              validatedArgs: data.validatedArgs,
              fallbackUsed: data.fallbackUsed,
              fallbackReason: data.fallbackReason,
              intent: data.intent,
              planOnly: data.planOnly,
              plan: data.plan,
              stepProvenance: data.stepProvenance,
              handledByCustomModel: data.handledByCustomModel,
              handledByFallback: data.handledByFallback,
              nextStepRecommendations: data.nextStepRecommendations || data.next_step_recommendations || (data.synthesis || {}).next_step_recommendations || [],
              next_step_recommendations: data.nextStepRecommendations || data.next_step_recommendations || (data.synthesis || {}).next_step_recommendations || [],
            };

            setMessages((prev) => {
              if (data.eventId && prev.some((m) => m.eventId === data.eventId)) {
                return prev.map((m) =>
                  m.eventId === data.eventId ? { ...m, ...responseMsg, id: m.id } : m
                );
              }
              return [...prev, responseMsg];
            });

            if (data.event) {
              setAllEvents((prev) => [data.event, ...prev]);
            }
          } else if (data.type === "scope_violation") {
            setActiveTaskId(null);
            setRunningToolName(null);
            const msgId = createUniqueMsgId("scope_err");
            setMessages((prev) => [
              ...prev,
              {
                id: msgId,
                sender: "agent",
                text: `Scope Violation Blocked: Tool "${data.tool || "tool"}" targeting ${data.target || "host"} is outside the authorized CIDR scope contract. ${data.reason || ""}`,
                timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
              },
            ]);
          } else if (
            data.type === "planner_plan_created" ||
            data.type === "planner_plan_updated" ||
            data.type === "planner_plan_details"
          ) {
            if (data.plan) {
              setLatestPlan(data.plan);
            }
          } else if (data.type === "error") {
            setActiveTaskId(null);
            setRunningToolName(null);
            const msgId = createUniqueMsgId("err");
            setMessages((prev) => [
              ...prev,
              {
                id: msgId,
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
        if (!isMounted) return;
        setWsStatus("disconnected");
        setWsInstance(null);
        reconnectTimeout = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        if (!isMounted) return;
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      };
    }

    connect();

    return () => {
      isMounted = false;
      clearTimeout(reconnectTimeout);
      setWsInstance(null);

      const socket = wsRef.current;
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;

        if (socket.readyState === WebSocket.OPEN) {
          socket.close();
        } else if (socket.readyState === WebSocket.CONNECTING) {
          socket.onopen = () => {
            try {
              socket.close();
            } catch {
              // Ignore any errors if closed during transition
            }
          };
        }
      }
      wsRef.current = null;
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
      id: createUniqueMsgId("user"),
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
        modelId: selectedModelId,
        autonomous: true,
        mode: "autonomous_task",
        target: scopeInfo.target,
        scopeContract: {
          contract_id: scopeInfo.contractId,
          target: scopeInfo.target,
          targets: scopeInfo.cidrAllowed,
        },
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
    const newId = `sess_${Date.now().toString(36)}_${Math.random().toString(36).substring(2, 6)}`;
    setSessionId(newId);
    setMessages([]);
    setActiveTaskId(null);
    setSessions((prev) => [
      { id: newId, title: "New Security Session", time: "Just now" },
      ...prev,
    ]);
    setIsMobileSidebarOpen(false);
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

        {/* Center: Claude Model Selector with Real Backend Status */}
        <div className="top-bar-center">
          <div className="model-picker-container">
            <button
              className="claude-model-pill"
              onClick={() => setShowModelMenu(!showModelMenu)}
              aria-label="Select Model"
            >
              <span className="model-pill-spark">✦</span>
              <span>{selectedModel}</span>
              {modelCenter?.real_backend_status && (
                <span
                  style={{
                    fontSize: "10px",
                    padding: "2px 6px",
                    borderRadius: "6px",
                    background: modelCenter.real_backend_status.is_primary_custom
                      ? "rgba(16, 185, 129, 0.2)"
                      : "rgba(245, 158, 11, 0.2)",
                    color: modelCenter.real_backend_status.is_primary_custom ? "#10b981" : "#f59e0b",
                    border: `1px solid ${
                      modelCenter.real_backend_status.is_primary_custom
                        ? "rgba(16, 185, 129, 0.4)"
                        : "rgba(245, 158, 11, 0.4)"
                    }`,
                    fontWeight: 600,
                  }}
                  title={`Real Backend Model: ${modelCenter.real_backend_status.active_model_id} (${modelCenter.real_backend_status.runtime})`}
                >
                  Backend: {modelCenter.real_backend_status.active_model_id} [{modelCenter.real_backend_status.runtime}]
                </span>
              )}
              <span className="model-pill-chevron">{showModelMenu ? "▲" : "▼"}</span>
            </button>
            {showModelMenu && (
              <div className="model-dropdown-menu">
                {AVAILABLE_MODELS.map((opt) => {
                  const isActive =
                    selectedModelId === opt.id ||
                    selectedModel === opt.name ||
                    selectedModel.toLowerCase().includes(opt.id.toLowerCase());
                  const isCustomPrimary = opt.id === "kairo-scale-2b";
                  const isLocalFallback = opt.id === "Qwen2.5-0.5B-Instruct";
                  return (
                    <button
                      key={opt.id}
                      className={`model-dropdown-item ${isActive ? "active" : ""}`}
                      onClick={() => handleSelectModel(opt.id, opt.name)}
                    >
                      <div className="model-item-title">
                        <span>{opt.shortName}</span>
                        {isCustomPrimary && (
                          <span style={{ fontSize: "10px", color: "#10b981", border: "1px solid rgba(16,185,129,0.3)", padding: "1px 5px", borderRadius: "4px" }}>
                            Primary Custom
                          </span>
                        )}
                        {isLocalFallback && (
                          <span style={{ fontSize: "10px", color: "#38bdf8", border: "1px solid rgba(56,189,248,0.3)", padding: "1px 5px", borderRadius: "4px" }}>
                            Local Fallback
                          </span>
                        )}
                        {opt.badge && !isCustomPrimary && !isLocalFallback && (
                          <span
                            className={opt.badgeClass || ""}
                            style={opt.badgeColor ? { fontSize: "10px", color: opt.badgeColor } : undefined}
                          >
                            {opt.badge}
                          </span>
                        )}
                      </div>
                      <span className="model-item-desc">{opt.desc}</span>
                    </button>
                  );
                })}
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
                  <span>Selected Model (UI)</span>
                  <strong>{selectedModel}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Real Backend Model</span>
                  <strong style={{ color: modelCenter?.real_backend_status?.is_primary_custom ? "#10b981" : "#f59e0b" }}>
                    {modelCenter?.real_backend_status?.active_model_id || modelCenter?.model_id || "kairo-scale-2b"}
                  </strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Inference Runtime</span>
                  <strong>{modelCenter?.real_backend_status?.runtime || modelCenter?.runtime || "transformers"}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Air-Gapped Privacy</span>
                  <strong style={{ color: "#10b981" }}>100% Local (Cloud Blocked)</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Primary Custom Status</span>
                  <strong>{modelCenter?.real_backend_status?.custom_primary_ready ? "Available (1.98B)" : "Unavailable"}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Local Fallback</span>
                  <strong>{modelCenter?.real_backend_status?.fallback_model_id || "Qwen2.5-0.5B-Instruct"}</strong>
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

          {/* Quick Split-View Toggles for Terminal and Kali GUI (VNC) */}
          <div className="top-bar-split-toggles" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <button
              className={`console-btn ${isAdvancedOpen && advancedTab === "terminal" ? "active" : ""}`}
              onClick={() => {
                if (isAdvancedOpen && advancedTab === "terminal") {
                  setIsAdvancedOpen(false);
                } else {
                  setAdvancedTab("terminal");
                  setIsAdvancedOpen(true);
                }
              }}
              aria-label="Toggle Terminal Split View"
              title="Toggle Terminal Shell (CLI)"
              style={isAdvancedOpen && advancedTab === "terminal" ? { borderColor: "#38bdf8", color: "#38bdf8", background: "rgba(56, 189, 248, 0.12)" } : undefined}
            >
              <span style={{ fontSize: "11px", fontFamily: "monospace", fontWeight: 700 }}>&gt;_</span>
              <span>Terminal</span>
            </button>

            <button
              className={`console-btn ${isAdvancedOpen && advancedTab === "screen" ? "active" : ""}`}
              onClick={() => {
                if (isAdvancedOpen && advancedTab === "screen") {
                  setIsAdvancedOpen(false);
                } else {
                  setAdvancedTab("screen");
                  setIsAdvancedOpen(true);
                }
              }}
              aria-label="Toggle Kali GUI VNC Split View"
              title="Toggle Kali GUI (VNC Desktop)"
              style={isAdvancedOpen && advancedTab === "screen" ? { borderColor: "#c084fc", color: "#c084fc", background: "rgba(192, 132, 252, 0.12)" } : undefined}
            >
              <span style={{ fontSize: "11px" }}>🖥️</span>
              <span>Kali GUI</span>
            </button>

            <button
              className={`console-btn ${isAdvancedOpen && advancedTab === "knowledge" ? "active" : ""}`}
              onClick={() => {
                if (isAdvancedOpen && advancedTab === "knowledge") {
                  setIsAdvancedOpen(false);
                } else {
                  setAdvancedTab("knowledge");
                  setIsAdvancedWide(true);
                  setIsAdvancedOpen(true);
                }
              }}
              aria-label="Toggle Tool Knowledge Center"
              title="Tool Knowledge Center (13-Section Deep Metadata & Examples)"
              style={isAdvancedOpen && advancedTab === "knowledge" ? { borderColor: "#58a6ff", color: "#58a6ff", background: "rgba(88, 166, 255, 0.12)" } : undefined}
            >
              <span style={{ fontSize: "11px" }}>📚</span>
              <span>Tools</span>
            </button>

            <button
              className={`console-btn ${isAdvancedOpen && advancedTab === "updates" ? "active" : ""}`}
              onClick={() => {
                if (isAdvancedOpen && advancedTab === "updates") {
                  setIsAdvancedOpen(false);
                } else {
                  setAdvancedTab("updates");
                  setIsAdvancedWide(true);
                  setIsAdvancedOpen(true);
                }
              }}
              aria-label="Toggle Kali & Tool Updates"
              title="Kali & Tool Updates (Snapshot Rollback Protected)"
              style={isAdvancedOpen && advancedTab === "updates" ? { borderColor: "#3fb950", color: "#3fb950", background: "rgba(63, 185, 80, 0.12)" } : undefined}
            >
              <span style={{ fontSize: "11px" }}>🔄</span>
              <span>Updates</span>
            </button>

            <button
              className={`console-btn ${isAdvancedOpen && advancedTab === "settings" ? "active" : ""}`}
              onClick={() => {
                if (isAdvancedOpen && advancedTab === "settings") {
                  setIsAdvancedOpen(false);
                } else {
                  setAdvancedTab("settings");
                  setIsAdvancedWide(true);
                  setIsAdvancedOpen(true);
                }
              }}
              aria-label="Toggle Advanced Menu Settings"
              title="Advanced Menu Settings (Autonomous Policies, Scope, VM Sandbox, Models)"
              style={isAdvancedOpen && advancedTab === "settings" ? { borderColor: "#38bdf8", color: "#38bdf8", background: "rgba(56, 189, 248, 0.12)" } : undefined}
            >
              <span style={{ fontSize: "11px" }}>⚙️</span>
              <span>Settings</span>
            </button>
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

          <div className="sidebar-section-label">Navigation</div>
          <div style={{ padding: "0 8px 10px 8px", display: "flex", flexDirection: "column", gap: "2px" }}>
            <button
              className={`session-item ${!isAdvancedOpen ? "active" : ""}`}
              onClick={() => {
                setIsAdvancedOpen(false);
                setIsMobileSidebarOpen(false);
              }}
              style={{ padding: "6px 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span>💬</span>
              <span className="session-title">Chat &amp; Workspace</span>
            </button>
            <button
              className={`session-item ${isAdvancedOpen && advancedTab === "knowledge" ? "active" : ""}`}
              onClick={() => {
                setAdvancedTab("knowledge");
                setIsAdvancedWide(true);
                setIsAdvancedOpen(true);
                setIsMobileSidebarOpen(false);
              }}
              style={{ padding: "6px 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span>📚</span>
              <span className="session-title">Tool Knowledge</span>
            </button>
            <button
              className={`session-item ${isAdvancedOpen && advancedTab === "updates" ? "active" : ""}`}
              onClick={() => {
                setAdvancedTab("updates");
                setIsAdvancedWide(true);
                setIsAdvancedOpen(true);
                setIsMobileSidebarOpen(false);
              }}
              style={{ padding: "6px 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span>🔄</span>
              <span className="session-title">Kali &amp; Updates</span>
            </button>
            <button
              className={`session-item ${isAdvancedOpen && advancedTab === "graph" ? "active" : ""}`}
              onClick={() => {
                setAdvancedTab("graph");
                setIsAdvancedOpen(true);
                setIsMobileSidebarOpen(false);
              }}
              style={{ padding: "6px 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span>📊</span>
              <span className="session-title">Workflows (DAG)</span>
            </button>
            <button
              className={`session-item ${isAdvancedOpen && advancedTab === "audit" ? "active" : ""}`}
              onClick={() => {
                setAdvancedTab("audit");
                setIsAdvancedOpen(true);
                setIsMobileSidebarOpen(false);
              }}
              style={{ padding: "6px 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span>🛡️</span>
              <span className="session-title">Audit History</span>
            </button>
            <button
              className={`session-item ${isAdvancedOpen && advancedTab === "settings" ? "active" : ""}`}
              onClick={() => {
                setAdvancedTab("settings");
                setIsAdvancedWide(true);
                setIsAdvancedOpen(true);
                setIsMobileSidebarOpen(false);
              }}
              style={{ padding: "6px 10px", borderRadius: "6px", display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span>⚙️</span>
              <span className="session-title">Advanced Settings</span>
            </button>
          </div>

          <div className="sidebar-section-label">Recent</div>
          <div className="session-list">
            {sessions.map((s, idx) => (
              <button
                key={`${s.id}-${idx}`}
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
              <span className="profile-tier">Airgap · Operator Authorized</span>
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
                messages.map((m, idx) => (
                  <div key={`${m.id || "msg"}-${idx}`} className={`turn-wrapper ${m.sender}`}>
                    {m.sender === "user" ? (
                      <div className="user-bubble">{m.text}</div>
                    ) : m.sender === "agent" ? (
                      <ClaudeOutputCard
                        messageId={m.id}
                        text={m.text}
                        timestamp={m.timestamp}
                        tool={m.tool}
                        execution={m.execution}
                        durationMs={m.durationMs}
                        toolSelection={(m.toolSelection as unknown) as ClaudeToolSelectionMeta}
                        synthesis={m.synthesis || m.execution?.synthesis}
                        scopeTarget={scopeInfo.target}
                        modelVerification={m.modelVerification}
                        selectedModel={m.selectedModel}
                        actualModelId={m.actualModelId || m.modelId}
                        inferenceRuntime={m.inferenceRuntime}
                        processedBySelectedModel={m.processedBySelectedModel}
                        structuredOutput={m.structuredOutput}
                        selectedTool={m.selectedTool}
                        validatedArgs={m.validatedArgs}
                        fallbackUsed={m.fallbackUsed}
                        fallbackReason={m.fallbackReason}
                        intent={m.intent}
                        planOnly={m.planOnly}
                        plan={m.plan}
                        stepProvenance={m.stepProvenance}
                        handledByCustomModel={m.handledByCustomModel}
                        handledByFallback={m.handledByFallback}
                        nextStepRecommendations={m.nextStepRecommendations || m.next_step_recommendations}
                        next_step_recommendations={m.next_step_recommendations || m.nextStepRecommendations}
                        onRunPrompt={(prompt) => {
                          setInputVal(prompt);
                          textareaRef.current?.focus();
                        }}
                        onOpenConsole={(toolId) => openToolInConsole(toolId)}
                        onOpenGraph={(plan) => {
                          setLatestPlan(plan);
                          setAdvancedTab("graph");
                          setIsAdvancedOpen(true);
                        }}
                      />
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
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span>Scope Contract</span>
                      {scopeInfo.contractId && (
                        <span style={{ fontSize: "10px", color: "var(--text-secondary)", fontFamily: "monospace" }}>
                          ({scopeInfo.contractId.slice(0, 10)})
                        </span>
                      )}
                    </div>
                    <button
                      className="ghost-btn"
                      style={{ padding: "0 4px" }}
                      onClick={() => setShowScopePopover(false)}
                    >
                      ✕
                    </button>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", margin: "4px 0" }}>
                    <strong style={{ color: "var(--text-primary)" }}>Status:</strong>
                    <span
                      style={{
                        fontSize: "11px",
                        padding: "1px 6px",
                        borderRadius: "4px",
                        background: scopeInfo.signatureValid !== false ? "rgba(16, 185, 129, 0.15)" : "rgba(239, 68, 68, 0.15)",
                        color: scopeInfo.signatureValid !== false ? "#10b981" : "#ef4444",
                        border: `1px solid ${scopeInfo.signatureValid !== false ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                        fontWeight: 600,
                      }}
                    >
                      {scopeInfo.signatureValid !== false ? "HMAC-SHA256 Valid" : "Signature Invalid"}
                    </span>
                    {scopeInfo.secondsRemaining !== undefined && scopeInfo.secondsRemaining > 0 && (
                      <span style={{ fontSize: "10px", color: "var(--text-secondary)" }}>
                        ({Math.round(scopeInfo.secondsRemaining / 60)}m left)
                      </span>
                    )}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Primary Target:</strong> {scopeInfo.target}
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
                    <strong style={{ color: "var(--text-primary)" }}>Tool Policy:</strong>{" "}
                    {scopeInfo.authorizationMode}
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
                {/* 1. Configuration */}
                <div className="drawer-nav-group-label">
                  <span>⚙️</span>
                  <span>Configuration</span>
                </div>
                <button
                  className={`drawer-nav-item ${advancedTab === "settings" ? "active" : ""}`}
                  onClick={() => {
                    setAdvancedTab("settings");
                    setIsAdvancedWide(true);
                  }}
                  title="Configure autonomous policies, scope boundaries, VM sandbox caps, and inference models"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🛠️</span>
                    <span>Settings</span>
                  </div>
                  <span className="drawer-nav-badge">Prefs</span>
                </button>

                {/* 2. Core */}
                <div className="drawer-nav-group-label" style={{ marginTop: "6px" }}>
                  <span>📊</span>
                  <span>Core</span>
                </div>
                <button
                  className={`drawer-nav-item ${advancedTab === "system" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("system")}
                  title="Hardware, inference engine, VM status, and session telemetry"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🖥️</span>
                    <span>System</span>
                  </div>
                  <span
                    className={`status-dot ${
                      modelCenter?.server_status === "running" ? "success" : "error"
                    }`}
                  />
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "events" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("events")}
                  title="SQLite operational audit trail and tool execution events"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">📜</span>
                    <span>Event Log</span>
                  </div>
                  <span className="drawer-nav-badge">{allEvents.length}</span>
                </button>

                {/* 3. Operations */}
                <div className="drawer-nav-group-label" style={{ marginTop: "6px" }}>
                  <span>⚡</span>
                  <span>Operations</span>
                </div>
                <button
                  className={`drawer-nav-item ${advancedTab === "terminal" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("terminal")}
                  title="Interactive Kali Linux terminal shell and process tree"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">&gt;_</span>
                    <span>Terminal</span>
                  </div>
                  <span className="drawer-nav-badge">CLI</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "screen" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("screen")}
                  title="Interactive Kali GUI desktop remote via noVNC (port 6080)"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🖵</span>
                    <span>Screen (VNC)</span>
                  </div>
                  <span className="drawer-nav-badge">GUI</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "graph" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("graph")}
                  title="Interactive task dependency DAG graph view"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🕸️</span>
                    <span>Task Graph</span>
                  </div>
                  <span className="drawer-nav-badge">DAG</span>
                </button>

                {/* 4. Tools & Maintenance */}
                <div className="drawer-nav-group-label" style={{ marginTop: "6px" }}>
                  <span>🧰</span>
                  <span>Tools &amp; Maintenance</span>
                </div>
                <button
                  className={`drawer-nav-item ${advancedTab === "knowledge" ? "active" : ""}`}
                  onClick={() => {
                    setAdvancedTab("knowledge");
                    setIsAdvancedWide(true);
                  }}
                  title="Deep 13-section tool documentation, capabilities, and arguments"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">📚</span>
                    <span>Tool Knowledge</span>
                  </div>
                  <span className="drawer-nav-badge">13-Sec</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "updates" ? "active" : ""}`}
                  onClick={() => {
                    setAdvancedTab("updates");
                    setIsAdvancedWide(true);
                  }}
                  title="Managed Kali tool updates with automated pre-update snapshots and rollback"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🔄</span>
                    <span>Kali Updates</span>
                  </div>
                  <span className="drawer-nav-badge">Sync</span>
                </button>

                {/* 5. Security & Models */}
                <div className="drawer-nav-group-label" style={{ marginTop: "6px" }}>
                  <span>🛡️</span>
                  <span>Security &amp; Models</span>
                </div>
                <button
                  className={`drawer-nav-item ${advancedTab === "audit" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("audit")}
                  title="Cryptographic evidence store, CVE findings, and remediation reports"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🔍</span>
                    <span>Audit</span>
                  </div>
                  <span className="drawer-nav-badge">SHA-256</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "benchmarks" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("benchmarks")}
                  title="Competitive benchmark leaderboard comparing local models against CTF targets"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🏆</span>
                    <span>Benchmarks</span>
                  </div>
                  <span className="drawer-nav-badge">Eval</span>
                </button>
                <button
                  className={`drawer-nav-item ${advancedTab === "evolution" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("evolution")}
                  title="Self-improving synthetic fine-tuning pipeline and candidate model gate"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">🧬</span>
                    <span>Model Evolution</span>
                  </div>
                  <span className="drawer-nav-badge">Gate</span>
                </button>

                {/* 6. Testing */}
                <div className="drawer-nav-group-label" style={{ marginTop: "6px" }}>
                  <span>🧪</span>
                  <span>Testing</span>
                </div>
                <button
                  className={`drawer-nav-item ${advancedTab === "devtools" ? "active" : ""}`}
                  onClick={() => setAdvancedTab("devtools")}
                  title="Developer debugging fixtures: sandbox execution, timeouts, and process SIGKILL"
                >
                  <div className="drawer-nav-item-left">
                    <span className="drawer-nav-icon">⚡</span>
                    <span>Dev Tools</span>
                  </div>
                  <span className="drawer-nav-badge" style={{ color: "#f59e0b" }}>Test</span>
                </button>
              </nav>

              {/* Right Content Pane */}
              <div className="drawer-content-pane">
                {advancedTab === "system" && (
                  <div className="sys-dashboard">
                    {/* Header */}
                    <div className="sys-header-bar">
                      <div className="sys-title-group">
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span style={{ fontSize: "16px" }}>📊</span>
                          <h3>Core System &amp; Telemetry Hub</h3>
                          <span className="adv-tag cyan">LIVE PULSE</span>
                        </div>
                        <p>Real-time orchestrator health, local model inference server, VirtualBox sandbox, and WebSocket metrics.</p>
                      </div>

                      <div className="drawer-quick-actions" style={{ marginBottom: 0 }}>
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
                    </div>

                    {/* Quick KPI Stat Cards */}
                    <div className="sys-quick-stats-grid">
                      <div className="sys-stat-card">
                        <div className="sys-stat-header">
                          <span className="sys-stat-label">Model Server</span>
                          <span className={`status-dot ${modelCenter?.server_status === "running" ? "success" : "error"}`} />
                        </div>
                        <span className="sys-stat-value">{modelCenter?.server_status === "running" ? "Online" : "Offline"}</span>
                        <span className="sys-stat-sub">{modelCenter?.runtime || "llama.cpp"}</span>
                      </div>

                      <div className="sys-stat-card">
                        <div className="sys-stat-header">
                          <span className="sys-stat-label">Kali Sandbox</span>
                          <span className={`status-dot ${vmStatus?.worker_online ? "success" : "warning"}`} />
                        </div>
                        <span className="sys-stat-value">{vmStatus?.worker_online ? "Active" : "Offline"}</span>
                        <span className="sys-stat-sub">{vmStatus?.vm_state || "poweroff"}</span>
                      </div>

                      <div className="sys-stat-card">
                        <div className="sys-stat-header">
                          <span className="sys-stat-label">Gateway WS</span>
                          <span className={`status-dot ${wsStatus === "connected" ? "success" : "error"}`} />
                        </div>
                        <span className="sys-stat-value">{wsStatus === "connected" ? "Connected" : "Disconnected"}</span>
                        <span className="sys-stat-sub">Port 4000</span>
                      </div>

                      <div className="sys-stat-card">
                        <div className="sys-stat-header">
                          <span className="sys-stat-label">Zero-Tier</span>
                          <span className="status-dot success" />
                        </div>
                        <span className="sys-stat-value" style={{ color: "#38bdf8" }}>ADR-004</span>
                        <span className="sys-stat-sub">Tiers Retired</span>
                      </div>
                    </div>

                    {/* Deep Panels */}
                    <div className="sys-sections-grid">
                      {/* Left: Model & Inference Engine */}
                      <div className="sys-panel-card">
                        <div className="sys-panel-header">
                          <span className="sys-panel-title">
                            <span>🧠</span>
                            <span>Inference Engine</span>
                          </span>
                          <span className="adv-tag green">Loaded</span>
                        </div>

                        <div className="sys-detail-list">
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Active Model ID</span>
                            <span className="sys-detail-val" title={modelCenter?.model_id}>{modelCenter?.model_id || "None loaded"}</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Runtime / Engine</span>
                            <span className="sys-detail-val">{modelCenter?.runtime || "llama.cpp server"}</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Quantization</span>
                            <span className="sys-detail-val">{modelCenter?.quantization || "Q4_K_M"}</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Context Window</span>
                            <span className="sys-detail-val">{modelCenter?.context_length || 4096} tokens</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">GPU VRAM Usage</span>
                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              {modelCenter?.vram && (
                                <div className="gauge-container" style={{ width: "90px" }}>
                                  <div className="gauge-track">
                                    <div
                                      className="gauge-fill"
                                      style={{ width: `${Math.min(modelCenter.vram.utilization_pct || 0, 100)}%` }}
                                    />
                                  </div>
                                </div>
                              )}
                              <span className="sys-detail-val">
                                {modelCenter?.vram
                                  ? `${modelCenter.vram.used_mb}MB / ${modelCenter.vram.total_mb}MB`
                                  : "Integrated / CPU"}
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Right: Environment & Virtualization */}
                      <div className="sys-panel-card">
                        <div className="sys-panel-header">
                          <span className="sys-panel-title">
                            <span>🖥️</span>
                            <span>Kali VM Sandbox</span>
                          </span>
                          <span className="adv-tag cyan">Isolated</span>
                        </div>

                        <div className="sys-detail-list">
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Worker VM State</span>
                            <span className="sys-detail-val">
                              <span className={`status-dot ${vmStatus?.worker_online ? "success" : "warning"}`} />
                              {vmStatus?.worker_online ? "Online & Ready" : "Offline"} ({vmStatus?.vm_state || "poweroff"})
                            </span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">VM Name</span>
                            <span className="sys-detail-val">{vmStatus?.name || "kali-linux-amd64"}</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Snapshots Count</span>
                            <span className="sys-detail-val">{vmStatus?.snapshots_count ?? 42} (Rollback Ready)</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">noVNC RFB Stream</span>
                            <span className="sys-detail-val">ws://127.0.0.1:6080</span>
                          </div>
                          <div className="sys-detail-item">
                            <span className="sys-detail-key">Orchestrator API</span>
                            <span className="sys-detail-val">http://127.0.0.1:8000</span>
                          </div>
                        </div>
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
                      <TaskGraphView ws={wsInstance} activeSessionId={sessionId} plan={latestPlan} />
                    </div>
                  </div>
                )}

                {advancedTab === "benchmarks" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <BenchmarkLeaderboard />
                    <DatasetCurationPanel />
                  </div>
                )}

                {advancedTab === "evolution" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <ModelEvolutionPanel apiBaseUrl="http://127.0.0.1:8000" />
                  </div>
                )}

                {advancedTab === "audit" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <AuditExplorer />
                  </div>
                )}

                {advancedTab === "knowledge" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <ToolKnowledgeCenter
                      onUseInChat={handleUsePromptInChat}
                      apiBaseUrl="http://127.0.0.1:8000"
                    />
                  </div>
                )}

                {advancedTab === "updates" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <UpdatesPanel apiBaseUrl="http://127.0.0.1:8000" />
                  </div>
                )}

                {advancedTab === "settings" && (
                  <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                    <AdvancedSettingsPanel
                      apiBaseUrl="http://127.0.0.1:8000"
                      sessionId={sessionId}
                      activeModelId={selectedModelId}
                      onModelChange={handleSelectModel}
                      onScopeUpdated={fetchActiveScope}
                      onClose={() => setIsAdvancedOpen(false)}
                    />
                  </div>
                )}

                {advancedTab === "devtools" && (
                  <div className="dev-tools-container">
                    {/* Header */}
                    <div className="dev-header-card">
                      <div>
                        <h3 className="dev-header-title">
                          <span>🧪</span>
                          <span>Testing &amp; Developer Debugging Fixtures</span>
                        </h3>
                        <p className="dev-header-desc">
                          Fixtures to evaluate sandbox isolation boundaries, simulated process timeouts, elevated execution, and fault-tolerant SIGKILL mechanisms.
                        </p>
                      </div>
                      <span className="adv-tag red">SANDBOX ISOLATED</span>
                    </div>

                    {/* Interactive Sandbox Command Runner */}
                    <div className="dev-group-card">
                      <div className="dev-group-card-header">
                        <span className="dev-group-title">⚡ Interactive Kali Command Runner</span>
                        <span style={{ fontSize: "10px", color: "var(--accent-cyan)", fontFamily: "var(--font-mono)" }}>
                          kali.exec.v1 Gateway
                        </span>
                      </div>
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
                          placeholder="Command to exec (e.g. whoami, id, uname -a, ip a)..."
                          value={devCustomCmd}
                          onChange={(e) => setDevCustomCmd(e.target.value)}
                        />
                        <button
                          type="submit"
                          className="action-pill-btn"
                          style={{ padding: "6px 14px", color: "#38bdf8", borderColor: "rgba(56, 189, 248, 0.4)", background: "rgba(56, 189, 248, 0.1)" }}
                        >
                          ▶ Run in VM
                        </button>
                      </form>
                    </div>

                    {/* Preset Worker Checks */}
                    <div className="dev-group-card">
                      <div className="dev-group-card-header">
                        <span className="dev-group-title">🔍 Sandbox &amp; Host Validation Presets</span>
                        <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>1-Click Diagnostics</span>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                        <button
                          className="dev-action-btn"
                          onClick={() =>
                            triggerDevAction("tool_call", {
                              tool: "kali.exec.v1",
                              args: { command: "uname", args: ["-a"] },
                            })
                          }
                        >
                          <span>▶ <strong>kali.exec.v1</strong>: <code>uname -a</code> (Verify Linux Kernel &amp; Architecture)</span>
                        </button>

                        <button
                          className="dev-action-btn"
                          onClick={() =>
                            triggerDevAction("tool_call", {
                              tool: "kali.exec.v1",
                              args: { command: "which", args: ["nmap", "sqlmap", "nikto", "msfconsole"] },
                            })
                          }
                        >
                          <span>▶ <strong>kali.exec.v1</strong>: <code>which nmap sqlmap nikto msfconsole</code> (Verify Installed Security Tools)</span>
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
                          <span>▶ <strong>shell.run.v1</strong>: <code>date</code> (Verify Host Clock &amp; Drift)</span>
                        </button>
                      </div>
                    </div>

                    {/* Fault Tolerance and Kill Switch */}
                    <div className="dev-group-card">
                      <div className="dev-group-card-header">
                        <span className="dev-group-title">🛡️ Fault Tolerance &amp; Supervisor Recovery</span>
                        <span style={{ fontSize: "10px", color: "#f87171" }}>Safety Controls</span>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
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
                          <span>⏱️ <strong>Trigger Simulated Timeout</strong> (Execute 5s task with 800ms limit test)</span>
                        </button>

                        <button
                          className="dev-action-btn danger"
                          onClick={() => {
                            if (activeTaskId && wsRef.current) {
                              wsRef.current.send(JSON.stringify({ type: "kill", taskId: activeTaskId }));
                            }
                          }}
                        >
                          <span>☠️ <strong>Emergency SIGKILL Active Task</strong> (Send SIGKILL to active child PID and cleanup)</span>
                        </button>
                      </div>
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
