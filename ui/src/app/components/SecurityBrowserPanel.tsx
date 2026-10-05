"use client";
/* eslint-disable @next/next/no-img-element */

import React, { useState, useEffect, useCallback } from "react";

interface CookieInfo {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  http_only?: boolean;
  secure?: boolean;
  same_site?: string;
}

interface ActionStep {
  step_index: number;
  action: string;
  target: string;
  value?: string | null;
  status: string;
  duration_ms: number;
  timestamp: string;
  details?: {
    type?: string;
    severity?: string;
    alert_message?: string;
    [key: string]: unknown;
  };
  evidence_id?: string | null;
  screenshot_path?: string | null;
  screenshot_sha256?: string | null;
  thumbnail_b64?: string | null;
}

interface VisibleState {
  tool_id: string;
  app_name: string;
  is_running: boolean;
  url: string;
  page_title: string;
  status_code: number;
  viewport?: { width: number; height: number };
  security_context?: {
    is_https: boolean;
    headers: Record<string, string>;
    cookies_count: number;
    cookies: CookieInfo[];
    local_storage_keys: string[];
  };
  dom_snapshot?: {
    elements_count: number;
    interactive_elements: InteractiveElement[];
  };
  alerts_captured?: Array<{ type: string; message: string; timestamp?: string }>;
  recent_actions_count?: number;
  findings_count?: number;
  last_screenshot?: {
    evidence_id: string;
    filepath: string;
    sha256: string;
    thumbnail_b64?: string;
    caption?: string;
    width?: number;
    height?: number;
    timestamp?: string;
  } | null;
}

interface SecurityFinding {
  id?: string;
  type?: string;
  severity?: string;
  category?: string;
  target_url?: string;
  target_selector?: string;
  payload?: string;
  alert_triggered?: boolean;
  alert_message?: string;
  reflected_unescaped?: boolean;
  evidence_id?: string;
  screenshot_sha256?: string;
  timestamp?: string;
  issue?: string;
  cwe?: string;
  recommendation?: string;
}

interface InteractiveElement {
  id: string;
  tag: string;
  selector?: string;
  label?: string;
  type?: string;
  value?: string;
  text?: string;
  bounds?: number[];
  unescaped?: boolean;
  vulnerability?: string;
}

interface SecurityBrowserPanelProps {
  ws?: WebSocket | null;
  activeSessionId?: string;
  apiUrl?: string;
}

export default function SecurityBrowserPanel({
  activeSessionId = "browser_session",
  apiUrl = "http://localhost:8000",
}: SecurityBrowserPanelProps) {
  const [state, setState] = useState<VisibleState | null>(null);
  const [history, setHistory] = useState<ActionStep[]>([]);
  const [findings, setFindings] = useState<SecurityFinding[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [activeSubTab, setActiveSubTab] = useState<"history" | "security" | "workflows" | "dom">("history");
  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(null);

  // Workflow Trigger Inputs
  const [xssUrl, setXssUrl] = useState<string>("http://target.local/search.php");
  const [xssSelector, setXssSelector] = useState<string>("input[name='q']");
  const [xssPayload, setXssPayload] = useState<string>("<script>alert('kairo-xss')</script>");

  const [authUrl, setAuthUrl] = useState<string>("http://target.local/login.php");
  const [authUsername, setAuthUsername] = useState<string>("admin");
  const [authPassword, setAuthPassword] = useState<string>("P@ssw0rd2026!");
  const [authSubmitSelector] = useState<string>("button[type='submit']");

  const [navUrlInput, setNavUrlInput] = useState<string>("http://target.local/search.php");
  const [executionMessage, setExecutionMessage] = useState<string | null>(null);

  // Fetch visible state and action history
  const fetchBrowserData = useCallback(async () => {
    try {
      const [stateRes, histRes] = await Promise.all([
        fetch(`${apiUrl}/browser/state`).catch(() => null),
        fetch(`${apiUrl}/browser/history`).catch(() => null),
      ]);

      if (stateRes && stateRes.ok) {
        const s = await stateRes.json();
        setState(s);
      }
      if (histRes && histRes.ok) {
        const h = await histRes.json();
        setHistory(h.history || []);
        setFindings(h.findings || []);
      }
    } catch (err) {
      console.error("Error fetching browser state:", err);
    }
  }, [apiUrl]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchBrowserData();
    }, 10);
    const interval = setInterval(fetchBrowserData, 3000);
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [fetchBrowserData]);

  // Execute discrete or workflow action
  const executeAction = async (payload: Record<string, unknown>) => {
    setLoading(true);
    setExecutionMessage(null);
    try {
      const res = await fetch(`${apiUrl}/browser/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: activeSessionId,
          ...payload,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        setExecutionMessage(`❌ Error: ${data.detail || data.error || "Action failed"}`);
      } else {
        const status = data.status || "success";
        const wf = (payload.workflow as string) || (payload.action as string) || "action";
        setExecutionMessage(`✓ ${wf} completed: ${status.toUpperCase()}`);
        await fetchBrowserData();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setExecutionMessage(`❌ Network error: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCaptureScreenshot = async () => {
    setLoading(true);
    try {
      await fetch(`${apiUrl}/browser/screenshot?caption=Manual+Visual+Capture`, { method: "POST" });
      await fetchBrowserData();
      setExecutionMessage("✓ Visual Evidence screenshot captured & SHA-256 registered");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setExecutionMessage(`❌ Screenshot failed: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const handleStopBrowser = async () => {
    setLoading(true);
    try {
      await fetch(`${apiUrl}/browser/stop`, { method: "POST" });
      await fetchBrowserData();
      setExecutionMessage("Session closed");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setExecutionMessage(`❌ Stop failed: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const isHttps = state?.url?.startsWith("https://") || state?.security_context?.is_https;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--card-bg, #0f172a)",
        color: "var(--text-primary, #f1f5f9)",
        fontFamily: "var(--font-mono, monospace)",
        fontSize: "13px",
        overflow: "hidden",
      }}
    >
      {/* Top Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "10px 14px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
          background: "rgba(15, 23, 42, 0.95)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "16px" }}>🌐</span>
          <div>
            <div style={{ fontWeight: "bold", color: "var(--accent-cyan, #06b6d4)", fontSize: "14px" }}>
              Security Testing Browser (Playwright / DAST)
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-muted, #94a3b8)" }}>
              First-class observable actions with SHA-256 Visual Evidence provenance
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              padding: "2px 8px",
              borderRadius: "4px",
              fontSize: "11px",
              fontWeight: 600,
              background: state?.is_running ? "rgba(16, 185, 129, 0.2)" : "rgba(148, 163, 184, 0.15)",
              color: state?.is_running ? "var(--accent-emerald, #10b981)" : "#94a3b8",
              border: `1px solid ${state?.is_running ? "rgba(16, 185, 129, 0.4)" : "rgba(148, 163, 184, 0.3)"}`,
            }}
          >
            {state?.is_running ? "● ACTIVE SESSION" : "○ STOPPED"}
          </span>

          <button
            onClick={fetchBrowserData}
            style={{
              padding: "4px 8px",
              background: "rgba(255, 255, 255, 0.05)",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              borderRadius: "4px",
              color: "#f1f5f9",
              cursor: "pointer",
              fontSize: "11px",
            }}
            title="Refresh Browser State"
          >
            🔄
          </button>

          <button
            onClick={handleCaptureScreenshot}
            disabled={loading}
            style={{
              padding: "4px 10px",
              background: "rgba(6, 182, 212, 0.15)",
              border: "1px solid var(--accent-cyan, #06b6d4)",
              borderRadius: "4px",
              color: "var(--accent-cyan, #06b6d4)",
              cursor: "pointer",
              fontSize: "11px",
              fontWeight: 600,
            }}
          >
            📸 Capture Evidence
          </button>

          {state?.is_running && (
            <button
              onClick={handleStopBrowser}
              disabled={loading}
              style={{
                padding: "4px 8px",
                background: "rgba(244, 63, 94, 0.15)",
                border: "1px solid var(--accent-rose, #f43f5e)",
                borderRadius: "4px",
                color: "var(--accent-rose, #f43f5e)",
                cursor: "pointer",
                fontSize: "11px",
              }}
            >
              Stop
            </button>
          )}
        </div>
      </div>

      {/* Address Bar & Visible State Strip */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "8px 14px",
          background: "rgba(30, 41, 59, 0.8)",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        }}
      >
        <span style={{ fontSize: "14px" }} title={isHttps ? "Secure SSL/TLS" : "Insecure HTTP"}>
          {isHttps ? "🔒" : "⚠️"}
        </span>

        <input
          type="text"
          value={navUrlInput}
          onChange={(e) => setNavUrlInput(e.target.value)}
          placeholder="http://target.local/..."
          style={{
            flex: 1,
            padding: "5px 10px",
            background: "#090d16",
            border: "1px solid rgba(255, 255, 255, 0.15)",
            borderRadius: "4px",
            color: "#38bdf8",
            fontFamily: "inherit",
            fontSize: "12px",
          }}
        />

        <button
          onClick={() => executeAction({ action: "navigate", url: navUrlInput })}
          disabled={loading}
          style={{
            padding: "5px 12px",
            background: "rgba(37, 99, 235, 0.25)",
            border: "1px solid rgba(59, 130, 246, 0.5)",
            borderRadius: "4px",
            color: "#60a5fa",
            cursor: "pointer",
            fontWeight: "bold",
            fontSize: "12px",
          }}
        >
          Go
        </button>

        <span
          style={{
            padding: "3px 8px",
            borderRadius: "4px",
            fontSize: "11px",
            fontWeight: "bold",
            background: state?.status_code === 200 ? "rgba(16, 185, 129, 0.15)" : "rgba(239, 68, 68, 0.15)",
            color: state?.status_code === 200 ? "#10b981" : "#ef4444",
            border: `1px solid ${state?.status_code === 200 ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
          }}
        >
          HTTP {state?.status_code || 200}
        </span>

        <span
          style={{
            maxWidth: "200px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            color: "var(--text-muted, #94a3b8)",
            fontSize: "11px",
          }}
          title={state?.page_title}
        >
          {state?.page_title || "Blank Page"}
        </span>
      </div>

      {/* Execution Feedback Banner */}
      {executionMessage && (
        <div
          style={{
            padding: "6px 14px",
            fontSize: "12px",
            background: executionMessage.startsWith("❌")
              ? "rgba(244, 63, 94, 0.15)"
              : "rgba(16, 185, 129, 0.15)",
            color: executionMessage.startsWith("❌") ? "#fb7185" : "#34d399",
            borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
          }}
        >
          {executionMessage}
        </div>
      )}

      {/* Sub-tab Navigation */}
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          background: "rgba(15, 23, 42, 0.6)",
        }}
      >
        <button
          onClick={() => setActiveSubTab("history")}
          style={{
            padding: "8px 16px",
            background: activeSubTab === "history" ? "rgba(6, 182, 212, 0.15)" : "transparent",
            color: activeSubTab === "history" ? "var(--accent-cyan, #06b6d4)" : "var(--text-muted, #94a3b8)",
            border: "none",
            borderBottom: activeSubTab === "history" ? "2px solid var(--accent-cyan, #06b6d4)" : "none",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "12px",
          }}
        >
          ⚡ Action History ({history.length})
        </button>

        <button
          onClick={() => setActiveSubTab("workflows")}
          style={{
            padding: "8px 16px",
            background: activeSubTab === "workflows" ? "rgba(6, 182, 212, 0.15)" : "transparent",
            color: activeSubTab === "workflows" ? "var(--accent-cyan, #06b6d4)" : "var(--text-muted, #94a3b8)",
            border: "none",
            borderBottom: activeSubTab === "workflows" ? "2px solid var(--accent-cyan, #06b6d4)" : "none",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "12px",
          }}
        >
          🎯 Security Workflows
        </button>

        <button
          onClick={() => setActiveSubTab("security")}
          style={{
            padding: "8px 16px",
            background: activeSubTab === "security" ? "rgba(6, 182, 212, 0.15)" : "transparent",
            color: activeSubTab === "security" ? "var(--accent-cyan, #06b6d4)" : "var(--text-muted, #94a3b8)",
            border: "none",
            borderBottom: activeSubTab === "security" ? "2px solid var(--accent-cyan, #06b6d4)" : "none",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "12px",
          }}
        >
          🛡️ Security Context ({state?.security_context?.cookies_count || 0} Cookies)
        </button>

        <button
          onClick={() => setActiveSubTab("dom")}
          style={{
            padding: "8px 16px",
            background: activeSubTab === "dom" ? "rgba(6, 182, 212, 0.15)" : "transparent",
            color: activeSubTab === "dom" ? "var(--accent-cyan, #06b6d4)" : "var(--text-muted, #94a3b8)",
            border: "none",
            borderBottom: activeSubTab === "dom" ? "2px solid var(--accent-cyan, #06b6d4)" : "none",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "12px",
          }}
        >
          🌲 DOM Snapshot ({state?.dom_snapshot?.elements_count || 0} Elements)
        </button>
      </div>

      {/* Main Content Area: Split View (Left: Tab Panel, Right: Live Visual Evidence) */}
      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* Left: Tab Panel */}
        <div style={{ flex: 1, overflowY: "auto", padding: "14px", borderRight: "1px solid rgba(255, 255, 255, 0.08)" }}>
          {/* Sub-tab 1: Action History */}
          {activeSubTab === "history" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "14px", color: "var(--accent-cyan, #06b6d4)" }}>
                    Activity Rail Action History
                  </h3>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>
                    Sequential audit trail showing discrete browser actions, payloads, and linked evidence.
                  </div>
                </div>
                {findings.length > 0 && (
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: "4px",
                      fontSize: "11px",
                      fontWeight: "bold",
                      background: "rgba(239, 68, 68, 0.2)",
                      color: "#ef4444",
                      border: "1px solid rgba(239, 68, 68, 0.4)",
                    }}
                  >
                    ⚠️ {findings.length} Vulnerabilities Detected
                  </span>
                )}
              </div>

              {history.length === 0 ? (
                <div style={{ textAlign: "center", padding: "40px 20px", color: "#64748b" }}>
                  <p>No browser actions recorded yet.</p>
                  <p style={{ fontSize: "12px" }}>
                    Select the <strong>&quot;Security Workflows&quot;</strong> tab to launch an automated XSS check or auth walkthrough.
                  </p>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {history.map((step) => {
                    const isVuln = step.status === "vulnerability_detected";
                    const isErr = step.status === "error";
                    return (
                      <div
                        key={step.step_index}
                        style={{
                          background: isVuln
                            ? "rgba(239, 68, 68, 0.08)"
                            : "rgba(30, 41, 59, 0.5)",
                          border: `1px solid ${
                            isVuln
                              ? "rgba(239, 68, 68, 0.4)"
                              : isErr
                              ? "rgba(244, 63, 94, 0.4)"
                              : "rgba(255, 255, 255, 0.08)"
                          }`,
                          borderRadius: "6px",
                          padding: "10px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span
                              style={{
                                padding: "2px 6px",
                                borderRadius: "3px",
                                fontSize: "10px",
                                fontWeight: "bold",
                                background: "rgba(255, 255, 255, 0.1)",
                                color: "#94a3b8",
                              }}
                            >
                              STEP #{step.step_index}
                            </span>
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: "rgba(6, 182, 212, 0.15)",
                                color: "#38bdf8",
                              }}
                            >
                              {step.action.toUpperCase()}
                            </span>
                            <span style={{ fontSize: "11px", color: "#64748b" }}>
                              {step.duration_ms}ms • {step.timestamp.split("T")[1]?.slice(0, 8)}
                            </span>
                          </div>

                          <span
                            style={{
                              padding: "2px 8px",
                              borderRadius: "4px",
                              fontSize: "10px",
                              fontWeight: "bold",
                              background: isVuln
                                ? "rgba(239, 68, 68, 0.25)"
                                : isErr
                                ? "rgba(244, 63, 94, 0.25)"
                                : "rgba(16, 185, 129, 0.15)",
                              color: isVuln ? "#f87171" : isErr ? "#fb7185" : "#34d399",
                            }}
                          >
                            {step.status.toUpperCase()}
                          </span>
                        </div>

                        {/* Target & Value */}
                        <div style={{ fontSize: "12px", marginBottom: "4px", wordBreak: "break-all" }}>
                          <span style={{ color: "#94a3b8" }}>Target: </span>
                          <span style={{ color: "#e2e8f0", fontWeight: 500 }}>{step.target}</span>
                        </div>

                        {step.value && (
                          <div style={{ fontSize: "12px", marginBottom: "6px", wordBreak: "break-all" }}>
                            <span style={{ color: "#94a3b8" }}>Value / Payload: </span>
                            <code style={{ background: "#090d16", padding: "1px 5px", borderRadius: "3px", color: isVuln ? "#fbbf24" : "#a7f3d0" }}>
                              {step.value}
                            </code>
                          </div>
                        )}

                        {/* Finding / Details Callout */}
                        {isVuln && step.details?.type && (
                          <div
                            style={{
                              marginTop: "6px",
                              padding: "6px 8px",
                              background: "rgba(239, 68, 68, 0.15)",
                              borderRadius: "4px",
                              fontSize: "11px",
                              color: "#fca5a5",
                            }}
                          >
                            🚨 <strong>{step.details.type} ({step.details.severity})</strong>: {step.details.alert_message ? `Triggered alert('${step.details.alert_message}')` : "Unescaped payload reflected in DOM."}
                          </div>
                        )}

                        {/* Linked Visual Evidence Preview */}
                        {step.thumbnail_b64 && (
                          <div style={{ marginTop: "8px", display: "flex", alignItems: "center", gap: "10px" }}>
                            <img
                              src={step.thumbnail_b64}
                              alt="Step Evidence"
                              onClick={() => setSelectedScreenshot(step.thumbnail_b64 || null)}
                              style={{
                                width: "90px",
                                height: "55px",
                                objectFit: "cover",
                                borderRadius: "4px",
                                border: "1px solid rgba(255, 255, 255, 0.2)",
                                cursor: "pointer",
                              }}
                              title="Click to expand Visual Evidence"
                            />
                            <div style={{ fontSize: "11px" }}>
                              <div style={{ color: "var(--accent-cyan, #06b6d4)", fontWeight: 500 }}>
                                📸 Visual Evidence
                              </div>
                              <div style={{ color: "#64748b", fontFamily: "monospace", fontSize: "10px" }}>
                                SHA: {step.screenshot_sha256?.slice(0, 16)}...
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Sub-tab 2: Security Workflows */}
          {activeSubTab === "workflows" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* XSS Check Workflow Card */}
              <div
                style={{
                  background: "rgba(30, 41, 59, 0.6)",
                  border: "1px solid rgba(255, 255, 255, 0.1)",
                  borderRadius: "6px",
                  padding: "14px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                  <span style={{ fontSize: "16px" }}>🧪</span>
                  <h4 style={{ margin: 0, fontSize: "13px", color: "var(--accent-cyan, #06b6d4)" }}>
                    Manual-Trigger XSS Security Check
                  </h4>
                </div>
                <p style={{ margin: "0 0 12px 0", fontSize: "11px", color: "#94a3b8" }}>
                  Injects an XSS payload into the target form or parameter, attaches an alert dialog listener, verifies execution, and captures visual proof.
                </p>

                <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "12px" }}>
                  <div>
                    <label style={{ fontSize: "11px", color: "#94a3b8" }}>Target URL:</label>
                    <input
                      type="text"
                      value={xssUrl}
                      onChange={(e) => setXssUrl(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        color: "#f1f5f9",
                        fontSize: "12px",
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "#94a3b8" }}>Input Selector:</label>
                    <input
                      type="text"
                      value={xssSelector}
                      onChange={(e) => setXssSelector(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        color: "#f1f5f9",
                        fontSize: "12px",
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "#94a3b8" }}>Payload:</label>
                    <input
                      type="text"
                      value={xssPayload}
                      onChange={(e) => setXssPayload(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        color: "#fbbf24",
                        fontSize: "12px",
                      }}
                    />
                  </div>
                </div>

                <button
                  onClick={() =>
                    executeAction({
                      action: "workflow",
                      workflow: "xss_check",
                      params: {
                        url: xssUrl,
                        selector: xssSelector,
                        payload: xssPayload,
                      },
                    })
                  }
                  disabled={loading}
                  style={{
                    padding: "6px 14px",
                    background: "rgba(239, 68, 68, 0.2)",
                    border: "1px solid var(--accent-rose, #f43f5e)",
                    borderRadius: "4px",
                    color: "#fca5a5",
                    cursor: "pointer",
                    fontWeight: "bold",
                    fontSize: "12px",
                  }}
                >
                  ⚡ Run XSS Reflection & Alert Check
                </button>
              </div>

              {/* Auth Flow Walkthrough Card */}
              <div
                style={{
                  background: "rgba(30, 41, 59, 0.6)",
                  border: "1px solid rgba(255, 255, 255, 0.1)",
                  borderRadius: "6px",
                  padding: "14px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                  <span style={{ fontSize: "16px" }}>🔑</span>
                  <h4 style={{ margin: 0, fontSize: "13px", color: "var(--accent-emerald, #10b981)" }}>
                    Authentication Flow Walkthrough
                  </h4>
                </div>
                <p style={{ margin: "0 0 12px 0", fontSize: "11px", color: "#94a3b8" }}>
                  Automates credential entry, form submission, redirects, and session cookie issuance inspection.
                </p>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "12px" }}>
                  <div style={{ gridColumn: "span 2" }}>
                    <label style={{ fontSize: "11px", color: "#94a3b8" }}>Login URL:</label>
                    <input
                      type="text"
                      value={authUrl}
                      onChange={(e) => setAuthUrl(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        color: "#f1f5f9",
                        fontSize: "12px",
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "#94a3b8" }}>Username:</label>
                    <input
                      type="text"
                      value={authUsername}
                      onChange={(e) => setAuthUsername(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        color: "#f1f5f9",
                        fontSize: "12px",
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "#94a3b8" }}>Password:</label>
                    <input
                      type="password"
                      value={authPassword}
                      onChange={(e) => setAuthPassword(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        color: "#f1f5f9",
                        fontSize: "12px",
                      }}
                    />
                  </div>
                </div>

                <button
                  onClick={() =>
                    executeAction({
                      action: "workflow",
                      workflow: "auth_walkthrough",
                      params: {
                        login_url: authUrl,
                        username: authUsername,
                        password: authPassword,
                        submit_selector: authSubmitSelector,
                      },
                    })
                  }
                  disabled={loading}
                  style={{
                    padding: "6px 14px",
                    background: "rgba(16, 185, 129, 0.2)",
                    border: "1px solid var(--accent-emerald, #10b981)",
                    borderRadius: "4px",
                    color: "#6ee7b7",
                    cursor: "pointer",
                    fontWeight: "bold",
                    fontSize: "12px",
                  }}
                >
                  ⚡ Run Auth Walkthrough
                </button>
              </div>

              {/* Cookie & DOM Audits */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <button
                  onClick={() => executeAction({ action: "workflow", workflow: "cookie_audit" })}
                  disabled={loading}
                  style={{
                    padding: "10px",
                    background: "rgba(245, 158, 11, 0.15)",
                    border: "1px solid rgba(245, 158, 11, 0.4)",
                    borderRadius: "6px",
                    color: "#fcd34d",
                    cursor: "pointer",
                    fontWeight: "bold",
                    fontSize: "12px",
                  }}
                >
                  🍪 Audit Cookie Security Flags
                </button>

                <button
                  onClick={() => executeAction({ action: "workflow", workflow: "dom_audit" })}
                  disabled={loading}
                  style={{
                    padding: "10px",
                    background: "rgba(139, 92, 246, 0.15)",
                    border: "1px solid rgba(139, 92, 246, 0.4)",
                    borderRadius: "6px",
                    color: "#c4b5fd",
                    cursor: "pointer",
                    fontWeight: "bold",
                    fontSize: "12px",
                  }}
                >
                  🌲 Audit DOM Sinks & CSRF
                </button>
              </div>
            </div>
          )}

          {/* Sub-tab 3: Security Context & Cookies */}
          {activeSubTab === "security" && (
            <div>
              <h4 style={{ margin: "0 0 10px 0", fontSize: "13px", color: "var(--accent-cyan, #06b6d4)" }}>
                Active Session Cookies & Security Flags
              </h4>
              {(!state?.security_context?.cookies || state.security_context.cookies.length === 0) ? (
                <p style={{ color: "#64748b" }}>No cookies captured for current origin.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {state.security_context.cookies.map((c, i) => (
                    <div
                      key={i}
                      style={{
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.1)",
                        borderRadius: "4px",
                        padding: "8px 12px",
                        fontSize: "12px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: "bold", color: "#38bdf8" }}>{c.name}</span>
                        <div style={{ display: "flex", gap: "6px" }}>
                          <span
                            style={{
                              padding: "1px 6px",
                              borderRadius: "3px",
                              fontSize: "10px",
                              fontWeight: "bold",
                              background: c.http_only ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)",
                              color: c.http_only ? "#34d399" : "#f87171",
                            }}
                          >
                            HttpOnly: {c.http_only ? "YES" : "NO"}
                          </span>
                          <span
                            style={{
                              padding: "1px 6px",
                              borderRadius: "3px",
                              fontSize: "10px",
                              fontWeight: "bold",
                              background: c.secure ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)",
                              color: c.secure ? "#34d399" : "#f87171",
                            }}
                          >
                            Secure: {c.secure ? "YES" : "NO"}
                          </span>
                          <span
                            style={{
                              padding: "1px 6px",
                              borderRadius: "3px",
                              fontSize: "10px",
                              fontWeight: "bold",
                              background: "rgba(245, 158, 11, 0.2)",
                              color: "#fcd34d",
                            }}
                          >
                            SameSite: {c.same_site || "Lax"}
                          </span>
                        </div>
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px", wordBreak: "break-all" }}>
                        Value: {c.value}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Alert Dialogs Log */}
              {state?.alerts_captured && state.alerts_captured.length > 0 && (
                <div style={{ marginTop: "16px" }}>
                  <h4 style={{ margin: "0 0 10px 0", fontSize: "13px", color: "#fbbf24" }}>
                    ⚠️ Captured Alert Dialogs (DOM Injections)
                  </h4>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {state.alerts_captured.map((a, i) => (
                      <div
                        key={i}
                        style={{
                          background: "rgba(245, 158, 11, 0.1)",
                          border: "1px solid rgba(245, 158, 11, 0.3)",
                          borderRadius: "4px",
                          padding: "6px 10px",
                          fontSize: "11px",
                          color: "#fde68a",
                        }}
                      >
                        [Dialog: {a.type.toUpperCase()}] &quot;{a.message}&quot;
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Sub-tab 4: DOM Elements */}
          {activeSubTab === "dom" && (
            <div>
              <h4 style={{ margin: "0 0 10px 0", fontSize: "13px", color: "var(--accent-cyan, #06b6d4)" }}>
                Active Interactive DOM Tree
              </h4>
              {(!state?.dom_snapshot?.interactive_elements || state.dom_snapshot.interactive_elements.length === 0) ? (
                <p style={{ color: "#64748b" }}>No DOM elements extracted.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  {state.dom_snapshot.interactive_elements.map((el, i) => (
                    <div
                      key={i}
                      style={{
                        background: "#090d16",
                        border: "1px solid rgba(255, 255, 255, 0.08)",
                        borderRadius: "4px",
                        padding: "6px 10px",
                        fontSize: "11px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: "#38bdf8", fontWeight: "bold" }}>
                          &lt;{el.tag} id=&quot;{el.id}&quot;&gt;
                        </span>
                        <span style={{ color: "#64748b" }}>
                          {el.bounds ? `[${el.bounds.join(", ")}]` : ""}
                        </span>
                      </div>
                      {el.selector && (
                        <div style={{ color: "#94a3b8", fontSize: "10px" }}>Selector: {el.selector}</div>
                      )}
                      {(el.value || el.text) && (
                        <div style={{ color: "#cbd5e1", marginTop: "2px" }}>
                          Content: &quot;{el.value || el.text}&quot;
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Live Visual Evidence Screenshot Card */}
        <div
          style={{
            width: "380px",
            background: "#090d16",
            padding: "14px",
            display: "flex",
            flexDirection: "column",
            gap: "10px",
            overflowY: "auto",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: "bold", fontSize: "13px", color: "var(--accent-cyan, #06b6d4)" }}>
              🖼️ Latest Visual Evidence
            </span>
            <span style={{ fontSize: "10px", color: "#64748b" }}>
              {state?.viewport?.width || 1280}x{state?.viewport?.height || 800}
            </span>
          </div>

          {state?.last_screenshot?.thumbnail_b64 ? (
            <div>
              <div
                style={{
                  position: "relative",
                  borderRadius: "6px",
                  overflow: "hidden",
                  border: "1px solid rgba(255, 255, 255, 0.15)",
                  cursor: "pointer",
                }}
                onClick={() => setSelectedScreenshot(state.last_screenshot?.thumbnail_b64 || null)}
                title="Click to view full Visual Evidence frame"
              >
                <img
                  src={state.last_screenshot.thumbnail_b64}
                  alt="Visual Evidence Frame"
                  style={{ width: "100%", height: "auto", display: "block" }}
                />
              </div>

              <div style={{ marginTop: "8px", fontSize: "11px", display: "flex", flexDirection: "column", gap: "4px" }}>
                <div style={{ color: "#e2e8f0", fontWeight: 500 }}>
                  {state.last_screenshot.caption || "Screenshot"}
                </div>
                <div style={{ color: "#64748b", fontFamily: "monospace", fontSize: "10px", wordBreak: "break-all" }}>
                  SHA-256: {state.last_screenshot.sha256}
                </div>
              </div>
            </div>
          ) : (
            <div
              style={{
                height: "180px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                border: "1px dashed rgba(255, 255, 255, 0.15)",
                borderRadius: "6px",
                color: "#64748b",
                fontSize: "12px",
              }}
            >
              <span>No Visual Evidence captured</span>
              <button
                onClick={handleCaptureScreenshot}
                style={{
                  marginTop: "8px",
                  padding: "4px 10px",
                  background: "rgba(6, 182, 212, 0.15)",
                  border: "1px solid var(--accent-cyan, #06b6d4)",
                  borderRadius: "4px",
                  color: "var(--accent-cyan, #06b6d4)",
                  cursor: "pointer",
                  fontSize: "11px",
                }}
              >
                📸 Capture Now
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Expanded Screenshot Modal */}
      {selectedScreenshot && (
        <div
          onClick={() => setSelectedScreenshot(null)}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.85)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: "20px",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "relative",
              maxWidth: "90vw",
              maxHeight: "90vh",
              background: "#0f172a",
              border: "1px solid rgba(255, 255, 255, 0.2)",
              borderRadius: "8px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "8px 14px",
                background: "#1e293b",
                borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
              }}
            >
              <span style={{ fontWeight: "bold", color: "#38bdf8" }}>
                Visual Evidence Frame (Cryptographic Provenance)
              </span>
              <button
                onClick={() => setSelectedScreenshot(null)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#94a3b8",
                  fontSize: "16px",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>
            <img
              src={selectedScreenshot}
              alt="Expanded Evidence"
              style={{ maxWidth: "100%", maxHeight: "calc(90vh - 50px)", display: "block" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
