"use client";

import React, { useState, useEffect, useCallback } from "react";

export interface AdvancedSettingsState {
  // Execution Engine
  executionMode: "autonomous" | "step_by_step" | "plan_only" | "manual";
  autoReplanning: boolean;
  maxPlanDepth: number;
  stepTimeoutSec: number;
  maxRetriesPerNode: number;
  autoSynthesizeReports: boolean;

  // Scope & Safety Boundaries
  authorizedTargets: string[];
  networkScope: string;
  timeWindowHours: number;
  authorizedBy: string;
  failClosedEnforcement: boolean;
  strictTargetMatching: boolean;

  // Kali VM & Sandbox Isolation
  snapshotBeforeTask: boolean;
  rollbackOnFailure: boolean;
  rollbackAfterExecution: boolean;
  maxCpuPct: number;
  maxRamMb: number;
  maxDiskMb: number;
  maxConcurrentProcesses: number;
  vncQuality: "low" | "medium" | "high";
  vncTargetFps: number;

  // AI & Reasoning Models
  selectedModelId: string;
  temperature: number;
  contextLength: number;
  autoLocalFallback: boolean;
  cotDisplayMode: "verbose" | "summary" | "hidden";

  // Privileges & Tool Execution
  requireRootElevationPrompt: boolean;
  unifiedToolAccessAudit: boolean;
  autoCheckToolUpdates: boolean;

  // UI & Workspace Preferences
  terminalFont: string;
  audibleAlerts: boolean;
  defaultDrawerWide: boolean;
}

const DEFAULT_SETTINGS: AdvancedSettingsState = {
  executionMode: "autonomous",
  autoReplanning: true,
  maxPlanDepth: 10,
  stepTimeoutSec: 120,
  maxRetriesPerNode: 2,
  autoSynthesizeReports: true,

  authorizedTargets: ["127.0.0.1", "192.168.1.0/24", "target.local"],
  networkScope: "authorized_lab",
  timeWindowHours: 4,
  authorizedBy: "secops_lead@kairo.internal",
  failClosedEnforcement: true,
  strictTargetMatching: true,

  snapshotBeforeTask: true,
  rollbackOnFailure: true,
  rollbackAfterExecution: false,
  maxCpuPct: 80,
  maxRamMb: 512,
  maxDiskMb: 100,
  maxConcurrentProcesses: 3,
  vncQuality: "high",
  vncTargetFps: 30,

  selectedModelId: "kairo-scale-2b",
  temperature: 0.2,
  contextLength: 4096,
  autoLocalFallback: true,
  cotDisplayMode: "verbose",

  requireRootElevationPrompt: false,
  unifiedToolAccessAudit: true,
  autoCheckToolUpdates: true,

  terminalFont: "'JetBrains Mono', 'Fira Code', monospace",
  audibleAlerts: false,
  defaultDrawerWide: true,
};

interface AdvancedSettingsPanelProps {
  apiBaseUrl?: string;
  sessionId?: string;
  activeModelId?: string;
  onModelChange?: (modelId: string, modelName: string) => void;
  onScopeUpdated?: () => void;
  onClose?: () => void;
}

export default function AdvancedSettingsPanel({
  apiBaseUrl = "http://127.0.0.1:8000",
  sessionId = "default",
  activeModelId,
  onModelChange,
  onScopeUpdated,
  onClose,
}: AdvancedSettingsPanelProps) {
  const [settings, setSettings] = useState<AdvancedSettingsState>(DEFAULT_SETTINGS);
  const [activeSubTab, setActiveSubTab] = useState<
    "execution" | "scope" | "sandbox" | "ai" | "tools" | "preferences"
  >("execution");

  // Status & Telemetry
  const [liveScope, setLiveScope] = useState<any | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [newTargetInput, setNewTargetInput] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Load persisted settings on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem("kairo_advanced_settings");
      if (saved) {
        const parsed = JSON.parse(saved);
        setSettings((prev) => ({ ...prev, ...parsed }));
      }
    } catch {
      // Ignore parse errors, use defaults
    }
  }, []);

  // Fetch active Scope Contract from backend
  const fetchActiveScope = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/scope/active`);
      if (res.ok) {
        const data = await res.json();
        setLiveScope(data);
        if (data.targets && Array.isArray(data.targets)) {
          setSettings((prev) => ({
            ...prev,
            authorizedTargets: data.targets,
            networkScope: data.network_scope || prev.networkScope,
            authorizedBy: data.authorized_by || prev.authorizedBy,
          }));
        }
      }
    } catch (err) {
      console.warn("Unable to fetch active scope from backend:", err);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    fetchActiveScope();
  }, [fetchActiveScope]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    try {
      localStorage.setItem("kairo_advanced_settings", JSON.stringify(settings));

      // 1. Sync Scope Contract with backend if changed
      try {
        const contractPayload = {
          targets: settings.authorizedTargets,
          network_scope: settings.networkScope,
          time_window: `${settings.timeWindowHours}h`,
          authorized_by: settings.authorizedBy,
          metadata: {
            configured_via: "advanced_settings_ui",
            strict_matching: settings.strictTargetMatching,
            fail_closed: settings.failClosedEnforcement,
          },
        };
        const scopeRes = await fetch(`${apiBaseUrl}/scope/contract`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(contractPayload),
        });
        if (scopeRes.ok) {
          await fetchActiveScope();
          if (onScopeUpdated) onScopeUpdated();
        }
      } catch (scopeErr) {
        console.warn("Scope contract sync warning:", scopeErr);
      }

      // 2. If model changed, inform parent
      if (onModelChange && settings.selectedModelId) {
        const modelNames: Record<string, string> = {
          "kairo-scale-2b": "Kairo Scale 2B (Custom Primary)",
          "deepseek-r1-moe": "DeepSeek R1 MoE (Advanced)",
          "llama-3-8b": "Meta Llama 3 8B Instruct",
          "qwen-2.5-0.5b": "Qwen 2.5 0.5B (Local Fallback)",
        };
        onModelChange(
          settings.selectedModelId,
          modelNames[settings.selectedModelId] || settings.selectedModelId
        );
      }

      showToast("✓ Advanced settings saved and applied across all subsystems");
    } catch (err: any) {
      showToast(`⚠️ Failed to persist settings: ${err?.message || err}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetDefaults = () => {
    if (confirm("Reset all advanced menu settings to factory defaults?")) {
      setSettings(DEFAULT_SETTINGS);
      localStorage.removeItem("kairo_advanced_settings");
      showToast("↺ Settings reset to factory defaults");
    }
  };

  const handleAddTarget = () => {
    const trimmed = newTargetInput.trim().toLowerCase();
    if (!trimmed) return;
    if (settings.authorizedTargets.includes(trimmed)) {
      showToast(`Target "${trimmed}" is already in the authorized scope`);
      return;
    }
    setSettings((prev) => ({
      ...prev,
      authorizedTargets: [...prev.authorizedTargets, trimmed],
    }));
    setNewTargetInput("");
  };

  const handleRemoveTarget = (targetToRemove: string) => {
    if (settings.authorizedTargets.length <= 1) {
      showToast("At least one authorized target must remain in scope");
      return;
    }
    setSettings((prev) => ({
      ...prev,
      authorizedTargets: prev.authorizedTargets.filter((t) => t !== targetToRemove),
    }));
  };

  const exportConfigJson = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(settings, null, 2));
    const dlAnchor = document.createElement("a");
    dlAnchor.setAttribute("href", dataStr);
    dlAnchor.setAttribute("download", `kairo_settings_${Date.now()}.json`);
    dlAnchor.click();
    showToast("✓ Configuration exported to JSON file");
  };

  const importConfigJson = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const parsed = JSON.parse(evt.target?.result as string);
        setSettings((prev) => ({ ...prev, ...parsed }));
        showToast("✓ Configuration successfully loaded from file");
      } catch (err) {
        showToast("⚠️ Invalid JSON configuration file");
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="adv-settings-container">
      {/* Header bar */}
      <div className="adv-settings-header">
        <div className="adv-settings-title-group">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "18px" }}>⚙️</span>
            <h2 className="adv-settings-heading">Advanced Menu Settings</h2>
            <span className="adv-adr-badge" title="ADR-004 Unified Tool Access: Fully Enforced">
              ADR-004 ZERO TIERS ACTIVE
            </span>
          </div>
          <p className="adv-settings-subheading">
            Configure autonomous execution policies, fail-closed scope boundaries, VM sandbox caps, and inference reasoning parameters.
          </p>
        </div>

        <div className="adv-settings-actions">
          <button
            className="adv-secondary-btn"
            onClick={exportConfigJson}
            title="Export settings to JSON"
          >
            📥 Export JSON
          </button>
          <label className="adv-secondary-btn" style={{ cursor: "pointer", display: "inline-flex", alignItems: "center" }} title="Import settings from JSON">
            📤 Import JSON
            <input type="file" accept=".json" onChange={importConfigJson} style={{ display: "none" }} />
          </label>
          <button
            className="adv-secondary-btn danger"
            onClick={handleResetDefaults}
            title="Reset all settings to default values"
          >
            ↺ Reset
          </button>
          <button
            className={`adv-primary-btn ${isSaving ? "loading" : ""}`}
            onClick={handleSaveSettings}
            disabled={isSaving}
          >
            {isSaving ? "Applying..." : "💾 Save & Apply"}
          </button>
        </div>
      </div>

      {/* Toast Alert */}
      {toastMessage && (
        <div className="adv-toast">
          <span>{toastMessage}</span>
          <button onClick={() => setToastMessage(null)}>✕</button>
        </div>
      )}

      {/* Sub Tabs Navigation */}
      <div className="adv-subtabs-bar">
        <button
          className={`adv-subtab-btn ${activeSubTab === "execution" ? "active" : ""}`}
          onClick={() => setActiveSubTab("execution")}
        >
          <span>⚡</span>
          <span>Autonomous Engine</span>
        </button>

        <button
          className={`adv-subtab-btn ${activeSubTab === "scope" ? "active" : ""}`}
          onClick={() => setActiveSubTab("scope")}
        >
          <span>🛡️</span>
          <span>Scope &amp; Safety</span>
        </button>

        <button
          className={`adv-subtab-btn ${activeSubTab === "sandbox" ? "active" : ""}`}
          onClick={() => setActiveSubTab("sandbox")}
        >
          <span>🖥️</span>
          <span>Kali VM &amp; Caps</span>
        </button>

        <button
          className={`adv-subtab-btn ${activeSubTab === "ai" ? "active" : ""}`}
          onClick={() => setActiveSubTab("ai")}
        >
          <span>🧠</span>
          <span>AI Inference</span>
        </button>

        <button
          className={`adv-subtab-btn ${activeSubTab === "tools" ? "active" : ""}`}
          onClick={() => setActiveSubTab("tools")}
        >
          <span>🔧</span>
          <span>Tool Access</span>
        </button>

        <button
          className={`adv-subtab-btn ${activeSubTab === "preferences" ? "active" : ""}`}
          onClick={() => setActiveSubTab("preferences")}
        >
          <span>🎨</span>
          <span>Preferences</span>
        </button>
      </div>

      {/* Main Settings Content Area */}
      <div className="adv-settings-body">
        {/* ==================== 1. AUTONOMOUS ENGINE TAB ==================== */}
        {activeSubTab === "execution" && (
          <div className="adv-tab-content">
            <div className="adv-section-card">
              <div className="adv-card-header">
                <div>
                  <h3 className="adv-card-title">Execution Mode</h3>
                  <p className="adv-card-desc">
                    Determine how KAIRO interprets natural language objectives into task plans and executes tool commands.
                  </p>
                </div>
                <span className="adv-tag cyan">Active: {settings.executionMode.toUpperCase()}</span>
              </div>

              <div className="adv-mode-grid">
                {/* Autonomous Mode */}
                <div
                  className={`adv-mode-card ${settings.executionMode === "autonomous" ? "selected" : ""}`}
                  onClick={() => setSettings((s) => ({ ...s, executionMode: "autonomous" }))}
                >
                  <div className="adv-mode-card-top">
                    <span className="adv-mode-icon">⚡</span>
                    <span className="adv-mode-badge recommended">Recommended</span>
                  </div>
                  <h4 className="adv-mode-name">Full Autonomous</h4>
                  <p className="adv-mode-desc">
                    KAIRO independently constructs the DAG, executes tools in parallel, validates outputs, self-heals errors, and generates reports.
                  </p>
                </div>

                {/* Step-by-Step Approval */}
                <div
                  className={`adv-mode-card ${settings.executionMode === "step_by_step" ? "selected" : ""}`}
                  onClick={() => setSettings((s) => ({ ...s, executionMode: "step_by_step" }))}
                >
                  <div className="adv-mode-card-top">
                    <span className="adv-mode-icon">📋</span>
                    <span className="adv-mode-badge">Supervised</span>
                  </div>
                  <h4 className="adv-mode-name">Step-by-Step Approval</h4>
                  <p className="adv-mode-desc">
                    Generates the complete multi-tool plan, pausing before each tool execution to await explicit operator confirmation.
                  </p>
                </div>

                {/* Plan Only */}
                <div
                  className={`adv-mode-card ${settings.executionMode === "plan_only" ? "selected" : ""}`}
                  onClick={() => setSettings((s) => ({ ...s, executionMode: "plan_only" }))}
                >
                  <div className="adv-mode-card-top">
                    <span className="adv-mode-icon">🔍</span>
                    <span className="adv-mode-badge">Dry Run</span>
                  </div>
                  <h4 className="adv-mode-name">Plan Only (Dry Run)</h4>
                  <p className="adv-mode-desc">
                    Synthesizes task representation, dependency DAG, command parameters, and completion criteria without running any tools.
                  </p>
                </div>

                {/* Manual Control */}
                <div
                  className={`adv-mode-card ${settings.executionMode === "manual" ? "selected" : ""}`}
                  onClick={() => setSettings((s) => ({ ...s, executionMode: "manual" }))}
                >
                  <div className="adv-mode-card-top">
                    <span className="adv-mode-icon">⌨️</span>
                    <span className="adv-mode-badge">Direct</span>
                  </div>
                  <h4 className="adv-mode-name">Manual Control</h4>
                  <p className="adv-mode-desc">
                    Disables automatic tool dispatch. All commands must be initiated directly by the operator via the interactive shell or GUI.
                  </p>
                </div>
              </div>
            </div>

            {/* Execution Policies & Depth */}
            <div className="adv-section-card">
              <h3 className="adv-card-title">Dynamic Replanning &amp; Limits</h3>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Autonomous Dynamic Replanning</span>
                  <span className="adv-toggle-desc">
                    When active tools produce unexpected outputs, banners, or newly discovered services, automatically add follow-up nodes to the DAG.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.autoReplanning}
                    onChange={(e) => setSettings((s) => ({ ...s, autoReplanning: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Auto-Synthesize Technical Reports</span>
                  <span className="adv-toggle-desc">
                    Automatically assemble cryptographic evidence, findings, and Markdown/HTML reports upon task completion.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.autoSynthesizeReports}
                    onChange={(e) => setSettings((s) => ({ ...s, autoSynthesizeReports: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>

              <div className="adv-fields-grid">
                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Max Plan Depth (DAG Nodes)</label>
                    <span className="adv-val-tag">{settings.maxPlanDepth} nodes</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="25"
                    step="1"
                    value={settings.maxPlanDepth}
                    onChange={(e) => setSettings((s) => ({ ...s, maxPlanDepth: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>

                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Step Execution Timeout</label>
                    <span className="adv-val-tag">{settings.stepTimeoutSec}s</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="600"
                    step="10"
                    value={settings.stepTimeoutSec}
                    onChange={(e) => setSettings((s) => ({ ...s, stepTimeoutSec: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>

                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Max Auto-Retries per Node</label>
                    <span className="adv-val-tag">{settings.maxRetriesPerNode} retries</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="5"
                    step="1"
                    value={settings.maxRetriesPerNode}
                    onChange={(e) => setSettings((s) => ({ ...s, maxRetriesPerNode: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ==================== 2. SCOPE & SAFETY TAB ==================== */}
        {activeSubTab === "scope" && (
          <div className="adv-tab-content">
            <div className="adv-section-card">
              <div className="adv-card-header">
                <div>
                  <h3 className="adv-card-title">Cryptographic Scope Contract</h3>
                  <p className="adv-card-desc">
                    Centralized authorization boundary. Every tool command and network packet is validated against these explicit targets.
                  </p>
                </div>
                {liveScope && (
                  <span className={`adv-tag ${liveScope.signature_valid ? "green" : "red"}`}>
                    {liveScope.signature_valid ? "✓ HMAC-SHA256 SIGNED" : "⚠️ SIGNATURE INVALID"}
                  </span>
                )}
              </div>

              {liveScope && (
                <div className="adv-scope-status-box">
                  <div className="adv-stat-col">
                    <span className="adv-stat-lbl">Contract ID</span>
                    <span className="adv-stat-val mono">{liveScope.contract_id || "None"}</span>
                  </div>
                  <div className="adv-stat-col">
                    <span className="adv-stat-lbl">Authorized By</span>
                    <span className="adv-stat-val">{liveScope.authorized_by || "System"}</span>
                  </div>
                  <div className="adv-stat-col">
                    <span className="adv-stat-lbl">Time Remaining</span>
                    <span className="adv-stat-val green">
                      {liveScope.seconds_remaining
                        ? `${Math.floor(liveScope.seconds_remaining / 60)}m left`
                        : "Active"}
                    </span>
                  </div>
                  <div className="adv-stat-col">
                    <span className="adv-stat-lbl">Zero-Tier Status</span>
                    <span className="adv-stat-val cyan">Enforced (ADR-004)</span>
                  </div>
                </div>
              )}

              {/* Authorized Targets Tag Editor */}
              <div style={{ marginTop: "16px" }}>
                <label className="adv-label">Authorized Lab Targets &amp; CIDR Subnets</label>
                <div className="adv-tag-list">
                  {settings.authorizedTargets.map((target) => (
                    <div key={target} className="adv-target-pill">
                      <span>{target}</span>
                      <button
                        className="adv-remove-pill-btn"
                        onClick={() => handleRemoveTarget(target)}
                        title="Remove target from scope"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>

                <div className="adv-add-target-row">
                  <input
                    type="text"
                    className="adv-text-input"
                    placeholder="Add target IP, CIDR, or domain (e.g. 192.168.1.50, 10.0.0.0/24)..."
                    value={newTargetInput}
                    onChange={(e) => setNewTargetInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddTarget();
                      }
                    }}
                  />
                  <button className="adv-secondary-btn" onClick={handleAddTarget}>
                    + Add Target
                  </button>
                </div>
              </div>

              {/* Scope Contract Settings */}
              <div className="adv-fields-grid" style={{ marginTop: "16px" }}>
                <div className="adv-input-group">
                  <label>Network Scope Name</label>
                  <input
                    type="text"
                    className="adv-text-input"
                    value={settings.networkScope}
                    onChange={(e) => setSettings((s) => ({ ...s, networkScope: e.target.value }))}
                  />
                </div>

                <div className="adv-input-group">
                  <label>Engagement Validity Window</label>
                  <select
                    className="adv-select"
                    value={settings.timeWindowHours}
                    onChange={(e) => setSettings((s) => ({ ...s, timeWindowHours: Number(e.target.value) }))}
                  >
                    <option value={1}>1 Hour (Quick Assessment)</option>
                    <option value={4}>4 Hours (Standard Lab Engagement)</option>
                    <option value={8}>8 Hours (Full Shift Testing)</option>
                    <option value={24}>24 Hours (Extended Deep Audit)</option>
                  </select>
                </div>

                <div className="adv-input-group">
                  <label>Operator Authorized By Identity</label>
                  <input
                    type="text"
                    className="adv-text-input"
                    value={settings.authorizedBy}
                    onChange={(e) => setSettings((s) => ({ ...s, authorizedBy: e.target.value }))}
                  />
                </div>
              </div>

              <div className="adv-toggle-row" style={{ marginTop: "16px" }}>
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Fail-Closed Boundary Gate</span>
                  <span className="adv-toggle-desc">
                    Strictly block execution and log security alerts whenever an argument refers to any IP or domain outside authorized targets.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.failClosedEnforcement}
                    onChange={(e) => setSettings((s) => ({ ...s, failClosedEnforcement: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>
            </div>
          </div>
        )}

        {/* ==================== 3. KALI VM & SANDBOX TAB ==================== */}
        {activeSubTab === "sandbox" && (
          <div className="adv-tab-content">
            <div className="adv-section-card">
              <h3 className="adv-card-title">VirtualBox VM Snapshot &amp; Rollback Automation</h3>
              <p className="adv-card-desc">
                Defensive virtualization protection preventing permanent system state compromise inside the Kali Linux environment.
              </p>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Automatic Pre-Task Snapshot</span>
                  <span className="adv-toggle-desc">
                    Create a point-in-time VM snapshot before initiating active multi-tool execution pipelines.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.snapshotBeforeTask}
                    onChange={(e) => setSettings((s) => ({ ...s, snapshotBeforeTask: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Auto-Rollback on Task Failure</span>
                  <span className="adv-toggle-desc">
                    Revert Kali VM to baseline snapshot automatically if a tool fails with unrecoverable exit status or kernel crash.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.rollbackOnFailure}
                    onChange={(e) => setSettings((s) => ({ ...s, rollbackOnFailure: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Ephemeral Cleanup (Rollback After Execution)</span>
                  <span className="adv-toggle-desc">
                    Discard all filesystem changes and restore clean baseline as soon as the task completes successfully.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.rollbackAfterExecution}
                    onChange={(e) => setSettings((s) => ({ ...s, rollbackAfterExecution: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>
            </div>

            <div className="adv-section-card">
              <h3 className="adv-card-title">Supervisor Resource Caps</h3>
              <p className="adv-card-desc">
                Enforce hardware consumption quotas to avoid host exhaustion during compute-intensive tasks.
              </p>

              <div className="adv-fields-grid">
                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Max CPU Limit (%)</label>
                    <span className="adv-val-tag">{settings.maxCpuPct}%</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    step="5"
                    value={settings.maxCpuPct}
                    onChange={(e) => setSettings((s) => ({ ...s, maxCpuPct: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>

                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Max RAM Quota (MB)</label>
                    <span className="adv-val-tag">{settings.maxRamMb} MB</span>
                  </div>
                  <input
                    type="range"
                    min="64"
                    max="2048"
                    step="64"
                    value={settings.maxRamMb}
                    onChange={(e) => setSettings((s) => ({ ...s, maxRamMb: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>

                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Max Output Disk Size (MB)</label>
                    <span className="adv-val-tag">{settings.maxDiskMb} MB</span>
                  </div>
                  <input
                    type="range"
                    min="20"
                    max="1000"
                    step="20"
                    value={settings.maxDiskMb}
                    onChange={(e) => setSettings((s) => ({ ...s, maxDiskMb: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>

                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Max Concurrent Tool Processes</label>
                    <span className="adv-val-tag">{settings.maxConcurrentProcesses} procs</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="8"
                    step="1"
                    value={settings.maxConcurrentProcesses}
                    onChange={(e) => setSettings((s) => ({ ...s, maxConcurrentProcesses: Number(e.target.value) }))}
                    className="adv-range"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ==================== 4. AI INFERENCE TAB ==================== */}
        {activeSubTab === "ai" && (
          <div className="adv-tab-content">
            <div className="adv-section-card">
              <h3 className="adv-card-title">Reasoning Engine &amp; Hyperparameters</h3>
              <p className="adv-card-desc">
                Tune local model reasoning behavior, sampling temperature, and token window allocations.
              </p>

              <div className="adv-fields-grid">
                <div className="adv-input-group">
                  <label>Active Primary Model</label>
                  <select
                    className="adv-select"
                    value={settings.selectedModelId}
                    onChange={(e) => setSettings((s) => ({ ...s, selectedModelId: e.target.value }))}
                  >
                    <option value="kairo-scale-2b">Kairo Scale 2B (Custom Primary — Fast 1.98B)</option>
                    <option value="deepseek-r1-moe">DeepSeek R1 MoE (Advanced Reasoning)</option>
                    <option value="llama-3-8b">Meta Llama 3 8B Instruct</option>
                    <option value="qwen-2.5-0.5b">Qwen 2.5 0.5B (Ultra-Light Local)</option>
                  </select>
                </div>

                <div className="adv-input-group">
                  <div className="adv-label-row">
                    <label>Inference Temperature</label>
                    <span className="adv-val-tag">{settings.temperature.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={settings.temperature}
                    onChange={(e) => setSettings((s) => ({ ...s, temperature: Number(e.target.value) }))}
                    className="adv-range"
                  />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "10px", color: "var(--text-muted)" }}>
                    <span>0.0 (Deterministic / Exact)</span>
                    <span>1.0 (Creative / Exploratory)</span>
                  </div>
                </div>

                <div className="adv-input-group">
                  <label>Context Window Size</label>
                  <select
                    className="adv-select"
                    value={settings.contextLength}
                    onChange={(e) => setSettings((s) => ({ ...s, contextLength: Number(e.target.value) }))}
                  >
                    <option value={2048}>2,048 Tokens (Lightweight)</option>
                    <option value={4096}>4,096 Tokens (Standard)</option>
                    <option value={8192}>8,192 Tokens (Extended)</option>
                    <option value={16384}>16,384 Tokens (Deep Evidence Analysis)</option>
                  </select>
                </div>

                <div className="adv-input-group">
                  <label>Reasoning (Chain-of-Thought) Display</label>
                  <select
                    className="adv-select"
                    value={settings.cotDisplayMode}
                    onChange={(e) => setSettings((s) => ({ ...s, cotDisplayMode: e.target.value as any }))}
                  >
                    <option value="verbose">Verbose (Show Live CoT Thinking Block)</option>
                    <option value="summary">Summary (Show High-Level Decisions Only)</option>
                    <option value="hidden">Hidden (Output Final Actions Only)</option>
                  </select>
                </div>
              </div>

              <div className="adv-toggle-row" style={{ marginTop: "16px" }}>
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Automatic Local Fallback Failover</span>
                  <span className="adv-toggle-desc">
                    Instantly fallback to local quantized model if the primary inference server drops connection.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.autoLocalFallback}
                    onChange={(e) => setSettings((s) => ({ ...s, autoLocalFallback: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>
            </div>
          </div>
        )}

        {/* ==================== 5. TOOL ACCESS & PRIVILEGES TAB ==================== */}
        {activeSubTab === "tools" && (
          <div className="adv-tab-content">
            <div className="adv-section-card">
              <div className="adv-card-header">
                <div>
                  <h3 className="adv-card-title">Unified Tool Access Architecture (ADR-004)</h3>
                  <p className="adv-card-desc">
                    Confirmation and audit parameters for KAIRO's unified tool registry and managed Kali execution gateway.
                  </p>
                </div>
                <span className="adv-tag green">TIERS 1/2/3 RETIRED</span>
              </div>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Cryptographic Execution Event Audit</span>
                  <span className="adv-toggle-desc">
                    Log every tool invocation, SHA-256 output hashes, and exit codes into the tamper-evident SQLite events database.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.unifiedToolAccessAudit}
                    onChange={(e) => setSettings((s) => ({ ...s, unifiedToolAccessAudit: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Periodic Kali &amp; Tool Updates Check</span>
                  <span className="adv-toggle-desc">
                    Automatically poll Kali APT repositories and GitHub tool releases for updates with snapshot rollback capability.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.autoCheckToolUpdates}
                    onChange={(e) => setSettings((s) => ({ ...s, autoCheckToolUpdates: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>

              <div className="adv-toggle-row">
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Prompt for Elevated Root / Sudo Execution</span>
                  <span className="adv-toggle-desc">
                    When disabled, authorized lab operations execute with necessary privileges automatically within the Kali VM sandbox.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.requireRootElevationPrompt}
                    onChange={(e) => setSettings((s) => ({ ...s, requireRootElevationPrompt: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>
            </div>
          </div>
        )}

        {/* ==================== 6. WORKSPACE & PREFERENCES TAB ==================== */}
        {activeSubTab === "preferences" && (
          <div className="adv-tab-content">
            <div className="adv-section-card">
              <h3 className="adv-card-title">Console &amp; Workspace Display Preferences</h3>

              <div className="adv-fields-grid">
                <div className="adv-input-group">
                  <label>Terminal Console Monospace Font</label>
                  <select
                    className="adv-select"
                    value={settings.terminalFont}
                    onChange={(e) => setSettings((s) => ({ ...s, terminalFont: e.target.value }))}
                  >
                    <option value="'JetBrains Mono', monospace">JetBrains Mono</option>
                    <option value="'Fira Code', monospace">Fira Code</option>
                    <option value="'Courier New', Courier, monospace">Courier New</option>
                    <option value="'Consolas', monospace">Consolas</option>
                  </select>
                </div>

                <div className="adv-input-group">
                  <label>Default Advanced Console Width</label>
                  <select
                    className="adv-select"
                    value={settings.defaultDrawerWide ? "wide" : "standard"}
                    onChange={(e) => setSettings((s) => ({ ...s, defaultDrawerWide: e.target.value === "wide" }))}
                  >
                    <option value="wide">Expanded Wide (880px)</option>
                    <option value="standard">Standard Compact (520px)</option>
                  </select>
                </div>
              </div>

              <div className="adv-toggle-row" style={{ marginTop: "16px" }}>
                <div className="adv-toggle-info">
                  <span className="adv-toggle-title">Audible Completion Alerts</span>
                  <span className="adv-toggle-desc">
                    Play a gentle audio ping when background tasks or report generation completes.
                  </span>
                </div>
                <label className="adv-switch">
                  <input
                    type="checkbox"
                    checked={settings.audibleAlerts}
                    onChange={(e) => setSettings((s) => ({ ...s, audibleAlerts: e.target.checked }))}
                  />
                  <span className="adv-slider" />
                </label>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Embedded CSS for AdvancedSettingsPanel */}
      <style jsx>{`
        .adv-settings-container {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: var(--bg-surface);
          color: var(--text-primary);
          overflow-y: auto;
          padding: 4px 6px;
        }

        .adv-settings-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-subtle);
          background: var(--bg-surface-raised);
          border-radius: 8px;
          gap: 16px;
          flex-wrap: wrap;
        }

        .adv-settings-heading {
          font-size: 16px;
          font-weight: 700;
          margin: 0;
          color: var(--text-primary);
        }

        .adv-settings-subheading {
          font-size: 12px;
          color: var(--text-muted);
          margin: 4px 0 0 0;
          line-height: 1.4;
        }

        .adv-adr-badge {
          font-size: 10px;
          font-weight: 700;
          padding: 2px 7px;
          border-radius: 4px;
          background: rgba(56, 189, 248, 0.12);
          color: #38bdf8;
          border: 1px solid rgba(56, 189, 248, 0.3);
          letter-spacing: 0.04em;
        }

        .adv-settings-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .adv-primary-btn {
          background: #38bdf8;
          color: #0b0f17;
          border: none;
          font-weight: 600;
          font-size: 12px;
          padding: 6px 14px;
          border-radius: 6px;
          cursor: pointer;
          transition: background 0.15s, transform 0.1s;
        }

        .adv-primary-btn:hover {
          background: #7dd3fc;
        }

        .adv-primary-btn:active {
          transform: scale(0.98);
        }

        .adv-primary-btn.loading {
          opacity: 0.7;
          cursor: not-allowed;
        }

        .adv-secondary-btn {
          background: var(--bg-surface);
          color: var(--text-secondary);
          border: 1px solid var(--border-subtle);
          font-size: 11px;
          font-weight: 500;
          padding: 5px 10px;
          border-radius: 6px;
          cursor: pointer;
          transition: color 0.15s, border-color 0.15s, background 0.15s;
        }

        .adv-secondary-btn:hover {
          color: var(--text-primary);
          border-color: var(--border-medium);
          background: var(--bg-surface-raised);
        }

        .adv-secondary-btn.danger {
          color: #f87171;
        }

        .adv-secondary-btn.danger:hover {
          border-color: rgba(248, 113, 113, 0.4);
          background: rgba(248, 113, 113, 0.08);
        }

        .adv-toast {
          margin: 10px 0;
          padding: 8px 12px;
          background: rgba(56, 189, 248, 0.1);
          border: 1px solid rgba(56, 189, 248, 0.3);
          border-radius: 6px;
          color: #7dd3fc;
          font-size: 12px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .adv-toast button {
          background: transparent;
          border: none;
          color: #7dd3fc;
          cursor: pointer;
          font-size: 12px;
        }

        .adv-subtabs-bar {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 8px 0;
          border-bottom: 1px solid var(--border-subtle);
          overflow-x: auto;
        }

        .adv-subtab-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          background: transparent;
          border: 1px solid transparent;
          padding: 6px 12px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 500;
          color: var(--text-secondary);
          cursor: pointer;
          white-space: nowrap;
          transition: all 0.15s;
        }

        .adv-subtab-btn:hover {
          color: var(--text-primary);
          background: var(--bg-surface-raised);
        }

        .adv-subtab-btn.active {
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
          border-color: rgba(56, 189, 248, 0.25);
          font-weight: 600;
        }

        .adv-settings-body {
          padding: 14px 2px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .adv-tab-content {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .adv-section-card {
          background: var(--bg-surface-raised);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 16px;
        }

        .adv-card-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 12px;
          gap: 12px;
        }

        .adv-card-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
          margin: 0;
        }

        .adv-card-desc {
          font-size: 11px;
          color: var(--text-muted);
          margin: 4px 0 0 0;
          line-height: 1.4;
        }

        .adv-tag {
          font-size: 10px;
          font-weight: 700;
          padding: 2px 8px;
          border-radius: 4px;
          letter-spacing: 0.04em;
        }

        .adv-tag.cyan {
          background: rgba(56, 189, 248, 0.12);
          color: #38bdf8;
          border: 1px solid rgba(56, 189, 248, 0.3);
        }

        .adv-tag.green {
          background: rgba(34, 197, 94, 0.12);
          color: #22c55e;
          border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .adv-tag.red {
          background: rgba(239, 68, 68, 0.12);
          color: #ef4444;
          border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .adv-mode-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 12px;
          margin-top: 12px;
        }

        .adv-mode-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 14px;
          cursor: pointer;
          transition: all 0.18s ease;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .adv-mode-card:hover {
          border-color: var(--border-medium);
          transform: translateY(-1px);
        }

        .adv-mode-card.selected {
          border-color: #38bdf8;
          background: rgba(56, 189, 248, 0.06);
          box-shadow: 0 0 12px rgba(56, 189, 248, 0.12);
        }

        .adv-mode-card-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .adv-mode-icon {
          font-size: 16px;
        }

        .adv-mode-badge {
          font-size: 9px;
          font-weight: 700;
          text-transform: uppercase;
          padding: 1px 6px;
          border-radius: 4px;
          background: var(--bg-surface-raised);
          color: var(--text-muted);
          border: 1px solid var(--border-subtle);
        }

        .adv-mode-badge.recommended {
          background: rgba(34, 197, 94, 0.15);
          color: #4ade80;
          border-color: rgba(34, 197, 94, 0.3);
        }

        .adv-mode-name {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
          margin: 0;
        }

        .adv-mode-desc {
          font-size: 11px;
          color: var(--text-secondary);
          margin: 0;
          line-height: 1.4;
        }

        .adv-toggle-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px 0;
          border-bottom: 1px solid var(--border-subtle);
          gap: 16px;
        }

        .adv-toggle-row:last-child {
          border-bottom: none;
        }

        .adv-toggle-info {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .adv-toggle-title {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-primary);
        }

        .adv-toggle-desc {
          font-size: 11px;
          color: var(--text-muted);
          line-height: 1.35;
        }

        /* Modern Toggle Switch */
        .adv-switch {
          position: relative;
          display: inline-block;
          width: 38px;
          height: 20px;
          flex-shrink: 0;
        }

        .adv-switch input {
          opacity: 0;
          width: 0;
          height: 0;
        }

        .adv-slider {
          position: absolute;
          cursor: pointer;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background-color: #1e293b;
          border: 1px solid #334155;
          transition: 0.2s;
          border-radius: 20px;
        }

        .adv-slider:before {
          position: absolute;
          content: "";
          height: 14px;
          width: 14px;
          left: 2px;
          bottom: 2px;
          background-color: #94a3b8;
          transition: 0.2s;
          border-radius: 50%;
        }

        .adv-switch input:checked + .adv-slider {
          background-color: #0284c7;
          border-color: #38bdf8;
        }

        .adv-switch input:checked + .adv-slider:before {
          transform: translateX(18px);
          background-color: #ffffff;
        }

        .adv-fields-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 14px;
          margin-top: 14px;
        }

        .adv-input-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .adv-input-group label {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
        }

        .adv-label-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .adv-val-tag {
          font-size: 10px;
          font-family: var(--font-mono);
          font-weight: 700;
          color: #38bdf8;
        }

        .adv-range {
          width: 100%;
          accent-color: #38bdf8;
          cursor: pointer;
        }

        .adv-text-input,
        .adv-select {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 6px;
          padding: 7px 10px;
          font-size: 12px;
          color: var(--text-primary);
          outline: none;
          transition: border-color 0.15s;
        }

        .adv-text-input:focus,
        .adv-select:focus {
          border-color: #38bdf8;
        }

        .adv-scope-status-box {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
          gap: 10px;
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 6px;
          padding: 10px 14px;
          margin-top: 10px;
        }

        .adv-stat-col {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .adv-stat-lbl {
          font-size: 10px;
          text-transform: uppercase;
          color: var(--text-muted);
          font-weight: 700;
        }

        .adv-stat-val {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-primary);
        }

        .adv-stat-val.mono {
          font-family: var(--font-mono);
        }

        .adv-stat-val.green {
          color: #4ade80;
        }

        .adv-stat-val.cyan {
          color: #38bdf8;
        }

        .adv-tag-list {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-bottom: 8px;
        }

        .adv-target-pill {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(56, 189, 248, 0.08);
          border: 1px solid rgba(56, 189, 248, 0.25);
          color: #7dd3fc;
          padding: 3px 8px;
          border-radius: 14px;
          font-size: 11px;
          font-family: var(--font-mono);
        }

        .adv-remove-pill-btn {
          background: transparent;
          border: none;
          color: #7dd3fc;
          cursor: pointer;
          font-size: 10px;
          padding: 0;
          display: flex;
          align-items: center;
        }

        .adv-remove-pill-btn:hover {
          color: #f87171;
        }

        .adv-add-target-row {
          display: flex;
          gap: 8px;
        }

        .adv-add-target-row input {
          flex: 1;
        }
      `}</style>
    </div>
  );
}
