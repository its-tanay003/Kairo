"""
Conformance test suite for all 14 Kairo tool adapters.
Tests run each tool against the Kali VM (127.0.0.1:9999, SSH 2222)
and assert the parser produces valid structured observation output.

Run:
    python -m pytest test_tool_adapters.py -v
    python -m pytest test_tool_adapters.py -v -k nmap  # single tool
    python -m pytest test_tool_adapters.py -v --no-header -p no:warnings

Prerequisites:
  - Kali VM running with worker agent on port 9999
  - Run: python test_tool_adapters.py --local   to run parser-only unit tests without VM
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.adapters.base import ToolObservation

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

VM_HOST = os.environ.get("KALI_VM_HOST", "127.0.0.1")
VM_PORT = int(os.environ.get("KALI_VM_PORT", "9999"))
TARGET_IP = os.environ.get("KALI_TARGET_IP", "127.0.0.1")  # IP target inside Kali
TARGET_URL = os.environ.get("KALI_TARGET_URL", f"http://{TARGET_IP}")


def vm_available() -> bool:
    """Check if the Kali VM worker agent is reachable."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(f"http://{VM_HOST}:{VM_PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


VM_SKIP = pytest.mark.skipif(
    not vm_available(),
    reason="Kali VM not reachable at 127.0.0.1:9999 - skipping live execution tests",
)


def assert_valid_observation(obs: ToolObservation, tool_id: str) -> None:
    """Common assertions every adapter observation must satisfy."""
    assert isinstance(obs, ToolObservation), f"Expected ToolObservation, got {type(obs)}"
    assert obs.tool_id == tool_id
    assert obs.status in ("success", "error", "timeout"), f"Invalid status: {obs.status}"
    assert isinstance(obs.exit_code, int)
    assert isinstance(obs.raw_stdout, str)
    assert isinstance(obs.raw_stderr, str)
    assert isinstance(obs.duration_ms, (int, float))
    assert isinstance(obs.observation, dict), "observation must be a dict"
    assert "tool" in obs.observation, "observation must contain 'tool' key"

    # Ensure serializable
    obs_dict = obs.to_dict()
    assert json.dumps(obs_dict), "Observation must be JSON-serializable"


# ─────────────────────────────────────────────
# Parser-only unit tests (no VM required)
# ─────────────────────────────────────────────

class TestNmapParser:
    def test_parse_xml_output(self):
        from orchestrator.adapters.nmap_adapter import NmapAdapter
        adapter = NmapAdapter.__new__(NmapAdapter)

        xml = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.56.1" addrtype="ipv4"/>
    <hostnames><hostname name="router.local"/></hostnames>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.4"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="nginx" version="1.18"/>
      </port>
    </ports>
  </host>
  <runstats>
    <finished elapsed="2.34" summary="Nmap done"/>
    <hosts up="1" down="0" total="1"/>
  </runstats>
</nmaprun>"""

        result = adapter.parse(xml, "", 0, {"inputs": {"target": "192.168.56.1"}})
        assert result["tool"] == "nmap"
        assert result["hosts_found"] == 1
        assert len(result["hosts"][0]["ports"]) == 2
        assert result["hosts"][0]["ports"][0]["port"] == 22
        assert result["hosts"][0]["ports"][0]["service"] == "ssh"
        assert result["open_ports"] == 2
        assert result["scan_stats"]["hosts_up"] == 1

    def test_build_args_basic(self):
        from orchestrator.adapters.nmap_adapter import NmapAdapter
        adapter = NmapAdapter.__new__(NmapAdapter)
        args = adapter.build_args({"target": "192.168.56.1", "ports": "22,80", "scan_type": "sV"})
        assert "192.168.56.1" in args
        assert "-p" in args
        assert "22,80" in args
        assert "-sV" in args
        assert "-oX" in args

    def test_parse_empty_xml(self):
        from orchestrator.adapters.nmap_adapter import NmapAdapter
        adapter = NmapAdapter.__new__(NmapAdapter)
        result = adapter.parse("", "", 1, {"inputs": {"target": "192.168.56.1"}})
        assert "hosts" in result


class TestGobusterParser:
    def test_parse_dir_output(self):
        from orchestrator.adapters.gobuster_adapter import GobusterAdapter
        adapter = GobusterAdapter.__new__(GobusterAdapter)
        stdout = """
/admin                (Status: 301) [Size: 312] [--> http://192.168.56.1/admin/]
/login                (Status: 200) [Size: 1234]
/config               (Status: 403) [Size: 0]
"""
        result = adapter.parse(stdout, "", 0, {"inputs": {"url": "http://192.168.56.1", "mode": "dir"}})
        assert result["tool"] == "gobuster"
        assert result["total_found"] == 3
        assert any(f["path"] == "/admin" for f in result["findings"])
        assert any(f["status"] == 200 for f in result["findings"])

    def test_build_args(self):
        from orchestrator.adapters.gobuster_adapter import GobusterAdapter
        adapter = GobusterAdapter.__new__(GobusterAdapter)
        args = adapter.build_args({
            "url": "http://192.168.56.1",
            "wordlist": "/usr/share/wordlists/dirb/common.txt",
            "threads": 10,
        })
        assert "dir" in args
        assert "-u" in args
        assert "http://192.168.56.1" in args
        assert "-w" in args


class TestFfufParser:
    def test_parse_json_output(self):
        from orchestrator.adapters.ffuf_adapter import FfufAdapter
        adapter = FfufAdapter.__new__(FfufAdapter)
        stdout = json.dumps({
            "commandline": "ffuf -u http://example.com/FUZZ -w wordlist.txt",
            "results": [
                {"input": {"FUZZ": "admin"}, "url": "http://example.com/admin", "status": 200, "length": 1000, "words": 100, "lines": 50, "position": 1, "duration": 5000},
                {"input": {"FUZZ": "login"}, "url": "http://example.com/login", "status": 301, "length": 0, "words": 0, "lines": 0, "position": 2, "duration": 3000},
            ]
        })
        result = adapter.parse(stdout, "", 0, {"inputs": {"url": "http://example.com/FUZZ"}})
        assert result["tool"] == "ffuf"
        assert result["total_found"] == 2
        assert result["results"][0]["url"] == "http://example.com/admin"
        assert result["results"][0]["status"] == 200

    def test_build_args_get(self):
        from orchestrator.adapters.ffuf_adapter import FfufAdapter
        adapter = FfufAdapter.__new__(FfufAdapter)
        args = adapter.build_args({
            "url": "http://192.168.56.1/FUZZ",
            "wordlist": "/usr/share/wordlists/dirb/common.txt",
        })
        assert "-u" in args
        assert "http://192.168.56.1/FUZZ" in args
        assert "-of" in args
        assert "json" in args


class TestNiktoParser:
    def test_parse_csv_output(self):
        from orchestrator.adapters.nikto_adapter import NiktoAdapter
        adapter = NiktoAdapter.__new__(NiktoAdapter)
        stdout = (
            '"192.168.56.1","192.168.56.1","80","0","GET","/index.html","The anti-clickjacking X-Frame-Options header is not present."\n'
            '"192.168.56.1","192.168.56.1","80","OSVDB-3268","GET","/admin/","Directory indexing found"\n'
        )
        result = adapter.parse(stdout, "", 0, {"inputs": {"host": "192.168.56.1", "port": 80}})
        assert result["tool"] == "nikto"
        assert isinstance(result["findings"], list)

    def test_build_args(self):
        from orchestrator.adapters.nikto_adapter import NiktoAdapter
        adapter = NiktoAdapter.__new__(NiktoAdapter)
        args = adapter.build_args({"host": "192.168.56.1", "port": 80})
        assert "-h" in args
        assert "192.168.56.1" in args
        assert "-Format" in args
        assert "csv" in args


class TestWhatWebParser:
    def test_parse_json_output(self):
        from orchestrator.adapters.whatweb_adapter import WhatWebAdapter
        adapter = WhatWebAdapter.__new__(WhatWebAdapter)
        stdout = json.dumps({
            "target": "http://192.168.56.1",
            "http_status": 200,
            "plugins": {
                "Title": {"string": ["Welcome to nginx"]},
                "nginx": {"version": ["1.18.0"]},
                "HTTPServer": {"string": ["nginx/1.18.0"]},
            }
        })
        result = adapter.parse(stdout, "", 0, {"inputs": {"url": "http://192.168.56.1"}})
        assert result["tool"] == "whatweb"
        assert result["http_status"] == 200
        assert result["total_plugins"] >= 1
        assert result["title"] == "Welcome to nginx"

    def test_build_args(self):
        from orchestrator.adapters.whatweb_adapter import WhatWebAdapter
        adapter = WhatWebAdapter.__new__(WhatWebAdapter)
        args = adapter.build_args({"url": "http://192.168.56.1", "aggression": 1})
        assert "http://192.168.56.1" in args
        assert "-a1" in args
        assert "--log-json=-" in args


class TestSqlmapParser:
    def test_parse_injectable_output(self):
        from orchestrator.adapters.sqlmap_adapter import SqlmapAdapter
        adapter = SqlmapAdapter.__new__(SqlmapAdapter)
        stdout = """
Parameter: id (GET)
    Type: boolean-based blind
    Title: AND boolean-based blind - WHERE or HAVING clause
    Payload: id=1 AND 1=1
back-end DBMS: MySQL >= 5.0
[INFO] sqlmap identified the following injection point(s) with a total of 50 HTTP(s) requests
"""
        result = adapter.parse(stdout, "", 0, {"inputs": {"url": "http://192.168.56.1/login.php?id=1"}})
        assert result["tool"] == "sqlmap"
        assert result["dbms"] == "MySQL >= 5.0"
        assert len(result["injection_points"]) >= 1

    def test_build_args_batch_mode(self):
        from orchestrator.adapters.sqlmap_adapter import SqlmapAdapter
        adapter = SqlmapAdapter.__new__(SqlmapAdapter)
        args = adapter.build_args({"url": "http://192.168.56.1/?id=1", "level": 1, "risk": 1})
        assert "--batch" in args
        assert "--answers=N" in args
        assert "-v" in args


class TestHydraParser:
    def test_parse_credential_found(self):
        from orchestrator.adapters.hydra_adapter import HydraAdapter
        adapter = HydraAdapter.__new__(HydraAdapter)
        stdout = "[22][ssh] host: 192.168.56.1   login: root   password: toor"
        result = adapter.parse(stdout, "", 0, {"inputs": {"target": "192.168.56.1", "protocol": "ssh"}})
        assert result["tool"] == "hydra"
        assert result["success"] is True
        assert len(result["credentials_found"]) == 1
        assert result["credentials_found"][0]["username"] == "root"
        assert result["credentials_found"][0]["password"] == "toor"

    def test_parse_no_credentials(self):
        from orchestrator.adapters.hydra_adapter import HydraAdapter
        adapter = HydraAdapter.__new__(HydraAdapter)
        stdout = "[DATA] attack finished for 192.168.56.1 (waiting for children to complete tests)"
        result = adapter.parse(stdout, "", 0, {"inputs": {"target": "192.168.56.1", "protocol": "ssh"}})
        assert result["success"] is False

    def test_build_args_ssh(self):
        from orchestrator.adapters.hydra_adapter import HydraAdapter
        adapter = HydraAdapter.__new__(HydraAdapter)
        args = adapter.build_args({
            "target": "192.168.56.1",
            "protocol": "ssh",
            "username": "root",
            "password_list": "/usr/share/wordlists/rockyou.txt",
        })
        assert "192.168.56.1" in args
        assert "ssh" in args
        assert "-l" in args
        assert "root" in args


class TestSearchsploitParser:
    def test_parse_json_results(self):
        from orchestrator.adapters.searchsploit_adapter import SearchsploitAdapter
        adapter = SearchsploitAdapter.__new__(SearchsploitAdapter)
        stdout = json.dumps({
            "RESULTS_EXPLOIT": [
                {
                    "Title": "Apache 2.4.49 - Path Traversal",
                    "EDB-ID": "50383",
                    "Date": "2021-10-07",
                    "Author": "Ash Daulton",
                    "Type": "webapps",
                    "Platform": "Linux",
                    "Path": "/usr/share/exploitdb/exploits/linux/webapps/50383.py",
                    "Verified": True,
                }
            ]
        })
        result = adapter.parse(stdout, "", 0, {"inputs": {"query": "apache 2.4"}})
        assert result["tool"] == "searchsploit"
        assert result["total_found"] == 1
        assert result["exploits"][0]["edb_id"] == "50383"

    def test_build_args_json(self):
        from orchestrator.adapters.searchsploit_adapter import SearchsploitAdapter
        adapter = SearchsploitAdapter.__new__(SearchsploitAdapter)
        args = adapter.build_args({"query": "apache 2.4"})
        assert "--json" in args
        assert "apache" in args


class TestWhoisParser:
    def test_parse_domain_record(self):
        from orchestrator.adapters.whois_adapter import WhoisAdapter
        adapter = WhoisAdapter.__new__(WhoisAdapter)
        stdout = """
Domain Name: EXAMPLE.COM
Registrar: Example Registrar LLC
Creation Date: 1995-08-14T04:00:00Z
Registry Expiry Date: 2023-08-13T04:00:00Z
Updated Date: 2022-08-14T07:01:35Z
Name Server: A.IANA-SERVERS.NET
Name Server: B.IANA-SERVERS.NET
Domain Status: clientDeleteProhibited
"""
        result = adapter.parse(stdout, "", 0, {"inputs": {"target": "example.com"}})
        assert result["tool"] == "whois"
        assert "example" in result["domain"].lower()
        assert len(result["name_servers"]) >= 1
        assert len(result["status"]) >= 1

    def test_build_args(self):
        from orchestrator.adapters.whois_adapter import WhoisAdapter
        adapter = WhoisAdapter.__new__(WhoisAdapter)
        args = adapter.build_args({"target": "example.com"})
        assert "example.com" in args


class TestDigParser:
    def test_parse_a_record(self):
        from orchestrator.adapters.dig_adapter import DigAdapter
        adapter = DigAdapter.__new__(DigAdapter)
        stdout = """;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 12345
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0

;; ANSWER SECTION:
example.com.		300	IN	A	93.184.216.34

;; Query time: 42 msec
;; SERVER: 8.8.8.8#53(8.8.8.8)
"""
        result = adapter.parse(stdout, "", 0, {"inputs": {"target": "example.com", "record_type": "A"}})
        assert result["tool"] == "dig"
        assert result["status"] == "NOERROR"
        assert len(result["answers"]) == 1
        assert result["answers"][0]["value"] == "93.184.216.34"
        assert result["query_time_ms"] == 42

    def test_build_args_a_record(self):
        from orchestrator.adapters.dig_adapter import DigAdapter
        adapter = DigAdapter.__new__(DigAdapter)
        args = adapter.build_args({"target": "example.com", "record_type": "A"})
        assert "example.com" in args
        assert "A" in args


class TestTcpdumpParser:
    def test_parse_capture_stats(self):
        from orchestrator.adapters.tcpdump_adapter import TcpdumpAdapter
        adapter = TcpdumpAdapter.__new__(TcpdumpAdapter)
        stderr = """
tcpdump: listening on eth0, link-type EN10MB (Ethernet), snapshot length 262144 bytes
50 packets captured
50 packets received by filter
0 packets dropped by kernel
"""
        result = adapter.parse("", stderr, 0, {
            "inputs": {"interface": "eth0", "output_file": "/tmp/kairo_capture.pcap"}
        })
        assert result["tool"] == "tcpdump"
        assert result["packets_captured"] == 50
        assert result["packets_dropped"] == 0
        assert result["capture_file"] == "/tmp/kairo_capture.pcap"
        assert "/tmp/kairo_capture.pcap" in result["_artifacts"]

    def test_build_args_with_filter(self):
        from orchestrator.adapters.tcpdump_adapter import TcpdumpAdapter
        adapter = TcpdumpAdapter.__new__(TcpdumpAdapter)
        args = adapter.build_args({
            "interface": "eth0",
            "filter": "tcp port 80",
            "count": 50,
        })
        assert "-i" in args
        assert "eth0" in args
        assert "-c" in args
        assert "50" in args
        assert "-w" in args


class TestExiftoolParser:
    def test_parse_json_metadata(self):
        from orchestrator.adapters.exiftool_adapter import ExiftoolAdapter
        adapter = ExiftoolAdapter.__new__(ExiftoolAdapter)
        stdout = json.dumps([{
            "SourceFile": "/tmp/test.jpg",
            "Make": "Apple",
            "Model": "iPhone 13",
            "CreateDate": "2022:06:15 14:30:00",
            "Software": "iOS 15.5",
            "GPSLatitude": "37.7749 N",
            "GPSLongitude": "122.4194 W",
        }])
        result = adapter.parse(stdout, "", 0, {"inputs": {"file_path": "/tmp/test.jpg"}})
        assert result["tool"] == "exiftool"
        assert result["files_processed"] == 1
        assert result["files"][0]["make"] == "Apple"
        assert result["files"][0]["model"] == "iPhone 13"
        # GPS tags should appear in sensitive findings
        assert len(result["sensitive_findings"]) >= 1

    def test_build_args(self):
        from orchestrator.adapters.exiftool_adapter import ExiftoolAdapter
        adapter = ExiftoolAdapter.__new__(ExiftoolAdapter)
        args = adapter.build_args({"file_path": "/tmp/test.jpg"})
        assert "-json" in args
        assert "/tmp/test.jpg" in args


class TestHashidParser:
    def test_parse_md5_hash(self):
        from orchestrator.adapters.hashid_adapter import HashidAdapter
        adapter = HashidAdapter.__new__(HashidAdapter)
        stdout = """Analyzing '5f4dcc3b5aa765d61d8327deb882cf99'
[+] MD5 [Hashcat Mode: 0][JtR Format: raw-md5]
[+] MD4 [Hashcat Mode: 900][JtR Format: raw-md4]
[+] Double MD5 [Hashcat Mode: 2600]
"""
        result = adapter.parse(stdout, "", 0, {"inputs": {"hash": "5f4dcc3b5aa765d61d8327deb882cf99"}})
        assert result["tool"] == "hashid"
        assert result["hash"] == "5f4dcc3b5aa765d61d8327deb882cf99"
        assert result["hash_length"] == 32
        assert len(result["identified_types"]) >= 1
        assert result["identified_types"][0]["name"] == "MD5"
        assert result["identified_types"][0]["hashcat_mode"] == "0"

    def test_parse_bcrypt(self):
        from orchestrator.adapters.hashid_adapter import HashidAdapter
        adapter = HashidAdapter.__new__(HashidAdapter)
        h = "$2y$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy"
        stdout = f"""Analyzing '{h}'
[+] Blowfish(OpenBSD) [Hashcat Mode: 3200][JtR Format: bcrypt]
"""
        result = adapter.parse(stdout, "", 0, {"inputs": {"hash": h}})
        assert result["identified_types"][0]["hashcat_mode"] == "3200"

    def test_build_args_with_modes(self):
        from orchestrator.adapters.hashid_adapter import HashidAdapter
        adapter = HashidAdapter.__new__(HashidAdapter)
        args = adapter.build_args({"hash": "5f4dcc3b5aa765d61d8327deb882cf99"})
        assert "-m" in args
        assert "-j" in args
        assert "5f4dcc3b5aa765d61d8327deb882cf99" in args


# ─────────────────────────────────────────────
# Registry Conformance Tests
# ─────────────────────────────────────────────

class TestAdapterRegistryConformance:
    def test_all_adapters_registered(self):
        from orchestrator.adapters.registry import adapter_registry
        tool_ids = adapter_registry.list_tool_ids()
        expected = [
            "nmap.scan.v1",
            "metasploit.rpc.v1",
            "gobuster.dir.v1",
            "ffuf.fuzz.v1",
            "nikto.scan.v1",
            "whatweb.scan.v1",
            "sqlmap.scan.v1",
            "hydra.brute.v1",
            "searchsploit.search.v1",
            "whois.lookup.v1",
            "dig.lookup.v1",
            "tcpdump.capture.v1",
            "exiftool.extract.v1",
            "hashid.identify.v1",
        ]
        for eid in expected:
            assert eid in tool_ids, f"Missing adapter: {eid}"

    def test_adapters_instantiate(self):
        from orchestrator.adapters.registry import adapter_registry
        for tool_id in adapter_registry.list_tool_ids():
            instance = adapter_registry.get_instance(tool_id)
            assert instance is not None, f"Could not instantiate {tool_id}"
            assert instance.tool_id == tool_id


class TestToolSpecYamlConformance:
    """Ensure all tool YAML files pass ToolRegistry validation."""
    def test_all_new_specs_load_cleanly(self):
        from registry.loader import ToolRegistry
        reg = ToolRegistry()
        tool_ids = [t.id for t in reg.list_tools()]
        new_tools = [
            "nmap.scan.v1",
            "metasploit.rpc.v1",
            "gobuster.dir.v1",
            "ffuf.fuzz.v1",
            "nikto.scan.v1",
            "whatweb.scan.v1",
            "sqlmap.scan.v1",
            "hydra.brute.v1",
            "searchsploit.search.v1",
            "whois.lookup.v1",
            "dig.lookup.v1",
            "tcpdump.capture.v1",
            "exiftool.extract.v1",
            "hashid.identify.v1",
        ]
        for t in new_tools:
            assert t in tool_ids, f"Tool {t} not found in registry after YAML load"

    def test_all_specs_have_binary(self):
        from registry.loader import ToolRegistry
        reg = ToolRegistry()
        for spec in reg.list_tools():
            assert spec.binary, f"Tool {spec.id} has empty binary"
            assert spec.category, f"Tool {spec.id} has empty category"
            assert isinstance(spec.capabilities, list), f"Tool {spec.id} capabilities not list"


# ─────────────────────────────────────────────
# Live VM Execution Tests (require running VM)
# ─────────────────────────────────────────────

@VM_SKIP
class TestNmapLiveVM:
    def test_nmap_scan_local(self):
        from orchestrator.adapters.nmap_adapter import NmapAdapter
        adapter = NmapAdapter()
        obs = adapter.execute(
            {"target": "127.0.0.1", "ports": "22,9999", "scan_type": "sT", "timing": 3},
            task_id=f"test_nmap_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=60000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "nmap.scan.v1")
        assert obs.status in ("success", "error")
        assert "hosts" in obs.observation
        assert isinstance(obs.observation["hosts"], list)


@VM_SKIP
class TestSearchsploitLiveVM:
    def test_searchsploit_query(self):
        from orchestrator.adapters.searchsploit_adapter import SearchsploitAdapter
        adapter = SearchsploitAdapter()
        obs = adapter.execute(
            {"query": "ssh"},
            task_id=f"test_ss_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=30000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "searchsploit.search.v1")
        assert "exploits" in obs.observation
        assert isinstance(obs.observation["exploits"], list)
        assert obs.observation["total_found"] >= 0


@VM_SKIP
class TestWhoisLiveVM:
    def test_whois_lookup(self):
        from orchestrator.adapters.whois_adapter import WhoisAdapter
        adapter = WhoisAdapter()
        obs = adapter.execute(
            {"target": "example.com"},
            task_id=f"test_whois_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=30000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "whois.lookup.v1")
        assert "name_servers" in obs.observation
        assert isinstance(obs.observation["name_servers"], list)


@VM_SKIP
class TestDigLiveVM:
    def test_dig_a_record(self):
        from orchestrator.adapters.dig_adapter import DigAdapter
        adapter = DigAdapter()
        obs = adapter.execute(
            {"target": "8.8.8.8", "record_type": "PTR"},
            task_id=f"test_dig_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=20000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "dig.lookup.v1")
        assert "answers" in obs.observation
        assert isinstance(obs.observation["answers"], list)


@VM_SKIP
class TestHashidLiveVM:
    def test_hashid_md5(self):
        from orchestrator.adapters.hashid_adapter import HashidAdapter
        adapter = HashidAdapter()
        obs = adapter.execute(
            {"hash": "5f4dcc3b5aa765d61d8327deb882cf99"},
            task_id=f"test_hashid_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=20000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "hashid.identify.v1")
        assert "identified_types" in obs.observation
        assert len(obs.observation["identified_types"]) > 0


@VM_SKIP
class TestExiftoolLiveVM:
    def test_exiftool_system_binary(self):
        from orchestrator.adapters.exiftool_adapter import ExiftoolAdapter
        adapter = ExiftoolAdapter()
        # Use a binary we know exists in Kali
        obs = adapter.execute(
            {"file_path": "/bin/ls"},
            task_id=f"test_exif_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=20000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "exiftool.extract.v1")
        assert "files" in obs.observation


@VM_SKIP
class TestWhatWebLiveVM:
    def test_whatweb_localhost(self):
        from orchestrator.adapters.whatweb_adapter import WhatWebAdapter
        adapter = WhatWebAdapter()
        obs = adapter.execute(
            {"url": "http://127.0.0.1", "aggression": 1},
            task_id=f"test_whatweb_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=30000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "whatweb.scan.v1")
        assert "plugins_found" in obs.observation


@VM_SKIP
class TestGobusterLiveVM:
    def test_gobuster_localhost_dir(self):
        from orchestrator.adapters.gobuster_adapter import GobusterAdapter
        adapter = GobusterAdapter()
        obs = adapter.execute(
            {
                "url": "http://127.0.0.1",
                "wordlist": "/usr/share/wordlists/dirb/common.txt",
                "threads": 5,
            },
            task_id=f"test_gobuster_{uuid.uuid4().hex[:6]}",
            target="vm",
            timeout_ms=120000,
            snapshot_before=False,
        )
        assert_valid_observation(obs, "gobuster.dir.v1")
        assert "findings" in obs.observation
        assert isinstance(obs.observation["findings"], list)


if __name__ == "__main__":
    pytest.main(["-v", __file__, "--tb=short"])
