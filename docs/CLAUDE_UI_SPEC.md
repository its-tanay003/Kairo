# KAIRO: Claude UI Design System & Component Specification

> **Official Design System Specification for KAIRO v4.0**  
> **Aesthetic Archetype**: Anthropic Claude Dark Theme  
> **Key Brand Elements**: Terracotta Coral (`#d97757`), Warm Obsidian (`#141413`), Warm Slate (`#181816`), Editorial Serif (`Newsreader`), Progressive Artifacts.

---

## Table of Contents

1. [Visual Brand Identity & Anthropic Ethos](#1-visual-brand-identity--anthropic-ethos)
2. [Complete Design Token Catalog](#2-complete-design-token-catalog)
3. [Typography Hierarchy & Font System](#3-typography-hierarchy--font-system)
4. [Component Architecture & Contracts](#4-component-architecture--contracts)
   - [4.1 Collapsible Sidebar & Operator Profile](#41-collapsible-sidebar--operator-profile)
   - [4.2 Minimalist Top Navigation & Model Selector](#42-minimalist-top-navigation--model-selector)
   - [4.3 Claude Welcome Screen & Starter Grid](#43-claude-welcome-screen--starter-grid)
   - [4.4 User Message Bubbles](#44-user-message-bubbles)
   - [4.5 Claude 3.7 Extended Thinking Accordion](#45-claude-37-extended-thinking-accordion)
   - [4.6 Claude Artifact Tool Execution Cards](#46-claude-artifact-tool-execution-cards)
   - [4.7 Claude Floating Composer & Terracotta Send Action](#47-claude-floating-composer--terracotta-send-action)
   - [4.8 Right Split Console & Artifacts Drawer](#48-right-split-console--artifacts-drawer)
5. [Micro-Interactions & Animation Standards](#5-micro-interactions--animation-standards)
6. [Responsive Breakpoint Behaviors](#6-responsive-breakpoint-behaviors)
7. [Accessibility Standards (WCAG 2.2 AA)](#7-accessibility-standards-wcag-22-aa)

---

## 1. Visual Brand Identity & Anthropic Ethos

The KAIRO v4.0 interface embraces the signature **Anthropic Claude visual identity**:
- **Calm, High-Contrast Readability**: Avoiding pitch-black or cold blue surfaces; using warm charcoal and obsidian tones that reduce eye strain during prolonged cyber-operations.
- **Literary Sophistication**: Headings styled with classical editorial serif typography evoke the thoughtful, measured persona of Claude models.
- **Anthropic Terracotta Coral (`#d97757`)**: The definitive accent color representing warmth, precision, and focus.
- **Artifacts over Cockpits**: Raw developer telemetry is sequestered into clean, collapsible **Artifacts**, keeping the primary conversation focused and distraction-free.

---

## 2. Complete Design Token Catalog

Defined in [`ui/src/app/globals.css`](file:///c:/New%20Volume%20(D)/dev/ui/src/app/globals.css):

### 2.1 Surfaces & Backgrounds
| Token | Hex / Value | Semantic Role |
| :--- | :--- | :--- |
| `--bg-app` | `#181816` | Main application chat canvas background |
| `--bg-surface` | `#141413` | Left navigation sidebar, top header, drawer base |
| `--bg-surface-raised` | `#21211e` | Cards, popovers, model dropdowns, modal panels |
| `--bg-surface-hover` | `#292825` | Hover state for interactive items |
| `--bg-input` | `#21201d` | Floating composer textarea container |
| `--bg-input-focus` | `#252421` | Composer active focused state |

### 2.2 Borders & Dividers
| Token | Hex / Value | Semantic Role |
| :--- | :--- | :--- |
| `--border-subtle` | `#2d2c28` | Standard structural dividers and panel borders |
| `--border-focus` | `#424039` | Focused borders, active card outlines |
| `--border-accent` | `rgba(217, 119, 87, 0.4)` | Terracotta accent highlight borders |

### 2.3 Typography & Text
| Token | Hex / Value | Semantic Role |
| :--- | :--- | :--- |
| `--text-primary` | `#faf9f5` | Warm ivory white main text (headers, chat content) |
| `--text-secondary` | `#b0aea5` | Warm stone mid-gray (labels, secondary meta, timestamps) |
| `--text-muted` | `#757470` | Subtle placeholders, disabled controls, shortcuts |

### 2.4 Accents & Status
| Token | Hex / Value | Semantic Role |
| :--- | :--- | :--- |
| `--accent` | `#d97757` | Anthropic signature terracotta coral |
| `--accent-hover` | `#e58667` | Hover tint for terracotta buttons |
| `--accent-active` | `#c66749` | Pressed state for buttons |
| `--accent-subtle` | `rgba(217, 119, 87, 0.12)` | Translucent background for pills and active badges |
| `--accent-blue` | `#6a9bcc` | Secondary denim blue for network telemetry |
| `--accent-green` | `#788c5d` | Sage green for confirmed scope and successes |
| `--status-success` | `#788c5d` | 7px indicator dot for online / verified state |
| `--status-warning` | `#e8b84b` | Warm amber dot for degraded / fallback states |
| `--status-error` | `#d95757` | Coral red dot for disconnected / tool error states |

---

## 3. Typography Hierarchy & Font System

### 3.1 Font Families
- **Editorial Headings**: `'Newsreader', 'Lora', Georgia, serif`
- **Interface & Chat Text**: `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Technical & CLI Telemetry**: `'JetBrains Mono', ui-monospace, SFMono-Regular, monospace`

### 3.2 Scale
```text
Display 1 (Welcome Title)    : 29px / Line-height 1.25 / Newsreader Regular
Headline (Top Wordmark)      : 19px / Line-height 1.20 / Newsreader Medium
Body 1 (Messages, Input)     : 15px / Line-height 1.65 / Inter Regular
Body 2 (Card Titles)         : 13px / Line-height 1.40 / Inter SemiBold
Caption (Metadata, Badges)   : 11px / Line-height 1.30 / Inter Medium
Code 1 (Commands & Hashes)   : 12px / Line-height 1.45 / JetBrains Mono Medium
```

---

## 4. Component Architecture & Contracts

### 4.1 Collapsible Sidebar & Operator Profile
- **Width**: `260px` default; smoothly collapses to `0px` with `transition: width 0.2s cubic-bezier(0.16, 1, 0.3, 1)`.
- **Top Action**: `+ New session` button with terracotta starburst icon and `Ctrl K` keyboard shortcut badge.
- **Session Items**: Text truncation at 160px with relative timestamp (`Just now`, `12m ago`). Active session highlighted with terracotta font weight and subtle surface lift.
- **Operator Card**: Fixed to bottom footer displaying user avatar (`OP`), role title, and security authorization badge (`Airgap · Tier 2 Authorized`).

### 4.2 Minimalist Top Navigation & Model Selector
- **Height**: Restrained `52px`.
- **Sidebar Toggle**: Minimalist icon button to toggle sidebar visibility.
- **Model Selector Dropdown**: Pill located in center:
  - Displays `✦ {selectedModel}` with dropdown chevron.
  - Options include: `Kairo 3.7 (Sonnet Tier)`, `Kairo 3.5 (Haiku Fast)`, `Llama-3-70B Pentest SFT`, and `DeepSeek-R1 Reasoner`.
- **Status Pill**: Shows real-time connection state (`● Ready`, `● Running nmap…`, `● Connecting…`). Hovering reveals tooltip detailing Model, Kali Worker, Scope Target, and Session Hash.
- **Console Button**: Right-aligned pill with split-screen icon (`[ | ] ⚙ Advanced`).

### 4.3 Claude Welcome Screen & Starter Grid
When no messages exist in the active session, a welcoming empty state is rendered:
- Terracotta starburst spark icon (`44px`).
- Serif headline: *"What would you like to investigate today?"*
- Subtitle explaining autonomous capabilities.
- **2x2 Grid of Starter Cards**:
  1. `Reconnaissance & Scan` -> Fills input with `Perform comprehensive reconnaissance and port discovery against 192.168.1.0/24`.
  2. `Autonomous DAG Plan` -> Fills input with `Conduct comprehensive penetration test against 192.168.1.50 with parallel decomposition`.
  3. `Kali Terminal Session` -> Opens Terminal tab and starts interactive CLI session.
  4. `Audit Findings & CVEs` -> Opens Audit tab in the Console drawer.

### 4.4 User Message Bubbles
- Right-aligned container with rounded corners (`18px 18px 4px 18px`).
- Dark warm surface (`#282724`), delicate border (`#383632`), and warm ivory text (`#faf9f5`).
- Max-width capped at 82% of chat width for visual comfort.

### 4.5 Claude 3.7 Extended Thinking Accordion
- Styled identically to Claude 3.7 Sonnet's "Thinking..." block:
- Collapsible container with subtle terracotta border (`rgba(217, 119, 87, 0.25)`) and warm tint background.
- Toggle button: `✦ Thought for {duration}s ▾`.
- Content reveals cognitive evaluation rationale, candidate tool scoring, and self-healing recovery actions.

### 4.6 Claude Artifact Tool Execution Cards
Tool executions are encapsulated as rich Claude Artifacts:
- Header: `ARTIFACT` pill in terracotta, tool name (`nmap.scan.v1`), status indicator (`● Verified` or `● Failed`), duration.
- Action Buttons:
  - `Open in Console ↗`: Deep-links directly to the relevant drawer tab (Terminal, Screen, Task Graph, Audit).
  - `Details`: Toggles parameter values and full command telemetry.
- Code Output Container: JetBrains Mono on obsidian background (`#151514`) with syntax contrast.

### 4.7 Claude Floating Composer & Terracotta Send Action
- Centered container floating above the bottom viewport (`max-width: 760px`).
- Deep curved corners (`20px`), background `#21201d`, border `#2d2c28`, shadow `0 8px 30px rgba(0, 0, 0, 0.35)`.
- Active focus creates a delicate terracotta halo ring (`0 0 0 1px rgba(217, 119, 87, 0.4)`).
- Left tools: Scope Contract indicator pill (`🔒 Scope: 192.168.1.0/24 · Active`), Model shortcut pill.
- Right: **Circular Terracotta Send Button** (`34px` round, background `#d97757`, white upward arrow SVG, hover scale 1.04x).

### 4.8 Right Split Console & Artifacts Drawer
- Split panel sliding out from the right:
- Width modes: Standard `560px` or Expanded `880px`.
- Nav Rail tabs: `System`, `Event Log`, `Terminal`, `Screen (VNC)`, `Task Graph`, `Audit`, `Benchmarks`, `Dev tools`.
- Active rail tab highlighted with terracotta left-border (`#d97757`).

---

## 5. Micro-Interactions & Animation Standards

- **Transitions**: All interactive buttons and cards use `transition: all 0.15s ease-out`.
- **Drawer Slide-In**: `animation: slide-in 0.2s cubic-bezier(0.16, 1, 0.3, 1)`.
- **Send Button Lift**: `transform: scale(1.04)` on hover.
- **Status Dot Pulse**: `animation: pulse-dot 1.5s infinite ease-in-out` when operations are actively running.

---

## 6. Responsive Breakpoint Behaviors

| Screen Width | Viewport Mode | Layout Strategy |
| :--- | :--- | :--- |
| **>1024px** | Desktop Cockpit | Two-column layout with collapsible sidebar and slide-out console. |
| **768px – 1024px** | Tablet | Single-column chat; sidebar hidden by default; console overlays as drawer. |
| **<768px** | Mobile | Full-width chat; hamburger menu toggles full-screen sidebar; console drawer becomes full-screen with horizontal scrollable tab rail. |

---

## 7. Accessibility Standards (WCAG 2.2 AA)

- **Color Contrast**: Primary text achieves 14.8:1 contrast against `#181816`.
- **Keyboard Traps**: Zero traps. Escape key reliably closes drawers, popovers, and model dropdowns.
- **Focus Indicators**: 2px outline with high visibility across all keyboard tabbable elements.
