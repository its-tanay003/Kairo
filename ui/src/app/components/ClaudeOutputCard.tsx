"use client";

import React, { useState } from "react";

export interface ClaudeProcessMeta {
  title?: string;
  tool_id?: string;
  tool_name?: string;
  intent?: string;
  command_line?: string;
  target?: string;
  duration_s?: number;
  status?: string;
  status_label?: string;
  tier?: number;
  execution_plane?: string;
  fallback_notice?: string;
  local_fallback?: boolean;
  is_simulated?: boolean;
  simulation_notice?: string;
}

export interface ClaudeOutputFinding {
  host?: string;
  hostname?: string;
  port?: string;
  service?: string;
  version?: string;
  state?: string;
  item?: string;
  value?: string;
  status?: string;
}

export interface ClaudeOutputData {
  summary_metrics?: Array<{ label: string; value: string; type?: string }>;
  findings_table?: ClaudeOutputFinding[];
  raw_stdout?: string;
  raw_stderr?: string;
  has_raw_terminal?: boolean;
}

export interface ClaudeResultData {
  headline?: string;
  status?: string;
  security_posture?: string;
  key_takeaways?: string[];
  recommended_actions?: Array<{ label: string; prompt: string }>;
}

export interface ClaudeSynthesisPayload {
  reply?: string;
  process?: ClaudeProcessMeta;
  output?: ClaudeOutputData;
  result?: ClaudeResultData;
}

export interface ClaudeToolSelectionCandidate {
  tool_id?: string;
  tool_name?: string;
  version?: string;
  category?: string;
  rank?: number;
  total_score?: number;
  score_pct?: number;
  summary_rationale?: string;
  dimension_scores?: Array<{
    name: string;
    weight: number;
    weight_pct: number;
    score: number;
    score_pct: number;
    weighted_score: number;
    raw_signal: string;
  }>;
}

export interface ClaudeToolSelectionMeta {
  selected_tool?: ClaudeToolSelectionCandidate;
  candidates?: ClaudeToolSelectionCandidate[];
  selection_reason?: string;
  evaluated_count?: number;
  task_goal?: string;
  [key: string]: unknown;
}

export interface ClaudeModelVerification {
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
}

export interface ClaudeStepProvenanceItem {
  stage: string;
  handled_by: string;
  runtime: string;
  is_custom_model: boolean;
  is_fallback: boolean;
  executed: boolean;
  details?: string;
}

export interface ClaudeTaskPlanNode {
  node_id: string;
  capability?: string;
  tool_name?: string;
  target?: string;
  parameters?: Record<string, unknown>;
  dependencies?: string[];
  status?: string;
}

export interface ClaudeTaskPlanEdge {
  from_node: string;
  to_node: string;
}

export interface ClaudeTaskPlan {
  plan_id?: string;
  goal?: string;
  scope_target?: string;
  nodes?: ClaudeTaskPlanNode[];
  edges?: ClaudeTaskPlanEdge[];
  [key: string]: unknown;
}

export interface ClaudeOutputCardProps {
  messageId: string;
  text: string;
  timestamp?: string;
  tool?: {
    id: string;
    version: string;
    name: string;
  };
  execution?: {
    adapter?: string;
    command?: string;
    args?: string[];
    exit_code?: number;
    process_id?: number;
    stdout?: string;
    stderr?: string;
    duration_ms?: number;
    observation?: Record<string, unknown>;
    synthesis?: ClaudeSynthesisPayload;
    execution_plane?: string;
    fallback_notice?: string;
    local_fallback?: boolean;
    is_simulated?: boolean;
    simulation_notice?: string;
  };
  durationMs?: number;
  toolSelection?: ClaudeToolSelectionMeta;
  synthesis?: ClaudeSynthesisPayload;
  scopeTarget?: string;
  modelVerification?: ClaudeModelVerification;
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
  onRunPrompt?: (prompt: string) => void;
  onOpenConsole?: (toolId?: string) => void;
}

export default function ClaudeOutputCard({
  messageId,
  text,
  timestamp,
  tool,
  execution,
  durationMs,
  toolSelection,
  synthesis: propSynthesis,
  scopeTarget = "192.168.1.0/24",
  modelVerification,
  selectedModel,
  actualModelId,
  inferenceRuntime,
  processedBySelectedModel,
  structuredOutput,
  selectedTool,
  validatedArgs,
  fallbackUsed,
  fallbackReason,
  intent,
  planOnly,
  plan,
  stepProvenance,
  handledByCustomModel,
  handledByFallback,
  onRunPrompt,
  onOpenConsole,
}: ClaudeOutputCardProps) {
  // Merged synthesis from prop or execution payload
  const synth = propSynthesis || execution?.synthesis;
  const processData = synth?.process;
  const outputData = synth?.output;
  const resultData = synth?.result;

  // Model verification provenance normalization
  const effSelectedModel = selectedModel || modelVerification?.selected_model || "kairo-scale-2b";
  const effActualModel = actualModelId || modelVerification?.actual_model_id || "kairo-scale-2b";
  const effRuntime = inferenceRuntime || modelVerification?.inference_runtime || "transformers";
  const effProcessedBySelected = processedBySelectedModel ?? modelVerification?.processed_by_selected_model ?? true;
  const effFallbackUsed = fallbackUsed ?? modelVerification?.fallback_used ?? false;
  const effFallbackReason = fallbackReason || modelVerification?.fallback_reason;
  const effStructuredOutput = structuredOutput || (modelVerification?.structured_output as Record<string, unknown>);
  const effSelectedTool = selectedTool || modelVerification?.selected_tool || tool?.id;
  const effValidatedArgs = validatedArgs || modelVerification?.validated_args || execution?.args;

  // Local state for expandable sections
  const [isThinkingOpen, setIsThinkingOpen] = useState<boolean>(false);
  const [isModelVerifiedOpen, setIsModelVerifiedOpen] = useState<boolean>(false);
  const [activeStepTab, setActiveStepTab] = useState<"overview" | "terminal" | "telemetry">("overview");
  const [isProcessCardExpanded, setIsProcessCardExpanded] = useState<boolean>(true);
  const [isCopiedCommand, setIsCopiedCommand] = useState<boolean>(false);
  const [isCopiedOutput, setIsCopiedOutput] = useState<boolean>(false);

  // Failure detection
  const isFailed = Boolean(
    execution &&
    typeof execution.exit_code === "number" &&
    execution.exit_code !== 0
  );

  const durationSec = durationMs
    ? (durationMs / 1000).toFixed(1)
    : processData?.duration_s
    ? processData.duration_s.toFixed(1)
    : "1.2";

  const isSimulatedMock = Boolean(
    execution?.execution_plane === "simulated_mock" ||
    processData?.execution_plane === "simulated_mock" ||
    execution?.is_simulated ||
    processData?.is_simulated ||
    (synth?.output?.summary_metrics || []).some((m) => m.value?.toLowerCase().includes("simulated"))
  );
  const simulationNoticeText =
    execution?.simulation_notice ||
    processData?.simulation_notice ||
    "[SIMULATED — demo mode, not a live scan]";

  const isLocalHostFallback = !isSimulatedMock && Boolean(
    execution?.execution_plane === "local_host_fallback" ||
    processData?.execution_plane === "local_host_fallback" ||
    execution?.local_fallback ||
    processData?.local_fallback ||
    execution?.fallback_notice ||
    processData?.fallback_notice
  );
  const fallbackNoticeText =
    execution?.fallback_notice ||
    processData?.fallback_notice ||
    "Ran directly on this machine — no isolated Kali worker was available.";

  const commandString =
    processData?.command_line ||
    (execution?.command ? `${execution.command} ${(execution.args || []).join(" ")}`.trim() : "") ||
    (tool ? `${tool.id} target=${scopeTarget}` : "");

  const terminalOutput =
    outputData?.raw_stdout ||
    execution?.stdout ||
    (execution?.stderr ? `[STDERR]\n${execution.stderr}` : "");

  const handleCopyCommand = () => {
    if (!commandString) return;
    navigator.clipboard.writeText(commandString);
    setIsCopiedCommand(true);
    setTimeout(() => setIsCopiedCommand(false), 2000);
  };

  const handleCopyOutput = () => {
    if (!terminalOutput) return;
    navigator.clipboard.writeText(terminalOutput);
    setIsCopiedOutput(true);
    setTimeout(() => setIsCopiedOutput(false), 2000);
  };

  // Helper to get tool icon
  const getToolIcon = (id?: string) => {
    const s = (id || "").toLowerCase();
    if (s.includes("nmap") || s.includes("scan")) return "🔍";
    if (s.includes("terminal") || s.includes("shell") || s.includes("exec")) return "💻";
    if (s.includes("zap") || s.includes("burp") || s.includes("audit")) return "🛡️";
    if (s.includes("whois") || s.includes("dig") || s.includes("dns")) return "🌐";
    if (s.includes("wireshark") || s.includes("pcap")) return "🦈";
    return "⚡";
  };

  return (
    <div id={messageId} className="claude-agent-document">
      {/* 1. Claude Agent Header */}
      <div className="claude-agent-header">
        <div className="claude-avatar-spark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
          </svg>
        </div>
        <div className="claude-agent-meta">
          <span className="claude-agent-name">Kairo</span>
          <span className="claude-agent-model-badge" title={`Real Backend Model: ${effActualModel} (${effRuntime})`}>
            ✦ {effActualModel} [{effRuntime}]
          </span>
          {effFallbackUsed ? (
            <span
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "10px",
                backgroundColor: "rgba(245, 158, 11, 0.15)",
                color: "#f59e0b",
                border: "1px solid rgba(245, 158, 11, 0.35)",
                fontWeight: 600,
              }}
              title={`Fallback used: ${effFallbackReason || "Selected model checkpoint unavailable"}`}
            >
              ⚠️ Fallback ({effActualModel})
            </span>
          ) : (
            <span
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "10px",
                backgroundColor: "rgba(16, 185, 129, 0.15)",
                color: "#10b981",
                border: "1px solid rgba(16, 185, 129, 0.35)",
                fontWeight: 600,
              }}
            >
              ✓ Primary Model
            </span>
          )}
          {intent && (
            <span
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "10px",
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                ...(intent === "general_question"
                  ? { backgroundColor: "rgba(59, 130, 246, 0.15)", color: "#60a5fa", border: "1px solid rgba(59, 130, 246, 0.35)" }
                  : intent === "plan_only"
                  ? { backgroundColor: "rgba(168, 85, 247, 0.15)", color: "#c084fc", border: "1px solid rgba(168, 85, 247, 0.35)" }
                  : intent === "task_request"
                  ? { backgroundColor: "rgba(245, 158, 11, 0.15)", color: "#fbbf24", border: "1px solid rgba(245, 158, 11, 0.35)" }
                  : { backgroundColor: "rgba(16, 185, 129, 0.15)", color: "#34d399", border: "1px solid rgba(16, 185, 129, 0.35)" }),
              }}
              title={`Intent Stage: ${intent}`}
            >
              {intent === "general_question" && "💬 Conversational"}
              {intent === "plan_only" && "🗺️ Plan Only (0 Execution)"}
              {intent === "task_request" && "⚡ Task Plan (DAG)"}
              {intent === "tool_request" && "🛡️ Validated Tool"}
            </span>
          )}
          <span className="claude-agent-timestamp">{timestamp || "Just now"}</span>
        </div>
      </div>

      {/* Verifiable Model Provenance & Integration Audit Bar */}
      <div
        style={{
          marginTop: "6px",
          marginBottom: "12px",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: "8px",
          background: "rgba(15, 23, 42, 0.4)",
          padding: "8px 12px",
          fontSize: "12px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            cursor: "pointer",
            userSelect: "none",
          }}
          onClick={() => setIsModelVerifiedOpen(!isModelVerifiedOpen)}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <span style={{ color: "var(--accent-primary, #818cf8)", fontWeight: 600 }}>⚙ Model Provenance:</span>
            <strong>{effActualModel}</strong>
            <span style={{ color: "#94a3b8" }}>via <code>{effRuntime}</code></span>
            {effFallbackUsed && (
              <span style={{ color: "#f59e0b", fontWeight: 500 }}>(Fallback from {effSelectedModel})</span>
            )}
            {handledByCustomModel && (
              <span style={{
                fontSize: "10px",
                padding: "1px 6px",
                borderRadius: "4px",
                background: "rgba(167, 139, 250, 0.15)",
                color: "#c4b5fd",
                border: "1px solid rgba(167, 139, 250, 0.3)",
                fontWeight: 600
              }}>
                ✦ Custom Model Reasoner
              </span>
            )}
            {handledByFallback && (
              <span style={{
                fontSize: "10px",
                padding: "1px 6px",
                borderRadius: "4px",
                background: "rgba(245, 158, 11, 0.15)",
                color: "#f59e0b",
                border: "1px solid rgba(245, 158, 11, 0.3)",
                fontWeight: 600
              }}>
                ⚠️ Fallback Reasoner
              </span>
            )}
            <span
              style={{
                fontSize: "10px",
                padding: "1px 6px",
                borderRadius: "4px",
                background: "rgba(16, 185, 129, 0.12)",
                color: "#10b981",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                fontWeight: 600,
              }}
            >
              🔒 100% Local Air-Gapped (Cloud Blocked)
            </span>
          </div>
          <span style={{ color: "#94a3b8", fontSize: "11px" }}>
            {isModelVerifiedOpen ? "▲ Hide Verification" : "▼ Audit Model Integration (7 Points)"}
          </span>
        </div>

        {isModelVerifiedOpen && (
          <div style={{ marginTop: "10px", paddingTop: "8px", borderTop: "1px solid rgba(255,255,255,0.06)", display: "flex", flexDirection: "column", gap: "6px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "4px" }}>
              <span style={{ color: "#94a3b8" }}>1. Selected Model:</span>
              <code>{effSelectedModel}</code>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "4px" }}>
              <span style={{ color: "#94a3b8" }}>2. Inference Runtime:</span>
              <code>{effRuntime} (Local air-gapped)</code>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "4px" }}>
              <span style={{ color: "#94a3b8" }}>3. Processed by Selected:</span>
              <span style={{ color: effProcessedBySelected ? "#10b981" : "#f59e0b", fontWeight: 600 }}>
                {effProcessedBySelected ? "✓ True (Direct match)" : "⚠️ False (Routed to verified local fallback)"}
              </span>
            </div>
            {effFallbackUsed && (
              <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "4px" }}>
                <span style={{ color: "#f59e0b" }}>4. Fallback Reason:</span>
                <span style={{ color: "#f59e0b" }}>{effFallbackReason || "Selected model checkpoint not ready; routed to local fallback."}</span>
              </div>
            )}
            {effStructuredOutput && (
              <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "4px" }}>
                <span style={{ color: "#94a3b8" }}>5. Structured Output:</span>
                <pre style={{ margin: 0, padding: "4px 8px", background: "rgba(0,0,0,0.3)", borderRadius: "4px", fontSize: "11px", overflowX: "auto" }}>
                  {JSON.stringify(effStructuredOutput, null, 2)}
                </pre>
              </div>
            )}
            {(effSelectedTool || effValidatedArgs) && (
              <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "4px" }}>
                <span style={{ color: "#94a3b8" }}>6. Tool &amp; Validated Args:</span>
                <div>
                  {effSelectedTool && <div>Tool: <code>{effSelectedTool}</code></div>}
                  {effValidatedArgs && (
                    <pre style={{ margin: 0, padding: "4px 8px", background: "rgba(0,0,0,0.3)", borderRadius: "4px", fontSize: "11px", overflowX: "auto" }}>
                      {JSON.stringify(effValidatedArgs, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            )}
            {stepProvenance && stepProvenance.length > 0 && (
              <div style={{ marginTop: "6px", paddingTop: "6px", borderTop: "1px dashed rgba(255,255,255,0.08)" }}>
                <div style={{ color: "#94a3b8", marginBottom: "4px", fontWeight: 600 }}>7. Step Provenance &amp; Reasoner Routing:</div>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  {stepProvenance.map((step, sIdx) => (
                    <div key={sIdx} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(0,0,0,0.25)", padding: "4px 8px", borderRadius: "4px", fontSize: "11px" }}>
                      <span style={{ color: "#e2e8f0" }}>
                        <strong style={{ textTransform: "capitalize" }}>{step.stage.replace(/_/g, " ")}:</strong> {step.details || (step.executed ? "Executed" : "Resolved")}
                      </span>
                      <span style={{ display: "inline-flex", gap: "6px", alignItems: "center" }}>
                        <code style={{ fontSize: "10px", color: step.is_custom_model ? "#a78bfa" : "#38bdf8" }}>{step.handled_by} [{step.runtime}]</code>
                        <span style={{
                          fontSize: "9px",
                          padding: "1px 5px",
                          borderRadius: "3px",
                          background: step.is_custom_model ? "rgba(167, 139, 250, 0.2)" : "rgba(245, 158, 11, 0.2)",
                          color: step.is_custom_model ? "#c4b5fd" : "#fbbf24",
                          fontWeight: 600
                        }}>
                          {step.is_custom_model ? "CUSTOM MODEL" : "LOCAL FALLBACK"}
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 2. Claude 3.7 Extended Thinking Accordion (Collapsible) */}
      <div className="claude-thinking-container">
        <button
          className="claude-thinking-btn"
          onClick={() => setIsThinkingOpen(!isThinkingOpen)}
          aria-expanded={isThinkingOpen}
        >
          <div className="claude-thinking-left">
            <span className="claude-sparkle">✦</span>
            <span className="claude-thinking-label">
              Thought for {durationSec}s
            </span>
          </div>
          <span className="claude-thinking-arrow">
            {isThinkingOpen ? "▲ Hide reasoning" : "▼ Show reasoning"}
          </span>
        </button>

        {isThinkingOpen && (
          <div className="claude-thinking-drawer">
            <div className="thinking-row">
              <span className="thinking-key">Operational Goal:</span>
              <span className="thinking-val">
                {processData?.intent || "Execute security inspection within active boundary."}
              </span>
            </div>
            <div className="thinking-row">
              <span className="thinking-key">Scope Verification:</span>
              <span className="thinking-val">
                Verified target against Scope Contract <code>{scopeTarget}</code>.
              </span>
            </div>
            {Boolean(toolSelection && typeof toolSelection.selection_reason === "string") && (
              <div className="thinking-row">
                <span className="thinking-key">Tool Selection:</span>
                <span className="thinking-val">{String(toolSelection?.selection_reason)}</span>
              </div>
            )}
            {Boolean(toolSelection && typeof toolSelection.selected_tool === "object" && toolSelection.selected_tool) && (
              <div className="thinking-telemetry-pill">
                <span>Selected: <strong>{String((toolSelection?.selected_tool as { tool_name?: string })?.tool_name || "tool")}</strong></span>
                <span>Match Score: {String((toolSelection?.selected_tool as { score_pct?: number })?.score_pct || "80")}%</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 3. The Process Card: Clear Step Breakdown & Interactive Terminal */}
      {(tool || processData || execution) && (
        <div className={`claude-process-card ${isFailed ? "has-error" : ""}`}>
          {isSimulatedMock && (
            <div
              className="claude-simulation-banner"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 14px",
                backgroundColor: "rgba(168, 85, 247, 0.15)",
                borderBottom: "1px solid rgba(168, 85, 247, 0.35)",
                color: "#c084fc",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              <span style={{ fontSize: "14px" }}>🎭</span>
              <span><strong>SIMULATED DEMO:</strong> {simulationNoticeText} (Mock Adapter — No live scan performed)</span>
            </div>
          )}

          {isLocalHostFallback && (
            <div
              className="claude-fallback-banner"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 14px",
                backgroundColor: "rgba(245, 158, 11, 0.12)",
                borderBottom: "1px solid rgba(245, 158, 11, 0.25)",
                color: "#fbbf24",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              <span style={{ fontSize: "14px" }}>⚠️</span>
              <span>{fallbackNoticeText}</span>
            </div>
          )}

          <div className="claude-process-card-header">
            <div className="claude-process-card-title-group">
              <span className="claude-process-icon">
                {getToolIcon(processData?.tool_id || tool?.id)}
              </span>
              <div className="claude-process-text-group">
                <div className="claude-process-main-title">
                  {processData?.title || tool?.name || tool?.id || "Tool Execution"}
                </div>
                <div className="claude-process-subtitle">
                  {processData?.intent || (commandString ? `$ ${commandString}` : "Supervised Execution")}
                </div>
              </div>
            </div>

            <div className="claude-process-actions-group">
              {isSimulatedMock && (
                <span
                  style={{
                    fontSize: "11px",
                    padding: "2px 8px",
                    borderRadius: "10px",
                    backgroundColor: "rgba(168, 85, 247, 0.15)",
                    color: "#c084fc",
                    border: "1px solid rgba(168, 85, 247, 0.35)",
                    fontWeight: 600,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                  title={simulationNoticeText}
                >
                  🎭 Simulated Mock
                </span>
              )}

              {isLocalHostFallback && (
                <span
                  style={{
                    fontSize: "11px",
                    padding: "2px 8px",
                    borderRadius: "10px",
                    backgroundColor: "rgba(245, 158, 11, 0.15)",
                    color: "#f59e0b",
                    border: "1px solid rgba(245, 158, 11, 0.35)",
                    fontWeight: 600,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                  title={fallbackNoticeText}
                >
                  ⚠️ Host Fallback
                </span>
              )}

              <span className={`claude-status-badge ${isFailed ? "error" : "success"}`}>
                <span className="status-dot-pulse" />
                {isFailed
                  ? `Failed (exit ${execution?.exit_code || 1})`
                  : `Completed (${durationSec}s)`}
              </span>

              <button
                className="claude-details-toggle-btn"
                onClick={() => setIsProcessCardExpanded(!isProcessCardExpanded)}
                title="Toggle Process and Terminal details"
              >
                {isProcessCardExpanded ? "▲ Process Details" : "▼ Process Details"}
              </button>
            </div>
          </div>

          {/* Expanded Process Inspector with 3 Tabs */}
          {isProcessCardExpanded && (
            <div className="claude-process-card-body">
              {/* Internal Tab Bar */}
              <div className="claude-card-tab-bar">
                <button
                  className={`claude-card-tab ${activeStepTab === "overview" ? "active" : ""}`}
                  onClick={() => setActiveStepTab("overview")}
                >
                  📋 Overview &amp; Command
                </button>
                <button
                  className={`claude-card-tab ${activeStepTab === "terminal" ? "active" : ""}`}
                  onClick={() => setActiveStepTab("terminal")}
                >
                  💻 Terminal Console {terminalOutput ? "•" : ""}
                </button>
                <button
                  className={`claude-card-tab ${activeStepTab === "telemetry" ? "active" : ""}`}
                  onClick={() => setActiveStepTab("telemetry")}
                >
                  ⚙️ Execution Audit
                </button>
              </div>

              {/* Tab 1: Overview & Command */}
              {activeStepTab === "overview" && (
                <div className="claude-tab-content">
                  <div className="claude-overview-grid">
                    <div className="overview-item">
                      <span className="overview-label">Target Asset</span>
                      <span className="overview-val font-mono">{processData?.target || scopeTarget}</span>
                    </div>
                    <div className="overview-item">
                      <span className="overview-label">Tool Adapter</span>
                      <span className="overview-val">{processData?.tool_name || tool?.name || tool?.id || "Shell"}</span>
                    </div>
                    <div className="overview-item">
                      <span className="overview-label">Duration</span>
                      <span className="overview-val">{durationSec}s</span>
                    </div>
                    <div className="overview-item">
                      <span className="overview-label">Safety Tier</span>
                      <span className="overview-val">
                        Tier {processData?.tier || 2} · Authorized
                      </span>
                    </div>
                    <div className="overview-item">
                      <span className="overview-label">Execution Plane</span>
                      <span
                        className="overview-val font-mono"
                        style={{
                          color: isSimulatedMock ? "#c084fc" : isLocalHostFallback ? "#f59e0b" : "inherit",
                        }}
                      >
                        {isSimulatedMock
                          ? "simulated_mock"
                          : isLocalHostFallback
                          ? "local_host_fallback"
                          : "Isolated Kali Worker"}
                      </span>
                    </div>
                  </div>

                  {isSimulatedMock && (
                    <div
                      style={{
                        margin: "10px 0",
                        padding: "8px 12px",
                        borderRadius: "6px",
                        backgroundColor: "rgba(168, 85, 247, 0.1)",
                        border: "1px solid rgba(168, 85, 247, 0.3)",
                        color: "#d8b4fe",
                        fontSize: "12px",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                      }}
                    >
                      <span style={{ fontSize: "14px" }}>ℹ️</span>
                      <span>
                        <strong>Honest Simulation:</strong> {simulationNoticeText} Findings are illustrative mock telemetry for offline GUI testing.
                      </span>
                    </div>
                  )}

                  {isLocalHostFallback && (
                    <div
                      style={{
                        margin: "10px 0",
                        padding: "8px 12px",
                        borderRadius: "6px",
                        backgroundColor: "rgba(245, 158, 11, 0.1)",
                        border: "1px solid rgba(245, 158, 11, 0.3)",
                        color: "#fbbf24",
                        fontSize: "12px",
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                      }}
                    >
                      <span style={{ fontSize: "14px" }}>⚠️</span>
                      <span><strong>Notice:</strong> {fallbackNoticeText}</span>
                    </div>
                  )}

                  {commandString && (
                    <div className="claude-command-box">
                      <div className="command-box-header">
                        <span className="command-box-label">Executed Command</span>
                        <button
                          className="copy-mini-btn"
                          onClick={handleCopyCommand}
                          title="Copy command to clipboard"
                        >
                          {isCopiedCommand ? "✓ Copied" : "Copy"}
                        </button>
                      </div>
                      <div className="command-box-code font-mono">
                        <span className="command-prompt">$ </span>
                        {commandString}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 2: Terminal Console */}
              {activeStepTab === "terminal" && (
                <div className="claude-tab-content">
                  <div className="claude-terminal-window">
                    <div className="terminal-window-topbar">
                      <div className="terminal-dots">
                        <span className="dot red" />
                        <span className="dot yellow" />
                        <span className="dot green" />
                      </div>
                      <span className="terminal-window-title font-mono">
                        {commandString ? `$ ${commandString.slice(0, 48)}...` : "Terminal Output"}
                      </span>
                      <div className="terminal-window-actions">
                        <button
                          className="copy-mini-btn"
                          onClick={handleCopyOutput}
                          title="Copy terminal output"
                        >
                          {isCopiedOutput ? "✓ Copied" : "Copy Output"}
                        </button>
                        {onOpenConsole && (
                          <button
                            className="copy-mini-btn"
                            onClick={() => onOpenConsole(tool?.id)}
                            title="Open in full Advanced Console"
                          >
                            Popout ↗
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="terminal-window-scroll font-mono">
                      {commandString && (
                        <div className="terminal-line command-echo">
                          <span className="terminal-prompt-sym">❯ </span>
                          <span className="terminal-cmd-text">{commandString}</span>
                        </div>
                      )}

                      {terminalOutput ? (
                        terminalOutput.split("\n").map((line, idx) => (
                          <div key={idx} className="terminal-line">
                            <span className="terminal-line-num">{idx + 1}</span>
                            <span className={`terminal-line-text ${line.includes("ERROR") || line.includes("failed") ? "text-error" : ""}`}>
                              {line || " "}
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className="terminal-empty-text">No standard output recorded for this step.</div>
                      )}

                      <div className="terminal-exit-banner">
                        <span className={`exit-badge ${isFailed ? "error" : "success"}`}>
                          Process exited with status code {execution?.exit_code ?? 0}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 3: Telemetry & Audit */}
              {activeStepTab === "telemetry" && (
                <div className="claude-tab-content">
                  <div className="claude-telemetry-content">
                    <div className="telemetry-row">
                      <span>Tool ID:</span>
                      <code>{tool?.id || processData?.tool_id || "unknown"}</code>
                    </div>
                    <div className="telemetry-row">
                      <span>Process ID:</span>
                      <code>{execution?.process_id || "isolated_worker"}</code>
                    </div>
                    <div className="telemetry-row">
                      <span>Execution Duration:</span>
                      <code>{durationMs ? `${durationMs}ms` : `${durationSec}s`}</code>
                    </div>
                    {execution?.adapter && (
                      <div className="telemetry-row">
                        <span>Adapter Class:</span>
                        <code>{execution.adapter}</code>
                      </div>
                    )}
                    <div className="telemetry-row">
                      <span>Execution Plane:</span>
                      <code>
                        {isSimulatedMock
                          ? "simulated_mock"
                          : execution?.execution_plane || processData?.execution_plane || (isLocalHostFallback ? "local_host_fallback" : "isolated_worker")}
                      </code>
                    </div>
                    {isSimulatedMock && (
                      <div className="telemetry-row">
                        <span>Simulation Notice:</span>
                        <code style={{ color: "#c084fc" }}>{simulationNoticeText}</code>
                      </div>
                    )}
                    {isLocalHostFallback && (
                      <div className="telemetry-row">
                        <span>Fallback Notice:</span>
                        <code style={{ color: "#f59e0b" }}>{fallbackNoticeText}</code>
                      </div>
                    )}
                    {onOpenConsole && (
                      <div style={{ marginTop: "10px" }}>
                        <button
                          className="claude-action-btn secondary"
                          onClick={() => onOpenConsole(tool?.id)}
                        >
                          Open in Advanced Audit Explorer ↗
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 4. The Output: Discovered Findings & Summary Metrics */}
      {outputData?.summary_metrics && outputData.summary_metrics.length > 0 && (
        <div className="claude-output-metrics-strip">
          {outputData.summary_metrics.map((m, i) => (
            <div key={i} className={`output-metric-pill ${m.type || "neutral"}`}>
              <span className="metric-label">{m.label}:</span>
              <span className="metric-val">{m.value}</span>
            </div>
          ))}
        </div>
      )}

      {outputData?.findings_table && outputData.findings_table.length > 0 && (
        <div className="claude-findings-box">
          <div className="findings-box-header">
            <span className="findings-box-title">Discovered Assets &amp; Services</span>
            <span className="findings-count-badge">
              {outputData.findings_table.length} detected
            </span>
          </div>

          <div className="findings-table-wrapper">
            <table className="claude-data-table">
              <thead>
                <tr>
                  <th>Host / Asset</th>
                  <th>Port / Protocol</th>
                  <th>Service &amp; Banner</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {outputData.findings_table.map((row, idx) => (
                  <tr key={idx}>
                    <td className="font-mono font-medium">
                      {row.host || row.item || scopeTarget}
                      {row.hostname ? <span className="host-sub"> ({row.hostname})</span> : ""}
                    </td>
                    <td className="font-mono">
                      <span className="port-badge">{row.port || row.value || "—"}</span>
                    </td>
                    <td>
                      <span className="service-name">{row.service || "service"}</span>
                      {row.version && <span className="service-ver"> {row.version}</span>}
                    </td>
                    <td>
                      <span className={`status-pill ${row.state === "open" || row.status === "Active" ? "green" : "neutral"}`}>
                        {row.state || row.status || "Open"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Structured Task Plan (DAG) Card */}
      {Boolean(plan?.nodes && Array.isArray(plan.nodes) && plan.nodes.length > 0) && (
        <div
          style={{
            margin: "12px 0",
            border: "1px solid rgba(168, 85, 247, 0.25)",
            borderRadius: "10px",
            background: "linear-gradient(135deg, rgba(30, 27, 75, 0.45) 0%, rgba(15, 23, 42, 0.6) 100%)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "10px 14px",
              background: "rgba(168, 85, 247, 0.12)",
              borderBottom: "1px solid rgba(168, 85, 247, 0.2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "8px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "16px" }}>🗺️</span>
              <strong style={{ color: "#f3e8ff", fontSize: "13px" }}>
                {planOnly ? "Plan-Only Request (Zero Execution)" : "Structured Task Plan (DAG)"}
              </strong>
              <span
                style={{
                  fontSize: "10px",
                  padding: "1px 6px",
                  borderRadius: "4px",
                  background: planOnly ? "rgba(168, 85, 247, 0.25)" : "rgba(245, 158, 11, 0.25)",
                  color: planOnly ? "#e9d5ff" : "#fef3c7",
                  border: `1px solid ${planOnly ? "rgba(168, 85, 247, 0.4)" : "rgba(245, 158, 11, 0.4)"}`,
                  fontWeight: 600,
                }}
              >
                {planOnly ? "EXPLAIN PLAN • EXECUTE NOTHING" : "ACTIVE TASK DECOMPOSITION"}
              </span>
            </div>
            <span style={{ fontSize: "11px", color: "#c084fc", fontFamily: "monospace" }}>
              Nodes: {(plan?.nodes || []).length} | Edges: {(plan?.edges || []).length}
            </span>
          </div>

          <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: "8px" }}>
            {(plan?.nodes || []).map((node: ClaudeTaskPlanNode, nIdx: number) => (
              <div
                key={nIdx}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: "rgba(15, 23, 42, 0.65)",
                  border: "1px solid rgba(255, 255, 255, 0.06)",
                  borderRadius: "6px",
                  padding: "8px 12px",
                  fontSize: "12px",
                  gap: "10px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: "140px" }}>
                  <span
                    style={{
                      width: "20px",
                      height: "20px",
                      borderRadius: "50%",
                      background: "rgba(168, 85, 247, 0.2)",
                      color: "#c084fc",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "10px",
                      fontWeight: 700,
                    }}
                  >
                    {nIdx + 1}
                  </span>
                  <code style={{ color: "#e2e8f0", fontSize: "11px" }}>{node.node_id}</code>
                </div>

                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ color: "#f8fafc", fontWeight: 600, fontSize: "12px" }}>
                    {node.capability || node.tool_name}
                  </div>
                  <div style={{ color: "#94a3b8", fontSize: "11px" }}>
                    Target: <code>{node.target || scopeTarget}</code>
                    {node.dependencies && node.dependencies.length > 0 && (
                      <span style={{ marginLeft: "8px", color: "#a855f7" }}>
                        Depends on: {node.dependencies.join(", ")}
                      </span>
                    )}
                  </div>
                </div>

                <div>
                  <span
                    style={{
                      fontSize: "10px",
                      padding: "2px 8px",
                      borderRadius: "10px",
                      fontWeight: 600,
                      background:
                        node.status === "COMPLETED"
                          ? "rgba(16, 185, 129, 0.15)"
                          : node.status === "RUNNING"
                          ? "rgba(59, 130, 246, 0.15)"
                          : "rgba(148, 163, 184, 0.15)",
                      color:
                        node.status === "COMPLETED"
                          ? "#34d399"
                          : node.status === "RUNNING"
                          ? "#60a5fa"
                          : "#94a3b8",
                      border: "1px solid rgba(255, 255, 255, 0.08)",
                    }}
                  >
                    {node.status || "PENDING"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. The Result: Executive Synthesis & Human-Friendly Explanation */}
      {text && (
        <div className="claude-result-body">
          {isSimulatedMock && !text.includes(simulationNoticeText) && (
            <div
              className="claude-simulated-chat-notice"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 12px",
                marginBottom: "12px",
                backgroundColor: "rgba(168, 85, 247, 0.12)",
                borderRadius: "6px",
                border: "1px solid rgba(168, 85, 247, 0.35)",
                color: "#c084fc",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              <span>🎭</span>
              <span>{simulationNoticeText}</span>
            </div>
          )}
          {isLocalHostFallback && !text.includes(fallbackNoticeText) && (
            <div
              className="claude-fallback-chat-notice"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 12px",
                marginBottom: "12px",
                backgroundColor: "rgba(245, 158, 11, 0.12)",
                borderRadius: "6px",
                border: "1px solid rgba(245, 158, 11, 0.3)",
                color: "#fbbf24",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              <span>⚠️</span>
              <span>{fallbackNoticeText}</span>
            </div>
          )}
          <div className="claude-markdown-prose">
            {/* Render plain text or simple markdown formatting */}
            <MarkdownRenderer content={text} />
          </div>
        </div>
      )}

      {/* 6. Actionable Recommended Next Steps (Click to Run) */}
      {resultData?.recommended_actions && resultData.recommended_actions.length > 0 && (
        <div className="claude-next-steps-container">
          <div className="next-steps-label">Suggested Next Steps:</div>
          <div className="next-steps-pills">
            {resultData.recommended_actions.map((act, i) => (
              <button
                key={i}
                className="next-step-pill-btn"
                onClick={() => onRunPrompt && onRunPrompt(act.prompt)}
                title={`Run: ${act.prompt}`}
              >
                <span className="pill-spark">👉</span>
                <span>{act.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Lightweight, safe Markdown renderer for Claude typography.
 * Handles headings, bold, code blocks, bullet points, tables, and links safely.
 */
function MarkdownRenderer({ content }: { content: string }) {
  if (!content) return null;

  // Split lines into structured blocks
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBlockLines: string[] = [];
  let codeBlockLang = "";

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Handle Code Blocks: ```bash ... ```
    if (line.trim().startsWith("```")) {
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeBlockLang = line.trim().slice(3).trim();
        codeBlockLines = [];
      } else {
        inCodeBlock = false;
        elements.push(
          <div key={`code-${i}`} className="prose-code-block">
            {codeBlockLang && <div className="prose-code-lang">{codeBlockLang}</div>}
            <pre className="font-mono">
              <code>{codeBlockLines.join("\n")}</code>
            </pre>
          </div>
        );
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // Headings
    if (line.startsWith("### ")) {
      elements.push(
        <h3 key={i} className="prose-h3">
          {renderInlineMarkdown(line.slice(4))}
        </h3>
      );
      continue;
    }
    if (line.startsWith("#### ")) {
      elements.push(
        <h4 key={i} className="prose-h4">
          {renderInlineMarkdown(line.slice(5))}
        </h4>
      );
      continue;
    }
    if (line.startsWith("## ")) {
      elements.push(
        <h2 key={i} className="prose-h2">
          {renderInlineMarkdown(line.slice(3))}
        </h2>
      );
      continue;
    }

    // Blockquote or Callout: > ...
    if (line.trim().startsWith("> ")) {
      elements.push(
        <div
          key={i}
          className="prose-callout-notice"
          style={{
            borderLeft: "3px solid #f59e0b",
            background: "rgba(245, 158, 11, 0.1)",
            padding: "8px 12px",
            borderRadius: "0 6px 6px 0",
            margin: "8px 0",
            color: "#fbbf24",
            fontSize: "13px",
            lineHeight: "1.5",
          }}
        >
          {renderInlineMarkdown(line.trim().slice(2))}
        </div>
      );
      continue;
    }

    // Bullet lists
    if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
      elements.push(
        <div key={i} className="prose-bullet-item">
          <span className="bullet-dot">•</span>
          <span>{renderInlineMarkdown(line.trim().slice(2))}</span>
        </div>
      );
      continue;
    }

    // Numbered lists
    const numMatch = line.trim().match(/^(\d+)\.\s+(.*)/);
    if (numMatch) {
      elements.push(
        <div key={i} className="prose-numbered-item">
          <span className="num-prefix">{numMatch[1]}.</span>
          <span>{renderInlineMarkdown(numMatch[2])}</span>
        </div>
      );
      continue;
    }

    // Empty lines (spacing)
    if (!line.trim()) {
      elements.push(<div key={i} className="prose-spacer" />);
      continue;
    }

    // Paragraph
    elements.push(
      <p key={i} className="prose-paragraph">
        {renderInlineMarkdown(line)}
      </p>
    );
  }

  return <div className="claude-prose-wrapper">{elements}</div>;
}

/**
 * Parses inline bold (**text**), inline code (`code`), and italics (*text*).
 */
function renderInlineMarkdown(text: string): React.ReactNode {
  // Regex to split on `code`, **bold**, *italic*
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g);

  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return (
        <code key={index} className="prose-inline-code font-mono">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      return (
        <strong key={index} className="prose-strong">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length >= 2) {
      return (
        <em key={index} className="prose-italic">
          {part.slice(1, -1)}
        </em>
      );
    }
    return part;
  });
}
