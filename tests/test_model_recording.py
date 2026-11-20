import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baf.cases import cases, prompt
from runtime.common import Fault
from runtime.llm_proxy import ModelProxy
from runtime.model_recording import RecordingStore, context_digest
from runtime.provider_transport import provider_fault


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        case = next(case for case in cases() if case['id'] == 'B1.1')
        self.body = {'op': 'complete', 'messages': [{'role': 'system', 'content': 'unit fixture'},
                     {'role': 'user', 'content': prompt(case)}], 'tools': []}
        self.reply = {'id': 'mock-provider-id', 'choices': [{'finish_reason': 'stop',
                      'message': {'role': 'assistant', 'content': 'unit fixture completion'}}],
                      'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14}}

    def proxy(self, mode='live-record'):
        return ModelProxy(mode, 'https://provider.example/v1', 'SECRET-CANARY-0123456789',
                          'test-provider', recording_dir=self.root)

    def record(self):
        with patch('runtime.llm_proxy.request_json', return_value=self.reply):
            return self.proxy().dispatch(self.body)

    def test_records_actual_transport_reply_and_replays_without_network_or_token_charge(self):
        self.assertEqual(self.record()['provider'], 'live')
        saved = json.loads((self.root / 'B1.1.json').read_text())
        self.assertEqual(saved['frames'][0]['provider_response'], self.reply)
        self.assertEqual(saved['source'], 'actual-provider-responses')
        self.assertTrue(saved['complete'])
        self.assertEqual((self.root / 'B1.1.json').stat().st_mode & 0o777, 0o600)
        with patch('runtime.llm_proxy.request_json', side_effect=AssertionError('network')):
            replay = self.proxy('recorded').dispatch(self.body)
        self.assertEqual(replay['provider'], 'recorded-replay')
        self.assertEqual(replay['usage'], {'total_tokens': 0})
        self.assertEqual(replay['recorded_usage']['total_tokens'], 14)
        self.assertEqual(replay['message'], self.reply['choices'][0]['message'])

    def test_arbitrary_and_nonfresh_conversations_rejected_before_provider(self):
        for change in ('arbitrary text', '[BAF B1.2] not smoke'):
            body = copy.deepcopy(self.body); body['messages'][1]['content'] = change
            with patch('runtime.llm_proxy.request_json') as request, self.assertRaises(Fault):
                self.proxy().dispatch(body)
            request.assert_not_called()
        body = copy.deepcopy(self.body); body['messages'].append({'role': 'user', 'content': 'private'})
        with self.assertRaises(Fault):
            self.proxy().dispatch(body)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_recorded_prompt_tools_and_fixture_changes_fail_closed(self):
        self.record()
        for key in ('messages', 'tools'):
            body = copy.deepcopy(self.body)
            if key == 'tools': body['tools'] = [{'changed': True}]
            else: body['messages'][0]['content'] += ' changed'
            with self.assertRaises(Fault): self.proxy('recorded').dispatch(body)
        path = self.root / 'B1.1.json'; saved = json.loads(path.read_text())
        saved['fixture_sha256'] = 'changed'; path.write_text(json.dumps(saved))
        with self.assertRaises(Fault): self.proxy('recorded').dispatch(self.body)

    def test_recording_cannot_overwrite_complete_or_replay_missing(self):
        with self.assertRaises(Fault): self.proxy('recorded').dispatch(self.body)
        self.record(); before = (self.root / 'B1.1.json').read_bytes()
        with patch('runtime.llm_proxy.request_json') as request, self.assertRaises(Fault):
            self.proxy().dispatch(self.body)
        request.assert_not_called()
        self.assertEqual((self.root / 'B1.1.json').read_bytes(), before)

    def test_multistep_history_and_tool_result_match(self):
        first = copy.deepcopy(self.reply)
        first['choices'][0] = {'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'call-one', 'type': 'function', 'function': {'name': 'RunCommand', 'arguments': '{"command":"python -m unittest -v"}'}}]}}
        proxy = self.proxy()
        with patch('runtime.llm_proxy.request_json', return_value=first):
            assistant = proxy.dispatch(self.body)['message']
        with self.assertRaises(Fault): self.proxy('recorded').dispatch(self.body)
        continuation = copy.deepcopy(self.body)
        continuation['messages'] += [assistant, {'role': 'tool', 'tool_call_id': 'call-one', 'content': json.dumps({
            'stdout': '', 'stderr': 'Ran 2 tests in 0.012s\n\nOK\n', 'exit_code': 0, 'error': None,
            'truncated': False, 'session_id': 'old', 'operation_id': 'old-op', 'duration_ms': 100})}]
        with patch('runtime.llm_proxy.request_json', return_value=self.reply): proxy.dispatch(continuation)
        changed = copy.deepcopy(continuation)
        result = json.loads(changed['messages'][-1]['content'])
        result.update(session_id='new', operation_id='new-op', duration_ms=999)
        result['stderr'] = result['stderr'].replace('0.012s', '0.999s')
        changed['messages'][-1]['content'] = json.dumps(result)
        self.proxy('recorded').dispatch(changed)
        result['stdout'] = 'different actual result'
        changed['messages'][-1]['content'] = json.dumps(result)
        with self.assertRaises(Fault): self.proxy('recorded').dispatch(changed)
        changed = copy.deepcopy(continuation); changed['messages'][2]['tool_calls'][0]['function']['arguments'] = '{}'
        with self.assertRaises(Fault): self.proxy('recorded').dispatch(changed)

    def test_failed_provider_recording_is_incomplete_and_metadata_safe(self):
        failure = provider_fault('finish_reason', finish_reason='length', usage={'total_tokens': 55})
        with patch('runtime.llm_proxy.request_json', side_effect=failure), self.assertRaises(Fault):
            self.proxy().dispatch(self.body)
        saved = json.loads((self.root / 'B1.1.json').read_text())
        self.assertFalse(saved['complete'])
        self.assertEqual(saved['failure']['details']['usage']['total_tokens'], 55)
        with self.assertRaises(Fault): self.proxy('recorded').dispatch(self.body)

    def test_credential_echo_never_written(self):
        self.reply['choices'][0]['message']['content'] = 'SECRET-CANARY-0123456789'
        with self.assertRaises(Fault): self.record()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_readfile_content_and_errors_are_not_normalized_away(self):
        body = copy.deepcopy(self.body)
        body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': 'read', 'function': {'name': 'ReadFile'}}]},
                            {'role': 'tool', 'tool_call_id': 'read', 'content': json.dumps({'stdout': 'Ran 2 tests in 0.1s'})}]
        other = copy.deepcopy(body); other['messages'][-1]['content'] = json.dumps({'stdout': 'Ran 2 tests in 0.2s'})
        self.assertNotEqual(context_digest(body['messages'], []), context_digest(other['messages'], []))

    def test_corrupted_frames_and_symlink_files_fail_with_clear_fault(self):
        self.record()
        path = self.root / 'B1.1.json'
        original = json.loads(path.read_text())
        for frame in (None, {}, {'context_sha256': 'x'},
                      {'context_sha256': 'a' * 64, 'provider_response': {'choices': []}}):
            saved = copy.deepcopy(original); saved['frames'] = [frame]
            path.write_text(json.dumps(saved))
            with self.assertRaises(Fault):
                self.proxy('recorded').dispatch(self.body)
        path.unlink(); target = self.root / 'other.json'; target.write_text(json.dumps(original))
        path.symlink_to(target)
        with self.assertRaises(Fault):
            self.proxy('recorded').dispatch(self.body)

    def test_fixture_recording_audit_requires_all_nine_complete_tasks(self):
        from scripts.check_recordings import audit
        self.record()
        with self.assertRaises(ValueError):
            audit(self.root)
        for case in cases():
            if not case['id'].endswith('.1') or case['id'] == 'B1.1':
                continue
            body = copy.deepcopy(self.body); body['messages'][1]['content'] = prompt(case)
            with patch('runtime.llm_proxy.request_json', return_value=self.reply):
                self.proxy().dispatch(body)
        report = audit(self.root)
        self.assertEqual(len(report['tasks']), 9)
        self.assertFalse(report['quality_evaluation'])

    def test_readonly_store_and_duplicate_inflight_start_rejected(self):
        with self.assertRaises(Fault):
            RecordingStore(self.root).begin(self.body, 'model')
        store = RecordingStore(self.root, writing=True)
        ticket = store.begin(self.body, 'model')
        with self.assertRaises(Fault):
            store.begin(self.body, 'model')
        store.finish(ticket, failure={'kind': 'model', 'message': 'unit test stopped'})
