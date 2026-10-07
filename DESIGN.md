# KAIRO: Frontend UI Design System & Architecture Specification

> **Source of Truth for KAIRO Cyber-Ops Autonomous Platform Interface**  
> **Framework**: Next.js 16 (App Router), React 19, Vanilla CSS Custom Properties  
> **Visual Archetype**: Minimalist, Visual Quiet, ChatGPT-Style (Focus on Chat + Progressive Disclosure)  
> **Release**: v3.0.0 (ChatGPT-Clean Production Edition)

---

## Table of Contents

1. [Executive Summary & Design Philosophy](#1-executive-summary--design-philosophy)
2. [Color System & Design Tokens](#2-color-system--design-tokens)
3. [Typography & Spatial Geometry](#3-typography--spatial-geometry)
4. [Master Page Layout & Cockpit Topology](#4-master-page-layout--cockpit-topology)
5. [Inline Tool Execution Cards & Progressive Disclosure](#5-inline-tool-execution-cards--progressive-disclosure)
6. [The Advanced Drawer (Telemetry & Deep Subsystems)](#6-the-advanced-drawer-telemetry--deep-subsystems)
7. [Visual Interface Walkthrough & Screenshots](#7-visual-interface-walkthrough--screenshots)
   - [7.1 Clean Main Chat Surface](#71-clean-main-chat-surface)
   - [7.2 Plain-Language Status Tooltip](#72-plain-language-status-tooltip)
   - [7.3 Cryptographic Scope Contract Indicator & Popover](#73-cryptographic-scope-contract-indicator--popover)
   - [7.4 Advanced Drawer: System & Hardware Telemetry (Standard 520px)](#74-advanced-drawer-system--hardware-telemetry-standard-520px)
   - [7.5 Advanced Drawer: Wide Console Mode (Expanded 840px)](#75-advanced-drawer-wide-console-mode-expanded-840px)
   - [7.6 Advanced Drawer: SQLite Event Log & Real-Time Search](#76-advanced-drawer-sqlite-event-log--real-time-search)
   - [7.7 Advanced Drawer: Filtered Event Search Results](#77-advanced-drawer-filtered-event-search-results)
   - [7.8 Advanced Drawer: Live Kali Terminal Stream (CLI)](#78-advanced-drawer-live-kali-terminal-stream-cli)
   - [7.9 Advanced Drawer: Kali Desktop Screen Stream (noVNC GUI)](#79-advanced-drawer-kali-desktop-screen-stream-novnc-gui)
   - [7.10 Advanced Drawer: Dev Tools & Interactive Command Runner](#710-advanced-drawer-dev-tools--interactive-command-runner)
   - [7.11 Mobile Viewport: Clean Chat (375px)](#711-mobile-viewport-clean-chat-375px)
   - [7.12 Mobile Viewport: Full-Screen Sidebar Overlay](#712-mobile-viewport-full-screen-sidebar-overlay)
   - [7.13 Mobile Viewport: Full-Screen Advanced Drawer](#713-mobile-viewport-full-screen-advanced-drawer)
8. [Responsive Breakpoint Architecture & Mobile Behavior](#8-responsive-breakpoint-architecture--mobile-behavior)
9. [Accessibility (a11y) & Visual Safety Controls](#9-accessibility-a11y--visual-safety-controls)

---

## 1. Executive Summary & Design Philosophy

The interface of KAIRO is built around one governing principle:

> **The main screen is a chat. Everything else is one click away, never zero clicks away.**

Previous iterations presented an overwhelming cockpit of raw developer test fixtures—6 simultaneous raw status badges, 10 raw debug buttons (`SIGKILL`, `shell.run.v1`, `uname -a`), 11 dense tabs, and internal verification checklists displayed directly on screen.

KAIRO v3.0 replaces all visual clutter with a calm, high-focus conversational interface:

- **One primary surface, one primary action**: The operator opens the app and sees exactly one thing: a chat with a text box.
- **Progressive disclosure**: All advanced subsystems (SQLite event logs, terminal stream, noVNC desktop stream, task DAG planner, benchmark leaderboard, audit explorer, dev test actions) exist in an on-demand **Advanced drawer**, closed by default, opened by a single button (`⚙ Advanced`).
- **No raw debug controls in the main view**: Buttons like `SIGKILL` or `shell.run.v1` are isolated inside `Advanced → Dev tools`.
- **Plain language over cryptic badges**: The top bar displays a single status pill explaining in words what is happening (`● Ready`, `● Running nmap scan…`, `● Connecting…`, `● No model loaded`).
- **Visual quiet**: Neutral dark backgrounds, text in clean gray/white shades, and a single cohesive accent color (`#4f8cff`). No loud gradients, neon borders, or pulsating glows.

---

## 2. Color System & Design Tokens

KAIRO enforces a strict, minimal palette defined in [`ui/src/app/globals.css`](file:///c:/New%20Volume%20(D)/dev/ui/src/app/globals.css):

```css
:root {
  /* Backgrounds */
  --bg-app: #0b0d11;        /* page background */
  --bg-surface: #13161b;    /* sidebar, panels, cards */
  --bg-surface-raised: #1a1e25; /* message bubbles, composer, hover states */
  --bg-input: #15181e;      /* text input field */

  /* Borders */
  --border-subtle: #22262e; /* default dividers */
  --border-focus: #3a3f4a;  /* hover/active borders */

  /* Text */
  --text-primary: #e8e9ec;   /* main text */
  --text-secondary: #9a9fa8; /* labels, timestamps, secondary info */
  --text-muted: #5f636d;     /* placeholder, disabled */

  /* Single accent color */
  --accent: #4f8cff;
  --accent-hover: #6b9fff;

  /* Semantic status colors — ONLY for small 8px dots or small inline text */
  --status-success: #3ecf8e;
  --status-warning: #e8b84b;
  --status-error: #f0636b;

  /* Elevation / shadow */
  --shadow-panel: 0 8px 24px rgba(0, 0, 0, 0.35);
}
```

### Color Rules

1. **Single Accent Color**: `--accent` (`#4f8cff`) is the only color permitted on button backgrounds, active nav items, and primary links.
2. **Semantic Status Colors**: `--status-success`, `--status-warning`, and `--status-error` are restricted to 8px status indicator dots and small inline text. They never fill large cards or badges.
3. **No Gradients or Glows**: All surfaces use flat, curated matte finishes.

---

## 3. Typography & Spatial Geometry

Typography is anchored in **Inter** for clean readability, supplemented by **JetBrains Mono** for technical outputs:

```css
font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

### Typographic Hierarchy

| Role | Font Size | Weight | Line Height | Letter Spacing | Context |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **App Title** | `15px` | `600 (Semi)` | `1.2` | `-0.01em` | Top bar wordmark |
| **Chat Message** | `15px` | `400 (Regular)` | `1.6` | `0.00em` | User bubbles & agent responses |
| **Section Label** | `12px` | `600 (Semi)` | `1.4` | `0.04em` (Uppercase) | Sidebar headers, card section headers |
| **Secondary / Meta** | `12px` | `400 (Regular)` | `1.4` | `0.00em` | Timestamps, tool names, status text |
| **Composer Input** | `15px` | `400 (Regular)` | `1.5` | `0.00em` | Textarea prompt input |
| **Button Text** | `13px` | `500 (Medium)` | `1.2` | `0.00em` | Navigation items, session triggers |
| **Telemetry / Code** | `11px – 12px` | `500 (Medium)` | `1.4` | `0.02em` | CLI commands, hashes, JSON inspection |

### Spacing & Corner Radii

- **Base Grid**: 8px spatial unit (`4px`, `8px`, `12px`, `16px`, `24px`, `32px`, `48px`).
- **Corner Radii**: Consistent `10px` for cards, buttons, composer, and dialogs; `6px` for small chips and pills; `50%` for circular action buttons.

---

## 4. Master Page Layout & Cockpit Topology

The default desktop layout is a **Two-Column Architecture**:

```text
+----------------------------------------------------------------+
|  [☰]  Kairo              [● Ready]              [⚙ Advanced]   |  <- Top Bar (56px)
+--------------+---------------------------------------------------+
|              |                                                   |
|  Sidebar     |                 Chat Area                         |
|  (260px,     |                 (Flexible width)                  |
|  collapsible |                                                   |
|  on mobile)  |                                                   |
|              |          [User & Agent messages, centered,        |
|  + New chat  |           max-width 720px]                        |
|              |                                                   |
|  Recent:     |          [Inline Tool Cards (44px collapsed)]     |
|  - Session 1 |                                                   |
|  - Session 2 |                                                   |
|              |                                                   |
|              +---------------------------------------------------+
|              |  [🔒 Scope: 192.168.1.0/24]                       |
|              |  [Composer: textarea + 36px send button]  (72px)  |
+--------------+---------------------------------------------------+
```

### Components

1. **Top Bar (56px)**:
   - Wordmark: "Kairo" (15px / 600).
   - Single Status Pill: One 8px status dot + plain phrase (`● Ready`, `● Running nmap scan…`, `● Connecting…`, `● No model loaded`). Hover/click reveals a 3-row plain-language tooltip (Model, Kali Worker, Session).
   - Advanced Button: `⚙ Advanced` ghost button opening the slide-in drawer.
2. **Sidebar (260px)**:
   - `+ New session` button: Full-width, `--accent` text, transparent background, 10px radius, 36px height.
   - `RECENT` section label with past session list.
3. **Chat Area**:
   - Centered message stream (`max-width: 720px`) with 24px spacing between turns.
   - User messages: Right-aligned, `--bg-surface-raised` bubble, 10px radius, 12px 16px padding.
   - Agent messages: Left-aligned, transparent background on `--bg-app` (reads like a clean document).
   - Empty State: Muted shield icon + *"Describe a security task in plain language to get started."*
4. **Composer (72px)**:
   - Single-line auto-growing textarea (`--bg-input`, 10px radius).
   - Send Button: 36×36px circle, `--accent` background, white icon.
5. **Scope Indicator Pill**:
   - Persistent small pill bottom-left of chat: `🔒 Scope: <target> · <status>`.
   - Clicking opens the Scope Contract details popover (allowed CIDRs, excluded hosts, tool tiers).

---

## 5. Inline Tool Execution Cards & Progressive Disclosure

Tool execution results appear **directly inline within the chat stream**, replacing the permanent side-pane inspector:

```text
+--------------------------------------------------+
| 🔧 nmap.scan.v1          ● success   [▼ Details]  |   <- 44px collapsed row
+--------------------------------------------------+
```

### Expansion Hierarchy

When the operator clicks `▼ Details`:

1. **Plain-Language Summary**: One clear sentence describing the outcome.
2. **Why This Tool**: Explainable multi-factor scoring displayed as horizontal percentage bars with plain rationale.
3. **Command & Telemetry**: Collapsed monospace block containing executed CLI command, arguments, and stdout/stderr.
4. **Recovery Path**: Rendered only when error recovery occurred, showing step-by-step mitigation actions taken.
5. **Evidence**: Artifact references and screenshot chips.

> **Auto-Expansion Rule**: Tool cards remain collapsed by default. They auto-expand ONLY when an execution error or failure occurs.

---

## 6. The Advanced Drawer (Telemetry & Deep Subsystems)

Triggered by the `⚙ Advanced` button, the Advanced drawer is an engineer-grade slide-in developer console with two flexible viewing modes:
- **Standard Console (`520px`)**: Default compact drawer overlay for checking quick metrics, events, and running tests.
- **Wide Console (`840px`)**: Expanded desktop view toggled via the `⛶ Expand` header action, providing optimal widescreen layout for `TerminalProcessView`, `TaskGraphView` (DAG), and `ScreenPanel` (noVNC).

```text
+--------------------------------------------------------------------------------+
| Advanced                                            [⛶ Expand]  [✕ Close (Esc)] |
| System telemetry, audit trail & subsystems                                     |
+-------------------+------------------------------------------------------------+
| CORE              |  System & Hardware Telemetry                               |
| - System          |  [↻ Refresh Telemetry]   [📋 Copy Session ID]              |
| - Event Log       |                                                            |
|                   |  - Active Model: Qwen3-Coder-30B                           |
| OPERATIONS        |  - Model Server: ● running                                 |
| - Terminal [CLI]  |  - GPU VRAM: [||||||....] 749MB / 8151MB (9%)              |
| - Screen [GUI]    |  - Kali VM Worker: ○ Offline (poweroff)                    |
| - Task Graph [DAG]|  - Gateway WebSocket: ● connected                          |
|                   |                                                            |
| SECURITY          |  SQLite Operational Event Log                              |
| - Audit           |  [🔍 Search events by tool, actor, or arguments...]        |
| - Benchmarks      |  [All (14)]  [Success (12)]  [Failures (2)]                |
|                   |                                                            |
| TESTING           |  Interactive Sandbox Command Runner                        |
| - Dev tools [⚠️]  |  [ bash command: uname -a                   ] [▶ Execute]  |
+-------------------+------------------------------------------------------------+
```

### Categorized Navigation Rail

1. **CORE**:
   - **System**: Live telemetry, hardware VRAM utilization gauge, active runtime engine, and quick-action pills (`↻ Refresh Telemetry`, `📋 Copy Session ID` with transient copied feedback).
   - **Event Log**: Real-time SQLite operational log with instant text search, status filtering chips (`All`, `Success`, `Failures`), and expandable event cards with arguments/results.
2. **OPERATIONS**:
   - **Terminal (`CLI`)**: Interactive xterm.js process stream connecting directly to the Kali worker shell.
   - **Screen (`GUI`)**: Live RFB/noVNC desktop stream for graphical tools (Burp Suite, Wireshark, Ghidra).
   - **Task Graph (`DAG`)**: Real-time Directed Acyclic Graph visualizer for multi-stage autonomous missions.
3. **SECURITY**:
   - **Audit**: Cryptographic Scope Contract ledger and compliance checkpoint verification.
   - **Benchmarks**: Cybersecurity evaluation benchmarks (AgentBench, CyberGym) and dataset curation.
4. **TESTING**:
   - **Dev tools (`⚠️`)**: Interactive Sandbox Command Runner with custom bash input, pre-configured validation suites (`kali.exec.v1: uname -a`, `shell.run.v1: date`), timeout test triggers, and emergency `SIGKILL`.

---

## 7. Visual Interface Walkthrough & Screenshots

All screenshots below are captured directly from the running production environment:

### 7.1 Clean Main Chat Surface

The primary viewport on initial launch. Zero debug controls, zero cluttered badges, pristine ChatGPT-style focus.

![01_chatgpt_clean_main.png](/docs/assets/screenshots/01_chatgpt_clean_main.png)

### 7.2 Plain-Language Status Tooltip

Clicking or hovering over the single header status pill reveals concise plain-language system facts without opening any complex panels.

![01b_status_tooltip.png](/docs/assets/screenshots/01b_status_tooltip.png)

### 7.3 Cryptographic Scope Contract Indicator & Popover

The sole persistent trust control outside Advanced. Clicking the pill displays authorized network boundaries, excluded hosts, and permitted execution tiers.

![01c_scope_contract_popover.png](/docs/assets/screenshots/01c_scope_contract_popover.png)

### 7.4 Advanced Drawer: System & Hardware Telemetry (Standard 520px)

Slide-in drawer with quick-action pills, structured hardware rows, and real-time GPU VRAM utilization gauge.

![advanced_system_520px.png](/docs/assets/screenshots/advanced_system_520px.png)

### 7.5 Advanced Drawer: Wide Console Mode (Expanded 840px)

Toggled with the `⛶ Expand` button to maximize horizontal canvas width for complex terminal sessions and deep telemetry.

![advanced_system_wide_840px.png](/docs/assets/screenshots/advanced_system_wide_840px.png)

### 7.6 Advanced Drawer: SQLite Event Log & Real-Time Search

Searchable operational audit log featuring status filtering chips (`All`, `Success`, `Failures`) and live text query filtering.

![advanced_events_tab.png](/docs/assets/screenshots/advanced_events_tab.png)

### 7.7 Advanced Drawer: Filtered Event Search Results

Interactive filtering narrowing events instantly by tool name, parameters, or execution status.

![advanced_events_searched.png](/docs/assets/screenshots/advanced_events_searched.png)

### 7.8 Advanced Drawer: Live Kali Terminal Stream (CLI)

Interactive terminal process view with command execution stream.

![advanced_terminal_tab.png](/docs/assets/screenshots/advanced_terminal_tab.png)

### 7.9 Advanced Drawer: Kali Desktop Screen Stream (noVNC GUI)

Live RFB/noVNC desktop display stream for interactive graphical penetration testing tools.

![advanced_screen_tab.png](/docs/assets/screenshots/advanced_screen_tab.png)

### 7.10 Advanced Drawer: Dev Tools & Interactive Command Runner

Interactive sandbox command runner with custom bash execution, test fixtures, and emergency SIGKILL control.

![advanced_devtools_tab.png](/docs/assets/screenshots/advanced_devtools_tab.png)

### 7.11 Mobile Viewport: Clean Chat (375px)

On mobile screens (e.g., iPhone 375×812), the layout gracefully scales with zero horizontal overflow and full touch ergonomics.

![10_mobile_chat_375px.png](/docs/assets/screenshots/10_mobile_chat_375px.png)

### 7.12 Mobile Viewport: Full-Screen Sidebar Overlay

Triggered via the hamburger button, the sidebar presents a dedicated full-screen drawer with a dismiss button.

![11_mobile_sidebar_375px.png](/docs/assets/screenshots/11_mobile_sidebar_375px.png)

### 7.13 Mobile Viewport: Full-Screen Advanced Drawer

The Advanced drawer adapts into a full-screen view with horizontally scrollable tab navigation and touch-optimized controls.

![12_mobile_advanced_375px.png](/docs/assets/screenshots/12_mobile_advanced_375px.png)

---

## 8. Responsive Breakpoint Architecture & Mobile Behavior

| Breakpoint | Target Category | Layout Behavior |
| :--- | :--- | :--- |
| **`>= 769px`** | Desktop & Laptop | Two-Column layout (260px fixed sidebar + centered 720px chat area) + 480px slide-in Advanced drawer |
| **`< 768px`** | Mobile Devices (375px – 767px) | Single-column chat, hamburger-triggered full-screen sidebar overlay, full-screen Advanced drawer with horizontal tab rail |

### Mobile Rules

1. **Full-Screen Overlays**: The sidebar and Advanced drawer expand to `100vw` / `100vh`, preventing narrow cramped side-drawers on phones.
2. **Touch-Safe Targets**: All interactive elements maintain a minimum hit target of `36px` to `44px`.
3. **No Horizontal Overflow**: All flex containers wrap cleanly; the composer and scope pills fit comfortably within a 375px viewport.

---

## 9. Accessibility (a11y) & Visual Safety Controls

1. **Textual State Pairing**: All status dots are accompanied by plain-language text (`Ready`, `Running`, `Connecting`, `Disconnected`) ensuring accessibility for color-blind operators.
2. **Contrast Standards**: Body text (`#e8e9ec`) against background (`#0b0d11`) achieves a contrast ratio of **14.8:1**, comfortably exceeding WCAG 2.2 AAA criteria.
3. **Keyboard Shortcuts**: `Enter` dispatches messages, `Shift+Enter` inserts newlines, and `Escape` dismisses the Advanced drawer or popovers.
4. **Isolated Test Execution**: Dangerous operations (`SIGKILL`, command execution) are safely quarantined behind the Advanced drawer under a dedicated warning notice.

---

*Authored by Antigravity Design Systems Team & KAIRO Core Engineering.*
