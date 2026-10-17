"use client";

import React, { useCallback, useEffect, useState } from "react";

export interface EvolutionProposal {
  proposal_id: string;
  timestamp: string;
  rule_name: string;
  action: string;
  job_type?: string;
  target_preset?: string;
  rationale: string;
  plain_language_summary?: string;
  trigger_metrics?: Record<string, unknown>;
  estimated_cost?: {
    expected_duration_seconds?: number;
    expected_duration_human?: string;
    compute_hardware?: string;
    estimated_gpu_hours?: number;
    historical_basis?: string;
  };
  recommended_parameters?: Record<string, unknown>;
  status: "PROPOSED" | "APPROVED" | "DISMISSED";
  approved_at?: string;
  approved_by?: string;
  executed_job?: Record<string, unknown>;
  dismissed_at?: string;
  dismissed_by?: string;
  dismiss_reason?: string;
  event_id?: number;
}

export interface EvolutionEvaluation {
  evaluation_id: string;
  timestamp: string;
  job_id: string;
  job_type?: string;
  preset?: string;
  checkpoint_model_id: string;
  active_model_id: string;
  decision: "PROMOTED" | "NOT_PROMOTED";
  promoted: boolean;
  plain_language_notice: string;
  comparisons: Record<
    string,
    {
      new_val: number;
      active_val: number;
      delta: number;
      delta_pct: number;
    }
  >;
  new_checkpoint_metrics?: Record<string, number>;
  active_model_metrics?: Record<string, number>;
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
}

export interface ControllerStatus {
  running: boolean;
  cycle_count: number;
  last_cycle_timestamp: string | null;
  last_cycle_summary: string | null;
  total_proposals_recorded: number;
  total_evaluations_recorded?: number;
  policy_file: string;
  active_model: string;
  polling_interval_seconds: number;
  recent_logs: string[];
}

interface ModelEvolutionPanelProps {
  apiBaseUrl?: string;
  onJobDispatched?: (job: Record<string, unknown>) => void;
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

export default function ModelEvolutionPanel({
  apiBaseUrl = "http://127.0.0.1:8000",
  onJobDispatched,
}: ModelEvolutionPanelProps) {
  const [proposals, setProposals] = useState<EvolutionProposal[]>([]);
  const [evaluations, setEvaluations] = useState<EvolutionEvaluation[]>([]);
  const [status, setStatus] = useState<ControllerStatus | null>(null);
  const [filterMode, setFilterMode] = useState<"pending" | "evaluations" | "approved" | "dismissed" | "all">("pending");
  const [loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ msg: string; type: "success" | "error" | "info" } | null>(null);
  const [expandedProposalId, setExpandedProposalId] = useState<string | null>(null);

  const showToast = (msg: string, type: "success" | "error" | "info" = "info") => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 5000);
  };

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/evolution/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch {
      // Graceful offline fallback
    }
  }, [apiBaseUrl]);

  const fetchProposals = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${apiBaseUrl}/evolution/proposals?limit=100`);
      if (res.ok) {
        const data = await res.json();
        setProposals(data.proposals || []);
      }
    } catch (e) {
      console.error("Failed to fetch evolution proposals:", e);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  const fetchEvaluations = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/evolution/evaluations?limit=50`);
      if (res.ok) {
        const data = await res.json();
        setEvaluations(data.evaluations || []);
      }
    } catch (e) {
      console.error("Failed to fetch evaluations:", e);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    let active = true;
    const runFetch = async () => {
      try {
        const [statusRes, propsRes, evalRes] = await Promise.all([
          fetch(`${apiBaseUrl}/evolution/status`),
          fetch(`${apiBaseUrl}/evolution/proposals?limit=100`),
          fetch(`${apiBaseUrl}/evolution/evaluations?limit=50`),
        ]);
        if (active && statusRes.ok) {
          const s = await statusRes.json();
          setStatus(s);
        }
        if (active && propsRes.ok) {
          const p = await propsRes.json();
          setProposals(p.proposals || []);
        }
        if (active && evalRes.ok) {
          const ev = await evalRes.json();
          setEvaluations(ev.evaluations || []);
        }
      } catch {
        // Ignore offline poll
      }
    };

    runFetch();
    const interval = setInterval(runFetch, 10000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [apiBaseUrl]);

  const handleRunCycle = async () => {
    try {
      setActionInProgress("cycle");
      const res = await fetch(`${apiBaseUrl}/evolution/cycle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        const genCount = data.proposals_generated?.length || 0;
        showToast(
          genCount > 0
            ? `Cycle complete: ${genCount} new proposal(s) formulated.`
            : `Cycle complete: All rules evaluated, no new proposals needed.`,
          genCount > 0 ? "success" : "info"
        );
        fetchStatus();
        fetchProposals();
        fetchEvaluations();
      } else {
        showToast("Error running policy evaluation cycle.", "error");
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(`Policy check failed: ${msg}`, "error");
    } finally {
      setActionInProgress(null);
    }
  };

  const handleSweepCompletedJobs = async () => {
    try {
      setActionInProgress("sweep_jobs");
      const res = await fetch(`${apiBaseUrl}/evolution/evaluate-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        const data = await res.json();
        const count = data.count || 0;
        showToast(
          count > 0
            ? `Evaluated ${count} completed checkpoint(s).`
            : `Completed checkpoint evaluation: No un-evaluated jobs waiting.`,
          "info"
        );
        fetchEvaluations();
        fetchStatus();
      } else {
        showToast("Failed to evaluate completed checkpoints.", "error");
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(`Evaluation error: ${msg}`, "error");
    } finally {
      setActionInProgress(null);
    }
  };

  const handleManualActivate = async (checkpointModelId: string) => {
    try {
      setActionInProgress(checkpointModelId);
      const res = await fetch(`${apiBaseUrl}/model-center/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: checkpointModelId }),
      });
      if (res.ok) {
        showToast(`Model Center: Activated checkpoint "${checkpointModelId}" manually.`, "success");
        fetchStatus();
        fetchEvaluations();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(`Activation failed: ${err.detail || "Server error"}`, "error");
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(`Activation error: ${msg}`, "error");
    } finally {
      setActionInProgress(null);
    }
  };

  const handleApprove = async (proposal: EvolutionProposal) => {
    try {
      setActionInProgress(proposal.proposal_id);
      const res = await fetch(`${apiBaseUrl}/evolution/proposals/${encodeURIComponent(proposal.proposal_id)}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operator: "operator_secops" }),
      });
      if (res.ok) {
        const data = await res.json();
        const job = data.dispatched_job;
        showToast(
          `✓ Approved! Dispatched training run: ${job?.id || proposal.action}`,
          "success"
        );
        if (onJobDispatched && job) {
          onJobDispatched(job);
        }
        fetchProposals();
        fetchStatus();
      } else {
        const errData = await res.json().catch(() => ({}));
        showToast(`Approval failed: ${errData.detail || "Server error"}`, "error");
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(`Approval error: ${msg}`, "error");
    } finally {
      setActionInProgress(null);
    }
  };

  const handleDismiss = async (proposal: EvolutionProposal) => {
    try {
      setActionInProgress(proposal.proposal_id);
      const res = await fetch(`${apiBaseUrl}/evolution/proposals/${encodeURIComponent(proposal.proposal_id)}/dismiss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operator: "operator_secops", reason: "Operator dismissed from UI" }),
      });
      if (res.ok) {
        showToast(`Proposal dismissed. No training job was started.`, "info");
        fetchProposals();
        fetchStatus();
      } else {
        const errData = await res.json().catch(() => ({}));
        showToast(`Dismiss failed: ${errData.detail || "Server error"}`, "error");
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(`Dismiss error: ${msg}`, "error");
    } finally {
      setActionInProgress(null);
    }
  };

  const pendingList = proposals.filter((p) => p.status === "PROPOSED");
  const approvedList = proposals.filter((p) => p.status === "APPROVED");
  const dismissedList = proposals.filter((p) => p.status === "DISMISSED");

  const filteredProposals = proposals.filter((p) => {
    if (filterMode === "pending") return p.status === "PROPOSED";
    if (filterMode === "approved") return p.status === "APPROVED";
    if (filterMode === "dismissed") return p.status === "DISMISSED";
    return true;
  });

  const getActionBadge = (ruleName: string) => {
    switch (ruleName) {
      case "sft_refresh":
        return <span className="evolution-badge sft">SFT Refresh</span>;
      case "tier_scaling":
        return <span className="evolution-badge scaling">Tier Scaling</span>;
      case "regression_rollback":
        return <span className="evolution-badge rollback">Regression Rollback</span>;
      default:
        return <span className="evolution-badge generic">{ruleName}</span>;
    }
  };

  return (
    <div className="model-evolution-container">
      {/* Toast Notification */}
      {notification && (
        <div className={`evolution-toast ${notification.type}`}>
          <span>{notification.msg}</span>
          <button onClick={() => setNotification(null)}>✕</button>
        </div>
      )}

      {/* Header Banner & Human-in-the-Loop Guarantee */}
      <div className="evolution-header-card">
        <div className="evolution-header-content">
          <div className="evolution-title-row">
            <span className="evolution-icon">🧬</span>
            <div>
              <h3>Model Evolution Controller & Auto-Promotion Gate</h3>
              <p className="evolution-subtitle">
                Autonomous policy monitors benchmark sweeps, evaluates completed checkpoints, and guards against performance regressions.
              </p>
            </div>
          </div>
          <div className="evolution-quick-actions">
            <button
              className="action-pill-btn primary"
              onClick={handleRunCycle}
              disabled={actionInProgress === "cycle"}
              title="Runs a synchronous check against current dataset & benchmark metrics"
            >
              {actionInProgress === "cycle" ? "↻ Checking..." : "↻ Evaluate Policy Cycle"}
            </button>
            <button
              className="action-pill-btn"
              onClick={handleSweepCompletedJobs}
              disabled={actionInProgress === "sweep_jobs"}
              title="Runs Part-A benchmark sweep on any completed training checkpoints"
            >
              {actionInProgress === "sweep_jobs" ? "↻ Evaluating..." : "⚡ Sweep Completed Runs"}
            </button>
            <button
              className="action-pill-btn"
              onClick={() => {
                fetchStatus();
                fetchProposals();
                fetchEvaluations();
              }}
              title="Refresh list"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Human-in-the-loop Security Callout & Auto-Promotion Boundary */}
        <div className="evolution-guarantee-box">
          <span className="guarantee-shield">🛡️</span>
          <div className="guarantee-text">
            <strong>Safety Boundaries:</strong>
            <ul className="safety-bullets">
              <li>
                <strong>Gated Action (Starting Jobs):</strong> Only human approval dispatches multi-hour training runs to protect local compute.
              </li>
              <li>
                <strong>Automated Action (Evaluating Completed Jobs):</strong> Finished checkpoints are automatically benchmarked and auto-promoted if superior, or guarded with zero weight deletion if regressed.
              </li>
            </ul>
          </div>
        </div>
      </div>

      {/* Controller Telemetry Ribbon */}
      {status && (
        <div className="evolution-telemetry-ribbon">
          <div className="telem-item">
            <span className="telem-label">Controller State</span>
            <span className="telem-val">
              <span className={`status-dot ${status.running ? "success" : "idle"}`} />
              {status.running ? "Loop Active" : "On-Demand"}
            </span>
          </div>
          <div className="telem-item">
            <span className="telem-label">Active Model</span>
            <span className="telem-val font-mono">{status.active_model}</span>
          </div>
          <div className="telem-item">
            <span className="telem-label">Evaluated Cycles</span>
            <span className="telem-val">{status.cycle_count}</span>
          </div>
          <div className="telem-item">
            <span className="telem-label">Pending Decisions</span>
            <span className="telem-val highlight">{pendingList.length}</span>
          </div>
          <div className="telem-item">
            <span className="telem-label">Evaluated Runs</span>
            <span className="telem-val info-highlight">{evaluations.length}</span>
          </div>
        </div>
      )}

      {/* Filter Tabs Bar */}
      <div className="evolution-filter-strip">
        <button
          className={`filter-pill ${filterMode === "pending" ? "active" : ""}`}
          onClick={() => setFilterMode("pending")}
        >
          Pending Decisions ({pendingList.length})
          {pendingList.length > 0 && <span className="count-badge warning">{pendingList.length}</span>}
        </button>
        <button
          className={`filter-pill ${filterMode === "evaluations" ? "active" : ""}`}
          onClick={() => setFilterMode("evaluations")}
        >
          Auto-Evaluated Runs ({evaluations.length})
          {evaluations.length > 0 && <span className="count-badge info">{evaluations.length}</span>}
        </button>
        <button
          className={`filter-pill ${filterMode === "approved" ? "active" : ""}`}
          onClick={() => setFilterMode("approved")}
        >
          Approved History ({approvedList.length})
        </button>
        <button
          className={`filter-pill ${filterMode === "dismissed" ? "active" : ""}`}
          onClick={() => setFilterMode("dismissed")}
        >
          Dismissed ({dismissedList.length})
        </button>
        <button
          className={`filter-pill ${filterMode === "all" ? "active" : ""}`}
          onClick={() => setFilterMode("all")}
        >
          All Proposals ({proposals.length})
        </button>
      </div>

      {/* Auto-Evaluations View (Task C.3) */}
      {filterMode === "evaluations" ? (
        <div className="evaluations-list-section">
          {evaluations.length === 0 ? (
            <div className="empty-proposals-card">
              <span className="empty-icon">✓</span>
              <h4>No Completed Runs Evaluated Yet</h4>
              <p>
                When a training job finishes, Model Evolution Controller automatically executes a Part-A benchmark sweep on the new checkpoint, compares every tracked metric against the active baseline, and auto-promotes or safeguards the active model.
              </p>
              <button
                className="action-pill-btn primary"
                onClick={handleSweepCompletedJobs}
                disabled={actionInProgress === "sweep_jobs"}
              >
                {actionInProgress === "sweep_jobs" ? "Checking Completed Runs..." : "⚡ Check Completed Runs Now"}
              </button>
            </div>
          ) : (
            evaluations.map((ev) => {
              const isPromoted = ev.promoted;
              return (
                <div
                  key={ev.evaluation_id}
                  className={`evaluation-card ${isPromoted ? "eval-promoted" : "eval-guarded"}`}
                >
                  {/* Evaluation Header */}
                  <div className="eval-card-header">
                    <div className="eval-header-meta">
                      <div className="eval-badge-row">
                        {isPromoted ? (
                          <span className="eval-status-badge promoted">✓ AUTO-PROMOTED TO ACTIVE</span>
                        ) : (
                          <span className="eval-status-badge guarded">🛡️ ROLLBACK GUARDED — NOT PROMOTED</span>
                        )}
                        <span className="eval-model-tag font-mono">{ev.checkpoint_model_id}</span>
                        <span className="eval-job-ref font-mono">Job: {ev.job_id}</span>
                      </div>
                      <span className="eval-timestamp">
                        {new Date(ev.timestamp).toLocaleString([], {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>
                  </div>

                  {/* Plain-Language Notice Banner */}
                  <div className={`eval-notice-box ${isPromoted ? "notice-promoted" : "notice-guarded"}`}>
                    <span className="notice-icon">{isPromoted ? "🚀" : "⚠️"}</span>
                    <div className="notice-body">
                      <strong className="notice-title">
                        {isPromoted ? "Autonomous Model Promotion" : "Regression Safeguard Notice"}
                      </strong>
                      <p className="notice-plain-text">{ev.plain_language_notice}</p>
                    </div>

                    {!isPromoted && (
                      <div className="notice-actions">
                        <button
                          className="action-pill-btn manual-activate-btn"
                          onClick={() => handleManualActivate(ev.checkpoint_model_id)}
                          disabled={actionInProgress === ev.checkpoint_model_id}
                          title="Manually set this model as active in Model Center"
                        >
                          {actionInProgress === ev.checkpoint_model_id ? "Activating..." : "Activate in Model Center"}
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Benchmark Comparison Table */}
                  <div className="eval-comparison-table-wrap">
                    <div className="comparison-table-title">
                      <span>Part-A Golden Sweep Metric Comparison</span>
                      <span className="comparison-subtitle font-mono">
                        Active Baseline: {ev.active_model_id} ➔ Checkpoint: {ev.checkpoint_model_id}
                      </span>
                    </div>

                    <table className="eval-comparison-table">
                      <thead>
                        <tr>
                          <th>Tracked Metric</th>
                          <th>Active Baseline ({ev.active_model_id})</th>
                          <th>New Checkpoint ({ev.checkpoint_model_id})</th>
                          <th>Delta</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(ev.comparisons || {}).map(([metricKey, cmp]) => {
                          const delta = cmp.delta;
                          const isRegressed = ev.regressions?.some((r) => r.metric === metricKey);
                          const isImproved = ev.improvements?.some((i) => i.metric === metricKey);

                          return (
                            <tr
                              key={metricKey}
                              className={isRegressed ? "row-regressed" : isImproved ? "row-improved" : "row-neutral"}
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
                              <td className="metric-cell-status">
                                {isRegressed ? (
                                  <span className="eval-status-pill regressed">Regressed (&gt;1% drop)</span>
                                ) : isImproved ? (
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

                  {/* Safety Guarantee Footer */}
                  <div className="eval-card-footer">
                    <span className="footer-invariant">
                      🔒 <strong>Preservation Guarantee:</strong> Checkpoint weights remain permanently preserved in <code>training/checkpoints/</code>. Nothing is ever deleted.
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      ) : (
        /* Proposals List Section */
        <div className="proposals-list-section">
          {loading && proposals.length === 0 ? (
            <div className="empty-proposals-card">
              <span>Loading evolution proposals...</span>
            </div>
          ) : filteredProposals.length === 0 ? (
            <div className="empty-proposals-card">
              <span className="empty-icon">✓</span>
              <h4>No {filterMode} proposals</h4>
              <p>
                {filterMode === "pending"
                  ? "The controller has evaluated all rules. Dataset thresholds (>=2,000 new examples) and plateau checks have not triggered any pending actions."
                  : "No proposals recorded in this category yet."}
              </p>
              {filterMode === "pending" && (
                <button className="action-pill-btn primary" onClick={handleRunCycle}>
                  Trigger Manual Check Cycle
                </button>
              )}
            </div>
          ) : (
            filteredProposals.map((prop) => {
              const isPending = prop.status === "PROPOSED";
              const isApproved = prop.status === "APPROVED";
              const isDismissed = prop.status === "DISMISSED";
              const isBusy = actionInProgress === prop.proposal_id;
              const isExpanded = expandedProposalId === prop.proposal_id;

              const plainLanguageText =
                prop.plain_language_summary ||
                (prop.rule_name === "sft_refresh"
                  ? `Propose: retrain ${prop.target_preset || "kairo-scale-1.2b"} on ${(
                      Number(prop.trigger_metrics?.new_examples_since_last_run) || 2000
                    ).toLocaleString()} new examples (validity ${Math.round(
                      (Number(prop.trigger_metrics?.schema_validity_pass_rate) || 0.94) * 100
                    )}%). Estimated time: ~${prop.estimated_cost?.expected_duration_human || "3.5 hours"} on this hardware.`
                  : prop.rule_name === "tier_scaling"
                  ? `Propose: scale parameter tier to ${prop.target_preset || "kairo-3b"} after 3 consecutive plateaus (<1% accuracy delta). Estimated time: ~${
                      prop.estimated_cost?.expected_duration_human || "30m"
                    } on this hardware.`
                  : `Propose: rollback active model to last known-good checkpoint ${
                      prop.target_preset || "kairo-scale-1.2b"
                    } (regression detected). Estimated time: instantaneous.`);

              return (
                <div
                  key={prop.proposal_id}
                  className={`proposal-card ${prop.rule_name} ${prop.status.toLowerCase()}`}
                >
                  {/* Primary Plain-Language Header Card */}
                  <div className="proposal-primary-row">
                    <div className="proposal-meta-left">
                      <div className="proposal-tag-row">
                        {getActionBadge(prop.rule_name)}
                        <span className="proposal-id-tag font-mono">{prop.proposal_id}</span>
                        <span className="proposal-timestamp">
                          {new Date(prop.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </div>

                      {/* Prominent Plain-Language Summary Requirement */}
                      <div className="plain-language-card-body">
                        <div className="proposal-quote-box">
                          <span className="quote-mark">“</span>
                          <span className="plain-language-headline">{plainLanguageText}</span>
                          <span className="quote-mark">”</span>
                        </div>
                      </div>
                    </div>

                    {/* Approve / Dismiss Action Buttons (Human Gate) */}
                    <div className="proposal-action-block">
                      {isPending && (
                        <div className="action-buttons-group">
                          <button
                            className="btn-approve"
                            onClick={() => handleApprove(prop)}
                            disabled={isBusy}
                            title="Authorize and dispatch training run immediately"
                          >
                            {isBusy ? "Dispatching..." : "✓ Approve"}
                          </button>
                          <button
                            className="btn-dismiss"
                            onClick={() => handleDismiss(prop)}
                            disabled={isBusy}
                            title="Dismiss proposal without starting any training"
                          >
                            ✕ Dismiss
                          </button>
                        </div>
                      )}

                      {isApproved && (
                        <div className="resolution-badge approved">
                          <span>✓ APPROVED</span>
                          {prop.executed_job?.id ? (
                            <span className="job-link font-mono">{String(prop.executed_job.id)}</span>
                          ) : null}
                        </div>
                      )}

                      {isDismissed && (
                        <div className="resolution-badge dismissed">
                          <span>✕ DISMISSED</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Secondary Collapsible Details Strip */}
                  <div className="proposal-secondary-strip">
                    <div className="strip-left">
                      <span className="cost-tag">
                        ⏱️ Cost Estimate: <strong>{prop.estimated_cost?.expected_duration_human || "N/A"}</strong> (
                        {prop.estimated_cost?.compute_hardware || "Local Compute"})
                      </span>
                      {prop.trigger_metrics?.schema_validity_pass_rate != null && (
                        <span className="validity-tag">
                          🎯 Schema Pass:{" "}
                          <strong>{(Number(prop.trigger_metrics.schema_validity_pass_rate) * 100).toFixed(1)}%</strong>
                        </span>
                      )}
                    </div>

                    <button
                      className="toggle-details-btn"
                      onClick={() => setExpandedProposalId(isExpanded ? null : prop.proposal_id)}
                    >
                      {isExpanded ? "Hide Evidence Details ▲" : "Inspect Decision Evidence ▼"}
                    </button>
                  </div>

                  {/* Expanded Inspection Drawer */}
                  {isExpanded && (
                    <div className="proposal-expanded-drawer">
                      <div className="drawer-grid">
                        <div className="drawer-col">
                          <h4>Exact Decision Rationale</h4>
                          <p className="rationale-text">{prop.rationale}</p>

                          <h4>Hardware Basis</h4>
                          <p className="basis-text">{prop.estimated_cost?.historical_basis || "Local GPU profile."}</p>
                        </div>

                        <div className="drawer-col">
                          <h4>Trigger Metrics Snapshot</h4>
                          <div className="metrics-kv-table">
                            {prop.trigger_metrics &&
                              Object.entries(prop.trigger_metrics).map(([k, v]) => (
                                <div key={k} className="kv-row">
                                  <span className="kv-key">{k}</span>
                                  <span className="kv-val font-mono">{String(v)}</span>
                                </div>
                              ))}
                          </div>

                          {prop.recommended_parameters && (
                            <>
                              <h4 style={{ marginTop: "10px" }}>Dispatched Parameters</h4>
                              <div className="metrics-kv-table">
                                {Object.entries(prop.recommended_parameters).map(([k, v]) => (
                                  <div key={k} className="kv-row">
                                    <span className="kv-key">{k}</span>
                                    <span className="kv-val font-mono">{String(v)}</span>
                                  </div>
                                ))}
                              </div>
                            </>
                          )}

                          {prop.event_id && (
                            <div className="event-store-ref">
                              Event Store Audit Entry: <code>#{prop.event_id}</code>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
