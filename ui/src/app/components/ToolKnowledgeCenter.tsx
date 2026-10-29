"use client";

import React, { useState, useEffect, useMemo } from "react";

export interface ToolSummary {
  id: string;
  tool_id: string;
  name: string;
  icon: string;
  category: string;
  description: string;
  version: string;
  detected_version: string;
  binary: string;
  binary_path: string;
  is_installed: boolean;
  health_status: string;
  execution_type: string;
  privilege: string;
  capabilities: string[];
  update_available: boolean;
}

export interface ToolDetails extends ToolSummary {
  author: string;
  license: string;
  official_docs: string;
  last_verified_at: string;
  supported_actions: string[];
  side_effects: string[];
  inputs_schema: Record<string, any>;
  required_arguments: string[];
  optional_arguments: string[];
  natural_language_examples: string[];
  cli_examples: Array<{ title: string; command: string; description: string }>;
  prerequisites: string[];
  parser_type: string;
  output_schema: Record<string, any>;
  latest_version: string;
  update_method: string;
  recent_runs: Array<{
    id: number;
    session_id: string;
    task_id: string;
    timestamp: string;
    actor: string;
    exit_code: number;
    result_summary: string;
  }>;
  total_runs_count: number;
  success_rate_pct: number;
  operational_guidance: {
    noisy_flags?: string[];
    safety_notes?: string;
    timeout_advice?: string;
  };
  related_tools: string[];
  chat_prompt_template: string;
}

interface ToolKnowledgeCenterProps {
  onUseInChat?: (promptText: string) => void;
  apiBaseUrl?: string;
}

export default function ToolKnowledgeCenter({
  onUseInChat,
  apiBaseUrl = "",
}: ToolKnowledgeCenterProps) {
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [activeToolId, setActiveToolId] = useState<string | null>(null);
  const [activeToolDetails, setActiveToolDetails] = useState<ToolDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState<boolean>(false);
  const [activeDrawerTab, setActiveDrawerTab] = useState<"overview" | "args" | "examples" | "guidance" | "history">("overview");
  const [verifyingTool, setVerifyingTool] = useState<boolean>(false);
  const [verificationResult, setVerificationResult] = useState<Record<string, any> | null>(null);
  const [updatingTool, setUpdatingTool] = useState<boolean>(false);
  const [updateNotice, setUpdateNotice] = useState<string | null>(null);
  const [copiedText, setCopiedText] = useState<string | null>(null);

  // Fetch tool catalogue
  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/knowledge/tools`);
      if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to load tool knowledge index`);
      const data = await res.json();
      setTools(data.tools || []);
    } catch (err: any) {
      setError(err.message || "Failed to connect to Tool Knowledge Center");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  // Fetch individual tool 13-section specifications
  const fetchToolDetails = async (toolId: string) => {
    setLoadingDetails(true);
    setVerificationResult(null);
    setUpdateNotice(null);
    try {
      const res = await fetch(`${apiBaseUrl}/knowledge/tools/${encodeURIComponent(toolId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to load tool specification`);
      const data = await res.json();
      setActiveToolDetails(data);
      setActiveToolId(toolId);
    } catch (err: any) {
      alert(`Could not load details for ${toolId}: ${err.message}`);
    } finally {
      setLoadingDetails(false);
    }
  };

  // Run live verification health check
  const handleVerify = async (toolId: string) => {
    setVerifyingTool(true);
    setVerificationResult(null);
    try {
      const res = await fetch(`${apiBaseUrl}/knowledge/tools/${encodeURIComponent(toolId)}/verify`, {
        method: "POST",
      });
      const data = await res.json();
      setVerificationResult(data);
      // Refresh details
      if (activeToolId === toolId) {
        fetchToolDetails(toolId);
      }
    } catch (err: any) {
      setVerificationResult({ success: false, error: err.message });
    } finally {
      setVerifyingTool(false);
    }
  };

  // Copy helper
  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(text);
    setTimeout(() => setCopiedText(null), 2000);
  };

  // Filtered catalogue
  const filteredTools = useMemo(() => {
    return tools.filter((t) => {
      // Category filter
      if (selectedCategory !== "all" && t.category.toLowerCase() !== selectedCategory.toLowerCase()) {
        return false;
      }
      // Status filter
      if (selectedStatus === "installed" && !t.is_installed) return false;
      if (selectedStatus === "missing" && t.is_installed) return false;
      if (selectedStatus === "healthy" && t.health_status !== "healthy") return false;

      // Query filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const mId = t.id.toLowerCase().includes(q) || (t.tool_id && t.tool_id.toLowerCase().includes(q));
        const mName = t.name.toLowerCase().includes(q);
        const mDesc = (t.description || "").toLowerCase().includes(q);
        const mCaps = t.capabilities?.some((c) => c.toLowerCase().includes(q));
        return mId || mName || mDesc || mCaps;
      }
      return true;
    });
  }, [tools, selectedCategory, selectedStatus, searchQuery]);

  const categories = ["all", "recon", "web", "network", "exploitation", "forensics", "passwords"];

  return (
    <div className="flex flex-col h-full bg-[#0d1117] text-[#e6edf3] overflow-hidden select-text">
      {/* Top Header & Search Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 border-b border-[#30363d] bg-[#161b22]">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">📚</span>
            <h1 className="text-lg font-bold text-white tracking-wide">Integrated Tool Knowledge Center</h1>
            <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-[#1f6feb]/20 text-[#58a6ff] border border-[#1f6feb]/40">
              ADR-004 Unified Access
            </span>
          </div>
          <p className="text-xs text-[#8b949e] mt-1">
            Authoritative reference, live verification, operational boundaries, and direct execution templates for all managed Kali Linux tools.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <input
              type="text"
              placeholder="Search tools, capabilities, flags..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 md:w-80 px-3 py-1.5 pl-8 text-xs bg-[#0d1117] border border-[#30363d] rounded-md text-white placeholder-[#8b949e] focus:outline-none focus:border-[#58a6ff]"
            />
            <span className="absolute left-2.5 top-2 text-xs text-[#8b949e]">🔍</span>
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1.5 text-xs text-[#8b949e] hover:text-white"
              >
                ✕
              </button>
            )}
          </div>
          <button
            onClick={fetchTools}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-[#21262d] hover:bg-[#30363d] text-[#c9d1d9] border border-[#30363d] transition-colors"
            title="Refresh tool catalogue"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Filter Chips Bar */}
      <div className="flex items-center justify-between px-5 py-2.5 border-b border-[#21262d] bg-[#161b22]/70 overflow-x-auto gap-4">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-[#8b949e] font-semibold uppercase tracking-wider mr-2">Category:</span>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-2.5 py-1 text-xs rounded-full capitalize font-medium transition-colors ${
                selectedCategory === cat
                  ? "bg-[#238636] text-white"
                  : "bg-[#21262d] text-[#8b949e] hover:text-white hover:bg-[#30363d]"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-[#8b949e]">Status:</span>
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="px-2 py-1 text-xs bg-[#0d1117] border border-[#30363d] rounded text-[#c9d1d9] focus:outline-none focus:border-[#58a6ff]"
          >
            <option value="all">All Statuses ({tools.length})</option>
            <option value="installed">Installed Only</option>
            <option value="healthy">Healthy Only</option>
            <option value="missing">Missing / Unavailable</option>
          </select>
          <span className="text-xs text-[#8b949e] ml-2">
            Showing <strong className="text-white">{filteredTools.length}</strong> of {tools.length} tools
          </span>
        </div>
      </div>

      {/* Main Grid View */}
      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-64 text-[#8b949e]">
            <div className="animate-spin text-2xl mb-2">↻</div>
            <p className="text-sm">Loading authoritative tool registry and verifying binaries...</p>
          </div>
        ) : error ? (
          <div className="p-4 rounded-md bg-[#da3633]/10 border border-[#da3633]/30 text-[#f85149] text-sm">
            <strong>Error connecting to Knowledge Center:</strong> {error}
          </div>
        ) : filteredTools.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-[#8b949e]">
            <span className="text-3xl mb-2">🔍</span>
            <p className="text-sm font-semibold">No tools matching your filters</p>
            <p className="text-xs mt-1">Try clearing your search query or selecting a different category.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredTools.map((t) => {
              const isSelected = activeToolId === t.id || activeToolId === t.tool_id;
              return (
                <div
                  key={t.id || t.tool_id}
                  onClick={() => fetchToolDetails(t.id || t.tool_id)}
                  className={`group relative flex flex-col justify-between p-4 rounded-lg border cursor-pointer transition-all ${
                    isSelected
                      ? "bg-[#1c2128] border-[#58a6ff] ring-1 ring-[#58a6ff]"
                      : "bg-[#161b22] border-[#30363d] hover:border-[#58a6ff]/60 hover:bg-[#1c2128]"
                  }`}
                >
                  <div>
                    {/* Header: Icon, Name, Category */}
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-2xl">{t.icon || "🛠️"}</span>
                        <div>
                          <h3 className="text-sm font-bold text-white group-hover:text-[#58a6ff] transition-colors leading-tight">
                            {t.name}
                          </h3>
                          <span className="text-[11px] font-mono text-[#8b949e]">{t.id}</span>
                        </div>
                      </div>
                      <span className="px-1.5 py-0.5 text-[10px] font-medium uppercase rounded bg-[#21262d] text-[#8b949e] border border-[#30363d]">
                        {t.category}
                      </span>
                    </div>

                    {/* Description */}
                    <p className="text-xs text-[#8b949e] line-clamp-2 mb-3 leading-relaxed">
                      {t.description || "No description available in registry specification."}
                    </p>

                    {/* Capabilities Tags */}
                    <div className="flex flex-wrap gap-1 mb-3">
                      {(t.capabilities || []).slice(0, 3).map((cap, i) => (
                        <span
                          key={i}
                          className="px-1.5 py-0.5 text-[10px] rounded bg-[#1f6feb]/10 text-[#58a6ff] border border-[#1f6feb]/20"
                        >
                          {cap}
                        </span>
                      ))}
                      {(t.capabilities || []).length > 3 && (
                        <span className="px-1.5 py-0.5 text-[10px] rounded bg-[#21262d] text-[#8b949e]">
                          +{(t.capabilities || []).length - 3}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Footer status row */}
                  <div className="flex items-center justify-between pt-2.5 border-t border-[#21262d] text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          t.is_installed ? "bg-[#238636]" : "bg-[#da3633]"
                        }`}
                      />
                      <span className={t.is_installed ? "text-[#3fb950]" : "text-[#f85149]"}>
                        {t.is_installed ? `Installed (v${t.detected_version || t.version})` : "Missing"}
                      </span>
                    </div>

                    <span className="text-[10px] font-medium text-[#58a6ff] group-hover:translate-x-0.5 transition-transform">
                      Specs →
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 13-Section Slide-Over Drawer for Selected Tool */}
      {activeToolId && (
        <div className="fixed inset-y-0 right-0 w-full md:w-[780px] lg:w-[860px] bg-[#161b22] border-l border-[#30363d] shadow-2xl z-[150] flex flex-col animate-in slide-in-from-right duration-200">
          {/* Drawer Header */}
          <div className="flex items-start justify-between p-5 border-b border-[#30363d] bg-[#0d1117]">
            <div className="flex items-start gap-3">
              <span className="text-3xl">{activeToolDetails?.icon || "🛠️"}</span>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-bold text-white">{activeToolDetails?.name || activeToolId}</h2>
                  <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded-full bg-[#1f6feb]/20 text-[#58a6ff] border border-[#1f6feb]/30">
                    {activeToolDetails?.category || "security"}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-[#8b949e] mt-1 font-mono">
                  <span>ID: {activeToolDetails?.tool_id || activeToolId}</span>
                  <span>•</span>
                  <span>Binary: {activeToolDetails?.binary}</span>
                  <span>•</span>
                  <span>{activeToolDetails?.license || "Open Source"}</span>
                </div>
              </div>
            </div>

            <button
              onClick={() => setActiveToolId(null)}
              className="p-1 rounded-md text-[#8b949e] hover:text-white hover:bg-[#21262d] transition-colors"
              title="Close drawer"
            >
              ✕
            </button>
          </div>

          {/* Drawer Quick Actions Bar */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-[#21262d] bg-[#161b22] gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (onUseInChat && activeToolDetails) {
                    onUseInChat(activeToolDetails.chat_prompt_template);
                  }
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-[#238636] hover:bg-[#2ea043] text-white transition-colors shadow-sm"
              >
                <span>💬</span>
                <span>Use in KAIRO Chat</span>
              </button>

              <button
                disabled={verifyingTool}
                onClick={() => handleVerify(activeToolId)}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md bg-[#21262d] hover:bg-[#30363d] text-[#c9d1d9] border border-[#30363d] transition-colors disabled:opacity-50"
              >
                {verifyingTool ? <span>↻ Testing...</span> : <span>🩺 Run Health Check</span>}
              </button>
            </div>

            {activeToolDetails?.official_docs && (
              <a
                href={activeToolDetails.official_docs}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-[#58a6ff] hover:underline flex items-center gap-1"
              >
                <span>Docs ↗</span>
              </a>
            )}
          </div>

          {/* Verification feedback banner if triggered */}
          {verificationResult && (
            <div
              className={`px-5 py-2 text-xs flex items-center justify-between border-b ${
                verificationResult.success
                  ? "bg-[#238636]/15 border-[#238636]/30 text-[#3fb950]"
                  : "bg-[#da3633]/15 border-[#da3633]/30 text-[#f85149]"
              }`}
            >
              <span>
                {verificationResult.success
                  ? `✓ Live Health Check Passed: Binary detected at '${verificationResult.binary_path}' (v${verificationResult.detected_version}) in ${verificationResult.duration_ms}ms.`
                  : `✗ Health Check Issue: ${verificationResult.error || "Binary probe failed."}`}
              </span>
              <button onClick={() => setVerificationResult(null)} className="ml-2 font-bold hover:underline">
                ✕
              </button>
            </div>
          )}

          {/* Drawer Section Tabs */}
          <div className="flex border-b border-[#30363d] bg-[#0d1117] text-xs font-medium px-5">
            {[
              { id: "overview", label: "1. Overview & Identity" },
              { id: "args", label: "4. Arguments & Flags" },
              { id: "examples", label: "5 & 6. Examples" },
              { id: "guidance", label: "7. Guidance & Safety" },
              { id: "history", label: "11. Audit History" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveDrawerTab(tab.id as any)}
                className={`py-2.5 px-3 border-b-2 transition-colors ${
                  activeDrawerTab === tab.id
                    ? "border-[#f78166] text-white font-semibold"
                    : "border-transparent text-[#8b949e] hover:text-[#c9d1d9]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Drawer Scrollable Content Body */}
          <div className="flex-1 overflow-y-auto p-5 space-y-6 text-xs">
            {loadingDetails ? (
              <div className="flex flex-col items-center justify-center h-64 text-[#8b949e]">
                <div className="animate-spin text-2xl mb-2">↻</div>
                <p>Loading full 13-section technical specifications...</p>
              </div>
            ) : activeToolDetails ? (
              <>
                {/* TAB 1: OVERVIEW & IDENTITY */}
                {activeDrawerTab === "overview" && (
                  <div className="space-y-5">
                    {/* Section 1: Overview */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        1. Tool Description & Purpose
                      </h4>
                      <p className="text-xs text-[#c9d1d9] leading-relaxed">
                        {activeToolDetails.description}
                      </p>
                      <div className="grid grid-cols-2 gap-3 mt-4 pt-3 border-t border-[#21262d] text-[11px]">
                        <div>
                          <span className="text-[#8b949e]">Author / Maintainer:</span>
                          <p className="text-white font-medium">{activeToolDetails.author}</p>
                        </div>
                        <div>
                          <span className="text-[#8b949e]">License:</span>
                          <p className="text-white font-medium">{activeToolDetails.license}</p>
                        </div>
                      </div>
                    </div>

                    {/* Section 2: System Status & Verification */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        2. System Status & Binary Details
                      </h4>
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-[#8b949e]">Binary Path:</span>
                          <code className="px-1.5 py-0.5 rounded bg-[#161b22] text-[#58a6ff] font-mono">
                            {activeToolDetails.binary_path || `/usr/bin/${activeToolDetails.binary}`}
                          </code>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[#8b949e]">Detected Version:</span>
                          <span className="font-mono text-white">v{activeToolDetails.detected_version || activeToolDetails.version}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[#8b949e]">Privilege Requirements:</span>
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[#30363d] text-[#e6edf3]">
                            {activeToolDetails.privilege || "standard_user"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[#8b949e]">Execution Mode:</span>
                          <span className="text-white font-medium uppercase">{activeToolDetails.execution_type}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[#8b949e]">Health Status:</span>
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[#238636]/20 text-[#3fb950] border border-[#238636]/40">
                            {activeToolDetails.health_status}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Section 3: Capabilities & Actions */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        3. Capabilities & Supported Actions
                      </h4>
                      <div className="mb-3">
                        <span className="text-[11px] text-[#8b949e] block mb-1.5">Tool Capabilities:</span>
                        <div className="flex flex-wrap gap-1.5">
                          {activeToolDetails.capabilities?.map((c, i) => (
                            <span
                              key={i}
                              className="px-2 py-0.5 rounded text-xs bg-[#1f6feb]/15 text-[#58a6ff] border border-[#1f6feb]/30"
                            >
                              {c}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="text-[11px] text-[#8b949e] block mb-1.5">Supported Actions:</span>
                        <div className="flex flex-wrap gap-1.5">
                          {activeToolDetails.supported_actions?.map((act, i) => (
                            <span
                              key={i}
                              className="px-2 py-0.5 rounded text-xs bg-[#238636]/15 text-[#3fb950] border border-[#238636]/30 font-mono"
                            >
                              {act}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Section 12: Related Tools */}
                    {activeToolDetails.related_tools?.length > 0 && (
                      <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                        <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                          12. Related & Complementary Tools
                        </h4>
                        <div className="flex flex-wrap gap-2">
                          {activeToolDetails.related_tools.map((rId) => (
                            <button
                              key={rId}
                              onClick={() => fetchToolDetails(rId)}
                              className="px-2.5 py-1 text-xs rounded bg-[#161b22] hover:bg-[#21262d] text-[#58a6ff] border border-[#30363d] transition-colors"
                            >
                              🔗 {rId}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* TAB 2: ARGUMENTS & FLAGS SCHEMA */}
                {activeDrawerTab === "args" && (
                  <div className="space-y-4">
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-1">
                        4. Tool Argument Specifications
                      </h4>
                      <p className="text-xs text-[#8b949e] mb-3">
                        Strict JSON schema mapping for KAIRO argument synthesis. All inputs are validated before container or VM execution.
                      </p>

                      {/* Required Arguments */}
                      <div className="mb-4">
                        <span className="text-[11px] font-bold text-[#f85149] uppercase tracking-wider block mb-2">
                          Required Parameters ({activeToolDetails.required_arguments?.length || 0})
                        </span>
                        {activeToolDetails.required_arguments?.length === 0 ? (
                          <span className="text-xs text-[#8b949e] italic">No strictly required parameters.</span>
                        ) : (
                          <div className="space-y-2">
                            {activeToolDetails.required_arguments?.map((reqKey) => {
                              const prop = activeToolDetails.inputs_schema?.properties?.[reqKey] || {};
                              return (
                                <div key={reqKey} className="p-2.5 rounded bg-[#161b22] border border-[#da3633]/30">
                                  <div className="flex items-center justify-between">
                                    <span className="font-mono font-bold text-white">{reqKey}</span>
                                    <span className="text-[10px] text-[#f85149] font-semibold uppercase">Required • {prop.type || "string"}</span>
                                  </div>
                                  {prop.description && (
                                    <p className="text-xs text-[#8b949e] mt-1">{prop.description}</p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      {/* Optional Arguments */}
                      <div>
                        <span className="text-[11px] font-bold text-[#58a6ff] uppercase tracking-wider block mb-2">
                          Optional Parameters ({activeToolDetails.optional_arguments?.length || 0})
                        </span>
                        <div className="space-y-2 max-h-80 overflow-y-auto">
                          {activeToolDetails.optional_arguments?.map((optKey) => {
                            const prop = activeToolDetails.inputs_schema?.properties?.[optKey] || {};
                            return (
                              <div key={optKey} className="p-2.5 rounded bg-[#161b22] border border-[#30363d]">
                                <div className="flex items-center justify-between">
                                  <span className="font-mono text-white">{optKey}</span>
                                  <span className="text-[10px] text-[#8b949e] font-mono">{prop.type || "any"}</span>
                                </div>
                                {prop.description && (
                                  <p className="text-xs text-[#8b949e] mt-1">{prop.description}</p>
                                )}
                                {prop.default !== undefined && (
                                  <span className="text-[10px] text-[#238636] font-mono mt-1 block">
                                    Default: {JSON.stringify(prop.default)}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>

                    {/* Section 8 & 9: Prerequisites & Parser */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        8 & 9. Dependencies, Prerequisites & Parser
                      </h4>
                      <div className="space-y-2">
                        <div>
                          <span className="text-[#8b949e] block mb-1">Prerequisite Evidence Gates:</span>
                          {activeToolDetails.prerequisites?.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {activeToolDetails.prerequisites.map((p, i) => (
                                <span key={i} className="px-2 py-0.5 rounded bg-[#30363d] text-[#c9d1d9] text-[11px]">
                                  {p}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs text-[#8b949e] italic">None (can run on initial discovery phase).</span>
                          )}
                        </div>
                        <div className="pt-2 border-t border-[#21262d] flex items-center justify-between">
                          <span className="text-[#8b949e]">Telemetry Parser:</span>
                          <code className="text-[#58a6ff] font-mono">{activeToolDetails.parser_type}</code>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB 3: EXAMPLES */}
                {activeDrawerTab === "examples" && (
                  <div className="space-y-4">
                    {/* Section 5: Natural Language Prompts */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        5. Natural Language Prompt Examples
                      </h4>
                      <p className="text-xs text-[#8b949e] mb-3">
                        Click any prompt to instantly prefill the KAIRO message composer.
                      </p>
                      <div className="space-y-2">
                        {activeToolDetails.natural_language_examples?.map((prompt, i) => (
                          <div
                            key={i}
                            className="p-3 rounded-lg bg-[#161b22] border border-[#30363d] hover:border-[#58a6ff] transition-colors flex items-start justify-between gap-3 group"
                          >
                            <p className="text-xs text-[#c9d1d9] italic leading-relaxed">
                              &ldquo;{prompt}&rdquo;
                            </p>
                            <button
                              onClick={() => {
                                if (onUseInChat) {
                                  onUseInChat(prompt);
                                }
                              }}
                              className="px-2 py-1 text-[11px] font-semibold rounded bg-[#1f6feb]/20 hover:bg-[#1f6feb] text-[#58a6ff] hover:text-white transition-colors shrink-0"
                            >
                              Insert ↗
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Section 6: CLI Command Equivalents */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        6. Ready-to-Run CLI Examples
                      </h4>
                      <p className="text-xs text-[#8b949e] mb-3">
                        Exact command line invocations used under the hood by KAIRO execution gateway.
                      </p>
                      <div className="space-y-3">
                        {activeToolDetails.cli_examples?.map((cmdEx, i) => (
                          <div key={i} className="p-3 rounded bg-[#161b22] border border-[#30363d]">
                            <div className="flex items-center justify-between mb-1.5">
                              <span className="font-semibold text-white text-xs">{cmdEx.title}</span>
                              <button
                                onClick={() => handleCopy(cmdEx.command)}
                                className="text-[11px] text-[#58a6ff] hover:underline"
                              >
                                {copiedText === cmdEx.command ? "Copied! ✓" : "Copy"}
                              </button>
                            </div>
                            <pre className="p-2 rounded bg-[#0d1117] text-[#58a6ff] font-mono text-[11px] overflow-x-auto border border-[#21262d]">
                              {cmdEx.command}
                            </pre>
                            {cmdEx.description && (
                              <p className="text-[11px] text-[#8b949e] mt-1.5">{cmdEx.description}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB 4: GUIDANCE & SAFETY */}
                {activeDrawerTab === "guidance" && (
                  <div className="space-y-4">
                    {/* Section 7: Operational Guidance */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        7. Operational Guidance & Safety Boundaries
                      </h4>

                      <div className="space-y-3">
                        <div className="p-3 rounded bg-[#f78166]/10 border border-[#f78166]/30 text-[#f78166]">
                          <span className="font-bold block mb-1">⚠️ Safety & Scope Boundary Notes</span>
                          <p className="text-xs text-[#c9d1d9]">
                            {activeToolDetails.operational_guidance?.safety_notes ||
                              "Execution is strictly restricted to targets defined in the active cryptographically-signed Scope Contract."}
                          </p>
                        </div>

                        {Boolean(activeToolDetails.operational_guidance?.noisy_flags?.length) && (
                          <div className="p-3 rounded bg-[#da3633]/10 border border-[#da3633]/30">
                            <span className="font-bold text-[#f85149] block mb-1">
                              🚨 Highly Noisy / Intrusive Options
                            </span>
                            <ul className="list-disc list-inside text-xs text-[#c9d1d9] space-y-1">
                              {(activeToolDetails.operational_guidance?.noisy_flags || []).map((nf, idx) => (
                                <li key={idx} className="font-mono text-[11px] text-[#f85149]">{nf}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        <div className="p-3 rounded bg-[#161b22] border border-[#30363d]">
                          <span className="font-bold text-white block mb-1">⏱️ Timeout Recommendations</span>
                          <p className="text-xs text-[#8b949e]">
                            {activeToolDetails.operational_guidance?.timeout_advice ||
                              "Recommended operational timeout between 30 and 300 seconds depending on target latency."}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Section 10: Maintenance & Updates */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2">
                        10. Maintenance & Package Upgrade
                      </h4>
                      <p className="text-xs text-[#8b949e] mb-2">
                        Upgrades are executed within managed Kali VMs with automated pre-snapshot creation and post-upgrade health checks.
                      </p>
                      <pre className="p-2.5 rounded bg-[#161b22] text-[#238636] font-mono text-[11px] border border-[#21262d]">
                        {activeToolDetails.update_method || `apt-get install --only-upgrade ${activeToolDetails.binary}`}
                      </pre>
                    </div>
                  </div>
                )}

                {/* TAB 5: AUDIT HISTORY */}
                {activeDrawerTab === "history" && (
                  <div className="space-y-4">
                    {/* Section 11: Execution History from DB */}
                    <div className="bg-[#0d1117] p-4 rounded-lg border border-[#30363d]">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                          11. Historical Reliability & Invocations
                        </h4>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-[#8b949e]">Total Runs: <strong>{activeToolDetails.total_runs_count}</strong></span>
                          <span className="px-2 py-0.5 rounded text-xs font-bold bg-[#238636]/20 text-[#3fb950] border border-[#238636]/40">
                            {activeToolDetails.success_rate_pct}% Success
                          </span>
                        </div>
                      </div>

                      {activeToolDetails.recent_runs?.length === 0 ? (
                        <p className="text-xs text-[#8b949e] italic py-4 text-center">
                          No recorded execution events for this tool in the active audit store yet.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {activeToolDetails.recent_runs?.map((run) => (
                            <div
                              key={run.id}
                              className="p-2.5 rounded bg-[#161b22] border border-[#30363d] flex items-center justify-between text-xs"
                            >
                              <div>
                                <div className="flex items-center gap-2">
                                  <span
                                    className={`w-2 h-2 rounded-full ${
                                      run.exit_code === 0 ? "bg-[#238636]" : "bg-[#da3633]"
                                    }`}
                                  />
                                  <span className="font-mono text-white">Task: {run.task_id}</span>
                                </div>
                                <p className="text-[11px] text-[#8b949e] mt-1 line-clamp-1">{run.result_summary}</p>
                              </div>

                              <div className="text-right">
                                <span className="font-mono text-[10px] text-[#8b949e] block">
                                  {new Date(run.timestamp).toLocaleTimeString()}
                                </span>
                                <span className={`text-[10px] font-bold ${run.exit_code === 0 ? "text-[#3fb950]" : "text-[#f85149]"}`}>
                                  Exit {run.exit_code}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
