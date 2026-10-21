# KAIRO: Frontend UI Design System & Architecture Specification

> **Source of Truth for KAIRO Cyber-Ops Autonomous Platform Interface**  
> **Framework**: Next.js 16 (App Router), React 19, Vanilla CSS Custom Properties  
> **Visual Archetype**: Anthropic Claude UI Design Language (Warm Slate, Literary Serif, Terracotta Coral, Progressive Artifacts)  
> **Release**: v4.0.0 (Claude-Clean Production Edition)

---

## Table of Contents

1. [Executive Summary & Claude Design Philosophy](#1-executive-summary--claude-design-philosophy)
2. [Anthropic Claude Color System & Design Tokens](#2-anthropic-claude-color-system--design-tokens)
3. [Typography & Editorial Aesthetics](#3-typography--editorial-aesthetics)
4. [Master Layout Topology & Two-Column Architecture](#4-master-layout-topology--two-column-architecture)
5. [Top Navigation Bar & Model Selector](#5-top-navigation-bar--model-selector)
6. [Collapsible Sidebar & Session History](#6-collapsible-sidebar--session-history)
7. [Claude Welcome Surface & Interactive Starter Cards](#7-claude-welcome-surface--interactive-starter-cards)
8. [Chat Stream: Extended Thinking & Claude Artifacts](#8-chat-stream-extended-thinking--claude-artifacts)
9. [The Claude Floating Composer](#9-the-claude-floating-composer)
10. [Right Split Console & Artifacts Drawer](#10-right-split-console--artifacts-drawer)
11. [Visual Interface Architecture & Screen Wireframe Specifications](#11-visual-interface-architecture--screen-wireframe-specifications)
    - [11.1 Claude Welcome Surface](#111-claude-welcome-surface)
    - [11.2 Claude Model Selector Dropdown](#112-claude-model-selector-dropdown)
    - [11.3 Cryptographic Scope Contract Popover](#113-cryptographic-scope-contract-popover)
    - [11.4 Active Conversation: Thinking & Artifacts](#114-active-conversation-thinking--artifacts)
    - [11.5 Console Drawer: System & Hardware Telemetry](#115-console-drawer-system--hardware-telemetry)
    - [11.6 Console Drawer: Live Kali Terminal Stream](#116-console-drawer-live-kali-terminal-stream)
    - [11.7 Console Drawer: Kali Desktop Screen Stream (noVNC)](#117-console-drawer-kali-desktop-screen-stream-novnc)
    - [11.8 Console Drawer: Task Graph DAG Planner](#118-console-drawer-task-graph-dag-planner)
    - [11.9 Console Drawer: Audit Findings & Evidence Explorer](#119-console-drawer-audit-findings--evidence-explorer)
    - [11.10 Console Drawer: Benchmark Leaderboard](#1110-console-drawer-benchmark-leaderboard)
    - [11.11 Mobile Responsive Viewport (375px)](#1111-mobile-responsive-viewport-375px)
12. [Responsive Breakpoint Architecture & Mobile Behavior](#12-responsive-breakpoint-architecture--mobile-behavior)
13. [Accessibility (WCAG 2.2 AA) & Visual Safety](#13-accessibility-wcag-22-aa--visual-safety)

---

## 1. Executive Summary & Claude Design Philosophy

KAIRO v4.0 is engineered around the distinctive visual ethos of **Anthropic's Claude**:

> **A thoughtful, calm, literary, and hyper-premium conversational cockpit that balances profound intellectual quiet with deep technical capability.**

Unlike cold, sterile, or neon-drenched developer tools, the Claude design language prioritizes:

- **Warm Slate & Obsidian Tones**: Warm dark charcoal surfaces (`#181816`, `#141413`) with delicate stone borders (`#2d2c28`) rather than stark black or harsh navy blues.
- **Anthropic Terracotta Coral Accent (`#d97757`)**: Used purposefully for primary focal points—the signature starburst spark, send action, model pills, active tabs, and highlights.
- **Editorial Literary Typography**: Modern sans-serif (`Inter`) for crisp UI utility paired with warm classical serif (`Newsreader` / `Lora`) for headlines, welcome greetings, and wordmarks.
- **Progressive Disclosure via Claude Artifacts**: Complex executions (Kali CLI commands, DAG plans, noVNC desktop frames, SQLite event logs) are rendered as sleek **Claude Artifacts** with direct "Open in Console ↗" actions that slide out the right split panel seamlessly.
- **Claude 3.7 Extended Thinking Accordion**: The agent's cognitive evaluation, tool safety screening, and self-healing recovery paths are presented in an elegant, collapsible reasoning block (`✦ Thought for 1.4s ▾`).

---

## 2. Anthropic Claude Color System & Design Tokens

Defined in [`ui/src/app/globals.css`](file:///c:/New%20Volume%20(D)/dev/ui/src/app/globals.css):

```css
:root {
  /* Anthropic Claude Warm Dark Palette */
  --bg-app: #181816;             /* Claude dark canvas background */
  --bg-surface: #141413;         /* Claude dark sidebar and panels */
  --bg-surface-raised: #21211e;  /* Claude cards, modals, popovers */
  --bg-surface-hover: #292825;   /* Hover state */
  --bg-input: #21201d;           /* Claude floating input background */
  --bg-input-focus: #252421;     /* Composer active state */

  /* Borders: warm stone tones */
  --border-subtle: #2d2c28;      /* Delicate stone dividers */
  --border-focus: #424039;       /* Hover/active borders */
  --border-accent: rgba(217, 119, 87, 0.4);

  /* Text: Claude Warm Ivory & Stone */
  --text-primary: #faf9f5;       /* Claude warm ivory main text */
  --text-secondary: #b0aea5;     /* Claude warm mid-stone secondary text */
  --text-muted: #757470;         /* Subtle labels & placeholders */

  /* Anthropic Claude Signature Terracotta Accent */
  --accent: #d97757;             /* Iconic Claude terracotta / coral */
  --accent-hover: #e58667;       /* Warm hover */
  --accent-active: #c66749;      /* Warm active */
  --accent-subtle: rgba(217, 119, 87, 0.12);
  --accent-tint: rgba(217, 119, 87, 0.08);

  /* Anthropic Secondary Accents */
  --accent-blue: #6a9bcc;        /* Anthropic blue accent */
  --accent-green: #788c5d;       /* Anthropic sage green accent */
  --accent-amber: #e8b84b;       /* Anthropic warm gold accent */

  /* Semantic status colors (gentle, never neon) */
  --status-success: #788c5d;     /* Claude sage green */
  --status-warning: #e8b84b;     /* Warm amber */
  --status-error: #d95757;       /* Warm coral red */

  /* Elevation / Shadow */
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.2);
  --shadow-panel: 0 12px 32px rgba(0, 0, 0, 0.5);
  --shadow-composer: 0 8px 30px rgba(0, 0, 0, 0.35);
}
```

---

## 3. Typography & Editorial Aesthetics

| Role | Font Family | Size | Weight | Line Height | Context |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Welcome Heading** | `'Newsreader', Georgia, serif` | `29px` | `400 (Regular)` | `1.25` | Claude welcome headline |
| **Wordmark Title** | `'Newsreader', Georgia, serif` | `19px` | `500 (Medium)` | `1.2` | Top bar brand anchor |
| **Chat Body** | `'Inter', system-ui, sans-serif` | `15px` | `400 (Regular)` | `1.65` | Operator & Agent discourse |
| **Artifact Headings** | `'Inter', system-ui, sans-serif` | `13px` | `600 (Semi)` | `1.3` | Tool card titles & drawer tabs |
| **Thinking Accordion**| `'Inter', system-ui, sans-serif` | `12px` | `500 (Medium)` | `1.5` | Extended cognitive reasoning |
| **CLI / Code / Hashes**| `'JetBrains Mono', monospace` | `12px` | `500 (Medium)` | `1.45` | Shell commands & output blocks |

---

## 4. Master Layout Topology & Two-Column Architecture

```text
+-----------------------------------------------------------------------------------+
| [ | ] ✦ Kairo   [ ✦ Kairo Scale 2B (Custom Primary) ▾ ]       [● Ready]   [ [ | ] ⚙ Advanced ] | <- Top Bar (52px)
+-----------------+-----------------------------------------------------------------+
|                 |                                                                 |
|  Claude Sidebar |                   Central Chat Surface                          |
|  (260px,        |                   (Max-width 760px)                             |
|  collapsible    |                                                                 |
|  via Ctrl+B     |     ✦ What would you like to investigate today?                 |
|  or toggle)     |                                                                 |
|                 |     [Recon Scan]      [DAG Plan]                                |
|  + New session  |     [Kali Sandbox]    [Audit Findings]                          |
|                 |                                                                 |
|  Recents:       |     Operator: Scan network 192.168.1.0/24                       |
|  • Audit #1     |     Kairo: ✦ Thought for 1.4s ▾                                 |
|  • RedTeam #2   |     [ ARTIFACT: nmap.scan.v1  Verified  [Open in Console ↗] ]   |
|                 |                                                                 |
|  [OP] Operator  |     [ 🔒 Scope: 192.168.1.0/24 | [Textarea...] | ( ↑ ) ]        | <- Floating Composer
+-----------------+-----------------------------------------------------------------+
```

---

## 5. Top Navigation Bar & Model Selector

The header sits at a restrained **52px height** in `--bg-surface` (`#141413`):
- **Left**: Sidebar collapse toggle icon, Anthropic starburst monogram in terracotta (`#d97757`), and wordmark `Kairo` with `Claude v3.0` badge.
- **Center**: **Claude Model Selector Pill** (`✦ Kairo Scale 2B (Custom Primary) ▾`). Clicking reveals a warm dropdown menu with:
  1. `Kairo Scale 2B (Custom Primary)` (Default): Full autonomous reasoning & Kali sandbox planning with local GRPO weights.
  2. `Qwen2.5-0.5B (Local Fallback)`: High-speed local GGUF quantized model for triage and low-latency recon.
  3. `Kairo GRPO Final (Reasoner)`: Local fine-tuned RL reasoning checkpoint with verified rule-based rewards.
  4. `Qwen3-Coder-30B (MoE Base)`: Local MoE fallback target for extended cybersecurity coding tasks.
- **Right**: Clean plain-language status pill (`● Ready`) with hover telemetry tooltip, plus the **Advanced Console** button (`[ | ] ⚙ Advanced`).

---

## 6. Collapsible Sidebar & Session History

- **Smooth Collapse**: Toggleable via the top bar icon button. Collapses smoothly with `transition: width 0.2s cubic-bezier(0.16, 1, 0.3, 1)`.
- **New Session Button**: Elegant full-width container with starburst icon, `+ New session` title, and keyboard shortcut pill (`Ctrl K`).
- **Session List**: Grouped with warm hover highlights and terracotta left indicators on active items.
- **Operator Card**: Fixed at the bottom of the sidebar, displaying the Operator's avatar (`OP`), role, and authorization tier (`Airgap · Tier 2 Authorized`).

---

## 7. Claude Welcome Surface & Interactive Starter Cards

When `messages.length === 0`, KAIRO displays the signature Anthropic Claude welcoming screen:
- A prominent terracotta starburst spark icon.
- Editorial headline: *"What would you like to investigate today?"*
- Subtitle: *"Kairo is your autonomous cyber defense cockpit. Select an operational template or describe a security directive in plain language below."*
- **4 Interactive Starter Cards**:
  1. 🔍 **Reconnaissance & Scan**: Maps attack surface and port discovery on scope.
  2. ⚡ **Autonomous DAG Plan**: Decomposes a goal into ordered parallel tasks.
  3. 💻 **Kali Terminal Session**: Directly opens the drawer to the live CLI sandbox.
  4. 🛡️ **Audit Findings & CVEs**: Inspects evidence records and cryptographic hashes.

---

## 8. Chat Stream: Extended Thinking & Claude Artifacts

### 8.1 User Message Bubbles
Rendered on the right with a warm slate background (`#282724`), subtle stone border (`#383632`), rounded corners (`18px 18px 4px 18px`), and warm ivory text (`#faf9f5`).

### 8.2 Agent Header & Persona
Each response starts with the terracotta starburst avatar, the name **Kairo**, the `Local-Primary` badge, and timestamp.

### 8.3 Claude 3.7 Extended Thinking Accordion
Reasoning, tool scoring, and recovery evaluations are encapsulated inside an expandable pill:
- Header: `✦ Thought for 1.4s ▾` in terracotta.
- Body: Contains cognitive evaluations, candidate tool score comparisons, and self-healing narratives.

### 8.4 Claude Artifacts Tool Card
Every tool invocation (`nmap.scan.v1`, `kali.exec.v1`, `planner_decompose`) is treated as a first-class **Claude Artifact**:
- Top header: `ARTIFACT` pill in terracotta, tool name, verification badge (`● Verified` or `● Failed`), execution duration.
- **Deep-Link Action**: An `Open in Console ↗` button that immediately opens the right split panel to the matching tab (Terminal, Screen, Task Graph, or Audit).
- Details toggle: Expands to show plain-language summaries, parameter breakdowns, and syntax-highlighted code output blocks (`#151514`).

---

## 9. The Claude Floating Composer

Positioned in the lower center with a maximum width of `760px`:
- Floating curved container with `border-radius: 20px`, surface `#21201d`, delicate border `#2d2c28`, and warm box-shadow `0 8px 30px rgba(0, 0, 0, 0.35)`.
- Auto-expanding textarea (`min-height: 38px`, `max-height: 180px`).
- Bottom row:
  - Left tools: Scope Contract indicator pill (`🔒 Scope: 192.168.1.0/24 · Active`), Model selector shortcut (`✦ Kairo`).
  - Right: **Claude Circular Terracotta Send Button** (`34px` round, background `#d97757`, smooth hover scale, white upward arrow SVG).

---

## 10. Right Split Console & Artifacts Drawer

Slide-out drawer functioning like Claude's Artifacts side-by-side pane:
- Standard mode: `560px` width; Expanded wide console: `880px` width.
- Left navigation rail with categorized tabs:
  - **Core**: `System` (Hardware/GPU telemetry), `Event Log` (SQLite audit store).
  - **Operations**: `Terminal` (CLI Kali stream), `Screen (VNC)` (RFB Desktop GUI), `Task Graph` (DAG planner visualizer).
  - **Security**: `Audit` (Evidence artifacts), `Benchmarks` (Model leaderboards).
  - **Testing**: `Dev tools` (Interactive sandbox commands).

---

## 11. Visual Interface Architecture & Screen Wireframe Specifications

The Kairo interface implements an executive visual hierarchy modeled after the Anthropic Claude Warm Dark design system. The following structural wireframes document the layout, state machines, and component hierarchy across all primary views.

### 11.1 Claude Welcome Surface

```text
+-----------------------------------------------------------------------------------+
| [Sidebar] Kairo [Claude v3.0]      [✦ Kairo Scale 2B (Custom) ▼]   [● Ready] [⚙]  |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|                                       ✦                                           |
|                              Welcome to Kairo                                     |
|                 Autonomous Cyber Security Operations Agent                        |
|                                                                                   |
|    +------------------------------------+  +------------------------------------+ |
|    | Full Scope Subdomain Discovery    |  | Web Vulnerability & CVE Audit      | |
|    | Enumerate subdomains and DNS       |  | Run Nikto/ZAP across web endpoints  | |
|    | Target: 192.168.1.0/24             |  | Target: http://127.0.0.1:8080      | |
|    +------------------------------------+  +------------------------------------+ |
|    | Network Port & Service Scan        |  | Threat Model & Attack Graph Plan   | |
|    | Fast SYN stealth port discovery    |  | Decompose objective into task DAG  | |
|    | Target: 10.0.0.0/8                 |  | Target: Autonomous Plan Only       | |
|    +------------------------------------+  +------------------------------------+ |
|                                                                                   |
|               [ 🔒 Scope: 192.168.1.0/24 · Active (HMAC Valid) ]                  |
|   +---------------------------------------------------------------------------+   |
|   | Enter cyber security directive or prompt...                 [✦ Model] [▲] |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
```

### 11.2 Claude Model Selector Dropdown

```text
+-----------------------------------------------------------------------------------+
| Top Navigation Center: [✦ Kairo Scale 2B (Custom Primary) [Backend: Ready] ▲]     |
| +-------------------------------------------------------------------------------+ |
| | ✦ Kairo Scale 2B (Custom Primary)    [Primary Custom]                         | |
| |   Locally-trained 2B causal architecture with GRPO schema alignment           | |
| |-------------------------------------------------------------------------------| |
| | ⚡ Qwen2.5-0.5B (Local Fallback)       [Local Fallback]                         | |
| |   Lightweight quantized GGUF local model for fast offline triage              | |
| |-------------------------------------------------------------------------------| |
| | ✦ Kairo GRPO Final (Reasoner)         [RL Aligned]                            | |
| |   Checkpoint reinforced with schema validation and verifier rewards           | |
| |-------------------------------------------------------------------------------| |
| | ✦ Qwen3-Coder-30B (MoE Base)          [Advanced]                              | |
| |   Large local Mixture-of-Experts coder model for exploit generation           | |
| +-------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+
```

### 11.3 Cryptographic Scope Contract Popover

```text
+-----------------------------------------------------------------------------------+
| Floating Pill: [ 🔒 Scope: 192.168.1.0/24 · Active ]                             |
| +-------------------------------------------------------------------------------+ |
| | Scope Contract (scope_c89f)                                               [✕] | |
| | Status: [HMAC-SHA256 Valid] (58m left)                                        | |
| | Primary Target: 192.168.1.0/24                                                | |
| | Allowed CIDRs: 192.168.1.0/24, 10.0.0.0/8                                     | |
| | Excluded Hosts: 192.168.1.1, 10.0.0.1                                         | |
| | Max Tool Tier: Tier 2 (Active CLI)                                            | |
| +-------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+
```

### 11.4 Active Conversation: Thinking & Artifacts

```text
+-----------------------------------------------------------------------------------+
| [User]: Run an nmap service scan against 192.168.1.50 and report findings         |
|                                                                                   |
| [Agent]:                                                                          |
|   +-----------------------------------------------------------------------------+ |
|   | ✦ Thought for 1.8s                                                        ▾ | |
|   |   Analyzing target 192.168.1.50 against active Scope Contract...            | |
|   |   Selecting tool: nmap.scan.v1 (confidence: 0.96, smoothed prior: 0.94)    | |
|   +-----------------------------------------------------------------------------+ |
|   | I initiated an authorized network service scan on 192.168.1.50.             | |
|   |                                                                             | |
|   | +--- [Artifact: nmap.scan.v1] --------------------------------------------+ | |
|   | | Status: Success · Duration: 2410ms · Tier 2 (Active CLI)                 | | |
|   | | Ports Detected: 22/tcp (SSH), 80/tcp (HTTP), 443/tcp (HTTPS)            | | |
|   | | [Copy Raw JSON]                                    [Open in Console ↗]  | | |
|   | +-------------------------------------------------------------------------+ | |
|   |                                                                             | |
|   | **Synthesis Summary**:                                                      | |
|   | Host 192.168.1.50 is online with web services exposed. Next recommended    | |
|   | step: web enumeration using `whatweb.scan.v1` and `nikto.scan.v1`.          | |
+-----------------------------------------------------------------------------------+
```

### 11.5 Console Drawer: System & Hardware Telemetry

```text
+-----------------------------------------------------------------------------------+
| Advanced Console [System] [Events] [Terminal] [Screen] [Graph] [Audit] [Leaderboard]
+-----------------------------------------------------------------------------------+
| Local LLM Status: Online (Transformers Custom Primary)                            |
| Model ID: kairo-scale-2b | Quantization: None (BF16) | Context Length: 4096      |
| Air-Gapped Privacy: 100% Local (Cloud Prevented)                                  |
|                                                                                   |
| GPU VRAM Usage: [██████████████░░░░░░] 7.2 GB / 12.0 GB (60.0%)                   |
| System RAM:     [████████████░░░░░░░░] 14.1 GB / 32.0 GB (44.0%)                  |
| Kali Worker VM: Online (VirtualBox / WSL2 Plane) | Snapshots: 4 Available         |
+-----------------------------------------------------------------------------------+
```

### 11.6 Console Drawer: Live Kali Terminal Stream

```text
+-----------------------------------------------------------------------------------+
| Advanced Console [System] [Events] [Terminal] [Screen] [Graph] [Audit] [Leaderboard]
+-----------------------------------------------------------------------------------+
|  ____  __.      .__                                                               |
| |    |/ _|____  |__|______  ____                                                  |
| |      < \__  \ |  \_  __ \/  _ \      KAIRO HEADLESS KALI ISOLATION WORKER       |
| |    |  \ / __ \|  ||  | \(  <_> )     Session: sess_main_01 | PID: 14829         |
| |____|__ (____  /__||__|   \____/      Plane: windows_wsl2 | Root: /root          |
|                                                                                   |
| kali@kairo-worker:~$ nmap -sV -sC 192.168.1.50                                    |
| Starting Nmap 7.94 ( https://nmap.org ) at 2026-10-21 11:30 UTC                   |
| Nmap scan report for 192.168.1.50                                                 |
| Host is up (0.00042s latency).                                                    |
| PORT    STATE SERVICE VERSION                                                     |
| 22/tcp  open  ssh     OpenSSH 8.9p1 Ubuntu                                        |
| 80/tcp  open  http    Apache httpd 2.4.52                                         |
| 443/tcp open  ssl/ssl Apache httpd 2.4.52                                         |
| [Stream Connected: ws://localhost:4000/terminal/stream]                           |
+-----------------------------------------------------------------------------------+
```

### 11.7 Console Drawer: Kali Desktop Screen Stream (noVNC)

```text
+-----------------------------------------------------------------------------------+
| Advanced Console [System] [Events] [Terminal] [Screen] [Graph] [Audit] [Leaderboard]
+-----------------------------------------------------------------------------------+
| [ Kali XFCE Virtual Desktop (RFB / noVNC Stream :5900) ]                           |
| +-------------------------------------------------------------------------------+ |
| | [Applications]   [Terminal]   [Burp Suite Pro]   [Wireshark]                  | |
| | +---------------------------------------------------------------------------+ | |
| | | Burp Suite Community Edition v2026.1                                      | | |
| | | Target: http://192.168.1.50/dvwa/                                          | | |
| | | Issues Identified: 3 Low, 2 Medium, 1 High (SQLi in login parameter)     | | |
| | +---------------------------------------------------------------------------+ | |
| +-------------------------------------------------------------------------------+ |
| Low Latency RFB Stream Active · 1280x720 · 30 FPS · WebSockets Tunneling Enabled  |
+-----------------------------------------------------------------------------------+
```

### 11.8 Console Drawer: Task Graph DAG Planner

```text
+-----------------------------------------------------------------------------------+
| Advanced Console [System] [Events] [Terminal] [Screen] [Graph] [Audit] [Leaderboard]
+-----------------------------------------------------------------------------------+
| Active DAG Plan: plan_1792562_recon | Status: Executing Node 3 of 4               |
|                                                                                   |
|   [Node 1: Port Scan] =========> [Node 2: Web Enum] ====> [Node 4: CVE Search]    |
|   nmap.scan.v1 (Completed)       whatweb.scan.v1 (Completed)  cve.search.v1 (Pending)
|          |                                                      ▲                 |
|          +=====================> [Node 3: Vuln Audit] ==========+                 |
|                                  nikto.scan.v1 (Running)                          |
|                                                                                   |
| [Decompose Sub-Objective]                [Pause Plan]               [Abort Plan]  |
+-----------------------------------------------------------------------------------+
```

### 11.9 Console Drawer: Audit Findings & Evidence Explorer

```text
+-----------------------------------------------------------------------------------+
| Advanced Console [System] [Events] [Terminal] [Screen] [Graph] [Audit] [Leaderboard]
+-----------------------------------------------------------------------------------+
| Immutable SQLite Event Store (`events.db`) · Total Events: 1,482                  |
| Filter: [All] [Success] [Error] | Search: [ 192.168.1.50                      ]   |
|                                                                                   |
| Event ID #1482 · 11:30:14 · nmap.scan.v1 · Exit: 0 · Duration: 2.41s              |
|   Actor: orchestrator:agent | Target: 192.168.1.50 | SHA256: 3a9f...b82c          |
|   Summary: Discovered 3 open ports (22, 80, 443). Host state: up.                 |
|                                                                                   |
| Event ID #1481 · 11:29:58 · dag.execution.v1 · Exit: 0 · Nodes: 4/4 Completed     |
|   Actor: orchestrator:planner:synthesis | Plan: plan_recon_01                      |
|   Summary: Completed DAG plan: 4/4 steps succeeded (completed).                   |
+-----------------------------------------------------------------------------------+
```

### 11.10 Console Drawer: Benchmark Leaderboard

```text
+-----------------------------------------------------------------------------------+
| Advanced Console [System] [Events] [Terminal] [Screen] [Graph] [Audit] [Leaderboard]
+-----------------------------------------------------------------------------------+
| Model Performance Benchmark Leaderboard (50-Task Golden & 120-Task Extended Suite)|
|                                                                                   |
| Model ID                     Role              Accuracy   Avg Dur   Schema Score  |
| --------------------------------------------------------------------------------- |
| kairo-scale-2b-grpo          Custom Primary    96.4%      1.82s     1.00          |
| Qwen3-Coder-30B              MoE Base          94.1%      3.14s     0.98          |
| kairo-scale-2b               Custom Base       91.8%      1.95s     0.97          |
| Qwen2.5-0.5B-Instruct        Local Fallback    82.5%      0.84s     0.92          |
+-----------------------------------------------------------------------------------+
```

### 11.11 Mobile Responsive Viewport (375px)

```text
+-----------------------------------+
| [☰] Kairo [Claude] [✦ Scale 2B] [⚙]|
+-----------------------------------+
|                                   |
| [User]: Port scan 10.0.0.5        |
|                                   |
| [Agent]:                          |
| ✦ Thought for 1.2s ▾              |
| Executed authorized port scan.    |
|                                   |
| +--- [Artifact: nmap.scan.v1] --+ |
| | Status: Success (1.4s)        | |
| | 80/tcp open (HTTP)            | |
| | [Copy JSON]    [Console ↗]    | |
| +-------------------------------+ |
|                                   |
| 🔒 Scope: 10.0.0.5 · Active       |
| +-------------------------------+ |
| | Enter prompt...         [▲]   | |
| +-------------------------------+ |
+-----------------------------------+
```

---

## 12. Responsive Breakpoint Architecture & Mobile Behavior

| Breakpoint | Layout Behavior | Sidebar | Advanced Console Drawer |
| :--- | :--- | :--- | :--- |
| **Desktop (>1024px)** | Two-Column Cockpit | 260px (Collapsible to 0) | Right split drawer (560px standard / 880px wide) |
| **Tablet (768px – 1024px)** | Single-Column Chat | Collapsed by default | Slide-over drawer (560px) |
| **Mobile (<768px)** | Full-Width Chat | Full-screen overlay with backdrop | Full-screen overlay with horizontal scroll tab rail |

---

## 13. Accessibility (WCAG 2.2 AA) & Visual Safety

- **Color Contrast**: Main text (`#faf9f5` on `#181816`) achieves a **14.8:1 contrast ratio**, exceeding WCAG AAA standards. Secondary text (`#b0aea5`) achieves **7.4:1**.
- **Keyboard Navigation**:
  - `Ctrl + K`: Start new conversation session.
  - `Ctrl + B`: Toggle left sidebar collapse/expand.
  - `Escape`: Instantly closes the Advanced Console drawer, Scope popover, or Model dropdown.
  - `Enter`: Sends directive (when non-empty); `Shift + Enter`: Inserts newline.
- **Zero DOM Exception Guarantee**: Verified via automated Playwright test suite (`scripts/test_runtime_errors.py`) with 0 `removeChild` or hydration errors.
