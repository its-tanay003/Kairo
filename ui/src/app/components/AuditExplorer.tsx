"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";

export interface TimelineItem {
  id?: number | string;
  session_id?: string;
  task_id?: string;
  timestamp: string;
  actor?: string;
  tool_id?: string;
  tool_version?: string;
  requested_args?: Record<string, unknown> | string | number | boolean | null | undefined;
  normalized_args?: Record<string, unknown> | string | number | boolean | null | undefined;
  process_id?: number;
  exit_code?: number;
  stdout_ref?: string;
  stderr_ref?: string;
  artifact_refs?: Record<string, unknown> | unknown[] | string | null | undefined;
  result_summary?: string;
  confidence?: number;
  parent_event?: string;

  // Scope Contract correlation fields
  governing_contract_id?: string;
  governing_contract_targets?: string[];
  governing_contract_tiers?: number[];
  tool_tier?: number;
  target_evaluated?: string;
  target_in_scope?: boolean;
  tier_authorized?: boolean;
  scope_status?: "in_scope" | "scope_violation" | "unscoped";
  scope_violation_reason?: string;

  // Scope Contract Milestone fields
  is_scope_contract_milestone?: boolean;
  contract_id?: string;
  expires_at?: string;
  targets?: string[];
  allowed_tool_tiers?: number[];
  signature?: string;
  signature_valid?: boolean;
  is_active?: boolean;
  is_expired?: boolean;
  summary?: string;
}

export interface AuditStats {
  in_scope_actions: number;
  scope_violations: number;
  compliance_rate_pct: number;
  active_contracts: number;
}

export interface EvolutionTimelineItem {
  id: string;
  event_type:
    | "PROPOSAL"
    | "HUMAN_GATE_DECISION"
    | "TRAINING_JOB_START"
    | "TRAINING_JOB_STOPPED"
    | "TRAINING_JOB_COMPLETED"
    | "PROMOTION_DECISION";
  category: "proposal" | "human_gate" | "training_lifecycle" | "promotion_gate";
  timestamp: string;
  plain_language_summary: string;
  benchmark_justification: string;
  justifying_sweep_numbers?: Record<string, unknown>;
  rule_name?: string;
  action?: string;
  target_preset?: string;
  preset?: string;
  status?: string;
  decision?: string;
  operator?: string;
  proposal_id?: string;
  dispatched_job_id?: string;
  job_id?: string;
  job_type?: string;
  checkpoint_model_id?: string;
  active_model_id?: string;
  promoted?: boolean;
  plain_language_notice?: string;
  comparisons?: Record<
    string,
    {
      new_val: number;
      active_val: number;
      delta: number;
      delta_pct: number;
    }
  >;
  new_checkpoint_metrics?: Record<string, unknown>;
  active_model_metrics?: Record<string, unknown>;
  regressions?: Array<{
    metric: string;
    drop: number;
    new_val: number;
    active_val: number;
  }>;
  improvements?: Array<{
    metric: string;
    gain: number;
  }>;
  tolerated_variance?: number;
  estimated_cost?: {
    expected_duration_human?: string;
    compute_hardware?: string;
    historical_basis?: string;
  };
  parameters?: Record<string, unknown>;
  output_dir?: string;
  final_loss?: number;
  reward_margin?: number;
  stage_results?: Record<string, unknown>;
  rationale?: string;
  reason?: string;
  event_id?: number;
}


export interface EvolutionStats {
  total_events: number;
  total_proposals: number;
  total_approvals: number;
  total_dismissals: number;
  total_training_runs: number;
  total_promotions: number;
  total_rollbacks_guarded: number;
}

function formatMetricName(key: string): string {
  switch (key) {
    case "tool_accuracy_pct":
      return "Tool Accuracy";
    case "schema_pass_pct":
      return "Schema Pass Rate";
    case "recovery_rate_pct":
      return "Recovery Rate";
    case "composite_score":
      return "Composite Score";
    default:
      return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

export default function AuditExplorer() {
  const [activeTab, setActiveTab] = useState<"scope_execution" | "model_evolution">("model_evolution");

  // Standard Scope & Execution Timeline States
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [totalDbEvents, setTotalDbEvents] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [selectedItem, setSelectedItem] = useState<TimelineItem | null>(null);

  // Standard Filters
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [actorFilter, setActorFilter] = useState<string>("all");
  const [toolFilter, setToolFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [scopeFilter, setScopeFilter] = useState<string>("all");
  const [timeRange, setTimeRange] = useState<string>("all");

  // Model Evolution Timeline States (Task C.1 - C.3)
  const [evolutionTimeline, setEvolutionTimeline] = useState<EvolutionTimelineItem[]>([]);
  const [evolutionStats, setEvolutionStats] = useState<EvolutionStats | null>(null);
  const [isEvolutionLoading, setIsEvolutionLoading] = useState<boolean>(true);
  const [selectedEvolutionItem, setSelectedEvolutionItem] = useState<EvolutionTimelineItem | null>(null);

  // Model Evolution Filters
  const [evolutionSearchQuery, setEvolutionSearchQuery] = useState<string>("");
  const [evolutionFilterType, setEvolutionFilterType] = useState<string>("all");
  const [evolutionPresetFilter, setEvolutionPresetFilter] = useState<string>("all");

  const buildStandardParams = useCallback(() => {
    const params = new URLSearchParams();
    if (searchQuery.trim()) params.append("query", searchQuery.trim());
    if (actorFilter !== "all") params.append("actor", actorFilter);
    if (toolFilter !== "all") params.append("tool_id", toolFilter);
    if (statusFilter !== "all") params.append("status", statusFilter);
    if (scopeFilter !== "all") params.append("scope_filter", scopeFilter);
    if (timeRange !== "all") params.append("time_range", timeRange);
    params.append("limit", "250");
    return params;
  }, [searchQuery, actorFilter, toolFilter, statusFilter, scopeFilter, timeRange]);

  const buildEvolutionParams = useCallback(() => {
    const params = new URLSearchParams();
    if (evolutionSearchQuery.trim()) params.append("query", evolutionSearchQuery.trim());
    if (evolutionFilterType !== "all") params.append("event_type", evolutionFilterType);
    if (evolutionPresetFilter !== "all") params.append("preset", evolutionPresetFilter);
    params.append("limit", "200");
    return params;
  }, [evolutionSearchQuery, evolutionFilterType, evolutionPresetFilter]);

  // Fetch helper with fallback between Gateway (4000) and Orchestrator (8000)
  const fetchApi = useCallback(async (path: string) => {
    try {
      const res = await fetch(`http://localhost:4000${path}`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback to direct orchestrator port
    }
    try {
      const res = await fetch(`http://127.0.0.1:8000${path}`);
      if (res.ok) return await res.json();
    } catch {
      // Offline fallback
    }
    return null;
  }, []);

  const loadStandardData = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await fetchApi(`/audit/timeline?${buildStandardParams().toString()}`);
      if (data) {
        setTimeline(data.timeline || []);
        setStats(data.stats || null);
        setTotalDbEvents(data.total_db_events || 0);
      }
    } catch (e) {
      console.error("Failed to fetch standard audit timeline", e);
    } finally {
      setIsLoading(false);
    }
  }, [fetchApi, buildStandardParams]);

  const loadEvolutionData = useCallback(async () => {
    setIsEvolutionLoading(true);
    try {
      const data = await fetchApi(`/audit/model-evolution-timeline?${buildEvolutionParams().toString()}`);
      if (data) {
        setEvolutionTimeline(data.timeline || []);
        setEvolutionStats(data.stats || null);
      }
    } catch (e) {
      console.error("Failed to fetch model evolution timeline", e);
    } finally {
      setIsEvolutionLoading(false);
    }
  }, [fetchApi, buildEvolutionParams]);

  useEffect(() => {
    let ignore = false;
    const runStandard = async () => {
      try {
        const data = await fetchApi(`/audit/timeline?${buildStandardParams().toString()}`);
        if (!ignore && data) {
          setTimeline(data.timeline || []);
          setStats(data.stats || null);
          setTotalDbEvents(data.total_db_events || 0);
        }
      } catch (e) {
        console.error("Failed to fetch standard audit timeline", e);
      } finally {
        if (!ignore) setIsLoading(false);
      }
    };

    const runEvolution = async () => {
      try {
        const data = await fetchApi(`/audit/model-evolution-timeline?${buildEvolutionParams().toString()}`);
        if (!ignore && data) {
          setEvolutionTimeline(data.timeline || []);
          setEvolutionStats(data.stats || null);
        }
      } catch (e) {
        console.error("Failed to fetch model evolution timeline", e);
      } finally {
        if (!ignore) setIsEvolutionLoading(false);
      }
    };

    runStandard();
    runEvolution();

    return () => {
      ignore = true;
    };
  }, [fetchApi, buildStandardParams, buildEvolutionParams]);


  const handleStandardSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadStandardData();
  };

  const handleEvolutionSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadEvolutionData();
  };

  // Distinct actors and tools for standard timeline
  const availableActors = useMemo(() => {
    const s = new Set<string>();
    timeline.forEach((item) => {
      if (item.actor) s.add(item.actor);
    });
    return Array.from(s);
  }, [timeline]);

  const availableTools = useMemo(() => {
    const s = new Set<string>();
    timeline.forEach((item) => {
      if (item.tool_id) s.add(item.tool_id);
    });
    return Array.from(s);
  }, [timeline]);

  // Distinct presets for evolution timeline
  const availablePresets = useMemo(() => {
    const s = new Set<string>();
    evolutionTimeline.forEach((item) => {
      const p = item.target_preset || item.preset || item.checkpoint_model_id;
      if (p) s.add(p);
    });
    return Array.from(s);
  }, [evolutionTimeline]);

  // Export functions for Standard Timeline
  const exportStandardAsJSON = () => {
    const blob = new Blob([JSON.stringify(timeline, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_timeline_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportStandardAsCSV = () => {
    const headers = [
      "Timestamp",
      "Type",
      "Actor",
      "Tool_ID",
      "Exit_Code",
      "Scope_Status",
      "Governing_Contract",
      "Target",
      "Summary",
    ];
    const rows = timeline.map((i) => {
      if (i.is_scope_contract_milestone) {
        return [
          i.timestamp,
          "CONTRACT_MILESTONE",
          "system",
          "-",
          "-",
          i.signature_valid ? "VALID_SIGNATURE" : "INVALID_SIGNATURE",
          i.contract_id || "-",
          (i.targets || []).join(";"),
          `Scope Contract Signed: ${i.contract_id}`,
        ];
      }
      return [
        i.timestamp,
        "EXECUTION_EVENT",
        i.actor || "-",
        i.tool_id || "-",
        String(i.exit_code ?? "-"),
        i.scope_status || "unscoped",
        i.governing_contract_id || "-",
        i.target_evaluated || "-",
        `"${(i.result_summary || "").replace(/"/g, '""')}"`,
      ];
    });

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_timeline_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Export functions for Model Evolution Timeline
  const exportEvolutionAsJSON = () => {
    const blob = new Blob([JSON.stringify(evolutionTimeline, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `model_evolution_audit_trail_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportEvolutionAsCSV = () => {
    const headers = [
      "Timestamp",
      "EventType",
      "TargetPreset",
      "Decision_Or_Status",
      "Summary",
      "BenchmarkJustification",
      "LinkedNumbers",
    ];
    const rows = evolutionTimeline.map((i) => [
      i.timestamp,
      i.event_type,
      i.target_preset || i.preset || i.checkpoint_model_id || "-",
      i.decision || i.status || "-",
      `"${(i.plain_language_summary || "").replace(/"/g, '""')}"`,
      `"${(i.benchmark_justification || "").replace(/"/g, '""')}"`,
      `"${JSON.stringify(i.justifying_sweep_numbers || {}).replace(/"/g, '""')}"`,
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `model_evolution_audit_trail_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="audit-explorer-container">
      {/* View Switcher Bar */}
      <div className="audit-view-mode-tabs">
        <button
          className={`view-mode-pill ${activeTab === "model_evolution" ? "active" : ""}`}
          onClick={() => setActiveTab("model_evolution")}
        >
          <span className="mode-icon">🧬</span>
          <span className="mode-label">Model Evolution Timeline</span>
          <span className="mode-badge highlight">{evolutionStats?.total_events ?? evolutionTimeline.length}</span>
        </button>

        <button
          className={`view-mode-pill ${activeTab === "scope_execution" ? "active" : ""}`}
          onClick={() => setActiveTab("scope_execution")}
        >
          <span className="mode-icon">🛡️</span>
          <span className="mode-label">Scope &amp; Execution Ledger</span>
          <span className="mode-badge">{totalDbEvents || timeline.length}</span>
        </button>
      </div>

      {activeTab === "model_evolution" ? (
        /* =========================================================================
           MODEL EVOLUTION DEDICATED TIMELINE (Task C.1 - C.3)
           ========================================================================= */
        <div className="model-evolution-audit-view">
          {/* Hero Header */}
          <div className="audit-hero-card evolution-theme">
            <div className="hero-top-row">
              <span className="hero-badge evolution">Verifiable Self-Improvement Ledger</span>
              <span className="font-xs mono text-muted">Tasks C.1 • C.2 • C.3 Decision Evidence Trail</span>
            </div>
            <h2 className="hero-title">Model Evolution Audit Timeline</h2>
            <p className="hero-desc">
              Every proposal, human approval/dismissal, training job run, and auto-promote decision linked directly
              to the exact benchmark sweep numbers and schema thresholds that justified it.
            </p>
          </div>

          {/* Evolution KPI Strip */}
          <div className="audit-kpi-bar evolution-kpis">
            <div className="kpi-card">
              <span className="kpi-label">EVOLUTION EVENTS</span>
              <span className="kpi-val">{evolutionStats?.total_events ?? evolutionTimeline.length}</span>
              <span className="kpi-sub">Total lifecycle records</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">PROPOSALS (TASK C.1)</span>
              <span className="kpi-val highlight">{evolutionStats?.total_proposals ?? 0}</span>
              <span className="kpi-sub">Inspectable candidates</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">HUMAN GATES (TASK C.2)</span>
              <span className="kpi-val good">
                {evolutionStats?.total_approvals ?? 0} <span className="sub-val">/ {evolutionStats?.total_dismissals ?? 0}d</span>
              </span>
              <span className="kpi-sub">Approved vs Dismissed</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">TRAINING RUNS</span>
              <span className="kpi-val">{evolutionStats?.total_training_runs ?? 0}</span>
              <span className="kpi-sub">Dispatched compute jobs</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">AUTO-PROMOTED (TASK C.3)</span>
              <span className="kpi-val in-scope">{evolutionStats?.total_promotions ?? 0}</span>
              <span className="kpi-sub">Beat baseline across metrics</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">ROLLBACKS GUARDED</span>
              <span className={`kpi-val ${(evolutionStats?.total_rollbacks_guarded ?? 0) > 0 ? "warning" : "good"}`}>
                {evolutionStats?.total_rollbacks_guarded ?? 0}
              </span>
              <span className="kpi-sub">Protected against regressions</span>
            </div>
          </div>

          {/* Evolution Filter & Search Bar */}
          <div className="audit-filter-bar">
            <form onSubmit={handleEvolutionSearchSubmit} className="search-form">
              <span className="search-icon">🔍</span>
              <input
                type="text"
                className="audit-search-input"
                placeholder="Search evolution timeline (preset, metric, proposal rationale, decision notice)..."
                value={evolutionSearchQuery}
                onChange={(e) => setEvolutionSearchQuery(e.target.value)}
              />
              <button type="submit" className="audit-filter-btn">
                Filter
              </button>
            </form>

            <div className="filter-controls-group">
              {/* Event Type Filter */}
              <select
                className="audit-select"
                value={evolutionFilterType}
                onChange={(e) => setEvolutionFilterType(e.target.value)}
                title="Filter by Evolution Event Type"
              >
                <option value="all">All Evolution Events</option>
                <option value="proposal">Proposals (Task C.1)</option>
                <option value="human_gate">Human Gates (Task C.2)</option>
                <option value="training">Training Jobs</option>
                <option value="promotion">Promotion Decisions (Task C.3)</option>
              </select>

              {/* Preset / Model Filter */}
              <select
                className="audit-select"
                value={evolutionPresetFilter}
                onChange={(e) => setEvolutionPresetFilter(e.target.value)}
                title="Filter by Target Model / Preset"
              >
                <option value="all">All Presets &amp; Models</option>
                {availablePresets.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>

              {/* Export Controls */}
              <div className="export-btn-group">
                <button className="export-btn" onClick={exportEvolutionAsCSV} title="Export as CSV">
                  📥 CSV
                </button>
                <button className="export-btn" onClick={exportEvolutionAsJSON} title="Export as JSON">
                  📥 JSON
                </button>
                <button className="export-btn refresh-btn" onClick={loadEvolutionData} title="Refresh Timeline">
                  ↻
                </button>
              </div>
            </div>
          </div>

          {/* Main Evolution Timeline Stream */}
          <div className="timeline-container">
            {isEvolutionLoading ? (
              <div className="timeline-loading">
                <div className="loading-spinner" />
                <p>Loading Model Evolution Decision Ledger &amp; Benchmark Evidence...</p>
              </div>
            ) : evolutionTimeline.length === 0 ? (
              <div className="timeline-empty">
                <span className="empty-icon">🧬</span>
                <h4>No Evolution Timeline Records Found</h4>
                <p>No model evolution proposals, approvals, training runs, or promotion decisions matched criteria.</p>
                <button
                  className="reset-filter-btn"
                  onClick={() => {
                    setEvolutionSearchQuery("");
                    setEvolutionFilterType("all");
                    setEvolutionPresetFilter("all");
                  }}
                >
                  Reset Filters
                </button>
              </div>
            ) : (
              <div className="timeline-stream evolution-stream">
                {evolutionTimeline.map((item, idx) => {
                  const isProposal = item.event_type === "PROPOSAL";
                  const isHumanGate = item.event_type === "HUMAN_GATE_DECISION";
                  const isTrainingStart = item.event_type === "TRAINING_JOB_START";
                  const isTrainingEnd =
                    item.event_type === "TRAINING_JOB_COMPLETED" || item.event_type === "TRAINING_JOB_STOPPED";
                  const isPromotion = item.event_type === "PROMOTION_DECISION";

                  const isPromoted = item.promoted === true;
                  const isApproved = item.decision === "APPROVED";
                  const isDismissed = item.decision === "DISMISSED";

                  const cardClass = isPromotion
                    ? isPromoted
                      ? "ev-card promotion-promoted"
                      : "ev-card promotion-guarded"
                    : isProposal
                    ? "ev-card proposal-card"
                    : isHumanGate
                    ? isApproved
                      ? "ev-card gate-approved"
                      : isDismissed
                      ? "ev-card gate-dismissed"
                      : "ev-card gate-pending"
                    : "ev-card training-card";


                  return (
                    <div
                      key={`ev_${item.id}_${idx}`}
                      className={`timeline-event-card ${cardClass} ${
                        selectedEvolutionItem?.id === item.id ? "selected" : ""
                      }`}
                      onClick={() => setSelectedEvolutionItem(item)}
                    >
                      {/* Top Meta Row */}
                      <div className="card-top-row">
                        <div className="actor-tool-group">
                          {isProposal && (
                            <span className="evolution-type-badge proposal">
                              💡 PROPOSAL: {(item.rule_name || "rule").toUpperCase()}
                            </span>
                          )}
                          {isHumanGate && (
                            <span className={`evolution-type-badge ${isApproved ? "approved" : "dismissed"}`}>
                              🛡️ HUMAN GATE: {item.decision}
                            </span>
                          )}
                          {isTrainingStart && (
                            <span className="evolution-type-badge training-start">
                              🚀 TRAINING JOB: STARTED
                            </span>
                          )}
                          {isTrainingEnd && (
                            <span className={`evolution-type-badge ${item.status === "completed" ? "training-complete" : "training-stopped"}`}>
                              {item.status === "completed" ? "✓ TRAINING: COMPLETED" : "⏹️ TRAINING: STOPPED"}
                            </span>
                          )}
                          {isPromotion && (
                            <span className={`evolution-type-badge ${isPromoted ? "promoted" : "guarded"}`}>
                              {isPromoted ? "✓ AUTO-PROMOTED TO ACTIVE" : "🛡️ ROLLBACK GUARDED — NOT PROMOTED"}
                            </span>
                          )}

                          {/* Model / Target Tag */}
                          {(item.target_preset || item.preset || item.checkpoint_model_id) && (
                            <span className="eval-model-tag font-mono">
                              {item.target_preset || item.preset || item.checkpoint_model_id}
                            </span>
                          )}
                        </div>

                        <div className="scope-status-group">
                          <span className="timestamp-pill">
                            {new Date(item.timestamp).toLocaleString([], {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })}
                          </span>
                        </div>
                      </div>

                      {/* Plain-Language Summary Box */}
                      <div className="card-body-row">
                        <div className="evolution-quote-box">
                          <span className="quote-mark">“</span>
                          <span className="plain-language-headline">{item.plain_language_summary}</span>
                          <span className="quote-mark">”</span>
                        </div>

                        {/* Benchmark & Threshold Justification Callout */}
                        <div className="justification-callout-box">
                          <div className="justification-header">
                            <span className="just-icon">🎯</span>
                            <strong>Justifying Benchmark Sweep &amp; Evidence:</strong>
                          </div>
                          <p className="justification-text">{item.benchmark_justification}</p>

                          {/* Embedded Side-by-Side Sweep Table for Promotion Decisions */}
                          {isPromotion && item.comparisons && (
                            <div className="eval-comparison-table-wrap mini">
                              <table className="eval-comparison-table">
                                <thead>
                                  <tr>
                                    <th>Tracked Metric</th>
                                    <th>Active Baseline ({item.active_model_id})</th>
                                    <th>New Checkpoint ({item.checkpoint_model_id})</th>
                                    <th>Delta</th>
                                    <th>Sweep Outcome</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {Object.entries(item.comparisons).map(([metricKey, cmp]) => {
                                    const delta = cmp.delta;
                                    const isReg = item.regressions?.some((r) => r.metric === metricKey);
                                    const isImp = item.improvements?.some((i) => i.metric === metricKey);

                                    return (
                                      <tr
                                        key={metricKey}
                                        className={isReg ? "row-regressed" : isImp ? "row-improved" : "row-neutral"}
                                      >
                                        <td className="metric-cell-name font-mono">{formatMetricName(metricKey)}</td>
                                        <td className="metric-cell-val font-mono">{cmp.active_val.toFixed(1)}%</td>
                                        <td className="metric-cell-val font-mono">{cmp.new_val.toFixed(1)}%</td>
                                        <td
                                          className={`metric-cell-delta font-mono ${
                                            delta > 0 ? "gain" : delta < 0 ? "drop" : "neutral"
                                          }`}
                                        >
                                          {delta > 0 ? `+${delta.toFixed(1)}%` : `${delta.toFixed(1)}%`}
                                        </td>
                                        <td>
                                          {isReg ? (
                                            <span className="eval-status-pill regressed">Drop &gt; 1.0% (Rollback)</span>
                                          ) : isImp ? (
                                            <span className="eval-status-pill improved">▲ Beat Baseline</span>
                                          ) : (
                                            <span className="eval-status-pill satisfied">✓ Within Tolerance</span>
                                          )}
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          )}

                          {/* Quick Justifying Chips for Proposals & Training */}
                          {isProposal && item.justifying_sweep_numbers && (
                            <div className="justification-pills-row">
                              {item.justifying_sweep_numbers.new_examples !== undefined && (
                                <span className="just-pill">
                                  📊 New Examples:{" "}
                                  <strong>{Number(item.justifying_sweep_numbers.new_examples).toLocaleString()}</strong>
                                </span>
                              )}
                              {item.justifying_sweep_numbers.schema_pass_pct !== undefined && (
                                <span className="just-pill">
                                  🎯 Schema Pass: <strong>{String(item.justifying_sweep_numbers.schema_pass_pct)}%</strong>
                                </span>
                              )}
                              {item.estimated_cost?.expected_duration_human && (
                                <span className="just-pill">
                                  ⏱️ Est. Duration:{" "}
                                  <strong>{item.estimated_cost.expected_duration_human}</strong>
                                </span>
                              )}
                            </div>
                          )}

                          {isTrainingEnd && item.final_loss !== undefined && (
                            <div className="justification-pills-row">
                              <span className="just-pill">
                                📉 Final Loss: <strong>{item.final_loss}</strong>
                              </span>
                              {item.reward_margin !== undefined && item.reward_margin !== null && (
                                <span className="just-pill">
                                  🏆 Reward Margin: <strong>{item.reward_margin}</strong>
                                </span>
                              )}
                              {item.output_dir && (
                                <span className="just-pill font-mono">
                                  📁 Path: {item.output_dir}
                                </span>
                              )}
                            </div>
                          )}

                          {isHumanGate && (
                            <div className="justification-pills-row">
                              <span className="just-pill">
                                👤 Operator: <strong>{item.operator || "operator_secops"}</strong>
                              </span>
                              {item.dispatched_job_id && (
                                <span className="just-pill font-mono">
                                  ⚡ Dispatched Job: <strong>{item.dispatched_job_id}</strong>
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Footer Link & Verification Proof */}
                      <div className="card-meta-footer evolution-footer">
                        <span className="task-id-text font-mono">ID: {item.id}</span>
                        {item.event_id && (
                          <span className="event-ref font-mono">
                            Event Store Audit Entry: <code>#{item.event_id}</code>
                          </span>
                        )}
                        <span className="inspect-hint">Click to inspect full justification proof →</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      ) : (
        /* =========================================================================
           STANDARD SCOPE & EXECUTION TIMELINE (Task 2.3)
           ========================================================================= */
        <div className="standard-audit-view">
          {/* Top Accountability Hero */}
          <div className="audit-hero-card">
            <div className="hero-top-row">
              <span className="hero-badge">Immutable Audit Ledger</span>
              <span className="font-xs mono text-muted">Task 2.3 Scope Contract Accountability</span>
            </div>
            <h2 className="hero-title">Audit Explorer &amp; Timeline Stream</h2>
            <p className="hero-desc">
              Cryptographically correlated timeline of every agent, supervisor, and tool action. Enforces HMAC-SHA256 scope boundary contracts and deterministic SLA compliance.
            </p>
          </div>

          {/* Top Accountability KPI Strip */}
          <div className="audit-kpi-bar">
            <div className="kpi-card">
              <span className="kpi-label">TOTAL AUDIT EVENTS</span>
              <span className="kpi-val">{totalDbEvents || timeline.length}</span>
              <span className="kpi-sub">Every agent, user & tool action</span>
            </div>
            <div className="kpi-card highlight">
              <span className="kpi-label">SCOPE COMPLIANCE RATE</span>
              <span className={`kpi-val ${(stats?.compliance_rate_pct ?? 100) >= 95 ? "good" : "bad"}`}>
                {stats ? `${stats.compliance_rate_pct}%` : "100%"}
              </span>
              <span className="kpi-sub">Task 2.3 Contract enforcement</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">IN-SCOPE ACTIONS</span>
              <span className="kpi-val in-scope">{stats?.in_scope_actions ?? 0}</span>
              <span className="kpi-sub">Verified against CIDR boundaries</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">SCOPE VIOLATIONS</span>
              <span className={`kpi-val ${(stats?.scope_violations ?? 0) > 0 ? "bad" : "good"}`}>
                {stats?.scope_violations ?? 0}
              </span>
              <span className="kpi-sub">Out-of-boundary / unauthorized attempts</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">ACTIVE SCOPE CONTRACTS</span>
              <span className="kpi-val">{stats?.active_contracts ?? 1}</span>
              <span className="kpi-sub">HMAC-SHA256 signed boundaries</span>
            </div>
          </div>

          {/* Filter and Search Bar */}
          <div className="audit-filter-bar">
            <form onSubmit={handleStandardSearchSubmit} className="search-form">
              <span className="search-icon">🔍</span>
              <input
                type="text"
                className="audit-search-input"
                placeholder="Search audit timeline (target, tool, arguments, stdout, summary)..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              <button type="submit" className="audit-filter-btn">
                Filter
              </button>
            </form>

            <div className="filter-controls-group">
              {/* Actor Filter */}
              <select
                className="audit-select"
                value={actorFilter}
                onChange={(e) => setActorFilter(e.target.value)}
                title="Filter by Actor"
              >
                <option value="all">All Actors</option>
                {availableActors.map((a) => (
                  <option key={a} value={a}>
                    Actor: {a}
                  </option>
                ))}
              </select>

              {/* Tool Filter */}
              <select
                className="audit-select"
                value={toolFilter}
                onChange={(e) => setToolFilter(e.target.value)}
                title="Filter by Tool"
              >
                <option value="all">All Tools</option>
                {availableTools.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>

              {/* Status Filter */}
              <select
                className="audit-select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                title="Filter by Exit Status"
              >
                <option value="all">All Statuses</option>
                <option value="success">Success (Exit 0)</option>
                <option value="failure">Failure (Exit != 0)</option>
              </select>

              {/* Scope Filter */}
              <select
                className="audit-select"
                value={scopeFilter}
                onChange={(e) => setScopeFilter(e.target.value)}
                title="Filter by Scope Accountability"
              >
                <option value="all">All Scope States</option>
                <option value="in_scope">In-Scope Only</option>
                <option value="violations">Scope Violations Only</option>
                <option value="contracts">Contracts Only</option>
              </select>

              {/* Time Range */}
              <select
                className="audit-select"
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value)}
                title="Filter by Time Window"
              >
                <option value="all">All Time</option>
                <option value="1h">Past 1 Hour</option>
                <option value="24h">Past 24 Hours</option>
                <option value="7d">Past 7 Days</option>
              </select>

              {/* Export Controls */}
              <div className="export-btn-group">
                <button className="export-btn" onClick={exportStandardAsCSV} title="Export as CSV">
                  📥 CSV
                </button>
                <button className="export-btn" onClick={exportStandardAsJSON} title="Export as JSON">
                  📥 JSON
                </button>
              </div>
            </div>
          </div>

          {/* Main Standard Timeline Stream */}
          <div className="timeline-container">
            {isLoading ? (
              <div className="timeline-loading">
                <div className="loading-spinner" />
                <p>Querying SQLite Event Store &amp; Correlating Scope Contracts...</p>
              </div>
            ) : timeline.length === 0 ? (
              <div className="timeline-empty">
                <p>No audit events matched the selected filter criteria.</p>
                <button
                  className="reset-filter-btn"
                  onClick={() => {
                    setSearchQuery("");
                    setActorFilter("all");
                    setToolFilter("all");
                    setStatusFilter("all");
                    setScopeFilter("all");
                    setTimeRange("all");
                  }}
                >
                  Reset Filters
                </button>
              </div>
            ) : (
              <div className="timeline-stream">
                {timeline.map((item, idx) => {
                  if (item.is_scope_contract_milestone) {
                    return (
                      <div
                        key={`milestone_${item.contract_id}_${idx}`}
                        className="timeline-milestone-card"
                        onClick={() => setSelectedItem(item)}
                      >
                        <div className="milestone-badge-row">
                          <span className="milestone-icon">📜</span>
                          <span className="milestone-title">SCOPE CONTRACT ACTIVATION MILESTONE (Task 2.3)</span>
                          <span className="milestone-time">{item.timestamp}</span>
                        </div>

                        <div className="milestone-content">
                          <div className="milestone-main">
                            <div className="contract-id-pill">
                              <span>Contract ID:</span>
                              <strong>{item.contract_id}</strong>
                            </div>
                            <div className="signature-pill valid">
                              <span className="sig-icon">🔒</span>
                              <span>HMAC-SHA256: {item.signature?.slice(0, 16)}...</span>
                              <span className="sig-check">✓ VERIFIED</span>
                            </div>
                          </div>

                          <div className="milestone-targets-row">
                            <span className="label">Authorized Scope Boundaries:</span>
                            <div className="target-tags">
                              {(item.targets || []).map((tgt) => (
                                <span key={tgt} className="cidr-tag">
                                  🎯 {tgt}
                                </span>
                              ))}
                            </div>
                          </div>

                          <div className="milestone-tiers-row">
                            <span className="label">Tool Access Policy:</span>
                            {item.allowed_tool_tiers && item.allowed_tool_tiers.length > 0 ? (
                              item.allowed_tool_tiers.map((t) => (
                                <span key={t} className="tier-tag">
                                  Tier {t}
                                </span>
                              ))
                            ) : (
                              <span className="tier-tag" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", borderColor: "rgba(16, 185, 129, 0.3)" }}>
                                Unified Access (ADR-004)
                              </span>
                            )}
                            {item.is_active && <span className="status-pill active">ACTIVE</span>}
                            {item.is_expired && <span className="status-pill expired">EXPIRED</span>}
                          </div>
                        </div>
                      </div>
                    );
                  }

                  const isInScope = item.scope_status === "in_scope";
                  const isViolation = item.scope_status === "scope_violation";
                  const isSuccess = item.exit_code === 0;

                  return (
                    <div
                      key={`event_${item.id || item.task_id}_${idx}`}
                      className={`timeline-event-card ${isViolation ? "violation" : ""} ${
                        selectedItem?.id === item.id ? "selected" : ""
                      }`}
                      onClick={() => setSelectedItem(item)}
                    >
                      <div className="card-top-row">
                        <div className="actor-tool-group">
                          <span className={`actor-badge ${item.actor}`}>
                            {item.actor === "agent" ? "🤖" : item.actor === "supervisor" ? "🛡️" : "👤"} {item.actor}
                          </span>
                          {item.tool_id && (
                            <span className="tool-badge">
                              ⚡ {item.tool_id} {item.tool_version ? `(v${item.tool_version})` : ""}
                            </span>
                          )}
                          {item.tool_tier && (
                            <span className={`tier-badge tier-${item.tool_tier}`}>
                              T{item.tool_tier}
                            </span>
                          )}
                        </div>

                        <div className="scope-status-group">
                          {isViolation && (
                            <span className="scope-pill violation" title={item.scope_violation_reason || "Scope Violation"}>
                              🚨 SCOPE VIOLATION
                            </span>
                          )}
                          {isInScope && (
                            <span className="scope-pill in-scope">
                              ✓ IN SCOPE
                            </span>
                          )}
                          {!isInScope && !isViolation && (
                            <span className="scope-pill unscoped">
                              ⚡ UNSCOPED
                            </span>
                          )}

                          <span className={`exit-pill ${isSuccess ? "success" : "failure"}`}>
                            {item.exit_code !== undefined ? `EXIT ${item.exit_code}` : "PENDING"}
                          </span>
                          <span className="timestamp-pill">{item.timestamp}</span>
                        </div>
                      </div>

                      <div className="card-body-row">
                        <p className="event-summary-text">
                          {item.result_summary || "Tool execution recorded in event store."}
                        </p>
                        {item.target_evaluated && (
                          <div className="target-accountability-line">
                            <span className="target-label">Target:</span>
                            <span className="target-value">{item.target_evaluated}</span>
                            {item.governing_contract_id && (
                              <span className="contract-link-pill" title="Governing Scope Contract at execution time">
                                Bound: {item.governing_contract_id}
                              </span>
                            )}
                          </div>
                        )}
                        {isViolation && item.scope_violation_reason && (
                          <div className="violation-warning-box">
                            <strong>⚠️ Policy Reason:</strong> {item.scope_violation_reason}
                          </div>
                        )}
                      </div>

                      <div className="card-meta-footer">
                        <span className="task-id-text">Task: {item.task_id}</span>
                        <span className="session-id-text">Session: {item.session_id}</span>
                        {item.process_id && <span className="pid-text">PID: {item.process_id}</span>}
                        {item.artifact_refs && (
                          <span className="artifacts-text">
                            📁 Artifacts Attached
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Deep Inspection Drawer: Scope Contract or Standard Event */}
      {selectedItem && (
        <div className="audit-drawer-backdrop" onClick={() => setSelectedItem(null)}>
          <div className="audit-drawer-pane" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <div className="drawer-title-group">
                <h3>
                  {selectedItem.is_scope_contract_milestone
                    ? "📜 Scope Contract Audit Proof"
                    : `🔍 Event Detail: ${selectedItem.tool_id || selectedItem.actor}`}
                </h3>
                <span className="drawer-sub">Timestamp: {selectedItem.timestamp}</span>
              </div>
              <button className="drawer-close-btn" onClick={() => setSelectedItem(null)}>
                ✕
              </button>
            </div>

            <div className="drawer-body">
              {selectedItem.is_scope_contract_milestone ? (
                <div className="contract-drawer-details">
                  <div className="proof-card">
                    <h4>HMAC-SHA256 Cryptographic Signature</h4>
                    <pre className="signature-box">{selectedItem.signature}</pre>
                    <div className="proof-status-row">
                      <span>Status:</span>
                      <strong
                        style={{
                          color: selectedItem.signature_valid ? "var(--accent-emerald)" : "var(--accent-rose)",
                        }}
                      >
                        {selectedItem.signature_valid ? "✓ Valid Signature (Authentic Contract)" : "✗ Invalid Signature"}
                      </strong>
                    </div>
                  </div>

                  <div className="drawer-section">
                    <h4>Contract Boundaries</h4>
                    <ul className="drawer-list">
                      <li>
                        <strong>Contract ID:</strong> {selectedItem.contract_id}
                      </li>
                      <li>
                        <strong>Created At:</strong> {selectedItem.timestamp}
                      </li>
                      <li>
                        <strong>Expires At:</strong> {selectedItem.expires_at || "Never"}
                      </li>
                      <li>
                        <strong>Targets:</strong> {(selectedItem.targets || []).join(", ")}
                      </li>
                      <li>
                        <strong>Tool Policy:</strong>{" "}
                        {selectedItem.allowed_tool_tiers && selectedItem.allowed_tool_tiers.length > 0
                          ? `Legacy Tiers: ${selectedItem.allowed_tool_tiers.join(", ")}`
                          : "Unified Access (ADR-004)"}
                      </li>
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="event-drawer-details">
                  <div className="scope-accountability-card">
                    <h4>Task 2.3 Scope Contract Accountability</h4>
                    <div className="accountability-grid">
                      <div>
                        <span>Governing Contract:</span>
                        <strong>{selectedItem.governing_contract_id || "None (Unscoped)"}</strong>
                      </div>
                      <div>
                        <span>Scope Status:</span>
                        <strong className={selectedItem.scope_status || "unscoped"}>
                          {(selectedItem.scope_status || "unscoped").toUpperCase()}
                        </strong>
                      </div>
                      <div>
                        <span>Target Evaluated:</span>
                        <strong>{selectedItem.target_evaluated || "N/A"}</strong>
                      </div>
                      <div>
                        <span>Tool Authorization:</span>
                        <strong>{selectedItem.scope_status === "in_scope" ? "Authorized (In-Scope)" : "Evaluated"}</strong>
                      </div>
                    </div>
                    {selectedItem.scope_violation_reason && (
                      <div className="drawer-violation-alert">{selectedItem.scope_violation_reason}</div>
                    )}
                  </div>

                  <div className="drawer-section">
                    <h4>Requested Arguments</h4>
                    <pre className="code-block">
                      {typeof selectedItem.requested_args === "object"
                        ? JSON.stringify(selectedItem.requested_args, null, 2)
                        : String(selectedItem.requested_args || "None")}
                    </pre>
                  </div>

                  <div className="drawer-section">
                    <h4>Normalized Arguments</h4>
                    <pre className="code-block">
                      {typeof selectedItem.normalized_args === "object"
                        ? JSON.stringify(selectedItem.normalized_args, null, 2)
                        : String(selectedItem.normalized_args || "None")}
                    </pre>
                  </div>

                  {selectedItem.stdout_ref && (
                    <div className="drawer-section">
                      <h4>Captured STDOUT</h4>
                      <pre className="code-block stdout">{selectedItem.stdout_ref}</pre>
                    </div>
                  )}

                  {selectedItem.stderr_ref && (
                    <div className="drawer-section">
                      <h4>Captured STDERR</h4>
                      <pre className="code-block stderr">{selectedItem.stderr_ref}</pre>
                    </div>
                  )}

                  <div className="drawer-section">
                    <h4>Raw Event JSON</h4>
                    <pre className="code-block raw">{JSON.stringify(selectedItem, null, 2)}</pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Deep Inspection Drawer: Model Evolution Event */}
      {selectedEvolutionItem && (
        <div className="audit-drawer-backdrop" onClick={() => setSelectedEvolutionItem(null)}>
          <div className="audit-drawer-pane evolution-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <div className="drawer-title-group">
                <h3>
                  🧬 Model Evolution Proof: {selectedEvolutionItem.event_type}
                </h3>
                <span className="drawer-sub">
                  ID: {selectedEvolutionItem.id} • Timestamp: {selectedEvolutionItem.timestamp}
                </span>
              </div>
              <button className="drawer-close-btn" onClick={() => setSelectedEvolutionItem(null)}>
                ✕
              </button>
            </div>

            <div className="drawer-body">
              {/* Plain-Language Rationale Box */}
              <div className="proof-card evolution-proof">
                <h4>Plain-Language Summary &amp; Decision Rationale</h4>
                <div className="evolution-quote-box drawer-quote">
                  <span className="quote-mark">“</span>
                  <span className="plain-language-headline">{selectedEvolutionItem.plain_language_summary}</span>
                  <span className="quote-mark">”</span>
                </div>
                {selectedEvolutionItem.rationale && (
                  <p className="drawer-rationale-full">{selectedEvolutionItem.rationale}</p>
                )}
              </div>

              {/* Justifying Benchmark Evidence */}
              <div className="drawer-section">
                <h4>Justifying Benchmark Sweep Evidence</h4>
                <p className="justification-text">{selectedEvolutionItem.benchmark_justification}</p>

                {/* Side-by-side Sweep Comparison Table */}
                {selectedEvolutionItem.comparisons && (
                  <div className="eval-comparison-table-wrap" style={{ marginTop: "12px" }}>
                    <div className="comparison-table-title">
                      <span>Full Tracked Metric Comparison</span>
                      <span className="comparison-subtitle font-mono">
                        {selectedEvolutionItem.active_model_id} ➔ {selectedEvolutionItem.checkpoint_model_id}
                      </span>
                    </div>
                    <table className="eval-comparison-table">
                      <thead>
                        <tr>
                          <th>Tracked Metric</th>
                          <th>Active Baseline</th>
                          <th>New Checkpoint</th>
                          <th>Delta</th>
                          <th>Result</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(selectedEvolutionItem.comparisons).map(([mk, cmp]) => {
                          const delta = cmp.delta;
                          const isReg = selectedEvolutionItem.regressions?.some((r) => r.metric === mk);
                          const isImp = selectedEvolutionItem.improvements?.some((i) => i.metric === mk);

                          return (
                            <tr key={mk} className={isReg ? "row-regressed" : isImp ? "row-improved" : "row-neutral"}>
                              <td className="metric-cell-name font-mono">{formatMetricName(mk)}</td>
                              <td className="metric-cell-val font-mono">{cmp.active_val.toFixed(1)}%</td>
                              <td className="metric-cell-val font-mono">{cmp.new_val.toFixed(1)}%</td>
                              <td className={`metric-cell-delta font-mono ${delta > 0 ? "gain" : delta < 0 ? "drop" : "neutral"}`}>
                                {delta > 0 ? `+${delta.toFixed(1)}%` : `${delta.toFixed(1)}%`}
                              </td>
                              <td>
                                {isReg ? (
                                  <span className="eval-status-pill regressed">Regressed (&gt;1%)</span>
                                ) : isImp ? (
                                  <span className="eval-status-pill improved">▲ Beat Baseline</span>
                                ) : (
                                  <span className="eval-status-pill satisfied">✓ Within Tolerance</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Justifying Sweep Numbers / Trigger Metrics JSON */}
              {selectedEvolutionItem.justifying_sweep_numbers && (
                <div className="drawer-section">
                  <h4>Justifying Numbers (Raw Snapshot)</h4>
                  <pre className="code-block">
                    {JSON.stringify(selectedEvolutionItem.justifying_sweep_numbers, null, 2)}
                  </pre>
                </div>
              )}

              {/* Hardware Cost & Parameters */}
              {(selectedEvolutionItem.estimated_cost || selectedEvolutionItem.parameters) && (
                <div className="drawer-section">
                  <h4>Hardware, Duration &amp; Parameters</h4>
                  <ul className="drawer-list">
                    {selectedEvolutionItem.estimated_cost?.expected_duration_human && (
                      <li>
                        <strong>Expected Duration:</strong>{" "}
                        {selectedEvolutionItem.estimated_cost.expected_duration_human}
                      </li>
                    )}
                    {selectedEvolutionItem.estimated_cost?.compute_hardware && (
                      <li>
                        <strong>Compute Hardware:</strong>{" "}
                        {selectedEvolutionItem.estimated_cost.compute_hardware}
                      </li>
                    )}
                    {selectedEvolutionItem.estimated_cost?.historical_basis && (
                      <li>
                        <strong>Historical Basis:</strong>{" "}
                        {selectedEvolutionItem.estimated_cost.historical_basis}
                      </li>
                    )}
                  </ul>
                  {selectedEvolutionItem.parameters && (
                    <pre className="code-block" style={{ marginTop: "8px" }}>
                      {JSON.stringify(selectedEvolutionItem.parameters, null, 2)}
                    </pre>
                  )}
                </div>
              )}

              {/* Full Raw Event Payload */}
              <div className="drawer-section">
                <h4>Raw Evolution Event Payload</h4>
                <pre className="code-block raw">{JSON.stringify(selectedEvolutionItem, null, 2)}</pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
