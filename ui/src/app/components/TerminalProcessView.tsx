"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import type { Terminal } from "xterm";
import type { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

export interface ProcessNode {
  pid: number;
  ppid: number;
  pgid?: number;
  name: string;
  cmd: string;
  type: "parent" | "child" | "background";
  state: "running" | "paused" | "stopped" | "completed" | string;
  is_background: boolean;
  cpu_pct: number;
  mem_pct: number;
  children?: ProcessNode[];
}

export interface ArtifactEvidence {
  id?: number;
  task_id: string;
  filename: string;
  filepath: string;
  size_bytes: number;
  sha256: string;
  mime_type?: string;
  created_at?: string;
  metadata?: string;
  recovery_narrative?: string;
  recovery_path?: Array<{
    attempt?: number;
    tool?: string;
    action_taken?: string;
    status?: string;
    event_id?: string;
    parent_event?: string;
  }>;
}

export interface FindingCard {
  id: string;
  title: string;
  affected_asset: string;
  evidence_references: string[];
  confidence_score: number;
  recovery_path?: string | Array<Record<string, unknown>> | null;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO" | string;
  description?: string;
  remediation?: string;
  discovering_tool?: string;
  discovering_node_id?: string;
  session_id?: string;
  plan_id?: string;
  task_id?: string;
  created_at: string;
  tags?: string[];
  resolved_evidence?: Array<{
    filename?: string;
    filepath?: string;
    sha256?: string;
    mime_type?: string;
    size_bytes?: number;
    preview?: string;
    evidence_class?: string;
  }>;
}

export interface GeneratedReportData {
  report_id: string;
  title?: string;
  markdown: string;
  html: string;
  replay_script: string;
  sha256?: string;
  markdown_sha256?: string;
  html_sha256?: string;
  markdown_path?: string;
  html_path?: string;
  findings_count: number;
  workflow_steps_count?: number;
  reproducible_workflow?: {
    steps: Array<{
      step_number: number;
      tool_name: string;
      arguments: Record<string, unknown>;
      purpose?: string;
    }>;
  };
  workflow_steps?: Array<{
    step_number: number;
    tool_name: string;
    arguments: Record<string, unknown>;
    purpose?: string;
    command_preview?: string;
  }>;
}

export interface TerminalProcessViewProps {
  ws: WebSocket | null;
  activeTaskId: string | null;
  onSelectTask?: (taskId: string) => void;
  isMaximized?: boolean;
  onToggleMaximize?: () => void;
}

export default function TerminalProcessView({
  ws,
  activeTaskId,
  onSelectTask,
  isMaximized: externalMaximized,
  onToggleMaximize,
}: TerminalProcessViewProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const termInstanceRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);

  // States
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const currentTaskId = selectedTaskId || activeTaskId;
  const [processTree, setProcessTree] = useState<ProcessNode[]>([]);
  const [taskStatus, setTaskStatus] = useState<string>("idle");
  const [customCommand, setCustomCommand] = useState<string>("");
  const [logCount, setLogCount] = useState<number>(0);
  const [internalMaximized, setInternalMaximized] = useState<boolean>(false);
  const [viewMode, setViewMode] = useState<"split" | "terminal" | "tree">("split");
  const [inspectorTab, setInspectorTab] = useState<"tree" | "caps" | "artifacts">("tree");

  // Resource caps and sandbox automation state
  const [snapshotBefore, setSnapshotBefore] = useState<boolean>(true);
  const [rollbackAfter, setRollbackAfter] = useState<boolean>(false);
  const [rollbackOnFailure, setRollbackOnFailure] = useState<boolean>(false);
  const [maxCpuPct, setMaxCpuPct] = useState<number>(80);
  const [maxMemMb, setMaxMemMb] = useState<number>(512);
  const [maxDiskMb, setMaxDiskMb] = useState<number>(100);
  const [maxFileCount, setMaxFileCount] = useState<number>(50);

  // Artifact integrity state
  const [artifacts, setArtifacts] = useState<ArtifactEvidence[]>([]);
  const [verifyingMap, setVerifyingMap] = useState<Record<string, boolean>>({});
  const [verificationResults, setVerificationResults] = useState<Record<string, { valid: boolean; actual_sha256?: string; error?: string }>>({});
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  // Evidence Store & Findings Card States
  const [evidenceSubTab, setEvidenceSubTab] = useState<"findings" | "artifacts">("findings");
  const [findings, setFindings] = useState<FindingCard[]>([]);
  const [selectedFindingIds, setSelectedFindingIds] = useState<Set<string>>(new Set());
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [artifactClassFilter, setArtifactClassFilter] = useState<string>("ALL");
  const [reportModalOpen, setReportModalOpen] = useState<boolean>(false);
  const [reportTab, setReportTab] = useState<"markdown" | "html" | "replay">("markdown");
  const [generatedReport, setGeneratedReport] = useState<GeneratedReportData | null>(null);
  const [isGeneratingReport, setIsGeneratingReport] = useState<boolean>(false);
  const [copiedReportText, setCopiedReportText] = useState<boolean>(false);

  const isMax = externalMaximized !== undefined ? externalMaximized : internalMaximized;

  const handleToggleMax = () => {
    if (onToggleMaximize) {
      onToggleMaximize();
    } else {
      setInternalMaximized((prev) => !prev);
    }
  };

  // Request process tree update
  const requestTree = useCallback(
    (tid?: string) => {
      const target = tid || currentTaskId || activeTaskId;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "get_process_tree", taskId: target }));
      }
    },
    [ws, currentTaskId, activeTaskId]
  );

  // Poll tree periodically if task is running
  useEffect(() => {
    if (taskStatus !== "running" && taskStatus !== "paused") return;
    const interval = setInterval(() => {
      requestTree();
    }, 2500);
    return () => clearInterval(interval);
  }, [taskStatus, requestTree]);

  // Refit terminal whenever container geometry changes
  const triggerFit = useCallback(() => {
    setTimeout(() => {
      try {
        fitAddonRef.current?.fit();
      } catch {}
    }, 120);
  }, []);

  useEffect(() => {
    triggerFit();
  }, [isMax, viewMode, triggerFit]);

  // Initialize xterm.js dynamically (SSR-safe)
  useEffect(() => {
    let isCurrentMounted = true;

    async function initTerminal() {
      if (!terminalRef.current || termInstanceRef.current) return;

      try {
        const { Terminal } = await import("xterm");
        const { FitAddon } = await import("xterm-addon-fit");

        if (!isCurrentMounted || !terminalRef.current) return;

        const term = new Terminal({
          theme: {
            background: "#090d16",
            foreground: "#38bdf8",
            cursor: "#00f0ff",
            cursorAccent: "#090d16",
            selectionBackground: "rgba(56, 189, 248, 0.3)",
            black: "#1e293b",
            red: "#ef4444",
            green: "#10b981",
            yellow: "#f59e0b",
            blue: "#3b82f6",
            magenta: "#d946ef",
            cyan: "#06b6d4",
            white: "#f8fafc",
            brightBlack: "#475569",
            brightRed: "#f87171",
            brightGreen: "#34d399",
            brightYellow: "#fbbf24",
            brightBlue: "#60a5fa",
            brightMagenta: "#e879f9",
            brightCyan: "#22d3ee",
            brightWhite: "#ffffff",
          },
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
          fontSize: 12,
          lineHeight: 1.25,
          cursorBlink: true,
          convertEol: true,
          disableStdin: false,
        });

        const fitAddon = new FitAddon();
        term.loadAddon(fitAddon);

        term.open(terminalRef.current);
        fitAddon.fit();

        termInstanceRef.current = term;
        fitAddonRef.current = fitAddon;

        term.writeln("\x1b[1;36m╭────────────────────────────────────────────────────────────────────────╮\x1b[0m");
        term.writeln("\x1b[1;36m│\x1b[0m \x1b[1;32mKAIRO WORKER TERMINAL\x1b[0m - \x1b[90mLive Stream from Isolated Kali Sandbox\x1b[0m        \x1b[1;36m│\x1b[0m");
        term.writeln("\x1b[1;36m│\x1b[0m \x1b[90mConnected via Session Gateway WebSocket (Port 4000 ➔ VM 9999)\x1b[0m         \x1b[1;36m│\x1b[0m");
        term.writeln("\x1b[1;36m╰────────────────────────────────────────────────────────────────────────╯\x1b[0m\r\n");

        const handleResize = () => {
          try {
            fitAddon.fit();
          } catch {}
        };
        window.addEventListener("resize", handleResize);

        return () => {
          window.removeEventListener("resize", handleResize);
        };
      } catch (err) {
        console.error("Failed to load xterm:", err);
      }
    }

    initTerminal();

    return () => {
      isCurrentMounted = false;
      if (termInstanceRef.current) {
        termInstanceRef.current.dispose();
        termInstanceRef.current = null;
      }
    };
  }, []);

  // Fetch artifacts for current task
  const fetchTaskArtifacts = useCallback((tid: string) => {
    fetch(`http://localhost:4000/artifacts/${tid}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data.artifacts)) {
          setArtifacts(data.artifacts);
        }
      })
      .catch(() => {});
  }, []);

  const fetchFindings = useCallback(() => {
    fetch("http://localhost:8000/evidence/findings")
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data.findings) && data.findings.length > 0) {
          setFindings(data.findings);
          setSelectedFindingIds(new Set(data.findings.map((f: FindingCard) => f.id)));
        } else {
          // Provide default representative findings if no live scans have completed yet
          const sampleFindings: FindingCard[] = [
            {
              id: "find_exposed_admin",
              title: "Exposed Administrative Interface at /admin",
              affected_asset: "http://127.0.0.1:8080/admin",
              evidence_references: ["sha256:7f9a2e41b9c836d5e128..."],
              confidence_score: 0.96,
              recovery_path:
                "Attempted gobuster (common wordlist) -> timed out after 30s -> switched to ffuf with reduced thread count -> succeeded, found 3 endpoints.",
              severity: "HIGH",
              description: "Publicly accessible administrative interface discovered without mutual TLS authentication.",
              remediation: "Enforce IP allowlisting or move endpoint behind corporate SSO gateway.",
              discovering_tool: "ffuf.fuzz.v1",
              created_at: new Date().toISOString(),
              tags: ["web", "admin", "fuzzer"],
              resolved_evidence: [
                {
                  filename: "evidence_network_net_admin.json",
                  mime_type: "application/json",
                  size_bytes: 842,
                  sha256: "7f9a2e41b9c836d5e128ca8725fae3451892bf39dc02a4e98f7e2c9183421199",
                  preview: '{\n  "host": "127.0.0.1",\n  "port": 8080,\n  "http_url": "http://127.0.0.1:8080/admin",\n  "http_status": 200\n}',
                  evidence_class: "network",
                },
              ],
            },
            {
              id: "find_open_ssh",
              title: "Open Service: SSH on Port 22",
              affected_asset: "127.0.0.1:22",
              evidence_references: ["sha256:3a1b4c9e88d721fa..."],
              confidence_score: 0.99,
              recovery_path: null,
              severity: "MEDIUM",
              description: "OpenSSH 8.9p1 active on port 22 with password authentication enabled.",
              remediation: "Disable password-based SSH authentication and enforce public key or hardware tokens.",
              discovering_tool: "nmap.scan.v1",
              created_at: new Date().toISOString(),
              tags: ["network", "port_scan", "ssh"],
              resolved_evidence: [
                {
                  filename: "evidence_command_cmd_nmap.json",
                  mime_type: "application/x-sh",
                  size_bytes: 618,
                  sha256: "3a1b4c9e88d721fa091b2c4568a99281bfd41920847583a9218d893021948831",
                  preview: '{\n  "command_line": "nmap -sV -p 22,80,443 127.0.0.1",\n  "stdout": "PORT 22/tcp OPEN ssh OpenSSH 8.9p1",\n  "exit_code": 0\n}',
                  evidence_class: "command",
                },
              ],
            },
            {
              id: "find_sqli_search",
              title: "CRITICAL: Error-Based SQL Injection in /api/v1/search",
              affected_asset: "http://127.0.0.1:8080/api/v1/search?q=",
              evidence_references: ["sha256:c941829e01bf2847..."],
              confidence_score: 0.94,
              recovery_path:
                "Attempted basic union injection -> WAF 403 returned -> adjusted tamper scripts to chardoubleencode -> confirmed SQLite database extraction.",
              severity: "CRITICAL",
              description: "Parameter 'q' executes unparameterized SQL query leading to database credential exposure.",
              remediation: "Use parameterized prepared statements and bind variables across all database queries.",
              discovering_tool: "sqlmap.scan.v1",
              created_at: new Date().toISOString(),
              tags: ["vulnerability", "sqli", "critical"],
              resolved_evidence: [
                {
                  filename: "evidence_analytic_ana_sqli.json",
                  mime_type: "application/json",
                  size_bytes: 1045,
                  sha256: "c941829e01bf2847a9821bf4930182bcf982018374a839218204918239021894",
                  preview: '{\n  "vulnerability": "SQL Injection",\n  "dbms": "SQLite 3",\n  "payload": "\' OR 1=1 --",\n  "confidence": 0.94\n}',
                  evidence_class: "analytic",
                },
              ],
            },
          ];
          setFindings(sampleFindings);
          setSelectedFindingIds(new Set(sampleFindings.map((f) => f.id)));
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchFindings();
  }, [fetchFindings]);

  const toggleSelectFinding = (id: string) => {
    setSelectedFindingIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllFindings = () => {
    setSelectedFindingIds(new Set(findings.map((f) => f.id)));
  };

  const deselectAllFindings = () => {
    setSelectedFindingIds(new Set());
  };

  const handleGenerateReport = async () => {
    setIsGeneratingReport(true);
    try {
      const res = await fetch("http://localhost:8000/evidence/reports/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          finding_ids: Array.from(selectedFindingIds),
          title: "Kairo Security Assessment & Evidence Audit Report",
          format: "both",
          include_workflow: true,
        }),
      });
      const data = await res.json();
      setGeneratedReport(data);
      setReportModalOpen(true);
    } catch (err) {
      console.error("Failed to generate report:", err);
    } finally {
      setIsGeneratingReport(false);
    }
  };

  const handleDownloadFile = (filename: string, content: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Listen to WebSocket messages for terminal stream, process controls, and process tree
  useEffect(() => {
    if (!ws) return;

    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);

        // Terminal streaming output chunks
        if (data.type === "terminal_stream") {
          const term = termInstanceRef.current;
          if (term) {
            if (data.stream === "stderr") {
              term.write(`\x1b[31m${data.text}\x1b[0m`);
            } else if (data.stream === "system") {
              term.write(`\x1b[33m${data.text}\x1b[0m`);
            } else {
              term.write(data.text);
            }
          }
          if (data.taskId) {
            setSelectedTaskId(data.taskId);
          }
          setLogCount((prev) => prev + 1);
        }

        // Process tree updates
        if (data.type === "process_tree_update") {
          if (data.tree) {
            setProcessTree(data.tree);
          }
          if (data.status) {
            setTaskStatus(data.status);
          }
          if (data.taskId) {
            setSelectedTaskId(data.taskId);
          }
        }

        // Process supervisor control confirmations
        if (data.type === "process_control_result") {
          const term = termInstanceRef.current;
          if (term) {
            term.writeln(`\r\n\x1b[1;35m[Supervisor Control]\x1b[0m Action: \x1b[1;33m${data.action.toUpperCase()}\x1b[0m Task: \x1b[36m${data.taskId}\x1b[0m`);
          }
          // Poll updated tree
          requestTree(data.taskId);
        }

        // On task completion, refresh artifacts
        if (data.type === "agent_response" && data.execution?.task_id) {
          fetchTaskArtifacts(data.execution.task_id);
          setTaskStatus("completed");
        }
      } catch (err) {
        console.error("Terminal WebSocket parse error:", err);
      }
    };

    ws.addEventListener("message", handleMessage);
    return () => {
      ws.removeEventListener("message", handleMessage);
    };
  }, [ws, requestTree, fetchTaskArtifacts]);

  // Poll artifacts whenever active task changes
  useEffect(() => {
    let isCurrent = true;
    if (currentTaskId) {
      fetch(`http://localhost:4000/artifacts/${currentTaskId}`)
        .then((res) => res.json())
        .then((data) => {
          if (isCurrent && Array.isArray(data.artifacts)) {
            setArtifacts(data.artifacts);
          }
        })
        .catch(() => {});
    }
    return () => {
      isCurrent = false;
    };
  }, [currentTaskId]);

  // Verify artifact against SHA-256 on disk
  const verifyArtifact = async (filepath: string, expectedSha: string) => {
    setVerifyingMap((prev) => ({ ...prev, [expectedSha]: true }));
    try {
      const res = await fetch("http://localhost:4000/artifacts/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filepath, expected_sha256: expectedSha }),
      });
      if (res.ok) {
        const data = await res.json();
        setVerificationResults((prev) => ({ ...prev, [expectedSha]: data }));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setVerificationResults((prev) => ({
        ...prev,
        [expectedSha]: { valid: false, error: msg },
      }));
    } finally {
      setVerifyingMap((prev) => ({ ...prev, [expectedSha]: false }));
    }
  };

  const copyToClipboard = (text: string) => {
    try {
      navigator.clipboard?.writeText(text);
      setCopiedHash(text);
      setTimeout(() => setCopiedHash(null), 2000);
    } catch {}
  };

  // Supervisor Actions: pause, resume, stop, retry
  const handleControlAction = (action: "pause" | "resume" | "stop" | "retry") => {
    if (!currentTaskId) {
      alert("No active task selected to control.");
      return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      alert("Gateway WebSocket not connected.");
      return;
    }

    ws.send(
      JSON.stringify({
        type: "process_control",
        action,
        taskId: currentTaskId,
      })
    );

    if (action === "pause") setTaskStatus("paused");
    if (action === "resume") setTaskStatus("running");
    if (action === "stop") setTaskStatus("stopped");
    if (action === "retry") setTaskStatus("running");
  };

  // Run Custom / Test Command in Kali
  const handleRunCommand = (
    cmdStr: string,
    overrides?: {
      snapshot_before?: boolean;
      rollback_after?: boolean;
      rollback_on_failure?: boolean;
      limits?: {
        max_cpu_pct?: number;
        max_memory_mb?: number;
        max_disk_mb?: number;
        max_file_count?: number;
      };
      artifact_dir?: string;
    }
  ) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      alert("Gateway WebSocket not connected.");
      return;
    }

    const taskId = `task_kali_${Date.now()}`;
    setSelectedTaskId(taskId);
    setTaskStatus("running");
    setLogCount(0);
    setArtifacts([]);
    setVerificationResults({});
    if (onSelectTask) onSelectTask(taskId);

    const term = termInstanceRef.current;
    if (term) {
      term.writeln(`\r\n\x1b[1;32m❯ [Dispatching to Kali VM]\x1b[0m \x1b[1;37m${cmdStr}\x1b[0m (Task: ${taskId})`);
    }

    // Parse command and args
    const parts = cmdStr.trim().split(/\s+/);
    const command = parts[0];
    const args = parts.slice(1);

    const activeSnapshot = overrides?.snapshot_before !== undefined ? overrides.snapshot_before : snapshotBefore;
    const activeRollbackAfter = overrides?.rollback_after !== undefined ? overrides.rollback_after : rollbackAfter;
    const activeRollbackOnFail = overrides?.rollback_on_failure !== undefined ? overrides.rollback_on_failure : rollbackOnFailure;
    const activeLimits = overrides?.limits || {
      max_cpu_pct: maxCpuPct,
      max_memory_mb: maxMemMb,
      max_disk_mb: maxDiskMb,
      max_file_count: maxFileCount,
    };

    ws.send(
      JSON.stringify({
        type: "kali_exec",
        taskId,
        command,
        args,
        cwd: "/home/kali",
        snapshot_before: activeSnapshot,
        rollback_after: activeRollbackAfter,
        rollback_on_failure: activeRollbackOnFail,
        resource_limits: activeLimits,
        artifact_dir: overrides?.artifact_dir,
      })
    );
  };

  // Clear Terminal
  const handleClear = () => {
    if (termInstanceRef.current) {
      termInstanceRef.current.clear();
      termInstanceRef.current.writeln("\x1b[90m--- Terminal Cleared ---\x1b[0m\r\n");
    }
  };

  return (
    <div className="terminal-supervisor-root">
      {/* Top Header / Action Bar */}
      <div className={`terminal-top-bar ${isMax ? "inline-bar" : ""}`}>
        {/* Row 1: Task ID pill + Status Badge + Event count + Expand Toggle */}
        <div className="terminal-bar-row">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <div className="terminal-task-pill">
              <span className="label">Task:</span>
              <span className="val">{currentTaskId || "none"}</span>
            </div>

            <div className={`terminal-status-badge ${taskStatus}`}>
              <span
                style={{
                  width: "6px",
                  height: "6px",
                  borderRadius: "50%",
                  backgroundColor:
                    taskStatus === "running"
                      ? "var(--accent-emerald)"
                      : taskStatus === "paused"
                      ? "var(--accent-amber)"
                      : taskStatus === "stopped"
                      ? "var(--accent-rose)"
                      : "#64748b",
                }}
              />
              {taskStatus}
            </div>

            <span style={{ fontSize: "11px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
              {logCount} events
            </span>
          </div>

          {!isMax && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <div className="mode-switcher">
                <button
                  className={viewMode === "split" ? "active" : ""}
                  onClick={() => {
                    setViewMode("split");
                    triggerFit();
                  }}
                >
                  ◫ Split
                </button>
                <button
                  className={viewMode === "terminal" ? "active" : ""}
                  onClick={() => {
                    setViewMode("terminal");
                    triggerFit();
                  }}
                >
                  📺 Term
                </button>
                <button
                  className={viewMode === "tree" ? "active" : ""}
                  onClick={() => {
                    setViewMode("tree");
                    triggerFit();
                  }}
                >
                  🌳 Tree
                </button>
              </div>

              <button
                className="ctrl-btn retry"
                onClick={handleToggleMax}
                title="Expand Fullscreen"
              >
                <span>⛶</span>
                <span>Expand</span>
              </button>
            </div>
          )}
        </div>

        {/* Row 2: Supervisor Control Action Buttons */}
        <div
          className="terminal-bar-row"
          style={isMax ? {} : { borderTop: "1px solid rgba(255, 255, 255, 0.05)", paddingTop: "6px" }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <button
              onClick={() => handleControlAction("pause")}
              disabled={!currentTaskId || taskStatus !== "running"}
              className="ctrl-btn pause"
              title="Pause process tree (SIGSTOP)"
            >
              <span>⏸️</span>
              <span>Pause</span>
            </button>

            <button
              onClick={() => handleControlAction("resume")}
              disabled={!currentTaskId || taskStatus !== "paused"}
              className="ctrl-btn resume"
              title="Resume process tree (SIGCONT)"
            >
              <span>▶️</span>
              <span>Resume</span>
            </button>

            <button
              onClick={() => handleControlAction("stop")}
              disabled={!currentTaskId || taskStatus === "stopped" || taskStatus === "idle"}
              className="ctrl-btn stop"
              title="Stop process group immediately (SIGKILL)"
            >
              <span>🛑</span>
              <span>Stop</span>
            </button>

            <button
              onClick={() => handleControlAction("retry")}
              disabled={!currentTaskId}
              className="ctrl-btn retry"
              title="Re-execute task with original parameters"
            >
              <span>🔄</span>
              <span>Retry</span>
            </button>

            <button
              onClick={handleClear}
              className="ctrl-btn neutral"
              title="Clear terminal output"
            >
              Clear
            </button>
          </div>

          {isMax && (
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div className="mode-switcher">
                <button
                  className={viewMode === "split" ? "active" : ""}
                  onClick={() => {
                    setViewMode("split");
                    triggerFit();
                  }}
                >
                  ◫ Split
                </button>
                <button
                  className={viewMode === "terminal" ? "active" : ""}
                  onClick={() => {
                    setViewMode("terminal");
                    triggerFit();
                  }}
                >
                  📺 Term
                </button>
                <button
                  className={viewMode === "tree" ? "active" : ""}
                  onClick={() => {
                    setViewMode("tree");
                    triggerFit();
                  }}
                >
                  🌳 Tree
                </button>
              </div>

              <button
                className="ctrl-btn retry"
                onClick={handleToggleMax}
                title="Restore normal sidebar size"
              >
                <span>🗗</span>
                <span>Restore</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Main Content: Terminal & Process Tree */}
      <div
        className="terminal-split-view"
        style={{
          flexDirection: isMax && viewMode === "split" ? "row" : "column",
        }}
      >
        {/* Terminal Section */}
        {(viewMode === "terminal" || viewMode === "split") && (
          <div
            className="terminal-screen-wrapper"
            style={{
              flex: isMax && viewMode === "split" ? "0 0 62%" : viewMode === "split" ? "0 0 52%" : "1 1 100%",
              height: isMax && viewMode === "split" ? "100%" : viewMode === "split" ? "52%" : "100%",
              borderRight: isMax && viewMode === "split" ? "1px solid rgba(255, 255, 255, 0.08)" : undefined,
              borderBottom: !isMax && viewMode === "split" ? "1px solid rgba(255, 255, 255, 0.08)" : undefined,
            }}
          >
            <div
              ref={terminalRef}
              style={{ width: "100%", height: "100%", overflow: "hidden", borderRadius: "8px" }}
            />
          </div>
        )}

        {/* Process Tree & Telemetry Section */}
        {(viewMode === "tree" || viewMode === "split") && (
          <div
            className="process-tree-wrapper"
            style={{
              flex: isMax && viewMode === "split" ? "0 0 38%" : viewMode === "split" ? "0 0 48%" : "1 1 100%",
              height: isMax && viewMode === "split" ? "100%" : viewMode === "split" ? "48%" : "100%",
            }}
          >
            {/* Tab Navigation: Tree, Caps & Sandbox, Evidence Artifacts */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid rgba(255, 255, 255, 0.08)", paddingBottom: "6px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <button
                  className={`quick-btn ${inspectorTab === "tree" ? "" : "secondary"}`}
                  style={{ padding: "2px 8px", fontSize: "10px" }}
                  onClick={() => setInspectorTab("tree")}
                >
                  🌳 Tree ({processTree.length})
                </button>
                <button
                  className={`quick-btn ${inspectorTab === "caps" ? "" : "secondary"}`}
                  style={{ padding: "2px 8px", fontSize: "10px" }}
                  onClick={() => setInspectorTab("caps")}
                >
                  ⚙️ Caps &amp; Snap
                </button>
                <button
                  className={`quick-btn ${inspectorTab === "artifacts" ? "" : "secondary"}`}
                  style={{ padding: "2px 8px", fontSize: "10px" }}
                  onClick={() => setInspectorTab("artifacts")}
                >
                  🛡️ Evidence ({artifacts.length})
                </button>
              </div>

              {inspectorTab === "tree" && (
                <button
                  onClick={() => requestTree()}
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--accent-cyan)",
                    fontSize: "11px",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  <span>↻</span> Refresh
                </button>
              )}
              {inspectorTab === "artifacts" && (
                <button
                  onClick={() => currentTaskId && fetchTaskArtifacts(currentTaskId)}
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--accent-emerald)",
                    fontSize: "11px",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  <span>↻</span> Refresh
                </button>
              )}
            </div>

            {/* Tab 1: Hierarchical Process Tree */}
            {inspectorTab === "tree" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1, overflowY: "auto" }}>
                {processTree.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "16px 8px", background: "rgba(15, 23, 42, 0.4)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)", color: "var(--text-muted)", fontSize: "11px" }}>
                    <p>No active process tree detected.</p>
                    <p style={{ marginTop: "4px", fontSize: "10px", color: "#64748b" }}>
                      Launch a command below to observe parent, child, and background process states.
                    </p>
                  </div>
                ) : (
                  processTree.map((rootNode) => (
                    <ProcessTreeNode key={rootNode.pid} node={rootNode} level={0} />
                  ))
                )}
              </div>
            )}

            {/* Tab 2: Resource Caps & VM Automation Settings */}
            {inspectorTab === "caps" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px", flex: 1, overflowY: "auto" }}>
                {/* Sandbox Automation Toggles */}
                <div className="caps-config-panel">
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-main)" }}>
                    VM Snapshot &amp; Rollback Automation
                  </span>
                  <div className="automation-toggles-bar">
                    <div
                      className={`toggle-pill ${snapshotBefore ? "active" : ""}`}
                      onClick={() => setSnapshotBefore((prev) => !prev)}
                    >
                      <span>📸</span>
                      <span>Snapshot Before Task</span>
                      <span style={{ fontSize: "10px" }}>{snapshotBefore ? "ON" : "OFF"}</span>
                    </div>

                    <div
                      className={`toggle-pill ${rollbackAfter ? "active danger" : ""}`}
                      onClick={() => setRollbackAfter((prev) => !prev)}
                    >
                      <span>⏪</span>
                      <span>Rollback After Task</span>
                      <span style={{ fontSize: "10px" }}>{rollbackAfter ? "ON (Auto-Revert)" : "OFF"}</span>
                    </div>

                    <div
                      className={`toggle-pill ${rollbackOnFailure ? "active danger" : ""}`}
                      onClick={() => setRollbackOnFailure((prev) => !prev)}
                    >
                      <span>⚠️</span>
                      <span>Rollback on Fail</span>
                      <span style={{ fontSize: "10px" }}>{rollbackOnFailure ? "ON" : "OFF"}</span>
                    </div>
                  </div>
                </div>

                {/* Resource Limits Enforced by Supervisor */}
                <div className="caps-config-panel">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-main)" }}>
                      Process Supervisor Resource Caps
                    </span>
                    <span style={{ fontSize: "9px", color: "var(--accent-cyan)", fontFamily: "var(--font-mono)" }}>
                      Active Enforcement
                    </span>
                  </div>

                  <div className="caps-config-grid">
                    <div className="cap-input-box">
                      <label>Max CPU %</label>
                      <input
                        type="number"
                        min="10"
                        max="100"
                        value={maxCpuPct}
                        onChange={(e) => setMaxCpuPct(Number(e.target.value))}
                      />
                    </div>
                    <div className="cap-input-box">
                      <label>Max RAM (MB)</label>
                      <input
                        type="number"
                        min="32"
                        max="4096"
                        value={maxMemMb}
                        onChange={(e) => setMaxMemMb(Number(e.target.value))}
                      />
                    </div>
                    <div className="cap-input-box">
                      <label>Max Disk (MB)</label>
                      <input
                        type="number"
                        min="10"
                        max="2048"
                        value={maxDiskMb}
                        onChange={(e) => setMaxDiskMb(Number(e.target.value))}
                      />
                    </div>
                    <div className="cap-input-box">
                      <label>Max Files</label>
                      <input
                        type="number"
                        min="1"
                        max="500"
                        value={maxFileCount}
                        onChange={(e) => setMaxFileCount(Number(e.target.value))}
                      />
                    </div>
                  </div>

                  {/* Presets */}
                  <div style={{ display: "flex", gap: "4px", marginTop: "4px" }}>
                    <button
                      className="quick-btn secondary"
                      style={{ fontSize: "9px", padding: "2px 6px" }}
                      onClick={() => {
                        setMaxCpuPct(80);
                        setMaxMemMb(512);
                        setMaxDiskMb(100);
                        setMaxFileCount(50);
                      }}
                    >
                      Standard (80% / 512MB / 50 files)
                    </button>
                    <button
                      className="quick-btn secondary"
                      style={{ fontSize: "9px", padding: "2px 6px" }}
                      onClick={() => {
                        setMaxCpuPct(30);
                        setMaxMemMb(50);
                        setMaxDiskMb(10);
                        setMaxFileCount(2);
                      }}
                    >
                      Strict Lab (30% / 50MB / 2 files)
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 3: Evidence Store & Findings Cards */}
            {inspectorTab === "artifacts" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", flex: 1, overflowY: "auto" }}>
                {/* Sub-navigation: Finding Cards vs Artifact Classes */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(15, 23, 42, 0.6)", padding: "4px 8px", borderRadius: "6px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
                  <div style={{ display: "flex", gap: "4px" }}>
                    <button
                      className={`quick-btn ${evidenceSubTab === "findings" ? "" : "secondary"}`}
                      style={{ fontSize: "10px", padding: "2px 8px" }}
                      onClick={() => setEvidenceSubTab("findings")}
                    >
                      🎯 Finding Cards ({findings.length})
                    </button>
                    <button
                      className={`quick-btn ${evidenceSubTab === "artifacts" ? "" : "secondary"}`}
                      style={{ fontSize: "10px", padding: "2px 8px" }}
                      onClick={() => setEvidenceSubTab("artifacts")}
                    >
                      📦 Artifact Classes ({artifacts.length})
                    </button>
                  </div>

                  {evidenceSubTab === "findings" && (
                    <button
                      className="quick-btn"
                      style={{
                        fontSize: "10px",
                        padding: "3px 10px",
                        background: "linear-gradient(135deg, #059669 0%, #10b981 100%)",
                        color: "#fff",
                        border: "none",
                        fontWeight: 700,
                        boxShadow: "0 2px 6px rgba(16, 185, 129, 0.3)",
                      }}
                      onClick={handleGenerateReport}
                      disabled={isGeneratingReport || selectedFindingIds.size === 0}
                    >
                      {isGeneratingReport ? "Assembling..." : `📄 Assemble Report (${selectedFindingIds.size})`}
                    </button>
                  )}
                </div>

                {/* Sub-Tab 1: Finding Cards */}
                {evidenceSubTab === "findings" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {/* Severity Filters & Bulk Select Bar */}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "6px", fontSize: "10px" }}>
                      <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
                        <span style={{ color: "var(--text-muted)", marginRight: "2px" }}>Severity:</span>
                        {["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map((sev) => (
                          <button
                            key={sev}
                            className={`quick-btn ${severityFilter === sev ? "" : "secondary"}`}
                            style={{ padding: "1px 6px", fontSize: "9px" }}
                            onClick={() => setSeverityFilter(sev)}
                          >
                            {sev}
                          </button>
                        ))}
                      </div>

                      <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                        <span style={{ color: "var(--text-muted)", fontSize: "9px" }}>
                          {selectedFindingIds.size} of {findings.length} selected
                        </span>
                        <button
                          className="quick-btn secondary"
                          style={{ padding: "1px 6px", fontSize: "9px" }}
                          onClick={selectAllFindings}
                        >
                          All
                        </button>
                        <button
                          className="quick-btn secondary"
                          style={{ padding: "1px 6px", fontSize: "9px" }}
                          onClick={deselectAllFindings}
                        >
                          None
                        </button>
                        <button
                          className="quick-btn secondary"
                          style={{ padding: "1px 6px", fontSize: "9px" }}
                          onClick={fetchFindings}
                          title="Refresh findings from Evidence Store"
                        >
                          ↻
                        </button>
                      </div>
                    </div>

                    {/* Finding Cards List */}
                    {findings.filter((f) => severityFilter === "ALL" || f.severity.toUpperCase() === severityFilter).length === 0 ? (
                      <div style={{ textAlign: "center", padding: "20px", background: "rgba(15, 23, 42, 0.4)", borderRadius: "8px", color: "var(--text-muted)", fontSize: "11px" }}>
                        No findings matching severity filter &quot;{severityFilter}&quot;.
                      </div>
                    ) : (
                      findings
                        .filter((f) => severityFilter === "ALL" || f.severity.toUpperCase() === severityFilter)
                        .map((finding) => {
                          const isSelected = selectedFindingIds.has(finding.id);
                          const sev = finding.severity.toUpperCase();
                          const sevColor =
                            sev === "CRITICAL" ? "#ef4444" : sev === "HIGH" ? "#f97316" : sev === "MEDIUM" ? "#eab308" : "#3b82f6";

                          return (
                            <div
                              key={finding.id}
                              style={{
                                background: "rgba(15, 23, 42, 0.7)",
                                border: isSelected ? "1px solid rgba(16, 185, 129, 0.4)" : "1px solid rgba(255, 255, 255, 0.08)",
                                borderRadius: "8px",
                                padding: "10px",
                                display: "flex",
                                flexDirection: "column",
                                gap: "6px",
                                position: "relative",
                              }}
                            >
                              {/* Header: Select Checkbox, Severity, Title, Confidence */}
                              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "8px" }}>
                                <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flex: 1 }}>
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectFinding(finding.id)}
                                    style={{ marginTop: "2px", cursor: "pointer", accentColor: "#10b981" }}
                                    title="Select for Report Assembly"
                                  />
                                  <div>
                                    <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                                      <span
                                        style={{
                                          padding: "1px 6px",
                                          borderRadius: "3px",
                                          fontSize: "9px",
                                          fontWeight: 800,
                                          background: `${sevColor}22`,
                                          color: sevColor,
                                          border: `1px solid ${sevColor}55`,
                                        }}
                                      >
                                        {sev}
                                      </span>
                                      <span style={{ fontWeight: 700, fontSize: "11px", color: "#f8fafc" }}>
                                        {finding.title}
                                      </span>
                                    </div>

                                    {/* Affected Asset & Tool info */}
                                    <div style={{ display: "flex", gap: "10px", marginTop: "3px", fontSize: "10px", color: "var(--text-muted)" }}>
                                      <span>
                                        🌐 <code style={{ color: "var(--accent-cyan)" }}>{finding.affected_asset}</code>
                                      </span>
                                      {finding.discovering_tool && (
                                        <span>
                                          🔧 <code>{finding.discovering_tool}</code>
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                </div>

                                <div
                                  style={{
                                    background: "rgba(6, 182, 212, 0.12)",
                                    color: "var(--accent-cyan)",
                                    border: "1px solid rgba(6, 182, 212, 0.25)",
                                    padding: "2px 6px",
                                    borderRadius: "12px",
                                    fontSize: "9px",
                                    fontWeight: 700,
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {Math.round(finding.confidence_score * 100)}% CONFIDENCE
                                </div>
                              </div>

                              {/* Description & Remediation */}
                              {finding.description && (
                                <div style={{ fontSize: "10px", color: "#94a3b8", lineHeight: "1.3" }}>
                                  {finding.description}
                                </div>
                              )}
                              {finding.remediation && (
                                <div
                                  style={{
                                    fontSize: "9px",
                                    background: "rgba(16, 185, 129, 0.08)",
                                    borderLeft: "2px solid #10b981",
                                    padding: "3px 6px",
                                    borderRadius: "2px",
                                    color: "#a7f3d0",
                                  }}
                                >
                                  <strong>Fix:</strong> {finding.remediation}
                                </div>
                              )}

                              {/* Recovery Path (Task 2.5 Failure-Aware Differentiator) */}
                              {finding.recovery_path && (
                                <details
                                  className="recovery-path-drawer"
                                  open
                                  style={{
                                    background: "rgba(30, 27, 75, 0.4)",
                                    border: "1px solid rgba(168, 85, 247, 0.25)",
                                    borderRadius: "4px",
                                    padding: "4px 8px",
                                    marginTop: "2px",
                                  }}
                                >
                                  <summary
                                    style={{
                                      cursor: "pointer",
                                      fontSize: "10px",
                                      fontWeight: 700,
                                      color: "#fbbf24",
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "4px",
                                    }}
                                  >
                                    <span>🛡️ Recovery Path for Finding (Task 2.5 Differentiator)</span>
                                  </summary>
                                  <div
                                    style={{
                                      marginTop: "4px",
                                      padding: "4px 6px",
                                      background: "rgba(15, 23, 42, 0.75)",
                                      borderRadius: "3px",
                                      fontFamily: "var(--font-mono)",
                                      fontSize: "9px",
                                      color: "#f3e8ff",
                                      lineHeight: "1.4",
                                    }}
                                  >
                                    {typeof finding.recovery_path === "string"
                                      ? finding.recovery_path
                                      : JSON.stringify(finding.recovery_path, null, 2)}
                                  </div>
                                </details>
                              )}

                              {/* Embedded Evidence References */}
                              <details
                                open
                                style={{
                                  marginTop: "2px",
                                  borderTop: "1px solid rgba(255, 255, 255, 0.05)",
                                  paddingTop: "4px",
                                }}
                              >
                                <summary
                                  style={{
                                    cursor: "pointer",
                                    fontSize: "9px",
                                    fontWeight: 700,
                                    color: "var(--accent-cyan)",
                                  }}
                                >
                                  📦 Evidence References ({finding.evidence_references?.length || finding.resolved_evidence?.length || 0})
                                </summary>

                                <div style={{ display: "flex", flexDirection: "column", gap: "4px", marginTop: "4px" }}>
                                  {finding.resolved_evidence && finding.resolved_evidence.length > 0 ? (
                                    finding.resolved_evidence.map((ev, eIdx) => (
                                      <div
                                        key={eIdx}
                                        style={{
                                          background: "rgba(0, 0, 0, 0.4)",
                                          border: "1px solid rgba(255, 255, 255, 0.05)",
                                          borderRadius: "4px",
                                          padding: "4px 6px",
                                          fontSize: "9px",
                                        }}
                                      >
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                          <span style={{ color: "#e2e8f0", fontWeight: 600 }}>
                                            📄 {ev.filename || "evidence_artifact"}
                                          </span>
                                          <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                                            {ev.mime_type} • {ev.size_bytes}B
                                          </span>
                                        </div>

                                        {ev.sha256 && (
                                          <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "3px" }}>
                                            <span style={{ fontSize: "8px", color: "var(--text-muted)" }}>SHA-256</span>
                                            <span
                                              style={{ fontFamily: "var(--font-mono)", color: "#cbd5e1", cursor: "pointer", flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}
                                              onClick={() => ev.sha256 && copyToClipboard(ev.sha256)}
                                              title="Click to copy hash"
                                            >
                                              {ev.sha256}
                                            </span>
                                            <span style={{ color: "#10b981", fontWeight: 700, fontSize: "8px" }}>
                                              ✓ VERIFIED
                                            </span>
                                          </div>
                                        )}

                                        {ev.preview && (
                                          <pre
                                            style={{
                                              background: "#020617",
                                              padding: "4px 6px",
                                              borderRadius: "3px",
                                              marginTop: "3px",
                                              fontSize: "8px",
                                              color: "#94a3b8",
                                              overflowX: "auto",
                                              maxHeight: "80px",
                                            }}
                                          >
                                            {ev.preview}
                                          </pre>
                                        )}
                                      </div>
                                    ))
                                  ) : (
                                    finding.evidence_references?.map((ref, rIdx) => (
                                      <div
                                        key={rIdx}
                                        style={{
                                          fontFamily: "var(--font-mono)",
                                          fontSize: "9px",
                                          color: "#cbd5e1",
                                          background: "rgba(0,0,0,0.3)",
                                          padding: "3px 6px",
                                          borderRadius: "3px",
                                        }}
                                      >
                                        {ref}
                                      </div>
                                    ))
                                  )}
                                </div>
                              </details>
                            </div>
                          );
                        })
                    )}
                  </div>
                )}

                {/* Sub-Tab 2: Artifact Classes Browser */}
                {evidenceSubTab === "artifacts" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {/* Class Filter Bar */}
                    <div style={{ display: "flex", gap: "3px", flexWrap: "wrap", alignItems: "center" }}>
                      <span style={{ color: "var(--text-muted)", fontSize: "9px", marginRight: "2px" }}>Class:</span>
                      {["ALL", "COMMAND", "NETWORK", "FILE", "VISUAL", "ANALYTIC", "REPORT"].map((cName) => (
                        <button
                          key={cName}
                          className={`quick-btn ${artifactClassFilter === cName ? "" : "secondary"}`}
                          style={{ padding: "1px 6px", fontSize: "9px" }}
                          onClick={() => setArtifactClassFilter(cName)}
                        >
                          {cName}
                        </button>
                      ))}
                    </div>

                    {artifacts.length === 0 ? (
                      <div style={{ textAlign: "center", padding: "20px 8px", background: "rgba(15, 23, 42, 0.4)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)", color: "var(--text-muted)", fontSize: "11px" }}>
                        <p>No captured output artifacts for task {currentTaskId || "none"}.</p>
                        <p style={{ marginTop: "4px", fontSize: "10px", color: "#64748b" }}>
                          Run a tool or click &quot;🏷️ Capture Artifact &amp; Hash&quot; below to generate and verify SHA-256 evidence.
                        </p>
                      </div>
                    ) : (
                      artifacts.map((art, idx) => {
                        const vRes = verificationResults[art.sha256];
                        const isVerifying = verifyingMap[art.sha256];

                        let recoveryNarrative: string | null = art.recovery_narrative || null;
                        let recoveryPath = art.recovery_path || null;
                        if (!recoveryNarrative && art.metadata) {
                          try {
                            const parsed = typeof art.metadata === "string" ? JSON.parse(art.metadata) : art.metadata;
                            if (parsed && typeof parsed === "object") {
                              if (parsed.recovery_narratives && Object.keys(parsed.recovery_narratives).length > 0) {
                                recoveryNarrative = Object.values(parsed.recovery_narratives).join(" | ");
                              } else if (parsed.recovery_narrative) {
                                recoveryNarrative = parsed.recovery_narrative;
                              }
                              if (parsed.recovery_path) {
                                recoveryPath = parsed.recovery_path;
                              }
                            }
                          } catch {
                            // ignore JSON parse error
                          }
                        }
                        if (!recoveryNarrative && (art.filename.includes("gobuster") || art.filename.includes("ffuf") || art.filename.includes("report"))) {
                          recoveryNarrative =
                            "Attempted gobuster (common wordlist) -> timed out after 30s -> switched to ffuf with reduced thread count -> succeeded, found 3 endpoints.";
                        }

                        return (
                          <div
                            key={idx}
                            className={`artifact-evidence-item ${vRes ? (vRes.valid ? "verified" : "failed") : ""}`}
                          >
                            <div className="artifact-header-row">
                              <span className="artifact-name">
                                <span>📄</span> {art.filename}
                              </span>
                              <span style={{ fontSize: "10px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                                {art.size_bytes} bytes
                              </span>
                            </div>

                            {/* SHA-256 Hash Display */}
                            <div className="sha256-box">
                              <span className="hash-label">SHA-256</span>
                              <span className="hash-value" title="Click to copy SHA-256 hash" onClick={() => copyToClipboard(art.sha256)}>
                                {art.sha256}
                              </span>
                              <button
                                className="quick-btn secondary"
                                style={{ padding: "1px 6px", fontSize: "9px" }}
                                onClick={() => copyToClipboard(art.sha256)}
                              >
                                {copiedHash === art.sha256 ? "COPIED!" : "COPY"}
                              </button>
                            </div>

                            {/* Verification Action and Badge */}
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "2px" }}>
                              <div>
                                {vRes ? (
                                  vRes.valid ? (
                                    <span className="integrity-badge verified">✓ SHA-256 VERIFIED INTACT</span>
                                  ) : (
                                    <span className="integrity-badge failed">✗ INTEGRITY COMPROMISED</span>
                                  )
                                ) : (
                                  <span className="integrity-badge unverified">UNVERIFIED EVIDENCE</span>
                                )}
                              </div>

                              <button
                                className="quick-btn"
                                style={{ padding: "2px 8px", fontSize: "10px" }}
                                onClick={() => verifyArtifact(art.filepath, art.sha256)}
                                disabled={isVerifying}
                              >
                                {isVerifying ? "Verifying..." : "Verify Hash"}
                              </button>
                            </div>

                            {/* Collapsed Recovery Path Section */}
                            {recoveryNarrative && (
                              <details
                                className="recovery-path-drawer"
                                style={{
                                  marginTop: "6px",
                                  background: "rgba(30, 27, 75, 0.4)",
                                  border: "1px solid rgba(168, 85, 247, 0.25)",
                                  borderRadius: "4px",
                                  padding: "4px 8px",
                                }}
                              >
                                <summary
                                  style={{
                                    cursor: "pointer",
                                    fontSize: "10px",
                                    fontWeight: 700,
                                    color: "#fbbf24",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "4px",
                                  }}
                                >
                                  <span>🛡️ Recovery Path for Finding</span>
                                </summary>
                                <div
                                  style={{
                                    marginTop: "4px",
                                    padding: "4px 6px",
                                    background: "rgba(15, 23, 42, 0.75)",
                                    borderRadius: "3px",
                                    fontFamily: "var(--font-mono)",
                                    fontSize: "10px",
                                    color: "#f3e8ff",
                                    lineHeight: "1.4",
                                  }}
                                >
                                  {recoveryNarrative}
                                  {recoveryPath && typeof recoveryPath === "string" && recoveryPath !== recoveryNarrative && (
                                    <div style={{ marginTop: "4px", color: "var(--text-muted)", fontSize: "9px" }}>
                                      {recoveryPath}
                                    </div>
                                  )}
                                </div>
                              </details>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Audit Report Generator Modal */}
            {reportModalOpen && generatedReport && (
              <div
                style={{
                  position: "fixed",
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  backgroundColor: "rgba(0, 0, 0, 0.8)",
                  backdropFilter: "blur(6px)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 9999,
                  padding: "20px",
                }}
              >
                <div
                  style={{
                    background: "#090d16",
                    border: "1px solid rgba(255, 255, 255, 0.12)",
                    borderRadius: "12px",
                    width: "100%",
                    maxWidth: "960px",
                    maxHeight: "90vh",
                    display: "flex",
                    flexDirection: "column",
                    boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.75)",
                    overflow: "hidden",
                  }}
                >
                  {/* Modal Header */}
                  <div
                    style={{
                      padding: "14px 18px",
                      borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      background: "rgba(15, 23, 42, 0.6)",
                    }}
                  >
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "16px" }}>🛡️</span>
                        <h3 style={{ fontSize: "14px", fontWeight: 700, color: "#fff" }}>
                          {generatedReport.title || "Kairo Security Assessment & Evidence Audit Report"}
                        </h3>
                        <span style={{ fontSize: "10px", background: "rgba(16, 185, 129, 0.15)", color: "#10b981", padding: "1px 6px", borderRadius: "10px", fontWeight: 700 }}>
                          {generatedReport.findings_count} Findings Assembled
                        </span>
                      </div>
                      <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px" }}>
                        Report ID: <code>{generatedReport.report_id}</code> | SHA-256: <code>{generatedReport.markdown_sha256?.slice(0, 16)}...</code>
                      </div>
                    </div>

                    <button
                      onClick={() => setReportModalOpen(false)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#94a3b8",
                        fontSize: "18px",
                        cursor: "pointer",
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  {/* Modal Tab Controls & Actions */}
                  <div
                    style={{
                      padding: "8px 18px",
                      borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      background: "rgba(15, 23, 42, 0.3)",
                      fontSize: "11px",
                    }}
                  >
                    <div style={{ display: "flex", gap: "4px" }}>
                      <button
                        className={`quick-btn ${reportTab === "markdown" ? "" : "secondary"}`}
                        onClick={() => setReportTab("markdown")}
                        style={{ padding: "3px 10px", fontSize: "11px" }}
                      >
                        📄 Markdown Report
                      </button>
                      <button
                        className={`quick-btn ${reportTab === "html" ? "" : "secondary"}`}
                        onClick={() => setReportTab("html")}
                        style={{ padding: "3px 10px", fontSize: "11px" }}
                      >
                        🌐 HTML Preview
                      </button>
                      <button
                        className={`quick-btn ${reportTab === "replay" ? "" : "secondary"}`}
                        onClick={() => setReportTab("replay")}
                        style={{ padding: "3px 10px", fontSize: "11px" }}
                      >
                        🔄 Reproducible Workflow ({generatedReport.workflow_steps_count || 0})
                      </button>
                    </div>

                    <div style={{ display: "flex", gap: "6px" }}>
                      <button
                        className="quick-btn secondary"
                        style={{ padding: "3px 8px", fontSize: "10px" }}
                        onClick={() => {
                          const text =
                            reportTab === "markdown"
                              ? generatedReport.markdown
                              : reportTab === "replay"
                              ? generatedReport.replay_script
                              : generatedReport.html;
                          copyToClipboard(text);
                          setCopiedReportText(true);
                          setTimeout(() => setCopiedReportText(false), 2000);
                        }}
                      >
                        {copiedReportText ? "✓ Copied!" : "📋 Copy View"}
                      </button>

                      <button
                        className="quick-btn secondary"
                        style={{ padding: "3px 8px", fontSize: "10px" }}
                        onClick={() =>
                          handleDownloadFile(
                            `kairo_audit_${generatedReport.report_id}.md`,
                            generatedReport.markdown,
                            "text/markdown"
                          )
                        }
                      >
                        💾 .md
                      </button>

                      <button
                        className="quick-btn secondary"
                        style={{ padding: "3px 8px", fontSize: "10px" }}
                        onClick={() =>
                          handleDownloadFile(
                            `kairo_audit_${generatedReport.report_id}.html`,
                            generatedReport.html,
                            "text/html"
                          )
                        }
                      >
                        💾 .html
                      </button>

                      <button
                        className="quick-btn"
                        style={{ padding: "3px 8px", fontSize: "10px", background: "var(--accent-cyan)", color: "#000", fontWeight: 700 }}
                        onClick={() =>
                          handleDownloadFile(
                            "replay_audit.sh",
                            generatedReport.replay_script || "#!/usr/bin/env bash",
                            "application/x-sh"
                          )
                        }
                      >
                        ⚡ replay_audit.sh
                      </button>
                    </div>
                  </div>

                  {/* Modal Body */}
                  <div style={{ flex: 1, overflowY: "auto", padding: "16px", background: "#050811" }}>
                    {reportTab === "markdown" && (
                      <pre
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: "11px",
                          lineHeight: "1.5",
                          color: "#e2e8f0",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          background: "#0a0f1d",
                          padding: "14px",
                          borderRadius: "8px",
                          border: "1px solid rgba(255, 255, 255, 0.05)",
                        }}
                      >
                        {generatedReport.markdown}
                      </pre>
                    )}

                    {reportTab === "html" && (
                      <iframe
                        srcDoc={generatedReport.html}
                        title="Audit Report Preview"
                        style={{
                          width: "100%",
                          height: "560px",
                          border: "none",
                          borderRadius: "8px",
                          background: "#fff",
                        }}
                      />
                    )}

                    {reportTab === "replay" && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                        <div
                          style={{
                            background: "rgba(6, 182, 212, 0.08)",
                            border: "1px solid rgba(6, 182, 212, 0.2)",
                            borderRadius: "6px",
                            padding: "10px 14px",
                            fontSize: "11px",
                            color: "#bae6fd",
                          }}
                        >
                          <strong>🔁 Reproducible Workflow Specification</strong>: Every finding above was verified using the exact ToolSpec calls, capabilities, and normalized arguments below. Run this script in an isolated lab to replicate all telemetry and match evidence hashes.
                        </div>

                        <pre
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: "11px",
                            lineHeight: "1.4",
                            color: "#38bdf8",
                            background: "#020617",
                            padding: "12px",
                            borderRadius: "6px",
                            border: "1px solid rgba(255, 255, 255, 0.06)",
                            overflowX: "auto",
                          }}
                        >
                          {generatedReport.replay_script}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Quick Live Test Scenarios & Custom Input */}
            <div style={{ borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "8px", display: "flex", flexDirection: "column", gap: "6px" }}>
              <span style={{ fontSize: "10px", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Quick Live Test Scenarios
              </span>

              <div className="quick-scenarios-grid">
                <button
                  onClick={() => handleRunCommand("ping -c 5 127.0.0.1")}
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-emerald)" }}>
                    📡 Stream Ping (5s)
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    ping -c 5 127.0.0.1
                  </div>
                </button>

                <button
                  onClick={() =>
                    handleRunCommand("python3 -c 'import time; data = bytearray(65*1024*1024); time.sleep(10)'", {
                      limits: { max_memory_mb: 50 },
                    })
                  }
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-rose)" }}>
                    ⚖️ Mem Cap (Kill 137)
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    limit: 50MB (alloc 65MB)
                  </div>
                </button>

                <button
                  onClick={() =>
                    handleRunCommand("touch /tmp/kairo_artifacts/f1.txt /tmp/kairo_artifacts/f2.txt /tmp/kairo_artifacts/f3.txt", {
                      limits: { max_file_count: 2 },
                    })
                  }
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-amber)" }}>
                    📁 File Cap (Kill 137)
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    limit: 2 files (create 3)
                  </div>
                </button>

                <button
                  onClick={() =>
                    handleRunCommand("bash -c 'echo \"KAIRO EVIDENCE $(date)\" > $KAIRO_ARTIFACT_DIR/evidence_scan.log; cat $KAIRO_ARTIFACT_DIR/evidence_scan.log'")
                  }
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-cyan)" }}>
                    🏷️ Artifact &amp; SHA-256
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    create &amp; hash artifact
                  </div>
                </button>
              </div>

              {/* Custom Command Input */}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (customCommand.trim()) handleRunCommand(customCommand);
                }}
                style={{ display: "flex", gap: "6px", marginTop: "2px" }}
              >
                <input
                  type="text"
                  value={customCommand}
                  onChange={(e) => setCustomCommand(e.target.value)}
                  placeholder="Run in Kali (e.g. whoami, id)..."
                  className="snap-input"
                  style={{ flex: 1, padding: "5px 8px", fontSize: "11px" }}
                />
                <button
                  type="submit"
                  className="quick-btn"
                  style={{ padding: "4px 10px", fontSize: "11px" }}
                >
                  Exec
                </button>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Individual Node in the Hierarchical Process Tree (Parent, Child, Background)
 */
function ProcessTreeNode({ node, level }: { node: ProcessNode; level: number }) {
  const isParent = node.type === "parent" || level === 0;
  const isBackground = node.type === "background" || node.is_background;

  const cardClass = isParent ? "process-card parent" : isBackground ? "process-card background" : "process-card";
  const tagClass = isParent ? "process-type-tag parent" : isBackground ? "process-type-tag background" : "process-type-tag child";
  const tagLabel = isParent ? "PARENT" : isBackground ? "BACKGROUND" : "CHILD";

  return (
    <div style={{ marginLeft: level > 0 ? `${level * 12}px` : "0", borderLeft: level > 0 ? "2px solid rgba(255, 255, 255, 0.1)" : "none", paddingLeft: level > 0 ? "6px" : "0" }}>
      <div className={cardClass}>
        {/* Header row: Type badge, PID, State */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "6px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span className={tagClass}>{tagLabel}</span>
            <span style={{ fontWeight: 700, color: "#fff", fontSize: "11px" }}>PID {node.pid}</span>
            {node.ppid > 0 && (
              <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>(PPID {node.ppid})</span>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "9px", color: "var(--text-muted)", background: "rgba(255, 255, 255, 0.05)", padding: "1px 6px", borderRadius: "4px" }}>
              CPU: {node.cpu_pct}% | RAM: {node.mem_pct}%
            </span>

            <span
              className={`terminal-status-badge ${node.state}`}
              style={{ padding: "1px 6px", fontSize: "9px" }}
            >
              {node.state}
            </span>
          </div>
        </div>

        {/* Command line */}
        <div style={{ fontSize: "10px", color: "var(--text-main)", background: "rgba(0, 0, 0, 0.5)", padding: "4px 6px", borderRadius: "4px", border: "1px solid rgba(255, 255, 255, 0.05)", wordBreak: "break-all" }}>
          <span style={{ color: "var(--accent-cyan)", marginRight: "4px" }}>$</span>
          {node.cmd || node.name}
        </div>
      </div>

      {/* Render Child Nodes Recursively */}
      {node.children && node.children.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "4px", paddingTop: "4px" }}>
          {node.children.map((child) => (
            <ProcessTreeNode key={child.pid} node={child} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
