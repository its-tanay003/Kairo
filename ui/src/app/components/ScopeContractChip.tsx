"use client";

import React, { useEffect, useState } from "react";

export interface ScopeContractData {
  contract_id: string;
  targets: string[];
  network_scope: string;
  time_window: string;
  allowed_tool_tiers: number[];
  authorized_by: string;
  created_at: string;
  expires_at: string;
  signature: string;
  is_active: boolean;
  is_expired?: boolean;
  seconds_remaining?: number;
  signature_valid?: boolean;
  metadata?: Record<string, unknown>;
}

interface ScopeContractChipProps {
  onScopeChange?: (contract: ScopeContractData) => void;
}

export default function ScopeContractChip({ onScopeChange }: ScopeContractChipProps) {
  const [contract, setContract] = useState<ScopeContractData | null>(null);
  const [secondsRemaining, setSecondsRemaining] = useState<number>(0);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Form states for modal
  const [editTargets, setEditTargets] = useState<string>("");
  const [editNetworkScope, setEditNetworkScope] = useState<string>("authorized_lab");
  const [editTimeWindow, setEditTimeWindow] = useState<string>("8h");
  const [editTiers, setEditTiers] = useState<number[]>([1, 2, 3]);
  const [editAuthorizedBy, setEditAuthorizedBy] = useState<string>("secops_lead@kairo.internal");

  const openModal = () => {
    if (contract) {
      setEditTargets((contract.targets || []).join(", "));
      setEditNetworkScope(contract.network_scope || "authorized_lab");
      setEditTimeWindow(contract.time_window || "8h");
      setEditTiers(contract.allowed_tool_tiers || [1, 2, 3]);
      setEditAuthorizedBy(contract.authorized_by || "secops_lead@kairo.internal");
    }
    setIsModalOpen(true);
  };

  useEffect(() => {
    let isMounted = true;

    const loadScope = async () => {
      try {
        const res = await fetch("http://localhost:8000/scope/active");
        if (res.ok) {
          const data: ScopeContractData = await res.json();
          if (isMounted) {
            setContract(data);
            if (data.seconds_remaining !== undefined) {
              setSecondsRemaining(data.seconds_remaining);
            }
            if (onScopeChange) onScopeChange(data);
          }
        }
      } catch (e) {
        console.error("Failed to fetch active scope contract", e);
      }
    };

    loadScope();
    const interval = setInterval(loadScope, 6000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [onScopeChange]);

  // 1-second countdown ticker for ultra-smooth UI time display
  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsRemaining((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTime = (secs: number) => {
    if (secs <= 0) return "EXPIRED";
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (h > 0) {
      return `${h}h ${m}m ${s}s`;
    }
    return `${m}m ${s}s`;
  };

  const handleCreateContract = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setIsSubmitting(true);
    try {
      const parsedTargets = editTargets
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);

      const res = await fetch("http://localhost:8000/scope/contract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targets: parsedTargets.length > 0 ? parsedTargets : ["127.0.0.1", "localhost"],
          network_scope: editNetworkScope,
          time_window: editTimeWindow,
          allowed_tool_tiers: editTiers,
          authorized_by: editAuthorizedBy,
          metadata: {
            updated_via: "ui_header_modal",
            authorized_at: new Date().toISOString(),
          },
        }),
      });

      if (res.ok) {
        const newContract = await res.json();
        setContract(newContract);
        setSecondsRemaining(newContract.seconds_remaining || 0);
        setIsModalOpen(false);
      }
    } catch (err) {
      console.error("Failed to sign new scope contract", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickRenew = async () => {
    setIsSubmitting(true);
    try {
      const res = await fetch("http://localhost:8000/scope/contract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targets: contract?.targets || ["127.0.0.1", "192.168.1.0/24"],
          network_scope: contract?.network_scope || "authorized_lab",
          time_window: "8h",
          allowed_tool_tiers: contract?.allowed_tool_tiers || [1, 2, 3],
          authorized_by: contract?.authorized_by || "secops_lead@kairo.internal",
          metadata: { renewed_at: new Date().toISOString() },
        }),
      });
      if (res.ok) {
        const newContract = await res.json();
        setContract(newContract);
        setSecondsRemaining(newContract.seconds_remaining || 0);
      }
    } catch (err) {
      console.error("Failed quick renew", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleTier = (tier: number) => {
    setEditTiers((prev) =>
      prev.includes(tier) ? prev.filter((t) => t !== tier) : [...prev, tier].sort()
    );
  };

  const isExpired = secondsRemaining <= 0;
  const isValid = contract?.signature_valid && !isExpired;

  // Render primary target summary
  const targetSummary =
    contract && contract.targets && contract.targets.length > 0
      ? contract.targets[0] + (contract.targets.length > 1 ? ` (+${contract.targets.length - 1})` : "")
      : "No Scope";

  return (
    <>
      {/* Persistent Scope Header Chip */}
      <button
        type="button"
        className={`scope-header-chip ${isValid ? "valid" : "invalid"}`}
        onClick={openModal}
        title="Active Authorization Context (Scope Contract) — Click to view & manage"
      >
        <div className="scope-chip-icon">
          <span className="shield-icon">🛡️</span>
          <span className={`status-indicator-dot ${isValid ? "dot-active" : "dot-expired"}`} />
        </div>

        <div className="scope-chip-content">
          <div className="scope-chip-top">
            <span className="scope-label">SCOPE:</span>
            <span className="scope-targets" title={(contract?.targets || []).join(", ")}>
              {targetSummary}
            </span>
            <span className="scope-tier-tag">
              Tiers [{(contract?.allowed_tool_tiers || []).join(",")}]
            </span>
          </div>
          <div className="scope-chip-bottom">
            <span className={`scope-countdown ${isExpired ? "expired" : ""}`}>
              ⏳ {formatTime(secondsRemaining)}
            </span>
            <span className="scope-auth-by">
              • {contract?.authorized_by?.split("@")[0] || "authorized"}
            </span>
            <span className={`scope-sig-tag ${contract?.signature_valid ? "sig-ok" : "sig-bad"}`}>
              {contract?.signature_valid ? "HMAC-SHA256 ✓" : "SIGNATURE INVALID"}
            </span>
          </div>
        </div>

        <span className="scope-chip-action">View &gt;</span>
      </button>

      {/* Scope Contract Inspection & Configuration Modal */}
      {isModalOpen && (
        <div className="scope-modal-backdrop" onClick={() => setIsModalOpen(false)}>
          <div className="scope-modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="scope-modal-header">
              <div className="modal-title-wrap">
                <span className="modal-icon">🛡️</span>
                <div>
                  <h3>Active Authorization Context (Scope Contract)</h3>
                  <p className="modal-subtitle">
                    Cryptographically signed boundaries enforced by the Execution Gateway
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setIsModalOpen(false)}
              >
                ✕
              </button>
            </div>

            <div className="scope-modal-body">
              {/* Trust & Safety Status Banner */}
              <div className={`scope-status-banner ${isValid ? "banner-valid" : "banner-invalid"}`}>
                <div className="banner-icon">{isValid ? "✓" : "⚠️"}</div>
                <div className="banner-details">
                  <div className="banner-heading">
                    {isValid
                      ? "GATEWAY ENFORCEMENT ACTIVE — Authorized Use Only"
                      : isExpired
                      ? "SCOPE CONTRACT EXPIRED — All Tool Calls Blocked"
                      : "CONTRACT TAMPERED / INVALID SIGNATURE"}
                  </div>
                  <div className="banner-subtext">
                    Contract ID: <code>{contract?.contract_id || "None"}</code> • Network Scope:{" "}
                    <b>{contract?.network_scope || "None"}</b> • Time Remaining:{" "}
                    <b>{formatTime(secondsRemaining)}</b>
                  </div>
                </div>
                {isExpired && (
                  <button
                    type="button"
                    className="quick-renew-btn"
                    onClick={handleQuickRenew}
                    disabled={isSubmitting}
                  >
                    Quick Renew (+8h)
                  </button>
                )}
              </div>

              {/* Scope Contract Parameters Editor */}
              <form onSubmit={handleCreateContract} className="scope-contract-form">
                <div className="form-group">
                  <label>
                    Authorized Target Subnets &amp; Hosts (Comma-separated CIDRs, IPs, or Hostnames):
                  </label>
                  <input
                    type="text"
                    value={editTargets}
                    onChange={(e) => setEditTargets(e.target.value)}
                    placeholder="127.0.0.1, 192.168.1.0/24, localhost, example.com"
                    className="scope-input"
                    required
                  />
                  <span className="field-hint">
                    Gateway will reject any tool targeting an IP/host outside these CIDR boundaries.
                  </span>
                </div>

                <div className="form-row">
                  <div className="form-group col">
                    <label>Network Scope Zone:</label>
                    <select
                      value={editNetworkScope}
                      onChange={(e) => setEditNetworkScope(e.target.value)}
                      className="scope-select"
                    >
                      <option value="authorized_lab">Authorized Lab (Sandbox / Isolated)</option>
                      <option value="internal_staging">Internal Staging</option>
                      <option value="production_authorized">Production (Read-Only Authorized)</option>
                      <option value="local_development">Local Development</option>
                    </select>
                  </div>

                  <div className="form-group col">
                    <label>Time Window Validity:</label>
                    <select
                      value={editTimeWindow}
                      onChange={(e) => setEditTimeWindow(e.target.value)}
                      className="scope-select"
                    >
                      <option value="1h">1 Hour</option>
                      <option value="4h">4 Hours</option>
                      <option value="8h">8 Hours (Standard Shift)</option>
                      <option value="24h">24 Hours (Full Engagement)</option>
                    </select>
                  </div>

                  <div className="form-group col">
                    <label>Authorized Sign-off Identity:</label>
                    <input
                      type="text"
                      value={editAuthorizedBy}
                      onChange={(e) => setEditAuthorizedBy(e.target.value)}
                      placeholder="secops_lead@kairo.internal"
                      className="scope-input"
                      required
                    />
                  </div>
                </div>

                {/* Tool Tier Authorization Matrix */}
                <div className="form-group">
                  <label>Permitted Tool Authorization Tiers:</label>
                  <div className="tiers-matrix">
                    <div
                      className={`tier-card ${editTiers.includes(1) ? "selected" : ""}`}
                      onClick={() => toggleTier(1)}
                    >
                      <div className="tier-header">
                        <input
                          type="checkbox"
                          checked={editTiers.includes(1)}
                          onChange={() => {}}
                        />
                        <span className="tier-badge tier-1">Tier 1: Passive Recon</span>
                      </div>
                      <p className="tier-desc">
                        OSINT, DNS lookup, whois, searchsploit, metadata extraction. Zero active traffic.
                      </p>
                    </div>

                    <div
                      className={`tier-card ${editTiers.includes(2) ? "selected" : ""}`}
                      onClick={() => toggleTier(2)}
                    >
                      <div className="tier-header">
                        <input
                          type="checkbox"
                          checked={editTiers.includes(2)}
                          onChange={() => {}}
                        />
                        <span className="tier-badge tier-2">Tier 2: Active Scanning</span>
                      </div>
                      <p className="tier-desc">
                        Port scanning (nmap), web enumeration (gobuster, ffuf, nikto), packet capture.
                      </p>
                    </div>

                    <div
                      className={`tier-card ${editTiers.includes(3) ? "selected" : ""}`}
                      onClick={() => toggleTier(3)}
                    >
                      <div className="tier-header">
                        <input
                          type="checkbox"
                          checked={editTiers.includes(3)}
                          onChange={() => {}}
                        />
                        <span className="tier-badge tier-3">Tier 3: Intrusive &amp; Remote Exec</span>
                      </div>
                      <p className="tier-desc">
                        SQL injection (sqlmap), brute-forcing (hydra), metasploit, arbitrary Kali VM shell exec.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Raw Cryptographic Payload Inspector */}
                <div className="form-group">
                  <label>Cryptographic Contract Verification (HMAC-SHA256 Signature):</label>
                  <div className="signature-inspector">
                    <div className="sig-meta-row">
                      <span>
                        Signature Status:{" "}
                        <b style={{ color: contract?.signature_valid ? "#10b981" : "#f43f5e" }}>
                          {contract?.signature_valid ? "VALID & VERIFIED" : "INVALID"}
                        </b>
                      </span>
                      <span>Algorithm: HMAC-SHA256</span>
                    </div>
                    <code className="sig-hex">{contract?.signature || "Awaiting Signature"}</code>
                    <pre className="canonical-preview">
                      {JSON.stringify(
                        {
                          contract_id: contract?.contract_id,
                          targets: contract?.targets,
                          network_scope: contract?.network_scope,
                          time_window: contract?.time_window,
                          allowed_tool_tiers: contract?.allowed_tool_tiers,
                          authorized_by: contract?.authorized_by,
                          created_at: contract?.created_at,
                          expires_at: contract?.expires_at,
                        },
                        null,
                        2
                      )}
                    </pre>
                  </div>
                </div>

                <div className="modal-actions">
                  <button
                    type="button"
                    className="modal-secondary-btn"
                    onClick={() => setIsModalOpen(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="modal-primary-btn"
                    disabled={isSubmitting || editTiers.length === 0}
                  >
                    {isSubmitting ? "Cryptographically Signing..." : "Sign & Deploy Scope Contract"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
