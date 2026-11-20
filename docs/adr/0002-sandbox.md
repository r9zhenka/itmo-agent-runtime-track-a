# 0002 — Docker-managed disposable command containers

Status: accepted; extended for Checkpoint 2.

## Context

Commands need process/filesystem isolation and predictable cancellation. Compose
must build all project components from source. The selected host folder must remain
available across tool calls.

## Decision

The manager and an independent watchdog receive the Docker socket. Both belong to
the privileged control plane and talk directly to Engine API v1.47 over a Unix
socket. Provisioning reserves a workspace. Each exec creates and starts
a fresh container, waits with a deadline, collects bounded output and force-removes
the container. Persistent state is limited to `/work`. Cancelling or removing the
container terminates its whole process namespace, including detached children.

Containers use a non-root UID/GID, read-only root filesystem, all capabilities
dropped, no-new-privileges, network mode `none`, a one-CPU quota, 256 MiB RAM with
no extra swap, 64 PIDs, a 64 MiB `/tmp` tmpfs, a 128 MiB per-file size limit and
256 open descriptors. These settings are exercised by
the separate real-Docker check command; configuration tests alone do not establish
enforcement.

The primary read-write workspace is the remote client export described in
[ADR 0005](0005-mounting.md). Its exporter bounds regular-file content to 256 MiB
and exported entries to 4096, including old-plus-new content and a temporary entry
while replacing a file. These are logical allocation bounds, not filesystem block
quotas. Protected `.git` contents are not exported or counted. Trusted local edits
can grow the folder independently; see [the quota boundary](../hardening.md).

A direct local bind has no portable aggregate quota. Local read-write sessions
therefore require the explicit trusted-development opt-in `ALLOW_LOCAL_RW=1`.
The runtime and Compose default to `0`; `.env.example` sets `1` for the documented
local development workflow. Local read-only snapshots, including code grading,
do not need that opt-in. The per-file limit does not replace an aggregate quota.

Every command container carries instance/operation labels and an absolute deadline.
The manager enforces its own timeout; the separate watchdog checks deadlines and
remote mount leases every 250 ms and force-removes expired or invalid containers.
This keeps deadline enforcement available after a manager or harness process loss.

## Alternatives

- Persistent container per session: lower exec latency and persistent shell state,
  but cancellation and leftover-process cleanup are more complex.
- Rootless Docker: reduces daemon privilege, but bind-mount ownership and setup
  vary across hosts. A strong candidate for later hardening.
- gVisor: a stronger kernel boundary, but requires a runtime installation beyond
  the standard Docker baseline.

## Risks and consequences

Docker socket access effectively grants root-equivalent host control. The manager
and watchdog are part of the trusted computing base; neither is an isolation
boundary. This extends the original CP1 manager-only socket decision. Never
mount the socket into the command sandbox. Restrict all input paths to the configured
workspace root and never accept arbitrary container configuration from clients.

Per-command startup is slower; measure that cost before optimizing. Commands cannot
rely on state outside `/work`. Graceful shutdown and manager restart remove labelled
containers. The watchdog depends on the Docker API and the host's wall clock;
polling and API latency can delay removal. Timely cleanup is not guaranteed while
both control-plane services or Docker are unavailable. Resource limits and remote
export quotas remain applicable. Cleanup does not restore conversation state or
automatically reexecute an operation whose result was lost.

Sources: [Docker Engine API](https://docs.docker.com/reference/api/engine/version/v1.47/),
[Docker run resource and security controls](https://docs.docker.com/engine/containers/run/).
