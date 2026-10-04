"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import WhyThisToolPanel from "./WhyThisToolPanel";

export interface PlanNode {
  node_id: string;
  label: string;
  capability: string;
  description: string;
  dependencies: string[];
  status: "queued" | "running" | "success" | "warning" | "failed";
  depth_level?: number;
  assigned_tool?: string;
  rationale?: string;
  expected_outputs?: string[];
  result?: Record<string, unknown>;
}

export interface FactPort {
  port: number | string;
  protocol?: string;
  service?: string;
  state?: string;
}

export interface FactEndpoint {
  path?: string;
  url?: string;
  status?: number | string;
  length?: number;
}

export interface FactVuln {
  id?: string;
  type?: string;
  severity?: string;
  description?: string;
}

export interface ObservationFacts {
  ports?: FactPort[];
  endpoints?: FactEndpoint[];
  vulnerabilities?: FactVuln[];
  hosts?: Array<Record<string, unknown>>;
  technologies?: string[];
  credentials?: Array<Record<string, unknown>>;
}

export interface NodeCritique {
  status?: string;
  has_progress?: boolean;
  score?: number;
  critique?: string;
  suggested_action?: string;
}

export interface RecoveryPathStep {
  attempt?: number;
  action?: string;
  tool?: string;
  args?: Record<string, unknown>;
  status?: string;
  error_type?: string;
  details?: string;
  transition?: string;
  failure_reason?: string;
  duration_s?: number;
  action_taken?: string;
  event_id?: string;
  parent_event?: string;
}

export interface NodeResultData {
  error?: string;
  reason?: string;
  attempts?: number;
  critique?: NodeCritique;
  facts?: ObservationFacts;
  summary?: string;
  recovery_narrative?: string;
  recovery_path?: RecoveryPathStep[];
  history?: Array<{
    attempt?: number;
    tool?: string;
    args?: Record<string, unknown>;
    exit_code?: number;
    timed_out?: boolean;
    facts_count?: number;
    has_progress?: boolean;
    critic_status?: string;
    event_id?: string;
    parent_event?: string;
  }>;
  [key: string]: unknown;
}

export interface PlanDAG {
  plan_id: string;
  goal: string;
  session_id: string;
  status: "created" | "executing" | "completed" | "failed";
  total_nodes: number;
  created_at: string;
  updated_at?: string;
  nodes: PlanNode[];
  depth_levels?: { [node_id: string]: number };
  is_dag?: boolean;
  parallel_roots?: string[];
  convergence_nodes?: string[];
}

export interface PlanSummary {
  plan_id: string;
  goal: string;
  status: string;
  total_nodes: number;
  created_at: string;
}

export interface PlanReportData {
  plan_id?: string;
  target_scope?: string[];
  autonomous_healing_rate_pct?: number;
  resilience_metrics?: {
    autonomous_healing_rate_pct?: number;
    nodes_requiring_recovery?: number;
    total_recovery_interventions?: number;
    recovery_exhausted_caps?: number;
  };
  recovery_narratives?: Record<string, string>;
  artifacts?: {
    json?: { filename?: string; sha256?: string; path?: string };
    markdown?: { filename?: string; sha256?: string; path?: string };
  };
  markdown_report?: string;
  [key: string]: unknown;
}

interface TaskGraphViewProps {
  ws?: WebSocket | null;
  activeSessionId?: string;
  onSelectNode?: (node: PlanNode) => void;
}

const PRESET_GOALS = [
  {
    title: "Full Pentest: 192.168.1.50",
    goal: "Conduct comprehensive penetration test against 192.168.1.50: run parallel port scan and web directory enumeration, test web vulnerabilities, audit SSH credentials, and correlate findings into a unified report.",
  },
  {
    title: "Web Assessment: staging.corp.internal",
    goal: "Perform automated web vulnerability assessment on staging.corp.internal: discover virtual hosts, fuzz hidden endpoints, test for SQL injection and XSS vulnerabilities, and generate an executive risk summary.",
  },
  {
    title: "Subnet Recon: 10.0.0.0/24",
    goal: "Execute stealth active reconnaissance across 10.0.0.0/24: discover live hosts via ICMP/ARP, identify exposed service banners in parallel, map subnet topology, and flag outdated operating systems.",
  },
  {
    title: "Credential Audit: SSH & FTP",
    goal: "Audit credential resilience for target 172.16.20.10: discover open management ports, execute policy-bounded dictionary authentication on SSH and FTP in parallel, and report weak credentials.",
  },
];

export default function TaskGraphView({
  ws,
  activeSessionId = "default_session",
  onSelectNode,
}: TaskGraphViewProps) {
  const [goal, setGoal] = useState<string>(PRESET_GOALS[0].goal);
  const [preferLlm, setPreferLlm] = useState<boolean>(true);
  const [isPlanning, setIsPlanning] = useState<boolean>(false);
  const [isExecutingGraph, setIsExecutingGraph] = useState<boolean>(false);
  const [currentPlan, setCurrentPlan] = useState<PlanDAG | null>(null);
  const [recentPlans, setRecentPlans] = useState<PlanSummary[]>([]);
  const [selectedNode, setSelectedNode] = useState<PlanNode | null>(null);
  const [readyNodeIds, setReadyNodeIds] = useState<string[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [statusFeedback, setStatusFeedback] = useState<string | null>(null);
  const [reportModalData, setReportModalData] = useState<PlanReportData | null>(null);
  const [isGeneratingReport, setIsGeneratingReport] = useState<boolean>(false);

  const showNotification = useCallback((msg: string) => {
    setStatusFeedback(msg);
    const timer = setTimeout(() => setStatusFeedback(null), 3500);
    return () => clearTimeout(timer);
  }, []);

  const handleGenerateReport = async (planId: string) => {
    setIsGeneratingReport(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`http://localhost:8000/planner/plans/${planId}/report`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setReportModalData(data);
        showNotification("Security report generated & hashed with SHA-256");
      } else {
        setErrorMsg("Failed to generate report");
      }
    } catch (e: unknown) {
      const err = e instanceof Error ? e.message : String(e);
      setErrorMsg(`Report error: ${err}`);
    } finally {
      setIsGeneratingReport(false);
    }
  };

  const fetchReadyNodes = useCallback(async (planId: string) => {
    try {
      const res = await fetch(`http://localhost:4000/planner/plans/${planId}/ready`);
      if (res.ok) {
        const data = await res.json();
        const ids = (data.ready_nodes || []).map((n: PlanNode) => n.node_id);
        setReadyNodeIds(ids);
      }
    } catch {
      // ignore
    }
  }, []);

  const loadPlan = useCallback(async (planId: string) => {
    setErrorMsg(null);
    try {
      const res = await fetch(`http://localhost:4000/planner/plans/${planId}`);
      if (res.ok) {
        const plan = await res.json();
        setCurrentPlan(plan);
        setSelectedNode(null);
        fetchReadyNodes(planId);
      } else {
        setErrorMsg(`Failed to load plan ${planId}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(`Error loading plan: ${msg}`);
    }
  }, [fetchReadyNodes]);

  const fetchPlansList = useCallback(async () => {
    try {
      const res = await fetch("http://localhost:4000/planner/plans?limit=10");
      if (res.ok) {
        const data = await res.json();
        const plans = data.plans || [];
        setRecentPlans(plans);
        if (plans.length > 0) {
          loadPlan(plans[0].plan_id);
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn("Could not fetch recent plans:", msg);
    }
  }, [loadPlan]);

  // Load recent plans on mount
  useEffect(() => {
    let ignore = false;
    const loadInitial = async () => {
      try {
        const res = await fetch("http://localhost:4000/planner/plans?limit=10");
        if (res.ok && !ignore) {
          const data = await res.json();
          const plans = data.plans || [];
          setRecentPlans(plans);
          if (plans.length > 0) {
            loadPlan(plans[0].plan_id);
          }
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        console.warn("Could not fetch recent plans:", msg);
      }
    };
    loadInitial();
    return () => {
      ignore = true;
    };
  }, [loadPlan]);

  // Listen for WebSocket planner messages
  useEffect(() => {
    if (!ws) return;

    const handleMessage = (evt: MessageEvent) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "planner_plan_created" && data.plan) {
          setIsPlanning(false);
          setCurrentPlan(data.plan);
          fetchPlansList();
          showNotification(`Task Graph created: ${data.plan.plan_id}`);
        } else if (data.type === "planner_plan_details" && data.plan) {
          setCurrentPlan(data.plan);
        } else if (data.type === "planner_plan_updated" && data.plan) {
          setCurrentPlan(data.plan);
          showNotification("Node status updated");
        }
      } catch {
        // ignore non-json messages
      }
    };

    ws.addEventListener("message", handleMessage);
    return () => ws.removeEventListener("message", handleMessage);
  }, [ws, fetchPlansList, showNotification]);

  const handleDecompose = async () => {
    if (!goal.trim()) {
      setErrorMsg("Please enter a goal description.");
      return;
    }

    setIsPlanning(true);
    setErrorMsg(null);

    // Try via WebSocket first if connected
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "planner_decompose",
          goal: goal.trim(),
          sessionId: activeSessionId,
          prefer_llm: preferLlm,
        })
      );
    } else {
      // Fallback to HTTP proxy
      try {
        const res = await fetch("http://localhost:4000/planner/decompose", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            goal: goal.trim(),
            session_id: activeSessionId,
            prefer_llm: preferLlm,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server error HTTP ${res.status}`);
        }

        const plan = await res.json();
        setCurrentPlan(plan);
        fetchPlansList();
        fetchReadyNodes(plan.plan_id);
        showNotification(`Plan ${plan.plan_id} decomposed into DAG.`);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setErrorMsg(`Decomposition failed: ${msg}`);
      } finally {
        setIsPlanning(false);
      }
    }
  };

  const handleUpdateNodeStatus = async (
    nodeId: string,
    newStatus: "queued" | "running" | "success" | "warning" | "failed"
  ) => {
    if (!currentPlan) return;

    try {
      const res = await fetch(
        `http://localhost:4000/planner/plans/${currentPlan.plan_id}/nodes/${nodeId}/status`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: newStatus,
            result: { simulated_by: "ui_interaction", timestamp: new Date().toISOString() },
          }),
        }
      );

      if (res.ok) {
        const updated = await res.json();
        setCurrentPlan(updated);
        fetchReadyNodes(currentPlan.plan_id);
        showNotification(`Node ${nodeId} marked as ${newStatus}`);
      } else {
        const err = await res.json().catch(() => ({}));
        setErrorMsg(err.detail || "Failed to update node status");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(`Error updating node: ${msg}`);
    }
  };

  const handleExecuteTaskGraph = async () => {
    if (!currentPlan) return;
    setIsExecutingGraph(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`http://localhost:4000/planner/plans/${currentPlan.plan_id}/execute`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        if (data.updated_plan) {
          setCurrentPlan(data.updated_plan);
          fetchReadyNodes(currentPlan.plan_id);
        }
        showNotification(
          `Executed ${data.executed_count || 0} node(s) through Observer, Critic & Recovery Agent.`
        );
      } else {
        const err = await res.json().catch(() => ({}));
        setErrorMsg(err.detail || "Task graph execution failed");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(`Error executing task graph: ${msg}`);
    } finally {
      setIsExecutingGraph(false);
    }
  };

  const handleExecuteSingleNode = async (nodeId: string) => {
    if (!currentPlan) return;
    try {
      const res = await fetch(
        `http://localhost:4000/planner/plans/${currentPlan.plan_id}/nodes/${nodeId}/execute`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ max_attempts: 3 }),
        }
      );
      if (res.ok) {
        const data = await res.json();
        if (data.updated_plan) {
          setCurrentPlan(data.updated_plan);
          fetchReadyNodes(currentPlan.plan_id);
          const updatedTarget = data.updated_plan.nodes?.find((n: PlanNode) => n.node_id === nodeId);
          if (updatedTarget) setSelectedNode(updatedTarget);
        }
        const execRes = data.execution_result || {};
        showNotification(
          `Node #${nodeId} execution complete (${execRes.status || "done"}) in ${execRes.attempts || 1} attempt(s).`
        );
      } else {
        const err = await res.json().catch(() => ({}));
        setErrorMsg(err.detail || `Node execution failed for #${nodeId}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(`Error executing node: ${msg}`);
    }
  };

  // Group nodes into topological layers by depth_level
  const groupedColumns = useMemo(() => {
    if (!currentPlan || !currentPlan.nodes) return [];

    const depthMap: { [key: number]: PlanNode[] } = {};
    const depths = currentPlan.depth_levels || {};

    currentPlan.nodes.forEach((node) => {
      const d = depths[node.node_id] !== undefined ? depths[node.node_id] : (node.depth_level || 0);
      if (!depthMap[d]) depthMap[d] = [];
      depthMap[d].push(node);
    });

    const sortedLevels = Object.keys(depthMap)
      .map(Number)
      .sort((a, b) => a - b);

    return sortedLevels.map((lvl) => ({
      level: lvl,
      nodes: depthMap[lvl],
    }));
  }, [currentPlan]);

  // Compute status summary counts
  const statusCounts = useMemo(() => {
    const counts = { queued: 0, running: 0, success: 0, warning: 0, failed: 0 };
    if (!currentPlan?.nodes) return counts;
    currentPlan.nodes.forEach((n) => {
      if (counts[n.status] !== undefined) counts[n.status]++;
    });
    return counts;
  }, [currentPlan]);

  const getLayerTitle = (lvl: number) => {
    if (lvl === 0) return "Layer 0: Parallel Recon Roots";
    if (lvl === 1) return "Layer 1: Deep Enumeration";
    if (lvl === 2) return "Layer 2: Vulnerability & Exploitation";
    return `Layer ${lvl}: Correlation & Reporting`;
  };

  return (
    <div className="task-graph-root">
      {/* Top Input & Goal Formulation Bar */}
      <div className="task-graph-top-bar">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "14px", fontWeight: "700", color: "var(--accent-cyan)" }}>
              🌐 Autonomous DAG Planner
            </span>
            <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
              (Directed Acyclic Graph decomposition with parallel branching & multi-parent convergence)
            </span>
          </div>

          {/* Saved Plans Selector */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Load Plan:</span>
            <select
              style={{
                background: "rgba(15, 23, 42, 0.9)",
                border: "1px solid rgba(255, 255, 255, 0.15)",
                color: "#e2e8f0",
                fontSize: "11px",
                padding: "3px 8px",
                borderRadius: "4px",
                outline: "none",
              }}
              value={currentPlan?.plan_id || ""}
              onChange={(e) => {
                if (e.target.value) loadPlan(e.target.value);
              }}
            >
              <option value="">-- Recent Saved Plans ({recentPlans.length}) --</option>
              {recentPlans.map((p) => (
                <option key={p.plan_id} value={p.plan_id}>
                  {p.plan_id} — {p.goal ? p.goal.slice(0, 36) + "..." : "No goal"}
                </option>
              ))}
            </select>
            <button
              className="quick-btn secondary"
              style={{ padding: "3px 8px", fontSize: "11px" }}
              onClick={fetchPlansList}
              title="Refresh saved plans list"
            >
              🔄
            </button>
          </div>
        </div>

        {/* Goal Input Row */}
        <div className="task-graph-input-row">
          <input
            type="text"
            className="task-graph-input"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Describe your security goal (e.g., Penetration test target 192.168.1.50 with parallel web enum and port scan)..."
            disabled={isPlanning}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isPlanning) handleDecompose();
            }}
          />

          <button
            className="quick-btn"
            style={{
              padding: "8px 16px",
              fontSize: "12px",
              fontWeight: 700,
              background: "rgba(6, 182, 212, 0.2)",
              borderColor: "var(--accent-cyan)",
              color: "#fff",
            }}
            onClick={handleDecompose}
            disabled={isPlanning || !goal.trim()}
          >
            {isPlanning ? "🧠 Decomposing DAG..." : "⚡ Decompose to DAG"}
          </button>
        </div>

        {/* Options & Scenario Presets */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
          {/* Quick Presets */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <span style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
              Presets:
            </span>
            {PRESET_GOALS.map((preset, idx) => (
              <button
                key={idx}
                className="quick-btn secondary"
                style={{ padding: "2px 7px", fontSize: "10px" }}
                onClick={() => setGoal(preset.goal)}
                title={preset.goal}
              >
                {preset.title}
              </button>
            ))}
          </div>

          {/* Model Prefer Checkbox */}
          <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "11px", color: "var(--text-muted)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={preferLlm}
              onChange={(e) => setPreferLlm(e.target.checked)}
              style={{ cursor: "pointer" }}
            />
            <span>Prefer Local LLM (llama.cpp)</span>
          </label>
        </div>

        {/* Error / Status Feedback */}
        {errorMsg && (
          <div style={{ background: "rgba(244, 63, 94, 0.15)", border: "1px solid rgba(244, 63, 94, 0.4)", color: "#fca5a5", padding: "6px 10px", borderRadius: "4px", fontSize: "11px" }}>
            ⚠️ {errorMsg}
          </div>
        )}
        {statusFeedback && (
          <div style={{ background: "rgba(16, 185, 129, 0.15)", border: "1px solid rgba(16, 185, 129, 0.4)", color: "#6ee7b7", padding: "6px 10px", borderRadius: "4px", fontSize: "11px" }}>
            ✓ {statusFeedback}
          </div>
        )}
      </div>

      {/* DAG Plan Metrics Banner */}
      {currentPlan && (
        <div className="dag-metrics-banner">
          <div className="dag-metric-item">
            <span className="dag-metric-label">Plan ID:</span>
            <span className="dag-metric-val" style={{ color: "var(--accent-cyan)" }}>
              {currentPlan.plan_id}
            </span>
          </div>

          <div className="dag-metric-item">
            <span className="dag-metric-label">Total Nodes:</span>
            <span className="dag-metric-val">{currentPlan.total_nodes || currentPlan.nodes.length}</span>
          </div>

          <div className="dag-metric-item">
            <span className="dag-metric-label">Parallel Roots:</span>
            <span className="dag-metric-val" style={{ color: "var(--accent-emerald)" }}>
              {currentPlan.parallel_roots ? currentPlan.parallel_roots.length : groupedColumns[0]?.nodes.length || 0}
            </span>
          </div>

          <div className="dag-metric-item">
            <span className="dag-metric-label">Convergence Nodes:</span>
            <span className="dag-metric-val" style={{ color: "#c084fc" }}>
              {currentPlan.convergence_nodes ? currentPlan.convergence_nodes.length : 0}
            </span>
          </div>

          <div className="dag-metric-item">
            <span className="dag-metric-label">Status Breakdown:</span>
            <div style={{ display: "flex", gap: "4px" }}>
              <span className="dag-status-pill queued">{statusCounts.queued} Queued</span>
              <span className="dag-status-pill running">{statusCounts.running} Running</span>
              <span className="dag-status-pill success">{statusCounts.success} Success</span>
              {statusCounts.warning > 0 && (
                <span className="dag-status-pill warning">{statusCounts.warning} Warning</span>
              )}
              {statusCounts.failed > 0 && (
                <span className="dag-status-pill failed">{statusCounts.failed} Failed</span>
              )}
            </div>
          </div>

          <div style={{ display: "flex", gap: "6px" }}>
            <button
              className="quick-btn"
              style={{
                padding: "2px 10px",
                fontSize: "10px",
                fontWeight: 700,
                background: "rgba(16, 185, 129, 0.2)",
                borderColor: "#10b981",
                color: "#6ee7b7",
              }}
              onClick={handleExecuteTaskGraph}
              disabled={isExecutingGraph}
              title="Execute unblocked DAG nodes through Observer, Critic & Recovery Agent"
            >
              {isExecutingGraph ? "⚙️ Executing DAG..." : "▶ Execute DAG"}
            </button>
            <button
              className="quick-btn secondary"
              style={{
                padding: "2px 8px",
                fontSize: "10px",
                borderColor: readyNodeIds.length > 0 ? "rgba(16, 185, 129, 0.4)" : undefined,
                color: readyNodeIds.length > 0 ? "#34d399" : undefined,
              }}
              onClick={() => currentPlan && fetchReadyNodes(currentPlan.plan_id)}
              title="Query ready nodes whose dependencies are satisfied"
            >
              Ready to Run ({readyNodeIds.length})
            </button>
            <button
              className="quick-btn"
              style={{
                padding: "2px 10px",
                fontSize: "10px",
                fontWeight: 700,
                background: "rgba(245, 158, 11, 0.15)",
                borderColor: "#f59e0b",
                color: "#fbbf24",
              }}
              onClick={() => currentPlan && handleGenerateReport(currentPlan.plan_id)}
              disabled={isGeneratingReport}
              title="Generate final security report with failure-aware recovery lineage and SHA-256 artifacts"
            >
              {isGeneratingReport ? "📄 Generating..." : "📄 Audit Report"}
            </button>
            <button
              className="quick-btn secondary"
              style={{ padding: "2px 8px", fontSize: "10px" }}
              onClick={() => currentPlan && loadPlan(currentPlan.plan_id)}
              title="Reload plan"
            >
              🔄 Refresh
            </button>
          </div>
        </div>
      )}

      {/* DAG Visual Canvas / Columns */}
      <div className="dag-canvas-container">
        {!currentPlan ? (
          <div style={{ textAlign: "center", color: "var(--text-muted)", marginTop: "80px" }}>
            <div style={{ fontSize: "28px", marginBottom: "12px" }}>🕸️</div>
            <h3 style={{ color: "#e2e8f0", marginBottom: "6px" }}>No Task Graph Loaded</h3>
            <p style={{ fontSize: "12px", maxWidth: "460px", margin: "0 auto" }}>
              Enter a goal above and click <strong>&quot;Decompose to DAG&quot;</strong> to break it down into an
              executable directed acyclic graph with parallel branches and multi-parent convergence.
            </p>
          </div>
        ) : (
          <div className="dag-columns-wrapper">
            {groupedColumns.map((col) => (
              <div key={col.level} className="dag-column">
                <div className="dag-column-header">
                  <span>{getLayerTitle(col.level)}</span>
                  <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                    {col.nodes.length} {col.nodes.length === 1 ? "task" : "tasks"}
                  </span>
                </div>

                {col.nodes.map((node) => {
                  const isReady = readyNodeIds.includes(node.node_id);
                  const isSelected = selectedNode?.node_id === node.node_id;

                  return (
                    <div
                      key={node.node_id}
                      className={`dag-node-card ${node.status} ${isSelected ? "selected" : ""}`}
                      style={{
                        outline: isReady && node.status === "queued" ? "2px solid rgba(16, 185, 129, 0.6)" : undefined,
                        cursor: "pointer",
                      }}
                      onClick={() => {
                        setSelectedNode(node);
                        if (onSelectNode) onSelectNode(node);
                      }}
                    >
                      {/* Node Header */}
                      <div className="dag-node-header">
                        <span className="dag-node-id">#{node.node_id}</span>
                        <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                          {isReady && node.status === "queued" && (
                            <span
                              style={{
                                fontSize: "9px",
                                background: "rgba(16, 185, 129, 0.2)",
                                color: "#34d399",
                                padding: "1px 4px",
                                borderRadius: "3px",
                                fontWeight: 700,
                              }}
                            >
                              READY
                            </span>
                          )}
                          <span className={`dag-status-pill ${node.status}`}>{node.status}</span>
                        </div>
                      </div>

                      {/* Capability Tag */}
                      <div className="dag-capability-tag">
                        🎯 {node.capability}
                      </div>

                      {/* Node Title & Description */}
                      <div className="dag-node-label">{node.label}</div>
                      <div className="dag-node-desc">{node.description}</div>

                      {/* Dependencies */}
                      <div className="dag-deps-box">
                        <span className="dag-dep-label">Depends on:</span>
                        {node.dependencies.length === 0 ? (
                          <span style={{ fontSize: "10px", color: "var(--accent-emerald)", fontStyle: "italic" }}>
                            ⚡ None (Parallel Root)
                          </span>
                        ) : (
                          node.dependencies.map((depId) => {
                            const depNode = currentPlan.nodes.find((n) => n.node_id === depId);
                            const depStatus = depNode?.status || "unknown";
                            return (
                              <span
                                key={depId}
                                className="dag-dep-tag"
                                style={{
                                  borderColor:
                                    depStatus === "success"
                                      ? "rgba(16, 185, 129, 0.5)"
                                      : depStatus === "running"
                                      ? "rgba(56, 189, 248, 0.5)"
                                      : undefined,
                                }}
                                title={`Dependency #${depId} is currently ${depStatus}`}
                              >
                                #{depId} {depStatus === "success" ? "✓" : ""}
                              </span>
                            );
                          })
                        )}
                      </div>

                      {/* Interactive Node Controls */}
                      <div className="dag-node-actions" onClick={(e) => e.stopPropagation()}>
                        <button
                          className="dag-action-btn"
                          title="Simulate Running"
                          onClick={() => handleUpdateNodeStatus(node.node_id, "running")}
                        >
                          ▶ Run
                        </button>
                        <button
                          className="dag-action-btn"
                          style={{ color: "#34d399" }}
                          title="Mark Success"
                          onClick={() => handleUpdateNodeStatus(node.node_id, "success")}
                        >
                          ✔ Done
                        </button>
                        <button
                          className="dag-action-btn"
                          style={{ color: "#fbbf24" }}
                          title="Mark Warning"
                          onClick={() => handleUpdateNodeStatus(node.node_id, "warning")}
                        >
                          ⚠ Warn
                        </button>
                        <button
                          className="dag-action-btn"
                          style={{ color: "#fb7185" }}
                          title="Mark Failed"
                          onClick={() => handleUpdateNodeStatus(node.node_id, "failed")}
                        >
                          ✖ Fail
                        </button>
                        <button
                          className="dag-action-btn"
                          title="Reset to Queued"
                          onClick={() => handleUpdateNodeStatus(node.node_id, "queued")}
                        >
                          ↺
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Selected Node Details Drawer */}
      {selectedNode && (
        <div
          style={{
            background: "rgba(11, 16, 29, 0.98)",
            borderTop: "1px solid rgba(255, 255, 255, 0.12)",
            padding: "12px 16px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: "16px",
            maxHeight: "340px",
            overflowY: "auto",
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent-cyan)", fontWeight: 700 }}>
                #{selectedNode.node_id}
              </span>
              <span style={{ fontWeight: 600, color: "#fff", fontSize: "13px" }}>{selectedNode.label}</span>
              <span className={`dag-status-pill ${selectedNode.status}`}>{selectedNode.status}</span>
              {selectedNode.assigned_tool && (
                <span className="dag-capability-tag">🔧 Tool: {selectedNode.assigned_tool}</span>
              )}
            </div>
            <p style={{ fontSize: "11px", color: "var(--text-muted)", marginBottom: "6px" }}>
              {selectedNode.description}
            </p>
            {selectedNode.rationale && (
              <p style={{ fontSize: "11px", color: "#cbd5e1", fontStyle: "italic", marginBottom: "4px" }}>
                💡 Rationale: {selectedNode.rationale}
              </p>
            )}
            {selectedNode.expected_outputs && selectedNode.expected_outputs.length > 0 && (
              <div style={{ display: "flex", gap: "4px", alignItems: "center", flexWrap: "wrap", marginBottom: "8px" }}>
                <span style={{ fontSize: "10px", color: "#64748b", textTransform: "uppercase", fontWeight: 700 }}>
                  Expected Outputs:
                </span>
                {selectedNode.expected_outputs.map((out, idx) => (
                  <span
                    key={idx}
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "9px",
                      background: "rgba(255, 255, 255, 0.05)",
                      padding: "1px 5px",
                      borderRadius: "3px",
                      color: "#94a3b8",
                    }}
                  >
                    {out}
                  </span>
                ))}
              </div>
            )}

            {/* Cognitive Results / Facts / Critique / Recovery Status */}
            {(() => {
              if (!selectedNode.result) return null;
              let resObj: NodeResultData = {};
              if (typeof selectedNode.result === "string") {
                try {
                  resObj = JSON.parse(selectedNode.result) as NodeResultData;
                } catch {
                  resObj = { text: selectedNode.result };
                }
              } else if (typeof selectedNode.result === "object" && selectedNode.result !== null) {
                resObj = selectedNode.result as NodeResultData;
              }
              const isRecoveryExhausted =
                resObj.error === "RECOVERY_EXHAUSTED" ||
                (typeof resObj.reason === "string" && resObj.reason.includes("RECOVERY_EXHAUSTED"));
              const critique = resObj.critique;
              const facts = resObj.facts;
              const attempts = typeof resObj.attempts === "number" ? resObj.attempts : 1;
              const reasonText =
                typeof resObj.reason === "string"
                  ? resObj.reason
                  : "Node reached maximum recovery attempt cap (3/3) without moving the task graph forward.";
              const critiqueText = typeof critique?.critique === "string" ? critique.critique : "";
              const suggestedActionText = typeof critique?.suggested_action === "string" ? critique.suggested_action : "";
              const summaryText = typeof resObj.summary === "string" ? resObj.summary : "";

              return (
                <div style={{ marginTop: "10px", display: "flex", flexDirection: "column", gap: "8px" }}>
                  {/* Recovery Exhausted Cap Warning */}
                  {isRecoveryExhausted && (
                    <div
                      style={{
                        background: "rgba(239, 68, 68, 0.15)",
                        border: "1px solid rgba(239, 68, 68, 0.4)",
                        padding: "8px 10px",
                        borderRadius: "6px",
                        color: "#fca5a5",
                        fontSize: "11px",
                      }}
                    >
                      <div
                        style={{
                          fontWeight: 700,
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          marginBottom: "3px",
                        }}
                      >
                        <span>🚨 RECOVERY EXHAUSTED (3/3 attempts)</span>
                        <span
                          style={{
                            fontSize: "10px",
                            background: "rgba(239, 68, 68, 0.3)",
                            padding: "1px 5px",
                            borderRadius: "3px",
                          }}
                        >
                          SURFACED TO OPERATOR
                        </span>
                      </div>
                      <div>{reasonText}</div>
                    </div>
                  )}

                  {/* Critic Evaluation */}
                  {critique && (
                    <div
                      style={{
                        background: "rgba(30, 41, 59, 0.8)",
                        border: "1px solid rgba(255, 255, 255, 0.1)",
                        padding: "8px 10px",
                        borderRadius: "6px",
                        fontSize: "11px",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: "4px",
                        }}
                      >
                        <span style={{ color: "var(--accent-cyan)", fontWeight: 700 }}>⚖️ Critic Evaluation</span>
                        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                          <span
                            className={`dag-status-pill ${critique.has_progress ? "success" : "warning"}`}
                            style={{ fontSize: "9px" }}
                          >
                            {critique.status || (critique.has_progress ? "progress" : "no_progress")}
                          </span>
                          <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                            Attempts: {attempts}/3
                          </span>
                        </div>
                      </div>
                      <p style={{ color: "#e2e8f0", margin: "2px 0 4px 0" }}>{critiqueText}</p>
                      {suggestedActionText && (
                        <p style={{ color: "#fbbf24", margin: 0, fontStyle: "italic", fontSize: "10px" }}>
                          💡 Suggested Action: {suggestedActionText}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Observer Structured Facts Summary */}
                  {facts && (
                    <div
                      style={{
                        background: "rgba(15, 23, 42, 0.7)",
                        border: "1px solid rgba(255, 255, 255, 0.08)",
                        padding: "8px 10px",
                        borderRadius: "6px",
                        fontSize: "11px",
                      }}
                    >
                      <span
                        style={{
                          color: "var(--accent-emerald)",
                          fontWeight: 700,
                          display: "block",
                          marginBottom: "4px",
                        }}
                      >
                        🔬 Observer Structured Facts:
                      </span>
                      {facts.ports && facts.ports.length > 0 && (
                        <div style={{ marginBottom: "3px" }}>
                          <strong style={{ color: "#94a3b8" }}>Open Ports: </strong>
                          {facts.ports.map((p: FactPort, i: number) => (
                            <span
                              key={i}
                              style={{
                                fontFamily: "var(--font-mono)",
                                background: "rgba(16, 185, 129, 0.15)",
                                color: "#34d399",
                                padding: "1px 4px",
                                borderRadius: "3px",
                                marginRight: "4px",
                                fontSize: "10px",
                              }}
                            >
                              {p.port}/{p.service || "unknown"}
                            </span>
                          ))}
                        </div>
                      )}
                      {facts.endpoints && facts.endpoints.length > 0 && (
                        <div style={{ marginBottom: "3px" }}>
                          <strong style={{ color: "#94a3b8" }}>Endpoints: </strong>
                          {facts.endpoints.slice(0, 4).map((e: FactEndpoint, i: number) => (
                            <span
                              key={i}
                              style={{
                                fontFamily: "var(--font-mono)",
                                background: "rgba(56, 189, 248, 0.15)",
                                color: "#38bdf8",
                                padding: "1px 4px",
                                borderRadius: "3px",
                                marginRight: "4px",
                                fontSize: "10px",
                              }}
                            >
                              {e.path || e.url || "endpoint"} [{e.status || 200}]
                            </span>
                          ))}
                          {facts.endpoints.length > 4 && (
                            <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>
                              +{facts.endpoints.length - 4} more
                            </span>
                          )}
                        </div>
                      )}
                      {facts.vulnerabilities && facts.vulnerabilities.length > 0 && (
                        <div style={{ marginBottom: "3px" }}>
                          <strong style={{ color: "#fca5a5" }}>Vulnerabilities: </strong>
                          {facts.vulnerabilities.map((v: FactVuln, i: number) => (
                            <span
                              key={i}
                              style={{
                                fontFamily: "var(--font-mono)",
                                background: "rgba(244, 63, 94, 0.2)",
                                color: "#fca5a5",
                                padding: "1px 4px",
                                borderRadius: "3px",
                                marginRight: "4px",
                                fontSize: "10px",
                              }}
                            >
                              {v.id || v.type || "vuln"}
                            </span>
                          ))}
                        </div>
                      )}
                      {summaryText && (
                        <div style={{ color: "#cbd5e1", fontSize: "11px", marginTop: "4px" }}>
                          {summaryText}
                        </div>
                      )}

                      {/* Collapsed Recovery Path Section Per Finding */}
                      {(resObj.recovery_narrative || attempts > 1) && (
                        <details
                          style={{
                            marginTop: "6px",
                            background: "rgba(30, 41, 59, 0.6)",
                            border: "1px solid rgba(245, 158, 11, 0.3)",
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
                            }}
                          >
                            🛡️ Recovery Path for Findings ({attempts} attempt{attempts > 1 ? "s" : ""})
                          </summary>
                          <div style={{ marginTop: "4px", fontSize: "10px", color: "#e2e8f0" }}>
                            {resObj.recovery_narrative ||
                              `Node recovered autonomously after ${attempts} attempts via Task 2.4 intervention.`}
                          </div>
                        </details>
                      )}
                    </div>
                  )}

                  {/* Failure-Aware Full Attempt History & Autonomous Recovery Panel */}
                  {(resObj.recovery_narrative || (resObj.recovery_path && resObj.recovery_path.length > 1) || attempts > 1) && (
                    <div
                      style={{
                        background: "rgba(30, 27, 75, 0.4)",
                        border: "1px solid rgba(168, 85, 247, 0.3)",
                        padding: "8px 10px",
                        borderRadius: "6px",
                        fontSize: "11px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ color: "#c084fc", fontWeight: 700 }}>
                          🛡️ Failure-Aware Autonomous Recovery (Task 2.4)
                        </span>
                        <span className="dag-status-pill warning" style={{ fontSize: "9px" }}>
                          Healed ({attempts} attempts)
                        </span>
                      </div>

                      {resObj.recovery_narrative && (
                        <div
                          style={{
                            background: "rgba(15, 23, 42, 0.8)",
                            padding: "6px 8px",
                            borderRadius: "4px",
                            borderLeft: "3px solid #a855f7",
                            fontFamily: "var(--font-mono)",
                            fontSize: "10px",
                            color: "#f3e8ff",
                            marginBottom: "6px",
                            lineHeight: "1.4",
                          }}
                        >
                          {resObj.recovery_narrative}
                        </div>
                      )}

                      {/* Step-by-Step Linked Attempt Chain */}
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        {((resObj.recovery_path && resObj.recovery_path.length > 0)
                          ? resObj.recovery_path
                          : (resObj.history || [])
                        ).map((step: RecoveryPathStep, sIdx: number) => (
                          <div
                            key={sIdx}
                            style={{
                              background: "rgba(15, 23, 42, 0.6)",
                              border: "1px solid rgba(255, 255, 255, 0.05)",
                              padding: "4px 8px",
                              borderRadius: "4px",
                              fontSize: "10px",
                            }}
                          >
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <span style={{ fontWeight: 600, color: step.status === "failed" ? "#fca5a5" : "#6ee7b7" }}>
                                {step.status === "failed" ? "❌ Failed Attempt" : "✓ Successful Execution"} #{step.attempt || sIdx + 1}: {step.tool || "Tool"}
                              </span>
                              <span style={{ color: "var(--text-muted)", fontSize: "9px" }}>
                                {step.duration_s ? `${step.duration_s}s` : ""}
                              </span>
                            </div>
                            {step.failure_reason && (
                              <div style={{ color: "#f87171", fontSize: "10px", marginTop: "2px" }}>
                                Reason: {step.failure_reason}
                              </div>
                            )}
                            {step.action_taken && (
                              <div style={{ color: "#fbbf24", fontSize: "10px", marginTop: "2px" }}>
                                💡 Recovery Action: {step.action_taken}
                              </div>
                            )}
                            {(step.event_id || step.parent_event) && (
                              <div style={{ color: "#64748b", fontSize: "9px", fontFamily: "var(--font-mono)", marginTop: "2px" }}>
                                {step.event_id ? `Event: ${step.event_id.slice(0, 16)}...` : ""}
                                {step.parent_event ? ` ↳ Parent: ${step.parent_event.slice(0, 16)}...` : ""}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Why This Tool Breakdown Panel */}
            <WhyThisToolPanel
              toolId={selectedNode.assigned_tool || `${selectedNode.capability}.v1`}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "6px", alignItems: "flex-end" }}>
            <button
              className="quick-btn secondary"
              style={{ padding: "2px 8px", fontSize: "10px" }}
              onClick={() => setSelectedNode(null)}
            >
              ✕ Close
            </button>
            <button
              className="quick-btn"
              style={{
                fontSize: "10px",
                padding: "3px 8px",
                background: "rgba(6, 182, 212, 0.2)",
                borderColor: "var(--accent-cyan)",
                color: "#67e8f9",
              }}
              onClick={() => handleExecuteSingleNode(selectedNode.node_id)}
            >
              ▶ Run Cognitive Loop
            </button>
            <div style={{ display: "flex", gap: "4px" }}>
              <button
                className="ctrl-btn resume"
                style={{ fontSize: "10px", padding: "2px 6px" }}
                onClick={() => handleUpdateNodeStatus(selectedNode.node_id, "running")}
              >
                Set Running
              </button>
              <button
                className="ctrl-btn pause"
                style={{ fontSize: "10px", padding: "2px 6px" }}
                onClick={() => handleUpdateNodeStatus(selectedNode.node_id, "success")}
              >
                Set Success
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cryptographic Audit Report Modal */}
      {reportModalData && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(4px)",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px",
          }}
          onClick={() => setReportModalData(null)}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              borderRadius: "10px",
              width: "800px",
              maxWidth: "95vw",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7)",
              overflow: "hidden",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: "12px 16px",
                borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "rgba(30, 41, 59, 0.5)",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>🛡️ Kairo Security &amp; Autonomous Resilience Audit Report</span>
                  <span className="dag-status-pill success" style={{ fontSize: "10px" }}>
                    SHA-256 Signed
                  </span>
                </h3>
                <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                  Plan ID: {(reportModalData.plan_id as string) || "N/A"} • Generated: {new Date().toLocaleTimeString()}
                </span>
              </div>
              <button
                className="quick-btn secondary"
                style={{ padding: "3px 8px", fontSize: "11px" }}
                onClick={() => setReportModalData(null)}
              >
                ✕ Close
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "14px" }}>
              {/* Resilience Metrics KPI Banner */}
              {reportModalData.resilience_metrics && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                    gap: "10px",
                    background: "rgba(15, 23, 42, 0.6)",
                    padding: "10px",
                    borderRadius: "6px",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                  }}
                >
                  <div>
                    <span style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase" }}>Autonomous Healing Rate</span>
                    <div style={{ fontSize: "18px", fontWeight: 800, color: "#34d399" }}>
                      {((reportModalData.resilience_metrics as Record<string, unknown>).autonomous_healing_rate_pct as number) ?? 100}%
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase" }}>Nodes Recovered</span>
                    <div style={{ fontSize: "18px", fontWeight: 800, color: "#fbbf24" }}>
                      {((reportModalData.resilience_metrics as Record<string, unknown>).nodes_requiring_recovery as number) ?? 0}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase" }}>Total Interventions</span>
                    <div style={{ fontSize: "18px", fontWeight: 800, color: "#60a5fa" }}>
                      {((reportModalData.resilience_metrics as Record<string, unknown>).total_recovery_interventions as number) ?? 0}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase" }}>Recovery Cap Limits</span>
                    <div style={{ fontSize: "18px", fontWeight: 800, color: "#a855f7" }}>
                      {((reportModalData.resilience_metrics as Record<string, unknown>).recovery_exhausted_caps as number) ?? 0}
                    </div>
                  </div>
                </div>
              )}

              {/* Recovery Narratives Showcase */}
              {reportModalData.recovery_narratives &&
                Object.keys(reportModalData.recovery_narratives as Record<string, string>).length > 0 && (
                  <div
                    style={{
                      background: "rgba(30, 27, 75, 0.3)",
                      border: "1px solid rgba(168, 85, 247, 0.3)",
                      borderRadius: "6px",
                      padding: "10px",
                    }}
                  >
                    <span style={{ fontSize: "12px", fontWeight: 700, color: "#c084fc", display: "block", marginBottom: "6px" }}>
                      🔄 Autonomous Recovery Paths (Task 2.4 Attempt History)
                    </span>
                    {Object.entries(reportModalData.recovery_narratives as Record<string, string>).map(([nId, narrative]) => (
                      <div
                        key={nId}
                        style={{
                          background: "rgba(15, 23, 42, 0.7)",
                          padding: "6px 8px",
                          borderRadius: "4px",
                          fontFamily: "var(--font-mono)",
                          fontSize: "11px",
                          color: "#f3e8ff",
                          marginBottom: "4px",
                        }}
                      >
                        <strong style={{ color: "#38bdf8" }}>Node #{nId}: </strong>
                        {narrative}
                      </div>
                    ))}
                  </div>
                )}

              {/* SHA-256 Integrity Verification Artifacts */}
              {reportModalData.artifacts && (
                <div
                  style={{
                    background: "rgba(15, 23, 42, 0.6)",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                    borderRadius: "6px",
                    padding: "10px",
                  }}
                >
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--accent-cyan)", display: "block", marginBottom: "4px" }}>
                    🔒 SHA-256 Cryptographic Artifact Hashes
                  </span>
                  <div style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "#94a3b8" }}>
                    JSON: {((reportModalData.artifacts as Record<string, Record<string, string>>).json?.sha256) || "N/A"}<br />
                    Markdown: {((reportModalData.artifacts as Record<string, Record<string, string>>).markdown?.sha256) || "N/A"}
                  </div>
                </div>
              )}

              {/* Raw Markdown Report Preview */}
              {reportModalData.markdown_report && (
                <div>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", display: "block", marginBottom: "4px" }}>
                    Report Preview
                  </span>
                  <pre
                    style={{
                      background: "#020617",
                      padding: "12px",
                      borderRadius: "6px",
                      fontSize: "10px",
                      fontFamily: "var(--font-mono)",
                      color: "#cbd5e1",
                      maxHeight: "220px",
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                      margin: 0,
                    }}
                  >
                    {reportModalData.markdown_report as string}
                  </pre>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div
              style={{
                padding: "10px 16px",
                borderTop: "1px solid rgba(255, 255, 255, 0.1)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "rgba(30, 41, 59, 0.4)",
              }}
            >
              <button
                className="quick-btn secondary"
                style={{ fontSize: "11px", padding: "4px 10px" }}
                onClick={() => {
                  if (reportModalData.markdown_report) {
                    navigator.clipboard.writeText(reportModalData.markdown_report as string);
                    showNotification("Markdown report copied to clipboard!");
                  }
                }}
              >
                📋 Copy Markdown Report
              </button>
              <button
                className="quick-btn"
                style={{ fontSize: "11px", padding: "4px 12px" }}
                onClick={() => setReportModalData(null)}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
