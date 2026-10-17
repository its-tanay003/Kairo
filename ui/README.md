# /ui - Kairo Claude Warm Dark Desktop & Web Interface

The `/ui` subsystem is Kairo's executive frontend interface. Built on **Next.js 16**, **React 19**, and packaged for cross-platform desktop execution via **Tauri v2** (Rust), it faithfully implements the **Anthropic Claude Warm Dark** design archetype—pairing quiet editorial aesthetics with high-density cybersecurity observability.

---

## Visual Design System & Aesthetics

- **Anthropic Claude Warm Dark Palette**:
  - Main Background: Deep Warm Slate (`#181816`)
  - Sidebar & Drawer: Warm Obsidian (`#141413`)
  - Elevated Cards & Popovers: Slate Stone (`#222220`)
  - Subtle Borders: Dark Stone (`#2d2c28`)
  - Signature Accent: Terracotta Coral (`#d97757`)
- **Editorial Typography**:
  - Serif Headlines & Monograms: `Newsreader` / `Lora`
  - Body Text & Tooling Labels: `Inter`
  - Code & Event Streams: `JetBrains Mono`
- **Signature UI Elements**:
  - Claude Monogram Spark (8-point terracotta starburst).
  - Floating Pill Composer with integrated HMAC Scope popover.
  - Collapsible Claude 3.7 Extended Thinking Accordion (`✦ Thought for 1.2s ▾`).
  - Interactive Claude Artifact Cards with inline JSON copy and console deep-linking.
  - Smooth Drawer System toggling between Standard (560px) and Wide (880px) modes.

---

## Component Catalog (`ui/src/app/components/`)

| Component | Purpose & Subsystem View |
| :--- | :--- |
| [`LiveSessionView.tsx`](src/app/components/LiveSessionView.tsx) | Primary chat conversation stream, displaying user prompts, thinking accordions, and agent responses. |
| [`AuditExplorer.tsx`](src/app/components/AuditExplorer.tsx) | High-density operational audit log inspector querying the 20-field SQLite event store with search and filters. |
| [`BenchmarkLeaderboard.tsx`](src/app/components/BenchmarkLeaderboard.tsx) | Multi-model evaluation matrix, historical score progression charts, and public verifiable benchmark cards. |
| [`ModelEvolutionPanel.tsx`](src/app/components/ModelEvolutionPanel.tsx) | Real-time telemetry for the autonomous self-improvement loop, active proposals, and checkpoint promotion. |
| [`DatasetCurationPanel.tsx`](src/app/components/DatasetCurationPanel.tsx) | Operator data curation panel for reviewing harvested SFT/DPO examples and schema cleaning reports. |
| [`TaskGraphView.tsx`](src/app/components/TaskGraphView.tsx) | Interactive Directed Acyclic Graph (DAG) visualizer displaying plan decomposition and node execution status. |
| [`TerminalProcessView.tsx`](src/app/components/TerminalProcessView.tsx) | VT100 / Xterm streaming terminal connected to isolated Kali Linux worker processes. |
| [`ScreenPanel.tsx`](src/app/components/ScreenPanel.tsx) | Low-latency RFB / noVNC desktop viewer displaying the virtual Kali Linux desktop for GUI tool automation. |
| [`SecurityBrowserPanel.tsx`](src/app/components/SecurityBrowserPanel.tsx) | Embedded web browser view driven by Playwright (`browser.security.v1`) for web application security auditing. |
| [`ScopeContractChip.tsx`](src/app/components/ScopeContractChip.tsx) | Interactive popover displaying active target CIDRs, HMAC signatures, authorized operator, and expiry countdown. |
| [`WhyThisToolPanel.tsx`](src/app/components/WhyThisToolPanel.tsx) | Explainability inspector breaking down the 7-dimensional scoring weights behind every tool selection decision. |
| [`ClaudeOutputCard.tsx`](src/app/components/ClaudeOutputCard.tsx) | Deliverable container with copy actions, finding metadata, and console deep-linking. |
| [`OfflineIndicator.tsx`](src/app/components/OfflineIndicator.tsx) | Non-intrusive status banner indicating backend connectivity, reconnect countdown, and failover status. |

---

## Desktop Packaging via Tauri (`src-tauri/`)

Kairo packages into a lightweight, native cross-platform desktop application using Tauri v2:
- Native window chrome and menu integration.
- Hardware-accelerated WebKit/WebView2 rendering.
- Rust IPC layer for local execution plane discovery (WSL2 on Windows, native Linux sockets, macOS virtualization).

---

## Running & Developing the UI

### Web Mode (Next.js)
```bash
cd ui
npm install
npm run dev
# Opens on http://localhost:3000
```

### Desktop Mode (Tauri)
```bash
cd ui
npm run tauri dev
```
