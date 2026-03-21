## Amplifier IPC

This is an implementation of Amplifier that uses IPC (inter-process communication) to orchestrate calls to services that manage orchestrators, context-managers, tools, hooks, and providers tools. They also expose context (files). The goal is to have a single process, the "host" that manages the orchestration of all these services, and to have each service run in its own process. This allows for better isolation and resource management, as well as the ability to use different programming languages for different services if desired.

It also sets us up for a full micro-service future.

## Design Direction

- docs/design-direction.md

## Current Implementation

- amplifier-ipc-host: The main process that manages the orchestration of all tools and services. It is responsible for registering agents and behaviors, managing sessions, and orchestrating calls to tools and services.
- amplifier-ipc-protocol: The protocol used for communication between the host and the tools and services. It defines the message formats and the communication patterns.
- services/: A directory for tools and services that can be registered and used by agents and behaviors. Each tool or service is expected to have a `run` entry point that the host can call to execute the tool or service.
