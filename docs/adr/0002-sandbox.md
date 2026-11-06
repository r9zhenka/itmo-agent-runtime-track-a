# 0002 — Docker-managed disposable command containers

Status: accepted for Checkpoint 1.

## Context

Commands need process/filesystem isolation and predictable cancellation. Compose
must build all project components from source. The selected host folder must remain
available across tool calls.

## Decision

Only the manager receives the Docker socket. It talks directly to Engine API v1.47
over a Unix socket. Provisioning reserves a workspace. Each exec creates and starts
a fresh container, waits with a deadline, collects bounded output and force-removes
the container. Persistent state is limited to `/work`. Cancelling or removing the
container terminates its whole process namespace, including detached children.

Containers use a non-root UID/GID, read-only root filesystem, all capabilities
dropped, no-new-privileges, network mode `none`, a one-CPU quota, 256 MiB RAM with
no extra swap, 64 PIDs, and a 64 MiB `/tmp` tmpfs. These settings are exercised by
the separate real-Docker check command; configuration tests alone do not establish
enforcement. The host workspace is not disk-quota limited yet.

## Alternatives

- Persistent container per session: lower exec latency and persistent shell state,
  but cancellation and leftover-process cleanup are more complex.
- Rootless Docker: reduces daemon privilege, but bind-mount ownership and setup
  vary across hosts. A strong candidate for later hardening.
- gVisor: a stronger kernel boundary, but requires a runtime installation beyond
  the standard Docker baseline.

## Risks and consequences

Docker socket access effectively grants root-equivalent host control. The manager
is part of the trusted computing base; it is not an isolation boundary. Never
mount the socket into the command sandbox. Restrict all input paths to the configured
workspace root and never accept arbitrary container configuration from clients.

Per-command startup is slower; measure that cost before optimizing. Commands cannot
rely on state outside `/work`. Graceful shutdown and manager restart remove labelled
containers; a manager crash currently has no independent execution watchdog.

Sources: [Docker Engine API](https://docs.docker.com/reference/api/engine/version/v1.47/),
[Docker run resource and security controls](https://docs.docker.com/engine/containers/run/).
