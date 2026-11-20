import tempfile
import time
import unittest
from pathlib import Path

from client.api import Client
from runtime.common import Fault, Remote
from runtime.sandbox_manager import SandboxManager
from tests.support import FixtureProcessEngine, server


class SandboxEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'work').mkdir()
        self.engine = FixtureProcessEngine()
        self.manager = SandboxManager(self.engine, self.root, self.root, allow_local_rw=True)
        self.manager.provision('s', 'work', 'rw')

    def tearDown(self):
        self.manager.close()
        self.engine.close()
        self.tmp.cleanup()

    def operation(self, command):
        return dict(session_id='s', operation_id='operation', tool='RunCommand',
                    arguments={'command': command}, timeout_s=3)

    def test_progress_is_observable_before_completion_and_retry_has_no_side_effect(self):
        operation = self.operation('while [ ! -f proceed ]; do sleep 0.02; done; echo once >> output; cat output')
        with server(self.manager) as url:
            remote = Remote(url, 'internal')
            accepted = remote('start', **operation)
            self.assertEqual(accepted, remote('start', **operation))
            events = []
            deadline = time.monotonic() + 2
            while not any(e['type'] == 'running' for e in events) and time.monotonic() < deadline:
                events += list(Client(url, 'internal').event_batch('s', events[-1]['seq'] if events else 0))
            self.assertEqual([e['type'] for e in events], ['started', 'running'])
            self.assertEqual(len(self.engine.created), 1)
            with self.assertRaises(Fault):
                remote('start', **{**operation, 'arguments': {'command': 'echo changed'}})
            (self.root / 'work/proceed').touch()
            progress = []
            result = remote.execute(on_event=progress.append, **operation)
            self.assertEqual(result['stdout'], 'once\n')
            self.assertEqual(len([e for e in progress if e['type'] == 'result']), 1)
            self.assertEqual(result, remote.execute(**operation))
            self.assertEqual(len(self.engine.created), 1)
            replay = remote('events', session_id='s', after=events[-1]['seq'])['events']
            self.assertEqual([e['type'] for e in replay], ['result'])
            self.assertEqual(replay[0]['result'], result)

    def test_cancelled_operation_stream_has_one_terminal_after_cleanup(self):
        operation = self.operation('sleep 10')
        self.manager.start(**operation)
        events = []
        deadline = time.monotonic() + 2
        while not any(e['type'] == 'running' for e in events) and time.monotonic() < deadline:
            events += self.manager.events('s', events[-1]['seq'] if events else 0)
        self.manager.cancel('s')
        self.manager.release('s')
        results = [event for event in self.manager.session('s')['events'] if event['type'] == 'result']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['result']['error']['kind'], 'cancelled')
        self.assertFalse(self.engine.containers)

    def test_many_released_sessions_do_not_exhaust_manager_capacity(self):
        self.manager.release('s')
        for i in range(520):
            sid = 'released-' + str(i)
            self.manager.provision(sid, 'work', 'rw')
            self.manager.release(sid)
        self.manager.provision('fresh', 'work', 'rw')
        self.assertLessEqual(len(self.manager.sessions), 130)
