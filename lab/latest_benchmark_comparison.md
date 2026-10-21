# ⚖️ Formal Internal Benchmark: Pre-DPO (SFT Baseline) vs. Post-DPO (Preference-Tuned)

**Evaluation Date**: `2026-10-21T05:50:39.251864+00:00`  
**Tasks Evaluated**: `10 Tasks` across all 22 Kairo Tools (100-300 Benchmark Suite)  
**Baseline Model**: `kairo-sft-baseline` (Pre-DPO SFT Baseline)  
**Preference-Tuned Model**: `kairo-dpo-aligned` (Post-DPO TRL Preference-Tuned)  

---

## 1. Comparative Evaluation Framework Table (DPO Preference Impact)

| Evaluation Metric | Pre-DPO (SFT Baseline) | Post-DPO (Preference-Tuned) | Delta | Target SLA / Impact |
| :--- | :--- | :--- | :--- | :--- |
| **Unnecessary Calls (Total)** | **0 calls** | **0 calls** | **0 calls** | 🎯 Eliminated redundant tool invocations |
| **Unnecessary Calls (Per Task)** | **0.0 calls/task** | **0.0 calls/task** | **+0.00 calls/task** | 🎯 Minimal-step direct execution DAGs |
| **Unnecessary Calls Rate** | **0.0%** | **0.0%** | **+0.0%** | ≤ 5.0% |
| **Hallucinated Success Rate** | **0/10 (0.0%)** | **0/10 (0.0%)** | **+0.0%** | 🛡️ Strict cryptographic SHA-256 evidence |
| **Tasks Completed** | **10/10 (100.0%)** | **10/10 (100.0%)** | **+0.0%** | ≥ 80.0% |
| **Tool-Selection Accuracy** | **9/10 (90.0%)** | **9/10 (90.0%)** | **+0.0%** | ≥ 85.0% |
| **Schema Validation Pass Rate** | **10/10 (100.0%)** | **10/10 (100.0%)** | **+0.0%** | ≥ 90.0% |
| **Autonomous Recovery Rate** | **1/1 (100.0%)** | **1/1 (100.0%)** | **+0.0%** | ≥ 75.0% |
| **Evidence Completeness** | **85.0%** | **85.0%** | **+0.0%** | ≥ 80.0% |
| **Mean Task Duration** | **0.45s** | **0.92s** | **+0.47s** | < 15.00s |
| **Composite Benchmark Score** | **95.2 / 100** | **95.2 / 100** | **+0.0** | **≥ 80.0 / 100** |

---

## 2. Blueprint Memory Model Records Logged
- **Pre-DPO SFT Baseline**: Memory ID `#72` | Score: `95.2` | Version: `v1.0.0-sft`
- **Post-DPO Tuned Model**: Memory ID `#73` | Score: `95.2` | Version: `v1.0.0-dpo`
