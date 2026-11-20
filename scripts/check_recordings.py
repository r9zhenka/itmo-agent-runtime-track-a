"""Audit the nine recorded smoke artifacts without calling a provider or tools."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from runtime.llm_proxy import ModelProxy
from runtime.model_recording import RecordingStore
from runtime.provider_transport import safe_usage


def audit(directory):
    store = RecordingStore(directory)
    proxy = ModelProxy()
    rows = []
    for task, case in sorted(store.smoke.items()):
        saved = store.load(case)
        if not saved or not saved.get('complete') or saved.get('failure') or not saved['frames']:
            raise ValueError('Missing complete provider recording: ' + task)
        tokens = 0
        for index, frame in enumerate(saved['frames']):
            if not re.fullmatch('[0-9a-f]{64}', frame.get('context_sha256', '')):
                raise ValueError('Invalid recorded context digest: ' + task)
            reply = frame['provider_response']
            proxy.validated(reply)
            source = reply['choices'][0]
            final = index == len(saved['frames']) - 1
            if (source['finish_reason'] == 'stop') != final or bool(source['message'].get('tool_calls')) == final:
                raise ValueError('Invalid completion sequence: ' + task)
            tokens += safe_usage(reply.get('usage')).get('total_tokens', 0)
        path = Path(directory) / (task + '.json')
        rows.append({'task': task, 'model': saved['model'], 'frames': len(saved['frames']),
                     'recorded_reported_tokens': tokens, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if len({row['model'] for row in rows}) != 1:
        raise ValueError('Smoke recordings use different model identities')
    return {'format': 'project-a-recorded-smoke-audit-v1', 'tasks': rows,
            'passed': True, 'provider': 'recorded-replay', 'quality_evaluation': False,
            'note': 'Artifact audit only; run offline smoke against real tools to verify playback outcomes.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    result = audit(args.directory)
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        Path(args.output).write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
