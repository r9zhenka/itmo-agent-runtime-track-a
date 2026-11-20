"""Run only fresh smoke fixtures against a separately configured live-record stack.

This command never changes server configuration or reads provider credentials.
The server operator must opt in to LLM_MODE=live-record and LLM_RECORDING_DIR.
Raw replies remain there until explicitly copied for offline validation.
"""
import argparse
import json
import os
import time
from pathlib import Path

from baf.cases import cases
from client.api import settings
from client.remote import RemoteClient
from scripts.benchmark import run_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', required=True)
    parser.add_argument('--server-repo', required=True)
    parser.add_argument('--ssh-config')
    parser.add_argument('--ssh-port', type=int, default=22)
    parser.add_argument('--gateway-port', type=int, default=18080)
    parser.add_argument('--root', default='workspaces/provider-recordings')
    parser.add_argument('--output', default='results/provider-record-smoke.jsonl')
    parser.add_argument('--task', help='One of B1.1–B9.1; omit for all nine')
    args = parser.parse_args()
    selected = [case for case in cases() if case['id'].endswith('.1')
                and (not args.task or case['id'] == args.task)]
    if not selected:
        parser.error('Choose one of the nine smoke tasks')
    config = settings()
    token = os.getenv('CLIENT_TOKEN', config.get('CLIENT_TOKEN', ''))
    if not token:
        parser.error('Set the server CLIENT_TOKEN on the client')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    # Exclusive output avoids overwriting or mixing a previous scored campaign.
    with output.open('x', encoding='utf-8') as file:
        for case in selected:
            client = RemoteClient(token, args.ssh_host, args.server_repo,
                                  args.ssh_port, args.gateway_port, args.ssh_config)
            started = time.monotonic()
            try:
                result = run_case(client, case, args.root)
                if (result.get('model') or {}).get('provider') != 'live':
                    result.update({'pass': False, 'reason': 'Recording run did not use a live provider'})
            except Exception:
                result = {'task': case['id'], 'pass': False, 'reason': 'Recording run failed; inspect server recording metadata'}
            finally:
                try:
                    client.close()
                except Exception:
                    result = {'task': case['id'], 'pass': False, 'reason': 'Recording workspace cleanup failed'}
            result.update(purpose='provider-recording-capture', pair_label='recording-smoke',
                          capture_duration_ms=round((time.monotonic() - started) * 1000, 3))
            file.write(json.dumps(result) + '\n'); file.flush()
            print(f"{case['id']}: {'PASS' if result['pass'] else 'FAIL'}", flush=True)
            failures += not result['pass']
    print('Capture runner finished; audit and offline playback are required before claiming recorded-smoke readiness.')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
