# 0007 — Networkless command containers

Status: accepted for Checkpoint 1.

## Decision

Use Docker network mode `none` for all command containers. They do not receive
server tokens, model keys or the Docker socket. The harness calls only the internal
LLM proxy. The proxy has an egress-capable network; other service traffic uses the
internal Compose network. The gateway also joins a dedicated ordinary `frontend`
bridge for host port publishing. Only the gateway has a loopback-bound published
port, default `127.0.0.1:18080`. It must not rely on an internal-only bridge for
publishing a port. The frontend bridge gives the gateway egress as well; command
sandboxes remain networkless.

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
