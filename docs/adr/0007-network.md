# 0007 — Networkless command containers

Status: accepted; extended for Checkpoint 2.

## Decision

Use Docker network mode `none` for all command containers. They do not receive
server tokens, model keys or the Docker socket. The harness calls only the internal
LLM proxy. The proxy has an egress-capable network; other service traffic uses the
internal Compose network. The gateway also joins a dedicated ordinary `frontend`
bridge for host port publishing. Only the gateway has a loopback-bound published
port, default `127.0.0.1:18080`. It must not rely on an internal-only bridge for
publishing a port. The frontend bridge gives the gateway egress as well; command
sandboxes remain networkless.

Provider requests support an explicit HTTP proxy or an SSH-forwarded Unix socket
carrying HTTP CONNECT; the optional socket is mounted only into `llm-proxy`.
HTTPS remains end-to-end to the configured provider, with certificate verification.
Internal RPC does not inherit shell proxy settings. This transport changes the
provider's route, not sandbox network policy; see
[ADR 0009](0009-provider-transport.md).

## Alternatives

- Unrestricted sandbox egress: convenient dependency installation, but permits
  arbitrary exfiltration and non-reproducible external dependencies.
- Destination allowlisting through a network proxy: more flexible, but requires
  testing DNS, direct-IP and alternate-protocol bypasses. Deferred until needed.

## Consequences

Bundled BAF tasks must use the sandbox's prebuilt Python and shell tools. Package
downloads from inside the agent sandbox fail by design. Image builds and live model
calls can use external network access. Offline test/replay execution does not need
external network access after images are present.

## Remote-folder transport

The host-side mount helper reaches only the client's exported WebDAV endpoint via
an SSH reverse forward bound to server loopback. Gateway requests use a separate
local forward through the same SSH connection. No sandbox network is enabled:
file I/O crosses the mount while networking remains on the trusted host. SSH
credentials and per-export tokens remain outside the sandbox.

The exporter bounds remote workspace content to 256 MiB and entries to 4096.
Its host-side networking does not give the command a general-purpose network
interface. A lost mount lease is checked by the manager and independent watchdog;
affected containers are removed, and failed operations are not automatically
reexecuted. See [ADR 0002](0002-sandbox.md) for control-plane failure limits and
[ADR 0006](0006-sessions.md) for session behavior.
