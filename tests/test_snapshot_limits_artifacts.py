"""
Comprehensive Conformance Test Suite for:
1. Automated VM Snapshot-Before-Task & Optional Rollback-After-Task
2. Process Supervisor Resource Caps (CPU, RAM, Disk, File-Count Limits per Task)
3. Cryptographic Artifact Hashing (SHA-256) and Integrity Verification
"""

import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from events.db import compute_sha256, get_artifacts_by_task, verify_artifact_file
from orchestrator.process_supervisor import ResourceLimits, supervisor
from orchestrator.vm_manager import vm_manager


def test_1_process_supervisor_host_resource_caps():
    """
    Asserts that the host process supervisor actively enforces:
    - File-count limits per task
    - Memory (RSS MB) limits per task
    - Output directory artifact auto-scanning & SHA-256 calculation
    """
    print("\n" + "=" * 60)
    print("TEST 1: Host Process Supervisor Resource Caps & Hashing")
    print("=" * 60)

    # 1. File Count Cap
    with tempfile.TemporaryDirectory() as tdir:
        limits = ResourceLimits(max_file_count=2, max_disk_mb=10)
        script = f"""
import os, time
tdir = {repr(tdir)}
for i in range(5):
    with open(os.path.join(tdir, f"leak_{{i}}.log"), "w") as f:
        f.write("A" * 100)
    time.sleep(0.08)
"""
        res = supervisor.execute(
            "test_host_file_cap",
            sys.executable,
            ["-c", script],
            limits=limits,
            artifact_dir=tdir,
        )
        print(f"File Cap Test: exceeded={res.resource_limit_exceeded}, reason={res.violation_reason}")
        assert res.resource_limit_exceeded is True
        assert "File-count cap exceeded" in res.violation_reason
        assert res.exit_code in (137, 1)

    # 2. RAM Memory Cap
    limits_mem = ResourceLimits(max_memory_mb=50.0)
    script_mem = """
import time
data = []
for _ in range(8):
    data.append(b"M" * (12 * 1024 * 1024))
    time.sleep(0.08)
"""
    res_mem = supervisor.execute(
        "test_host_mem_cap",
        sys.executable,
        ["-c", script_mem],
        limits=limits_mem,
        timeout_ms=10000,
    )
    print(f"Memory Cap Test: exceeded={res_mem.resource_limit_exceeded}, reason={res_mem.violation_reason}, peak={res_mem.peak_memory_mb}MB")
    assert res_mem.resource_limit_exceeded is True
    assert "Memory cap exceeded" in res_mem.violation_reason

    # 3. Artifact SHA-256 Hashing on Host
    with tempfile.TemporaryDirectory() as tdir:
        art_path = os.path.join(tdir, "forensic_sample.txt")
        test_content = "AUTHENTIC EVIDENCE PAYLOAD 2026"
        with open(art_path, "w", encoding="utf-8") as f:
            f.write(test_content)

        expected_hash = hashlib.sha256(test_content.encode("utf-8")).hexdigest()
        res_art = supervisor.execute(
            "test_host_artifact_hash",
            sys.executable,
            ["-c", "print('complete')"],
            artifact_dir=tdir,
        )
        assert len(res_art.artifacts) >= 1
        found_art = res_art.artifacts[0]
        assert found_art["filename"] == "forensic_sample.txt"
        assert found_art["sha256"] == expected_hash
        print(f"Host Artifact Hashed: {found_art['filename']} -> SHA-256: {found_art['sha256']}")

    print("✓ Test 1: Host Process Supervisor Resource Caps & Hashing PASSED!")


def test_2_vm_guest_worker_resource_caps():
    """
    Asserts that the in-guest Kali worker agent enforces:
    - Memory limits with SIGKILL (exit 137)
    - File-count limits with status 'resource_limit_exceeded'
    """
    print("\n" + "=" * 60)
    print("TEST 2: VM In-Guest Worker Agent Resource Caps")
    print("=" * 60)

    # 1. VM Memory Limit
    mem_payload = {
        "task_id": "test_vm_caps_mem",
        "tool_id": "kali.exec.v1",
        "tool_version": "1.0.0",
        "resource_limits": {
            "max_memory_mb": 50.0,
        },
        "arguments": {
            "command": "python3",
            "args": [
                "-c",
                "import time; l = [];\nfor _ in range(8):\n    l.append(b'X' * (15 * 1024 * 1024))\n    time.sleep(0.08)",
            ],
        },
    }
    req = urllib.request.Request(
        "http://127.0.0.1:9999/execute",
        data=json.dumps(mem_payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    print(f"VM Memory Cap: exceeded={resp.get('resource_limit_exceeded')}, reason={resp.get('violation_reason')}, exit={resp.get('exit_code')}")
    assert resp.get("resource_limit_exceeded") is True
    assert "Memory cap exceeded" in resp.get("violation_reason")
    assert resp.get("exit_code") == 137

    # 2. VM File Count Limit
    file_payload = {
        "task_id": "test_vm_caps_file",
        "tool_id": "kali.exec.v1",
        "tool_version": "1.0.0",
        "resource_limits": {
            "max_file_count": 2,
        },
        "arguments": {
            "command": "bash",
            "args": [
                "-c",
                "for i in 1 2 3 4; do echo item > $KAIRO_ARTIFACT_DIR/drop_$i.dat; sleep 0.1; done",
            ],
        },
    }
    req2 = urllib.request.Request(
        "http://127.0.0.1:9999/execute",
        data=json.dumps(file_payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp2 = json.loads(urllib.request.urlopen(req2, timeout=15).read().decode())
    print(f"VM File Cap: exceeded={resp2.get('resource_limit_exceeded')}, reason={resp2.get('violation_reason')}, exit={resp2.get('exit_code')}")
    assert resp2.get("resource_limit_exceeded") is True
    assert "File-count cap exceeded" in resp2.get("violation_reason")

    print("✓ Test 2: VM In-Guest Worker Agent Resource Caps PASSED!")


def test_3_automated_vm_snapshot_and_rollback():
    """
    Asserts:
    1. Automated snapshot is taken prior to task execution
    2. Task executes and creates artifacts
    3. Artifact SHA-256 hashes are recorded in SQLite
    4. Automated rollback restores VM to pristine baseline
    5. Side-effects created during task are confirmed vanished
    """
    print("\n" + "=" * 60)
    print("TEST 3: Automated VM Snapshot & Rollback Lifecycle")
    print("=" * 60)

    task_id = f"test_snap_rb_full_{int(time.time())}"

    # Task writes an ephemeral flag in /tmp and an evidence file in $KAIRO_ARTIFACT_DIR
    res = vm_manager.execute_in_vm(
        task_id=task_id,
        tool_id="kali.exec.v1",
        tool_version="1.0.0",
        args={
            "command": "bash",
            "args": [
                "-c",
                "echo 'VOLATILE_MARKER_12345' > /tmp/kairo_volatile.flag && "
                "echo 'EVIDENCE_REPORT_PAYLOAD' > $KAIRO_ARTIFACT_DIR/audit_report.txt && "
                "cat $KAIRO_ARTIFACT_DIR/audit_report.txt",
            ],
        },
        snapshot_before=True,
        rollback_after=True,
        timeout_ms=30000,
    )

    print("Execution Status:", res.get("status"))
    print("Snapshot Taken:", res.get("snapshot_name"))
    print("Rolled Back After Task:", res.get("rolled_back"))
    print("Rollback Info:", res.get("rollback_info"))

    assert res.get("snapshot_name") is not None
    assert res.get("rolled_back") is True
    assert res.get("rollback_info", {}).get("status") == "success"

    # Artifact check
    artifacts = res.get("artifacts", [])
    assert len(artifacts) >= 1
    report_art = [a for a in artifacts if a["filename"] == "audit_report.txt"][0]
    expected_sha = hashlib.sha256(b"EVIDENCE_REPORT_PAYLOAD\n").hexdigest()
    assert report_art["sha256"] == expected_sha
    print(f"Captured Artifact Verified: {report_art['filename']} -> SHA-256: {report_art['sha256']}")

    # Confirm artifact was saved to SQLite artifacts table
    db_artifacts = get_artifacts_by_task(task_id)
    assert len(db_artifacts) >= 1
    assert any(a["sha256"] == expected_sha for a in db_artifacts)
    print("✓ Artifact registered in SQLite 'artifacts' database table!")

    # Verify rollback: /tmp/kairo_volatile.flag must NOT exist anymore
    verify_task_id = f"test_clean_check_{int(time.time())}"
    verify_res = vm_manager.execute_in_vm(
        task_id=verify_task_id,
        tool_id="kali.exec.v1",
        tool_version="1.0.0",
        args={
            "command": "bash",
            "args": ["-c", "test -f /tmp/kairo_volatile.flag && echo 'EXISTS' || echo 'DOES_NOT_EXIST'"],
        },
        snapshot_before=False,
        rollback_after=False,
        timeout_ms=10000,
    )
    clean_status = verify_res.get("stdout", "").strip()
    print("Pristine State Verification:", clean_status)
    assert clean_status == "DOES_NOT_EXIST"
    print("✓ Rollback Confirmed! Ephemeral file in VM was reverted cleanly.")

    print("✓ Test 3: Automated VM Snapshot & Rollback Lifecycle PASSED!")


def test_4_artifact_sha256_cryptographic_verification():
    """
    Asserts:
    1. verify_artifact_file detects valid SHA-256 checksums
    2. verify_artifact_file detects tampering/checksum mismatches
    """
    print("\n" + "=" * 60)
    print("TEST 4: Artifact SHA-256 Cryptographic Integrity Verification")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tdir:
        test_file = Path(tdir) / "evidence.pcap"
        original_data = b"\xd4\xc3\xb2\xa1\x02\x00\x04\x00" + b"\x00" * 32
        test_file.write_bytes(original_data)

        orig_sha = compute_sha256(test_file)
        print("Original SHA-256:", orig_sha)

        # 1. Valid Check
        valid_res = verify_artifact_file(test_file, orig_sha)
        assert valid_res["valid"] is True
        assert valid_res["actual_sha256"] == orig_sha
        print("✓ Valid artifact verification passed:", valid_res)

        # 2. Tampered Check (modify 1 byte)
        test_file.write_bytes(original_data + b"\xff")
        tampered_res = verify_artifact_file(test_file, orig_sha)
        assert tampered_res["valid"] is False
        assert tampered_res["actual_sha256"] != orig_sha
        print("✓ Tampered artifact detected correctly:", tampered_res)

    print("✓ Test 4: Artifact SHA-256 Integrity Verification PASSED!")


if __name__ == "__main__":
    test_1_process_supervisor_host_resource_caps()
    test_2_vm_guest_worker_resource_caps()
    test_3_automated_vm_snapshot_and_rollback()
    test_4_artifact_sha256_cryptographic_verification()

    print("\n" + "#" * 60)
    print("### ALL CONFORMANCE TESTS PASSED (100% SUCCESS) ###")
    print("#" * 60)
