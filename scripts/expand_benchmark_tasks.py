"""
Script to expand LAB_TASKS from 10 to exactly 50 tasks in lab/tasks.py.
Covers all 18 cybersecurity tools in the Kairo registry and multiple recovery challenges.
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
TASKS_FILE = ROOT_DIR / "lab" / "tasks.py"

content_tasks_11_to_50 = r'''
    # =========================================================================
    # FORMAL INTERNAL BENCHMARK HARNESS - EXTENDED TASKS (LAB-TASK-11 to 50)
    # Target: 50 Tasks covering all 18 Tools and diverse attack vectors
    # =========================================================================

    # Task 11: Host Live Detection / ICMP Ping Sweep
    LabTask(
        task_id="LAB-TASK-11",
        name="Local Subnet Host Live Detection",
        objective="Verify if lab target 127.0.0.1 is responsive and active on the network interface.",
        target="127.0.0.1",
        capability="host_live_detection",
        expected_tool_family="system_ping",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "hosts": ["127.0.0.1"],
        },
        simulated_raw_output={
            "stdout": "PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.\n64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.045 ms\n1 packets transmitted, 1 received, 0% packet loss",
            "stderr": "",
            "exit_code": 0,
        },
        description="Verifies host availability using network ICMP echo requests.",
    ),

    # Task 12: Comprehensive TCP SYN Port Enumeration
    LabTask(
        task_id="LAB-TASK-12",
        name="Aggressive Service & Port Scanning",
        objective="Perform aggressive TCP port scan against lab host 127.0.0.1:8889 to detect SSH and HTTP service versions.",
        target="127.0.0.1:8889",
        capability="network_port_scan",
        expected_tool_family="nmap.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "ports": [22, 80],
            "hosts": ["127.0.0.1"],
        },
        simulated_raw_output={
            "stdout": """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" version="7.94">
<host starttime="1600000000" endtime="1600000005">
  <status state="up" reason="conn-ack"/>
  <address addr="127.0.0.1" addrtype="ipv4"/>
  <ports>
    <port protocol="tcp" portid="22"><state state="open" reason="syn-ack"/><service name="ssh" product="OpenSSH" version="4.7p1"/></port>
    <port protocol="tcp" portid="80"><state state="open" reason="syn-ack"/><service name="http" product="Apache" version="2.2.8"/></port>
  </ports>
</host>
</nmaprun>""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies open SSH and HTTP services on lab host.",
    ),

    # Task 13: DNS Service Port Verification
    LabTask(
        task_id="LAB-TASK-13",
        name="DNS Daemon Port Scan",
        objective="Scan port 53 on 127.0.0.1 to detect active named / bind9 DNS resolution listeners.",
        target="127.0.0.1:53",
        capability="network_port_scan",
        expected_tool_family="nmap.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "ports": [53],
        },
        simulated_raw_output={
            "stdout": """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" version="7.94">
<host starttime="1600000000" endtime="1600000005">
  <status state="up" reason="conn-ack"/>
  <address addr="127.0.0.1" addrtype="ipv4"/>
  <ports>
    <port protocol="tcp" portid="53"><state state="open" reason="syn-ack"/><service name="domain" product="BIND" version="9.4.2"/></port>
  </ports>
</host>
</nmaprun>""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Checks for listening DNS service on port 53.",
    ),

    # Task 14: OS Fingerprinting & Kernel Detection
    LabTask(
        task_id="LAB-TASK-14",
        name="Operating System Fingerprinting",
        objective="Execute TCP/IP stack fingerprinting on 127.0.0.1 to determine underlying Linux distribution and kernel generation.",
        target="127.0.0.1",
        capability="os_fingerprint",
        expected_tool_family="nmap.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "technologies": ["Linux"],
        },
        simulated_raw_output={
            "stdout": """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" version="7.94">
<host starttime="1600000000" endtime="1600000005">
  <status state="up" reason="conn-ack"/>
  <address addr="127.0.0.1" addrtype="ipv4"/>
  <os><osmatch name="Linux 2.6.9 - 2.6.33" accuracy="98"/></os>
</host>
</nmaprun>""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Determines operating system family and kernel baseline.",
    ),

    # Task 15: Setup & Diagnostic Endpoint Discovery
    LabTask(
        task_id="LAB-TASK-15",
        name="Diagnostic & Setup Web Directory Scan",
        objective="Scan http://127.0.0.1:8888/dvwa/ to detect exposed setup.php and phpinfo diagnostics.",
        target="http://127.0.0.1:8888/dvwa/",
        capability="web_directory_enum",
        expected_tool_family="gobuster.dir.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "endpoints": ["/setup.php", "/phpinfo.php"],
        },
        simulated_raw_output={
            "stdout": """
Found: /setup.php (Status: 200) [Size: 1200]
Found: /phpinfo.php (Status: 200) [Size: 84000]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Locates web installation and diagnostic configuration endpoints.",
    ),

    # Task 16: API Route Fuzzing under Rate Limits (Recovery Challenge)
    LabTask(
        task_id="LAB-TASK-16",
        name="Resilient API Route Fuzzing (Rate Limit Recovery)",
        objective="Fuzz API routes on http://127.0.0.1:8888/api/v1/FUZZ; autonomously recover when rate-limited (HTTP 429) by throttling request frequency.",
        target="http://127.0.0.1:8888/api/v1/FUZZ",
        capability="web_fuzzing",
        expected_tool_family="ffuf.fuzz.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "endpoints": ["/users", "/tokens"],
        },
        recovery_challenge=True,
        recovery_trigger={
            "attempt_1_tool": "ffuf.fuzz.v1",
            "attempt_1_status": "rate_limited",
            "attempt_1_error": "HTTP 429 Too Many Requests: Rate limit exceeded",
            "attempt_2_tool": "ffuf.fuzz.v1",
            "attempt_2_args": {"threads": 2, "rate_limit": 20},
            "attempt_2_status": "success",
        },
        simulated_raw_output={
            "attempt_1": {
                "stdout": "HTTP 429 Too Many Requests",
                "stderr": "Rate limit exceeded: 100 requests / min limit reached",
                "exit_code": 1,
            },
            "attempt_2": {
                "stdout": """
users                   [Status: 200, Size: 412, Words: 32, Lines: 12]
tokens                  [Status: 200, Size: 180, Words: 14, Lines: 5]
""",
                "stderr": "",
                "exit_code": 0,
            },
        },
        description="Fuzzes internal API routes with automated recovery on rate limit enforcement.",
    ),

    # Task 17: Query Parameter Fuzzing
    LabTask(
        task_id="LAB-TASK-17",
        name="Web Parameter Discovery",
        objective="Fuzz hidden HTTP GET parameters on http://127.0.0.1:8888/search.php?FUZZ=1 to identify debug/admin override toggles.",
        target="http://127.0.0.1:8888/search.php?FUZZ=1",
        capability="web_fuzzing",
        expected_tool_family="ffuf.fuzz.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "endpoints": ["debug"],
        },
        simulated_raw_output={
            "stdout": """
debug                   [Status: 200, Size: 1450, Words: 80, Lines: 25]
admin                   [Status: 200, Size: 1200, Words: 60, Lines: 20]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies hidden administrative and debug query parameters.",
    ),

    # Task 18: Sensitive File Extension Fuzzing (.env, .git)
    LabTask(
        task_id="LAB-TASK-18",
        name="Sensitive File & Backup Enumeration",
        objective="Scan http://127.0.0.1:8888/ for leaked environment configuration files (.env, .git/HEAD).",
        target="http://127.0.0.1:8888/",
        capability="web_directory_enum",
        expected_tool_family="gobuster.dir.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "endpoints": ["/.env", "/.git/HEAD"],
        },
        simulated_raw_output={
            "stdout": """
Found: /.env (Status: 200) [Size: 320]
Found: /.git/HEAD (Status: 200) [Size: 23]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Detects exposed source repository headers and environment configuration files.",
    ),

    # Task 19: HTTP Security Header Inspection
    LabTask(
        task_id="LAB-TASK-19",
        name="HTTP Header & CSP Fingerprinting",
        objective="Inspect HTTP response headers of http://127.0.0.1:8888/ to identify missing security headers (HSTS, CSP, X-Frame-Options).",
        target="http://127.0.0.1:8888/",
        capability="service_fingerprinting",
        expected_tool_family="whatweb.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "technologies": ["Apache", "PHP"],
        },
        simulated_raw_output={
            "stdout": '{"target": "http://127.0.0.1:8888/", "http_status": 200, "plugins": {"Apache": {"version": ["2.4.41"]}, "PHP": {"version": ["7.4.3"]}}}',
            "stderr": "",
            "exit_code": 0,
        },
        description="Assesses security posture via response header and technology inspection.",
    ),

    # Task 20: PHP Engine Version Fingerprinting
    LabTask(
        task_id="LAB-TASK-20",
        name="PHP Interpreter Version Identification",
        objective="Probe http://127.0.0.1:8888/dvwa/ to pinpoint the exact PHP runtime build and installed modules.",
        target="http://127.0.0.1:8888/dvwa/",
        capability="service_fingerprinting",
        expected_tool_family="whatweb.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "technologies": ["PHP"],
        },
        simulated_raw_output={
            "stdout": '{"target": "http://127.0.0.1:8888/dvwa/", "http_status": 200, "plugins": {"PHP": {"version": ["7.4.3"]}}}',
            "stderr": "",
            "exit_code": 0,
        },
        description="Fingerprints backend programming runtime.",
    ),

    # Task 21: CMS & Blog Platform Identification
    LabTask(
        task_id="LAB-TASK-21",
        name="Content Management System Identification",
        objective="Identify whether target web service http://127.0.0.1:8888/wordpress/ runs WordPress and extract version tag.",
        target="http://127.0.0.1:8888/wordpress/",
        capability="service_fingerprinting",
        expected_tool_family="whatweb.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "technologies": ["WordPress"],
        },
        simulated_raw_output={
            "stdout": '{"target": "http://127.0.0.1:8888/wordpress/", "http_status": 200, "plugins": {"WordPress": {"version": ["5.8.1"]}}}',
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies CMS presence and release version.",
    ),

    # Task 22: Secondary Metasploitable Web Service Inspection
    LabTask(
        task_id="LAB-TASK-22",
        name="Metasploitable Web Banner Grab",
        objective="Perform banner grab on Metasploitable Apache web server port http://127.0.0.1:8889.",
        target="http://127.0.0.1:8889",
        capability="service_fingerprinting",
        expected_tool_family="whatweb.scan.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "technologies": ["Apache"],
        },
        simulated_raw_output={
            "stdout": '{"target": "http://127.0.0.1:8889", "http_status": 200, "plugins": {"Apache": {"version": ["2.2.8"]}}}',
            "stderr": "",
            "exit_code": 0,
        },
        description="Collects HTTP banner details on auxiliary web service.",
    ),

    # Task 23: Web Server Misconfiguration & Directory Listing Audit
    LabTask(
        task_id="LAB-TASK-23",
        name="Directory Listing & Information Leak Scan",
        objective="Scan http://127.0.0.1:8888/ with Nikto to detect enabled directory indexing and exposed backup scripts.",
        target="http://127.0.0.1:8888/",
        capability="web_vulnerability_scan",
        expected_tool_family="nikto.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["directory indexing", "backup"],
        },
        simulated_raw_output={
            "stdout": """- Nikto v2.1.6
+ Target IP:          127.0.0.1
+ Target Hostname:    127.0.0.1
+ Target Port:        8888
+ Server: Apache/2.4.41 (Ubuntu)
+ [VULN] /icons/: Directory indexing found.
+ [VULN] /config.bak: Backup file found containing configuration settings.
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Detects web directory indexing and exposed backup artifacts.",
    ),

    # Task 24: Insecure Cookie Flags & Session Management Audit
    LabTask(
        task_id="LAB-TASK-24",
        name="Session Cookie Security Audit",
        objective="Audit http://127.0.0.1:8888/dvwa/ for session cookies missing HttpOnly and Secure protection flags.",
        target="http://127.0.0.1:8888/dvwa/",
        capability="web_vulnerability_scan",
        expected_tool_family="nikto.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["HttpOnly", "cookie"],
        },
        simulated_raw_output={
            "stdout": """- Nikto v2.1.6
+ [VULN] The anti-clickjacking X-Frame-Options header is not present.
+ [VULN] Cookie PHPSESSID created without the httponly flag.
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies cookies susceptible to client-side script extraction.",
    ),

    # Task 25: SSL/TLS Insecure Cipher & Certificate Scan
    LabTask(
        task_id="LAB-TASK-25",
        name="SSL/TLS Cipher Suite Vulnerability Audit",
        objective="Scan HTTPS port http://127.0.0.1:8443/ for outdated SSLv3/TLS 1.0 protocols and weak CBC cipher suites.",
        target="http://127.0.0.1:8443/",
        capability="web_vulnerability_scan",
        expected_tool_family="nikto.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["SSL", "ciphers"],
        },
        simulated_raw_output={
            "stdout": """- Nikto v2.1.6
+ Target Port: 8443
+ [VULN] Server allows SSLv3 which is vulnerable to POODLE attack.
+ [VULN] Weak cipher suite RC4-SHA supported.
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Checks cryptographic protocol strength on HTTPS endpoints.",
    ),

    # Task 26: Dangerous HTTP Method Verification (PUT/DELETE)
    LabTask(
        task_id="LAB-TASK-26",
        name="HTTP Method Vulnerability Verification",
        objective="Inspect http://127.0.0.1:8888/webdav/ to determine if dangerous HTTP PUT or DELETE verbs are enabled.",
        target="http://127.0.0.1:8888/webdav/",
        capability="web_vulnerability_scan",
        expected_tool_family="nikto.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["PUT", "WebDAV"],
        },
        simulated_raw_output={
            "stdout": """- Nikto v2.1.6
+ [VULN] /webdav/: HTTP methods PUT and DELETE are allowed, which may permit unauthorized file upload.
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Discovers dangerous WebDAV and arbitrary file write capabilities.",
    ),

    # Task 27: Error-Based SQL Injection Verification
    LabTask(
        task_id="LAB-TASK-27",
        name="Error-Based SQL Injection Audit",
        objective="Verify vulnerability to SQL error injection on parameter 'id' at http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=1&Submit=Submit.",
        target="http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=1&Submit=Submit",
        capability="sql_injection_test",
        expected_tool_family="sqlmap.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["boolean-based blind", "UNION query"],
        },
        simulated_raw_output={
            "stdout": """
[INFO] testing 'AND boolean-based blind - WHERE or HAVING clause'
[INFO] parameter 'id' is vulnerable:
Type: boolean-based blind
Title: AND boolean-based blind - WHERE or HAVING clause
Payload: id=1' AND 2854=2854 AND 'WlUv'='WlUv&Submit=Submit

Type: UNION query
Title: Generic UNION query (NULL) - 2 columns
Payload: id=1' UNION ALL SELECT NULL,CONCAT('qkkzq','payload','qvvxq')-- -&Submit=Submit
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Confirms exploitable error and boolean SQL injection vectors.",
    ),

    # Task 28: Blind Time-Based SQLi Assessment (Recovery Challenge)
    LabTask(
        task_id="LAB-TASK-28",
        name="Time-Based SQLi with Tamper Script (Recovery Challenge)",
        objective="Assess blind SQL injection on http://127.0.0.1:8888/dvwa/vulnerabilities/sqli_blind/?id=1&Submit=Submit; recover when WAF drops queries by applying space-to-comment tamper scripts.",
        target="http://127.0.0.1:8888/dvwa/vulnerabilities/sqli_blind/?id=1&Submit=Submit",
        capability="sql_injection_test",
        expected_tool_family="sqlmap.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["time-based blind"],
        },
        recovery_challenge=True,
        recovery_trigger={
            "attempt_1_tool": "sqlmap.scan.v1",
            "attempt_1_status": "waf_blocked",
            "attempt_1_error": "Connection reset by peer: WAF rule triggered on spaces",
            "attempt_2_tool": "sqlmap.scan.v1",
            "attempt_2_args": {"tamper": "space2comment", "time_sec": 5},
            "attempt_2_status": "success",
        },
        simulated_raw_output={
            "attempt_1": {
                "stdout": "[WARNING] HTTP error 403 Forbidden: WAF block detected",
                "stderr": "WAF blocked payload containing unescaped spaces",
                "exit_code": 1,
            },
            "attempt_2": {
                "stdout": """
[INFO] testing 'MySQL >= 5.0.12 AND time-based blind (query SLEEP)'
[INFO] parameter 'id' is vulnerable:
Type: time-based blind
Title: MySQL >= 5.0.12 AND time-based blind (query SLEEP)
Payload: id=1'/**/AND/**/(SELECT/**/5502/**/FROM/**/(SELECT(SLEEP(5)))Poxf)--/**/gqPz&Submit=Submit
""",
                "stderr": "",
                "exit_code": 0,
            },
        },
        description="Executes time-based SQL injection with autonomous tamper script recovery.",
    ),

    # Task 29: Database Management System Fingerprinting via SQLi
    LabTask(
        task_id="LAB-TASK-29",
        name="Database Engine & Version Fingerprinting",
        objective="Identify backend database engine and exact version on target http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=2&Submit=Submit.",
        target="http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=2&Submit=Submit",
        capability="sql_injection_test",
        expected_tool_family="sqlmap.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "technologies": ["MySQL"],
        },
        simulated_raw_output={
            "stdout": """
[INFO] the back-end DBMS is MySQL
web server operating system: Linux Ubuntu
web application technology: Apache 2.4.41, PHP 7.4.3
back-end DBMS: MySQL >= 5.0.12 (5.7.35-0ubuntu0.18.04.1)
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Discovers database engine release and hosting environment.",
    ),

    # Task 30: Database Schema Enumeration
    LabTask(
        task_id="LAB-TASK-30",
        name="Database Table Schema Enumeration",
        objective="Extract table names from database 'dvwa' via SQL injection at http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=3&Submit=Submit.",
        target="http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=3&Submit=Submit",
        capability="sql_injection_test",
        expected_tool_family="sqlmap.scan.v1",
        expected_evidence_class=EvidenceClass.REPORT,
        expected_evidence_spec={
            "vulnerabilities": ["SQL injection"],
        },
        simulated_raw_output={
            "stdout": """
Database: dvwa
[2 tables]
+----------+
| guestbook|
| users    |
+----------+
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Lists database schema tables through SQL injection extraction.",
    ),

    # Task 31: VSFTPD Backdoor Exploit Search
    LabTask(
        task_id="LAB-TASK-31",
        name="VSFTPD 2.3.4 Backdoor Exploit Identification",
        objective="Query Exploit Database for known remote root backdoor exploits targeting vsftpd 2.3.4.",
        target="vsftpd 2.3.4",
        capability="exploit_search",
        expected_tool_family="searchsploit.search.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "vulnerabilities": ["Backdoor Command Execution"],
        },
        simulated_raw_output={
            "stdout": """--------------------------------------------------------------------------------------------------------- ---------------------------------
 Exploit Title                                                                                           |  Path
--------------------------------------------------------------------------------------------------------- ---------------------------------
vsftpd 2.3.4 - Backdoor Command Execution                                                               | unix/remote/49757.py
vsftpd 2.3.4 - Backdoor Command Execution (Metasploit)                                                  | unix/remote/17491.rb
--------------------------------------------------------------------------------------------------------- ---------------------------------
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies weaponized exploits for vulnerable FTP service.",
    ),

    # Task 32: Apache 2.2.8 Public Vulnerability Query
    LabTask(
        task_id="LAB-TASK-32",
        name="Apache HTTP Server Exploit Query",
        objective="Search exploit archives for public denial-of-service and remote code execution vulnerabilities affecting Apache 2.2.8.",
        target="Apache 2.2.8",
        capability="exploit_search",
        expected_tool_family="searchsploit.search.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "vulnerabilities": ["Remote Denial of Service"],
        },
        simulated_raw_output={
            "stdout": """--------------------------------------------------------------------------------------------------------- ---------------------------------
 Exploit Title                                                                                           |  Path
--------------------------------------------------------------------------------------------------------- ---------------------------------
Apache 2.2.x - Remote Denial of Service                                                                 | multiple/dos/8261.py
Apache mod_isapi - Dangling Pointer Remote Code Execution                                                | windows/remote/11650.py
--------------------------------------------------------------------------------------------------------- ---------------------------------
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Matches discovered web server version to published CVE PoCs.",
    ),

    # Task 33: OpenSSH 4.7p1 Security Advisory Search
    LabTask(
        task_id="LAB-TASK-33",
        name="OpenSSH Legacy Vulnerability Lookup",
        objective="Retrieve public security advisories and exploit details for OpenSSH 4.7p1.",
        target="OpenSSH 4.7p1",
        capability="exploit_search",
        expected_tool_family="searchsploit.search.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "vulnerabilities": ["Information Disclosure"],
        },
        simulated_raw_output={
            "stdout": """--------------------------------------------------------------------------------------------------------- ---------------------------------
 Exploit Title                                                                                           |  Path
--------------------------------------------------------------------------------------------------------- ---------------------------------
OpenSSH < 7.4 - Information Disclosure / User Enumeration                                                | linux/remote/40113.txt
--------------------------------------------------------------------------------------------------------- ---------------------------------
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies information disclosure vectors against legacy SSH daemon.",
    ),

    # Task 34: Metasploit Samba Module Resolution
    LabTask(
        task_id="LAB-TASK-34",
        name="Metasploit Exploit Module Lookup",
        objective="Identify Metasploit RPC exploit module matching Samba trans2open vulnerability.",
        target="samba trans2open",
        capability="metasploit_exploit",
        expected_tool_family="metasploit.rpc.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "vulnerabilities": ["trans2open"],
        },
        simulated_raw_output={
            "stdout": """
Matching Modules:
1. exploit/linux/samba/trans2open - Samba trans2open Overflow (Linux x86) - Rank: Great
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Resolves Metasploit exploit modules for remote buffer overflow.",
    ),

    # Task 35: SSH Administrative Credential Testing
    LabTask(
        task_id="LAB-TASK-35",
        name="SSH Root Password Audit",
        objective="Test common administrative passwords against SSH service at 127.0.0.1:22 for user root.",
        target="127.0.0.1:22",
        capability="credential_testing",
        expected_tool_family="hydra.brute.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "credentials": [{"username": "root", "password": "toor"}],
        },
        simulated_raw_output={
            "stdout": """[DATA] attacking ssh://127.0.0.1:22/
[22][ssh] host: 127.0.0.1   login: root   password: toor
1 of 1 target completed, 1 valid password found
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Audits SSH service for default and weak administrator credentials.",
    ),

    # Task 36: FTP Credential Audit under Connection Throttling (Recovery Challenge)
    LabTask(
        task_id="LAB-TASK-36",
        name="FTP Password Audit with Connection Throttling Recovery",
        objective="Perform credential audit against FTP at 127.0.0.1:21; recover from server connection throttling by reducing concurrent tasks.",
        target="127.0.0.1:21",
        capability="credential_testing",
        expected_tool_family="hydra.brute.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "credentials": [{"username": "msfadmin", "password": "msfadmin"}],
        },
        recovery_challenge=True,
        recovery_trigger={
            "attempt_1_tool": "hydra.brute.v1",
            "attempt_1_status": "throttled",
            "attempt_1_error": "[ERROR] Child failed: too many connections from your IP",
            "attempt_2_tool": "hydra.brute.v1",
            "attempt_2_args": {"tasks": 1, "wait_sec": 3},
            "attempt_2_status": "success",
        },
        simulated_raw_output={
            "attempt_1": {
                "stdout": "[ERROR] Server 127.0.0.1 refused connection (too many connections)",
                "stderr": "Service connection limit reached",
                "exit_code": 1,
            },
            "attempt_2": {
                "stdout": """[DATA] attacking ftp://127.0.0.1:21/
[21][ftp] host: 127.0.0.1   login: msfadmin   password: msfadmin
1 of 1 target completed, 1 valid password found
""",
                "stderr": "",
                "exit_code": 0,
            },
        },
        description="Executes resilient FTP credential audit handling connection concurrency limits.",
    ),

    # Task 37: HTTP Basic Authentication Audit
    LabTask(
        task_id="LAB-TASK-37",
        name="HTTP Basic Auth Credential Audit",
        objective="Audit restricted HTTP directory http://127.0.0.1:8888/restricted/ protected by HTTP Basic Authentication.",
        target="http://127.0.0.1:8888/restricted/",
        capability="credential_testing",
        expected_tool_family="hydra.brute.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "credentials": [{"username": "admin", "password": "password123"}],
        },
        simulated_raw_output={
            "stdout": """[DATA] attacking http-get://127.0.0.1:8888/restricted/
[8888][http-get] host: 127.0.0.1   login: admin   password: password123
1 of 1 target completed, 1 valid password found
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies valid credentials protecting administrative HTTP realm.",
    ),

    # Task 38: MySQL Database Empty Password Audit
    LabTask(
        task_id="LAB-TASK-38",
        name="MySQL Root Empty Password Audit",
        objective="Check if MySQL service at 127.0.0.1:3306 allows administrative access with empty or default root password.",
        target="127.0.0.1:3306",
        capability="credential_testing",
        expected_tool_family="hydra.brute.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "credentials": [{"username": "root", "password": ""}],
        },
        simulated_raw_output={
            "stdout": """[DATA] attacking mysql://127.0.0.1:3306/
[3306][mysql] host: 127.0.0.1   login: root   password: <empty>
1 of 1 target completed, 1 valid password found
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Detects critical unauthenticated root access on database daemon.",
    ),

    # Task 39: PDF Forensic Metadata Analysis
    LabTask(
        task_id="LAB-TASK-39",
        name="PDF Report Forensic Metadata Inspection",
        objective="Extract author provenance, creation software, and internal paths from audit_report.pdf.",
        target="audit_report.pdf",
        capability="file_metadata_analysis",
        expected_tool_family="exiftool.extract.v1",
        expected_evidence_class=EvidenceClass.FILE,
        expected_evidence_spec={
            "FileType": "PDF",
        },
        simulated_raw_output={
            "stdout": """[{
  "SourceFile": "audit_report.pdf",
  "FileName": "audit_report.pdf",
  "FileType": "PDF",
  "Author": "Chief Security Officer",
  "Creator": "Internal Word Processor v4"
}]""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Extracts document author and creation tool signatures.",
    ),

    # Task 40: JPEG Image EXIF & Geolocation Extraction
    LabTask(
        task_id="LAB-TASK-40",
        name="Image EXIF Geolocation Extraction",
        objective="Analyze evidence.jpg to extract camera model and GPS coordinates.",
        target="evidence.jpg",
        capability="file_metadata_analysis",
        expected_tool_family="exiftool.extract.v1",
        expected_evidence_class=EvidenceClass.FILE,
        expected_evidence_spec={
            "FileType": "JPEG",
        },
        simulated_raw_output={
            "stdout": """[{
  "SourceFile": "evidence.jpg",
  "FileName": "evidence.jpg",
  "FileType": "JPEG",
  "CameraModel": "Canon EOS 80D",
  "GPSLatitude": "37 deg 46' 29.88\" N",
  "GPSLongitude": "122 deg 25' 9.84\" W"
}]""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Extracts embedded geographic and hardware metadata from image files.",
    ),

    # Task 41: Word Document Metadata Inspection
    LabTask(
        task_id="LAB-TASK-41",
        name="DOCX Document Author & Company Metadata Inspection",
        objective="Extract revision history, company name, and last modifying user from resume.docx.",
        target="resume.docx",
        capability="file_metadata_analysis",
        expected_tool_family="exiftool.extract.v1",
        expected_evidence_class=EvidenceClass.FILE,
        expected_evidence_spec={
            "FileType": "DOCX",
        },
        simulated_raw_output={
            "stdout": """[{
  "SourceFile": "resume.docx",
  "FileName": "resume.docx",
  "FileType": "DOCX",
  "Company": "Acme Cyber Defense Corp",
  "LastModifiedBy": "Lead Analyst"
}]""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Recovers corporate organizational identities from office document metadata.",
    ),

    # Task 42: Firmware Image Metadata & Architecture Extraction
    LabTask(
        task_id="LAB-TASK-42",
        name="Embedded Firmware File Header Analysis",
        objective="Inspect binary file firmware.bin to identify target processor architecture and timestamp.",
        target="firmware.bin",
        capability="file_metadata_analysis",
        expected_tool_family="exiftool.extract.v1",
        expected_evidence_class=EvidenceClass.FILE,
        expected_evidence_spec={
            "FileType": "BIN",
        },
        simulated_raw_output={
            "stdout": """[{
  "SourceFile": "firmware.bin",
  "FileName": "firmware.bin",
  "FileType": "BIN",
  "CPUArchitecture": "ARM Cortex-M4",
  "BuildTimestamp": "2026-10-01 12:00:00"
}]""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies architecture and build flags from compiled firmware images.",
    ),

    # Task 43: SHA-256 Cryptographic Hash Identification
    LabTask(
        task_id="LAB-TASK-43",
        name="SHA-256 Hash Algorithm Identification",
        objective="Determine algorithm family for hexadecimal hash 5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8.",
        target="5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
        capability="hash_identification",
        expected_tool_family="hashid.identify.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "technologies": ["SHA-256"],
        },
        simulated_raw_output={
            "stdout": """Analyzing '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8'
[+] SHA-256 [Hashcat Mode: 1400]
[+] Haval-256 [Hashcat Mode: 1400]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Classifies cryptographic hash as SHA-256 with Hashcat mode 1400.",
    ),

    # Task 44: Bcrypt Hash Identification
    LabTask(
        task_id="LAB-TASK-44",
        name="Bcrypt Password Hash Identification",
        objective="Identify format and cost factor for salted hash $2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW.",
        target="$2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW",
        capability="hash_identification",
        expected_tool_family="hashid.identify.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "technologies": ["Blowfish", "Bcrypt"],
        },
        simulated_raw_output={
            "stdout": """Analyzing '$2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW'
[+] Blowfish(OpenBSD) [Hashcat Mode: 3200]
[+] Bcrypt [Hashcat Mode: 3200]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Identifies Bcrypt/Blowfish algorithm specification.",
    ),

    # Task 45: Windows NTLM Hash Identification
    LabTask(
        task_id="LAB-TASK-45",
        name="Windows NTLM Hash Identification",
        objective="Identify hash type for 32-character string 31d6cfe0d16ae931b73c59d7e0c089c0 extracted from memory dump.",
        target="31d6cfe0d16ae931b73c59d7e0c089c0",
        capability="hash_identification",
        expected_tool_family="hashid.identify.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "technologies": ["NTLM"],
        },
        simulated_raw_output={
            "stdout": """Analyzing '31d6cfe0d16ae931b73c59d7e0c089c0'
[+] NTLM [Hashcat Mode: 1000]
[+] MD4 [Hashcat Mode: 900]
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Recognizes Windows NT LAN Manager (NTLM) authentication hash.",
    ),

    # Task 46: DNS Forward Resolution & MX Record Query
    LabTask(
        task_id="LAB-TASK-46",
        name="DNS Domain Record Enumeration",
        objective="Perform DNS query for lab.local to resolve IPv4 A record and mail exchange (MX) hosts.",
        target="lab.local",
        capability="dns_lookup",
        expected_tool_family="dig.lookup.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "dns_records": [{"type": "A", "value": "127.0.0.1"}],
        },
        simulated_raw_output={
            "stdout": """; <<>> DiG 9.16.1-Ubuntu <<>> lab.local
;; ANSWER SECTION:
lab.local.		300	IN	A	127.0.0.1
lab.local.		300	IN	MX	10 mail.lab.local.
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Enumerates authoritative DNS mapping for internal lab domain.",
    ),

    # Task 47: Domain WHOIS Registration & Registrar Lookup
    LabTask(
        task_id="LAB-TASK-47",
        name="WHOIS Domain Intelligence Query",
        objective="Retrieve domain registrar, creation date, and administrative contact data for example-lab.org.",
        target="example-lab.org",
        capability="domain_whois_lookup",
        expected_tool_family="whois.lookup.v1",
        expected_evidence_class=EvidenceClass.ANALYTIC,
        expected_evidence_spec={
            "metadata": {"domain_name": "example-lab.org"},
        },
        simulated_raw_output={
            "stdout": """Domain Name: example-lab.org
Registry Domain ID: D1234567-LROR
Registrar: Example Registrar LLC
Creation Date: 2020-01-15T00:00:00Z
Registry Expiry Date: 2028-01-15T00:00:00Z
Registrant Organization: Cyber Security Lab Operations
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Collects registration metadata and registrar provenance via WHOIS.",
    ),

    # Task 48: Reverse DNS PTR Record Resolution
    LabTask(
        task_id="LAB-TASK-48",
        name="Reverse DNS Pointer Lookup",
        objective="Perform reverse DNS lookup on IP address 127.0.0.1 to extract PTR hostname record.",
        target="127.0.0.1",
        capability="dns_lookup",
        expected_tool_family="dig.lookup.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "dns_records": [{"type": "PTR"}],
        },
        simulated_raw_output={
            "stdout": """; <<>> DiG 9.16.1-Ubuntu <<>> -x 127.0.0.1
;; ANSWER SECTION:
1.0.0.127.in-addr.arpa.	300	IN	PTR	localhost.
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Performs in-addr.arpa reverse DNS hostname resolution.",
    ),

    # Task 49: Network Traffic Capture & PCAP Sniffing
    LabTask(
        task_id="LAB-TASK-49",
        name="Network Interface Packet Sniffing",
        objective="Capture packet traffic on loopback interface lo during reconnaissance execution.",
        target="lo",
        capability="network_traffic_capture",
        expected_tool_family="tcpdump.capture.v1",
        expected_evidence_class=EvidenceClass.NETWORK,
        expected_evidence_spec={
            "metadata": {"packets_captured": 10},
        },
        simulated_raw_output={
            "stdout": """tcpdump: listening on lo, link-type EN10MB (Ethernet), capture size 262144 bytes
10 packets captured
10 packets received by filter
0 packets dropped by kernel
""",
            "stderr": "",
            "exit_code": 0,
        },
        description="Captures raw packet traces for evidentiary forensic audit.",
    ),

    # Task 50: Kali Environment Pipeline Sanity & Execution
    LabTask(
        task_id="LAB-TASK-50",
        name="Kali Environment Execution & Pipeline Sanity",
        objective="Execute container pipeline health check in Kali execution environment.",
        target="127.0.0.1",
        capability="command_execution",
        expected_tool_family="shell.run.v1",
        expected_evidence_class=EvidenceClass.COMMAND,
        expected_evidence_spec={
            "metadata": {"status": "ok"},
        },
        simulated_raw_output={
            "stdout": '{"status": "ok", "environment": "kali-rolling", "uptime": "up 12 hours"}',
            "stderr": "",
            "exit_code": 0,
        },
        description="Validates agent execution shell and sandbox readiness.",
    ),
'''

def update_tasks_file():
    text = TASKS_FILE.read_text(encoding="utf-8")
    target = '        description="Tests autonomous tool swapping and causal recovery path recording when encountering execution timeouts.",\n    ),\n]'
    if target not in text:
        raise ValueError("Target anchor not found in lab/tasks.py")
    
    replacement = '        description="Tests autonomous tool swapping and causal recovery path recording when encountering execution timeouts.",\n    ),' + content_tasks_11_to_50 + '\n]\n\nBENCHMARK_TASKS: List[LabTask] = LAB_TASKS\n'
    updated = text.replace(target, replacement, 1)
    TASKS_FILE.write_text(updated, encoding="utf-8")
    print(f"Successfully updated {TASKS_FILE}!")


if __name__ == "__main__":
    update_tasks_file()

