"""
Kairo Data Pipeline CLI & Validator (Task 3.1 - Track B).
Orchestrates harvesting, synthesis, strict schema validation, train/val splitting,
and dataset profiling. Produces:
  - training/data/train.jsonl
  - training/data/val.jsonl
  - training/data/dataset_summary.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from events.db import DEFAULT_DB_PATH, is_target_in_scope
from training.harvest import DataHarvestPipeline, ToolSpecDoc
from training.synthesizer import SFTDataSynthesizer, SFTExample

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("training.pipeline")

DEFAULT_OUTPUT_DIR = ROOT_DIR / "training" / "data"


class DatasetValidator:
    """Validates SFT examples for schema adherence, ToolSpec conformance, and Scope compliance."""

    def __init__(self, toolspecs: Dict[str, ToolSpecDoc]):
        self.toolspecs = toolspecs
        self.required_keys = {
            "id",
            "user_goal",
            "task_graph",
            "tool_call",
            "observation",
            "next_step",
            "conversation",
            "scope_contract",
        }

    def validate(self, example: SFTExample) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        d = example.to_dict()

        # 1. Top-level keys
        missing = self.required_keys - set(d.keys())
        if missing:
            errors.append(f"Missing required fields: {missing}")

        # 2. ToolSpec existence
        t_id = d["tool_call"].get("tool_id")
        if not t_id:
            errors.append("tool_call missing 'tool_id'")
        elif t_id not in self.toolspecs:
            errors.append(f"tool_id '{t_id}' not found in registered ToolSpecs")
        else:
            spec = self.toolspecs[t_id]
            args = d["tool_call"].get("arguments", {})
            if not isinstance(args, dict):
                errors.append("tool_call 'arguments' must be a dictionary")
            else:
                # Check required inputs
                req_props = spec.required_inputs
                for req in req_props:
                    if req not in args:
                        errors.append(f"Missing required argument '{req}' for tool '{t_id}'")

        # 3. Conversation turn validation
        conv = d.get("conversation", [])
        if not isinstance(conv, list) or len(conv) < 3:
            errors.append("conversation must be a list with at least 3 turns")
        else:
            valid_roles = {"system", "user", "assistant", "tool"}
            for turn_idx, turn in enumerate(conv):
                if not isinstance(turn, dict) or "role" not in turn:
                    errors.append(f"Turn {turn_idx} missing role")
                elif turn["role"] not in valid_roles:
                    errors.append(f"Turn {turn_idx} has invalid role '{turn['role']}'")

        # 4. Scope contract boundary check
        scope = d.get("scope_contract", {})
        allowed_targets = [
            "127.0.0.1",
            "localhost",
            "192.168.1.0/24",
            "192.168.56.0/24",
            "10.0.0.0/24",
            "example.com",
            "*.internal",
        ]
        args = d.get("tool_call", {}).get("arguments", {})
        target = args.get("target") or args.get("url") or args.get("domain") or args.get("host")
        if target and not is_target_in_scope(str(target), allowed_targets):
            errors.append(f"Target '{target}' violates authorized scope bounds: {allowed_targets}")

        return (len(errors) == 0, errors)


class KairoDataPipeline:
    """Executes the full Phase 3 / Task 3.1 Data Pipeline."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        target_count: int = 2500,
        val_ratio: float = 0.1,
        seed: int = 42,
    ):
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir)
        self.target_count = target_count
        self.val_ratio = val_ratio
        self.seed = seed

        self.harvester = DataHarvestPipeline(db_path=self.db_path)

    def run(self) -> Dict[str, Any]:
        logger.info("=" * 80)
        logger.info("🚀 STARTING KAIRO DATA PIPELINE v1 (TASK 3.1 - TRACK B)")
        logger.info(f"   Target Volume: {self.target_count} SFT conversation examples")
        logger.info(f"   Output Directory: {self.output_dir}")
        logger.info("=" * 80)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Harvesting
        logger.info("[1/5] Harvesting ToolSpecs, Event Store triples, and Counterfactual chains...")
        harvested = self.harvester.harvest_all()
        toolspecs = harvested["toolspecs"]
        event_triples = harvested["event_triples"]
        recovery_chains = harvested["recovery_chains"]
        logger.info(
            f"   Harvested: {len(toolspecs)} ToolSpecs | {len(event_triples)} Event Triples | {len(recovery_chains)} Recovery Chains"
        )

        # Step 2: Synthesis
        logger.info(f"[2/5] Synthesizing SFT conversation dataset (Target: {self.target_count})...")
        synthesizer = SFTDataSynthesizer(toolspecs)
        raw_examples = synthesizer.synthesize_all(
            event_triples=event_triples,
            recovery_chains=recovery_chains,
            target_total_count=self.target_count,
        )
        logger.info(f"   Synthesized {len(raw_examples)} raw examples.")

        # Step 3: Strict Validation
        logger.info("[3/5] Validating examples against ToolSpec schemas, conversation roles, and scope bounds...")
        validator = DatasetValidator(toolspecs)
        valid_examples: List[SFTExample] = []
        validation_failures = 0

        for ex in raw_examples:
            is_valid, errs = validator.validate(ex)
            if is_valid:
                valid_examples.append(ex)
            else:
                validation_failures += 1
                logger.debug(f"Example {ex.id} rejected: {errs}")

        logger.info(
            f"   Validation complete: {len(valid_examples)} PASSED | {validation_failures} REJECTED ({len(valid_examples) / len(raw_examples) * 100:.1f}% pass rate)"
        )

        # Step 4: Train / Val Split
        logger.info(f"[4/5] Splitting dataset ({100 - int(self.val_ratio * 100)}% Train / {int(self.val_ratio * 100)}% Val)...")
        rng = random.Random(self.seed)
        rng.shuffle(valid_examples)

        val_size = int(len(valid_examples) * self.val_ratio)
        val_examples = valid_examples[:val_size]
        train_examples = valid_examples[val_size:]

        train_path = self.output_dir / "train.jsonl"
        val_path = self.output_dir / "val.jsonl"

        with open(train_path, "w", encoding="utf-8") as f:
            for ex in train_examples:
                f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

        with open(val_path, "w", encoding="utf-8") as f:
            for ex in val_examples:
                f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

        logger.info(f"   Wrote {len(train_examples)} train examples to {train_path.name}")
        logger.info(f"   Wrote {len(val_examples)} val examples to {val_path.name}")

        # Step 5: Statistical Profiling & Dataset Summary
        logger.info("[5/5] Generating dataset profiling report and metadata summary...")
        summary = self._generate_summary(train_examples, val_examples, toolspecs, validation_failures)
        summary_path = self.output_dir / "dataset_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"   Saved dataset summary report to {summary_path.name}")
        logger.info("=" * 80)
        logger.info("✅ KAIRO DATA PIPELINE v1 COMPLETED SUCCESSFULLY")
        logger.info(f"   Total Verified Examples: {summary['total_examples']}")
        logger.info(f"   Tool Coverage: {len(summary['tool_distribution'])} / {len(toolspecs)} tools")
        logger.info(f"   Recovery Chains: {summary['source_distribution'].get('counterfactual_recovery', 0)} examples ({summary['recovery_percentage']}%)")
        logger.info("=" * 80)

        return summary

    def _generate_summary(
        self,
        train_examples: List[SFTExample],
        val_examples: List[SFTExample],
        toolspecs: Dict[str, ToolSpecDoc],
        validation_failures: int,
    ) -> Dict[str, Any]:
        all_examples = train_examples + val_examples
        total = len(all_examples)

        # Source type distribution
        source_dist: Dict[str, int] = {}
        for ex in all_examples:
            source_dist[ex.source_type] = source_dist.get(ex.source_type, 0) + 1

        # Tool distribution
        tool_dist: Dict[str, int] = {}
        for ex in all_examples:
            t_id = ex.tool_call["tool_id"]
            tool_dist[t_id] = tool_dist.get(t_id, 0) + 1

        # Tier distribution
        tier_dist: Dict[int, int] = {1: 0, 2: 0, 3: 0}
        for ex in all_examples:
            tier = ex.tool_call.get("tier", 1)
            tier_dist[tier] = tier_dist.get(tier, 0) + 1

        # Category distribution
        cat_dist: Dict[str, int] = {}
        for ex in all_examples:
            t_id = ex.tool_call["tool_id"]
            cat = toolspecs.get(t_id).category if t_id in toolspecs else "other"
            cat_dist[cat] = cat_dist.get(cat, 0) + 1

        # Recovery strategy distribution
        rec_strategies: Dict[str, int] = {}
        rec_count = 0
        for ex in all_examples:
            if ex.metadata.get("is_recovery"):
                rec_count += 1
                strat = ex.metadata.get("strategy") or "AUTONOMOUS_HEALING"
                rec_strategies[strat] = rec_strategies.get(strat, 0) + 1

        # Estimate token counts (approx 4 chars / token)
        total_chars = sum(len(json.dumps(ex.to_dict())) for ex in all_examples)
        approx_tokens = total_chars // 4

        return {
            "pipeline_version": "1.0.0",
            "task": "Task 3.1 - Data pipeline v1 (Track B)",
            "total_examples": total,
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "validation_failures": validation_failures,
            "validation_pass_rate_pct": round(total / (total + validation_failures) * 100, 2) if total else 0.0,
            "approximate_total_tokens": approx_tokens,
            "mean_tokens_per_example": round(approx_tokens / total, 1) if total else 0,
            "recovery_examples_count": rec_count,
            "recovery_percentage": round(rec_count / total * 100, 2) if total else 0.0,
            "source_distribution": source_dist,
            "tool_distribution": dict(sorted(tool_dist.items(), key=lambda x: x[1], reverse=True)),
            "tier_distribution": tier_dist,
            "category_distribution": cat_dist,
            "recovery_strategies_distribution": rec_strategies,
            "registered_tools_count": len(toolspecs),
            "covered_tools_count": len(tool_dist),
        }


def main():
    parser = argparse.ArgumentParser(description="Kairo SFT Data Pipeline CLI")
    parser.add_argument("--count", "-n", type=int, default=2500, help="Target total examples to synthesize")
    parser.add_argument("--output-dir", "-o", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Output directory for jsonl files")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Event store database path")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio (default 0.1)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    args = parser.parse_args()
    pipeline = KairoDataPipeline(
        db_path=Path(args.db),
        output_dir=Path(args.output_dir),
        target_count=args.count,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
