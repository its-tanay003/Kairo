# /registry - Declarative ToolSpec Definitions & Schema Registry

The `/registry` directory is the single source of truth for all tools available to Kairo's autonomous agents. Every tool is defined declaratively as a YAML specification conforming to a formal 16-field JSON schema (`registry/schema/toolspec.schema.json`).

---

## The 16-Field Blueprint Schema

Every ToolSpec strictly implements all 16 specification fields:

```yaml
id: string                    # Unique tool identifier (e.g. nmap.scan.v1, burpsuite.gui.v1)
binary: string                # Executable binary path or command name
category: string              # Classification (recon, web_audit, vulnerability_scan, exploit, etc.)
capabilities: [string]        # Capability tokens declaring functionality
inputs: object                # Parameter definitions with types, descriptions, defaults, requirements
outputs: object               # Return attributes, output formats, and artifacts
side_effects: [string]        # Declared external side effects (network_scan, process_fork, disk_write)
privilege: string             # Privilege requirement (user, elevated, root, admin, kernel, guest)
gui: boolean | object         # GUI interaction requirement or display metadata
parser: string | object       # Output parser strategy (nmap_xml, nikto_csv, json, plain_text)
prerequisites: [string]       # Runtime packages or environment requirements
docs: string | object         # Embedded reference documentation, usage guide, and examples
success_signals: object       # Exit codes, patterns, and indicators of successful execution
failure_signals: object       # Failure codes, timeout conditions, and error patterns
rollback: string | object     # Rollback strategy, compensating action, or snapshot revert
version_compatibility: obj    # Supported agent versions and OS matrix
```

---

## Tool Catalog (27 Production Tools)

### 1. Network & Domain Reconnaissance (Tier 1 & Tier 2)

- [`nmap_scan_v1.yaml`](tools/nmap_scan_v1.yaml): Host discovery, port scanning, OS fingerprinting, and NSE scripts.
- [`subfinder_enum_v1.yaml`](tools/subfinder_enum_v1.yaml): Passive subdomain enumeration across open data sources.
- [`dnsrecon_enum_v1.yaml`](tools/dnsrecon_enum_v1.yaml): Comprehensive DNS record enumeration and zone transfers.
- [`dnsenum_enum_v1.yaml`](tools/dnsenum_enum_v1.yaml): DNS information gathering and dictionary brute-forcing.
- [`dig_lookup_v1.yaml`](tools/dig_lookup_v1.yaml): Direct DNS queries and resolver inspection.
- [`whois_lookup_v1.yaml`](tools/whois_lookup_v1.yaml): Domain registration, registrar, and IP ownership lookup.

### 2. Web Application Security & Fuzzing (Tier 2)

- [`nikto_scan_v1.yaml`](tools/nikto_scan_v1.yaml): Web server vulnerability and misconfiguration scanning.
- [`gobuster_dir_v1.yaml`](tools/gobuster_dir_v1.yaml): High-speed directory and file path discovery.
- [`ffuf_fuzz_v1.yaml`](tools/ffuf_fuzz_v1.yaml): Ultra-fast web fuzzer for endpoints, headers, and parameters.
- [`whatweb_scan_v1.yaml`](tools/whatweb_scan_v1.yaml): Web technology fingerprinting and CMS detection.
- [`wpscan_audit_v1.yaml`](tools/wpscan_audit_v1.yaml): Specialized WordPress vulnerability and plugin auditor.
- [`sqlmap_scan_v1.yaml`](tools/sqlmap_scan_v1.yaml): Automated SQL injection detection and database takeover.

### 3. Vulnerability Scanning, Exploitation & Credentials (Tier 2)

- [`trivy_fs_v1.yaml`](tools/trivy_fs_v1.yaml): Filesystem vulnerability and misconfiguration scanner.
- [`searchsploit_search_v1.yaml`](tools/searchsploit_search_v1.yaml): Offline Exploit-DB search and exploit locator.
- [`metasploit_rpc_v1.yaml`](tools/metasploit_rpc_v1.yaml): Metasploit Framework RPC integration for verified exploit payloads.
- [`hydra_brute_v1.yaml`](tools/hydra_brute_v1.yaml): Multi-protocol network login brute-force tool (SSH, FTP, HTTP).
- [`hashid_identify_v1.yaml`](tools/hashid_identify_v1.yaml): Cryptographic hash format identifier.
- [`exiftool_extract_v1.yaml`](tools/exiftool_extract_v1.yaml): Metadata extraction from documents and images.
- [`tcpdump_capture_v1.yaml`](tools/tcpdump_capture_v1.yaml): Network packet capture and protocol analysis.

### 4. Interactive Desktop GUI Security Tools (Tier 3)

- [`burpsuite_gui_v1.yaml`](tools/burpsuite_gui_v1.yaml): Burp Suite Professional / Community interactive web proxy.
- [`wireshark_gui_v1.yaml`](tools/wireshark_gui_v1.yaml): Wireshark interactive packet capture and deep inspection.
- [`zap_gui_v1.yaml`](tools/zap_gui_v1.yaml): OWASP ZAP interactive proxy and vulnerability scanner.

### 5. Automated Security Browser & Execution Utilities

- [`browser_security_v1.yaml`](tools/browser_security_v1.yaml): Playwright-driven security browser for automated web auditing.
- [`shell_run_v1.yaml`](tools/shell_run_v1.yaml): Supervised local host command execution with process limits.
- [`kali_exec_v1.yaml`](tools/kali_exec_v1.yaml): Isolated Kali Linux VM remote execution.
- [`system_ping.yaml`](tools/system_ping.yaml): Network latency and host reachability check.
- [`hello_world.yaml`](tools/hello_world.yaml): Conformance baseline tool for end-to-end pipe testing.

---

## Load-Time Verification

Both Python and TypeScript loaders enforce fail-fast startup:

**Python (`registry/loader.py`)**:

```python
from registry.loader import ToolRegistry
registry = ToolRegistry() # Validates all YAML specs against JSON schema
```

**TypeScript (`registry/loader.ts`)**:

```typescript
import { ToolRegistry } from "./registry/loader";
const registry = new ToolRegistry();
```

**Test Command**:

```bash
python -m pytest tests/test_toolspec_registry.py -v
```
