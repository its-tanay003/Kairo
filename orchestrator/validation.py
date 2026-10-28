"""
Argument validation and workflow approval policy engine for Kairo tool execution.

Enforces:
1. Typed schema validation: Ensures arguments match the ToolSpec schema (types, bounds, enums, required fields).
2. Input sanitization: Rejects command injection sequences in structured arguments.
3. Workflow approval gate: Restricts unrestricted command execution (shell.run.v1, kali.exec.v1)
   to explicitly approved workflows while favoring typed, validated security tool adapters.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple
from registry.loader import ToolSpec

logger = logging.getLogger("orchestrator.validation")

# Dangerous command injection metacharacter sequences
INJECTION_SEQS = [";", "&&", "||", "`", "$(", "|", "\n"]

# Broad command execution tool identifiers
BROAD_EXECUTION_TOOLS = {"shell.run.v1", "kali.exec.v1"}


def validate_tool_arguments(
    spec: ToolSpec,
    args: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Validates arguments against the tool's declared ToolSpec inputs schema.
    Returns (is_valid, errors).
    """
    errors: List[str] = []

    if not isinstance(args, dict):
        return False, ["Arguments must be provided as a dictionary."]

    inputs_schema = spec.inputs if isinstance(spec.inputs, dict) else {}
    props = inputs_schema.get("properties", {})
    required = inputs_schema.get("required", [])

    # 1. Required field checks
    for req_field in required:
        val = args.get(req_field)
        if val is None or (isinstance(val, str) and not val.strip()):
            # If property has default defined in schema, populate it
            if req_field in props and isinstance(props[req_field], dict) and "default" in props[req_field]:
                args[req_field] = props[req_field]["default"]
                continue
            # Check common synonyms
            synonyms = {
                "target": ["host", "domain", "url", "ip", "path"],
                "url": ["target", "host"],
                "domain": ["target", "host"],
                "host": ["target", "domain"],
            }
            found_synonym = False
            for syn in synonyms.get(req_field, []):
                if args.get(syn) is not None and str(args[syn]).strip():
                    found_synonym = True
                    break
            if not found_synonym:
                errors.append(f"Missing required parameter '{req_field}' for tool '{spec.id}'.")

    # 2. Type and bounds checking
    for key, val in args.items():
        if key in props and isinstance(props[key], dict):
            prop_def = props[key]
            expected_type = prop_def.get("type")

            if expected_type == "integer":
                try:
                    int_val = int(val)
                    if "minimum" in prop_def and int_val < prop_def["minimum"]:
                        errors.append(f"Parameter '{key}' value {int_val} below minimum {prop_def['minimum']}.")
                    if "maximum" in prop_def and int_val > prop_def["maximum"]:
                        errors.append(f"Parameter '{key}' value {int_val} exceeds maximum {prop_def['maximum']}.")
                except (ValueError, TypeError):
                    errors.append(f"Parameter '{key}' must be an integer, got '{type(val).__name__}'.")

            elif expected_type == "boolean":
                if not isinstance(val, bool) and str(val).lower() not in ("true", "false", "1", "0"):
                    errors.append(f"Parameter '{key}' must be a boolean.")

            elif expected_type == "array":
                if not isinstance(val, (list, tuple)):
                    errors.append(f"Parameter '{key}' must be a list/array.")

            elif expected_type == "string":
                if not isinstance(val, str):
                    errors.append(f"Parameter '{key}' must be a string, got '{type(val).__name__}'.")

            # Check enum constraints (case-insensitive comparison for CLI scan flags)
            if "enum" in prop_def and isinstance(prop_def["enum"], list):
                val_str = str(val).lower()
                enum_strs = [str(e).lower() for e in prop_def["enum"]]
                if val_str not in enum_strs:
                    errors.append(
                        f"Parameter '{key}' value '{val}' not in permitted choices: {prop_def['enum']}."
                    )

    # 3. Security sanitization: reject command injection sequences in typed tools
    if spec.id not in BROAD_EXECUTION_TOOLS:
        for k, v in args.items():
            if isinstance(v, str):
                for seq in INJECTION_SEQS:
                    if seq in v:
                        errors.append(
                            f"Security policy violation: detected command injection sequence '{seq}' in parameter '{k}'."
                        )

    return (len(errors) == 0, errors)


def is_workflow_approved(
    tool_id: str,
    requested_args: Dict[str, Any],
    scope_contract: Optional[Dict[str, Any]] = None,
    operator_token: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Checks whether unrestricted command execution is authorized for the given tool and request.
    Typed security tools are approved by default.
    Broad command-execution tools (shell.run.v1, kali.exec.v1) require explicit workflow approval.
    """
    # 1. Typed security tools are always allowed under standard Scope Contract rules
    if tool_id not in BROAD_EXECUTION_TOOLS:
        return True, "Typed security tool adapter approved."

    # 2. Check for trusted operator or cryptographically verified workflow approval token
    wf_tok = requested_args.get("workflow_token") or operator_token
    if wf_tok and isinstance(wf_tok, str):
        from orchestrator.auth import auth_manager
        is_valid, session, err = auth_manager.verify_token(wf_tok)
        if is_valid and session and session.role in ("admin", "operator"):
            return True, f"Authorized via verified operator token for {session.user_id} ({session.role})."
        return False, f"Invalid or unauthorized workflow approval token: {err or 'untrusted token'}"

    # 3. Check active Scope Contract metadata (authoritative configuration)
    if scope_contract:
        metadata = scope_contract.get("metadata", {})
        if metadata.get("allow_unrestricted_execution") is True or metadata.get("unrestricted_execution_approved") is True:
            return True, f"Unrestricted execution approved under Scope Contract '{scope_contract.get('contract_id')}'."

        allowed_broad = metadata.get("approved_broad_tools", [])
        if tool_id in allowed_broad:
            return True, f"Tool '{tool_id}' explicitly approved in Scope Contract '{scope_contract.get('contract_id')}'."

    # 4. Check explicit request flags (permitted only in dev mode when require_auth is False)
    from orchestrator.auth import auth_manager
    if not auth_manager.require_auth:
        if requested_args.get("approved_workflow") is True or requested_args.get("workflow_approved") is True:
            return True, "Explicit workflow approval granted in request parameters (development mode)."

    # Otherwise rejected
    rejection_msg = (
        f"Unrestricted command execution ({tool_id}) is restricted to explicitly approved workflows. "
        f"Please use a typed, validated tool adapter (e.g., nmap.scan.v1, gobuster.dir.v1, wpscan.audit.v1) "
        f"or request an explicitly approved workflow token/scope authorization."
    )
    return False, rejection_msg

