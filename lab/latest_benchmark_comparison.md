# ⚖️ Formal Internal Benchmark: Pre-DPO (SFT Baseline) vs. Post-DPO (Preference-Tuned)

**Evaluation Date**: `2026-10-05T17:00:19.718436+00:00`  
**Tasks Evaluated**: `10 Tasks` across all 22 Kairo Tools (100-300 Benchmark Suite)  
**Baseline Model**: `kairo-sft-baseline` (Pre-DPO SFT Baseline)  
**Preference-Tuned Model**: `kairo-dpo-aligned` (Post-DPO TRL Preference-Tuned)  

---

## 1. Comparative Evaluation Framework Table (DPO Preference Impact)

| Evaluation Metric | Pre-DPO (SFT Baseline) | Post-DPO (Preference-Tuned) | Delta | Target SLA / Impact |
| :--- | :--- | :--- | :--- | :--- |
| **Unnecessary Calls (Total)** | **22 calls** | **0 calls** | **-22 calls** | 🎯 Eliminated redundant tool invocations |
| **Unnecessary Calls (Per Task)** | **2.2 calls/task** | **0.0 calls/task** | **-2.20 calls/task** | 🎯 Minimal-step direct execution DAGs |
| **Unnecessary Calls Rate** | **90.0%** | **0.0%** | **-90.0%** | ≤ 5.0% |
| **Hallucinated Success Rate** | **2/10 (20.0%)** | **0/10 (0.0%)** | **-20.0%** | 🛡️ Strict cryptographic SHA-256 evidence |
| **Tasks Completed** | **8/10 (80.0%)** | **10/10 (100.0%)** | **+20.0%** | ≥ 80.0% |
| **Tool-Selection Accuracy** | **10/10 (100.0%)** | **10/10 (100.0%)** | **+0.0%** | ≥ 85.0% |
| **Schema Validation Pass Rate** | **10/10 (100.0%)** | **10/10 (100.0%)** | **+0.0%** | ≥ 90.0% |
| **Autonomous Recovery Rate** | **1/1 (100.0%)** | **1/1 (100.0%)** | **+0.0%** | ≥ 75.0% |
| **Evidence Completeness** | **72.0%** | **88.0%** | **+16.0%** | ≥ 80.0% |
| **Mean Task Duration** | **1.01s** | **0.43s** | **-0.58s** | < 15.00s |
| **Composite Benchmark Score** | **88.8 / 100** | **98.2 / 100** | **+9.4** | **≥ 80.0 / 100** |

---

## 2. Blueprint Memory Model Records Logged
- **Pre-DPO SFT Baseline**: Memory ID `#11` | Score: `88.8` | Version: `v1.0.0-sft`
- **Post-DPO Tuned Model**: Memory ID `#12` | Score: `98.2` | Version: `v1.0.0-dpo`
