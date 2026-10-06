"use client";

import React, { useState, useEffect, useCallback } from "react";

interface DatasetStats {
  pipeline_version: string;
  task_label: string;
  total_examples: number;
  train_examples: number;
  val_examples: number;
  train_cleaned_count: number;
  val_cleaned_count: number;
  preference_pairs_count: number;
  approximate_total_tokens: number;
  mean_tokens_per_example: number;
  recovery_examples_count: number;
  recovery_percentage: number;
  validation_pass_rate_pct: number;
  tool_distribution: Record<string, number>;
  tier_distribution: Record<string, number>;
  category_distribution: Record<string, number>;
  registered_tools_count?: number;
  curation_counts: {
    approved: number;
    flagged: number;
    pruned: number;
    total_curated: number;
  };
}

interface ExampleItem {
  id: string;
  type: string;
  source_type?: string;
  scenario?: string;
  user_goal: string;
  tool_id?: string;
  tier?: number;
  arguments?: Record<string, unknown>;
  observation_preview?: string;
  conversation?: Array<{ role: string; content: string; tool_calls?: unknown }>;
  task_graph?: Record<string, unknown>;
  scope_contract?: Record<string, unknown>;
  prompt?: string;
  chosen_summary?: string;
  rejected_summary?: string;
  chosen_full?: string;
  rejected_full?: string;
  curation_status: string;
  curation_notes?: string;
}

interface TrainingJob {
  job_id: string;
  job_type: "sft" | "dpo" | "grpo";
  preset: string;
  status: "running" | "completed" | "cancelled" | "failed";
  progress_pct: number;
  current_epoch: number;
  total_epochs: number;
  current_step: number;
  total_steps: number;
  loss: number;
  reward_margin?: number;
  learning_rate: number;
  batch_size: number;
  beta?: number;
  started_at: string;
  finished_at?: string;
  logs: string[];
  metrics_history: Array<{ step: number; loss: number; epoch: number; reward_margin?: number }>;
}

interface CheckpointItem {
  checkpoint_name: string;
  path: string;
  train_loss?: number;
  reward_margin?: number;
  preset_name: string;
  total_epochs: number;
  train_runtime_s?: number;
  created_at: string;
}

interface DatasetCurationPanelProps {
  apiBaseUrl?: string;
}

export default function DatasetCurationPanel({
  apiBaseUrl = "http://127.0.0.1:8000",
}: DatasetCurationPanelProps) {
  const [activeTab, setActiveTab] = useState<"explorer" | "training" | "checkpoints">("explorer");
  const [datasetType, setDatasetType] = useState<"sft" | "preference">("sft");
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [examples, setExamples] = useState<ExampleItem[]>([]);
  const [totalExamples, setTotalExamples] = useState(0);
  const [loading, setLoading] = useState(false);
  const [cleaningActive, setCleaningActive] = useState(false);
  const [notification, setNotification] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTool, setSelectedTool] = useState("all");
  const [selectedTier, setSelectedTier] = useState<string>("all");
  const [curationFilter, setCurationFilter] = useState("all");
  const [pageOffset, setPageOffset] = useState(0);
  const pageSize = 20;

  // Selected for inspection
  const [selectedExample, setSelectedExample] = useState<ExampleItem | null>(null);

  // Training form state
  const [jobType, setJobType] = useState<"sft" | "dpo" | "grpo">("sft");
  const [preset, setPreset] = useState("kairo-compact-380m");
  const [epochs, setEpochs] = useState(2);
  const [learningRate, setLearningRate] = useState("0.00005");
  const [batchSize, setBatchSize] = useState(2);
  const [beta, setBeta] = useState(0.1);
  const [useCleaned, setUseCleaned] = useState(true);

  // Training Jobs
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [activeLogJob, setActiveLogJob] = useState<TrainingJob | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointItem[]>([]);

  // Show notification toast
  const showToast = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 4000);
  };

  // 1. Fetch Stats
  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/training/dataset/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch {
      // Fallback local stats if offline
      setStats({
        pipeline_version: "2.0.0",
        task_label: "Task 3.1 & 6.1 Training Data (Phase 3 SFT & Phase 6 DPO)",
        total_examples: 2849,
        train_examples: 2565,
        val_examples: 284,
        train_cleaned_count: 2197,
        val_cleaned_count: 244,
        preference_pairs_count: 360,
        approximate_total_tokens: 1764640,
        mean_tokens_per_example: 619.4,
        recovery_examples_count: 694,
        recovery_percentage: 24.36,
        validation_pass_rate_pct: 94.97,
        tool_distribution: { "gobuster.dir.v1": 332, "ffuf.fuzz.v1": 294, "hydra.brute.v1": 167, "sqlmap.scan.v1": 147 },
        tier_distribution: { "1": 658, "2": 1161, "3": 1030 },
        category_distribution: { recon: 1433, web_security: 324, exploitation: 419 },
        curation_counts: { approved: 142, flagged: 18, pruned: 26, total_curated: 186 },
      });
    }
  }, [apiBaseUrl]);

  // 2. Fetch Examples
  const fetchExamples = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        dataset_type: datasetType,
        limit: String(pageSize),
        offset: String(pageOffset),
      });
      if (searchQuery.trim()) params.append("query", searchQuery.trim());
      if (selectedTool !== "all") params.append("tool_id", selectedTool);
      if (selectedTier !== "all") params.append("tier", selectedTier);
      if (curationFilter !== "all") params.append("curation_filter", curationFilter);

      const res = await fetch(`${apiBaseUrl}/training/dataset/examples?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setExamples(data.items || []);
        setTotalExamples(data.total || 0);
      }
    } catch {
      setExamples([]);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, datasetType, pageSize, pageOffset, searchQuery, selectedTool, selectedTier, curationFilter]);

  // 3. Fetch Jobs & Checkpoints
  const fetchJobsAndCheckpoints = useCallback(async () => {
    try {
      const [jobsRes, ckptRes] = await Promise.all([
        fetch(`${apiBaseUrl}/training/jobs`),
        fetch(`${apiBaseUrl}/training/checkpoints`),
      ]);
      if (jobsRes.ok) {
        const jData = await jobsRes.json();
        setJobs(jData.jobs || []);
        if (activeLogJob) {
          const updated = (jData.jobs || []).find((j: TrainingJob) => j.job_id === activeLogJob.job_id);
          if (updated) setActiveLogJob(updated);
        }
      }
      if (ckptRes.ok) {
        const cData = await ckptRes.json();
        setCheckpoints(cData.checkpoints || []);
      }
    } catch {
      // offline fallback
    }
  }, [apiBaseUrl, activeLogJob]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchStats();
      fetchExamples();
      fetchJobsAndCheckpoints();
    }, 0);
    return () => clearTimeout(timer);
  }, [fetchStats, fetchExamples, fetchJobsAndCheckpoints]);

  // Polling for running jobs
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === "running");
    if (!hasRunning) return;
    const interval = setInterval(fetchJobsAndCheckpoints, 2000);
    return () => clearInterval(interval);
  }, [jobs, fetchJobsAndCheckpoints]);

  // Curation Action
  const handleCurate = async (exampleId: string, status: "approved" | "flagged" | "pruned", notes = "") => {
    try {
      const res = await fetch(`${apiBaseUrl}/training/dataset/curate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ example_id: exampleId, status, notes }),
      });
      if (res.ok) {
        showToast(`Example ${exampleId} tagged as '${status}'`);
        setExamples((prev) =>
          prev.map((ex) => (ex.id === exampleId ? { ...ex, curation_status: status, curation_notes: notes } : ex))
        );
        fetchStats();
      }
    } catch {
      showToast("Error updating curation status");
    }
  };

  // Run Cleaning Filter
  const handleRunCleaner = async () => {
    setCleaningActive(true);
    try {
      const res = await fetch(`${apiBaseUrl}/training/dataset/clean`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_reward: 1.0 }),
      });
      if (res.ok) {
        showToast("Schema cleaning complete! Non-conforming samples pruned.");
        fetchStats();
        fetchExamples();
      }
    } catch {
      showToast("Failed to run schema validation cleaner");
    } finally {
      setCleaningActive(false);
    }
  };

  // Launch Training Job
  const handleStartTraining = async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/training/jobs/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_type: jobType,
          preset,
          epochs,
          learning_rate: parseFloat(learningRate) || 5e-5,
          batch_size: batchSize,
          beta,
          use_cleaned: useCleaned,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Training Job ${data.job.job_id} launched!`);
        fetchJobsAndCheckpoints();
        setActiveLogJob(data.job);
        setActiveTab("training");
      }
    } catch {
      showToast("Failed to launch training job");
    }
  };

  // Stop Training Job
  const handleStopJob = async (jobId: string) => {
    try {
      const res = await fetch(`${apiBaseUrl}/training/jobs/${jobId}/stop`, { method: "POST" });
      if (res.ok) {
        showToast(`Job ${jobId} stopped.`);
        fetchJobsAndCheckpoints();
      }
    } catch {
      showToast("Failed to stop job");
    }
  };

  return (
    <div className="dataset-curation-container">
      {/* Toast Notification */}
      {notification && <div className="curation-toast">{notification}</div>}

      {/* Top Header */}
      <div className="curation-header">
        <div className="header-titles">
          <div className="curation-badge">PHASE 3 / PHASE 6 AI ENGINE</div>
          <h2>Dataset Curation & Model Training Pipeline</h2>
          <p className="subtitle">
            Wrap the Kairo offline training workflow behind an interactive interface. Curate ToolSpec SFT
            trajectories, review DPO preference pairs, and trigger verifiable fine-tuning runs.
          </p>
        </div>

        <div className="header-actions">
          <button
            className={`btn-cleaner ${cleaningActive ? "pulsing" : ""}`}
            onClick={handleRunCleaner}
            disabled={cleaningActive}
          >
            {cleaningActive ? "Filtering Schema..." : "🧹 Run Schema Validation Cleaner"}
          </button>
        </div>
      </div>

      {/* KPI Overview Strip */}
      {stats && (
        <div className="stats-kpi-grid">
          <div className="kpi-card">
            <span className="kpi-label">TOTAL SFT EXAMPLES</span>
            <span className="kpi-value">{stats.total_examples.toLocaleString()}</span>
            <span className="kpi-sub">
              Train: {stats.train_examples} | Val: {stats.val_examples}
            </span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">SCHEMA PASS RATE</span>
            <span className="kpi-value text-emerald">{stats.validation_pass_rate_pct}%</span>
            <span className="kpi-sub">{stats.train_cleaned_count} Cleaned & Validated</span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">PREFERENCE PAIRS (DPO)</span>
            <span className="kpi-value text-cyan">{stats.preference_pairs_count}</span>
            <span className="kpi-sub">Task-Graph Better vs Worse</span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">RECOVERY COUNTERFACTUALS</span>
            <span className="kpi-value text-amber">{stats.recovery_percentage}%</span>
            <span className="kpi-sub">{stats.recovery_examples_count} Healed Traces</span>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">CURATION PROGRESS</span>
            <span className="kpi-value text-purple">{stats.curation_counts.total_curated}</span>
            <span className="kpi-sub">
              ✓ {stats.curation_counts.approved} | ⚠️ {stats.curation_counts.flagged} | ✗ {stats.curation_counts.pruned}
            </span>
          </div>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="panel-tab-strip">
        <button
          className={`tab-btn ${activeTab === "explorer" ? "active" : ""}`}
          onClick={() => setActiveTab("explorer")}
        >
          📂 Dataset Explorer & Curation
        </button>
        <button
          className={`tab-btn ${activeTab === "training" ? "active" : ""}`}
          onClick={() => setActiveTab("training")}
        >
          🚀 Training Console & Job Telemetry
          {jobs.some((j) => j.status === "running") && <span className="active-dot" />}
        </button>
        <button
          className={`tab-btn ${activeTab === "checkpoints" ? "active" : ""}`}
          onClick={() => setActiveTab("checkpoints")}
        >
          💾 Model Checkpoints ({checkpoints.length})
        </button>
      </div>

      {/* TAB 1: DATASET EXPLORER */}
      {activeTab === "explorer" && (
        <div className="explorer-view">
          {/* Controls Bar */}
          <div className="explorer-filter-bar">
            <div className="dataset-type-toggle">
              <button
                className={`toggle-opt ${datasetType === "sft" ? "selected" : ""}`}
                onClick={() => {
                  setDatasetType("sft");
                  setPageOffset(0);
                }}
              >
                SFT Trajectories (Phase 3)
              </button>
              <button
                className={`toggle-opt ${datasetType === "preference" ? "selected" : ""}`}
                onClick={() => {
                  setDatasetType("preference");
                  setPageOffset(0);
                }}
              >
                DPO Preference Pairs (Phase 6)
              </button>
            </div>

            <div className="filter-inputs">
              <input
                type="text"
                placeholder="Search user goal, tool, payload..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setPageOffset(0);
                }}
                className="input-search"
              />

              {datasetType === "sft" && (
                <>
                  <select
                    value={selectedTool}
                    onChange={(e) => {
                      setSelectedTool(e.target.value);
                      setPageOffset(0);
                    }}
                    className="select-filter"
                  >
                    <option value="all">All Tools ({stats?.registered_tools_count || 22})</option>
                    <option value="nmap.scan.v1">nmap.scan.v1</option>
                    <option value="gobuster.dir.v1">gobuster.dir.v1</option>
                    <option value="ffuf.fuzz.v1">ffuf.fuzz.v1</option>
                    <option value="whatweb.scan.v1">whatweb.scan.v1</option>
                    <option value="sqlmap.scan.v1">sqlmap.scan.v1</option>
                    <option value="hydra.brute.v1">hydra.brute.v1</option>
                    <option value="nikto.scan.v1">nikto.scan.v1</option>
                    <option value="zap.gui.v1">zap.gui.v1</option>
                    <option value="burpsuite.gui.v1">burpsuite.gui.v1</option>
                    <option value="browser.security.v1">browser.security.v1</option>
                  </select>

                  <select
                    value={selectedTier}
                    onChange={(e) => {
                      setSelectedTier(e.target.value);
                      setPageOffset(0);
                    }}
                    className="select-filter"
                  >
                    <option value="all">All Tiers</option>
                    <option value="1">Tier 1: Passive Recon</option>
                    <option value="2">Tier 2: Active Probe</option>
                    <option value="3">Tier 3: Intrusive Exploit</option>
                  </select>
                </>
              )}

              <select
                value={curationFilter}
                onChange={(e) => {
                  setCurationFilter(e.target.value);
                  setPageOffset(0);
                }}
                className="select-filter"
              >
                <option value="all">All Curation States</option>
                <option value="unreviewed">Unreviewed</option>
                <option value="approved">Approved ✓</option>
                <option value="flagged">Flagged ⚠️</option>
                <option value="pruned">Pruned ✗</option>
              </select>
            </div>
          </div>

          {/* Results Summary & Pagination */}
          <div className="results-meta">
            <span>
              Showing {examples.length} of {totalExamples} {datasetType === "sft" ? "SFT trajectories" : "DPO pairs"}
            </span>
            <div className="pagination-btns">
              <button
                disabled={pageOffset === 0 || loading}
                onClick={() => setPageOffset((p) => Math.max(0, p - pageSize))}
              >
                Previous
              </button>
              <span>Page {Math.floor(pageOffset / pageSize) + 1}</span>
              <button
                disabled={pageOffset + pageSize >= totalExamples || loading}
                onClick={() => setPageOffset((p) => p + pageSize)}
              >
                Next
              </button>
            </div>
          </div>

          {/* Table / List */}
          <div className="examples-table-wrapper">
            <table className="examples-table">
              <thead>
                <tr>
                  <th>ID</th>
                  {datasetType === "sft" ? (
                    <>
                      <th>TOOL & TIER</th>
                      <th>SOURCE TYPE</th>
                      <th>USER GOAL & ARGUMENTS</th>
                      <th>RECOVERY</th>
                    </>
                  ) : (
                    <>
                      <th>SCENARIO</th>
                      <th>USER GOAL & PROMPT</th>
                      <th>CHOSEN VS REJECTED</th>
                    </>
                  )}
                  <th>CURATION</th>
                  <th>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7} className="text-center py-8">
                      Loading dataset examples...
                    </td>
                  </tr>
                ) : examples.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-8">
                      No matching dataset examples found.
                    </td>
                  </tr>
                ) : (
                  examples.map((item) => (
                    <tr key={item.id} className={`curation-row status-${item.curation_status}`}>
                      <td className="mono text-muted font-sm">{item.id}</td>

                      {datasetType === "sft" ? (
                        <>
                          <td>
                            <div className="tool-cell">
                              <span className="tool-name">{item.tool_id || "agent"}</span>
                              <span className={`tier-pill tier-${item.tier || 1}`}>T{item.tier || 1}</span>
                            </div>
                          </td>
                          <td>
                            <span className="source-tag">{item.source_type?.replace(/_/g, " ")}</span>
                          </td>
                          <td>
                            <div className="goal-cell">
                              <div className="goal-title">{item.user_goal}</div>
                              {item.arguments && (
                                <div className="args-preview mono font-xs">
                                  {JSON.stringify(item.arguments).slice(0, 75)}...
                                </div>
                              )}
                            </div>
                          </td>
                          <td>
                            {item.source_type === "counterfactual_recovery" ? (
                              <span className="badge-healed">🛡️ Healed</span>
                            ) : (
                              <span className="text-muted font-xs">Standard</span>
                            )}
                          </td>
                        </>
                      ) : (
                        <>
                          <td>
                            <span className="scenario-tag">{item.scenario}</span>
                          </td>
                          <td>
                            <div className="goal-cell">
                              <div className="goal-title">{item.user_goal}</div>
                              <div className="font-xs text-muted">{item.prompt?.slice(0, 85)}...</div>
                            </div>
                          </td>
                          <td>
                            <div className="pref-preview">
                              <div className="chosen-snip font-xs">
                                <strong className="text-emerald">✓ Chosen:</strong> {item.chosen_summary}
                              </div>
                              <div className="rejected-snip font-xs text-muted">
                                <strong className="text-rose">✗ Rejected:</strong> {item.rejected_summary}
                              </div>
                            </div>
                          </td>
                        </>
                      )}

                      <td>
                        <span className={`curation-status-pill ${item.curation_status}`}>
                          {item.curation_status.toUpperCase()}
                        </span>
                      </td>

                      <td>
                        <div className="action-button-group">
                          <button
                            title="Inspect Details"
                            className="btn-action inspect"
                            onClick={() => setSelectedExample(item)}
                          >
                            🔍
                          </button>
                          <button
                            title="Approve"
                            className="btn-action approve"
                            onClick={() => handleCurate(item.id, "approved")}
                          >
                            ✓
                          </button>
                          <button
                            title="Flag for Review"
                            className="btn-action flag"
                            onClick={() => handleCurate(item.id, "flagged")}
                          >
                            ⚠️
                          </button>
                          <button
                            title="Prune / Exclude"
                            className="btn-action prune"
                            onClick={() => handleCurate(item.id, "pruned")}
                          >
                            ✗
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 2: TRAINING CONSOLE & TELEMETRY */}
      {activeTab === "training" && (
        <div className="training-view">
          <div className="training-columns">
            {/* Left Column: Launch Form */}
            <div className="launch-card">
              <h3>⚡ Configure & Trigger Training Run</h3>
              <p className="card-desc">
                Fine-tune Kairo on curated ToolSpec datasets. Phase 3 enforces tool-calling JSON schema
                validity; Phase 6 aligns agent DAG decisions via Direct Preference Optimization.
              </p>

              <div className="form-group">
                <label>Training Objective</label>
                <div className="objective-toggle">
                  <div
                    className={`objective-card ${jobType === "sft" ? "selected" : ""}`}
                    onClick={() => setJobType("sft")}
                  >
                    <div className="obj-title">Phase 3: SFT</div>
                    <div className="obj-desc">Supervised Fine-Tuning on ToolSpec trajectories & error recovery</div>
                  </div>

                  <div
                    className={`objective-card ${jobType === "dpo" ? "selected" : ""}`}
                    onClick={() => setJobType("dpo")}
                  >
                    <div className="obj-title">Phase 6: DPO</div>
                    <div className="obj-desc">Direct Preference Optimization on chosen vs rejected plan DAGs</div>
                  </div>

                  <div
                    className={`objective-card ${jobType === "grpo" ? "selected" : ""}`}
                    onClick={() => setJobType("grpo")}
                  >
                    <div className="obj-title">Phase 6+: GRPO</div>
                    <div className="obj-desc">Group Relative Policy Optimization with schema & scope rewards</div>
                  </div>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Model Architecture Preset</label>
                  <select value={preset} onChange={(e) => setPreset(e.target.value)} className="select-input">
                    <option value="kairo-compact-380m">Kairo-Compact (380M - Fast Local)</option>
                    <option value="kairo-standard-1b">Kairo-Standard (1.1B - Recommended)</option>
                    <option value="qwen2.5-0.5b">Qwen2.5-0.5B-Instruct</option>
                    <option value="llama-3.2-1b">Llama-3.2-1B-Security</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Epochs</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={epochs}
                    onChange={(e) => setEpochs(parseInt(e.target.value) || 1)}
                    className="number-input"
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Learning Rate</label>
                  <input
                    type="text"
                    value={learningRate}
                    onChange={(e) => setLearningRate(e.target.value)}
                    className="text-input"
                  />
                </div>

                <div className="form-group">
                  <label>Batch Size</label>
                  <select
                    value={batchSize}
                    onChange={(e) => setBatchSize(parseInt(e.target.value))}
                    className="select-input"
                  >
                    <option value={1}>1 (Low VRAM)</option>
                    <option value={2}>2 (Standard)</option>
                    <option value={4}>4 (Fast)</option>
                  </select>
                </div>
              </div>

              {jobType === "dpo" && (
                <div className="form-group">
                  <label>DPO Beta Penalty ({beta})</label>
                  <input
                    type="range"
                    min="0.05"
                    max="0.5"
                    step="0.05"
                    value={beta}
                    onChange={(e) => setBeta(parseFloat(e.target.value))}
                    className="range-input"
                  />
                  <span className="font-xs text-muted">Controls divergence penalty against the reference model</span>
                </div>
              )}

              <div className="form-checkbox">
                <label>
                  <input
                    type="checkbox"
                    checked={useCleaned}
                    onChange={(e) => setUseCleaned(e.target.checked)}
                  />
                  <span>Enforce Strict Schema-Cleaned Dataset (train_cleaned.jsonl)</span>
                </label>
              </div>

              <button className="btn-launch-run" onClick={handleStartTraining}>
                🚀 Start Verifiable Training Run
              </button>
            </div>

            {/* Right Column: Live Telemetry & Jobs List */}
            <div className="telemetry-card">
              <h3>Active & Completed Jobs</h3>

              {jobs.length === 0 ? (
                <div className="empty-jobs">
                  <p>No training jobs executed in this session yet.</p>
                  <span className="font-xs text-muted">Configure and launch a run above to track live telemetry.</span>
                </div>
              ) : (
                <div className="jobs-list">
                  {jobs.map((j) => (
                    <div
                      key={j.job_id}
                      className={`job-card-item ${activeLogJob?.job_id === j.job_id ? "selected" : ""}`}
                      onClick={() => setActiveLogJob(j)}
                    >
                      <div className="job-head">
                        <div className="job-title-group">
                          <span className={`status-pill ${j.status}`}>{j.status.toUpperCase()}</span>
                          <span className="job-id mono font-xs">{j.job_id}</span>
                          <span className="job-type-pill">{j.job_type.toUpperCase()}</span>
                        </div>
                        {j.status === "running" && (
                          <button
                            className="btn-stop font-xs"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStopJob(j.job_id);
                            }}
                          >
                            ⏹️ Stop
                          </button>
                        )}
                      </div>

                      <div className="job-progress-row">
                        <div className="progress-bar-bg">
                          <div className="progress-bar-fill" style={{ width: `${j.progress_pct}%` }} />
                        </div>
                        <span className="pct-label font-xs mono">{j.progress_pct}%</span>
                      </div>

                      <div className="job-meta-row font-xs">
                        <span>
                          Step {j.current_step}/{j.total_steps} (Epoch {j.current_epoch}/{j.total_epochs})
                        </span>
                        <span>Loss: <strong>{j.loss.toFixed(4)}</strong></span>
                        {j.reward_margin !== null && j.reward_margin !== undefined && (
                          <span>Margin: <strong>+{j.reward_margin.toFixed(3)}</strong></span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Console Viewer */}
              {activeLogJob && (
                <div className="console-viewer">
                  <div className="console-header">
                    <span>Terminal Stream: {activeLogJob.job_id}</span>
                    <span className="mono font-xs text-muted">{activeLogJob.preset}</span>
                  </div>
                  <div className="console-body">
                    {activeLogJob.logs.map((line, idx) => (
                      <div key={idx} className="log-line">
                        {line}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: MODEL CHECKPOINTS */}
      {activeTab === "checkpoints" && (
        <div className="checkpoints-view">
          <div className="checkpoints-header">
            <h3>Saved Model Weights & Metadata</h3>
            <p className="card-desc">
              All training checkpoints saved to <code>training/checkpoints/</code>. Ready for inference in
              the autonomous agent core or benchmark runner.
            </p>
          </div>

          <div className="checkpoints-grid">
            {checkpoints.length === 0 ? (
              <div className="p-8 text-center text-muted">No checkpoint models detected yet.</div>
            ) : (
              checkpoints.map((ckpt, idx) => (
                <div key={idx} className="checkpoint-card">
                  <div className="ckpt-head">
                    <span className="ckpt-name mono">{ckpt.checkpoint_name}</span>
                    <span className="ckpt-badge">Trained</span>
                  </div>
                  <div className="ckpt-meta">
                    <div className="meta-item">
                      <span className="label">PRESET:</span>
                      <span className="val mono">{ckpt.preset_name}</span>
                    </div>
                    {ckpt.train_loss && (
                      <div className="meta-item">
                        <span className="label">FINAL LOSS:</span>
                        <span className="val text-emerald">{ckpt.train_loss.toFixed(4)}</span>
                      </div>
                    )}
                    {ckpt.reward_margin && (
                      <div className="meta-item">
                        <span className="label">REWARD MARGIN:</span>
                        <span className="val text-cyan">+{ckpt.reward_margin.toFixed(4)}</span>
                      </div>
                    )}
                    <div className="meta-item">
                      <span className="label">EPOCHS:</span>
                      <span className="val">{ckpt.total_epochs}</span>
                    </div>
                    <div className="meta-item">
                      <span className="label">PATH:</span>
                      <span className="val mono font-xs text-muted">{ckpt.path}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Inspection Drawer */}
      {selectedExample && (
        <div className="inspection-drawer-backdrop" onClick={() => setSelectedExample(null)}>
          <div className="inspection-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <div>
                <h3>Trajectory Details: {selectedExample.id}</h3>
                <span className="text-muted font-xs">{selectedExample.type}</span>
              </div>
              <button className="btn-close" onClick={() => setSelectedExample(null)}>
                ✕
              </button>
            </div>

            <div className="drawer-content">
              <div className="drawer-section">
                <h4>User Goal</h4>
                <div className="goal-box">{selectedExample.user_goal}</div>
              </div>

              {selectedExample.tool_id && (
                <div className="drawer-section">
                  <h4>Tool Call Specification</h4>
                  <div className="drawer-tool-pill">
                    <strong>{selectedExample.tool_id}</strong> (Tier {selectedExample.tier || 1})
                  </div>
                  <pre className="code-box">
                    {JSON.stringify(selectedExample.arguments, null, 2)}
                  </pre>
                </div>
              )}

              {selectedExample.conversation && selectedExample.conversation.length > 0 && (
                <div className="drawer-section">
                  <h4>Full Multi-Turn Conversation ({selectedExample.conversation.length} Turns)</h4>
                  <div className="conversation-thread">
                    {selectedExample.conversation.map((turn, tIdx) => (
                      <div key={tIdx} className={`conv-turn role-${turn.role}`}>
                        <span className="role-label">{turn.role.toUpperCase()}</span>
                        <div className="turn-content">{turn.content}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedExample.chosen_full && (
                <div className="drawer-section">
                  <h4>Chosen Autonomous Plan DAG</h4>
                  <div className="plan-box chosen-bg">{selectedExample.chosen_full}</div>
                </div>
              )}

              {selectedExample.rejected_full && (
                <div className="drawer-section">
                  <h4>Rejected Plan (Flawed Baseline)</h4>
                  <div className="plan-box rejected-bg">{selectedExample.rejected_full}</div>
                </div>
              )}

              <div className="drawer-section curation-actions-box">
                <h4>Set Curation Decision</h4>
                <div className="curation-btn-row">
                  <button
                    className="btn-curate approved"
                    onClick={() => {
                      handleCurate(selectedExample.id, "approved");
                      setSelectedExample(null);
                    }}
                  >
                    ✓ Approve Example
                  </button>
                  <button
                    className="btn-curate flagged"
                    onClick={() => {
                      handleCurate(selectedExample.id, "flagged");
                      setSelectedExample(null);
                    }}
                  >
                    ⚠️ Flag for Review
                  </button>
                  <button
                    className="btn-curate pruned"
                    onClick={() => {
                      handleCurate(selectedExample.id, "pruned");
                      setSelectedExample(null);
                    }}
                  >
                    ✗ Prune from Training
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
