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
      } catch (err) {
        console.error("Terminal WebSocket parse error:", err);
      }
    };

    ws.addEventListener("message", handleMessage);
    return () => {
      ws.removeEventListener("message", handleMessage);
    };
  }, [ws, requestTree]);

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
  const handleRunCommand = (cmdStr: string) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      alert("Gateway WebSocket not connected.");
      return;
    }

    const taskId = `task_kali_${Date.now()}`;
    setSelectedTaskId(taskId);
    setTaskStatus("running");
    setLogCount(0);
    if (onSelectTask) onSelectTask(taskId);

    const term = termInstanceRef.current;
    if (term) {
      term.writeln(`\r\n\x1b[1;32m❯ [Dispatching to Kali VM]\x1b[0m \x1b[1;37m${cmdStr}\x1b[0m (Task: ${taskId})`);
    }

    // Parse command and args
    const parts = cmdStr.trim().split(/\s+/);
    const command = parts[0];
    const args = parts.slice(1);

    ws.send(
      JSON.stringify({
        type: "kali_exec",
        taskId,
        command,
        args,
        cwd: "/home/kali",
        snapshot_before: false,
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
            {/* Tree Section Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid rgba(255, 255, 255, 0.08)", paddingBottom: "6px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span>🌳</span>
                <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--text-main)" }}>
                  Process Tree Supervisor
                </span>
              </div>
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
            </div>

            {/* Hierarchical Process Cards */}
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
                    handleRunCommand("bash -c 'for i in {1..30}; do echo \"Ticking $i/30\"; sleep 1; done'")
                  }
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-amber)" }}>
                    ⏳ Pause/Stop (30s)
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    sleep loop 30s
                  </div>
                </button>

                <button
                  onClick={() =>
                    handleRunCommand("bash -c 'sleep 15 & sleep 20 & wait'")
                  }
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-violet)" }}>
                    👥 Background Procs
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    spawn background & wait
                  </div>
                </button>

                <button
                  onClick={() => handleRunCommand("nmap -sV -p 22,9999 127.0.0.1")}
                  className="scenario-card-btn"
                >
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--accent-cyan)" }}>
                    🔍 Nmap Scan
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    nmap -sV 127.0.0.1
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
