"""
Test process supervisor execution, hard timeout, and SIGKILL kill switch.
"""
from orchestrator.process_supervisor import supervisor
import threading
import time

def test_supervisor():
    print("=== Test 1: Normal execution ===")
    r1 = supervisor.execute("task_norm_1", "python", ["-c", "print('stdout line 1'); print('stdout line 2')"])
    print("PID:", r1.process_id, "Exit:", r1.exit_code, "Stdout:", repr(r1.stdout.strip()))
    assert r1.exit_code == 0
    assert "stdout line 1" in r1.stdout

    print("\n=== Test 2: Hard timeout enforcement ===")
    r2 = supervisor.execute("task_timeout_2", "python", ["-c", "import time; time.sleep(5)"], timeout_ms=300)
    print("Timed out:", r2.timed_out, "Exit:", r2.exit_code, "Stderr:", repr(r2.stderr.strip()))
    assert r2.timed_out is True
    assert r2.exit_code == 124

    print("\n=== Test 3: Kill switch by task_id ===")
    def bg_worker():
        supervisor.execute("task_kill_3", "python", ["-c", "import time; time.sleep(10)"], timeout_ms=10000)

    th = threading.Thread(target=bg_worker)
    th.start()
    time.sleep(0.3)
    active = supervisor.list_active()
    print("Active before kill:", active)
    assert len(active) == 1
    assert active[0]["task_id"] == "task_kill_3"

    k_res = supervisor.kill_by_task_id("task_kill_3")
    print("Kill switch result:", k_res)
    assert k_res["status"] == "killed"

    th.join(timeout=2.0)
    assert len(supervisor.list_active()) == 0
    print("Active after kill: [] (Verified)")
    print("\nALL PROCESS SUPERVISOR TESTS PASSED!")

if __name__ == "__main__":
    test_supervisor()
