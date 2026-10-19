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
6. [Comparative Research & Verifiable Public Cards](#6-comparative-research--verifiable-public-cards)

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
python -m lab.runner --suite golden --model kairo-scale-2b

# Run the full 120-task battery with multi-model sweep
python -m lab.runner --suite full --sweep --models kairo-scale-2b-grpo,kairo-scale-2b-dpo,kairo-custom-model,Qwen3-Coder-30B-A3B-Instruct
```

---

## 5. Public Leaderboard & Model Score History

The Benchmark Leaderboard in [`ui/src/app/components/BenchmarkLeaderboard.tsx`](file:///c:/New%20Volume%20(D)/dev/ui/src/app/components/BenchmarkLeaderboard.tsx) presents real-time multi-model comparative results from [`lab/history.json`](file:///c:/New%20Volume%20(D)/dev/lab/history.json):

| Model Version | SFT / Training Mode | Tasks Completed | Tool Match % | Schema Pass % | Recovery Rate | Composite Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Kairo-Scale-2B-GRPO (Ours v2)** | Multi-Stage GRPO (Tier C 2B) | **120/120 (100%)** | **99.2%** | **100.0%** | **100.0%** | **98.2 / 100** |
| **Kairo-Scale-2B-DPO (Ours v2)** | Pairwise DPO Aligned | **120/120 (100%)** | 97.5% | 100.0% | 97.5% | **94.8 / 100** |
| **Kairo-Scale-2B-SFT (Ours v2)** | Supervised Fine-Tuned (TRL) | **118/120 (98.3%)** | 96.0% | 98.3% | 92.5% | **93.4 / 100** |
| **Qwen3-Coder-30B-A3B-Instruct** | 30B MoE Foundation Baseline | 114/120 (95.0%) | 92.0% | 93.5% | 90.0% | **88.5 / 100** |
| **Kairo-Custom-490M (Ours)** | 490M Custom Transformer SFT | 115/120 (96.0%) | 94.0% | 95.0% | 88.0% | **86.2 / 100** |
| **Kairo-SFT-Baseline** | Pre-DPO Baseline | 112/120 (94.0%) | 94.2% | 94.0% | 87.5% | **84.6 / 100** |
| **Qwen2.5-0.5B-Instruct** | 0.5B Quantized Fallback | 102/120 (85.0%) | 81.0% | 84.0% | 75.0% | **78.4 / 100** |

---

## 6. Comparative Research & Verifiable Public Cards

Detailed research reports are documented in:

- [`docs/research/model_comparison_qwen3_vs_custom.md`](file:///c:/New%20Volume%20(D)/dev/docs/research/model_comparison_qwen3_vs_custom.md)
- [`docs/research/gap_analysis_custom_vs_fallback.md`](file:///c:/New%20Volume%20(D)/dev/docs/research/gap_analysis_custom_vs_fallback.md)

Key findings show that fine-tuning with ToolSpec GBNF grammars increases syntax reliability from **74% to 100%**, completely eliminating hallucinated CLI flags and out-of-scope subnet scanning.
