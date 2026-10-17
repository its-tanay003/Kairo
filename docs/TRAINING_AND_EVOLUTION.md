# KAIRO: Autonomous Model Training & Evolution Architecture

> **Authoritative Specification for Continuous Self-Improvement, Scale Stages & RL Alignment**  
> **Target Release**: KAIRO v4.0.0

---

## 1. Overview & Evolutionary Vision

Unlike static agent frameworks that rely solely on external proprietary LLM APIs, Kairo is powered by a **self-evolving, local-first Small Language Model (SLM) fleet**. The system continuously monitors its own real-world operational performance in `/events/events.db`, identifies accuracy plateaus or schema failures, synthesizes high-quality training pairs, and autonomously triggers model fine-tuning, evaluation, and hot-swapped deployment.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   Real Operational Engagements                         │
│  - Operator prompts, tool dispatches, exit codes, output parses        │
│  - Recorded to immutable 20-field SQLite /events/events.db             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Model Evolution Controller (Background Daemon)           │
│  - Evaluates rules every 60s against orchestrator/evolution_policy.yaml│
│  - Rule 1: Trigger SFT refresh when >= 50 new validated traces exist   │
│  - Rule 2: Scale parameter tier if accuracy plateaus for 3 cycles      │
│  - Rule 3: Rollback checkpoint if benchmark score regresses by > 2.5%  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Multi-Stage Model Training & Alignment                   │
│                                                                        │
│  1. Pretraining (pretrain.py)                                          │
│     - Domain corpus (security_corpus.txt, manpages, exploit guides)    │
│     - Custom Transformer (RMSNorm + RoPE + GQA + SwiGLU)               │
│                                                                        │
│  2. Supervised Fine-Tuning (trl_sft.py)                                │
│     - Multi-turn tool calling, XML thought tagging, schema filters     │
│                                                                        │
│  3. Direct Preference Optimization (dpo.py)                            │
│     - Safe vs Over-scoped target selection preference pairs            │
│                                                                        │
│  4. Group Relative Policy Optimization (grpo.py)                       │
│     - Verifiable reward signals (Schema pass, Zero CIDR violations)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Automated Benchmark Gate & Hot-Swapping                  │
│  - Runs 50-task Golden benchmark via /lab/runner.py                    │
│  - Requires Composite Score >= incumbent + 1.0                         │
│  - Atomic model switch via Orchestrator /api/models/switch             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Scale Stages & Parameter Hierarchy

Configured in [`models.yaml`](../models.yaml):

| Model Preset | Parameter Count | Layers | Hidden Dim | KV Heads | Context | Hardware Target | Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `Kairo-Base-380M` | 380 Million | 16 | 1024 | 4 | 4,096 | CPU / 4GB RAM | Edge triage, air-gapped field laptops |
| `kairo-custom-model` | 490 Million | 20 | 1280 | 4 | 8,192 | 8GB RAM / Metal | Fast tool selector, schema argument linter |
| `kairo-scale-700m` | 720 Million | 24 | 1536 | 6 | 8,192 | 12GB RAM / 6GB VRAM | Balanced DAG task decomposition |
| `kairo-scale-1.2b` | 1.18 Billion | 24 | 2048 | 8 | 8,192 | 16GB RAM / 8GB VRAM | Advanced penetration reasoning |
| `kairo-scale-2b` | 1.98 Billion | 32 | 2560 | 8 | 16,384 | 32GB RAM / 12GB VRAM | Flagship autonomous cyber defense model |

---

## 3. Autonomous Evolution Policy (`evolution_policy.yaml`)

The evolution controller evaluates deterministic policy rules configured in [`orchestrator/evolution_policy.yaml`](../orchestrator/evolution_policy.yaml):

```yaml
evolution_policy:
  evaluation_interval_seconds: 60
  min_new_events_for_sft: 50
  accuracy_plateau_threshold: 0.92
  plateau_cycles_before_scaling: 3
  regression_tolerance_pct: 2.5
  benchmark_suite: golden
  auto_deploy_approved: false
```

### Policy Execution Rules
1. **Rule 1 (Continuous SFT Refresh)**: When the event store records $\ge 50$ newly curated, verified execution traces, an incremental SFT job is spawned asynchronously.
2. **Rule 2 (Capacity Tier Scaling)**: If a model's benchmark accuracy stays within $\pm 0.5\%$ across 3 consecutive training cycles without reaching the target $95\%$ threshold, the controller automatically scales up to the next parameter tier (e.g., 700M $\to$ 1.2B $\to$ 2B).
3. **Rule 3 (Automated Safety Rollback)**: If a newly trained candidate scores more than $2.5\%$ lower on the benchmark suite than the incumbent model, the proposal is automatically rejected, and the system reverts to the stable baseline checkpoint.

---

## 4. Reinforcement Learning with Verifiable Rewards (GRPO)

Kairo avoids subjective reward models by using **verifiable mathematical reward signals** implemented in [`training/schema_reward.py`](../training/schema_reward.py):

```python
def compute_grpo_reward(candidate_output: str, task_context: dict) -> float:
    reward = 0.0
    
    # 1. Structural Schema Reward (+1.0 / -1.0)
    if is_valid_tool_call_json(candidate_output):
        reward += 1.0
    else:
        reward -= 1.0
        
    # 2. Registry Membership Reward (+1.0 / -1.5)
    tool_id = extract_tool_id(candidate_output)
    if tool_registry.has(tool_id):
        reward += 1.0
    else:
        reward -= 1.5  # Heavy penalty for hallucinated tools
        
    # 3. Scope Boundary Reward (+1.0 / -3.0)
    target = extract_target_argument(candidate_output)
    if is_target_in_cidr_scope(target, task_context["allowed_cidr"]):
        reward += 1.0
    else:
        reward -= 3.0  # Immediate critical penalty for out-of-scope targets
        
    # 4. Task Goal Reward (+2.0 / -0.5)
    if task_objective_satisfied(candidate_output, task_context["ground_truth"]):
        reward += 2.0
    else:
        reward -= 0.5
        
    return reward
```

---

## 5. UI Model Evolution & Curation Panel

The frontend exposes the entire evolution lifecycle at `/benchmark/leaderboard` and via the **Model Evolution Panel**:
- **Dataset Curation**: Operators can view raw SFT and DPO examples, inspect schema cleaning reports, and flag high-value or edge-case trajectories.
- **Active Proposals**: Review pending training job proposals, parameter sizing, benchmark gains, and click `Approve & Deploy` or `Dismiss`.
- **Chronological Run Telemetry**: Real-time loss curves, learning rate progression, and benchmark comparison charts.
