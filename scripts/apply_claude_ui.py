"""
DEPRECATED: This script was a one-time migration utility and has been superseded
by native Next.js React components (ClaudeOutputCard, page.tsx, modern split-views,
and SSE stream handlers). Do not run this script against ui/src/app/page.tsx.
"""
import sys
import re

print("[!] WARNING: scripts/apply_claude_ui.py is deprecated and superseded by native Next.js components.")
# Exit early to protect ui/src/app/page.tsx from accidental regression
if __name__ == "__main__" and "--force" not in sys.argv:
    print("[!] Exiting. Pass --force if you intentionally wish to run this legacy patch script.")
    sys.exit(0)

with open("ui/src/app/page.tsx", "r", encoding="utf-8") as f:
    code = f.read()

# 1. State additions
state_target = 'const [devCustomCmd, setDevCustomCmd] = useState<string>("");'
state_code = '''const [devCustomCmd, setDevCustomCmd] = useState<string>("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});
  const [selectedModel, setSelectedModel] = useState<string>("Kairo 3.7 (Cyber-Ops Sonnet)");
  const [showModelMenu, setShowModelMenu] = useState<boolean>(false);

  const toggleThinking = (id: string) => {
    setExpandedThinking((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const openToolInConsole = (toolId?: string) => {
    if (!toolId) {
      setAdvancedTab("events");
    } else if (toolId.includes("terminal") || toolId.includes("kali") || toolId.includes("shell") || toolId.includes("exec")) {
      setAdvancedTab("terminal");
    } else if (toolId.includes("novnc") || toolId.includes("screen") || toolId.includes("gui") || toolId.includes("desktop")) {
      setAdvancedTab("screen");
    } else if (toolId.includes("planner") || toolId.includes("graph") || toolId.includes("decompose")) {
      setAdvancedTab("graph");
    } else if (toolId.includes("audit") || toolId.includes("evidence") || toolId.includes("cve")) {
      setAdvancedTab("audit");
    } else {
      setAdvancedTab("events");
    }
    setIsAdvancedOpen(true);
  };'''

if state_target in code:
    code = code.replace(state_target, state_code)
    print("[+] State injected")
else:
    print("[!] State target not found or already replaced")

# 2. Top bar, Sidebar, and Messages rendering replacement
# Find from `<div className="app-shell">` to `/* 3. ADVANCED DRAWER */`
shell_start = code.find('<div className="app-shell">')
drawer_marker = code.find('{/* 3. ADVANCED DRAWER */}')

if shell_start != -1 and drawer_marker != -1:
    new_shell_content = '''<div className="app-shell">
      {/* 1. TOP BAR (Claude Minimalist Style) */}
      <header className="top-bar">
        <div className="top-bar-left">
          <button
            className="sidebar-toggle-btn"
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            aria-label="Toggle Sessions Sidebar"
            title={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M9 3v18" />
            </svg>
          </button>
          <button
            className="mobile-hamburger-btn"
            onClick={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
            aria-label="Toggle Sessions Sidebar"
          >
            ☰
          </button>
          <div className="wordmark-container" onClick={handleNewSession}>
            <svg className="wordmark-spark" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
            </svg>
            <span className="wordmark">Kairo</span>
            <span className="wordmark-badge">Claude v3.0</span>
          </div>
        </div>

        {/* Center: Claude Model Selector */}
        <div className="top-bar-center">
          <div className="model-picker-container">
            <button
              className="claude-model-pill"
              onClick={() => setShowModelMenu(!showModelMenu)}
              aria-label="Select Model"
            >
              <span className="model-pill-spark">✦</span>
              <span>{selectedModel}</span>
              <span className="model-pill-chevron">{showModelMenu ? "▲" : "▼"}</span>
            </button>
            {showModelMenu && (
              <div className="model-dropdown-menu">
                <button
                  className={`model-dropdown-item ${selectedModel.includes("Sonnet") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("Kairo 3.7 (Cyber-Ops Sonnet)"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>Kairo 3.7 (Sonnet Tier)</span>
                    <span className="wordmark-badge">Default</span>
                  </div>
                  <span className="model-item-desc">High-capability autonomous planning & Kali VM reasoning</span>
                </button>
                <button
                  className={`model-dropdown-item ${selectedModel.includes("Haiku") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("Kairo 3.5 (Haiku Fast)"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>Kairo 3.5 (Haiku Fast)</span>
                    <span style={{ fontSize: "10px", color: "var(--accent-green)" }}>⚡ Low Latency</span>
                  </div>
                  <span className="model-item-desc">High-speed port discovery & initial banner reconnaissance</span>
                </button>
                <button
                  className={`model-dropdown-item ${selectedModel.includes("Llama") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("Llama-3-70B Pentest SFT"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>Llama-3-70B Pentest SFT</span>
                    <span style={{ fontSize: "10px", color: "var(--accent-blue)" }}>Fine-Tuned</span>
                  </div>
                  <span className="model-item-desc">Local 70B cyber-ops weights with strict grammar constraints</span>
                </button>
                <button
                  className={`model-dropdown-item ${selectedModel.includes("DeepSeek") ? "active" : ""}`}
                  onClick={() => { setSelectedModel("DeepSeek-R1 Reasoner"); setShowModelMenu(false); }}
                >
                  <div className="model-item-title">
                    <span>DeepSeek-R1 Reasoner</span>
                    <span style={{ fontSize: "10px", color: "var(--accent-amber)" }}>Thinking</span>
                  </div>
                  <span className="model-item-desc">Deep chain-of-thought mathematical and exploit analysis</span>
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="top-bar-right">
          {/* Single Status Pill */}
          <div className="status-pill-container">
            <button
              className="status-pill"
              onClick={() => setShowStatusTooltip(!showStatusTooltip)}
              onMouseEnter={() => setShowStatusTooltip(true)}
              onMouseLeave={() => setShowStatusTooltip(false)}
            >
              <span className={`status-dot ${statusInfo.dotClass}`} />
              <span>{statusInfo.text}</span>
            </button>

            {showStatusTooltip && (
              <div key="status-tooltip" className="status-tooltip">
                <div className="status-tooltip-row">
                  <span>Model Engine</span>
                  <strong>{modelCenter?.model_id || selectedModel}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Kali Worker VM</span>
                  <strong>{vmStatus?.worker_online ? "Online" : "Offline"}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Scope Boundary</span>
                  <strong>{scopeInfo.target}</strong>
                </div>
                <div className="status-tooltip-row">
                  <span>Session Hash</span>
                  <strong>{sessionId.slice(0, 12)}</strong>
                </div>
              </div>
            )}
          </div>

          {/* Claude Split Console / Artifacts Button */}
          <button
            className="console-btn"
            onClick={() => setIsAdvancedOpen(true)}
            aria-label="Open Console and Artifacts"
            title="Open Console, Artifacts, and Subsystem Telemetry"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <line x1="15" x2="15" y1="3" y2="21" />
            </svg>
            <span>⚙ Advanced</span>
          </button>
        </div>
      </header>

      {/* 2. MAIN BODY LAYOUT (TWO-COLUMN) */}
      <div className="main-layout">
        {/* Mobile Backdrop */}
        {isMobileSidebarOpen && (
          <div
            key="mobile-backdrop"
            className="mobile-backdrop"
            onClick={() => setIsMobileSidebarOpen(false)}
            aria-label="Close sidebar overlay"
          />
        )}

        {/* Sidebar (Claude-styled 260px) */}
        <aside className={`sidebar ${isSidebarCollapsed ? "collapsed" : ""} ${isMobileSidebarOpen ? "mobile-open" : ""}`}>
          <div className="sidebar-mobile-header">
            <div className="wordmark-container">
              <svg className="wordmark-spark" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
              </svg>
              <span className="wordmark">Kairo</span>
            </div>
            <button
              className="ghost-btn"
              onClick={() => setIsMobileSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              ✕
            </button>
          </div>

          <button className="new-session-btn" onClick={handleNewSession}>
            <div className="new-session-left">
              <span className="new-session-spark">✦</span>
              <span>New session</span>
            </div>
            <span className="new-session-shortcut">Ctrl K</span>
          </button>

          <div className="sidebar-section-label">Recent</div>
          <div className="session-list">
            {sessions.map((s) => (
              <button
                key={s.id}
                className={`session-item ${s.id === sessionId ? "active" : ""}`}
                onClick={() => {
                  setSessionId(s.id);
                  setIsMobileSidebarOpen(false);
                }}
              >
                <span className="session-title">{s.title}</span>
                <span className="session-time">{s.time}</span>
              </button>
            ))}
          </div>

          {/* Bottom Operator Profile Card */}
          <div className="sidebar-profile-card">
            <div className="profile-avatar">OP</div>
            <div className="profile-info">
              <span className="profile-name">Security Operator</span>
              <span className="profile-tier">Airgap · Tier 2 Authorized</span>
            </div>
          </div>
        </aside>

        {/* Central Chat Area */}
        <main className="chat-container">
          <div className="messages-scroll-area">
            <div className="messages-inner">
              {messages.length === 0 ? (
                /* Claude Welcome Screen with 4 Starter Cards */
                <div className="claude-welcome-container">
                  <svg className="claude-welcome-spark" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
                  </svg>
                  <h1 className="claude-welcome-title">What would you like to investigate today?</h1>
                  <p className="claude-welcome-subtitle">
                    Kairo is your autonomous cyber defense cockpit. Select an operational template or describe a security directive in plain language below.
                  </p>

                  <div className="claude-starter-grid">
                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setInputVal("Perform comprehensive reconnaissance and port discovery against 192.168.1.0/24");
                        textareaRef.current?.focus();
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">🔍</span>
                        <span className="claude-starter-title">Reconnaissance &amp; Scan</span>
                      </div>
                      <p className="claude-starter-desc">Map attack surface and identify open ports on target subnet</p>
                    </div>

                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setInputVal("Conduct comprehensive penetration test against 192.168.1.50 with parallel decomposition");
                        textareaRef.current?.focus();
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">⚡</span>
                        <span className="claude-starter-title">Autonomous DAG Plan</span>
                      </div>
                      <p className="claude-starter-desc">Decompose multi-stage penetration test into ordered tasks</p>
                    </div>

                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setAdvancedTab("terminal");
                        setIsAdvancedOpen(true);
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">💻</span>
                        <span className="claude-starter-title">Kali Terminal Session</span>
                      </div>
                      <p className="claude-starter-desc">Launch isolated CLI sandbox environment with live audit</p>
                    </div>

                    <div
                      className="claude-starter-card"
                      onClick={() => {
                        setAdvancedTab("audit");
                        setIsAdvancedOpen(true);
                      }}
                    >
                      <div className="claude-starter-header">
                        <span className="claude-starter-icon">🛡️</span>
                        <span className="claude-starter-title">Audit Findings &amp; CVEs</span>
                      </div>
                      <p className="claude-starter-desc">Inspect verified vulnerability findings and evidence store</p>
                    </div>
                  </div>
                </div>
              ) : (
                messages.map((m) => (
                  <div key={m.id} className={`turn-wrapper ${m.sender}`}>
                    {m.sender === "user" ? (
                      <div className="user-bubble">{m.text}</div>
                    ) : m.sender === "agent" ? (
                      <div className="agent-document">
                        <div className="agent-header">
                          <div className="agent-avatar">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                              <path d="M12 2L14.39 8.26L21 9.27L16.2 13.97L17.33 20.6L12 17.27L6.67 20.6L7.8 13.97L3 9.27L9.61 8.26L12 2Z" />
                            </svg>
                          </div>
                          <span className="agent-name">Kairo</span>
                          <span className="agent-model-badge">Sonnet-Grade</span>
                          <span className="agent-timestamp">{m.timestamp || "Just now"}</span>
                        </div>

                        {/* Claude 3.7 Extended Thinking Accordion */}
                        {(m.toolSelection || m.recovery_path || m.durationMs) && (
                          <div className="claude-thinking-block">
                            <button className="claude-thinking-toggle" onClick={() => toggleThinking(m.id)}>
                              <div className="thinking-left">
                                <span className="thinking-spark">✦</span>
                                <span>Thought for {m.durationMs ? `${(m.durationMs / 1000).toFixed(1)}s` : "1.4s"}</span>
                              </div>
                              <span className="thinking-chevron">{expandedThinking[m.id] ? "▲" : "▼"}</span>
                            </button>
                            {expandedThinking[m.id] && (
                              <div className="claude-thinking-content">
                                <div style={{ marginBottom: "6px" }}>
                                  <strong style={{ color: "var(--text-primary)" }}>Cognitive Evaluation:</strong> Evaluated goal requirements against Scope Contract <code>{scopeInfo.target}</code> and tool safety tier.
                                </div>
                                {m.toolSelection?.selection_reason && (
                                  <div style={{ marginBottom: "6px" }}>
                                    <strong style={{ color: "var(--text-primary)" }}>Tool Selection Rationale:</strong> {m.toolSelection.selection_reason}
                                  </div>
                                )}
                                {m.recovery_narrative && (
                                  <div>
                                    <strong style={{ color: "var(--status-warning)" }}>Self-Healing Recovery:</strong> {m.recovery_narrative}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}

                        {m.text && <div className="agent-body-text">{m.text}</div>}

                        {/* Claude Artifact / Tool Execution Card */}
                        {m.tool && (
                          <div
                            className={`tool-card ${
                              m.execution && m.execution.exit_code !== 0 ? "failed" : ""
                            }`}
                          >
                            <div className="tool-card-header">
                              <div className="tool-card-left">
                                <span className="artifact-pill">Artifact</span>
                                <span className="tool-card-title">
                                  {m.tool.name || m.tool.id}
                                </span>
                                <div className="tool-card-status">
                                  <span
                                    className={`status-dot ${
                                      m.execution?.exit_code === 0 ? "success" : "error"
                                    }`}
                                  />
                                  <span>
                                    {m.execution?.exit_code === 0 ? "Verified" : "Failed"}
                                    {m.durationMs ? ` (${(m.durationMs / 1000).toFixed(1)}s)` : ""}
                                  </span>
                                </div>
                              </div>
                              <div className="tool-card-actions">
                                <button
                                  className="open-console-btn"
                                  onClick={() => openToolInConsole(m.tool?.id)}
                                  title="Inspect in Advanced Console"
                                >
                                  Open in Console ↗
                                </button>
                                <button
                                  className="tool-card-toggle"
                                  onClick={() => toggleCard(m.id)}
                                >
                                  {expandedCards[m.id] ? "▲ Details" : "▼ Details"}
                                </button>
                              </div>
                            </div>

                            {expandedCards[m.id] && (
                              <div className="tool-card-body">
                                {/* 1. Plain Language Summary */}
                                <div>
                                  <div className="tool-section-label">Summary</div>
                                  <div className="tool-summary-text">
                                    {m.execution?.exit_code === 0
                                      ? `Execution succeeded for ${m.tool.id}. Results verified against declared schema.`
                                      : `Execution failed with exit code ${m.execution?.exit_code || 1}.`}
                                  </div>
                                </div>

                                {/* 2. Why This Tool Scoring */}
                                {m.toolSelection?.selected_tool && (
                                  <div>
                                    <div className="tool-section-label">Why This Tool</div>
                                    <div className="scoring-bars-container">
                                      {m.toolSelection.selected_tool.dimension_scores.map((dim) => (
                                        <div key={dim.name} className="score-row">
                                          <div className="score-row-meta">
                                            <span>{dim.name.replace("_", " ")}</span>
                                            <span>{dim.score_pct}%</span>
                                          </div>
                                          <div className="score-bar-track">
                                            <div
                                              className="score-bar-fill"
                                              style={{ width: `${dim.score_pct}%` }}
                                            />
                                          </div>
                                          <span className="score-row-reason">
                                            {dim.raw_signal}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* 3. Command & Output */}
                                <div>
                                  <div className="tool-section-label">Command &amp; Telemetry</div>
                                  <div className="code-block">
                                    {m.execution?.command && (
                                      <div>
                                        $ {m.execution.command} {m.execution.args?.join(" ")}
                                      </div>
                                    )}
                                    {m.execution?.stdout && <div>{m.execution.stdout}</div>}
                                    {m.execution?.stderr && (
                                      <div style={{ color: "var(--status-error)" }}>
                                        {m.execution.stderr}
                                      </div>
                                    )}
                                    {!m.execution?.stdout && !m.execution?.command && (
                                      <div>No stdout recorded.</div>
                                    )}
                                  </div>
                                </div>

                                {/* 4. Recovery Path */}
                                {m.recovery_path && m.recovery_path.length > 0 && (
                                  <div>
                                    <div className="tool-section-label">Recovery Path</div>
                                    <ul className="recovery-list">
                                      {m.recovery_path.map((step, idx) => (
                                        <li key={idx} className="recovery-step">
                                          <strong>{idx + 1}.</strong>
                                          <span>
                                            Tried {step.tool || "tool"} — {step.failure_reason || "failed"}.{" "}
                                            {step.action_taken || ""}
                                          </span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="system-notice">{m.text}</div>
                    )}
                  </div>
                ))
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Claude Floating Composer & Bottom Controls */}
          <footer className="chat-footer">
            <div className="chat-footer-inner">
              {/* Scope & Notice bar */}
              <div className="scope-indicator-bar">
                <button
                  className="scope-pill"
                  onClick={() => setShowScopePopover(!showScopePopover)}
                  title="Click to view Scope Contract details"
                >
                  🔒 Scope: {scopeInfo.target} · {scopeInfo.status}
                </button>

                {modelCenter && modelCenter.server_status !== "running" && (
                  <div className="offline-notice">
                    <span>No model is loaded.</span>
                    <a
                      onClick={() => {
                        setAdvancedTab("system");
                        setIsAdvancedOpen(true);
                      }}
                    >
                      Open Advanced → System to load one
                    </a>
                  </div>
                )}
              </div>

              {/* Scope Contract Popover */}
              {showScopePopover && (
                <div key="scope-popover" className="scope-popover">
                  <div className="scope-popover-title">
                    <span>Scope Contract</span>
                    <button
                      className="ghost-btn"
                      style={{ padding: "0 4px" }}
                      onClick={() => setShowScopePopover(false)}
                    >
                      ✕
                    </button>
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Target:</strong> {scopeInfo.target}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Allowed CIDRs:</strong>{" "}
                    {scopeInfo.cidrAllowed.join(", ")}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Excluded Hosts:</strong>{" "}
                    {scopeInfo.cidrExcluded.join(", ")}
                  </div>
                  <div>
                    <strong style={{ color: "var(--text-primary)" }}>Max Tool Tier:</strong>{" "}
                    {scopeInfo.maxTier}
                  </div>
                </div>
              )}

              {/* Claude Rounded Composer */}
              <div className="composer-row">
                <textarea
                  ref={textareaRef}
                  className="composer-input"
                  rows={1}
                  value={inputVal}
                  onChange={(e) => setInputVal(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    wsStatus === "connected"
                      ? "Reply to Kairo or enter an autonomous cyber security directive…"
                      : "Connecting to Kairo Gateway…"
                  }
                  disabled={wsStatus !== "connected"}
                />
                <div className="composer-actions-bottom">
                  <div className="composer-tools-left">
                    <span
                      className="scope-pill"
                      style={{ cursor: "pointer" }}
                      onClick={() => setShowModelMenu(true)}
                    >
                      ✦ {selectedModel.split(" ")[0]}
                    </span>
                  </div>
                  <button
                    className="send-btn"
                    onClick={handleSend}
                    disabled={!inputVal.trim() || wsStatus !== "connected"}
                    aria-label="Send Directive"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="12" y1="19" x2="12" y2="5" />
                      <polyline points="5 12 12 5 19 12" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </footer>
        </main>
      </div>

      '''
    
    # Replace the middle part
    code = code[:shell_start] + new_shell_content + code[drawer_marker:]
    with open("ui/src/app/page.tsx", "w", encoding="utf-8") as f:
        f.write(code)
    print("[+] Replaced shell and chat area successfully!")
else:
    print(f"[-] Could not find shell markers: {shell_start}, {drawer_marker}")
