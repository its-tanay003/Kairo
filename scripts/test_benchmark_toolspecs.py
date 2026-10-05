import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from lab.tasks import LAB_TASKS
from orchestrator.tool_selector import tool_selector
from training.schema_reward import ToolSpecSchemaValidator


def test_benchmark_tasks():
    validator = ToolSpecSchemaValidator()
    valid_cnt = 0
    matched_cnt = 0

    print(f"Testing all {len(LAB_TASKS)} benchmark tasks...")
    for t in LAB_TASKS:
        sel = tool_selector.select(goal=t.objective, required_capability=t.capability, session_id="test")
        tool_id = sel.selected_tool.tool_id
        args = sel.selected_tool.inferred_args
        matched = t.evaluate_tool_selection(tool_id)
        if matched:
            matched_cnt += 1
        
        # Check args
        res = validator.validate_tool_call({"tool_id": tool_id, "arguments": args})
        if res.is_valid:
            valid_cnt += 1
        else:
            print(f"[{t.task_id}] {tool_id} args {args} -> {res.errors}")


    print(f"Tool Selection Matched: {matched_cnt}/{len(LAB_TASKS)} ({matched_cnt/len(LAB_TASKS)*100:.1f}%)")
    print(f"Schema Validation Passed: {valid_cnt}/{len(LAB_TASKS)} ({valid_cnt/len(LAB_TASKS)*100:.1f}%)")

if __name__ == "__main__":
    test_benchmark_tasks()
