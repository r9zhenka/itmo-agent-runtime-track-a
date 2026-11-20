# 0009 — Optional SSH transport for provider requests

Status: accepted for Checkpoint 2.

## Context

The server VM may lack a working route to the model provider while the client
machine has a working HTTP proxy. Live model access must preserve the separation
between provider credentials, workspace transport and command sandboxes.

## Decision

Direct HTTPS is the default provider transport. `LLM_HTTP_PROXY` optionally selects
an explicit HTTP(S) proxy. Alternatively, an SSH remote forward exposes a Unix
socket on the server that reaches the client's HTTP proxy. The
`compose.llm-proxy.yml` overlay bind-mounts this existing socket only into
`llm-proxy`, at `/run/provider-proxy.sock`, and selects it through
`LLM_PROXY_SOCKET`. The overlay clears `LLM_HTTP_PROXY`; configuring both transports
is rejected. The bind does not create a missing host path.

The Unix transport connects to the socket, issues HTTP CONNECT for the configured
provider, and then establishes TLS to that provider with normal certificate and
hostname verification. The provider URL must use HTTPS. The provider bearer key
travels inside TLS, not in the CONNECT request. HTTP redirects are rejected rather
than forwarding bearer credentials to another endpoint. Internal service RPC
uses no proxy unless explicitly configured by its caller; the provider transport
does not depend on global `HTTP_PROXY` / `HTTPS_PROXY` environment variables.

The provider key remains in the LLM service configuration. SSH credentials stay
with the process that establishes the tunnel; they are not mounted into that
service. The HTTP proxy can observe the CONNECT destination and connection
metadata, but TLS protects request contents and the provider key. The socket is
an egress capability: its host permissions and the trusted SSH account are part
of the access boundary. A read-only bind does not prevent connecting to a socket.

The command sandbox receives none of the socket, provider key, SSH credentials or
Docker socket and retains network mode `none`. Provider forwarding is separate
from the remote folder's WebDAV forward; neither adds an agent web-search tool or
general sandbox egress.

## Alternatives

- Direct HTTPS: preferred when the server has reliable provider connectivity.
- A TCP proxy reachable from the VM: supported through `LLM_HTTP_PROXY`, but needs
  explicit address, firewall and access-control configuration.
- Giving all containers the client's proxy or VPN configuration: expands the
  network and credential boundary without helping the command isolation model.

## Consequences

The optional route depends on the SSH connection, the host socket and the client's
proxy. Losing any of them makes the provider call fail; the runtime does not
automatically rerun a task or its filesystem operations. Recreating the host
socket may require recreating the LLM service's bind mount. The route is an
operational connectivity option, not a provider-quality or availability guarantee.

See [ADR 0007](0007-network.md) for network policy and
[ADR 0006](0006-sessions.md) for failure/reexecution behavior.
