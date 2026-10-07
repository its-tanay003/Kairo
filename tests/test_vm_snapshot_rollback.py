import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.vm_manager import vm_manager
from events.db import get_artifacts_by_task, verify_artifact_file

def test_snapshot_and_rollback():
    task_id = f"test_snap_rb_{int(time.time())}"
    print(f"Executing task with snapshot_before=True and rollback_after=True: {task_id}")

    # Create a dummy flag file inside Kali, then rollback after task.
    # The flag file should NOT exist after rollback!
    res = vm_manager.execute_in_vm(
        task_id=task_id,
        tool_id="kali.exec.v1",
        tool_version="1.0.0",
        args={
            "command": "bash",
            "args": ["-c", "echo 'KAIRO_EPHEMERAL_FLAG' > /tmp/kairo_ephemeral.txt && echo 'Artifact evidence' > $KAIRO_ARTIFACT_DIR/evidence_hash.txt"],
        },
        snapshot_before=True,
        rollback_after=True,
        timeout_ms=30000,
    )

    print("Task Result Status:", res.get("status"))
    print("Snapshot Name:", res.get("snapshot_name"))
    print("Rollback Info:", res.get("rollback_info"))
    print("Rolled Back:", res.get("rolled_back"))
    print("Artifacts Captured:", res.get("artifacts"))

    assert res.get("snapshot_name") is not None
    assert res.get("pre_snapshot", {}).get("status") == "success"
    assert res.get("rolled_back") is True
    assert res.get("rollback_info", {}).get("status") == "success"
    assert len(res.get("artifacts", [])) >= 1

    art = res.get("artifacts")[0]
    assert art["filename"] == "evidence_hash.txt"
    assert len(art["sha256"]) == 64
    print("Artifact SHA-256 recorded:", art["sha256"])

    # Check that artifact is stored in local SQLite database
    db_arts = get_artifacts_by_task(task_id)
    assert len(db_arts) >= 1
    assert db_arts[0]["sha256"] == art["sha256"]
    print("Database verification passed! Found in SQLite artifacts table.")

    # Check that after rollback, the ephemeral file /tmp/kairo_ephemeral.txt does NOT exist!
    check_task_id = f"test_verify_clean_{int(time.time())}"
    res_check = vm_manager.execute_in_vm(
        task_id=check_task_id,
        tool_id="kali.exec.v1",
        tool_version="1.0.0",
        args={
            "command": "bash",
            "args": ["-c", "test -f /tmp/kairo_ephemeral.txt && echo 'EXISTS' || echo 'DOES_NOT_EXIST'"],
        },
        snapshot_before=False,
        rollback_after=False,
        timeout_ms=10000,
    )
    output = res_check.get("stdout", "").strip()
    print("Ephemeral file existence check in VM:", output)
    assert output == "DOES_NOT_EXIST"
    print("Clean state verified! Ephemeral changes were rolled back.")

if __name__ == "__main__":
    test_snapshot_and_rollback()
    print("ALL SNAPSHOT AND ROLLBACK TESTS PASSED!")
