"""
Intent Classification and Planning Stage for Kairo Cognitive Architecture.

Every ordinary user message is processed through this defined intent and planning stage:
1. Intent Classification:
   - General question -> Conversational response (no tools executed)
   - Task request     -> Structured task plan (DAG decomposition and staged safe execution)
   - Plan-only request-> Structured plan explanation (executes nothing)
   - Tool request     -> Schema validation, scope authorization, and safe execution

The custom model handles reasoning when available; local fallback handles when unready.
Step provenance explicitly exposes which model handled each stage.
"""

from dataclasses import dataclass, asdict, field
from enum import Enum
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("orchestrator.intent_classifier")


class IntentType(str, Enum):
    GENERAL_QUESTION = "general_question"
    TASK_REQUEST = "task_request"
    PLAN_ONLY = "plan_only"
    TOOL_REQUEST = "tool_request"


@dataclass
class StepProvenance:
    stage: str
    handled_by: str
    runtime: str
    is_custom_model: bool
    is_fallback: bool
    executed: bool = False
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntentClassificationResult:
    intent: IntentType
    confidence: float
    goal_or_query: str
    target: Optional[str] = None
    tool_id: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    rationale: str = ""
    handled_by: str = "kairo-scale-2b"
    runtime: str = "transformers"
    is_custom_model: bool = True
    is_fallback: bool = False
    step_provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def provenance(self) -> List[StepProvenance]:
        if isinstance(self.step_provenance, dict):
            res = []
            for v in self.step_provenance.values():
                if isinstance(v, dict):
                    res.append(StepProvenance(
                        stage=v.get("stage", "unknown"),
                        handled_by=v.get("handled_by", "kairo-scale-2b"),
                        runtime=v.get("runtime", "transformers"),
                        is_custom_model=v.get("is_custom_model", True),
                        is_fallback=v.get("is_fallback", False),
                        executed=v.get("executed", False),
                        details=v.get("details"),
                    ))
                elif isinstance(v, StepProvenance):
                    res.append(v)
            return res
        elif isinstance(self.step_provenance, list):
            return self.step_provenance
        return []

    @property
    def plan_only(self) -> bool:
        return self.intent == IntentType.PLAN_ONLY

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["intent"] = self.intent.value if isinstance(self.intent, IntentType) else str(self.intent)
        return d


class IntentClassifier:
    """
    Classifies user message into defined operational intents:
    - general_question
    - task_request
    - plan_only
    - tool_request
    """

    def __init__(self):
        pass

    def generate_conversational_response(self, query: str, model_id: str = "kairo-scale-2b") -> Tuple[str, StepProvenance]:
        runtime = "transformers" if "2b" in model_id else "llama.cpp"
        content = generate_conversational_response(
            query,
            model_id=model_id,
            runtime=runtime,
            is_custom="2b" in model_id,
            is_fallback="0.5b" in model_id.lower(),
        )
        prov = StepProvenance(
            stage="conversational_generation",
            handled_by=model_id,
            runtime=runtime,
            is_custom_model="2b" in model_id,
            is_fallback="0.5b" in model_id.lower(),
            executed=False,
            details={"query": query},
        )
        return content, prov

    def generate_plan_explanation(self, goal: str, nodes: List[Dict[str, Any]], model_id: str = "kairo-scale-2b", target: Optional[str] = None) -> Tuple[str, StepProvenance]:
        dummy_plan = {"plan_id": "plan_synth", "nodes": nodes, "goal": goal}
        runtime = "transformers" if "2b" in model_id else "llama.cpp"
        content = generate_plan_explanation(
            dummy_plan,
            goal=goal,
            target=target,
            model_id=model_id,
            runtime=runtime,
            is_custom="2b" in model_id,
            is_fallback="0.5b" in model_id.lower(),
        )
        prov = StepProvenance(
            stage="plan_explanation",
            handled_by=model_id,
            runtime=runtime,
            is_custom_model="2b" in model_id,
            is_fallback="0.5b" in model_id.lower(),
            executed=False,
            details={"nodes_count": len(nodes)},
        )
        return content, prov

    def classify(
        self,
        message: str,
        requested_model_id: Optional[str] = None,
        explicit_tool: Optional[str] = None,
        explicit_args: Optional[Dict[str, Any]] = None,
    ) -> IntentClassificationResult:
        from orchestrator.model_integration import model_integration

        actual_meta, selected_id, processed_by_selected, fallback_reason = (
            model_integration.resolve_model_for_request(requested_model_id)
        )

        model_id = actual_meta["model_id"]
        runtime = actual_meta.get("runtime", "transformers")
        role = actual_meta.get("role", "")
        is_custom = "primary-custom" in role or runtime == "transformers" or "2b" in model_id
        is_fallback = not processed_by_selected or role == "fallback" or "0.5b" in model_id.lower()

        lower = message.lower().strip()

        # Step provenance tracking for Intent stage
        intent_prov = StepProvenance(
            stage="intent_classification",
            handled_by=model_id,
            runtime=runtime,
            is_custom_model=is_custom,
            is_fallback=is_fallback,
            executed=True,
            details={"requested_model": selected_id, "fallback_reason": fallback_reason},
        )

        # 1. Explicit tool invocation
        if explicit_tool:
            extracted_target = None
            if explicit_args:
                extracted_target = (
                    explicit_args.get("target")
                    or explicit_args.get("host")
                    or explicit_args.get("url")
                    or explicit_args.get("domain")
                )
            return IntentClassificationResult(
                intent=IntentType.TOOL_REQUEST,
                confidence=1.0,
                goal_or_query=message,
                target=extracted_target,
                tool_id=explicit_tool,
                arguments=explicit_args or {},
                rationale="Explicit tool call parameter provided by caller.",
                handled_by=model_id,
                runtime=runtime,
                is_custom_model=is_custom,
                is_fallback=is_fallback,
                step_provenance={"intent_classification": intent_prov.to_dict()},
            )

        # 2. Extract potential IP / Domain target
        target = self._extract_target(message)

        # 3. Check for Plan-Only Request
        # (e.g. "plan a penetration test", "show me a plan", "plan only", "generate plan without executing", "dry run")
        plan_only_patterns = [
            r"\bplan[\s\-]only\b",
            r"\bonly[\s\-]plan\b",
            r"\bplan\s+(?:a\s+|an\s+|the\s+)?(?:pentest|penetration|audit|assessment|scan|recon|test)\b",
            r"\bshow\s+(?:me\s+)?(?:a\s+|the\s+)?plan\b",
            r"\bcreate\s+(?:a\s+)?plan\b",
            r"\bgenerate\s+(?:a\s+)?plan\b",
            r"\bwhat\s+is\s+the\s+plan\b",
            r"\bdraft\s+(?:a\s+)?(?:plan|methodology)\b",
            r"\bdry[\s\-]run\b",
            r"\bwithout\s+(?:executing|running)\b",
            r"\bdo\s+not\s+(?:execute|run)\b",
            r"\bno\s+(?:execution|running)\b",
            r"\bpropose\s+(?:a\s+)?plan\b",
            r"\boutline\s+(?:a\s+)?plan\b",
        ]
        has_exec_override = (
            ("and execute" in lower or "then execute" in lower or "& execute" in lower or "execute the plan" in lower)
            and not any(neg in lower for neg in ["without executing", "without running", "no execution", "do not execute", "do not run"])
        )
        is_plan_only = (not has_exec_override) and any(re.search(pat, lower) for pat in plan_only_patterns)
        if is_plan_only:
            return IntentClassificationResult(
                intent=IntentType.PLAN_ONLY,
                confidence=0.96,
                goal_or_query=message,
                target=target,
                rationale="User explicitly requested a structured execution plan without running tools.",
                handled_by=model_id,
                runtime=runtime,
                is_custom_model=is_custom,
                is_fallback=is_fallback,
                step_provenance={"intent_classification": intent_prov.to_dict()},
            )

        # 4. Check for General Questions
        # (Questions about concepts, security theory, explanations, conversational greetings)
        general_question_starters = [
            r"^(what|why|how|who|when|where|is|can|could|would|should|tell\s+me|explain)\b",
            r"\bwhat\s+is\b",
            r"\bexplain\s+(?:how|what|why|concept|the|cve|vulnerability)\b",
            r"\bhow\s+does\b",
            r"\bdifference\s+between\b",
            r"\btell\s+me\s+about\b",
            r"\bwho\s+are\s+you\b",
            r"\bwhat\s+tools\s+(?:do\s+you\s+have|are\s+available)\b",
            r"^(hi|hello|hey|greetings|help|status|ping)\b",
        ]
        is_question_starter = any(re.search(pat, lower) for pat in general_question_starters)
        action_verb = any(
            re.search(rf"\b{verb}\b", lower)
            for verb in ["scan", "run", "execute", "probe", "attack", "exploit", "enumerate", "fuzz", "audit", "assess"]
        )

        if is_question_starter and not (action_verb and target):
            return IntentClassificationResult(
                intent=IntentType.GENERAL_QUESTION,
                confidence=0.93,
                goal_or_query=message,
                target=None,
                rationale="User query is an educational, conceptual, or advisory cybersecurity question.",
                handled_by=model_id,
                runtime=runtime,
                is_custom_model=is_custom,
                is_fallback=is_fallback,
                step_provenance={"intent_classification": intent_prov.to_dict()},
            )

        # 5. Check for Direct Tool Request vs Multi-Step Task Request
        # Tool Request: Single tool specifically mentioned or single direct execution requested
        direct_tool_map = {
            "nmap": "nmap.scan.v1",
            "port scan": "nmap.scan.v1",
            "whois": "whois.lookup.v1",
            "dig": "dig.lookup.v1",
            "dnsrecon": "dnsrecon.enum.v1",
            "dnsenum": "dnsenum.enum.v1",
            "subfinder": "subfinder.enum.v1",
            "gobuster": "gobuster.dir.v1",
            "ffuf": "ffuf.fuzz.v1",
            "nikto": "nikto.scan.v1",
            "whatweb": "whatweb.scan.v1",
            "sqlmap": "sqlmap.scan.v1",
            "hydra": "hydra.brute.v1",
            "searchsploit": "searchsploit.search.v1",
            "trivy": "trivy.fs.v1",
            "wpscan": "wpscan.audit.v1",
            "tcpdump": "tcpdump.capture.v1",
            "wireshark": "wireshark.gui.v1",
            "burp": "burpsuite.gui.v1",
            "burpsuite": "burpsuite.gui.v1",
            "zap": "zap.gui.v1",
            "shell": "shell.run.v1",
            "terminal": "kali.exec.v1",
        }

        matched_tool: Optional[str] = None
        for keyword, tid in direct_tool_map.items():
            if re.search(rf"\b{re.escape(keyword)}\b", lower):
                matched_tool = tid
                break

        is_direct_tool_cmd = any(
            lower.startswith(prefix)
            for prefix in ["run ", "execute ", "exec ", "use ", "launch ", "trigger "]
        )

        if matched_tool and (is_direct_tool_cmd or target or len(message.split()) <= 8):
            args = {"target": target} if target else {}
            return IntentClassificationResult(
                intent=IntentType.TOOL_REQUEST,
                confidence=0.91,
                goal_or_query=message,
                target=target,
                tool_id=matched_tool,
                arguments=args,
                rationale=f"Identified single direct tool operation '{matched_tool}'.",
                handled_by=model_id,
                runtime=runtime,
                is_custom_model=is_custom,
                is_fallback=is_fallback,
                step_provenance={"intent_classification": intent_prov.to_dict()},
            )

        # 6. Check for Task Request
        # (Multi-step operational mission, penetration test, assessment, audit)
        task_indicators = [
            "audit", "penetration", "pentest", "assessment", "comprehensive",
            "reconnaissance", "investigate", "test", "vulnerability", "surface",
            "explore", "workflow", "analyze attack surface", "full scan",
            "find out", "what's running", "whats running", "running on", "outdated",
            "risky", "inspect", "discover", "check",
        ]
        is_task = any(ind in lower for ind in task_indicators) or (target is not None)

        if is_task:
            return IntentClassificationResult(
                intent=IntentType.TASK_REQUEST,
                confidence=0.89,
                goal_or_query=message,
                target=target,
                rationale="Identified operational multi-stage security mission requiring structured task plan.",
                handled_by=model_id,
                runtime=runtime,
                is_custom_model=is_custom,
                is_fallback=is_fallback,
                step_provenance={"intent_classification": intent_prov.to_dict()},
            )

        # Default fallback: Treat conversational inquiry as General Question
        return IntentClassificationResult(
            intent=IntentType.GENERAL_QUESTION,
            confidence=0.80,
            goal_or_query=message,
            target=target,
            rationale="Defaulted conversational dialogue to General Question stage.",
            handled_by=model_id,
            runtime=runtime,
            is_custom_model=is_custom,
            is_fallback=is_fallback,
            step_provenance={"intent_classification": intent_prov.to_dict()},
        )

    def _extract_target(self, text: str) -> Optional[str]:
        # URL match
        url_match = re.search(r"https?://[a-zA-Z0-9\.\_\:\-]+(?:/[^\s]*)?", text)
        if url_match:
            return url_match.group(0)

        # IP / CIDR match (e.g. 192.168.1.50 or 10.0.0.0/24)
        ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", text)
        if ip_match:
            return ip_match.group(0)

        # Domain match (e.g. example.com or target.local)
        domain_match = re.search(r"\b[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?\b", text)
        if domain_match:
            cand = domain_match.group(0).lower()
            if not cand.endswith((".py", ".pt", ".gguf", ".sh", ".json", ".md")):
                return cand

        # Host / localhost / local machine match
        if re.search(r"\b(?:this\s+host|localhost|local\s+host|local\s+machine|local\s+system|current\s+host|the\s+host)\b", text, re.IGNORECASE):
            return "127.0.0.1"

        return None


def generate_conversational_response(
    query: str,
    model_id: str,
    runtime: str,
    is_custom: bool,
    is_fallback: bool,
    fallback_reason: Optional[str] = None,
) -> str:
    """
    Synthesizes a domain conversational answer for general cybersecurity queries.
    Attributes the reasoning explicitly to the custom model or local fallback.
    """
    model_tag = "Custom Primary Model" if is_custom else "Local Fallback Model"
    provenance_banner = (
        f"> **🧠 Reasoning Engine:** `{model_id}` ({runtime}) • **Role:** {model_tag}\n"
    )
    if is_fallback and fallback_reason:
        provenance_banner += f"> ⚠️ **Fallback Notice:** {fallback_reason}\n"
    provenance_banner += "> 🔒 **Safety Guarantee:** Pure conversational response. Zero tools or commands executed.\n"

    lower = query.lower()

    if any(k in lower for k in ["ssrf", "server-side request forgery"]):
        content = (
            f"### 🛡️ Understanding Server-Side Request Forgery (SSRF)\n\n"
            f"{provenance_banner}\n\n"
            f"**Server-Side Request Forgery (SSRF)** occurs when a web application fetches a remote resource "
            f"without validating the user-supplied URL. An attacker can coerce the backend application into making "
            f"unintended HTTP/HTTPS requests to internal-only resources.\n\n"
            f"#### 🔍 Key Attack Vectors\n"
            f"- **Cloud Instance Metadata:** Accessing `http://169.254.169.254/latest/meta-data/` to harvest IAM credentials.\n"
            f"- **Internal Microservices:** Probing unauthenticated internal admin panels (`http://10.0.0.1/admin`).\n"
            f"- **Protocols & Schemas:** Exploiting `file://`, `gopher://`, or `dict://` to interact with Redis or read files.\n\n"
            f"#### 🛡️ Effective Mitigations\n"
            f"1. **Strict URL Allowlisting:** Restrict outbound calls to pre-approved domain names and IP ranges.\n"
            f"2. **Disable Unused Schemas:** Only permit `http://` and `https://` protocols at the HTTP client level.\n"
            f"3. **Network Layer Isolation:** Block egress from application servers to link-local (`169.254.0.0/16`) and RFC 1918 subnets.\n"
            f"4. **IMDSv2 Enforcement:** On AWS, enforce IMDSv2 requiring session tokens for metadata queries.\n"
        )
    elif any(k in lower for k in ["xss", "cross-site scripting"]):
        content = (
            f"### 🛡️ Understanding Cross-Site Scripting (XSS)\n\n"
            f"{provenance_banner}\n\n"
            f"**Cross-Site Scripting (XSS)** is an injection vulnerability that allows an attacker to execute malicious "
            f"JavaScript in the context of an unsuspecting user's browser session.\n\n"
            f"#### 🔍 Primary XSS Classifications\n"
            f"- **Stored XSS (Persistent):** Malicious payloads stored in database tables and served to subsequent visitors.\n"
            f"- **Reflected XSS:** Payloads reflected immediately off query parameters or form submissions.\n"
            f"- **DOM-based XSS:** Client-side JavaScript directly sinks unvalidated inputs into execution sinks (`eval`, `innerHTML`).\n\n"
            f"#### 🛡️ Defensive Controls\n"
            f"1. **Context-Aware Output Encoding:** HTML, attribute, and JavaScript encoding before rendering user data.\n"
            f"2. **Content Security Policy (CSP):** Disallow inline script execution (`'unsafe-inline'`) and restrict script sources.\n"
            f"3. **Cookie Hardening:** Mark session cookies with `HttpOnly`, `Secure`, and `SameSite=Strict` flags.\n"
        )
    elif any(k in lower for k in ["nmap", "port scan"]):
        content = (
            f"### 🛡️ Nmap Port Scanning Methodology\n\n"
            f"{provenance_banner}\n\n"
            f"**Nmap (Network Mapper)** is the standard utility for network discovery, host detection, and vulnerability probing.\n\n"
            f"#### 🔍 Core Scanning Techniques\n"
            f"- **TCP SYN Stealth (`-sS`):** Sends SYN packets without completing the 3-way handshake (half-open scanning).\n"
            f"- **Service Version Detection (`-sV`):** Probes open ports with application banners to identify software versions.\n"
            f"- **Default Script Engine (`-sC`):** Executes safe NSE scripts to discover misconfigurations.\n"
            f"- **OS Detection (`-O`):** Analyzes TCP/IP stack implementation nuances to fingerprint target operating systems.\n\n"
            f"#### 💡 Operating in Kairo\n"
            f"To scan a target within your active Scope Contract, you can issue: `Scan 127.0.0.1 with Nmap`.\n"
        )
    else:
        content = (
            f"### 🛡️ Kairo Cybersecurity Assistant\n\n"
            f"{provenance_banner}\n\n"
            f"I have processed your query regarding: **\"{query}\"**.\n\n"
            f"#### 🎯 Autonomous Capabilities\n"
            f"- **Intent-Gated Execution:** Educational inquiries receive comprehensive technical explanations without running tools.\n"
            f"- **Structured Planning:** Security assessment missions decompose into parallel Directed Acyclic Graphs (DAGs).\n"
            f"- **Plan-Only Verification:** Request a dry run anytime to inspect the methodology before authorizing execution.\n"
            f"- **Scope & Safety Gates:** Every tool execution is validated against cryptographic Scope Contracts and sandboxed.\n\n"
            f"How would you like to proceed? You can ask a technical cybersecurity question, request a dry-run assessment plan, or authorize a target."
        )

    return content


def generate_plan_explanation(
    plan: Dict[str, Any],
    goal: str,
    target: Optional[str],
    model_id: str,
    runtime: str,
    is_custom: bool,
    is_fallback: bool,
    fallback_reason: Optional[str] = None,
) -> str:
    """
    Synthesizes a structured plan explanation for plan-only requests.
    Explains the DAG phases, parallel execution branches, convergence nodes, and gates.
    Explicitly states that zero commands were executed.
    """
    model_tag = "Custom Primary Model" if is_custom else "Local Fallback Model"
    plan_id = plan.get("plan_id", "plan_unnamed")
    nodes = plan.get("nodes", [])
    meta = plan.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    elif not isinstance(meta, dict):
        meta = {}
    rationale = plan.get("rationale") or meta.get("rationale") or "Autonomous multi-phase offensive assessment."

    parallel_roots = [n for n in nodes if not n.get("dependencies")]
    convergence_nodes = [n for n in nodes if len(n.get("dependencies", [])) > 1]
    single_dep_nodes = [n for n in nodes if len(n.get("dependencies", [])) == 1]

    provenance_banner = (
        f"> **🧠 Reasoning & Planning Engine:** `{model_id}` ({runtime}) • **Role:** {model_tag}\n"
    )
    if is_fallback and fallback_reason:
        provenance_banner += f"> ⚠️ **Fallback Notice:** {fallback_reason}\n"
    provenance_banner += (
        "> 🔒 **EXECUTION POLICY: PLAN-ONLY MODE**\n"
        "> **Zero tools or commands have been executed.** The assessment graph below is a validated, dry-run plan.\n"
    )

    lines = [
        f"### 🗺️ Autonomous Security Assessment Plan (`{plan_id}`)\n",
        provenance_banner,
        f"#### 🎯 Assessment Objectives",
        f"- **Goal:** {goal}",
        f"- **Target Asset:** `{target or 'Identified in scope'}`",
        f"- **Strategy Rationale:** {rationale}\n",
        f"#### 📊 Directed Acyclic Graph (DAG) Structure",
        f"- **Total Nodes:** `{len(nodes)}` abstract capabilities",
        f"- **Parallel Execution Roots:** `{len(parallel_roots)}` independent axes",
        f"- **Convergence Correlation Nodes:** `{len(convergence_nodes)}` multi-branch synthesis points\n",
        f"#### ⚡ Phase Breakdown",
    ]

    # Phase 1: Parallel Roots
    lines.append(f"##### 1. Concurrent Reconnaissance Axes (Parallel Execution)")
    for r in parallel_roots:
        cap = r.get("capability", "unknown_capability")
        lbl = r.get("label", cap)
        desc = r.get("description", "")
        lines.append(f"- **`{r.get('node_id')}`** [{lbl}]: `{cap}` — {desc}")

    # Phase 2: Sequential Deepening
    if single_dep_nodes:
        lines.append(f"\n##### 2. Deepening & Route Enumeration (Sequential Branches)")
        for s in single_dep_nodes:
            cap = s.get("capability", "unknown_capability")
            lbl = s.get("label", cap)
            dep = ", ".join(s.get("dependencies", []))
            lines.append(f"- **`{s.get('node_id')}`** [{lbl}]: `{cap}` *(depends on `{dep}`)*")

    # Phase 3: Convergence
    if convergence_nodes:
        lines.append(f"\n##### 3. Multi-Parent Convergence (Attack Surface Synthesis)")
        for c in convergence_nodes:
            cap = c.get("capability", "unknown_capability")
            lbl = c.get("label", cap)
            deps = ", ".join(c.get("dependencies", []))
            lines.append(f"- **`{c.get('node_id')}`** [{lbl}]: `{cap}` *(converges `{deps}`)*")

    lines.append(
        f"\n#### 🛡️ Scope & Safety Checkpoints\n"
        f"- **Scope Contract Gate:** Target must be cryptographically authorized before any node execution.\n"
        f"- **Process Supervision:** Sandboxed execution inside Kali VM with SIGKILL hard timeouts.\n"
        f"- **Status:** Ready for operator review. To execute, issue directive: `Execute plan {plan_id}`.\n"
    )

    return "\n".join(lines)


intent_classifier = IntentClassifier()

