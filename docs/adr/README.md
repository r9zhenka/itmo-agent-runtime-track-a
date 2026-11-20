# Architecture decisions

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-harness.md) | Accepted | Small custom Python harness |
| [0002](0002-sandbox.md) | Accepted; CP2 extension | Disposable containers, remote quotas and independent watchdog |
| [0003](0003-client-transport.md) | Accepted for CP1 | HTTP JSON and resumable SSE batches |
| [0004](0004-sandbox-transport.md) | Accepted | Versioned JSON RPC with operation IDs |
| [0005](0005-mounting.md) | Accepted; two-machine acceptance passed | WebDAV over SSH + rclone/FUSE; same-host bind retained |
| [0006](0006-sessions.md) | Accepted; CP2 extension | Exclusive workspaces, lease loss and no automatic reexecution |
| [0007](0007-network.md) | Accepted; CP2 extension | Networkless sandbox, separate mount and provider transports |
| [0008](0008-evaluation.md) | Provisional | Synthetic replay for CI; quality selection pending |
| [0009](0009-provider-transport.md) | Accepted for CP2 | Optional provider HTTP CONNECT through an SSH Unix socket |

Keep superseded decisions in the repository and link their replacement.
