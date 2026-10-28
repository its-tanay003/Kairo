# ADR-004: Permanent Removal of Tool Authorization Tiers

## Status
**Accepted and Enforced** (Supersedes previous Tier 1/2/3 authorization model)

## Date
2026-10-28

## Context
KAIRO originally employed a three-tier tool authorization classification:
* **Tier 1**: Passive Reconnaissance / OSINT / Local metadata / Non-intrusive lookup
* **Tier 2**: Active Scanning / Probing / Fuzzing / Port enumeration / Network capture
* **Tier 3**: Intrusive Testing / Exploitation / Brute-forcing / Arbitrary remote execution

In practice, this classification system introduced severe operational shortcomings:
1. **Unnecessary Friction**: In an explicitly authorized security assessment or dedicated lab workspace, operators faced repetitive, fragmented approval prompts simply because a tool was labeled "Tier 3", disrupting autonomous multi-step security investigations.
2. **False Security Boundary**: Dividing tools into arbitrary tiers created an illusion of safety without providing stronger target isolation than strict CIDR/target boundaries already deliver.
3. **Impediment to Autonomous Multi-Tool Orchestration**: Autonomous DAG planning and adaptive re-planning require selecting the right tool for the technical objective based on evidence, rather than navigating artificial tier hurdles.

## Decision
1. **Permanent Decommissioning of Tool Authorization Tiers**:
   - The Tier 1/2/3 classification system is permanently retired and removed from KAIRO.
   - All tool specifications, registry models, execution gateways, frontend chips, API schemas, and adapters shall not enforce or classify tools by execution tiers.
   - Any legacy `allowed_tool_tiers` configuration or stored database column is treated as deprecated and optional for backward compatibility with historical records, but never required for execution authorization.

2. **Unified Tool Access & Authorization Model**:
   Authorization is unified around the following foundational controls:
   - **Authenticated Operator Identity**: Cryptographically signed sessions or API tokens identifying the authorized operator.
   - **Configured Workspace & Scope Contract**: Cryptographically signed (HMAC-SHA256) boundaries specifying authorized targets, subnets (CIDR), and validity time windows.
   - **Target Boundary Enforcement**: Tools targeting hosts or subnets outside the active Scope Contract are rejected fail-closed with 403 `SCOPE_VIOLATION`.
   - **Execution Perimeter (ExecutionGateway)**: Every execution route (Conversational Chat, Task Planner, Kali VM Connector, GUI Adapters, Browser DAST) MUST route strictly through `ExecutionGateway.execute()` with comprehensive 20-field audit logging.
   - **Broad Command Execution Approval**: Arbitrary shell/command execution tools (`shell.run.v1`, `kali.exec.v1`) require verified operator credentials or explicit Scope Contract configuration rather than arbitrary string prefix bypasses (`KAIRO-WF-*` prefix bypass removed).

3. **Prevention of Tier System Return**:
   - Automated regression tests (`tests/test_tier_removal_regression.py`) enforce that no tool call is classified into tiers or blocked for tier reasons.
   - Future architectural changes must not reintroduce tool execution tiers unless explicitly mandated by system architecture revisions.

## Consequences
- **Positive**: Operators can run full-spectrum security assessments autonomously across authorized targets.
- **Positive**: Single, authoritative choke point (`ExecutionGateway`) guarantees 100% auditability without redundant permission dialogs.
- **Positive**: Reduced cognitive load on operators and agents.
- **Negative / Risk**: Operators must exercise diligence when defining Scope Contract targets, as all registered tools are permitted against in-scope assets.

