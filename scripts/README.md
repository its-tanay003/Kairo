# /scripts - Automation, Verification & Operational Tooling

The `/scripts` directory houses maintenance utilities, chaos testing harnesses, benchmark generators, UI visual testing tools, and deployment automation scripts for the Kairo platform.

---

## Script Catalog

### 1. ToolSpec Scaffolding & Generation
| Script | Command / Description |
| :--- | :--- |
| [`create_toolspec.py`](create_toolspec.py) | Python wrapper for scaffolding third-party tools via the ToolSpec SDK.<br>`python scripts/create_toolspec.py <tool_id> --category <cat> --binary <bin>` |
| [`create-toolspec.bat`](create-toolspec.bat) | Windows batch file shortcut forwarding arguments to `python -m sdk create-toolspec`. |

### 2. UI Styling & Visual Automation
| Script | Command / Description |
| :--- | :--- |
| [`apply_claude_ui.py`](apply_claude_ui.py) | Automates injection of Claude Warm Dark design tokens, Newsreader serif typography, and component styling into `ui/`. |
| [`capture_claude_ui_screenshots.py`](capture_claude_ui_screenshots.py) | Playwright script capturing welcome screen, chat interactions, thinking accordions, and model selector views. |
| [`capture_drawer_views.py`](capture_drawer_views.py) | Automated capture of right-hand drawer views (Terminal, VNC Screen, DAG Graph, System Telemetry, Audit Explorer). |
| [`capture_scrolled_views.py`](capture_scrolled_views.py) | Captures deep scroll states of high-density tables (Audit Explorer, Benchmark Leaderboard). |
| [`capture_ui_screenshots.py`](capture_ui_screenshots.py) | Legacy UI snapshot utility. |
| [`verify_and_capture_new_ui.py`](verify_and_capture_new_ui.py) | End-to-end visual regression pipeline verifying responsive layout across desktop (1440px, 880px, 560px) and mobile (375px). |

### 3. Chaos Engineering & Extreme Testing
| Script | Command / Description |
| :--- | :--- |
| [`break_website_chaos.py`](break_website_chaos.py) | Injects chaos events into the WebSocket stream (dropped packets, malformed JSON, out-of-order events, network partitions) to verify frontend resilience. |
| [`test_extreme_user_simulation.py`](test_extreme_user_simulation.py) | Simulates rapid, erratic operator actions (burst clicking, fast tab toggling, simultaneous prompt submissions, rapid model switching). |
| [`stress_test_tools.py`](stress_test_tools.py) | Executes concurrent high-load stress testing against local adapters (Nmap, Nikto, Gobuster, SQLMap) under hard resource constraints. |
| [`test_advanced_menu.py`](test_advanced_menu.py) | Headless browser test validating drawer opening/closing, Escape key handling, and 560px $\leftrightarrow$ 880px width transitions. |
| [`test_runtime_errors.py`](test_runtime_errors.py) | Simulates backend offline states (`502 Bad Gateway`, `500 Internal Error`, dropped WebSockets) to verify frontend error boundaries. |

### 4. Benchmark Expansion & Tool Verification
| Script | Command / Description |
| :--- | :--- |
| [`expand_benchmark_tasks.py`](expand_benchmark_tasks.py) | Expands the core 50-task Golden benchmark into the 120-task Full benchmark suite in [`lab/extended_tasks.py`](../lab/extended_tasks.py). |
| [`test_benchmark_toolspecs.py`](test_benchmark_toolspecs.py) | Validates that all ToolSpecs declared across benchmark tasks pass strict 16-field schema validation. |
| [`list_classes.py`](list_classes.py) | Utility inspecting Python AST to report all class and function signatures across the repository. |

### 5. Deployment & Worker Automation
| Script | Command / Description |
| :--- | :--- |
| [`deploy_worker.py`](deploy_worker.py) | Automates packaging and deploying [`vm/worker_agent.py`](../vm/worker_agent.py) to a remote or local VirtualBox Kali Linux instance. |

---

## Common Developer Workflows

### Run Chaos Testing on Frontend
Ensure UI and Gateway are running on ports 3000 and 4000:
```bash
python scripts/break_website_chaos.py
```

### Run Extreme User Stress Simulation
```bash
python scripts/test_extreme_user_simulation.py
```

### Regenerate Extended Benchmark Tasks
```bash
python scripts/expand_benchmark_tasks.py
```
