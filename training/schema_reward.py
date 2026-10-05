"""
ToolSpec Schema Validation, Reward Calculation, and Filtering Module (Track B).
Enforces tool-call output format as a first-class training objective:
- Validates tool-call generation against registered ToolSpec JSON/YAML schemas
- Computes granular schema rewards (0.0 to 1.0)
- Provides dataset cleaning/filtering step that discards non-parseable/invalid examples
- Provides TrainerCallback to log schema validation metrics during SFT evaluation
"""

from typing import Dict, Any, List, Optional, Tuple, Union
import os
import sys
import json
import re
from pathlib import Path
import yaml
from dataclasses import dataclass, field

from transformers import TrainerCallback, TrainerControl, TrainerState, TrainingArguments

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from events.db import is_target_in_scope


@dataclass
class SchemaValidationResult:
    """Detailed outcome of schema validation and reward calculation."""
    is_valid: bool
    reward: float  # 0.0 to 1.0
    tool_id: Optional[str]
    parsed_args: Dict[str, Any]
    parse_success: bool
    errors: List[str] = field(default_factory=list)
    scope_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "reward": self.reward,
            "tool_id": self.tool_id,
            "parsed_args": self.parsed_args,
            "parse_success": self.parse_success,
            "errors": self.errors,
            "scope_valid": self.scope_valid
        }


DEFAULT_ALLOWED_TARGETS = [
    "127.0.0.1",
    "192.168.1.0/24",
    "192.168.1.10",
    "192.168.1.20",
    "192.168.1.25",
    "192.168.1.50",
    "192.168.1.100",
    "target.lab",
    "target.local",
    "staging.corp.internal",
    "api.corp.internal",
    "localhost"
]


class ToolSpecSchemaValidator:
    """
    Validates tool calls against the registered ToolSpec YAML schemas in registry/tools/.
    Evaluates JSON parseability, tool registration, required properties, types, and scope boundaries.
    """

    def __init__(
        self,
        registry_dir: Optional[str] = None,
        allowed_targets: Optional[List[str]] = None
    ):
        self.registry_dir = Path(registry_dir) if registry_dir else ROOT_DIR / "registry" / "tools"
        self.allowed_targets = allowed_targets or list(DEFAULT_ALLOWED_TARGETS)
        self.toolspecs: Dict[str, Dict[str, Any]] = {}
        self._load_toolspecs()

    def _load_toolspecs(self):
        """Loads and indexes all ToolSpec YAML files."""
        if not self.registry_dir.exists():
            return

        for yml_file in self.registry_dir.glob("*.yaml"):
            try:
                with open(yml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "id" in data:
                        self.toolspecs[data["id"]] = data
            except Exception:
                continue

    @property
    def registered_tool_ids(self) -> List[str]:
        return list(self.toolspecs.keys())

    def extract_tool_call(self, target: Union[str, Dict[str, Any]]) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool, List[str]]:
        """
        Extracts tool_id and arguments dict from various formats:
        - Dict: {"tool_id": "...", "arguments": {...}} or {"name": "...", "arguments": {...}}
        - XML Tag: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
        - Markdown code block: ```json {"tool_id": "...", "arguments": {...}} ```
        - Raw JSON string
        """
        errors = []
        if isinstance(target, dict):
            # Format 1: Kairo 5-tuple tool_call
            if "tool_id" in target:
                args = target.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as e:
                        return target["tool_id"], None, False, [f"Arguments string is not valid JSON: {e}"]
                return target["tool_id"], args, True, []
            
            # Format 2: OpenAI tool_call
            if "name" in target:
                args = target.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as e:
                        return target["name"], None, False, [f"Arguments string is not valid JSON: {e}"]
                return target["name"], args, True, []

            # Format 3: Nested function tool_call
            if "function" in target and isinstance(target["function"], dict):
                fn = target["function"]
                name = fn.get("name")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as e:
                        return name, None, False, [f"Arguments string is not valid JSON: {e}"]
                return name, args, True, []

            return None, None, False, ["Dictionary does not contain 'tool_id' or 'name'"]

        if isinstance(target, str):
            text = target.strip()

            # Check for <tool_call>...</tool_call> tags
            match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
            if match:
                payload = match.group(1).strip()
                try:
                    data = json.loads(payload)
                    return self.extract_tool_call(data)
                except json.JSONDecodeError as e:
                    return None, None, False, [f"JSON in <tool_call> failed to parse: {e}"]

            # Check for ```json ... ``` blocks
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                payload = match.group(1).strip()
                try:
                    data = json.loads(payload)
                    return self.extract_tool_call(data)
                except json.JSONDecodeError as e:
                    return None, None, False, [f"JSON in code block failed to parse: {e}"]

            # Try parsing raw string as JSON
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    return self.extract_tool_call(data)
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    return self.extract_tool_call(data[0])
            except json.JSONDecodeError:
                pass

            # Try regex heuristic for tool_id and arguments
            tool_match = re.search(r'["\']?(?:tool_id|name)["\']?\s*:\s*["\']([^"\']+)["\']', text)
            if tool_match:
                tool_id = tool_match.group(1)
                args_match = re.search(r'["\']?arguments["\']?\s*:\s*(\{.*?\})', text, re.DOTALL)
                if args_match:
                    try:
                        args = json.loads(args_match.group(1))
                        return tool_id, args, True, []
                    except json.JSONDecodeError:
                        return tool_id, None, False, ["Found tool_id but arguments failed JSON parsing"]
                return tool_id, {}, False, ["Found tool_id but no valid arguments dictionary"]

            return None, None, False, ["Could not extract valid tool call JSON from text"]

        return None, None, False, [f"Unsupported target type: {type(target)}"]

    def validate_tool_call(
        self,
        target: Union[str, Dict[str, Any]],
        scope_enforcement: bool = True
    ) -> SchemaValidationResult:
        """
        Validates a tool call and computes the schema reward (0.0 to 1.0).
        Reward breakdown:
        - 0.0: Failed JSON parsing or completely unrecognized structure
        - 0.2: Valid JSON but tool not recognized in ToolSpec registry
        - 0.5: Tool recognized, but missing required properties or severe type error
        - 0.7: Tool recognized, required properties present, but scope boundary violation
        - 1.0: Perfect schema compliance (tool exists, args parse, all required present, in-scope)
        """
        tool_id, args, parse_success, extract_errors = self.extract_tool_call(target)

        if not parse_success or not tool_id:
            return SchemaValidationResult(
                is_valid=False,
                reward=0.0,
                tool_id=tool_id,
                parsed_args=args or {},
                parse_success=False,
                errors=extract_errors,
                scope_valid=True
            )

        if tool_id not in self.toolspecs:
            return SchemaValidationResult(
                is_valid=False,
                reward=0.2,
                tool_id=tool_id,
                parsed_args=args or {},
                parse_success=True,
                errors=[f"Tool '{tool_id}' not found in registry (available: {len(self.toolspecs)} tools)"],
                scope_valid=True
            )

        spec = self.toolspecs[tool_id]
        spec_inputs = spec.get("inputs", {})
        properties = spec_inputs.get("properties", {})
        required = spec_inputs.get("required", [])

        errors: List[str] = []

        # Check required properties
        if not isinstance(args, dict):
            return SchemaValidationResult(
                is_valid=False,
                reward=0.3,
                tool_id=tool_id,
                parsed_args={},
                parse_success=True,
                errors=["Arguments must be a key-value dictionary"],
                scope_valid=True
            )

        missing_required = [req for req in required if req not in args or args[req] is None]
        if missing_required:
            errors.append(f"Missing required properties for '{tool_id}': {missing_required}")

        # Check argument types
        for k, v in args.items():
            if k in properties:
                prop_type = properties[k].get("type")
                if prop_type == "integer" and not isinstance(v, int) and not (isinstance(v, str) and v.isdigit()):
                    errors.append(f"Property '{k}' expected integer, got {type(v).__name__}")
                elif prop_type == "boolean" and not isinstance(v, bool) and str(v).lower() not in ["true", "false"]:
                    errors.append(f"Property '{k}' expected boolean, got {type(v).__name__}")
                elif prop_type == "array" and not isinstance(v, list):
                    errors.append(f"Property '{k}' expected array/list, got {type(v).__name__}")

        # Check scope enforcement on target/host/url
        scope_valid = True
        if scope_enforcement:
            target_val = args.get("target") or args.get("host") or args.get("url")
            if target_val and isinstance(target_val, str):
                # Clean URL / port
                clean_target = target_val.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
                if not is_target_in_scope(clean_target, self.allowed_targets):
                    errors.append(f"Target '{clean_target}' violates Scope Contract boundaries")
                    scope_valid = False

        if errors:
            if not scope_valid and not missing_required:
                reward = 0.7  # Schema is valid, but violates scope boundary
            else:
                reward = 0.5  # Schema missing fields or type error
            return SchemaValidationResult(
                is_valid=False,
                reward=reward,
                tool_id=tool_id,
                parsed_args=args,
                parse_success=True,
                errors=errors,
                scope_valid=scope_valid
            )

        # Perfect schema conformance
        return SchemaValidationResult(
            is_valid=True,
            reward=1.0,
            tool_id=tool_id,
            parsed_args=args,
            parse_success=True,
            errors=[],
            scope_valid=True
        )


def clean_dataset_with_schema_filter(
    input_jsonl: str,
    output_jsonl: str,
    min_reward: float = 1.0,
    validator: Optional[ToolSpecSchemaValidator] = None
) -> Dict[str, Any]:
    """
    Data cleaning step: filters the dataset and discards any example that does not
    parse or whose tool-call target fails schema validation.
    """
    validator = validator or ToolSpecSchemaValidator()
    total_count = 0
    passed_count = 0
    discarded_count = 0
    discard_reasons: Dict[str, int] = {}
    reward_sum = 0.0

    os.makedirs(os.path.dirname(os.path.abspath(output_jsonl)), exist_ok=True)

    with open(input_jsonl, "r", encoding="utf-8") as in_f, open(output_jsonl, "w", encoding="utf-8") as out_f:
        for line in in_f:
            line = line.strip()
            if not line:
                continue
            total_count += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                discarded_count += 1
                discard_reasons["json_decode_error"] = discard_reasons.get("json_decode_error", 0) + 1
                continue

            # Target can be in 'tool_call' or within assistant conversation turns
            target_to_check = record.get("tool_call")
            if not target_to_check:
                # Look for assistant tool call in conversation
                for turn in record.get("conversation", []):
                    if turn.get("role") == "assistant" and "tool_calls" in turn and turn["tool_calls"]:
                        target_to_check = turn["tool_calls"][0]
                        break

            if not target_to_check:
                discarded_count += 1
                discard_reasons["missing_tool_call_target"] = discard_reasons.get("missing_tool_call_target", 0) + 1
                continue

            res = validator.validate_tool_call(target_to_check)
            reward_sum += res.reward

            if res.reward >= min_reward and res.is_valid:
                # Attach verified schema validation metadata
                record.setdefault("metadata", {})["schema_reward"] = res.reward
                record.setdefault("metadata", {})["schema_validated"] = True
                out_f.write(json.dumps(record) + "\n")
                passed_count += 1
            else:
                discarded_count += 1
                primary_err = res.errors[0] if res.errors else f"reward_{res.reward}"
                discard_reasons[primary_err] = discard_reasons.get(primary_err, 0) + 1

    pass_rate_pct = (passed_count / total_count * 100.0) if total_count > 0 else 0.0
    mean_reward = (reward_sum / total_count) if total_count > 0 else 0.0

    return {
        "total_records": total_count,
        "retained_records": passed_count,
        "discarded_records": discarded_count,
        "pass_rate_pct": round(pass_rate_pct, 2),
        "mean_schema_reward": round(mean_reward, 4),
        "discard_reasons": discard_reasons
    }


class SchemaValidationEvalCallback(TrainerCallback):
    """
    Hugging Face / TRL Trainer Callback that runs during evaluation steps.
    Extracts generated tool calls or eval batch targets, computes the schema validation reward,
    and logs eval_schema_reward and eval_schema_pass_rate to trainer state.
    """

    def __init__(self, validator: Optional[ToolSpecSchemaValidator] = None, tokenizer=None):
        self.validator = validator or ToolSpecSchemaValidator()
        self.tokenizer = tokenizer

    def on_evaluate(self, args: TrainingArguments, state: TrainerState, control: TrainerControl, metrics=None, **kwargs):
        """Called by Trainer after each evaluation pass."""
        eval_dataset = kwargs.get("eval_dataset")
        if eval_dataset is None:
            return

        # Sample a subset from eval_dataset to compute schema reward
        sample_size = min(32, len(eval_dataset))
        valid_count = 0
        parse_count = 0
        rewards: List[float] = []

        for i in range(sample_size):
            item = eval_dataset[i]
            
            # If dataset has raw records
            if hasattr(eval_dataset, "records") and i < len(eval_dataset.records):
                record = eval_dataset.records[i]
                target = record.get("tool_call")
            elif "labels" in item and self.tokenizer is not None:
                # Decode non -100 labels to reconstruct assistant response
                label_ids = [tid for tid in item["labels"] if tid != -100]
                target_str = self.tokenizer.decode(label_ids, skip_special_tokens=False)
                target = target_str
            else:
                continue

            if target:
                res = self.validator.validate_tool_call(target)
                rewards.append(res.reward)
                if res.parse_success:
                    parse_count += 1
                if res.is_valid:
                    valid_count += 1

        if rewards:
            mean_reward = sum(rewards) / len(rewards)
            pass_rate = (valid_count / len(rewards)) * 100.0
            parse_rate = (parse_count / len(rewards)) * 100.0

            # Log to Trainer logs and metrics
            log_metrics = {
                "eval_schema_reward": round(mean_reward, 4),
                "eval_schema_pass_rate": round(pass_rate, 2),
                "eval_schema_parse_rate": round(parse_rate, 2)
            }
            if metrics is not None:
                metrics.update(log_metrics)
            
            print(f"\n[Schema Validation Eval @ Step {state.global_step}] "
                  f"Reward: {mean_reward:.4f} | Pass Rate: {pass_rate:.1f}% | Parse Rate: {parse_rate:.1f}%")
