# 🧪 Kairo Benchmark Score Report (Lab v1.0.0)

**Environment**: `Kairo Intentionally Vulnerable Lab v1 (Mini-DVWA / Mini-Metasploitable)`
**Run ID**: `bench_20261004_194911_8dea99` | **Git Commit**: `18ebea6` | **Evaluated At**: `2026-10-04T19:49:17.890160+00:00`
**Overall Status**: **PASS** (99.1 / 100)

---

## 1. Evaluation Framework Metrics Table

| Evaluation Metric | Benchmark Result | Target SLA / Baseline | Status |
| :--- | :--- | :--- | :--- |
| **Tasks Completed** | **10 / 10 (100.0%)** | ≥ 80.0% | ✅ PASS |
| **Tool-Selection Accuracy** | **10 / 10 (100.0%)** | ≥ 85.0% | ✅ PASS |
| **Autonomous Recovery Rate** | **1 / 1 (100.0%)** | ≥ 75.0% | ✅ PASS |
| **Evidence Completeness** | **94.0%** | ≥ 80.0% | ✅ PASS |
| **Mean Task Duration** | **0.63s** (Total: 6.27s) | < 15.00s | ✅ PASS |
| **Composite Benchmark Score** | **99.1 / 100** | ≥ 80.0 / 100 | ✅ PASS |

---

## 2. Per-Task Execution Breakdown

| Task ID | Objective | Expected Tool | Selected Tool | Evidence Class | Recovery | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `LAB-TASK-01` | Network Port & Service Enumeration | `nmap.scan.v1` | `nmap.scan.v1` | `network` | N/A | ✅ PASS |
| `LAB-TASK-02` | Hidden Administrative Directory Discovery | `gobuster.dir.v1` | `ffuf.fuzz.v1` | `network` | N/A | ✅ PASS |
| `LAB-TASK-03` | Web Server Technology & Header Fingerprinting | `whatweb.scan.v1` | `whatweb.scan.v1` | `network` | N/A | ✅ PASS |
| `LAB-TASK-04` | SQL Injection Detection in Search Parameter | `sqlmap.scan.v1` | `sqlmap.scan.v1` | `command` | N/A | ✅ PASS |
| `LAB-TASK-05` | Web Vulnerability & Security Header Audit | `nikto.scan.v1` | `nikto.scan.v1` | `analytic` | N/A | ✅ PASS |
| `LAB-TASK-06` | Known Exploit Database Correlation | `searchsploit.search.v1` | `searchsploit.search.v1` | `analytic` | N/A | ✅ PASS |
| `LAB-TASK-07` | Default Credential Testing & Authentication Audit | `hydra.brute.v1` | `hydra.brute.v1` | `command` | N/A | ✅ PASS |
| `LAB-TASK-08` | Exposed Backup Metadata & Secret Analysis | `exiftool.extract.v1` | `exiftool.extract.v1` | `file` | N/A | ✅ PASS |
| `LAB-TASK-09` | Credential Hash Type Identification | `hashid.identify.v1` | `hashid.identify.v1` | `analytic` | N/A | ✅ PASS |
| `LAB-TASK-10` | Failure-Aware Autonomous Recovery under Rate Throttling | `gobuster.dir.v1` | `gobuster.dir.v1` | `network` | 🛡️ Healed | ✅ PASS |

---

## 3. Failure-Aware Autonomous Recovery Deep-Dive (Task 2.5)

The benchmark includes explicit injection of execution anomalies (Task 10) to verify Kairo's failure-aware resilience:

### `LAB-TASK-10`: Failure-Aware Autonomous Recovery under Rate Throttling
- **Recovery Path Narrative**: `Attempted gobuster (default parameters) -> timed out after 30s -> succeeded.`
- **Autonomous Status**: Successfully recovered from timeout without human intervention.

---

## 4. Benchmark Score Over Time Story

Score history is automatically maintained in [`lab/history.json`](file:///C:/New Volume (D)/dev/lab/history.json) across releases.
Re-run after every major architecture update via:
```bash
python -m lab.runner
```
