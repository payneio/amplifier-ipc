## The process

I started with my own confusion from trying to grok current Amplifier code:

- Isn't the kernel just running an exec loop over modules?
- Isn't all this bundle loading just reinventing uv?
- Why is it so hard to understand what a bundle is?
- Does polyglot in the kernel actually give us anything? It instead seems we now have three different methods for trying to interact with a small bit of code (Python, GRPC, WASM). Isn't what we want for polyglot to be able to use modules written in other languages?

I worked with Amplifier to investigate. At first it tried to explain using its in-context philosophy docs. What it argued for still didn't make sense to me, so I explicitly asked it to ignore its philosophy docs and it came back with very clear answers.

## No Kernel

- There was no need for a "kernel". The actual mechanics of what the kernel does could be replaced by a 400 loc helper library.
- Instead, of trying to load modules at runtime, using a separate library, we can just define dependencies up front and let Python's import system take care of it.
- Eliminating the kernel removes the "mount" need.
  - "registering" a module is just adding it as a normal dependency and using it.
  - Much fewer errors in runtime.: Removing the runtime mounting means static code checking and compile/load-time enforcement now works (early fail on error).
- Eliminating the kernel removes the need for a "coordinator". Everything is just a session.
- Eliminating the kernel removes the need for mount plans and the tooling around them.
- Polyglot in the kernel adds 10,000 loc and two new integration methods for no additional flexibility. Polyglot in the modules is what we want, and we can simply use existing Python package mechanics that already handle exposing WASM, C++ binding, etc. 
  - This makes sense from a performance standpoint as agent orchestration performance is always bound by what the models or modules are doing, not the actual orchestration.
  - By using Python in the core/foundation-lib, we keep the core small and stable.

## No Bundles

- "Bundles" conflated many different things:
  - session configuration
  - session dependencies
  - behavior configuration
  - behavior dependencies
  - packaging (modules and data)
  - Because of this:
    - Nobody could understand what a bundle was.
    - We had silent naming conflicts between packages. Packages just overwrite other packages without warning.
    - We had to create our own custom bundle management instead of using python package management. IOW, we reinvented "uv" poorly instead of using it, creating cache difficulties.
    - We confused agents (how session execution should work) and behaviors (what things it can do).
    - We don't allow bundles to be placed anywhere in a repo like uv allows.
    - There are many magical business rules for handling bundles hidden in the code. If the bundle dev didn't follow convention, they would fail. This required substantial bundle verification (agents and functions) to manage and made it hard for bundle devs to know why things were failing or how to get them to work.

### Don't reinvent packaging and virtual environments (uv)

- An environment can be managed entirely with uv.
  - No other caching needed.
  - Easy to reason about: ALL dependencies are declared in agent.md and behavior.md files (formerly bundle.md).
  - Guaranteed: The correct versions will be efficiently cached and loaded.
  - Standard pyproject.toml packaging of modules and content.
- By using standard python packaging, we can:
  - declare dependencies
  - do package content discovery for at-mentions simply and declaratively via entrypoints.
  - Use efficient and correct uv package management
  - separate agent and behavior files, making it clear they are to be used in different ways
  - Ensure all dependencies are installed.
  - Use standard python package compilation errors for validation.
  - Nobody has to learn what a "bundle" is.

### Don't mix packaging into agent and behavior descriptions

- By separating agent and behavior config files (bundles.md) from the packages (pyproject.toml), we fix:
  - agent and behavior files can just be files.
  - All their package dependencies are declared and will always be available in the environment.
  - Relative include resolution works even if they are referenced from remote locations (not more git+ refs for agent or behavior files). This cleanly separates how the agent should behave (configuration) from how it executes (packages)
  - Reduce the amount of manual verification we need to do.
  - Simpler for agents and humans to understand what is being developed... no magical "bundles work this way" stuff... just normal python packages with modules and data.
- The environment and the agent config were conflated.
- A default agent and environment can be shipped with the project, ensuring it will ALWAYS work.

## Session State

- Session state and session spawning should not be in the CLI, they should be in foundation. What is 6,000loc in 14 files could be ~800 loc. Eliminates need for capability registration for apps.

## Amplifier Lite

After analysis, Amplifier believed, using a better design/architecture it could reimplement 16,000 lines of code with ~600 loc.

With these learnings in hand, I created a new working directory and started "Amplifier-lite" using foundation bundle in /brainstorm mode.

## The Result

- With all the things pulled out that are NOT amplifier (the core, bundles), we now can finally, clearly, answer the questions:
  - "what IS amplifier": Amplifier is a composable agent runtime. It composes code modules (agents loops, context-managers, providers, tools, and hooks) and content (agents, skills, recipes, and context files) using standard python packages. It gives developers complete control of agent composition allowing them to experiment rapidly with different behaviors and integrate their agent easily into other software and systems.
- How does it differ from Claude Code?
  - It allows us to configure ALL parts of the agent, including the loop, context-manager, and providers: all which are not accessible in Claude Code.
  - We provide three integration routes: 1) a Python library, 2) a CLI, 3) a web service, making it more immediately accessible to devs.
  - We ship it with a batteries-included "foundation" agent package that contains our best-practices. Unlike Claude-Code, it can be extended easily with standard Python packages, or entirely replaced with your own behavior.

BUT the result had a problem... the desire for polyglot was gone and it demanded that developers work with Python packaging instead of just configuration.

So, I took this back the design table and did another iteration.

## Amplifier IPC

### Polyglot services, not polyglot kernel

Much of the recent work on amplifier-core is to support polyglot access to the core. However, as noted above, the core isn't what you want polyglot access to. You want access to some combination of core+foundation. Recently GRPC was added, which is a nod to the idea that what is in the core should be a service. While we can go full-blown microservice architecture, we can also do something simpler with the idea of a core "host" and IPC/JSON2-RPC services as long as we find the right boundaries. We could throw every component (tool, provider, orchestrator, etc.) in its own service, but we actually have something better: agents and behaviors. The agent and behavior definitions (formerly bundles.md) already define clear boundaries for composition. We can just make each agent and behavior a service. This also makes it really easy to do polyglot development of different agents and behaviors as needed. In this world, it doesn't matter what the core/host is written in, because all communication is done between the core and the services that people really want to think in: agents/behaviors. With IPC (or in the future GRPC or other microservices with container orchestration for packaging and delivery), these agents and behaviors can literally be in any language as long as they follow the stable Amplifier protocol. 

We can get all of this today with little no more work than bundle rewriting.

### Amplifier as a service

- Put Amplifier Lite (the new core) into a "host" that calls out to "services" for the actual work. These are just executables talking to each other with IPC using JSON2-RPC. stdin/stdout stuff.
- Each agent.md and behavior.md (formerly bundles.md) becomes a service. The service can be written in any language, and it declares its dependencies in a standard way (e.g., pyproject.toml for Python). The host just needs to know how to spawn the service and talk to it with JSON2-RPC.
- The core lib supplies the protocol and the IPC plumbing, so the service just needs to implement the protocol and it can be in any language. We provide a Python service wrapper (others easily made) that handles all the complexity of talking to the host for you. For python, we provide simple decorators that let's you declare any python function to be a tool, provider, hook, orchestrator, or context manager and it will automatically be exposed to the host.
- We get complete process isolation. Having a Python service run with `uv run --environment` gives is complete venv isolation. This eliminates all the problems we had with bundles mixing all into one venv.

### The result

- https://github.com/payneio/amplifier-ipc
- 4,500 loc for all this:
  - A host (the core) that handles all session execution using whatever agent definition you give it. It launches the orchestrator you want and then launches any components (tools, providers, hooks, context managers) that you declare in your agent and behavior definitions as separate processes and talks to them with JSON2-RPC over stdin/stdout, providing event forwarding between all the components.
  - A service library to make agents and behaviors easily.
  - A CLI (replacement for `amplifier`) that allows you to register agent and behavior definitions and run sessions.
- This is a simple architecture for replacing 60,000 loc while giving us true polyglot, authentic process and environment isolation, eliminates friction like silent failures and stale code, a much clearer and simpler mental model for users, and sets us up for microservices--which are definitely part of an Agent OS future.

## Why was this so hard?

- We encoded bad architecture into the philosophy docs that we have used throughout the entire agentic development process... both previously when using Claude Code and with Amplifier. Attempts to understand Amplifier by users, or have Amplifier critique PRs were responded to with these philosophy docs in context. It is a type of design context poisoning.

## Some expected objections

- The core is too big to be stable now.
  - "fast moving with a stable core" can still be achieved, we just redefine what the stable part is--core and what remains of the foundation lib after we remove the uv-reinvention parts. If we don't include these _foundational_ library parts of foundation in the "stable" part makes it all MORE fragile. The pieces that we actually want to be rock-solid: the models and the protocols can easily be kept stable (through versioning, not an architectural proxy layer) even though they sit beside other code we might update more regularly.
  - Saying another way: the actual "kernel" is not just what is in amplifier-core now, mainly data models/protocols, but some of the things that are in foundation now. Putting a hard boundary around protocols is a boundary in the wrong place. You actually want the foundation pieces that work with those protocols also in the core. The whole objective to "keep something in the middle stable" is not around protocols (which can just be versioned), but rather everything that isn't a plugin (bundles).
  - It's still small and stable because all agent definition and behaviors are still outside the core. 
- This makes the core too opinionated.
  - Composing functionality is just as flexible as before. We are not locked into any specific implementation of what goes in an amplifier package. It's just easier to understand.
- Why change things, they're already working?
  - Friction matters. User comprehension matters. We need to move fast as individuals and as a team. Many of the six friction points that Sam identified by having Amplifier evaluate 70 sessions are resolved with this redesign.
- Why get so "stuck in the weeds", why not just have the agent evolve into a better design on its own?
  - The root problem of how we got to where we are is that we put the wrong design in our philosophy documents. Without changing the core design philosophy we would have continued running into these problems.
- We need to be focused on applications at this point, continual re-design of the core wastes time. 
  - We are wasting massive amounts of team time dealing with friction, trying to understand what Amplifier actually is, and trying to get people to understand how to use it. This waste will continue until we fix it. Having Amplifier superpowers rewrite Amplifier over a couple days to incorporate our learnings (which have piled up for months now) is exactly the kind of investment we should be making.
- This will require the team to relearn how to compose agents.
  - Yep. That's a good thing because it makes sense now. The team will be able to experiment much more rapidly.
- We can't make everyone update their bundles, it's too much work
  - There's a script for that.
  - What's the Cost-Value cutoff of things like this?

## Core Lessons Learned

- Philosophy docs mixed in system architecture/design.
  - At the time these were created they made a big impact on the productivity of Amplifier, so it wasn't wasted effort, but it would have been even more productive to have the early architecture-related parts of the docs reviewed before being embedded in the system.
  - System design parts of philosophy docs (vs approach or vision type things that would make sense in there) should be written with common and correct usage of terms: "kernel" should be "core library" or "core service" depending on what you want. "bricks and studs" should be described as "small units of encapsulation" using "clear interfaces and protocols", etc. "Unix Philosophy" contains many parts, so spell out the specific pieces you are really going for. Instead of making this a hard philosophy that all things that MUST be followed, describe them as "Architectural preferences" or something looser to allow the agent runtimes to pick better designs when needed. Have this reviewed by other humans with architecture/systems-design experience (see next point).
- Good system design/architecture still matters, even if it looks different than before. "Bundles" were created to solve immediate problems with the expectation that we could/would redesign at some point. Designing with Amplifier at that stage is kind-of like an author trying to get an agent to write good stories or a political scientist trying to get an agent to have a nuanced international opinion. Human experience is still needed to discern what is actually a good response vs. what sounds plausible. Knowing that bundles were one of the core value propositions of Amplifier, and that they had multiple cross-cutting concerns, we should have spent more time (a few days) getting it closer to right. The design should be reviewed by humans (until we do the next point).
- We can put this type of system design review capability into an amplifier package. We can't solely rely on Amplifier to come up with a good set of design principles: fleets of agents need different design practices than teams of humans. Many existing design principles were created to help human teams overcome their specific human problems. Fleets of agents will have different needs/problems. I have been capturing the types of questions I ask amplifier as I practice system design with Amplifier, and we can extract more through the two design sessions I used in making Amplifier-lite, along with continued revision with experience.

## Roll-out

If we want to use Amplifier-lite across the team:

- Revise the CLI. No more bundle commands. Environment commands.
- Update the service.
- Run conversion command against all microsoft bundles to create all the amplifier packages. Then either: push back to all the repos, or leave in amplifier-lite repo (they're just packages now, they can literally go anywhere... it's just distribution at this point).
- Decide whether we want to put lib, cli, service, and packages in one repo or multiple (I would argue for one for as it lets new devs see everything needed to get up and running in one spot, but since we're using standard Python packaging, we can do whatever we want).
- Update agent context. Update the foundation bundle to have awareness of its new design (e.g., merge in core package context)
- Update docs.
- Update all of our tooling around the existing repos (other agents that are looking at them, github workflows, etc.)
- We kept Amplifier's bundle composition rule of keeping only the last system instruction loaded. But, shouldn't we concatenate them from all loaded behaviors?

