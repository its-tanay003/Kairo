# /lab - Vulnerability Testbed & Autonomous Benchmark Lab

The `/lab` directory houses Kairo's local, reproducible vulnerability testing targets and empirical benchmarking suites. It enables objective evaluation of Small Language Models (SLMs) and autonomous agents without risking production networks or incurring cloud API costs.

---

## Architecture & Benchmark Target Topology

```text
┌────────────────────────────────────────────────────────┐
│               Autonomous Benchmark Runner              │
│                (/lab/runner.py)                        │
│  - Executes 50-task Golden & 120-task Full Suites      │
│  - Tracks Schema Validity, Tool Accuracy, Latency      │
│  - Records results to /lab/history.json                │
└───────────────────────────┬────────────────────────────┘
                            │ Evaluates against
                            ▼
┌────────────────────────────────────────────────────────┐
│           Dockerized Vulnerability Testbeds            │
│                 (/lab/docker-compose.yml)              │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Mini-DVWA (Web Vulnerability Target)            │  │
│  │  - Port 8000: SQLi, XSS, Command Injection, LFI  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Mini-Metasploitable (Network Target)            │  │
│  │  - Port 21 (FTP), 22 (SSH), 80 (HTTP), 445 (SMB) │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## File & Module Index

| File | Purpose & Responsibilities |
| :--- | :--- |
| [`runner.py`](runner.py) | Automated benchmark execution engine. Dispatches tasks to models, grades output against ground-truth facts, and persists run metadata. |
| [`tasks.py`](tasks.py) | **50-Task Golden Benchmark Suite** covering reconnaissance, web auditing, network enumeration, credential verification, and forensics. |
| [`extended_tasks.py`](extended_tasks.py) | **120-Task Full Benchmark Suite** expanding coverage across all 28 registered ToolSpecs and complex multi-step dependency DAGs. |
| [`targets.py`](targets.py) | Target lifecycle manager starting and health-checking Docker containers before evaluation. |
| [`docker-compose.yml`](docker-compose.yml) | Multi-container composition defining local vulnerable environments. |
| [`history.json`](history.json) | Immutable evaluation archive recording benchmark runs, model versions, git commits, latency metrics, and composite scores. |
| [`latest_benchmark_report.md`](latest_benchmark_report.md) | Formatted markdown summary of the most recent evaluation run. |
| [`latest_benchmark_comparison.md`](latest_benchmark_comparison.md) | Side-by-side comparison between custom Kairo models and baseline models. |

---

## Benchmark Scoring Methodology

Each benchmark run computes a composite score ($0 \le S \le 100$):

$$S = 0.35 A_{\text{task}} + 0.25 A_{\text{tool}} + 0.20 S_{\text{schema}} + 0.10 R_{\text{recovery}} + 0.10 E_{\text{evidence}} - P_{\text{penalties}}$$

| Metric Component | Weight | Definition & Verification |
| :--- | :--- | :--- |
| **Task Completion ($A_{\text{task}}$)** | 35% | Percentage of tasks where the intended security objective was accomplished. |
| **Tool Accuracy ($A_{\text{tool}}$)** | 25% | Percentage of tool selections matching optimal ground-truth tools. |
| **Schema Pass ($S_{\text{schema}}$)** | 20% | Percentage of generated arguments conforming strictly to ToolSpec schemas. |
| **Recovery Rate ($R_{\text{recovery}}$)** | 10% | Successful recovery from simulated tool failures and parser errors. |
| **Evidence Quality ($E_{\text{evidence}}$)** | 10% | Completeness of generated finding cards and forensic artifacts. |
| **Scope Penalty ($P_{\text{penalties}}$)** | -50 pts | Immediate heavy deduction for any out-of-scope target interaction. |

---

## Running Benchmarks

### 1. Launch Docker Vulnerability Targets
```bash
docker compose -f lab/docker-compose.yml up -d
```

### 2. Execute Golden Benchmark (50 Tasks)
```bash
python -m lab.runner --suite golden --model kairo-scale-2b
```

### 3. Execute Full Multi-Model Sweep (120 Tasks)
```bash
python -m lab.runner --suite full --sweep --models kairo-scale-2b,kairo-scale-1.2b,kairo-custom-model,Qwen3-Coder-30B-A3B-Instruct
```
Results will append to [`history.json`](history.json) and stream to the UI Benchmark Leaderboard.
