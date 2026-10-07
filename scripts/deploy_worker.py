import base64
import json
import time
import urllib.request

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
worker_file = ROOT_DIR / "vm" / "worker_agent.py"

with open(worker_file, "rb") as f:
    content_b64 = base64.b64encode(f.read()).decode("utf-8")

write_cmd = f"python3 -c \"import base64; open('/opt/kairo/worker_agent.py', 'wb').write(base64.b64decode('{content_b64}'))\""
p = {
    "task_id": "deploy_01",
    "tool_id": "kali.exec.v1",
    "tool_version": "1.0.0",
    "arguments": {
        "command": "bash",
        "args": ["-c", write_cmd],
    },
}
req = urllib.request.Request("http://127.0.0.1:9999/execute", data=json.dumps(p).encode(), headers={"Content-Type": "application/json"})
r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
print("Wrote file:", r.get("status"))

# Restart via systemctl
p_restart = {
    "task_id": "deploy_02",
    "tool_id": "kali.exec.v1",
    "tool_version": "1.0.0",
    "arguments": {
        "command": "systemctl",
        "args": ["restart", "kairo-worker"],
    },
}
try:
    req2 = urllib.request.Request("http://127.0.0.1:9999/execute", data=json.dumps(p_restart).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req2, timeout=5)
except Exception as e:
    print("Restarting service (connection drop expected):", e)

time.sleep(2.5)

# Wait for worker online
for i in range(15):
    try:
        with urllib.request.urlopen("http://127.0.0.1:9999/health", timeout=2) as h:
            if h.status == 200:
                print("Online!")
                break
    except Exception:
        time.sleep(1.0)

# Now test artifact creation
p_art = {
    "task_id": "test_artifact_probe",
    "tool_id": "kali.exec.v1",
    "tool_version": "1.0.0",
    "arguments": {
        "command": "bash",
        "args": ["-c", "echo 'Evidence sample 123' > $KAIRO_ARTIFACT_DIR/sample.txt"],
    },
}
req3 = urllib.request.Request("http://127.0.0.1:9999/execute", data=json.dumps(p_art).encode(), headers={"Content-Type": "application/json"})
r3 = json.loads(urllib.request.urlopen(req3, timeout=10).read().decode())
print("Probe status:", r3.get("status"))
print("Probe artifacts:", r3.get("artifacts"))
