"use client";

import React, { useState, useEffect } from "react";

export interface UpdateItem {
  id: string;
  name: string;
  category: "system" | "tool" | "database" | "custom";
  current_version: string;
  available_version: string;
  source: string;
  update_command: string;
  health_check_command: string;
  is_database: boolean;
  severity: "critical" | "security" | "normal";
}

export interface UpdateHistoryRecord {
  id: number;
  update_id: string;
  item_id: string;
  item_name: string;
  category: string;
  from_version: string;
  to_version: string;
  policy: string;
  status: "success" | "failed" | "rolled_back" | "in_progress";
  timestamp: string;
  duration_ms: number;
  snapshot_name?: string;
  health_check_status?: string;
  health_check_output?: string;
  error_message?: string;
}

export interface UpdateStatusResponse {
  policy: "standard_managed" | "managed_rolling" | "manual_control";
  available_updates_count: number;
  available_updates: UpdateItem[];
  last_checked_at: string;
  recent_history: UpdateHistoryRecord[];
  managed_environment: string;
  rollback_capable: boolean;
}

interface UpdatesPanelProps {
  apiBaseUrl?: string;
}

export default function UpdatesPanel({ apiBaseUrl = "" }: UpdatesPanelProps) {
  const [status, setStatus] = useState<UpdateStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [checking, setChecking] = useState<boolean>(false);
  const [applyingItemId, setApplyingItemId] = useState<string | null>(null);
  const [updatingAll, setUpdatingAll] = useState<boolean>(false);
  const [updateAllProgress, setUpdateAllProgress] = useState<string | null>(null);
  const [rollingBackSnap, setRollingBackSnap] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Fetch current status
  const fetchStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/updates/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch update subsystem status`);
      const data = await res.json();
      setStatus(data);
    } catch (err: any) {
      setError(err.message || "Failed to connect to Update Manager");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  // Trigger update check
  const handleCheckUpdates = async () => {
    setChecking(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBaseUrl}/updates/check`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}: Update discovery check failed`);
      const data = await res.json();
      setFeedback({
        type: "success",
        message: `Discovered ${data.count || 0} component and database updates across Kali system.`,
      });
      fetchStatus();
    } catch (err: any) {
      setFeedback({ type: "error", message: err.message });
    } finally {
      setChecking(false);
    }
  };

  // Change policy
  const handlePolicyChange = async (newPolicy: string) => {
    try {
      const res = await fetch(`${apiBaseUrl}/updates/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy: newPolicy }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to set policy`);
      fetchStatus();
      setFeedback({ type: "success", message: `Operational update policy updated to '${newPolicy}'.` });
    } catch (err: any) {
      setFeedback({ type: "error", message: err.message });
    }
  };

  // Apply update
  const handleApplyUpdate = async (item: UpdateItem) => {
    if (!confirm(`Apply update for '${item.name}'?\n\nA pre-update VM snapshot will be created automatically, followed by non-destructive health checks.`)) {
      return;
    }
    setApplyingItemId(item.id);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBaseUrl}/updates/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: item.id, create_snapshot: true }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setFeedback({
          type: "success",
          message: `Update applied successfully for '${item.name}'! Snapshot: '${data.snapshot_name}'. Health verification passed.`,
        });
      } else if (data.status === "rolled_back") {
        setFeedback({
          type: "error",
          message: `Update failed health checks and was automatically rolled back to snapshot '${data.snapshot_name}'. Error: ${data.error}`,
        });
      } else {
        setFeedback({
          type: "error",
          message: `Update failed: ${data.error || "Unknown error occurred"}`,
        });
      }
      fetchStatus();
    } catch (err: any) {
      setFeedback({ type: "error", message: err.message });
    } finally {
      setApplyingItemId(null);
    }
  };

  // Update All
  const handleUpdateAll = async () => {
    const count = status?.available_updates_count || status?.available_updates?.length || 0;
    if (count === 0) {
      setFeedback({ type: "success", message: "No updates are currently pending. Everything is up to date." });
      return;
    }
    if (!confirm(`Update all ${count} components in one click?\n\nA single pre-update hypervisor recovery point snapshot will be created before applying packages and vulnerability feeds.`)) {
      return;
    }

    setUpdatingAll(true);
    setUpdateAllProgress(`Preparing pre-update snapshot & executing ${count} updates...`);
    setFeedback(null);

    try {
      const res = await fetch(`${apiBaseUrl}/updates/apply-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (data.success) {
        setFeedback({
          type: "success",
          message: `⚡ One-click update finished! Successfully updated ${data.applied_count} of ${data.total} components. Recovery snapshot: '${data.snapshot_name || "snapshot_created"}'.`,
        });
      } else {
        setFeedback({
          type: data.applied_count > 0 ? "success" : "error",
          message: `Batch update finished with warnings: ${data.applied_count} succeeded, ${data.failed_count} failed. Snapshot: '${data.snapshot_name || "none"}'.`,
        });
      }
      fetchStatus();
    } catch (err: any) {
      setFeedback({ type: "error", message: `Batch update error: ${err.message}` });
    } finally {
      setUpdatingAll(false);
      setUpdateAllProgress(null);
    }
  };

  // Rollback to snapshot
  const handleRollback = async (snapshotName: string) => {
    if (!confirm(`Restore recovery snapshot '${snapshotName}'?\n\nThis will restore the Kali VM filesystem to this exact recovery point.`)) {
      return;
    }
    setRollingBackSnap(snapshotName);
    setFeedback(null);
    try {
      const res = await fetch(`${apiBaseUrl}/updates/rollback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_name: snapshotName }),
      });
      const data = await res.json();
      if (data.success) {
        setFeedback({
          type: "success",
          message: `Snapshot '${snapshotName}' restored successfully in ${data.duration_ms}ms.`,
        });
      } else {
        throw new Error(data.error || "Rollback restore failed");
      }
      fetchStatus();
    } catch (err: any) {
      setFeedback({ type: "error", message: err.message });
    } finally {
      setRollingBackSnap(null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#0d1117] text-[#e6edf3] overflow-y-auto select-text p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-[#30363d]">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🔄</span>
            <h1 className="text-xl font-bold text-white tracking-wide">Automatic Kali Linux & Tool Updates</h1>
            <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-[#238636]/20 text-[#3fb950] border border-[#238636]/40">
              Snapshot Rollback Guarded
            </span>
          </div>
          <p className="text-xs text-[#8b949e] mt-1">
            Automated discovery, non-destructive health checks, and instant hypervisor rollback for Kali base packages, security CLI/GUI tools, and vulnerability feeds.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            disabled={checking || updatingAll || (status?.available_updates_count === 0)}
            onClick={handleUpdateAll}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-md bg-gradient-to-r from-[#1f6feb] to-[#238636] hover:from-[#388bfd] hover:to-[#2ea043] text-white transition-all disabled:opacity-40 shadow-sm border border-[#388bfd]/30"
          >
            {updatingAll ? <span className="animate-spin">↻</span> : <span>⚡</span>}
            <span>{updatingAll ? "Updating All..." : `Update All (${status?.available_updates_count || 0})`}</span>
          </button>

          <button
            disabled={checking || updatingAll}
            onClick={handleCheckUpdates}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-md bg-[#238636] hover:bg-[#2ea043] text-white transition-colors disabled:opacity-50 shadow-sm"
          >
            {checking ? <span className="animate-spin">↻</span> : <span>🔍</span>}
            <span>{checking ? "Checking Repositories..." : "Check for Updates"}</span>
          </button>

          <button
            disabled={updatingAll}
            onClick={fetchStatus}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-[#21262d] hover:bg-[#30363d] text-[#c9d1d9] border border-[#30363d] transition-colors disabled:opacity-50"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Alert Feedback Banner */}
      {feedback && (
        <div
          className={`p-3 rounded-lg border text-xs flex items-center justify-between ${
            feedback.type === "success"
              ? "bg-[#238636]/15 border-[#238636]/40 text-[#3fb950]"
              : "bg-[#da3633]/15 border-[#da3633]/40 text-[#f85149]"
          }`}
        >
          <span>{feedback.message}</span>
          <button onClick={() => setFeedback(null)} className="font-bold hover:underline ml-3">
            ✕
          </button>
        </div>
      )}

      {/* Operational Policy Card */}
      <div className="p-5 rounded-lg bg-[#161b22] border border-[#30363d]">
        <h2 className="text-sm font-bold text-white mb-2 flex items-center gap-2">
          <span>⚙️</span> Operational Update Policy
        </h2>
        <p className="text-xs text-[#8b949e] mb-4">
          Defines how KAIRO discovers and applies updates across your isolated Kali environment.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            {
              id: "standard_managed",
              title: "Standard Managed",
              desc: "Checks repositories automatically, notifies the operator of pending updates, and waits for explicit approval before modifying the environment.",
              badge: "Default Safe",
            },
            {
              id: "managed_rolling",
              title: "Managed Rolling",
              desc: "Applies safe tool and vulnerability database updates automatically with a pre-update snapshot and automated rollback if health checks fail.",
              badge: "Autonomous",
            },
            {
              id: "manual_control",
              title: "Manual Control",
              desc: "On-demand updates only. Disables automatic checks; updates are executed solely upon direct operator request in this panel.",
              badge: "Air-Gapped",
            },
          ].map((p) => {
            const isSelected = status?.policy === p.id;
            return (
              <div
                key={p.id}
                onClick={() => handlePolicyChange(p.id)}
                className={`p-4 rounded-lg border cursor-pointer transition-all ${
                  isSelected
                    ? "bg-[#1f6feb]/15 border-[#58a6ff] ring-1 ring-[#58a6ff]"
                    : "bg-[#0d1117] border-[#30363d] hover:border-[#58a6ff]/50"
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-semibold text-xs text-white">{p.title}</span>
                  <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-[#21262d] text-[#58a6ff]">
                    {p.badge}
                  </span>
                </div>
                <p className="text-[11px] text-[#8b949e] leading-relaxed">{p.desc}</p>
                <div className="mt-3 flex items-center gap-1.5 text-[11px] font-medium">
                  <input
                    type="radio"
                    name="update_policy"
                    checked={isSelected}
                    onChange={() => handlePolicyChange(p.id)}
                    className="accent-[#58a6ff]"
                  />
                  <span className={isSelected ? "text-[#58a6ff] font-bold" : "text-[#8b949e]"}>
                    {isSelected ? "Active Policy" : "Select Policy"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Available Updates List */}
      <div className="p-5 rounded-lg bg-[#161b22] border border-[#30363d]">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
          <div>
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <span>📦</span> Available System & Tool Updates
            </h2>
            <span className="text-xs text-[#8b949e]">
              Last checked: {status?.last_checked_at ? new Date(status.last_checked_at).toLocaleString() : "Never"}
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-1 text-xs font-bold rounded-full bg-[#1f6feb]/20 text-[#58a6ff] border border-[#1f6feb]/40">
              {status?.available_updates_count || 0} Updates Pending
            </span>
            {(status?.available_updates_count || 0) > 0 && (
              <button
                disabled={updatingAll}
                onClick={handleUpdateAll}
                className="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded bg-[#238636] hover:bg-[#2ea043] text-white transition-colors disabled:opacity-50 shadow-sm"
              >
                {updatingAll ? <span className="animate-spin">↻</span> : <span>⚡</span>}
                <span>Update All</span>
              </button>
            )}
          </div>
        </div>

        {updateAllProgress && (
          <div className="mb-4 p-3 rounded-lg bg-[#1f6feb]/10 border border-[#1f6feb]/30 text-xs text-[#58a6ff] flex items-center gap-2">
            <span className="animate-spin">↻</span>
            <span>{updateAllProgress}</span>
          </div>
        )}

        {loading ? (
          <div className="py-8 text-center text-xs text-[#8b949e]">
            <span className="animate-spin text-xl block mb-2">↻</span>
            Probing packages and database feeds...
          </div>
        ) : !status?.available_updates || status.available_updates.length === 0 ? (
          <div className="py-8 text-center text-xs text-[#8b949e]">
            <span className="text-2xl block mb-1">✓</span>
            All Kali system packages, security tools, and vulnerability databases are up to date!
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-[#30363d] text-[#8b949e] font-semibold">
                  <th className="py-2.5 px-3">Component / Tool</th>
                  <th className="py-2.5 px-3">Category</th>
                  <th className="py-2.5 px-3">Installed</th>
                  <th className="py-2.5 px-3">Available</th>
                  <th className="py-2.5 px-3">Source</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#21262d]">
                {status.available_updates.map((item) => {
                  const isApplying = applyingItemId === item.id;
                  return (
                    <tr key={item.id} className="hover:bg-[#1c2128] transition-colors">
                      <td className="py-3 px-3">
                        <span className="font-semibold text-white block">{item.name}</span>
                        <code className="text-[10px] text-[#8b949e] font-mono">{item.id}</code>
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded bg-[#21262d] text-[#8b949e] border border-[#30363d]">
                          {item.category}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-mono text-[#c9d1d9]">{item.current_version}</td>
                      <td className="py-3 px-3 font-mono text-[#3fb950] font-semibold">{item.available_version}</td>
                      <td className="py-3 px-3 text-[#8b949e] capitalize">{item.source}</td>
                      <td className="py-3 px-3 text-right">
                        <button
                          disabled={isApplying}
                          onClick={() => handleApplyUpdate(item)}
                          className="px-3 py-1.5 text-xs font-semibold rounded bg-[#238636] hover:bg-[#2ea043] text-white transition-colors disabled:opacity-50"
                        >
                          {isApplying ? "Updating..." : "Update"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Snapshot Recovery & Rollback Audit History */}
      <div className="p-5 rounded-lg bg-[#161b22] border border-[#30363d]">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <span>🛡️</span> Recovery Snapshots & Immutable Update Audit History
            </h2>
            <p className="text-xs text-[#8b949e]">
              Pre-update recovery points created by the hypervisor before modifying the Kali filesystem.
            </p>
          </div>
        </div>

        {!status?.recent_history || status.recent_history.length === 0 ? (
          <p className="text-xs text-[#8b949e] italic py-4 text-center">
            No historical update or rollback records recorded yet.
          </p>
        ) : (
          <div className="space-y-2.5">
            {status.recent_history.map((rec) => {
              const isRollingBack = rollingBackSnap === rec.snapshot_name;
              return (
                <div
                  key={rec.id || rec.update_id}
                  className="p-3 rounded-lg bg-[#0d1117] border border-[#30363d] flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-2.5 h-2.5 rounded-full ${
                          rec.status === "success"
                            ? "bg-[#238636]"
                            : rec.status === "rolled_back"
                            ? "bg-[#d29922]"
                            : "bg-[#da3633]"
                        }`}
                      />
                      <span className="font-bold text-white">{rec.item_name}</span>
                      <span className="font-mono text-[10px] text-[#8b949e]">({rec.item_id})</span>
                      <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase rounded bg-[#21262d] text-[#c9d1d9]">
                        {rec.status}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 text-[11px] text-[#8b949e] mt-1 font-mono">
                      <span>{new Date(rec.timestamp).toLocaleString()}</span>
                      <span>•</span>
                      <span>Snapshot: {rec.snapshot_name || "None"}</span>
                      <span>•</span>
                      <span>Duration: {rec.duration_ms}ms</span>
                    </div>

                    {rec.error_message && (
                      <p className="text-[11px] text-[#f85149] mt-1 line-clamp-1">{rec.error_message}</p>
                    )}
                  </div>

                  {rec.snapshot_name && (
                    <button
                      disabled={isRollingBack}
                      onClick={() => handleRollback(rec.snapshot_name!)}
                      className="px-3 py-1.5 text-xs font-semibold rounded bg-[#21262d] hover:bg-[#da3633]/20 hover:text-[#f85149] hover:border-[#da3633] text-[#c9d1d9] border border-[#30363d] transition-colors shrink-0 disabled:opacity-50"
                    >
                      {isRollingBack ? "Restoring..." : "↺ Rollback to Snapshot"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

