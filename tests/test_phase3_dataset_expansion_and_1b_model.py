"""
Unit and Integration Tests for Phase 3 Track B Dataset Expansion & Scaled 1B-1.5B Model.

Verifies:
1. Model Presets in 1B-1.5B range (kairo-1.2b, kairo-1.4b, kairo-1.5b) complying with
   RMSNorm + RoPE + GQA + SwiGLU + 8k-16k context window.
2. Preference pairs (better vs. worse plans) authored by comparing agent task-graph choices.
3. Expanded SFT dataset incorporating Phase 4-5 GUI tools (Burp, Wireshark, ZAP, Browser)
   and counterfactual failure/recovery chains.
4. Domain continuation pretraining engine on the expanded Kali/security corpus.
"""

import json
import os
from pathlib import Path
import pytest
import torch
from transformers import Qwen2ForCausalLM

from training.model import (
    get_kairo_config,
    verify_architecture_spec,
    MODEL_CONFIG_PRESETS,
)
from training.preferences import TaskGraphPreferenceAuthor, PreferencePair
from training.pretrain import SecurityCorpusBuilder, DomainPretrainer
from training.harvest import RecoveryChainHarvester, ToolSpecHarvester
from training.schema_reward import ToolSpecSchemaValidator


ROOT_DIR = Path(__file__).resolve().parent.parent
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
DATA_DIR = ROOT_DIR / "training" / "data"


# ==============================================================================
# 1. Scaled 1B - 1.5B Architecture Compliance Tests
# ==============================================================================

class TestScaledModelArchitecture:
    """Verifies that the scaled model architectures comply with the 1B-1.5B specification."""

    def test_scaled_presets_registered(self):
        presets = ["kairo-1.2b", "kairo-1.4b", "kairo-1.5b"]
        for p in presets:
            assert p in MODEL_CONFIG_PRESETS, f"Preset {p} must be defined in MODEL_CONFIG_PRESETS"

    @pytest.mark.parametrize("preset_name,expected_min_m,expected_max_m", [
        ("kairo-1.2b", 1000, 1200),
        ("kairo-1.4b", 1250, 1450),
        ("kairo-1.5b", 1450, 1600),
    ])
    def test_parameter_sizing_in_1b_to_1_5b_range(self, preset_name, expected_min_m, expected_max_m):
        cfg = get_kairo_config(preset_name)
        with torch.device("meta"):
            meta_model = Qwen2ForCausalLM(cfg)
            total_params = sum(p.numel() for p in meta_model.parameters())

        params_m = total_params / 1e6
        assert expected_min_m <= params_m <= expected_max_m, (
            f"Preset {preset_name} has {params_m:.2f}M params, expected {expected_min_m}M - {expected_max_m}M"
        )

        spec = verify_architecture_spec(cfg, total_params)
        assert spec["all_passed"] is True, f"Architecture verification failed: {spec}"
        assert spec["has_rmsnorm"] is True
        assert spec["has_rope"] is True
        assert spec["has_gqa"] is True
        assert spec["has_swiglu"] is True
        assert spec["context_valid_8k_16k"] is True
        assert spec["params_in_1b_1_5b_range"] is True

    def test_scaled_forward_and_backward_gradient_computation(self):
        """Verifies forward and backward gradients with the scaled 1.2B configuration (2-layer slice)."""
        cfg = get_kairo_config("kairo-1.2b", context_length=256, num_hidden_layers=2)
        model = Qwen2ForCausalLM(cfg)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)

        # Batch of 2 tokens
        input_ids = torch.randint(0, 1000, (2, 32))
        labels = input_ids.clone()

        model.train()
        optimizer.zero_grad()
        outputs = model(input_ids=input_ids, labels=labels)
        assert outputs.loss is not None
        assert torch.isfinite(outputs.loss).item()

        outputs.loss.backward()
        grads = [p.grad for p in model.parameters() if p.grad is not None]
        assert len(grads) > 0
        assert all(torch.isfinite(g).all().item() for g in grads)
        optimizer.step()


# ==============================================================================
# 2. Preference Pairs (Better vs. Worse Plans) Tests
# ==============================================================================

class TestPreferencePairGeneration:
    """Verifies preference pair generation comparing agent task-graph choices."""

    def test_author_generates_preference_pairs(self):
        author = TaskGraphPreferenceAuthor(seed=42)
        pairs = author.generate_all(count_per_category=10)
        assert len(pairs) >= 60, "Expected at least 60 pairs across 6 categories"

        categories = set(p.scenario for p in pairs)
        assert "web_vulnerability_assessment" in categories
        assert "network_service_audit" in categories
        assert "auth_and_browser_testing" in categories
        assert "dast_vulnerability_pipeline" in categories
        assert "packet_capture_and_analysis" in categories
        assert "gui_repeater_fuzzing" in categories

    def test_preference_pairs_structure_and_task_graph_comparison(self):
        pref_file = DATA_DIR / "preferences.jsonl"
        assert pref_file.exists(), f"Preferences file {pref_file} must exist"

        with open(pref_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        assert len(lines) >= 300, f"Expected at least 300 preference pairs, got {len(lines)}"

        for p in lines[:20]:
            assert "prompt" in p
            assert "chosen" in p
            assert "rejected" in p
            assert "task_graph_comparison" in p
            
            comp = p["task_graph_comparison"]
            assert "chosen" in comp
            assert "rejected" in comp
            
            # Chosen must have nodes, rationale, and recovery branches or strategy
            assert "nodes" in comp["chosen"]
            assert len(comp["chosen"]["nodes"]) > 0
            
            # Rejected must identify flaws
            assert "flaws" in comp["rejected"]
            assert len(comp["rejected"]["flaws"]) > 0


# ==============================================================================
# 3. Expanded SFT Dataset Tests (GUI Tools & Failure/Recovery)
# ==============================================================================

class TestExpandedSFTDataset:
    """Verifies inclusion of Phase 4-5 GUI tools and counterfactual recovery traces."""

    def test_dataset_summary_reflects_expansion(self):
        summary_file = DATA_DIR / "dataset_summary.json"
        assert summary_file.exists()

        with open(summary_file, "r", encoding="utf-8") as f:
            summary = json.load(f)

        assert summary["total_examples"] >= 2500
        assert summary["covered_tools_count"] == 22, "All 22 tools must be covered"
        assert summary["preference_pairs_count"] >= 300
        assert summary["security_corpus_size_chars"] >= 50000

        # Check GUI tools covered
        tool_dist = summary["tool_distribution"]
        assert "burpsuite.gui.v1" in tool_dist
        assert "wireshark.gui.v1" in tool_dist
        assert "zap.gui.v1" in tool_dist
        assert "browser.security.v1" in tool_dist

    def test_counterfactual_recovery_chains_present_in_harvest(self):
        harvester = RecoveryChainHarvester()
        chains = harvester.harvest_chains()
        chain_ids = [c.chain_id for c in chains]

        # Verify Phase 4-5 recovery chains
        assert "rec_cf_burp_intercept_stall" in chain_ids
        assert "rec_cf_wireshark_perm_denied" in chain_ids
        assert "rec_cf_zap_spider_recursion" in chain_ids
        assert "rec_cf_browser_waf_evasion" in chain_ids
        assert "rec_cf_android_adb_restart" in chain_ids

    def test_schema_reward_cleaning_report(self):
        report_file = DATA_DIR / "schema_cleaning_report.json"
        assert report_file.exists()

        with open(report_file, "r", encoding="utf-8") as f:
            rep = json.load(f)

        assert rep["train"]["pass_rate_pct"] >= 80.0
        assert rep["train"]["mean_schema_reward"] >= 0.90
        assert rep["validation"]["pass_rate_pct"] >= 80.0


# ==============================================================================
# 4. Domain Continuation Pretraining Engine Tests
# ==============================================================================

class TestDomainContinuationPretraining:
    """Verifies the expanded Kali/security domain pretraining engine."""

    def test_security_corpus_builder(self):
        builder = SecurityCorpusBuilder(output_dir=DATA_DIR)
        corpus = builder.build_corpus(min_size_chars=20000)

        assert len(corpus) >= 20000
        assert "SECTION 1: KAIRO REGISTERED TOOL SPECIFICATIONS" in corpus
        assert "SECTION 2: NETWORK PROTOCOLS & PACKET ANALYSIS" in corpus
        assert "SECTION 3: WEB APPLICATION SECURITY" in corpus
        assert "SECTION 4: GUI PENETRATION TESTING WORKFLOWS" in corpus
        assert "SECTION 5: AUTONOMOUS RECOVERY" in corpus

    def test_domain_pretrainer_execution(self):
        pretrainer = DomainPretrainer(
            preset_name="kairo-1.2b",
            learning_rate=1e-4,
            block_size=128,
            batch_size=2,
        )

        test_corpus = (
            "Kairo Security Engine. Autonomous penetration testing framework. "
            "TCP handshake SYN, SYN-ACK, ACK. Burp Suite proxy intercept active on 127.0.0.1:8080. "
            "Wireshark BPF capture filter: host 192.168.1.50 and port 80. "
            "Playwright browser security XSS check with dialog alert verification. "
        ) * 50

        summary = pretrainer.run_pretraining(
            corpus_text=test_corpus,
            num_steps=2,
            save_checkpoint=False,
            use_small_slice_for_test=True,
        )

        assert summary["steps_completed"] == 2
        assert summary["mean_loss"] > 0
        assert torch.isfinite(torch.tensor(summary["mean_loss"])).item()
        assert summary["final_perplexity"] > 0
