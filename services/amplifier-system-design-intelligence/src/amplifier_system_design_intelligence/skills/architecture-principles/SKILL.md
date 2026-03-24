---
name: architecture-principles
description: "Senior engineer architectural evaluation framework. Contains questions, rubrics, pattern/anti-pattern catalogs, cross-cutting checklists, and agentic-era principles. Designed to be curated and evolved over time — the compounding value is the point. Load this skill when evaluating architecture, reviewing designs, or applying structured judgment to code."
---

# Architecture Principles

A living catalog of architectural evaluation methodology. This skill encodes the questions a senior/principal engineer asks, the rubrics they apply, and the patterns they recognize. It is designed to be curated and extended over time with hard-won experience from real projects.

**How to use this skill:** The architecture-critic agent loads sections selectively based on the surveyor's recommendations. You can also load it directly in a main session for ad-hoc evaluation. Don't apply every rubric to every problem — select what's relevant.

---

## 1. The Senior Engineer Questions

When encountering any component, module, or system, ask these questions in order. The first three establish understanding; the rest probe design quality.

### Understanding Questions

1. **What is this responsible for?** — Can you state its purpose in one sentence without using "and"? If not, it may have too many responsibilities.
2. **Who are its consumers?** — What calls this? What depends on its interface? Is the consumer set known and bounded, or open-ended?
3. **What are its dependencies?** — What does it import, call, or assume exists? Are dependencies explicit (injected, imported) or implicit (global state, environment variables, file system layout)?

### Design Quality Questions

4. **What happens when this fails?** — Is the failure mode explicit? Does the caller know what to do? Is there a partial success state that's worse than a clean failure?
5. **Is this reinventing something the language, framework, or ecosystem already provides?** — Check standard library, well-known packages, and framework conventions before accepting custom implementations. But also check: does the existing solution actually fit, or would using it require more glue code than the custom version?
6. **Are there established patterns for this?** — Is this a known problem shape (registry, pipeline, strategy, observer)? If so, does the implementation follow the pattern or create a novel variant that's harder to recognize?
7. **What would a new team member need to know?** — Is the design self-explaining from code, or does it require oral tradition? Could an agent (or a human with no context) understand this from the code and its immediate surroundings?
8. **What's the blast radius of a change?** — If I modify this component, what else breaks? Is the blast radius proportional to the importance of the change?
9. **Is this the simplest thing that could work?** — Not the most clever, most general, or most future-proof — the simplest. Complexity must justify itself with concrete, current requirements.
10. **Does this component have a clear lifecycle?** — How is it created, configured, used, and torn down? Are these phases explicit or muddled together?

---

## 2. Evaluation Rubrics

### Coupling Assessment

| Level | Indicators | Action |
|-------|-----------|--------|
| **Low** | Components communicate through well-defined interfaces. Changes to internals don't propagate. Dependencies are injected or configured, not hard-coded. | Healthy. Maintain. |
| **Medium** | Some shared data structures or conventions. Changes sometimes require coordinated updates across 2-3 files. Import paths are stable but deep. | Acceptable if bounded. Monitor. |
| **High** | Changes routinely cascade across multiple modules. Shared mutable state. Circular imports or bidirectional dependencies. "You can't change X without also changing Y and Z." | Refactor. Extract interfaces, inject dependencies, or merge tightly-coupled components. |

**Concrete indicators of problematic coupling:**
- Changing a function signature requires updating more than 3 call sites
- Two modules import each other (circular dependency)
- A "utils" or "helpers" module that everything imports (gravity well)
- Configuration that must be synchronized across multiple files
- Test setup that requires instantiating unrelated components

### Cohesion Assessment

| Level | Indicators | Action |
|-------|-----------|--------|
| **High** | Every function in the module serves the same purpose. The module name accurately describes everything in it. Removing any function would break the module's core responsibility. | Healthy. |
| **Medium** | Most functions are related, but there are a few "convenience" functions that serve callers rather than the module's core purpose. | Acceptable. Consider extracting convenience functions if the module grows. |
| **Low** | The module is a grab bag. Functions serve different purposes. The module name is vague ("utils", "helpers", "common", "misc"). | Split by responsibility. Each resulting module should pass the "one sentence without 'and'" test. |

### Interface Clarity

- **Clear:** Caller can use the interface correctly from its signature and docstring alone, without reading the implementation
- **Adequate:** Caller needs to read a few lines of implementation to understand edge cases, but the happy path is obvious
- **Opaque:** Caller must read the full implementation to use it correctly. Arguments have non-obvious constraints. Return types vary by code path.

### Single Responsibility

Apply the "reason to change" test: a component should have exactly one reason to change. If you can identify two independent reasons a component might need modification (e.g., "the serialization format changes" AND "the validation rules change"), it has too many responsibilities.

---

## 3. Pattern Catalog

### Registry Pattern
**When it's the right choice:** You have a set of implementations behind a common interface, and the set is determined at configuration/startup time rather than hardcoded.
**When you're misusing it:** The "registry" has 1-2 entries and will never grow. Or items are added at runtime in ways that make the system state hard to reason about. Or the registry is a disguised God object that everything reaches into.
**Key quality:** Registration and lookup should be separate from the implementations. The registry itself should be simple (a dict with validation, not a framework).

### Factory Pattern
**When it's the right choice:** Object creation involves decisions (which class? what config?) that shouldn't be the caller's responsibility. Multiple callers need the same creation logic.
**When you're misusing it:** The factory creates exactly one type and always will. Or the factory is hiding that there's really just one way to create the object.
**Key quality:** The factory's interface should be simpler than the constructors it wraps. If calling the factory requires as much knowledge as calling the constructor, it's not adding value.

### Strategy Pattern
**When it's the right choice:** An algorithm varies independently of the clients that use it. You need to swap behavior without changing the calling code.
**When you're misusing it:** There's only one strategy and no concrete plan for others. Or the strategies share so much state that they're not actually independent.
**Key quality:** Strategies should be stateless or carry only their own configuration. If a strategy needs access to the context object's internals, the boundary is in the wrong place.

### Observer / Event Pattern
**When it's the right choice:** One component needs to notify others without knowing who they are. The set of observers changes independently of the publisher.
**When you're misusing it:** There's exactly one observer, and it's always the same one. Or events are being used to implement what should be a direct function call, adding indirection without decoupling.
**Key quality:** Events should carry enough data for observers to act without calling back into the publisher. If observers routinely query the publisher after receiving an event, the event payload is too thin.

### Pipeline / Chain Pattern
**When it's the right choice:** Data flows through a sequence of transformations, and the steps are independently testable, reorderable, or conditionally applied.
**When you're misusing it:** The "pipeline" has rigid ordering, shared mutable state between steps, and steps that can't be tested independently. That's just sequential code pretending to be a pipeline.
**Key quality:** Each step should have a clear input type and output type. Steps should be composable without knowing about each other.

### Middleware Pattern
**When it's the right choice:** Cross-cutting concerns (auth, logging, error handling) need to wrap core logic without the core logic knowing about them.
**When you're misusing it:** Middleware is modifying core behavior rather than wrapping it. Or the middleware stack has implicit ordering dependencies.
**Key quality:** Removing any single middleware should leave the core logic functional. If it doesn't, that middleware is core logic in disguise.

---

## 4. Anti-Pattern Catalog

### God Object
**Symptom:** One class/module that knows about everything, does everything, or is imported by everything. Often named "Manager", "Handler", "Service", or "Utils".
**Why it's bad:** Impossible to modify without risk. Impossible to test in isolation. Impossible to understand without reading the whole thing.
**Fix:** Identify distinct responsibilities and extract them into focused modules. The God object becomes a thin coordinator that delegates.

### Shotgun Surgery
**Symptom:** A single logical change requires modifications across many files. Adding a new enum value requires updating 7 files. Adding a new feature means touching the router, the handler, the validator, the serializer, the tests for each, and the documentation.
**Why it's bad:** High probability of missing one site. Changes are expensive and error-prone.
**Fix:** Co-locate related code. If the same change always touches the same set of files, those files should probably be one module or at least in the same directory.

### Feature Envy
**Symptom:** A method spends more time accessing another object's data than its own. `order.customer.address.city` chains. Methods that take an object parameter just to pull fields out of it.
**Why it's bad:** Logic is in the wrong place. The method should probably live on the object whose data it's using.
**Fix:** Move the method to the class whose data it primarily uses, or extract the relevant data into a parameter.

### Leaky Abstraction
**Symptom:** Callers must understand the implementation to use the interface correctly. Error messages expose internal details. Configuration requires knowledge of internal components.
**Why it's bad:** The abstraction isn't abstracting. Callers are coupled to internals.
**Fix:** Make the interface usable from its contract alone. Translate internal errors to meaningful external errors. Hide configuration details behind sensible defaults.

### Reinvented Wheel
**Symptom:** Custom implementation of something the standard library or a well-known package already provides. Custom config parser, custom HTTP client wrapper, custom retry logic, custom event emitter.
**Why it's bad:** The custom version lacks edge case handling, documentation, and community testing. Maintenance burden falls on you.
**Fix:** Use the standard solution. If it doesn't fit exactly, extend or wrap it rather than replacing it. If you truly need custom behavior, document why the standard solution doesn't work.

### Premature Abstraction
**Symptom:** Interfaces with one implementation. Generic frameworks for specific problems. "We might need this later." Configuration-driven systems for things that change once a year.
**Why it's bad:** Abstraction has a cost: indirection, cognitive load, and constraints on future changes. Abstracting before you understand the variation is guessing at the future.
**Fix:** Wait for the second use case. Write concrete code first. Extract abstractions when you have two or three concrete examples to generalize from.

---

## 5. Cross-Cutting Checklists

### Error Handling
- [ ] Are errors handled at the right level? (Close to where recovery can happen, not at the top of every call stack)
- [ ] Do error messages help the reader fix the problem? (Not just "failed" — what failed, why, and what to do about it)
- [ ] Is there a clear boundary between retryable and fatal errors?
- [ ] Are partial failures handled explicitly? (Is "half the work succeeded" worse than "nothing succeeded"?)
- [ ] Are errors logged with enough context to debug without reproducing?
- [ ] Do async/concurrent errors propagate correctly?

### Observability
- [ ] Can you determine the system's state from its outputs (logs, metrics, health checks)?
- [ ] Is structured logging used for machine-parseable output?
- [ ] Are important state transitions logged?
- [ ] Can you trace a request through the system?
- [ ] Are performance-critical paths instrumented?

### Configuration Management
- [ ] Is configuration separated from code?
- [ ] Are defaults sensible? (The system should work without explicit configuration for common cases)
- [ ] Is configuration validated at startup, not at first use?
- [ ] Are configuration dependencies documented? (If setting A requires setting B)
- [ ] Is there a clear precedence order for configuration sources? (env vars > config file > defaults)

### Security Surface
- [ ] Are inputs validated at trust boundaries?
- [ ] Are secrets managed through a secrets system, not config files or environment variables in code?
- [ ] Is the principle of least privilege applied? (Components only have access to what they need)
- [ ] Are error messages safe? (No stack traces, internal paths, or credentials in user-facing errors)

---

## 6. Agentic-Era Principles

These principles are specific to a world where AI agents read, write, and reason about code. They augment (not replace) traditional principles.

### Code Legibility for Agents

Agents process code through context windows, not IDEs. This changes what "readable" means:

- **Explicit over implicit.** Agents can't hover for type info or click through to definitions as easily as a human in an IDE. Explicit type annotations, clear variable names, and documented parameters matter more than ever.
- **Local reasoning.** A function should be understandable from its file alone. If understanding a function requires reading 5 other files, an agent will either waste context loading them or hallucinate their contents.
- **Consistent patterns.** Agents learn patterns from context. If your codebase does the same thing three different ways, agents will guess wrong about which way to use. Pick one pattern and use it everywhere.
- **Discoverable conventions.** If there's a rule ("all handlers must register with the router"), it should be enforced by code (a registration call, a decorator, a base class), not just documented. Agents read code more reliably than documentation.

### Module Boundaries and Context Windows

Agent context windows create a physical constraint on how much code can be reasoned about simultaneously:

- **Keep modules small enough to fit in context.** A 5,000-line module is hard for humans and impossible for agents to reason about holistically. Prefer many small files over few large ones.
- **Make module interfaces explicit.** `__all__`, clear public/private boundaries, and well-defined entry points help agents understand a module's contract without loading its implementation.
- **Co-locate related code.** If understanding component X requires also loading files A, B, and C, those files should be in the same directory. Agents (and humans) navigate by proximity.
- **Minimize cross-module state.** Global state, singletons, and shared mutable objects require loading multiple modules to reason about behavior. Prefer explicit parameter passing.

### Convention Discoverability

In a human team, conventions spread through code review, pairing, and tribal knowledge. Agents have none of that:

- **Encode conventions in code, not wikis.** Base classes, decorators, type aliases, and factory functions are conventions that agents can discover and follow. Wiki pages are conventions that agents can't see.
- **Name things for discoverability.** `register_handler`, `create_service`, `validate_input` are patterns an agent can grep for and imitate. Bespoke names for common operations make it harder for agents to find examples.
- **Use consistent file organization.** If every feature has `handler.py`, `validator.py`, and `tests/test_handler.py`, agents can navigate by convention. If every feature organizes differently, agents must explore from scratch.

### The Reinvention Calculus Changes

Agents can compose existing libraries faster than humans but also hallucinate APIs that don't exist:

- **Prefer well-known libraries even more than before.** Agents have training data about popular libraries. They can use `requests`, `pydantic`, `click` correctly. They will invent plausible but wrong APIs for obscure libraries.
- **Pin and document dependencies.** Agents can't `pip install` and test on the fly. If you use a library, make sure it's in `pyproject.toml` and documented. Implicit dependencies lead to hallucinated imports.
- **Custom code needs more justification.** "I could write this in 20 lines" was a valid argument when a human was maintaining it. When agents are generating code, using a standard library function they know about beats a custom implementation they'll reinvent differently each time.

### Testing in the Agentic Era

- **Tests are specifications.** Agents read tests to understand expected behavior more reliably than they read documentation or comments. Well-written tests are the best specification.
- **Test names are documentation.** `test_login_rejects_expired_token` teaches agents what the system does. `test_case_7` teaches nothing.
- **Test isolation enables parallel agent work.** If tests share state, agents working in parallel will create flaky tests. Isolated tests let multiple agents modify the codebase safely.
