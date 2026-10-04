"""
Fixed, Versioned Benchmark Task Set for Kairo Lab (Exactly 10 Tasks).

Each task specification contains:
1. task_id: Unique benchmark identifier (LAB-TASK-01 to LAB-TASK-10)
2. name: Descriptive benchmark title
3. objective: Cybersecurity goal provided to the autonomous agent
4. target: Target asset / URI / IP
5. capability: Abstract capability category matched by tool selector
6. expected_tool_family: Expected tool spec ID or family
7. expected_evidence_class: Blueprint EvidenceClass (command, network, file, visual, analytic, report)
8. expected_evidence_spec: Expected key attributes and facts in structured observation / evidence
9. recovery_challenge: Indicates whether the task injects an execution anomaly to verify Task 2.5 self-healing
10. simulated_raw_output: Deterministic raw tool output matching tool adapter parsers
11. success_condition: Predicate function verifying task completion
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from orchestrator.evidence_store import EvidenceClass


@dataclass
class LabTask:
    task_id: str
    name: str
    objective: str
    target: str
    capability: str
    expected_tool_family: str
    expected_evidence_class: EvidenceClass
    expected_evidence_spec: Dict[str, Any]
    recovery_challenge: bool = False
    recovery_trigger: Optional[Dict[str, Any]] = None
    simulated_raw_output: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def evaluate_tool_selection(self, selected_tool_id: str) -> bool:
        """Checks whether the selected tool belongs to the expected tool family."""
        if selected_tool_id == self.expected_tool_family:
            return True
        # Allow compatible tool aliases
        aliases: Dict[str, List[str]] = {
            "nmap.scan.v1": ["system_ping", "nmap.scan.v1"],
            "gobuster.dir.v1": ["ffuf.fuzz.v1", "gobuster.dir.v1"],
            "ffuf.fuzz.v1": ["gobuster.dir.v1", "ffuf.fuzz.v1"],
            "sqlmap.scan.v1": ["sqlmap.scan.v1"],
            "whatweb.scan.v1": ["whatweb.scan.v1", "nmap.scan.v1"],
            "nikto.scan.v1": ["nikto.scan.v1"],
            "searchsploit.search.v1": ["searchsploit.search.v1", "metasploit.rpc.v1"],
            "hydra.brute.v1": ["hydra.brute.v1"],
            "exiftool.extract.v1": ["exiftool.extract.v1"],
            "hashid.identify.v1": ["hashid.identify.v1"],
        }
        return selected_tool_id in aliases.get(self.expected_tool_family, [self.expected_tool_family])

    def evaluate_evidence_completeness(self, observation_facts: Dict[str, Any], evidence_artifacts: List[Any]) -> float:
        """
        Calculates evidence completeness score (0.0 to 1.0) based on required evidence class
        and expected observation facts.
        """
        score = 0.0
        # 1. Evidence class match in stored artifacts (40%)
        class_matched = any(
            getattr(art, "evidence_class", None) == self.expected_evidence_class or
            getattr(art, "evidence_class", None) == self.expected_evidence_class.value
            for art in evidence_artifacts
        )
        if class_matched:
            score += 0.40

        # 2. Key observation fact presence (60%)
        spec_keys = self.expected_evidence_spec.keys()
        if not spec_keys:
            return 1.0

        matches = 0.0
        for key, expected_val in self.expected_evidence_spec.items():
            actual_val = observation_facts.get(key)
            if actual_val is None and "metadata" in observation_facts:
                actual_val = observation_facts["metadata"].get(key)

            if actual_val is not None:
                actual_str = json.dumps(actual_val).lower().replace("_", " ")
                if isinstance(expected_val, list) and expected_val:
                    item_matches = 0
                    for item in expected_val:
                        if isinstance(item, dict):
                            if all(str(v).lower() in actual_str for v in item.values()):
                                item_matches += 1
                        else:
                            norm_item = str(item).lower().replace("_", " ")
                            if norm_item in actual_str:
                                item_matches += 1
                    matches += item_matches / len(expected_val)
                elif isinstance(expected_val, dict) and expected_val:
                    dict_matches = sum(
                        1 for k, v in expected_val.items()
                        if str(v).lower() in actual_str or str(k).lower() in actual_str
                    )
                    matches += dict_matches / len(expected_val)
                elif str(expected_val).lower().replace("_", " ") in actual_str:
                    matches += 1.0
                else:
                    matches += 0.5
            elif observation_facts:
                all_str = json.dumps(observation_facts).lower().replace("_", " ")
                exp_str = str(expected_val).lower().replace("_", " ")
                if exp_str in all_str or str(key).lower().replace("_", " ") in all_str:
                    matches += 1.0

        fact_score = (matches / len(spec_keys)) * 0.60
        return min(1.0, score + fact_score)

    def evaluate_success(
        self,
        observation: Any,
        finding_created: bool,
        recovered: bool = False,
    ) -> bool:
        """Evaluates whether the task objective condition has been satisfied."""
        if not observation:
            return False
        if observation.status != "success":
            return False

        if self.recovery_challenge and not recovered:
            return False

        # Task-specific predicates
        facts = getattr(observation, "facts", None)
        if not facts:
            return finding_created

        if self.task_id == "LAB-TASK-01":
            return len(facts.ports) >= 2 or 8889 in [p.get("port") for p in facts.ports] or 80 in [p.get("port") for p in facts.ports]
        elif self.task_id == "LAB-TASK-02":
            return len(facts.endpoints) >= 1 or any("admin" in ep.get("path", "") for ep in facts.endpoints)
        elif self.task_id == "LAB-TASK-03":
            return any("apache" in str(tech).lower() or "php" in str(tech).lower() for tech in facts.technologies)
        elif self.task_id == "LAB-TASK-04":
            return len(facts.vulnerabilities) >= 1 or finding_created
        elif self.task_id == "LAB-TASK-05":
            return len(facts.vulnerabilities) >= 1 or len(facts.technologies) >= 1 or finding_created
        elif self.task_id == "LAB-TASK-06":
            return len(facts.vulnerabilities) >= 1 or finding_created
        elif self.task_id == "LAB-TASK-07":
            return len(facts.credentials) >= 1 or finding_created
        elif self.task_id == "LAB-TASK-08":
            return finding_created or bool(facts.metadata)
        elif self.task_id == "LAB-TASK-09":
            return finding_created or bool(facts.technologies) or bool(facts.metadata)
        elif self.task_id == "LAB-TASK-10":
            return recovered and (len(facts.endpoints) >= 1 or finding_created)

        return finding_created or observation.has_findings


# ─────────────────────────────────────────────────────────────────────────────
# EXACT 10 VERSIONED LAB TASKS
# ─────────────────────────────────────────────────────────────────────────────

LAB_TASKS: List[LabTask] = [
    # Task 1: Network Scanning
    LabTask(
        task_id="LAB-TASK-01",
        name="Network Port & Service Enumeration",
        objective="Scan vulnerable Metasploitable lab host 127.0.0.1:8889 to enumerate open ports and identify active service banners.",
        target="127.0.0.1:8889",
        capability="network_port_scan",
        expected_tool_family="nmap.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "ports": [21, 22, 80, 3306],
            "hosts": ["127.0.0.1"],
        },
        simulated_raw_output={
            "stdout": """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" version="7.94">
<host starttime="1600000000" endtime="1600000005">
  <status state="up" reason="conn-ack"/>
  <address addr="127.0.0.1" addrtype="ipv4"/>
  <ports>
    <port protocol="tcp" portid="21"><state state="open" reason="syn-ack"/><service name="ftp" product="vsftpd" version="2.3.4" extrainfo="backdoor"/></port>
    <port protocol="tcp" portid="22"><state state="open" reason="syn-ack"/><service name="ssh" product="OpenSSH" version="4.7p1 Debian-8ubuntu1"/></port>
    <port protocol="tcp" portid="80"><state state="open" reason="syn-ack"/><service name="http" product="Apache httpd" version="2.2.8"/></port>
    <port protocol="tcp" portid="3306"><state state="open" reason="syn-ack"/><service name="mysql" product="MySQL" version="5.0.51a-3ubuntu5"/></port>
  </ports>
</host>
</nmaprun>""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Enumerates TCP listening ports and service versions on Metasploitable lab host.",
    ),

    # Task 2: Directory Brute-force & Endpoint Fuzzing
    LabTask(
        task_id="LAB-TASK-02",
        name="Hidden Administrative Directory Discovery",
        objective="Perform directory fuzzing against Mini-DVWA target to discover unlinked endpoints and administrative portals (/admin, /secret_api).",
        target="http://127.0.0.1:8888/dvwa/",
        capability="web_directory_enum",
        expected_tool_family="gobuster.dir.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "endpoints": ["/admin", "/secret_api"],
        },
        simulated_raw_output={
            "stdout": """
===============================================================
Gobuster v3.5
by OJ Reeves (@TheColonial) & Christian Mehlmauer (@firefart)
===============================================================
[+] Url:                     http://127.0.0.1:8888/dvwa/
[+] Threads:                 10
[+] Wordlist:                /usr/share/wordlists/dirb/common.txt
===============================================================
Found: /admin (Status: 200) [Size: 204]
Found: /secret_api (Status: 200) [Size: 152]
Found: /login.php (Status: 200) [Size: 450]
Found: /config.bak (Status: 200) [Size: 280]
===============================================================
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies hidden administrative interfaces and configuration backups.",
    ),

    # Task 3: Web Server Technology Fingerprinting
    LabTask(
        task_id="LAB-TASK-03",
        name="Web Server Technology & Header Fingerprinting",
        objective="Inspect HTTP response headers and web technology stack of the Mini-DVWA target to determine server engine and PHP versions.",
        target="http://127.0.0.1:8888",
        capability="service_fingerprinting",
        expected_tool_family="whatweb.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "technologies": ["Apache", "PHP"],
        },
        simulated_raw_output={
            "stdout": '{"target": "http://127.0.0.1:8888", "http_status": 200, "plugins": {"Apache": {"version": ["2.4.41"]}, "PHP": {"version": ["7.4.3"]}, "HTTPServer": {"string": ["Apache/2.4.41 (Ubuntu)"]}, "Title": {"string": ["Damn Vulnerable Web App (DVWA)"]}}}',
            "stderr": "",
            "exit_code": 0,
        },
        description="Fingerprints web application server versions and server-side runtimes.",
    ),

    # Task 4: SQL Injection Vulnerability Verification
    LabTask(
        task_id="LAB-TASK-04",
        name="SQL Injection Detection in Search Parameter",
        objective="Analyze the SQL injection endpoint /dvwa/vulnerabilities/sqli/?id=1 to detect SQL injection flaws and extract backend database version.",
        target="http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=1",
        capability="sql_injection_test",
        expected_tool_family="sqlmap.scan.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "vulnerabilities": ["SQL Injection"],
        },
        simulated_raw_output={
            "stdout": """---
Parameter: id (GET)
    Type: boolean-based blind
    Title: AND boolean-based blind - WHERE or HAVING clause
    Payload: id=1' AND 3422=3422 AND 'kairo'='kairo

    Type: error-based
    Title: MySQL >= 5.0 AND error-based - WHERE, HAVING, ORDER BY or GROUP BY clause (FLOOR)
    Payload: id=1' AND (SELECT 4112 FROM(SELECT COUNT(*),CONCAT(0x7170707671,(SELECT (ELT(4112=4112,1))),0x71706b7a71,FLOOR(RAND(0)*2))x FROM INFORMATION_SCHEMA.PLUGINS GROUP BY x)a) AND 'kairo'='kairo

    Type: UNION query
    Title: Generic UNION query (NULL) - 3 columns
    Payload: id=1' UNION ALL SELECT NULL,CONCAT(0x7170707671,0x5463517454,0x71706b7a71),NULL-- -
---
web server operating system: Linux Ubuntu 20.04
web application technology: Apache 2.4.41, PHP 7.4.3
back-end DBMS: MySQL >= 5.0.0 (MariaDB fork 10.4.17)
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Confirms parameter susceptibility to Boolean, Error, and Union SQL injection.",
    ),

    # Task 5: Web Application Vulnerability & Misconfiguration Scan
    LabTask(
        task_id="LAB-TASK-05",
        name="Web Vulnerability & Security Header Audit",
        objective="Scan the web target with Nikto to uncover missing security headers (CSP, X-Frame-Options), dangerous methods, and outdated software.",
        target="http://127.0.0.1:8888",
        capability="web_vulnerability_scan",
        expected_tool_family="nikto.scan.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "vulnerabilities": ["Missing Security Headers", "Clickjacking"],
        },
        simulated_raw_output={
            "stdout": """- Nikto v2.5.0
+ Target IP:          127.0.0.1
+ Target Hostname:    127.0.0.1
+ Target Port:        8888
+ Start Time:         2026-10-05 00:00:00 (GMT)
---------------------------------------------------------------------------
+ Server: Apache/2.4.41 (Ubuntu)
+ /: The anti-clickjacking X-Frame-Options header is not present. See https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options
+ /: The X-Content-Type-Options header is not set. This could allow the user agent to render the content of the site in a different fashion to the MIME type.
+ /: The Content-Security-Policy header is not present.
+ /dvwa/admin/: Directory indexing found or secret administrative interface exposed.
+ /dvwa/config.bak: Configuration file containing database credentials exposed on public webroot.
+ 5 host(s) tested
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Audits web misconfigurations, header omissions, and information leakage.",
    ),

    # Task 6: Exploit Intelligence Search
    LabTask(
        task_id="LAB-TASK-06",
        name="Known Exploit Database Correlation",
        objective="Query exploit intelligence databases for verified remote exploits affecting vsftpd 2.3.4 backdoor and OpenSSH 4.7p1.",
        target="vsftpd 2.3.4",
        capability="exploit_search",
        expected_tool_family="searchsploit.search.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "vulnerabilities": ["vsftpd 2.3.4 - Backdoor Command Execution"],
        },
        simulated_raw_output={
            "stdout": """------------------------------------------------------------------------ ---------------------------------
 Exploit Title                                                          |  Path
------------------------------------------------------------------------ ---------------------------------
vsftpd 2.3.4 - Backdoor Command Execution                               | unix/remote/49757.py
vsftpd 2.3.4 - Backdoor Command Execution (Metasploit)                  | unix/remote/17491.rb
------------------------------------------------------------------------ ---------------------------------
Shellcodes: No Results
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Correlates discovered service versions with weaponized exploit modules.",
    ),

    # Task 7: Credential Brute Force & Password Audit
    LabTask(
        task_id="LAB-TASK-07",
        name="Default Credential Testing & Authentication Audit",
        objective="Perform dictionary credential audit against login portal /dvwa/login.php to verify presence of default administrative accounts.",
        target="http://127.0.0.1:8888/dvwa/login.php",
        capability="credential_testing",
        expected_tool_family="hydra.brute.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "credentials": [{"username": "admin", "password": "password"}],
        },
        simulated_raw_output={
            "stdout": """Hydra v9.5 (c) 2023 by van Hauser / THC & David Maciejak - Please do not use in military or secret service organizations!
[DATA] max 16 tasks per 1 server, overall 16 tasks, 4 login tries (l:2/p:2), ~4 tries per task
[DATA] attacking http-get://127.0.0.1:8888/dvwa/login.php
[8888][http-get] host: 127.0.0.1   login: admin   password: password
1 of 1 target completed, 1 valid password found
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies default administrator credentials.",
    ),

    # Task 8: File Metadata & Secret Extraction
    LabTask(
        task_id="LAB-TASK-08",
        name="Exposed Backup Metadata & Secret Analysis",
        objective="Extract metadata, author information, and leaked secrets from the exposed configuration backup file config.bak.",
        target="config.bak",
        capability="file_metadata_analysis",
        expected_tool_family="exiftool.extract.v1",
        expected_evidence_class=EvidenceClass.FILE,
        expected_evidence_spec={
            "FileType": "PHP",
            "MIMEType": "text/x-php",
        },
        simulated_raw_output={
            "stdout": """[{
  "SourceFile": "config.bak",
  "ExifToolVersion": 12.40,
  "FileName": "config.bak",
  "Directory": "/dvwa",
  "FileSize": "284 bytes",
  "FileModifyDate": "2026:10:05 00:00:00+00:00",
  "FileType": "PHP",
  "FileTypeExtension": "php",
  "MIMEType": "text/x-php",
  "Comment": "Internal backup containing db_password and api_key"
}]""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Extracts file provenance, modification records, and embedded metadata.",
    ),

    # Task 9: Cryptographic Hash Identification
    LabTask(
        task_id="LAB-TASK-09",
        name="Credential Hash Type Identification",
        objective="Identify the hashing algorithm and salt structure of extracted password hash $1$admin$0123456789abcdef to assist offline recovery.",
        target="$1$admin$0123456789abcdef",
        capability="hash_identification",
        expected_tool_family="hashid.identify.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "technologies": ["MD5-Crypt", "Unix Crypt"],
        },
        simulated_raw_output={
            "stdout": """Analyzing '$1$admin$0123456789abcdef'
[+] MD5-Crypt [Hashcat Mode: 500]
[+] Cisco-IOS type 5 (MD5) [Hashcat Mode: 500]
[+] FreeBSD MD5 [Hashcat Mode: 500]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Determines password hash specification and Hashcat mode.",
    ),

    # Task 10: Autonomous Recovery & Resilient Fuzzing (Failure-Aware Challenge)
    LabTask(
        task_id="LAB-TASK-10",
        name="Failure-Aware Autonomous Recovery under Rate Throttling",
        objective="Execute web directory discovery against a rate-limited endpoint where initial gobuster run times out; autonomously heal by switching to ffuf with calibrated thread count and capture full recovery lineage.",
        target="http://127.0.0.1:8888/dvwa/",
        capability="web_directory_enum",
        expected_tool_family="gobuster.dir.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "endpoints": ["/admin", "/secret_api"],
        },
        recovery_challenge=True,
        recovery_trigger={
            "attempt_1_tool": "gobuster.dir.v1",
            "attempt_1_status": "timeout",
            "attempt_1_error": "Connection timed out after 30s: thread starvation on target port 8888",
            "attempt_2_tool": "ffuf.fuzz.v1",
            "attempt_2_args": {"threads": 5, "rate_limit": 50},
            "attempt_2_status": "success",
        },
        simulated_raw_output={
            "attempt_1": {
                "stdout": "Error: context deadline exceeded (Client.Timeout exceeded while awaiting headers)",
                "stderr": "ERROR: Timeout connecting to http://127.0.0.1:8888/dvwa/ after 30000ms",
                "exit_code": 124,
            },
            "attempt_2": {
                "stdout": r"""
        /'___\  /'___\           /'___\
       /\ \__/ /\ \__/  __  __  /\ \__/
       \ \ ,__\\ \ ,__\/\ \/\ \ \ \ ,__\
        \ \ \_/ \ \ \_/\ \ \_\ \ \ \ \_/
         \ \_\   \ \_\  \ \____/  \ \_\
          \/_/    \/_/   \/___/    \/_/

       v2.0.0-git
________________________________________________

 :: Method           : GET
 :: URL              : http://127.0.0.1:8888/dvwa/FUZZ
 :: Follow redirects : false
 :: Calibration      : false
 :: Timeout          : 10
 :: Threads          : 5
________________________________________________

admin                   [Status: 200, Size: 204, Words: 18, Lines: 8]
secret_api              [Status: 200, Size: 152, Words: 12, Lines: 6]
:: Progress: [20/20] :: Job [1/1] :: 10 req/sec :: Duration: [00:00:02] :: Errors: 0 ::
""",
                "stderr": "",
                "exit_code": 0,
            },
        },
        description="Tests autonomous tool swapping and causal recovery path recording when encountering execution timeouts.",
    ),
]


def get_task_by_id(task_id: str) -> Optional[LabTask]:
    """Retrieve a LabTask by its unique identifier."""
    for task in LAB_TASKS:
        if task.task_id == task_id:
            return task
    return None


def list_tasks() -> List[LabTask]:
    """Return all 10 versioned lab tasks."""
    return list(LAB_TASKS)
