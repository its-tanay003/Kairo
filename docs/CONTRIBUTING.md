# KAIRO: Contributing Guidelines & Developer Standards

> **Guidelines for Contributing Code, ToolSpecs, Documentation, and Test Suites**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Safety & Responsible Disclosure Guidelines](#1-safety--responsible-disclosure-guidelines)
2. [Development Environment Setup](#2-development-environment-setup)
3. [Monorepo Coding Standards](#3-monorepo-coding-standards)
   - [3.1 Python Backend (`/orchestrator`, `/sdk`, `/lab`)](#31-python-backend-orchestrator-sdk-lab)
   - [3.2 TypeScript Gateway (`/gateway`)](#32-typescript-gateway-gateway)
   - [3.3 Next.js & React UI (`/ui`)](#33-nextjs--react-ui-ui)
4. [Testing & Conformance Verification](#4-testing--conformance-verification)
5. [Adding a New ToolSpec (Step-by-Step)](#5-adding-a-new-toolspec-step-by-step)
6. [Pull Request Checklist](#6-pull-request-checklist)

---

## 1. Safety & Responsible Disclosure Guidelines

KAIRO is an autonomous security auditing framework designed strictly for defensive analysis, security education, authorized penetration testing, and red-team operations on infrastructure you own or have explicit written permission to test.

- **Never hardcode production targets, live credentials, or unauthorized exploits.**
- **All new tools must enforce strict CIDR scope validation and declare appropriate privilege tiers.**
- **Adhere to the Zero-Trust safety architecture at all times.**

---

## 2. Development Environment Setup

Ensure you have completed the prerequisites in [`docs/DEPLOYMENT_AND_SETUP.md`](file:///c:/New%20Volume%20(D)/dev/docs/DEPLOYMENT_AND_SETUP.md):

- Python 3.11+
- Node.js 18+ with `npm`
- Git

Verify your environment by running:

```bash
python tests/test_boundary.py
```

---

## 3. Monorepo Coding Standards

### 3.1 Python Backend (`/orchestrator`, `/sdk`, `/lab`)

- Use explicit type annotations on all function signatures (`typing.Dict`, `typing.Optional`, `pydantic.BaseModel`).
- Format with `black` (line length 100).
- Docstrings required for all public methods following Google docstring conventions.
- Never use bare `except:` blocks; capture specific exceptions and log failure narratives.

### 3.2 TypeScript Gateway (`/gateway`)

- Strict TypeScript configuration (`noImplicitAny: true`, `strictNullChecks: true`).
- All incoming WebSocket payloads must be validated against runtime schemas before routing.
- Keep event handlers lightweight and asynchronous.

### 3.3 Next.js & React UI (`/ui`)

- Follow the **Anthropic Claude UI archetype** strictly:
  - Use centralized CSS custom properties in `globals.css` (`--bg-app: #181816`, `--accent: #d97757`).
  - Never introduce ad-hoc bright gradients, fluorescent blues, or arbitrary inline hex colors.
  - Maintain progressive disclosure: Keep the primary view focused on conversation; sequester developer fixtures in the Advanced Console drawer.
  - Zero tolerance for React DOM removal errors (`removeChild` / `NotFoundError`). Always maintain stable DOM element hierarchies.

---

## 4. Testing & Conformance Verification

Before submitting any Pull Request, ensure that all master test suites pass cleanly:

```bash
# 1. Master Consolidated Engineering Suite (104 Tests - 100% Pass)
python -m pytest tests/test_execution_gateway.py tests/test_model_integration.py tests/test_model_intent_flow.py tests/test_dag_controller.py tests/test_trustworthy_execution.py tests/test_toolspec_registry.py tests/test_scope_contract.py tests/test_workspace_and_auth_gateway.py tests/test_execution_plane_and_tauri.py tests/test_tool_selection.py -q

# 2. Execution Gateway & Scope Security Tests
python -m pytest tests/test_execution_gateway.py tests/test_scope_contract.py -v

# 3. ToolSpec 7-Gate Conformance Engine CLI
python -m sdk verify-toolspec registry/tools/subfinder_enum_v1.yaml

# 4. Model Center & Grammar Constraint Verification
python -m pytest tests/test_model_center.py -v
```

---

## 5. Adding a New ToolSpec (Step-by-Step)

1. **Scaffold the blueprint**:

   ```bash
   python -m sdk create-toolspec yourtool.action.v1 --category recon --binary yourtool
   ```

2. **Define the 16-field YAML**: Fill in `inputs`, `outputs`, `capabilities`, and `docs` in `registry/tools/yourtool_action_v1.yaml`.
3. **Write the adapter & parser**: Implement `build_args()` and `parse()` in `sdk/tools/yourtool_action_v1/`.
4. **Run 7-Gate Conformance**:

   ```bash
   python -m sdk verify-toolspec registry/tools/yourtool_action_v1.yaml
   ```

5. **Commit the YAML blueprint, adapter, parser, and conformance test.**

---

## 6. Pull Request Checklist

- [ ] Code adheres to style guides (`black` for Python, `eslint` for TS/React).
- [ ] New ToolSpecs pass all 7 automated conformance gates.
- [ ] UI changes maintain the Anthropic Claude design tokens and aesthetic quiet.
- [ ] All automated tests pass (`python tests/test_boundary.py` and `python scripts/test_runtime_errors.py`).
- [ ] Documentation updated in `README.md`, `DESIGN.md`, and relevant `/docs` guides.
- [ ] Commit messages follow conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`).
