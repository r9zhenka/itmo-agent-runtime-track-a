# Architecture decisions

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-harness.md) | Accepted | Small custom Python harness |
| [0002](0002-sandbox.md) | Accepted for CP1 | Docker socket manager, disposable command containers |
| [0003](0003-client-transport.md) | Accepted for CP1 | HTTP JSON and resumable SSE batches |
| [0004](0004-sandbox-transport.md) | Accepted | Versioned JSON RPC with operation IDs |
| [0005](0005-mounting.md) | CP1 accepted; remote proposal | Same-host bind now; evaluate SSHFS for CP2 |
| [0006](0006-sessions.md) | Accepted for CP1 | Single-user sessions with exclusive workspace ownership |
| [0007](0007-network.md) | Accepted for CP1 | Networkless sandbox, proxy-only model access |
| [0008](0008-evaluation.md) | Provisional | Synthetic replay for CI; quality selection pending |

Keep superseded decisions in the repository and link their replacement.
