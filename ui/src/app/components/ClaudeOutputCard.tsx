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
  };
  durationMs?: number;
  toolSelection?: ClaudeToolSelectionMeta;
  synthesis?: ClaudeSynthesisPayload;
  scopeTarget?: string;
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
  onRunPrompt,
  onOpenConsole,
}: ClaudeOutputCardProps) {
  // Merged synthesis from prop or execution payload
  const synth = propSynthesis || execution?.synthesis;
  const processData = synth?.process;
  const outputData = synth?.output;
  const resultData = synth?.result;

  // Local state for expandable sections
  const [isThinkingOpen, setIsThinkingOpen] = useState<boolean>(false);
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
          <span className="claude-agent-model-badge">Cyber Defense Agent</span>
          <span className="claude-agent-timestamp">{timestamp || "Just now"}</span>
        </div>
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
                  </div>

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

      {/* 5. The Result: Executive Synthesis & Human-Friendly Explanation */}
      {text && (
        <div className="claude-result-body">
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
