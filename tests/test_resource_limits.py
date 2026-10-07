import os
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.process_supervisor import supervisor, ResourceLimits
from events.db import get_artifacts_by_task, verify_artifact_file

def test_file_count_limit():
    with tempfile.TemporaryDirectory() as tdir:
        limits = ResourceLimits(max_file_count=3, max_disk_mb=10)
        script = f"""
import os, time
tdir = {repr(tdir)}
for i in range(10):
    with open(os.path.join(tdir, f"file_{{i}}.txt"), "w") as f:
        f.write("data " * 100)
    time.sleep(0.08)
"""
        res = supervisor.execute("test_file_limit_01", sys.executable, ["-c", script], limits=limits, artifact_dir=tdir)
        print("File count limit:", res.resource_limit_exceeded, res.violation_reason)
        assert res.resource_limit_exceeded is True
        assert "File-count cap exceeded" in res.violation_reason

def test_memory_limit():
    limits = ResourceLimits(max_memory_mb=60.0)  # low memory limit
    script = """
import time
data = []
# allocate ~100MB
for _ in range(10):
    data.append(b"X" * (10 * 1024 * 1024))
    time.sleep(0.1)
"""
    res = supervisor.execute("test_mem_limit_01", sys.executable, ["-c", script], limits=limits, timeout_ms=10000)
    print("Memory limit:", res.resource_limit_exceeded, res.violation_reason, f"Peak: {res.peak_memory_mb}MB")
    assert res.resource_limit_exceeded is True
    assert "Memory cap exceeded" in res.violation_reason

def test_artifact_hashing():
    with tempfile.TemporaryDirectory() as tdir:
        ev_file = os.path.join(tdir, "report.log")
        with open(ev_file, "w") as f:
            f.write("Port scan results: Port 80 OPEN, Port 443 OPEN, Port 22 OPEN")
        res = supervisor.execute("test_art_01", sys.executable, ["-c", "print('done')"], artifact_dir=tdir)
        print("Artifacts count:", len(res.artifacts))
        assert len(res.artifacts) >= 1
        art = res.artifacts[0]
        assert art["filename"] == "report.log"
        assert len(art["sha256"]) == 64
        # Verify in SQLite DB
        db_arts = get_artifacts_by_task("test_art_01")
        assert len(db_arts) >= 1
        assert db_arts[0]["sha256"] == art["sha256"]
        # Verify integrity check
        check = verify_artifact_file(ev_file, art["sha256"])
        assert check["valid"] is True
        print("Artifact verified with SHA-256:", art["sha256"])

if __name__ == "__main__":
    test_file_count_limit()
    test_memory_limit()
    test_artifact_hashing()
    print("ALL SUPERVISOR RESOURCE LIMIT AND ARTIFACT TESTS PASSED!")
