---
name: report-formats
description: "Templates for three architecture deliverable types, selectable by report_type: Explainer (how does X work?), Review (is X well-designed?), and Redesign Proposal (how should X change?). Load this skill when generating architecture reports to ensure consistent structure, appropriate depth, and clear communication for each deliverable type."
---

# Report Formats

Three report templates for architecture deliverables. Select the template that matches your `report_type`:

| `report_type` | Question Answered | Primary Audience |
|---------------|-------------------|------------------|
| `explainer` | How does X work? | Engineers new to the system |
| `review` | Is X well-designed? | Tech leads, architects, reviewers |
| `redesign` | How should X change? | Decision-makers and implementers |

---

## 1. Explainer Report

**Purpose:** Answer the question "How does X work?" — give a reader who has never touched this code a clear mental model of the system.

**Audience:** Engineers joining the project, reviewers needing orientation, or anyone who needs to understand the system before modifying it.

### Template

```
# [Component/System Name]: Explainer

## Summary
One paragraph. What is this? What problem does it solve? What is the one thing a reader must understand about it?

## Key Concepts
List 3–6 concepts a reader must understand before the rest of the report makes sense.
For each:
- **Concept Name** — Definition. Why it matters. How it relates to the system.

## Architecture
High-level diagram showing the major components and how they relate.
[diagram]

Prose walkthrough of the diagram: what each component is responsible for, how they are connected, and what flows between them.

## How It Works
Step-by-step walkthrough of the primary flow. Each step should include a file:line reference.

1. **[Step name]** — `path/to/file.py:42` — What happens here. What data enters, what happens to it, what leaves.
2. **[Step name]** — `path/to/file.py:87` — ...
3. ...

Include a focused diagram for this flow if the step-by-step is hard to follow in prose alone.

## Key Interfaces
Table of the public interfaces (functions, classes, endpoints) that callers interact with.

| Interface | Location | Purpose | Key Parameters |
|-----------|----------|---------|----------------|
| `FunctionName(x, y)` | `path/to/file.py:12` | What it does | `x`: type — meaning |
| ... | | | |

## Dependencies
What does this component depend on? What depends on it?

**Depends on:**
- `dependency-name` (`path/to/dep`) — Why this dependency exists.

**Depended on by:**
- `consumer-name` (`path/to/consumer`) — How it uses this component.

## Things to Know
Gotchas, non-obvious behaviors, important constraints, and historical context that would save a new engineer time.

- **[Thing 1]** — Explanation.
- **[Thing 2]** — Explanation.
- ...
```

### Guidelines

1. **Write narrative, not bullet soup.** The Summary, Architecture, and How It Works sections should be prose a reader can follow from start to finish. Reserve bullets for lists that are genuinely enumerable (Key Concepts, Dependencies, Things to Know).

2. **Every code claim needs a file:line reference.** If you say "the router dispatches to handlers," show where: `router.py:34`. Readers should be able to verify every statement by opening the referenced file.

3. **Use pseudo-code to clarify non-obvious logic.** When a step in How It Works involves branching or transformation that is hard to describe in prose, include a short pseudo-code block. Keep it short — 5–10 lines maximum.

4. **Diagrams are required for Architecture; optional elsewhere.** The Architecture section must include a diagram. The How It Works section should include one if the step-by-step flow is hard to follow linearly. Do not add diagrams for decoration.

5. **No evaluation in an Explainer.** Do not comment on whether the design is good or bad. That belongs in a Review. The Explainer's only job is to build an accurate mental model.

---

## 2. Review Report

**Purpose:** Answer the question "Is X well-designed?" — render a verdict with supporting evidence, highlight risks, and provide actionable recommendations.

**Audience:** Tech leads making go/no-go decisions, architects assessing code before merge, teams planning refactoring work.

### Template

```
# [Component/System Name]: Review

## Verdict
**[SOUND | CONCERNS | NEEDS REFACTORING]**

One paragraph justifying the verdict. What drove this conclusion? What is the single most important thing a reader should take away?

- **SOUND** — The design is appropriate for its purpose. Proceed with confidence.
- **CONCERNS** — Specific issues exist that warrant attention before scaling or extending this component.
- **NEEDS REFACTORING** — Structural problems make this component risky to extend. Refactoring is recommended before significant new work.

## Scope
- **Reviewed:** What was examined (files, components, interfaces, tests).
- **Focus:** What lens was applied (correctness, performance, maintainability, security, testability).
- **Not Reviewed:** Explicitly call out what was out of scope to bound the verdict.

## Findings
Each finding follows this structure:

### [Finding Title]
- **What:** Clear description of what was found.
- **Where:** `path/to/file.py:42` — specific location.
- **Assessment:** [STRENGTH | CONCERN | PROBLEM] — Why this matters.
- **Impact:** What goes wrong (or right) because of this?

Severity definitions:
- **STRENGTH** — A design decision done well. Worth noting so it is preserved and replicated.
- **CONCERN** — An issue that may cause problems under certain conditions. Worth tracking and addressing.
- **PROBLEM** — An issue that is likely to cause failures, make the system hard to change, or create security/correctness risks. Needs fixing.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk description] | Low / Medium / High | Low / Medium / High | What would reduce this risk |
| ... | | | |

## Recommendations

### Must Fix
Issues that should be resolved before this component is used in production or extended further.
1. [Specific, actionable recommendation with file references where applicable]

### Should Fix
Issues that are important but do not block current use.
1. [Specific, actionable recommendation]

### Consider
Improvements worth discussing that involve tradeoffs or significant scope.
1. [Specific, actionable recommendation with the tradeoff named]
```

### Guidelines

1. **Every finding needs a code reference.** Claims without evidence are opinions. Each CONCERN and PROBLEM must include a `file:line` reference. If you cannot point to specific code, the finding is not ready to include.

2. **Recommendations must be concrete.** "Improve error handling" is not a recommendation. "Add error handling for the nil-pointer case at `processor.py:78` — currently a missing key raises an unhandled exception that crashes the worker" is a recommendation.

3. **Name the strengths.** A Review that lists only problems trains teams to hide their work. STRENGTH findings show what good looks like in this codebase and make the verdict more credible.

4. **Call out tradeoffs, not just problems.** Many design decisions are reasonable given constraints. A finding that says "this trades off X for Y — that may be the right call given Z, but it means W will be harder later" is more useful than "this is bad."

5. **Ground every finding in the architecture rubric.** Findings should connect to properties of well-designed systems (cohesion, coupling, testability, correctness, performance, security). Avoid style opinions and preference-based criticism.

---

## 3. Redesign Proposal

**Purpose:** Answer the question "How should X change?" — propose a specific design, justify the choices, and give implementers a path forward.

**Audience:** Decision-makers who must approve the work, engineers who will implement it, and anyone who needs to understand why the change is being made.

### Template

```
# [Component/System Name]: Redesign Proposal

## Executive Summary
Two to four sentences. What is being proposed? Why? What is the expected outcome? What is the scope?

## Current State

### How It Works
Brief description of the existing design (3–5 sentences or a short How It Works walkthrough). Link to a full Explainer if one exists.

[diagram of current state]

### What's Wrong
The specific problems with the current design that motivate this proposal. Each problem should connect to a concrete symptom (failure mode, performance issue, maintenance burden).

- **Problem 1** — Description. Evidence: `path/to/file.py:line`. Symptom: what goes wrong.
- **Problem 2** — ...

## Proposed Design

### Overview
One paragraph describing the new design at a high level. What changes? What stays the same?

[diagram of proposed design]

### Key Changes

| Area | Current | Proposed | Reason |
|------|---------|----------|--------|
| [Component/interface/flow] | What it does now | What it will do | Why this change |
| ... | | | |

### Detailed Design
The full specification of the new design. This section must be detailed enough for an engineer to implement without significant design decisions left unresolved.

For each significant component or interface:

**[Component Name]**
Responsibility, key invariants, interface.

```pseudo
// Example or pseudo-code for non-obvious logic
function process(input: Input): Output {
    validate(input)
    result = transform(input)
    return result
}
```

## Tradeoff Analysis

| Dimension | Current Design | Proposed Design |
|-----------|---------------|-----------------|
| Complexity | Assessment | Assessment |
| Performance | Assessment | Assessment |
| Testability | Assessment | Assessment |
| Migration cost | — | Assessment |
| [Other relevant dimension] | Assessment | Assessment |

## Migration Path

### Phase 1: [Name]
What happens in this phase. What is deliverable at the end. What can be deployed independently.

### Phase 2: [Name]
What happens in this phase. Dependencies on Phase 1. What is deliverable.

### Phase 3: [Name]
What happens in this phase. Final state. What is removed or cleaned up.

## What This Doesn't Solve
Explicitly call out problems that this proposal does not address. This prevents scope creep during implementation and sets honest expectations.

- **[Problem not addressed]** — Why it is out of scope or requires a separate proposal.
```

### Guidelines

1. **The Detailed Design must be implementable.** An engineer picking up this proposal should not face major design decisions that were left open. Unresolved questions belong in a separate section before the proposal is finalized, not hidden in vague descriptions.

2. **Migration Path is not optional.** Systems in production cannot be replaced atomically. Every proposal must include a phased path that keeps the system operational at each phase boundary. If you cannot define a migration path, the proposal is not ready.

3. **Name the tradeoffs honestly.** Every design involves tradeoffs. The Tradeoff Analysis should include at least one dimension where the proposed design is worse than the current one. A proposal that claims pure improvement signals incomplete analysis.

4. **Scope management is the author's responsibility.** If reviewers will want to extend the proposal to solve adjacent problems, address that proactively in "What This Doesn't Solve." Keep the proposal focused on the problems it names in Current State.
