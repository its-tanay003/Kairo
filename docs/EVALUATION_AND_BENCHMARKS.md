# KAIRO: Evaluation Framework & Multi-Model Benchmark Guide

> **Vulnerability Verification Benchmarks, Scoring Rubrics, & Model Leaderboard**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Evaluation Architecture & Methodology](#1-evaluation-architecture--methodology)
2. [Benchmark Suites: Golden (50-Task) & Full (120-Task)](#2-benchmark-suites-golden-50-task--full-120-task)
3. [The 5 Scoring Dimensions](#3-the-5-scoring-dimensions)
4. [Running Automated Benchmarks via CLI](#4-running-automated-benchmarks-via-cli)
5. [Public Leaderboard & Model Score History](#5-public-leaderboard--model-score-history)
6. [Comparative Research: Custom SFT vs Foundation Fallback](#6-comparative-research-custom-sft-vs-foundation-fallback)

---

## 1. Evaluation Architecture & Methodology

Evaluating autonomous cybersecurity models requires rigorous, verifiable grading beyond standard language benchmarks. Models must not merely "talk" about security; they must formulate correct ToolSpec arguments, respect strict CIDR boundaries, decompose complex multi-stage attacks into valid DAGs, and recover gracefully when tools fail.

KAIRO's evaluation pipeline runs against real, containerized targets in [`lab/`](file:///c:/New%20Volume%20(D)/dev/lab), producing verifiable execution logs and cryptographic evidence artifacts.

---

## 2. Benchmark Suites: Golden (50-Task) & Full (120-Task)

### 2.1 50-Task Golden Benchmark (`lab/golden_benchmark.json`)
A curated, high-precision test suite designed for continuous integration (CI):
- **Reconnaissance (15 Tasks)**: Subnet discovery, port filtering, DNS records, banner grabs.
- **Web Assessment (15 Tasks)**: SQL injection detection, XSS verification, directory enumeration.
- **Network & Credential Auditing (10 Tasks)**: Weak SSH keys, anonymous FTP, SMB enumeration.
- **Recovery & Edge Cases (10 Tasks)**: Handling hung sockets, expired scopes, invalid ports.

### 2.2 120-Task Full Benchmark (`lab/full_benchmark.json`)
A comprehensive battery used for pre-release certification and fine-tuning checkpoint grading:
- Covers advanced multi-step lateral movement, authenticated API fuzzing, and cryptographic hash correlation.

---

## 3. The 5 Scoring Dimensions

Each task produces a composite score from `0.00` to `1.00` across 5 automated rubrics:

| Metric | Weight | Description |
| :--- | :--- | :--- |
| **1. Syntax Conformance** | 20% | Strict adherence to JSON / GBNF grammar constraints with zero syntax parsing failures. |
| **2. Argument Validity** | 25% | Pydantic & JSON Schema validation of all parameters against the 16-field ToolSpec. |
| **3. Scope Compliance** | 25% | 100% of generated IP/domain targets are inside the authorized CIDR blocks with zero excluded host interactions. |
| **4. DAG Decomposition** | 15% | Multi-step plans have valid topological ordering, no circular dependencies, and correct root nodes. |
| **5. Recovery Success** | 15% | Autonomous self-healing rate when a simulated tool error or network timeout is injected. |

---

## 4. Running Automated Benchmarks via CLI

Execute the benchmark runner against local model checkpoints or orchestrator endpoints:

```bash
# Run the 50-task Golden Benchmark
python lab/runner.py --suite golden --model kairo-3.7-cyberops

# Run the full 120-task battery with parallel workers
python lab/runner.py --suite full --workers 4 --output lab/history.json
```

---

## 5. Public Leaderboard & Model Score History

The Benchmark Leaderboard in [`ui/src/app/components/BenchmarkLeaderboard.tsx`](file:///c:/New%20Volume%20(D)/dev/ui/src/app/components/BenchmarkLeaderboard.tsx) presents real-time multi-model comparative results:

| Model Version | SFT / Training | Golden Score | Syntax Valid | Scope Pass | Recovery Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Kairo 3.7 (Sonnet Tier)** | SFT + DPO + GRPO | **94.8%** | 99.8% | 100.0% | **92.5%** |
| **Llama-3-70B Pentest SFT** | SFT (LoRA 70B) | **91.2%** | 98.4% | 100.0% | 88.0% |
| **Kairo 1.5B (Edge SFT)** | SFT (2.8k traces) | **86.4%** | 97.2% | 99.2% | 76.0% |
| **Qwen-2.5-Coder-7B (Base)** | Foundation Prompt | **73.5%** | 88.1% | 94.0% | 58.2% |
| **Llama-3-8B (Base)** | Zero-Shot Prompt | **61.0%** | 74.5% | 89.0% | 42.0% |

---

## 6. Comparative Research: Custom SFT vs Foundation Fallback

Detailed research reports are documented in:
- [`docs/research/model_comparison_qwen3_vs_custom.md`](file:///c:/New%20Volume%20(D)/dev/docs/research/model_comparison_qwen3_vs_custom.md)
- [`docs/research/gap_analysis_custom_vs_fallback.md`](file:///c:/New%20Volume%20(D)/dev/docs/research/gap_analysis_custom_vs_fallback.md)

Key findings show that fine-tuning with ToolSpec GBNF grammars increases syntax reliability from **74% to 99.8%**, virtually eliminating hallucinated CLI flags.
