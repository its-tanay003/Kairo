# KAIRO: Testing & Quality Assurance Architecture

> **Comprehensive Specification for Test Suites, Conformance Gates, Chaos Engineering & QA Protocols**  
> **Target Release**: KAIRO v4.0.0

---

## 1. Testing Philosophy & Guarantees

In autonomous cybersecurity platforms, software bugs and runtime hallucinations can lead to catastrophic side-effects, such as scanning unauthorized corporate networks or triggering unplanned outages. Kairo enforces a **zero-trust testing philosophy** underpinned by:

1. **Deterministic Conformance**: Every tool must pass a 7-gate automated conformance engine before admission to the trusted registry.
2. **Cryptographic Containment**: Cryptographic verification tests ensure no action executes without a valid HMAC-signed Scope Contract.
3. **Hard Fault Boundaries**: Process supervisor and VM limits guarantee that resource-exhaustion, infinite loops, and fork-bombs are killed within predetermined thresholds.
4. **Autonomous Self-Healing**: Recovery and critic tests verify that parser mismatches and tool failures trigger intelligent compensatory actions rather than silent abortion.

---

## 2. Test Architecture & Pytest Harness

The test harness comprises **48 test suites** located in `/tests`, executed via Python's `pytest` framework and Node.js for TypeScript interfaces:

```text
/tests
├── Unit & Schema Tests          # ToolSpec JSON Schema, Tokenizer, Datasets
├── Adapter & Conformance Tests  # 7-Gate verification for Tier 1, 2, and 3 tools
├── Cognitive Engine Tests       # DAG Planner, Observer, Critic, Recovery
├── Security & Isolation Tests   # Scope Contract HMAC, VM Sandboxing, Resource Caps
├── Model & Training Tests       # SFT, DPO, GRPO rewards, Scale stages
├── Multi-Client & Collab Tests  # Project presence, Audit Explorer, WebSocket sync
└── Chaos & Extreme Stress Tests # 100-node DAGs, CIDR fuzzing, network partitions
```

---

## 3. The 7-Gate Conformance Engine (`python -m sdk verify-toolspec`)

Every tool added to Kairo must pass all 7 automated gates:

```mermaid
flowchart LR
    G1[Gate 1: 16-Field Schema] --> G2[Gate 2: Adapter Contract]
    G2 --> G3[Gate 3: Arg Compilation]
    G3 --> G4[Gate 4: Output Determinism]
    G4 --> G5[Gate 5: Fact Normalization]
    G5 --> G6[Gate 6: Scope Compliance]
    G6 --> G7[Gate 7: Operational Limits]
    G7 --> PASS((STATUS: TRUSTED))
```

1. **Gate 1: Blueprint Schema**: Validates all 16 required fields against `registry/schema/toolspec.schema.json`.
2. **Gate 2: Adapter Contract**: Verifies Python adapter inherits from `ToolAdapter` and implements `build_args()` and `parse()`.
3. **Gate 3: Arg Compilation**: Tests parameter coercion, default arguments, and flag injection safety.
4. **Gate 4: Output Determinism**: Ensures parser handles raw output, empty responses, and non-zero exit codes without unhandled exceptions.
5. **Gate 5: Fact Normalization**: Verifies extraction of standard `ObservationFact` entities (open ports, discovered vulnerabilities, hosts).
6. **Gate 6: Scope Compliance**: Verifies that adapter respects target parameters and rejects out-of-scope targets.
7. **Gate 7: Operational Limits**: Enforces timeout $\le 300\text{s}$, explicit rollback declarations, and privilege boundaries.

---

## 4. Chaos Engineering & Extreme User Stress

Kairo includes purpose-built chaos engineering scripts in `/scripts`:

### 1. WebSocket Stream Chaos (`scripts/break_website_chaos.py`)
Simulates hostile network environments:
- **Packet Drop Simulation**: Randomly drops 15% of inbound/outbound WebSocket messages.
- **Malformed Payloads**: Injects corrupted JSON, null fields, and out-of-spec event numbers.
- **Latency Spikes**: Introduces artificial jitter (200ms - 2000ms) to test UI optimism and loader states.

### 2. Extreme Operator Simulation (`scripts/test_extreme_user_simulation.py`)
Simulates erratic human operator behavior:
- Rapid clicking on drawer tabs and action buttons (< 50ms interval).
- Simultaneous prompt submissions across multiple browser tabs.
- Hot-swapping model selectors while tasks are actively executing.
- Rapidly changing Scope Contract parameters during live tool execution.

---

## 5. Running the Master Test Matrix

```bash
# 1. Run all 48 test suites with verbose output
python -m pytest -v

# 2. Run fast unit and schema tests only
python -m pytest tests/test_toolspec_registry.py tests/test_tool_selection.py -v

# 3. Run security and scope authorization tests
python -m pytest tests/test_scope_contract.py tests/test_workspace_and_auth_gateway.py -v

# 4. Run cognitive loop and recovery tests
python -m pytest tests/test_observer_critic_recovery.py tests/test_planner.py -v

# 5. Run model training and reinforcement learning tests
python -m pytest tests/test_grpo_training_and_rewards.py tests/test_scale_stages_pipeline.py -v
```
