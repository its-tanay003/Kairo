# /orchestrator - Autonomous Agent Engine & Cognitive Core

The `/orchestrator` subsystem is the central nervous system of Kairo. Implemented in Python with FastAPI, it coordinates the autonomous cognitive loop: translating high-level operator directives into Directed Acyclic Graph (DAG) execution plans, selecting tools via 7-dimensional scoring, enforcing cryptographic scope boundaries, evaluating execution outcomes, and self-healing upon tool failures.

---

## Subsystem Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (/run, /chat, /events)           │
│                               (server.py)                              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Intent Classifier & Provenance (intent_classifier.py)    │
│  - Categorizes directives: question, plan_only, tool_request, task_req │
│  - Extracts target entities and records step provenance metadata       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Topological DAG Controller (dag_controller.py)           │
│  - Prerequisite evidence gating (verifies open ports before web scans) │
│  - Topological node execution & failure state containment              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Hybrid Tool Selector (tool_selector.py)                  │
│  - Scores tools across 7 dimensions (category, capability, history)    │
│  - Consults persistent Tool Memory Store (/events/events.db)           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Execution Gateway Perimeter (execution_gateway.py)         │
│  - Fail-closed Scope Contract validation (HMAC-SHA256, CIDRs, Tiers)   │
│  - Anti-Prompt-Injection cryptographic operator tokens (KAIRO-OP-...)  │
│  - Tool registration check (exit 127) & schema argument validation    │
│  - Broad command approval policy & immutable 20-field event logging    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│           Process Supervisor & VM Manager (process_supervisor.py)      │
│  - Dispatches to Host Supervisor or Kali VM Worker (vm_manager.py)     │
│  - Enforces hard memory/CPU caps, timeouts, and SIGKILL kill switch    │
│  - Preserves authentic exit codes and command_line reconstruction      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Active Finding Verification Engine (finding_verifier.py)   │
│  - Scope-authorized TCP socket handshakes with latency measurement     │
│  - HTTP/HTTPS service banner interrogation and confidence calibration  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Self-Healing Cognitive Loop (Observer & Critic)            │
│                                                                        │
│  1. Observer (observer.py): Extracts structured ObservationFacts       │
│  2. Critic (critic.py): Evaluates success vs failure criteria          │
│  3. Recovery Agent (recovery_agent.py): Proposes compensatory actions  │
│  4. Dynamic DAG Adapter (dag_controller.py): Injects downstream nodes  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│      Conversational Synthesizer & Recommendations                      │
│      (conversational_synthesizer.py, aliased by claude_synthesis.py)   │
│  - 4 Mandatory Sections: Executive Summary, Breakdown, Findings, Next  │
│  - 3–5 Proactive Click-to-Run Next-Step Recommendations with badges    │
│  - Honest failure badging (❌ Execution Failed) on errors               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│            Evidence & Trajectory Store (reporter.py, db.py)            │
│  - Emits 20-field audit events to SQLite (/events/events.db)           │
│  - Immutably persists execution trajectories for training curation     │
│  - Synthesizes Finding Cards & Executive Penetration Reports           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Module Index

| Module | Purpose & Core Responsibilities |
| :--- | :--- |
| [`conversational_synthesizer.py`](conversational_synthesizer.py) | **Conversational Synthesis & Recommendations Engine**: Formats conversational responses structured into 4 mandatory sections (`Executive Summary`, `Step-by-Step Breakdown`, `Verified Findings & Evidence`, and `What We Can Do Next`) and generates 3–5 click-to-run follow-up recommendations with valid ToolSpec IDs, parameters, and tactical rationales. Aliased by `claude_synthesis.py`. |
| [`execution_gateway.py`](execution_gateway.py) | **Centralized Execution Perimeter**: The authoritative single choke point for all tool and command execution routes. Enforces fail-closed scope contracts, CIDR targets, tool tiers, operator token verification (`KAIRO-OP-...`), broad execution approvals, and 20-field SQLite audit logging. |
| [`model_runtime.py`](model_runtime.py) | **Local Neural Inference Engine**: Manages local PyTorch causal LM inference (`TransformersLocalRuntime` for GRPO checkpoints) and local GGUF grammar inference (`LlamaCppLocalRuntime`). Enforces fine-grained `ModelReadinessState` and zero-cloud execution. |
| [`server.py`](server.py) | Main FastAPI application exposing REST, WebSocket, and real-time Server-Sent Events (`POST /chat/stream`) for streaming token generation, lifecycle states, process management, findings, intent, audit, and model evolution. |
| [`agent.py`](agent.py) | Autonomous agent execution loop coordinating intent classification, tool invocation, trustworthy execution result logging, and honest response synthesis. |
| [`dag_controller.py`](dag_controller.py) | Topological DAG execution controller enforcing prerequisite evidence gating, dynamic argument resolution from prior evidence (`_resolve_arguments_from_evidence`), and mid-execution dynamic attack surface adaptation (`_adapt_plan_if_new_attack_surface`). |
| [`finding_verifier.py`](finding_verifier.py) | Active live finding verification engine executing scope-checked TCP socket handshakes, HTTP/HTTPS banner inspection, and dynamic confidence updates (+0.2/-0.4). |
| [`intent_classifier.py`](intent_classifier.py) | Dynamic multi-class intent classifier (`question`, `plan_only`, `tool_request`, `task_request`) with extracted entities and provenance metadata. |
| [`model_integration.py`](model_integration.py) | Dual-model local routing orchestrator managing custom primary weights and local fallback inference with 6-tuple audit provenance. |
| [`reporter_templates.py`](reporter_templates.py) | Deterministic, zero-hallucination agent response formatting engine with truthful failure badging (`❌ Execution Failed`), simulation warnings, and reachability status. |
| [`planner.py`](planner.py) | Autonomous DAG task planner. Validates dependency structures, prevents cycles, and orchestrates multi-step penetration operations. |
| [`observer.py`](observer.py) | Telemetry observer parsing raw tool stdout/stderr into structured `ObservationFact` entities (open ports, CVEs, hosts). |
| [`critic.py`](critic.py) | Evaluation critic verifying task exit codes, regex success signals, and hallucination indicators. |
| [`recovery_agent.py`](recovery_agent.py) | Self-healing engine triggering fallback tools (e.g. Nmap XML $\to$ Nmap normal parse; Nikto $\to$ WhatWeb) upon tool errors. |
| [`tool_selector.py`](tool_selector.py) | 7-dimensional scoring engine evaluating candidate tools against requirements and historical success rates. |
| [`model_evolution_controller.py`](model_evolution_controller.py) | Background engine monitoring model performance and triggering autonomous SFT refresh, tier scaling, and benchmark validation. |
| [`failover_router.py`](failover_router.py) | High-availability inference router managing pair fallbacks and fast local model schema self-correction loops (`attempt_self_correction`) against `toolspec.schema.json`. |
| [`model_center.py`](model_center.py) | Centralized model runtime manager tracking active backends, GPU/CPU usage, and context memory. |
| [`training_manager.py`](training_manager.py) | Automated dataset curation engine (`curate_trajectories_for_training`) filtering valid execution traces from SQLite `trajectories` into SFT and DPO JSONL datasets. |
| [`process_supervisor.py`](process_supervisor.py) | Host process execution supervisor enforcing timeouts, memory caps, and process tree termination. |
| [`vm_manager.py`](vm_manager.py) | VirtualBox management plane managing snapshot creation, rollback, and host-to-guest networking. |
| [`kali_connector.py`](kali_connector.py) | HTTP client interfacing with the remote Kali Linux guest worker agent on port 9999. |
| [`vnc_server.py`](vnc_server.py) | Internal RFB proxy bridging desktop GUI streams to noVNC web sockets. |
| [`evidence_store.py`](evidence_store.py) | Forensic artifact store managing 6 artifact classes with cryptographic SHA-256 integrity checks. |
| [`reporter.py`](reporter.py) | Comprehensive markdown and PDF audit report generator with finding cards and causal recovery chains. |
| [`workspace_manager.py`](workspace_manager.py) | Manages ephemeral per-session working directories and artifact storage. |
| [`schema_gen.py`](schema_gen.py) | Compiles runtime GBNF grammars for `llama.cpp` to constrain model generation strictly to valid JSON. |

---

## Running the Orchestrator

```bash
# Start the FastAPI server on port 8000
python -m uvicorn orchestrator.server:app --host 0.0.0.0 --port 8000 --reload
```
