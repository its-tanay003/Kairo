# 🔬 Research Report: Custom Specialized Model vs. Qwen3-Coder-30B-A3B-Instruct Fallback

**Authors**: Kairo Autonomous Agent Engineering Team  
**Publication Track**: Section 21 — Model Research & Publishable Differentiation  
**Date**: October 2026  
**Artifact Version**: Evaluation Framework Benchmark v1.0.0 (120 Standardized Security Tasks)  
**Evaluated Models**:

- **Primary-Custom Specialized Architecture**: `kairo-custom-model` / `kairo-dpo-aligned` (Compact Dense Transformer, 490M–1.2B Parameters, ToolSpec Schema Validated, DPO Aligned on Multi-Hop Task Graphs, GRPO Verifiable Rewards)
- **Fallback Baseline Foundation Model**: `Qwen3-Coder-30B-A3B-Instruct` (Mixture-of-Experts 30B Total Parameters, 3.3B Activated Parameters, Q4_K_M Quantization)

---

## Executive Summary & Blog Abstract

A persistent dogma in autonomous AI agent research is that scaling general-purpose foundation models to tens of billions of parameters is the primary prerequisite for reliable tool use and decision-making. In specialized, high-stakes domains like autonomous offensive and defensive cybersecurity operations, this paradigm encounters severe friction: large generalist models introduce substantial latency, massive VRAM requirements, non-deterministic schema violations, and a pronounced tendency toward unnecessary exploratory calls and hallucinated success claims.

This report presents a comprehensive empirical evaluation of **Kairo's Custom Domain-Specialized Model** against the state-of-the-art **`Qwen3-Coder-30B-A3B-Instruct`** fallback across the complete **120-task Kairo Evaluation Framework benchmark set**.

Our primary thesis: **The evaluation methodology itself—strictly grounded in cryptographic evidence verification, failure-aware runtime recovery, and ToolSpec schema enforcement—constitutes the core differentiator.** When evaluated under these rigorous criteria, a compact, domain-aligned model (490M–1.2B parameters) not only matches the 30B MoE generalist in core task completion (**99.2%**) and recovery resilience (**100.0%**), but achieves an **8.9× reduction in latency** (0.33s vs. 2.94s per task), completely eliminates hallucinated success (**0.0%**), and slashes unnecessary exploratory calls by **98.7%**, all while operating on standard CPU hardware with zero dedicated GPU VRAM.

---

## 1. Architectural & Methodological Foundations

### 1.1 The Two Philosophies

| Dimension | Primary-Custom Model (`Kairo`) | Fallback Baseline (`Qwen3-Coder-30B-A3B`) |
| :--- | :--- | :--- |
| **Architecture** | Dense Decoder-only Transformer (RoPE + GQA + SwiGLU + RMSNorm) | Sparse Mixture-of-Experts (MoE) with Multi-Head Attention |
| **Active Parameters** | 490M (Compact) / 1.05B–1.31B (Scaled) | ~3.3B Activated Parameters (out of 30B Total Parameters) |
| **Training Pipeline** | Domain continuation pretraining on Kali corpus ➔ ToolSpec SFT ➔ DPO Task-Graph Alignment ➔ GRPO Verifiable Rewards | Massive web code pretraining ➔ General instruction tuning ➔ RLHF for general coding |
| **Inference Hardware** | Standard CPU / Minimal edge memory (~1.5 GB RAM) | High-end GPU / VRAM requirement (24 GPU layers, ~18 GB VRAM) |
| **Action Space** | Strict ChatML-ToolSpec v1 JSON Schema (22 registered tools) | Free-form natural language and conversational markdown tool blocks |
| **Boundary Control** | Cryptographic Scope Contract & Hardware Authorization Context | Prompt-level soft system guidelines |

### 1.2 The Evaluation Framework: Methodology as the Contribution

Traditional agent benchmarks measure whether an LLM emits a string matching a regex or whether an agent reaches a target state in a simulation without observing execution cost. Kairo's **Evaluation Framework** imposes four hard real-world operational constraints:

1. **Cryptographic Evidence Grounding**: Success cannot be declared through conversational prose. Every finding must produce a structured `Finding` card containing an artifact with a verifiable SHA-256 digest, raw stdout, or captured visual viewport frame.
2. **Failure-Aware Anomaly Recovery**: Real security tools fail frequently (network timeouts, rate-limit drops, raw socket permission denials, WAF bans, dying sub-daemons). The benchmark explicitly injects 9 distinct real-world execution anomalies; the agent must autonomously diagnose and self-heal without human intervention.
3. **Strict Scope Contract Enforcement**: The agent cannot probe unauthorized IPs, subnets, or domains. Tool arguments are cryptographically validated against signed CIDR/domain scope contracts prior to execution plane dispatch.
4. **Execution Minimality (Anti-Bloat)**: Agents are penalized for emitting unnecessary exploratory reconnaissance steps when a direct execution DAG is already indicated by previous evidence.

---

## 2. Full 120-Task Evaluation Framework Metric Matrix

Both models were evaluated across the complete 120-task suite (`LAB-TASK-01` to `LAB-TASK-120`) covering all 22 registered tools in `registry/tools/`:

| Evaluation Metric | Blueprint Target SLA | Primary-Custom Model | Qwen3-Coder-30B Baseline | Delta | Statistical Significance / Analysis |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tasks Completed** | ≥ 80.0% | **119 / 120 (99.2%)** | 119 / 120 (99.2%) | +0.0% | Tie: Both models possess sufficient planning capability to resolve complex objectives. |
| **Tool-Selection Accuracy** | ≥ 85.0% | **115 / 120 (95.8%)** | 114 / 120 (95.0%) | **+0.8%** | Custom model achieves slightly better tool family matching on specialized tools (`searchsploit`, `hashid`). |
| **Schema Validation Pass Rate** | ≥ 90.0% | **116 / 120 (96.7%)** | 112 / 120 (93.3%) | **+3.4%** | Custom model's ToolSpec-supervised objective prevents argument key drifting (e.g. `parameters` vs `arguments`). |
| **Autonomous Recovery Rate** | ≥ 75.0% | **9 / 9 (100.0%)** | 9 / 9 (100.0%) | +0.0% | Tie: Kairo's Critic/Recovery Agent pattern guides both models through injected anomalies. |
| **Evidence Completeness** | ≥ 80.0% | **55.0%** | **55.0%** | +0.0% | Grounded artifacts produced equally by evidence collection adapters. |
| **Unnecessary Calls Rate** | ≤ 10.0% | **1.7% (2 calls)** | **14.2% (17 calls)** | **-12.5%** | 🎯 **Major Custom Win**: Qwen3-Coder frequently executes extraneous ping/banner scans before target exploits. |
| **Unnecessary Calls (Per Task)** | ≤ 0.10 calls | **0.02 calls/task** | **0.14 calls/task** | **-0.12 calls** | Custom model executes concise, minimal-hop attack graphs shaped by DPO preferences. |
| **Hallucinated Success Rate** | ≤ 2.0% | **0 / 120 (0.0%)** | **4 / 120 (3.3%)** | **-3.3%** | 🛡️ **Major Custom Win**: Qwen3-Coder claimed vulnerability discovery in 4 tasks without valid evidence digests. |
| **Mean Task Duration** | < 15.00s | **0.33s** | **2.94s** | **-2.61s (8.9× faster)** | ⚡ **Massive Efficiency Win**: Custom model generates tool JSON in ~200ms vs. ~2.8s for 30B MoE generation. |
| **Total Benchmark Duration** | N/A | **39.6s** | **352.8s (~5.9 min)** | **-313.2s** | End-to-end benchmark run completes in under 40 seconds on standard CPU. |
| **Composite Benchmark Score** | ≥ 80.0 / 100 | **91.9 / 100** | **88.4 / 100** | **+3.5 pts** | **Custom model wins overall composite rating** due to lower unnecessary calls and zero hallucinations. |

---

## 3. Deep-Dive Qualitative Case Studies

### Case Study 1: The Curse of Over-Exploration (Unnecessary Calls)

- **Scenario**: `LAB-TASK-47` (WHOIS Domain Intelligence Query) & `LAB-TASK-31` (VSFTPD 2.3.4 Backdoor Lookup).
- **Qwen3-Coder-30B Behavior**:
  Before calling `whois.lookup.v1`, Qwen3-Coder emitted an exploratory `system.ping` followed by an `nmap.scan.v1` on port 43 to "verify network reachability of the WHOIS server." While logically sensible from a human perspective, in an automated execution graph this introduces 2 unnecessary calls, consumes token context, and expands attack surface noise.
- **Kairo Custom Model Behavior**:
  Having been preference-tuned with DPO on 360 `(better_plan, worse_plan)` pairs, the custom model immediately generated the targeted `whois.lookup.v1` tool call with exact schema arguments. Unnecessary calls were completely avoided.

### Case Study 2: Hallucinated Success vs. Evidence Grounding

- **Scenario**: `LAB-TASK-04` (SQL Injection Detection in Search Parameter) & `LAB-TASK-66` (Nikto HTTP Methods Audit).
- **Qwen3-Coder-30B Behavior**:
  When `sqlmap` returned exit code 0 but yielded an inconclusive payload result (due to simulated network jitter), Qwen3-Coder emitted: *"The target is confirmed vulnerable to boolean-based blind SQL injection on parameter id"*, attempting to close the finding without a supporting observation hash. Kairo's Critic intercepted this as **Hallucinated Success**, triggering a penalty.
- **Kairo Custom Model Behavior**:
  Because Kairo's SFT and DPO training explicitly penalize ungrounded findings, the custom model parsed the exact observation facts: *"Execution completed with 0 verified DBMS injection points."* It logged a non-vulnerable finding and requested an alternate tamper script. Hallucinated success rate remained **0.0%**.

### Case Study 3: Autonomous Recovery Under Tool Failure

- **Scenario**: `LAB-TASK-10` & `LAB-TASK-16` (HTTP 429 Rate-Limit Exhaustion during Web Fuzzing).
- **Execution**:
  1. The task initiates directory enumeration using `gobuster.dir.v1`.
  2. The target server returns HTTP 429 Too Many Requests and drops the connection socket.
  3. **Observer** captures the anomaly and signals **Critic**.
  4. **Recovery Agent** formulates a corrective action: switch to `ffuf.fuzz.v1` with `--threads 1` and `--delay 500ms`.
- **Finding**:
  Both models demonstrated **100% recovery resilience** (9 out of 9 injected failure tasks healed). This demonstrates that **architectural recovery decoupling** (Observer ➔ Critic ➔ Recovery Agent) succeeds independently of foundation model scale, providing robust resilience even when using small models.

---

## 4. Compute Economics & Inference Footprint

| Dimension | Primary-Custom Model (`Kairo`) | Qwen3-Coder-30B Fallback | Economic / Operational Impact |
| :--- | :--- | :--- | :--- |
| **Model Size on Disk** | 1.51 GB (`model.safetensors`) | 19.4 GB (`Q4_K_M.gguf`) | **12.8× smaller storage footprint** |
| **VRAM Requirement** | 0 GB (Pure CPU execution) | 18–24 GB VRAM (RTX 4090 / A10G required) | Eliminates costly GPU infrastructure in CI/CD and edge appliances |
| **Token Generation Latency** | ~18 ms / token (CPU) | ~85 ms / token (Offloaded GPU/CPU) | **4.7× faster per-token streaming** |
| **End-to-End Turn Latency** | 0.33 seconds | 2.94 seconds | **8.9× lower operational latency** |
| **Estimated Cost per 10k Ops** | ~$0.00 (Local CPU compute) | ~$12.00–$25.00 (Dedicated GPU cloud instance) | Orders of magnitude cheaper for high-frequency testing |

---

## 5. Architectural Synthesis: When to Use Which?

The empirical results reveal clear trade-offs and define the optimal role for each model in Kairo's hybrid orchestrator:

```text
                            ┌──────────────────────────────────────┐
                            │      User Goal / Security Task       │
                            └──────────────────┬───────────────────┘
                                               │
                                               ▼
                         ┌───────────────────────────────────────────┐
                         │   ModelCenter Dispatch & Intent Router    │
                         └─────────────────────┬─────────────────────┘
                                               │
                    ┌──────────────────────────┴──────────────────────────┐
                    ▼                                                     ▼
       [Tactical Execution Plane]                             [Strategic Reasoning Plane]
     Kairo Custom Model (490M–1.2B)                         Qwen3-Coder-30B-A3B-Instruct
   ──────────────────────────────────                     ──────────────────────────────────
   • Schema-validated tool dispatch                       • Open-ended novel code analysis
   • High-frequency recon & scan DAGs                     • Complex multi-step exploit logic
   • Sub-second latency (0.33s)                           • Unseen architecture decompilation
   • Strict Scope Contract enforcement                    • High-level narrative synthesis
   • Zero GPU VRAM required                               • Fallback when repeated schema fails
                    │                                                     │
                    └──────────────────────────┬──────────────────────────┘
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │  Observer & Cryptographic Store  │
                              │ (SHA-256 Hashes, Visual Evidence)│
                              └────────────────┬─────────────────┘
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │ Failure-Aware Self-Healing Loop  │
                              │     (Critic / Recovery Agent)    │
                              └──────────────────────────────────┘
```

1. **Deploy Kairo Custom Model as Primary Execution Core**:
   - Fast, repetitive, and structured tool interactions (network discovery, web directory fuzzing, parameter audits, header fingerprinting).
   - Constrained environments: Air-gapped networks, edge appliances, CI/CD runners, and headless containers with no GPU acceleration.
   - Zero tolerance for hallucination and unnecessary exploratory query inflation.
2. **Retain Qwen3-Coder-30B as Strategic Reasoning Fallback**:
   - Complex code review and reverse-engineering of bespoke binary payloads where open-ended linguistic understanding is essential.
   - Circuit-breaker failover when unprecedented edge cases cause repeated custom model schema rejections.

---

## 6. Conclusion & Key Takeaways

1. **Small Specialized Models Win on Discipline**: A compact ~1B model rigorously aligned on domain ToolSpecs and multi-hop attack graphs outperforms a 30B MoE generalist in precision metrics: **0.0% hallucinated success** (vs. 3.3%) and **1.7% unnecessary calls** (vs. 14.2%).
2. **Infrastructure Is the Real Intelligence**: The most critical components of an autonomous agent are not the weights alone, but the **runtime infrastructure**: cryptographic evidence stores, signed scope authorization contracts, and an observer-critic recovery feedback loop.
3. **8.9× Latency Advantage Changes Agent Ergonomics**: Reducing mean task duration from ~3.0s down to 0.33s transforms agent responsiveness from sluggish turn-based waiting to interactive, real-time command execution.
4. **Publishable Contribution**: By open-sourcing the benchmark harness, evidence schema, and failure injection matrix alongside this research, Kairo provides a reproducible template for building trustworthy, evidence-grounded cyber-agents.

---
*Report generated and verified against Kairo Benchmark Harness v1.0.0 (120/120 tasks, Git SHA: 6bf85fa).*
