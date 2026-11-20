"""Derive ls-portable hash sidecars only after verifying every original context.

Provider recordings stay byte-identical. The archived event file and each recording
are SHA256-bound into the sidecars. No model code, Docker or network is executed.
"""
import argparse
import hashlib
import json
from pathlib import Path

from baf.cases import cases, prompt
from runtime.contracts import tool_definitions
from runtime.harness import SYSTEM
from runtime.model_recording import context_digest
from runtime.recorded_context import NORMALIZER, portable_context_digest
from scripts.check_recordings import audit


def derive(directory, captures, event_file):
    directory, captures, event_file = map(Path, (directory, captures, event_file))
    audit(directory)
    rows = [json.loads(line) for line in captures.read_text().splitlines() if line.strip()]
    event_bytes = event_file.read_bytes()
    events = json.loads(event_bytes)
    smoke = {case['id']: case for case in cases() if case['id'].endswith('.1')}
    if len(rows) != len(smoke) or {row['task'] for row in rows} != set(smoke):
        raise ValueError('Expected each of the nine captured smoke tasks exactly once')
    prepared = {}
    # Complete validation comes before writing any new sidecar.
    for row in rows:
        task = row['task']
        if (row.get('model') or {}).get('provider') != 'live':
            raise ValueError('Capture events must come from the live provider')
        raw = (directory / (task + '.json')).read_bytes()
        recording = json.loads(raw)
        stream = events[row['session_id']]
        models = [event for event in stream if event.get('type') == 'model']
        tools = [event for event in stream if event.get('type') == 'tool_result']
        if len(models) != len(recording['frames']):
            raise ValueError('Provider/event frame count mismatch: ' + task)
        messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt(smoke[task])}]
        contexts = []
        cursor = 0
        for frame in recording['frames']:
            original = context_digest(messages, tool_definitions())
            if original != frame['context_sha256']:
                raise ValueError('Original captured context hash differs: ' + task)
            contexts.append({'original_sha256': original,
                             'portable_sha256': portable_context_digest(messages, tool_definitions())})
            message = frame['provider_response']['choices'][0]['message']
            messages.append(message)
            for call in message.get('tool_calls', []):
                if cursor >= len(tools) or tools[cursor].get('tool') != call['function']['name']:
                    raise ValueError('Captured tool sequence differs: ' + task)
                messages.append({'role': 'tool', 'tool_call_id': call['id'],
                                 'content': json.dumps(tools[cursor]['result'])})
                cursor += 1
        if cursor != len(tools):
            raise ValueError('Unexpected captured tool results: ' + task)
        prepared[task] = {'normalizer': NORMALIZER, 'task': task,
                          'recording_sha256': hashlib.sha256(raw).hexdigest(),
                          'events_sha256': hashlib.sha256(event_bytes).hexdigest(), 'contexts': contexts}
    return prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--captures', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--check', action='store_true', help='Verify existing sidecars instead of writing')
    args = parser.parse_args()
    prepared = derive(args.directory, args.captures, args.events)
    paths = {task: Path(args.directory) / (task + '.context.json') for task in prepared}
    if args.check:
        for task, path in paths.items():
            if json.loads(path.read_text()) != prepared[task]:
                raise ValueError('Sidecar differs from verified source evidence: ' + task)
    else:
        if any(path.exists() for path in paths.values()):
            raise ValueError('Sidecars already exist; use --check to verify without overwriting')
        for task, path in paths.items():
            with path.open('x') as file:
                json.dump(prepared[task], file, indent=2)
                file.write('\n')
    print(json.dumps({'tasks': len(prepared), 'original_contexts_verified': sum(len(v['contexts']) for v in prepared.values()),
                      'normalizer': NORMALIZER, 'raw_recordings_modified': False, 'checked': args.check}))


if __name__ == '__main__':
    main()
