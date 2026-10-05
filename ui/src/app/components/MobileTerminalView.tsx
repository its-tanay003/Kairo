"use client";

import React, { useState, useEffect, useRef } from "react";

export interface MobileTerminalViewProps {
  ws: WebSocket | null;
  activeTaskId?: string | null;
  activeWorkspace?: string | null;
  onSelectTask?: (taskId: string) => void;
  onRunCommand?: (command: string, args: string[]) => void;
}

interface StreamChunk {
  id: string;
  stream: "stdout" | "stderr" | "system";
  text: string;
  timestamp: string;
}

export default function MobileTerminalView({
  ws,
  activeTaskId = null,
  activeWorkspace = null,
  onRunCommand,
}: MobileTerminalViewProps) {
  const [chunks, setChunks] = useState<StreamChunk[]>([]);
  const [taskStatus, setTaskStatus] = useState<string>("idle");
  const [currentTask, setCurrentTask] = useState<string>("none");
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const displayTask = activeTaskId || currentTask;

  // Listen to WebSocket messages
  useEffect(() => {
    if (!ws) return;

    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "terminal_stream") {
          const newChunk: StreamChunk = {
            id: `chunk_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
            stream: data.stream || "stdout",
            text: data.text || "",
            timestamp: data.timestamp || new Date().toLocaleTimeString(),
          };

          if (data.taskId && data.taskId !== currentTask) {
            setCurrentTask(data.taskId);
          }

          setChunks((prev) => [...prev, newChunk]);
        } else if (data.type === "process_tree_update") {
          if (data.status) {
            setTaskStatus(data.status);
          }
          if (data.taskId) {
            setCurrentTask(data.taskId);
          }
        } else if (data.type === "status") {
          if (data.taskId) {
            setCurrentTask(data.taskId);
            setTaskStatus(data.status || "executing");
          }
          if (data.text) {
            setChunks((prev) => [
              ...prev,
              {
                id: `chunk_sys_${Date.now()}`,
                stream: "system",
                text: `[SYSTEM] ${data.text}\n`,
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          }
        } else if (data.type === "agent_response") {
          setTaskStatus("completed");
        }
      } catch {
        // ignore non-json
      }
    };

    ws.addEventListener("message", handleMessage);
    return () => {
      ws.removeEventListener("message", handleMessage);
    };
  }, [ws, currentTask]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chunks, autoScroll]);

  const handleCopy = () => {
    const fullText = chunks.map((c) => c.text).join("");
    navigator.clipboard.writeText(fullText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleClear = () => {
    setChunks([]);
  };

  // Helper to colorize ANSI or plain text
  const renderFormattedText = (text: string, stream: string) => {
    // Strip raw ANSI escape sequences for mobile display while retaining color cues
    const cleaned = text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");
    const color =
      stream === "stderr"
        ? "#f87171"
        : stream === "system"
        ? "#fbbf24"
        : "#38bdf8";

    return (
      <span style={{ color, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
        {cleaned}
      </span>
    );
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        backgroundColor: "#070a12",
        color: "#f8fafc",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: "12px",
        overflow: "hidden",
      }}
    >
      {/* Mobile Terminal Top Control Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 12px",
          background: "rgba(15, 23, 42, 0.9)",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", overflow: "hidden" }}>
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              backgroundColor:
                taskStatus === "running"
                  ? "#06b6d4"
                  : taskStatus === "completed"
                  ? "#10b981"
                  : "#64748b",
              boxShadow:
                taskStatus === "running" ? "0 0 8px #06b6d4" : "none",
            }}
          />
          <span style={{ fontWeight: 600, fontSize: "11px", color: "#94a3b8" }}>
            TASK:
          </span>
          <span
            style={{
              fontWeight: 500,
              fontSize: "11px",
              color: "#38bdf8",
              textOverflow: "ellipsis",
              overflow: "hidden",
              whiteSpace: "nowrap",
              maxWidth: "110px",
            }}
          >
            {displayTask}
          </span>
          {activeWorkspace && (
            <span
              style={{
                fontSize: "9px",
                padding: "2px 6px",
                borderRadius: "4px",
                background: "rgba(16, 185, 129, 0.15)",
                color: "#10b981",
                fontFamily: "var(--font-mono)",
              }}
            >
              VM: {activeWorkspace.slice(0, 8)}
            </span>
          )}
          <span
            style={{
              fontSize: "9px",
              padding: "2px 6px",
              borderRadius: "4px",
              background:
                taskStatus === "running"
                  ? "rgba(6, 182, 212, 0.2)"
                  : "rgba(255, 255, 255, 0.05)",
              color: taskStatus === "running" ? "#06b6d4" : "#94a3b8",
              textTransform: "uppercase",
              fontWeight: 700,
            }}
          >
            {taskStatus}
          </span>
        </div>

        {/* Action Buttons */}
        <div style={{ display: "flex", gap: "6px" }}>
          <button
            type="button"
            onClick={() => setAutoScroll(!autoScroll)}
            style={{
              padding: "4px 8px",
              borderRadius: "4px",
              fontSize: "10px",
              background: autoScroll ? "rgba(56, 189, 248, 0.2)" : "rgba(255, 255, 255, 0.05)",
              color: autoScroll ? "#38bdf8" : "#64748b",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              cursor: "pointer",
            }}
            title="Auto-scroll toggle"
          >
            {autoScroll ? "⬇ Follow" : "⏸ Pause"}
          </button>
          <button
            type="button"
            onClick={handleCopy}
            style={{
              padding: "4px 8px",
              borderRadius: "4px",
              fontSize: "10px",
              background: "rgba(255, 255, 255, 0.05)",
              color: copied ? "#10b981" : "#cbd5e1",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              cursor: "pointer",
            }}
          >
            {copied ? "✓ Copied" : "📋 Copy"}
          </button>
          <button
            type="button"
            onClick={handleClear}
            style={{
              padding: "4px 8px",
              borderRadius: "4px",
              fontSize: "10px",
              background: "rgba(244, 63, 94, 0.1)",
              color: "#f43f5e",
              border: "1px solid rgba(244, 63, 94, 0.2)",
              cursor: "pointer",
            }}
          >
            Clear
          </button>
        </div>
      </div>

      {/* Quick Mobile Action Bar */}
      {onRunCommand && (
        <div
          style={{
            display: "flex",
            gap: "6px",
            padding: "6px 12px",
            background: "rgba(10, 15, 26, 0.7)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.04)",
            overflowX: "auto",
            flexShrink: 0,
          }}
        >
          <button
            type="button"
            onClick={() => onRunCommand("uname", ["-a"])}
            style={{
              padding: "3px 8px",
              borderRadius: "4px",
              fontSize: "10px",
              background: "rgba(6, 182, 212, 0.12)",
              color: "#06b6d4",
              border: "1px solid rgba(6, 182, 212, 0.3)",
              whiteSpace: "nowrap",
              cursor: "pointer",
            }}
          >
            🐉 uname -a
          </button>
          <button
            type="button"
            onClick={() => onRunCommand("whoami", [])}
            style={{
              padding: "3px 8px",
              borderRadius: "4px",
              fontSize: "10px",
              background: "rgba(16, 185, 129, 0.12)",
              color: "#10b981",
              border: "1px solid rgba(16, 185, 129, 0.3)",
              whiteSpace: "nowrap",
              cursor: "pointer",
            }}
          >
            🐉 whoami
          </button>
          <button
            type="button"
            onClick={() => onRunCommand("ip", ["-brief", "address"])}
            style={{
              padding: "3px 8px",
              borderRadius: "4px",
              fontSize: "10px",
              background: "rgba(139, 92, 246, 0.12)",
              color: "#a78bfa",
              border: "1px solid rgba(139, 92, 246, 0.3)",
              whiteSpace: "nowrap",
              cursor: "pointer",
            }}
          >
            🐉 ip address
          </button>
        </div>
      )}

      {/* Main Read-Only Terminal Stream Body */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          padding: "12px",
          overflowY: "auto",
          WebkitOverflowScrolling: "touch",
          lineHeight: "1.4",
        }}
      >
        {chunks.length === 0 ? (
          <div style={{ color: "#475569", paddingTop: "20px", textAlign: "center" }}>
            <div style={{ fontSize: "20px", marginBottom: "8px" }}>🖥️</div>
            <div style={{ fontWeight: 600, color: "#64748b" }}>
              Mobile Read-Only Terminal Stream
            </div>
            <div style={{ fontSize: "11px", marginTop: "4px" }}>
              Waiting for task execution chunks from Kali VM...
            </div>
            <div
              style={{
                marginTop: "16px",
                display: "inline-block",
                padding: "4px 10px",
                borderRadius: "6px",
                background: "rgba(255, 255, 255, 0.03)",
                border: "1px solid rgba(255, 255, 255, 0.06)",
                fontSize: "10px",
                color: "#94a3b8",
              }}
            >
              Touch-optimized · No virtual keyboard interference
            </div>
          </div>
        ) : (
          chunks.map((chunk) => (
            <div key={chunk.id} style={{ marginBottom: "2px" }}>
              {renderFormattedText(chunk.text, chunk.stream)}
            </div>
          ))
        )}
        <div ref={terminalEndRef} />
      </div>

      {/* Mobile Stream Footer */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "4px 12px",
          background: "rgba(15, 23, 42, 0.8)",
          borderTop: "1px solid rgba(255, 255, 255, 0.05)",
          fontSize: "10px",
          color: "#64748b",
          flexShrink: 0,
        }}
      >
        <span>Chunks: {chunks.length}</span>
        <span>Kali Execution Plane (WSL2 / Isolated VM)</span>
      </div>
    </div>
  );
}
