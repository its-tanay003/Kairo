"""
Test suite for Kairo Data Pipeline (Task 3.1 - Track B).
Verifies:
1. ToolSpec harvesting and man-page/help documentation synthesis for all 18 tools.
2. Event store extraction into (goal, tool_call, outcome) triples.
3. Counterfactual recovery chain extraction (bad_attempt -> corrected_attempt -> verified_result).
4. SFT conversation format compliance ({user_goal, task_graph, tool_call, observation, next_step}).
5. DatasetValidator schema, conversation turn, and scope boundary checks.
6. End-to-end dataset generation, train/val split, and statistical profiling.
"""

import json
from pathlib import Path

import pytest

from training.harvest import (
    DataHarvestPipeline,
    EventStoreHarvester,
    RecoveryChainHarvester,
    ToolSpecHarvester,
)
from training.pipeline import DatasetValidator, KairoDataPipeline
from training.synthesizer import SFTDataSynthesizer


@pytest.fixture(scope="module")
def harvested_data():
    harvester = DataHarvestPipeline()
    return harvester.harvest_all()


def test_toolspec_harvesting(harvested_data):
    """Verifies that all 18 ToolSpecs are harvested with documentation and parameter schemas."""
    toolspecs = harvested_data["toolspecs"]
    assert len(toolspecs) == 18, f"Expected 18 ToolSpecs, got {len(toolspecs)}"

    for tool_id, spec in toolspecs.items():
        assert spec.tool_id == tool_id
        assert spec.tier in (1, 2, 3), f"Invalid tier {spec.tier} for {tool_id}"
        assert len(spec.capabilities) > 0, f"No capabilities for {tool_id}"
        assert spec.man_page_text.startswith("NAME"), f"Missing man page for {tool_id}"
        assert "SYNOPSIS" in spec.man_page_text
        assert "DESCRIPTION" in spec.man_page_text
        assert spec.help_text.startswith("Usage:"), f"Missing help text for {tool_id}"
        assert isinstance(spec.inputs_schema, dict)


def test_event_store_harvesting(harvested_data):
    """Verifies that event triples (goal, tool_call, outcome) are extracted from SQLite."""
    triples = harvested_data["event_triples"]
    assert len(triples) > 0, "Expected non-empty event triples from events.db"

    sample = triples[0]
    assert sample.goal, "Missing goal in event triple"
    assert "tool_id" in sample.tool_call
    assert "tier" in sample.tool_call
    assert "exit_code" in sample.outcome
    assert "status" in sample.outcome
    assert isinstance(sample.task_graph, dict)


def test_recovery_chains_harvesting(harvested_data):
    """Verifies explicit (bad_attempt -> corrected_attempt -> verified_result) sequences."""
    chains = harvested_data["recovery_chains"]
    assert len(chains) >= 6, f"Expected at least 6 recovery chains, got {len(chains)}"

    for c in chains:
        assert c.strategy in (
            "RATE_LIMIT_BACKOFF",
            "TOOL_SUBSTITUTION",
            "PARAM_MUTATION",
            "TIER_DOWNGRADE_STEALTH",
            "SYNTAX_ARGUMENT_REPAIR",
            "TOOL_SUBSTITUTION_AND_RATE_BACKOFF",
            "RATE_LIMIT_BACKOFF_OR_TOOL_SUBSTITUTION",
        ), f"Unrecognized strategy {c.strategy}"

        # Explicit bad_attempt -> corrected_attempt -> verified_result
        assert "tool" in c.bad_attempt
        assert "failure_reason" in c.bad_attempt
        assert c.recovery_action, "Missing recovery action"
        assert "tool" in c.corrected_attempt
        assert c.verified_result.get("status") == "success"


def test_sft_conversation_structure(harvested_data):
    """Verifies conversion into standard ToolSpec-conversation SFT format."""
    synth = SFTDataSynthesizer(harvested_data["toolspecs"])
    examples = synth.synthesize_all(
        event_triples=harvested_data["event_triples"][:50],
        recovery_chains=harvested_data["recovery_chains"],
        target_total_count=100,
    )
    assert len(examples) >= 100

    for ex in examples:
        d = ex.to_dict()
        assert "user_goal" in d
        assert "task_graph" in d
        assert "tool_call" in d
        assert "observation" in d
        assert "next_step" in d
        assert "conversation" in d
        assert "scope_contract" in d

        # Check conversation turns
        conv = d["conversation"]
        assert len(conv) >= 3
        roles = [t["role"] for t in conv]
        assert roles[0] == "system"
        assert roles[1] == "user"
        assert "assistant" in roles
        assert "tool" in roles


def test_dataset_validator(harvested_data):
    """Verifies that DatasetValidator rejects invalid records and passes compliant records."""
    validator = DatasetValidator(harvested_data["toolspecs"])
    synth = SFTDataSynthesizer(harvested_data["toolspecs"])
    examples = synth.synthesize_all(
        event_triples=harvested_data["event_triples"][:20],
        recovery_chains=harvested_data["recovery_chains"][:5],
        target_total_count=30,
    )

    # Valid example should pass
    ok, errs = validator.validate(examples[0])
    assert ok, f"Valid example failed: {errs}"

    # Invalid tool should fail
    bad_ex = SFTDataSynthesizer(harvested_data["toolspecs"]).synthesize_all(
        event_triples=[], recovery_chains=[], target_total_count=1
    )[0]
    bad_ex.tool_call["tool_id"] = "nonexistent_fake_tool_v99"
    ok, errs = validator.validate(bad_ex)
    assert not ok
    assert any("not found in registered ToolSpecs" in e for e in errs)


def test_pipeline_execution_and_summary(tmp_path):
    """Verifies end-to-end pipeline run, train/val split, and summary generation."""
    pipeline = KairoDataPipeline(
        output_dir=tmp_path,
        target_count=200,
        val_ratio=0.1,
        seed=1337,
    )
    summary = pipeline.run()

    train_file = tmp_path / "train.jsonl"
    val_file = tmp_path / "val.jsonl"
    summary_file = tmp_path / "dataset_summary.json"

    assert train_file.exists()
    assert val_file.exists()
    assert summary_file.exists()

    # Verify JSONL lines
    with open(train_file, "r", encoding="utf-8") as f:
        train_lines = [json.loads(line) for line in f]
    with open(val_file, "r", encoding="utf-8") as f:
        val_lines = [json.loads(line) for line in f]

    assert len(train_lines) + len(val_lines) == summary["total_examples"]
    assert len(val_lines) == int(summary["total_examples"] * 0.1)
    assert summary["validation_pass_rate_pct"] >= 98.0
    assert summary["covered_tools_count"] == 18
    assert summary["recovery_examples_count"] > 0
