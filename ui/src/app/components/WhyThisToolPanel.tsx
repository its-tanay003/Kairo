"use client";

import React, { useState, useEffect } from "react";

export interface DimensionScore {
  name: string;
  weight: number;
  weight_pct: number;
  score: number;
  score_pct: number;
  weighted_score: number;
  raw_signal: string;
}

export interface CandidateBreakdown {
  tool_id: string;
  tool_name: string;
  version: string;
  category: string;
  rank: number;
  total_score: number;
  score_pct: number;
  dimension_scores: DimensionScore[];
  inferred_args?: Record<string, unknown>;
}

export interface ToolSelectionResult {
  selected_tool: CandidateBreakdown;
  candidates: CandidateBreakdown[];
  selection_reason?: string;
  evaluated_count?: number;
  weights_used?: Record<string, number>;
}

interface WhyThisToolPanelProps {
  toolSelection?: ToolSelectionResult;
  toolId?: string;
  defaultExpanded?: boolean;
}

const DIMENSION_CONFIG: Record<
  string,
  { label: string; icon: string; weightLabel: string }
> = {
  semantic_fit: {
    label: "Semantic Fit",
    icon: "🎯",
    weightLabel: "30%",
  },
  capability_coverage: {
    label: "Capability Coverage",
    icon: "🛡️",
    weightLabel: "20%",
  },
  environment_compatibility: {
    label: "Environment Compatibility",
    icon: "💻",
    weightLabel: "15%",
  },
  expected_signal: {
    label: "Expected Signal Quality",
    icon: "📡",
    weightLabel: "10%",
  },
  reliability_history: {
    label: "Reliability History",
    icon: "📈",
    weightLabel: "10%",
  },
  execution_cost: {
    label: "Execution Cost Efficiency",
    icon: "⚡",
    weightLabel: "5%",
  },
  prior_task_success: {
    label: "Prior Task Success",
    icon: "🏆",
    weightLabel: "10%",
  },
};

export default function WhyThisToolPanel({
  toolSelection: initialSelection,
  toolId,
  defaultExpanded = false,
}: WhyThisToolPanelProps) {
  const [isExpanded, setIsExpanded] = useState<boolean>(defaultExpanded);
  const [fetchedSelection, setFetchedSelection] = useState<ToolSelectionResult | null>(null);
  const [selectedCandidateIndex, setSelectedCandidateIndex] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const selection = initialSelection || fetchedSelection;

  // If no selection was passed but a toolId is present, fetch selection analysis on demand
  useEffect(() => {
    let active = true;
    if (!selection && toolId && isExpanded) {
      fetch("http://localhost:4000/tools/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intent: `Execute tool ${toolId}`,
          capability: toolId.split(".")[0],
        }),
      })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (active && data && data.candidates) {
            setFetchedSelection(data);
          }
        })
        .catch(() => {})
        .finally(() => {
          if (active) setIsLoading(false);
        });
    }
    return () => {
      active = false;
    };
  }, [selection, toolId, isExpanded]);

  const candidates = selection?.candidates || [];
  const currentCandidate =
    candidates[selectedCandidateIndex] || selection?.selected_tool || candidates[0];

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return "var(--accent-emerald, #10b981)";
    if (score >= 0.5) return "var(--accent-amber, #f59e0b)";
    return "var(--accent-rose, #f43f5e)";
  };

  return (
    <div className="why-tool-container">
      {/* Accordion Toggle Header */}
      <div
        className={`why-tool-header ${isExpanded ? "expanded" : ""}`}
        onClick={() => setIsExpanded(!isExpanded)}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        title="Toggle Why This Tool factor breakdown"
      >
        <div className="why-tool-title-group">
          <span className="why-tool-badge">🔍 WHY THIS TOOL</span>
          <span className="why-tool-name">
            {currentCandidate
              ? `${currentCandidate.tool_name} (Score: ${(
                  currentCandidate.total_score || 0
                ).toFixed(3)})`
              : `Tool Selection Analysis (${toolId || "Active Tool"})`}
          </span>
          {currentCandidate && (
            <span
              className="why-tool-rank-badge"
              style={{
                borderColor: getScoreColor(currentCandidate.total_score),
                color: getScoreColor(currentCandidate.total_score),
              }}
            >
              Rank #{currentCandidate.rank} of {candidates.length || 3}
            </span>
          )}
        </div>

        <div className="why-tool-toggle-icon">
          <span>{isExpanded ? "▲ Hide Breakdown" : "▼ Expand Analysis"}</span>
        </div>
      </div>

      {/* Expanded Content Panel */}
      {isExpanded && (
        <div className="why-tool-body">
          {isLoading && !selection && (
            <div className="why-tool-loading">
              <span className="dot running" /> Evaluating hybrid tool-selection scores...
            </div>
          )}

          {/* Top 3 Candidate Selector Tabs */}
          {candidates.length > 0 && (
            <div className="candidate-tabs-bar">
              <span className="candidate-tabs-label">Top Evaluated Candidates:</span>
              <div className="candidate-tabs-list">
                {candidates.slice(0, 3).map((cand, idx) => {
                  const isSelected = idx === selectedCandidateIndex;
                  return (
                    <button
                      key={cand.tool_id}
                      className={`candidate-tab-btn ${isSelected ? "active" : ""}`}
                      onClick={() => setSelectedCandidateIndex(idx)}
                    >
                      <span className="candidate-rank">#{cand.rank}</span>
                      <span className="candidate-name">{cand.tool_id}</span>
                      <span
                        className="candidate-score"
                        style={{ color: getScoreColor(cand.total_score) }}
                      >
                        {cand.total_score.toFixed(3)} ({cand.score_pct}%)
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {currentCandidate ? (
            <div className="candidate-details-pane">
              {/* Formula & Overall Metric Banner */}
              <div className="formula-banner">
                <div className="formula-left">
                  <span className="formula-title">
                    📐 Formula: Score = 0.30·fit + 0.20·cap + 0.15·env + 0.10·sig + 0.10·rel + 0.05·cost + 0.10·prior
                  </span>
                  <p className="formula-desc">
                    {selection?.selection_reason ||
                      `Candidate #${currentCandidate.rank} scored ${currentCandidate.total_score.toFixed(
                        3
                      )} across 7 empirical dimensions.`}
                  </p>
                </div>
                <div className="formula-score-box">
                  <div
                    className="formula-big-score"
                    style={{ color: getScoreColor(currentCandidate.total_score) }}
                  >
                    {(currentCandidate.total_score * 100).toFixed(1)}%
                  </div>
                  <div className="formula-score-label">Overall Index</div>
                </div>
              </div>

              {/* 7 Factor Dimension Breakdown */}
              <div className="factors-grid">
                {(currentCandidate.dimension_scores || []).map((dim) => {
                  const cfg = DIMENSION_CONFIG[dim.name] || {
                    label: dim.name,
                    icon: "🔹",
                    weightLabel: `${dim.weight_pct}%`,
                  };
                  const color = getScoreColor(dim.score);

                  return (
                    <div key={dim.name} className="factor-card">
                      {/* Factor Header */}
                      <div className="factor-header">
                        <div className="factor-name-group">
                          <span className="factor-icon">{cfg.icon}</span>
                          <span className="factor-label">{cfg.label}</span>
                          <span className="factor-weight-pill">
                            Weight: {cfg.weightLabel}
                          </span>
                        </div>
                        <div className="factor-score-group">
                          <span
                            className="factor-score-val"
                            style={{ color }}
                          >
                            {(dim.score).toFixed(2)} ({dim.score_pct}%)
                          </span>
                          <span className="factor-contribution">
                            +{dim.weighted_score.toFixed(3)} pts
                          </span>
                        </div>
                      </div>

                      {/* Visual Score Bar */}
                      <div className="factor-bar-track">
                        <div
                          className="factor-bar-fill"
                          style={{
                            width: `${Math.min(100, Math.max(0, dim.score_pct))}%`,
                            background: `linear-gradient(90deg, ${color} 0%, rgba(56, 189, 248, 0.9) 100%)`,
                          }}
                        />
                      </div>

                      {/* Raw Empirical Signal Box */}
                      <div className="factor-raw-signal">
                        <span className="raw-signal-tag">SIGNAL</span>
                        <span className="raw-signal-text">
                          {dim.name}: {dim.score.toFixed(2)} — {dim.raw_signal}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Inferred Arguments Box (if present) */}
              {currentCandidate.inferred_args &&
                Object.keys(currentCandidate.inferred_args).length > 0 && (
                  <div className="inferred-args-box">
                    <span className="inferred-args-title">
                      ⚙️ Synthesized Execution Arguments:
                    </span>
                    <code>
                      {JSON.stringify(currentCandidate.inferred_args, null, 2)}
                    </code>
                  </div>
                )}

              {/* Competitive Differentiation Footer */}
              <div className="transparency-callout">
                <span className="callout-icon">✨</span>
                <span>
                  <strong>Full Decision Observability:</strong> Unlike black-box ReAct loops
                  that make arbitrary LLM tool choices, Kairo exposes the exact weighted utility
                  and empirical reliability history for every candidate.
                </span>
              </div>
            </div>
          ) : (
            <div className="why-tool-empty">
              No tool candidate breakdown available for this card.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
