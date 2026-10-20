# /tests - Master Verification & Test Harness Suite

The `/tests` directory contains Kairo's verification matrix comprising **52+ comprehensive test suites**. The test harness validates formal JSON schemas, deterministic process supervision, cryptographic boundary enforcement, VM sandboxing, cognitive self-healing loops, multi-model failover routing, and reinforcement learning reward signals.

---

## Subsystem Test Coverage Matrix

### 1. ToolSpec Engine & SDK Conformance

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_toolspec_registry.py`](test_toolspec_registry.py) | Schema validation against `toolspec.schema.json`; fail-fast startup on missing blueprint fields or invalid privilege enums. |
| [`test_toolspec_sdk.py`](test_toolspec_sdk.py) | SDK CLI scaffolding, adapter compilation, and the 7-Gate Conformance Engine. |
| [`test_third_party_sdk_tool_addition.py`](test_third_party_sdk_tool_addition.py) | Proves dynamic addition of third-party security tools (`subfinder.enum.v1`, `dnsrecon.enum.v1`) with zero core code modification. |
| [`test_registry_ts.ts`](test_registry_ts.ts) | TypeScript loader conformance in Node.js/Gateway runtime. |

### 2. Execution Plane, Adapters & Process Supervision

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_trustworthy_execution.py`](test_trustworthy_execution.py) | Authentic exit codes (`1` on runtime error, `127` on missing tool; never forged `0`), deterministic CLI command lines, structured typed invocations, honest failure synthesis, live finding verification, and DAG failure isolation. |
| [`test_adapter.py`](test_adapter.py) | Process supervisor lifecycle for `shell.run.v1`: argument compilation, stdout/stderr capture, hard timeout enforcement, and SIGKILL termination. |
| [`test_tool_adapters.py`](test_tool_adapters.py) | Core Tier 1 and Tier 2 adapters (Nmap, Gobuster, Nikto, SQLMap, Hydra, WhatWeb, ExifTool, HashID, TCPDump). |
| [`test_supervisor.py`](test_supervisor.py) | Host process supervisor resource caps, memory bounds, and CPU throttling. |
| [`test_terminal_stream_supervisor.py`](test_terminal_stream_supervisor.py) | Real-time ANSI/VT100 terminal output streaming via WebSocket. |

### 3. GUI Tools, Browser Security & Screen Streaming

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_gui_adapters.py`](test_gui_adapters.py) | Tier 3 GUI tools (Burp Suite, Wireshark, OWASP ZAP) executed in headless X11 with window tracking. |
| [`test_browser_security_adapter.py`](test_browser_security_adapter.py) | Playwright-driven headless browser (`browser.security.v1`) capturing DOM, network context, and web screenshots. |
| [`test_screen_streaming.py`](test_screen_streaming.py) | RFB / noVNC WebSocket bridge streaming Kali virtual display to the UI at low latency. |

### 4. Planning, Tool Selection & Cognitive Healing

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_dag_controller.py`](test_dag_controller.py) | Topological DAG execution, prerequisite evidence gating (e.g. blocking web scanning until HTTP port is confirmed), capability-aware tool selection, and recovery path lineage. |
| [`test_planner.py`](test_planner.py) | DAG task decomposition, cycle detection, dependency topological sorting, and parallel execution. |
| [`test_tool_selection.py`](test_tool_selection.py) | 7-dimension hybrid tool selection scoring (category match, capability overlap, success rate, speed, resource cost, recency, error rate). |
| [`test_observer_critic_recovery.py`](test_observer_critic_recovery.py) | Autonomous cognitive loop: Observer fact extraction $\to$ Critic rule evaluation $\to$ Recovery Agent compensatory replanning. |
| [`test_reporter_failure_aware.py`](test_reporter_failure_aware.py) | Generates executive audit reports highlighting failure chains, causal ancestors, and recovery narratives. |

### 5. Security & Scope Boundaries

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_execution_gateway.py`](test_execution_gateway.py) | **Authoritative Execution Perimeter (11 Tests)**: Single choke point verification for all execution routes. Validates in-scope targets, out-of-scope rejections before adapter dispatch, expired contracts, tool tier bounds, command injection blocking, unregistered tools (127), fail-closed enforcement without contracts, DAG node gateway enforcement, anti-prompt self-authorization, and cryptographic operator token verification (`KAIRO-OP-...`). |
| [`test_scope_contract.py`](test_scope_contract.py) | HMAC-SHA256 signature verification, tamper detection, CIDR IP validation, and out-of-scope rejection. |
| [`test_workspace_and_auth_gateway.py`](test_workspace_and_auth_gateway.py) | Multi-client authentication tokens, desktop vs mobile scopes, token revocation, and session isolation. |

### 6. Virtualization Sandbox & Forensics

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_vm_sandbox.py`](test_vm_sandbox.py) | VirtualBox headless VM lifecycle, socket RPC, and isolated guest command execution. |
| [`test_vm_snapshot_rollback.py`](test_vm_snapshot_rollback.py) | Automated VM snapshot creation prior to destructive actions and clean state rollback on failure. |
| [`test_vm_limits.py`](test_vm_limits.py) | Guest VM resource limits (RAM, vCPU, disk, network bandwidth). |
| [`test_snapshot_limits_artifacts.py`](test_snapshot_limits_artifacts.py) | Enforces 100MB artifact file caps, max 500 artifacts per task, and SHA-256 integrity verification. |
| [`test_resource_limits.py`](test_resource_limits.py) | Host resource exhaustion prevention under extreme workloads. |

### 7. Model Center, Failover, Intent & Local Routing

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_model_intent_flow.py`](test_model_intent_flow.py) | Dynamic intent classification (question, plan_only, tool_request, task_request), target extraction, and step provenance. |
| [`test_model_integration.py`](test_model_integration.py) | Dual-model local routing (custom primary + local Qwen fallback), air-gapped guarantees, and 6-tuple audit provenance. |
| [`test_model_center.py`](test_model_center.py) | Hot-swapping local LLM backends via `/api/models/switch` and real-time hardware telemetry. |
| [`test_failover_router_model_pairs.py`](test_failover_router_model_pairs.py) | Validates automated failover across all 10 model pairs upon consecutive inference failures. |
| [`test_model_evolution_controller.py`](test_model_evolution_controller.py) | Autonomous self-improvement loop: SFT refresh on data threshold, tier scaling on plateau, and rollback on regression. |

### 8. Model Training, Alignment & Reinforcement Learning

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_model_and_training.py`](test_model_and_training.py) | PyTorch Transformer architecture, RoPE positional encoding, RMSNorm, and GQA attention heads. |
| [`test_trl_sft_and_schema_reward.py`](test_trl_sft_and_schema_reward.py) | Hugging Face TRL SFTTrainer integration with schema-cleaning filters and XML tool-call extraction. |
| [`test_dpo_preference_tuning_and_benchmark.py`](test_dpo_preference_tuning_and_benchmark.py) | DPO preference dataset collator and alignment loss computation. |
| [`test_grpo_training_and_rewards.py`](test_grpo_training_and_rewards.py) | Verifiable mathematical rewards: Schema Validity (+1.0), Tool Registry (+1.0), and Task Completion (+2.0). |
| [`test_phase3_dataset_expansion_and_1b_model.py`](test_phase3_dataset_expansion_and_1b_model.py) | 1B-1.5B parameter scaling, gradient computation, and task graph expansion. |
| [`test_scale_stages_pipeline.py`](test_scale_stages_pipeline.py) | Validates progression across scale stages (350M $\to$ 700M $\to$ 1.2B $\to$ 2B). |
| [`test_pretrain_scale_job.py`](test_pretrain_scale_job.py) | Domain pre-training execution, loss telemetry, and checkpoint emission for Kairo-Scale-2B. |

### 9. Evidence Store, Collaboration & Benchmarks

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_evidence_store_and_reporter.py`](test_evidence_store_and_reporter.py) | 6 artifact classes (raw output, normalized facts, screenshots, network traces, finding cards, reports). |
| [`test_shared_projects_and_audit_explorer.py`](test_shared_projects_and_audit_explorer.py) | Multi-operator shared project state, live collaborator presence, and 20-field audit query filters. |
| [`test_multi_client_consistency.py`](test_multi_client_consistency.py) | Real-time state consistency across simultaneous desktop, web, and mobile operators. |
| [`test_lab_benchmark.py`](test_lab_benchmark.py) | 50-task Golden benchmark execution, scoring weights, and pass/fail thresholds. |
| [`test_benchmark_sweep.py`](test_benchmark_sweep.py) | Automated multi-model benchmark sweep comparing all registered models under identical conditions. |
| [`test_benchmark_expansion_and_failover.py`](test_benchmark_expansion_and_failover.py) | 120-task Full benchmark suite verifying all 28 registered tools. |
| [`test_dataset_curation_and_benchmark_leaderboard.py`](test_dataset_curation_and_benchmark_leaderboard.py) | Dataset curation panel, benchmark leaderboard history, and public cryptographic score cards. |

### 10. Boundary, Stress & Cross-Platform

| Test File | Focus & Verification Criteria |
| :--- | :--- |
| [`test_boundary.py`](test_boundary.py) | End-to-end service boundary integration (`llama.cpp` $\to$ Orchestrator $\to$ Gateway $\to$ SQLite). |
| [`test_extreme_stress.py`](test_extreme_stress.py) | 100-node massive DAGs, malformed CIDR fuzzing, HMAC bit-flip tamper detection. |
| [`test_real_usage_simulation.py`](test_real_usage_simulation.py) | Real-world penetration testing scenarios with multi-step discovery, exploitation, and reporting. |
| [`test_execution_plane_and_tauri.py`](test_execution_plane_and_tauri.py) | Cross-platform plane detection (Windows WSL2, Linux native, macOS virtualization) and Tauri desktop IPC. |
| [`test_mobile_browser_viewport.py`](test_mobile_browser_viewport.py) | Mobile client responsive layout on 375px viewports and touch interaction. |

---

## Running Tests

### Run Master Consolidated Engineering Suite (189 Passed, 5 Skipped, 0 Failed - 100% Pass)

```bash
python -m pytest tests/test_execution_gateway.py tests/test_model_intent_flow.py tests/test_dag_controller.py tests/test_trustworthy_execution.py tests/test_toolspec_registry.py tests/test_scope_contract.py tests/test_workspace_and_auth_gateway.py tests/test_execution_plane_and_tauri.py tests/test_tool_selection.py tests/test_tool_execution_chain.py tests/test_model_integration.py tests/test_model_center.py tests/test_boundary.py tests/test_reporter_failure_aware.py tests/test_evidence_store_and_reporter.py tests/test_observer_critic_recovery.py tests/test_planner.py tests/test_shared_projects_and_audit_explorer.py tests/test_lab_benchmark.py tests/test_snapshot_limits_artifacts.py tests/test_vm_limits.py tests/test_third_party_sdk_tool_addition.py tests/test_terminal_stream_supervisor.py -v
```

### Run Full Test Matrix

```bash
python -m pytest -v
```

### Run Specific Subsystem Tests

```bash
# Execution Gateway & Scope Security
python -m pytest tests/test_execution_gateway.py tests/test_scope_contract.py -v

# Cognitive Loop & Self-Healing
python -m pytest tests/test_observer_critic_recovery.py -v

# ToolSpec SDK & Conformance
python -m pytest tests/test_toolspec_sdk.py -v

# Model Evolution & Training
python -m pytest tests/test_model_evolution_controller.py -v
python -m pytest tests/test_grpo_training_and_rewards.py -v
```
