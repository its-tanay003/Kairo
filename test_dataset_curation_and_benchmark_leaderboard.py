"""
Integration Tests for Dataset Curation, Training Pipeline (SFT / DPO),
and Public Benchmark Leaderboard (Task 2.7 Golden & Task 6.2 Full).
"""

import json
import os
import tempfile
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from orchestrator.server import app
from orchestrator.training_manager import TrainingManager, training_manager
from orchestrator.benchmark_manager import BenchmarkManager, benchmark_manager


@pytest.fixture
def client():
    """FastAPI TestClient for Orchestrator server routes."""
    return TestClient(app)


# ==============================================================================
# 1. DATASET STATS & CURATION TESTS
# ==============================================================================

def test_dataset_stats_retrieval():
    """Verifies that dataset aggregate stats return counts, tier breakdown, and cleaning metadata."""
    stats = training_manager.get_dataset_stats()

    assert isinstance(stats, dict)
    assert stats["total_examples"] >= 2000
    assert stats["train_examples"] > 0
    assert stats["val_examples"] > 0
    assert stats["preference_pairs_count"] >= 300
    assert stats["validation_pass_rate_pct"] >= 90.0
    assert stats["recovery_examples_count"] > 0

    # Verify distributions
    assert "tier_distribution" in stats
    assert "tool_distribution" in stats
    assert "category_distribution" in stats
    assert "curation_counts" in stats

    # Verify curation counts structure
    curation = stats["curation_counts"]
    assert "approved" in curation
    assert "flagged" in curation
    assert "pruned" in curation


def test_dataset_examples_sft_listing_and_filtering():
    """Verifies querying SFT trajectories with search, tier, and pagination parameters."""
    res = training_manager.list_examples(
        dataset_type="sft",
        limit=10,
        offset=0,
    )

    assert isinstance(res, dict)
    assert "items" in res
    assert "total" in res
    assert len(res["items"]) <= 10
    assert res["total"] > 0

    if res["items"]:
        first = res["items"][0]
        assert "id" in first
        assert "type" in first
        assert "conversation" in first
        assert "user_goal" in first
        assert "curation_status" in first

    # Test filtering by tier
    filtered_tier = training_manager.list_examples(
        dataset_type="sft",
        tier=1,
        limit=5,
    )
    for item in filtered_tier.get("items", []):
        assert item.get("tier") == 1

    # Test search query
    searched = training_manager.list_examples(
        dataset_type="sft",
        query="nmap",
        limit=5,
    )
    assert "items" in searched


def test_dataset_examples_dpo_listing_and_filtering():
    """Verifies querying DPO preference pairs (chosen vs rejected)."""
    res = training_manager.list_examples(
        dataset_type="preference",
        limit=10,
        offset=0,
    )

    assert isinstance(res, dict)
    assert "items" in res
    assert "total" in res
    assert len(res["items"]) <= 10

    if res["items"]:
        first = res["items"][0]
        assert "id" in first
        assert first["type"] == "preference_pair"
        assert "prompt" in first
        assert "chosen_summary" in first
        assert "rejected_summary" in first
        assert "curation_status" in first


def test_curate_example_lifecycle():
    """Verifies setting curation decisions (approved, flagged, pruned) and reading them back."""
    sample_id = "test_sample_eval_001"

    # 1. Mark as approved
    res_app = training_manager.curate_example(
        example_id=sample_id,
        status="approved",
        notes="High quality multi-turn escalation trajectory",
        operator="lead_security_evaluator",
    )
    assert res_app["status"] == "approved"
    assert res_app["notes"] == "High quality multi-turn escalation trajectory"

    # 2. Change status to flagged
    res_flag = training_manager.curate_example(
        example_id=sample_id,
        status="flagged",
        notes="Requires review on scope boundary compliance",
        operator="lead_security_evaluator",
    )
    assert res_flag["status"] == "flagged"

    # 3. Mark as pruned
    res_pruned = training_manager.curate_example(
        example_id=sample_id,
        status="pruned",
        notes="Pruned due to outdated schema",
        operator="lead_security_evaluator",
    )
    assert res_pruned["status"] == "pruned"

    # Check that curation state is reflected in stats
    stats = training_manager.get_dataset_stats()
    assert stats["curation_counts"]["total_curated"] >= 1


def test_schema_cleaning_filter():
    """Tests executing schema validation cleaner to filter malformed samples."""
    clean_report = training_manager.run_cleaning_filter(min_reward=0.7)

    assert isinstance(clean_report, dict)
    assert clean_report["status"] == "cleaned"
    assert "input_count" in clean_report
    assert "valid_count" in clean_report
    assert "pruned_count" in clean_report
    assert "schema_pass_rate_pct" in clean_report
    assert clean_report["valid_count"] > 0
    assert clean_report["schema_pass_rate_pct"] >= 80.0


# ==============================================================================
# 2. TRAINING JOB LIFECYCLE TESTS
# ==============================================================================

def test_training_job_dispatch_and_execution():
    """Tests starting an asynchronous training job, inspecting steps, and monitoring completion."""
    job = training_manager.start_training_job(
        job_type="sft",
        preset="quick_test",
        epochs=1,
        learning_rate=2e-5,
        batch_size=2,
        use_cleaned=True,
        max_steps=4,
    )

    assert isinstance(job, dict)
    job_id = job["id"]
    assert job["job_type"] == "sft"
    assert job["status"] in ("running", "completed")

    # Wait briefly for thread execution
    time.sleep(1.2)

    polled = training_manager.get_training_job(job_id)
    assert polled is not None
    assert polled["id"] == job_id
    assert polled["total_steps"] == 4
    assert polled["current_step"] >= 1
    assert len(polled["logs"]) > 0

    # Retrieve all jobs
    all_jobs = training_manager.get_training_jobs()
    assert any(j["id"] == job_id for j in all_jobs)


def test_stop_training_job():
    """Tests stopping an active training run."""
    job = training_manager.start_training_job(
        job_type="dpo",
        preset="deep_alignment",
        epochs=3,
        learning_rate=1e-5,
        batch_size=4,
        max_steps=50,
    )
    job_id = job["id"]

    # Terminate the job
    stopped = training_manager.stop_training_job(job_id)
    assert stopped is True

    polled = training_manager.get_training_job(job_id)
    assert polled["status"] in ("stopped", "cancelled", "completed")


def test_list_checkpoints():
    """Tests scanning available checkpoints."""
    checkpoints = training_manager.list_checkpoints()
    assert isinstance(checkpoints, list)
    assert len(checkpoints) >= 1

    first_cp = checkpoints[0]
    assert "name" in first_cp
    assert "path" in first_cp
    assert "stage" in first_cp


# ==============================================================================
# 3. BENCHMARK LEADERBOARD & COMPARATIVE EVALUATION TESTS
# ==============================================================================

def test_benchmark_leaderboard_data():
    """
    Verifies that the benchmark leaderboard properly exposes:
    1. Golden Benchmark (Task 2.7, 50 tasks)
    2. Full Benchmark (Task 6.2, 120 tasks)
    3. Competitor baselines (PentAGI, Strix, CAI, Llama-3-8B)
    4. Model progression timeline
    5. Capability matrix
    """
    data = benchmark_manager.get_leaderboard_data()

    assert isinstance(data, dict)
    assert "golden_benchmark" in data
    assert "full_benchmark" in data
    assert "competitor_matrix" in data
    assert "progression_timeline" in data
    assert "category_matrix" in data
    assert "verification_card" in data

    # Check Golden Benchmark (Task 2.7)
    golden = data["golden_benchmark"]
    assert golden["task_count"] == 50
    assert golden["latest_run"] is not None
    assert golden["latest_run"]["composite_score"] >= 90.0

    # Check Full Benchmark (Task 6.2)
    full = data["full_benchmark"]
    assert full["task_count"] == 120
    assert full["latest_run"] is not None
    assert full["latest_run"]["composite_score"] >= 90.0

    # Check Progression Timeline
    timeline = data["progression_timeline"]
    assert len(timeline) >= 4
    stages = [s["stage"] for s in timeline]
    assert "Kairo-Base-380M" in stages
    assert "Kairo-SFT-1B" in stages
    assert "Kairo-DPO-1B" in stages
    assert "Kairo-GRPO-1.5B" in stages


def test_competitor_comparison_validity():
    """
    Validates empirical safety claims against PentAGI, Strix, and CAI:
    - 0% scope violations (vs 18-22% in ungrounded models)
    - 0% hallucinated tools
    - 100% schema compliance
    - $0.00 local inference cost
    """
    data = benchmark_manager.get_leaderboard_data()
    matrix = data["competitor_matrix"]

    kairo_grpo = next(m for m in matrix if m["model_id"] == "kairo-grpo-1.5b")
    pentagi = next(m for m in matrix if "pentagi" in m["model_id"])
    strix = next(m for m in matrix if "strix" in m["model_id"])
    cai = next(m for m in matrix if "cai" in m["model_id"])

    # Scope violations: Kairo must be 0% due to HMAC-signed CIDR contracts
    assert kairo_grpo["scope_violations_pct"] == 0.0
    assert pentagi["scope_violations_pct"] > 10.0
    assert strix["scope_violations_pct"] > 10.0
    assert cai["scope_violations_pct"] > 10.0

    # Hallucinated tools: Kairo must be 0%
    assert kairo_grpo["hallucinated_success_pct"] == 0.0
    assert pentagi["hallucinated_success_pct"] > 0.0

    # Cost: Kairo local weights must be $0.00
    assert kairo_grpo["cost_per_100_runs_usd"] == 0.00
    assert pentagi["cost_per_100_runs_usd"] > 10.00

    # Latency: Sub-second for Kairo
    assert kairo_grpo["mean_duration_s"] < 1.0


def test_trigger_and_retrieve_benchmark_run():
    """Tests triggering an on-demand benchmark evaluation and retrieving run details."""
    res = benchmark_manager.trigger_benchmark_run(
        benchmark_type="golden",
        model_id="kairo-dpo-1b",
        eval_mode="post-dpo",
    )
    assert res["success"] is True
    run_info = res["run"]
    run_id = run_info["run_id"]
    assert run_info["total_tasks"] == 50
    assert run_info["composite_score"] >= 90.0

    # Retrieve specific details
    fetched = benchmark_manager.get_run_details(run_id)
    assert fetched is not None
    assert fetched["run_id"] == run_id
    assert fetched["total_tasks"] == 50


def test_public_verification_card():
    """Verifies that the cryptographic proof card generates a valid SHA-256 digest and reproducibility command."""
    card = benchmark_manager.get_public_verification_card()

    assert isinstance(card, dict)
    assert "verification_sha256" in card
    assert len(card["verification_sha256"]) == 64  # Valid hex digest
    assert "reproducibility_command" in card
    assert "docker compose" in card["reproducibility_command"]
    assert "git_commit" in card
    assert "eval_transparency_charter" in card


# ==============================================================================
# 4. FASTAPI ORCHESTRATOR REST ENDPOINT TESTS
# ==============================================================================

def test_api_training_dataset_stats(client):
    """GET /training/dataset/stats returns 200 with dataset statistics."""
    resp = client.get("/training/dataset/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_examples" in data
    assert "preference_pairs_count" in data


def test_api_training_dataset_examples(client):
    """GET /training/dataset/examples returns paginated examples for SFT and DPO."""
    # SFT
    resp_sft = client.get("/training/dataset/examples?dataset_type=sft&limit=5")
    assert resp_sft.status_code == 200
    data_sft = resp_sft.json()
    assert "items" in data_sft

    # DPO
    resp_dpo = client.get("/training/dataset/examples?dataset_type=preference&limit=5")
    assert resp_dpo.status_code == 200
    data_dpo = resp_dpo.json()
    assert "items" in data_dpo


def test_api_training_curate_example(client):
    """POST /training/dataset/curate applies decision."""
    payload = {
        "example_id": "api_test_sample_01",
        "status": "approved",
        "notes": "Verified tool syntax and parameter boundaries",
        "operator": "automated_test_suite",
    }
    resp = client.post("/training/dataset/curate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["operator"] == "automated_test_suite"


def test_api_training_clean(client):
    """POST /training/dataset/clean runs cleaning filter."""
    payload = {"min_reward": 0.8}
    resp = client.post("/training/dataset/clean", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cleaned"
    assert "valid_count" in data


def test_api_training_jobs_flow(client):
    """Tests POST /training/jobs/start, GET /training/jobs, and GET /training/jobs/{job_id}."""
    start_payload = {
        "job_type": "sft",
        "preset": "smoke_test",
        "epochs": 1,
        "learning_rate": 1e-4,
        "batch_size": 1,
        "use_cleaned": True,
        "max_steps": 3,
    }
    resp_start = client.post("/training/jobs/start", json=start_payload)
    assert resp_start.status_code == 200
    start_data = resp_start.json()
    assert start_data["status"] == "started"
    job_id = start_data["job"]["id"]

    # Poll status
    resp_status = client.get(f"/training/jobs/{job_id}")
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert status_data["job"]["id"] == job_id

    # List all jobs
    resp_list = client.get("/training/jobs")
    assert resp_list.status_code == 200
    assert any(j["id"] == job_id for j in resp_list.json()["jobs"])


def test_api_training_checkpoints(client):
    """GET /training/checkpoints returns checkpoint directory contents."""
    resp = client.get("/training/checkpoints")
    assert resp.status_code == 200
    data = resp.json()
    assert "checkpoints" in data
    assert isinstance(data["checkpoints"], list)


def test_api_benchmark_leaderboard(client):
    """GET /benchmark/leaderboard returns full comparison datasets."""
    resp = client.get("/benchmark/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "golden_benchmark" in data
    assert "full_benchmark" in data
    assert "competitor_matrix" in data


def test_api_benchmark_public_card(client):
    """GET /benchmark/public-card returns cryptographic verification digest."""
    resp = client.get("/benchmark/public-card")
    assert resp.status_code == 200
    data = resp.json()
    assert "verification_sha256" in data
    assert "reproducibility_command" in data


def test_api_benchmark_trigger_and_get_run(client):
    """POST /benchmark/run and GET /benchmark/runs/{run_id}."""
    payload = {
        "benchmark_type": "golden",
        "model_id": "kairo-dpo-1b",
        "eval_mode": "post-dpo",
    }
    resp_run = client.post("/benchmark/run", json=payload)
    assert resp_run.status_code == 200
    run_data = resp_run.json()
    assert run_data["success"] is True
    run_id = run_data["run"]["run_id"]

    # Fetch run details
    resp_details = client.get(f"/benchmark/runs/{run_id}")
    assert resp_details.status_code == 200
    assert resp_details.json()["run"]["run_id"] == run_id
