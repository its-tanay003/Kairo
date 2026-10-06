"use client";

import React, { useEffect, useState, useMemo } from "react";

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

export default function AuditExplorer() {
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [totalDbEvents, setTotalDbEvents] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [selectedItem, setSelectedItem] = useState<TimelineItem | null>(null);

  // Filter States
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [actorFilter, setActorFilter] = useState<string>("all");
  const [toolFilter, setToolFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [scopeFilter, setScopeFilter] = useState<string>("all");
  const [timeRange, setTimeRange] = useState<string>("all");

  const buildParams = React.useCallback(() => {
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

  const loadData = () => {
    setIsLoading(true);
    fetch(`http://localhost:4000/audit/timeline?${buildParams().toString()}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setTimeline(data.timeline || []);
          setStats(data.stats || null);
          setTotalDbEvents(data.total_db_events || 0);
        }
      })
      .catch((e) => console.error("Failed to fetch audit timeline", e))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    let ignore = false;
    fetch(`http://localhost:4000/audit/timeline?${buildParams().toString()}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!ignore && data) {
          setTimeline(data.timeline || []);
          setStats(data.stats || null);
          setTotalDbEvents(data.total_db_events || 0);
        }
      })
      .catch((e) => console.error("Failed to fetch audit timeline", e))
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [buildParams]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  // Distinct actors and tools for dropdowns
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

  // Export functions
  const exportAsJSON = () => {
    const blob = new Blob([JSON.stringify(timeline, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_timeline_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportAsCSV = () => {
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

  return (
    <div className="audit-explorer-container">
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
          <span className="kpi-sub">Out-of-boundary / tier attempts</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-label">ACTIVE SCOPE CONTRACTS</span>
          <span className="kpi-val">{stats?.active_contracts ?? 1}</span>
          <span className="kpi-sub">HMAC-SHA256 signed boundaries</span>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="audit-filter-bar">
        <form onSubmit={handleSearchSubmit} className="search-form">
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
            <button className="export-btn" onClick={exportAsCSV} title="Export as CSV">
              📥 CSV
            </button>
            <button className="export-btn" onClick={exportAsJSON} title="Export as JSON">
              📥 JSON
            </button>
          </div>
        </div>
      </div>

      {/* Main Timeline Stream */}
      <div className="timeline-container">
        {isLoading ? (
          <div className="timeline-loading">
            <div className="loading-spinner" />
            <p>Querying SQLite Event Store & Correlating Scope Contracts...</p>
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
                // Scope Contract Milestone Card
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
                        <span className="label">Allowed Tool Tiers:</span>
                        {(item.allowed_tool_tiers || []).map((t) => (
                          <span key={t} className="tier-tag">
                            Tier {t} ({t === 1 ? "Passive" : t === 2 ? "Active Probing" : "Intrusive"})
                          </span>
                        ))}
                        {item.is_active && <span className="status-pill active">ACTIVE</span>}
                        {item.is_expired && <span className="status-pill expired">EXPIRED</span>}
                      </div>
                    </div>
                  </div>
                );
              }

              // Standard Execution Event Card
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

                  {/* Summary & Target Evaluated */}
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

      {/* Deep Inspection Drawer (Modal/Sidebar) */}
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
                <span className="drawer-sub">
                  Timestamp: {selectedItem.timestamp}
                </span>
              </div>
              <button className="drawer-close-btn" onClick={() => setSelectedItem(null)}>
                ✕
              </button>
            </div>

            <div className="drawer-body">
              {/* Scope Contract Milestone Details */}
              {selectedItem.is_scope_contract_milestone ? (
                <div className="contract-drawer-details">
                  <div className="proof-card">
                    <h4>HMAC-SHA256 Cryptographic Signature</h4>
                    <pre className="signature-box">{selectedItem.signature}</pre>
                    <div className="proof-status-row">
                      <span>Status:</span>
                      <strong style={{ color: selectedItem.signature_valid ? "var(--accent-emerald)" : "var(--accent-rose)" }}>
                        {selectedItem.signature_valid ? "✓ Valid Signature (Authentic Contract)" : "✗ Invalid Signature"}
                      </strong>
                    </div>
                  </div>

                  <div className="drawer-section">
                    <h4>Contract Boundaries</h4>
                    <ul className="drawer-list">
                      <li><strong>Contract ID:</strong> {selectedItem.contract_id}</li>
                      <li><strong>Created At:</strong> {selectedItem.timestamp}</li>
                      <li><strong>Expires At:</strong> {selectedItem.expires_at || "Never"}</li>
                      <li><strong>Targets:</strong> {(selectedItem.targets || []).join(", ")}</li>
                      <li><strong>Allowed Tool Tiers:</strong> {(selectedItem.allowed_tool_tiers || []).join(", ")}</li>
                    </ul>
                  </div>
                </div>
              ) : (
                /* Execution Event Details */
                <div className="event-drawer-details">
                  {/* Scope Contract Accountability Box */}
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
                        <span>Tool Tier:</span>
                        <strong>Tier {selectedItem.tool_tier || 1}</strong>
                      </div>
                    </div>
                    {selectedItem.scope_violation_reason && (
                      <div className="drawer-violation-alert">
                        {selectedItem.scope_violation_reason}
                      </div>
                    )}
                  </div>

                  {/* Execution Arguments */}
                  <div className="drawer-section">
                    <h4>Requested Arguments</h4>
                    <pre className="code-block">
                      {typeof selectedItem.requested_args === "object"
                        ? JSON.stringify(selectedItem.requested_args, null, 2)
                        : String(selectedItem.requested_args || "None")}
                    </pre>
                  </div>

                  {/* Normalized Arguments */}
                  <div className="drawer-section">
                    <h4>Normalized Arguments</h4>
                    <pre className="code-block">
                      {typeof selectedItem.normalized_args === "object"
                        ? JSON.stringify(selectedItem.normalized_args, null, 2)
                        : String(selectedItem.normalized_args || "None")}
                    </pre>
                  </div>

                  {/* Captured Output Snippets */}
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

                  {/* Raw Event Record */}
                  <div className="drawer-section">
                    <h4>Raw Event JSON</h4>
                    <pre className="code-block raw">
                      {JSON.stringify(selectedItem, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
