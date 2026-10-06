# ⚖️ Formal Internal Benchmark: Custom Model vs. Fallback Baseline

**Evaluation Date**: `2026-10-06T05:50:13.984290+00:00`  
**Tasks Evaluated**: `120 Tasks` across all 22 Kairo Tools (100-300 Benchmark Suite)  
**Custom Model**: `kairo-custom-model` (Role: `primary-custom`)  
**Fallback Baseline**: `Qwen2.5-0.5B-Instruct` (Role: `fallback`)  

---

## 1. Comparative Evaluation Framework Table

| Metric | Primary-Custom Model | Fallback Baseline | Delta | Blueprint Target SLA |
| :--- | :--- | :--- | :--- | :--- |
| **Tasks Completed** | **119/120 (99.2%)** | 119/120 (99.2%) | +0.0% | ≥ 80.0% |
| **Tool-Selection Accuracy** | **115/120 (95.8%)** | 115/120 (95.8%) | +0.0% | ≥ 85.0% |
| **Schema Validation Pass Rate** | **116/120 (96.7%)** | 116/120 (96.7%) | +0.0% | ≥ 90.0% |
| **Autonomous Recovery Rate** | **9/9 (100.0%)** | 9/9 (100.0%) | +0.0% | ≥ 75.0% |
| **Evidence Completeness** | **55.0%** | 55.0% | +0.0% | ≥ 80.0% |
| **Unnecessary Calls Rate** | **1.7%** (2 calls) | 1.7% (2 calls) | +0.0% | ≤ 10.0% |
| **Hallucinated Success Rate** | **0/120 (0.0%)** | 0/120 (0.0%) | +0.0% | ≤ 2.0% |
| **Mean Task Duration** | **0.33s** | 0.29s | +0.04s | < 15.00s |
| **Composite Benchmark Score** | **91.9 / 100** | **91.9 / 100** | **+0.0** | **≥ 80.0 / 100** |

---

## 2. Blueprint Memory Model Records Logged
- **Custom Model**: Memory ID `#13` | Score: `91.9` | Format: `chatml-toolspec-v1`
- **Fallback Model**: Memory ID `#14` | Score: `91.9` | Format: `chatml-toolspec-v1`
