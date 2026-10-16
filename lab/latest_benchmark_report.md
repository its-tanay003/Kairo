# 🧪 Kairo Benchmark Score Report (Lab v1.0.0)

**Environment**: `Kairo Intentionally Vulnerable Lab v1 (Mini-DVWA / Mini-Metasploitable)`
**Run ID**: `bench_20261016_185337_e08771` | **Git Commit**: `ebc7dcb` | **Evaluated At**: `2026-10-16T18:53:45.487777+00:00`
**Model**: `kairo-dpo-aligned` (Role: `dpo-aligned`) | **Failover Occurred**: `False`
**Overall Status**: **PASS** (99.1 / 100)

---

## 1. Evaluation Framework Metrics Table

| Evaluation Metric | Benchmark Result | Target SLA / Baseline | Status |
| :--- | :--- | :--- | :--- |
| **Tasks Completed** | **5 / 5 (100.0%)** | ≥ 80.0% | ✅ PASS |
| **Tool-Selection Accuracy** | **5 / 5 (100.0%)** | ≥ 85.0% | ✅ PASS |
| **Schema Validation Pass Rate** | **5 / 5 (100.0%)** | ≥ 90.0% | ✅ PASS |
| **Autonomous Recovery Rate** | **0 / 0 (100.0%)** | ≥ 75.0% | ✅ PASS |
| **Evidence Completeness** | **94.0%** | ≥ 80.0% | ✅ PASS |
| **Unnecessary Calls Rate** | **0.0%** (0 calls, 0.0/task) | ≤ 10.0% | ✅ PASS |
| **Hallucinated Success Rate** | **0 / 5 (0.0%)** | ≤ 2.0% | ✅ PASS |
| **Mean Task Duration** | **0.85s** (Total: 4.24s) | < 15.00s | ✅ PASS |
| **Composite Benchmark Score** | **99.1 / 100** | ≥ 80.0 / 100 | ✅ PASS |

---

## 2. Per-Task Execution Breakdown

| Task ID | Objective | Expected Tool | Selected Tool | Schema | Evidence Class | Recovery | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `LAB-TASK-01` | Network Port & Service Enumeration | `nmap.scan.v1` | `nmap.scan.v1` | ✅ | `network` | N/A | ✅ PASS |
| `LAB-TASK-02` | Hidden Administrative Directory Discovery | `gobuster.dir.v1` | `ffuf.fuzz.v1` | ✅ | `network` | N/A | ✅ PASS |
| `LAB-TASK-03` | Web Server Technology & Header Fingerprinting | `whatweb.scan.v1` | `whatweb.scan.v1` | ✅ | `network` | N/A | ✅ PASS |
| `LAB-TASK-04` | SQL Injection Detection in Search Parameter | `sqlmap.scan.v1` | `sqlmap.scan.v1` | ✅ | `command` | N/A | ✅ PASS |
| `LAB-TASK-05` | Web Vulnerability & Security Header Audit | `nikto.scan.v1` | `nikto.scan.v1` | ✅ | `analytic` | N/A | ✅ PASS |

---

## 3. Failure-Aware Autonomous Recovery Deep-Dive (Task 2.5)

The benchmark includes explicit injection of execution anomalies across multiple tasks to verify Kairo's failure-aware resilience:

---

## 4. Benchmark Score Over Time Story

Score history is automatically maintained in [`lab/history.json`](file:///C:/New Volume (D)/dev/lab/history.json) across releases.
Model memory records are logged to SQLite EventStore (`model_memory` table).
Re-run after every major architecture update via:
```bash
python -m lab.runner --compare-dpo
```
