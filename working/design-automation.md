## Design Automation

Design automation (could be additions to brainstorming)

## Principles

- comprehending existing
  - Is there some reason we can decipher about why the existing design was chosen?
  - What is the mental model? Is it human facing or system facing?
  - Why was X done this way? Wouldn't Y be better? Does the fact that X was chosen tell us something about the designer's tradeoffs?
- design integrity
  - Is this proposal consistent with the previous design decisions we have made? If not, how would we reconcile them?
  - Who does this belong to? Does it really belong here?
  - Are we changing the responsibility of X?

- red-teaming design
  - What are the downsides of this proposal?
  - Haven't we conflated X with Y?

- Developer Experience (DX)
  - How would this proposal affect DX?
  - Sometimes more steps for a developer indicate an additional need for tooling, not that the design is wrong. Simple things with tools are often better than complex things that are harder to work with.
  - Is this more or less challenging for developers to understand the overall mental model?
    - Does it require them to understand more concepts, or fewer? 
    - Does it make the concepts easier or harder to understand?
    - Does naming clearly indicate purpose and how the named fits into the overall system? Is it consistent?

- Implementation Viability
  - If we make this change, how will it effect the code base. Do an exhaustive search of everywhere it is used and validate the new design will be able to replace the old seamlessly.

- Design Simplicity
  - Isn't there a simpler way to do this? (What if we just... X)?
  - Let's take a step back and really ask what we're trying to accomplish here. Are there simpler approaches?
  - Are there existing computer science concept related to this work that might inform our design?
  - Does this amount of logic indicate that we should consider revising the architecture? If so, what would the revision be and how much less code would we end up with? What is the concept that we have uncovered that we didn't know before? How would this new concept effect the rest of the system?
  - Are we mixing two concepts here? Aren't these actually separate concerns?
  - Are these different things or the same thing? What are the unique qualities that make them different? What are they actually then?

- tooling consistency
  - Are there existing common Python ecosystem concepts related to this work that might inform our design?
  - Are there existing popular libraries that would replace much of this work?
  - Doesn't this diverge from standard python (python packaging, uv usage, pydantic settings, etc. etc. etc.)

- revision
  - Actually, I liked it better with... except let's also...

## Process

- Sometimes you need to go through several design-implement cycles because you only learn about flaws in a design after getting well down the path. At that point, a choice should be made... pivot or persevere.
- Better than full implementations, though, would be to try multiple different proposals with some sort of lightweight prototyping or even just pseudo-code to get a better sense of the pros and cons of each approach before going all in on one--a type of A* search through the design space.

## Mechanics

- Keep a spec in /brainstorm

## Future

- The principle set might be selected based on the type of design problem we're trying to solve. For example, if we're trying to decide between two approaches to implementing a feature, we might prioritize design simplicity and implementation viability. If we're trying to decide on a high-level architecture, we might prioritize design integrity and developer experience.
- To that end, we might make design criteria weighting clear.
