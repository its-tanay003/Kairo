import json
import urllib.request
import pytest


def is_vm_worker_running() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:9999/health")
        with urllib.request.urlopen(req, timeout=1):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not is_vm_worker_running(), reason="Kali VM worker daemon (http://127.0.0.1:9999) is offline")
def test_vm_file_limit():
    """Test 1: File count limit inside VM."""
    payload_files = {
        "task_id": "test_vm_file_limit",
        "tool_id": "kali.exec.v1",
        "tool_version": "1.0.0",
        "resource_limits": {
            "max_file_count": 2,
        },
        "arguments": {
            "command": "bash",
            "args": ["-c", "for i in 1 2 3 4 5; do echo test > $KAIRO_ARTIFACT_DIR/f$i.txt; sleep 0.1; done"],
        },
    }
    req = urllib.request.Request(
        "http://127.0.0.1:9999/execute",
        data=json.dumps(payload_files).encode(),
        headers={"Content-Type": "application/json"},
    )
    r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    assert r.get("resource_limit_exceeded") is True
    assert "File-count cap exceeded" in r.get("violation_reason")


@pytest.mark.skipif(not is_vm_worker_running(), reason="Kali VM worker daemon (http://127.0.0.1:9999) is offline")
def test_vm_memory_limit():
    """Test 2: Memory limit inside VM."""
    payload_mem = {
        "task_id": "test_vm_mem_limit",
        "tool_id": "kali.exec.v1",
        "tool_version": "1.0.0",
        "resource_limits": {
            "max_memory_mb": 50.0,
        },
        "arguments": {
            "command": "python3",
            "args": ["-c", "import time; l = [];\nfor _ in range(10):\n    l.append(b'A' * (15 * 1024 * 1024))\n    time.sleep(0.1)"],
        },
    }
    req2 = urllib.request.Request(
        "http://127.0.0.1:9999/execute",
        data=json.dumps(payload_mem).encode(),
        headers={"Content-Type": "application/json"},
    )
    r2 = json.loads(urllib.request.urlopen(req2, timeout=10).read().decode())
    assert r2.get("resource_limit_exceeded") is True
    assert "Memory cap exceeded" in r2.get("violation_reason")
