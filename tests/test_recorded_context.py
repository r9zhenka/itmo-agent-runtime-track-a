import copy
import json
import unittest
from runtime.recorded_context import normalize_ls, portable_context_digest


FUSE = ('total 5\ndrwx------ 1 1000 1000 0 Nov 20 10:52 .\n'
        'drwxr-xr-x 1 root root 4096 Nov 20 10:52 ..\n'
        '-rw------- 1 1000 1000 124 Nov 20 10:52 spec.md\n')
BIND = ('total 12\ndrwxr-xr-x 2 1001 1001 4096 Dec  1 12:30 .\n'
        'drwxr-xr-x 9 root root 8192 Dec  1 12:30 ..\n'
        '-rw-r--r-- 1 1001 1001 124 Dec  1 12:30 spec.md\n')


def context(output, command='ls -la /work', tool='RunCommand', **changes):
    result = {'stdout': output, 'stderr': '', 'error': None, 'exit_code': 0, 'truncated': False}
    result.update(changes)
    return [{'role': 'system', 'content': 'fixed'}, {'role': 'user', 'content': 'fixed'},
            {'role': 'assistant', 'tool_calls': [{'id': 'one', 'function': {'name': tool, 'arguments': json.dumps({'command': command})}}]},
            {'role': 'tool', 'tool_call_id': 'one', 'content': json.dumps(result)}]


class PortableContextTests(unittest.TestCase):
    def test_only_incidental_ls_metadata_changes_are_ignored(self):
        self.assertEqual(normalize_ls(FUSE), normalize_ls(BIND))
        for command in ('ls -la /work', 'ls -al /work/sales && cat task.md', 'ls -la /work; echo after'):
            self.assertEqual(portable_context_digest(context(FUSE, command), []),
                             portable_context_digest(context(BIND, command), []))

    def test_names_filetypes_regular_sizes_order_and_following_text_are_significant(self):
        reference = portable_context_digest(context(FUSE), [])
        variants = [BIND.replace('spec.md', 'other.md'), BIND.replace(' 124 ', ' 125 '),
                    BIND.replace('-rw-r--r--', 'drw-r--r--'),
                    '\n'.join([*BIND.splitlines()[:1], *reversed(BIND.splitlines()[1:])]) + '\n',
                    BIND + 'changed actual file content\n']
        for output in variants:
            self.assertNotEqual(reference, portable_context_digest(context(output), []), output)
        self.assertEqual(normalize_ls(FUSE + '---\nfile contents\n'), normalize_ls(BIND + '---\nfile contents\n'))

    def test_non_ls_commands_readfile_and_embedded_ls_text_are_not_masked(self):
        for command in ('cat task.md', "echo 'ls -la /work'", 'python -c "print(\'ls -la /work\')"',
                        'cat file; ls -la /work', 'ls -la /elsewhere', 'ls -la /work-not-work'):
            self.assertNotEqual(portable_context_digest(context(FUSE, command), []),
                                portable_context_digest(context(BIND, command), []), command)
        self.assertNotEqual(portable_context_digest(context(FUSE, tool='ReadFile'), []),
                            portable_context_digest(context(BIND, tool='ReadFile'), []))

    def test_malformed_or_nonleading_listing_is_never_masked(self):
        for text in (FUSE.replace('total 5', 'total unknown'), FUSE.replace(' 124 ', ' unknown '),
                     FUSE.replace('Nov 20 10:52 spec.md', 'not-a-timestamp spec.md'),
                     'unrelated prefix\n' + FUSE, 'total 5\nnot a listing\n'):
            self.assertEqual(normalize_ls(text), text)

    def test_errors_exit_truncation_and_other_stream_remain_significant(self):
        reference = portable_context_digest(context(FUSE), [])
        for change in ({'exit_code': 1}, {'error': {'kind': 'command'}}, {'truncated': True}, {'stderr': 'warning'}):
            self.assertNotEqual(reference, portable_context_digest(context(BIND, **change), []))

    def test_tool_arguments_and_unrelated_conversation_remain_significant(self):
        original = context(FUSE)
        other = context(BIND); other[1]['content'] = 'changed request'
        self.assertNotEqual(portable_context_digest(original, []), portable_context_digest(other, []))
        self.assertNotEqual(portable_context_digest(original, []),
                            portable_context_digest(context(BIND, 'ls -la /work && echo injected'), []))


class FixtureEnumerationTests(unittest.TestCase):
    def scoped(self, task, output, command):
        from baf.cases import cases, prompt
        messages = context(output, command)
        messages[1]['content'] = prompt(next(case for case in cases() if case['id'] == task))
        return portable_context_digest(messages, [])

    def test_only_exact_search_task_command_sorts_three_matching_records(self):
        from runtime.recorded_context import SEARCH_COMMAND
        prefix = './README.md\n./src/dates.py\n./src/main.py\n---\n'
        records = ['./README.md:1:parse_date is useful.\n', './src/dates.py:1:def parse_date(text):\n',
                   './src/main.py:1:from dates import parse_date\n']
        suffix = '---\nparse_date is useful.\n'
        first = prefix + ''.join(records) + suffix
        reordered = prefix + ''.join(reversed(records)) + suffix
        self.assertEqual(self.scoped('B2.1', first, SEARCH_COMMAND), self.scoped('B2.1', reordered, SEARCH_COMMAND))
        for command in (SEARCH_COMMAND + ' ', 'grep -rn "parse_date" .', 'echo ' + repr(SEARCH_COMMAND)):
            self.assertNotEqual(self.scoped('B2.1', first, command), self.scoped('B2.1', reordered, command))
        self.assertNotEqual(self.scoped('B9.1', first, SEARCH_COMMAND), self.scoped('B9.1', reordered, SEARCH_COMMAND))

    def test_search_content_paths_numbers_multiplicity_and_surroundings_stay_significant(self):
        from runtime.recorded_context import SEARCH_COMMAND
        text = ('./README.md\n./src/dates.py\n./src/main.py\n---\n'
                './README.md:1:parse_date is useful.\n./src/dates.py:1:def parse_date(text):\n'
                './src/main.py:1:from dates import parse_date\n---\nparse_date is useful.\n')
        expected = self.scoped('B2.1', text, SEARCH_COMMAND)
        variants = [text.replace('def parse_date(text):', 'def parse_date(other):'),
                    text.replace('dates.py:1:', 'dates.py:2:'), text.replace('dates.py:1:', 'other.py:1:'),
                    text.replace('./src/main.py:1:from dates import parse_date\n', ''),
                    text.replace('./src/main.py:1:from dates import parse_date\n', './src/dates.py:1:def parse_date(text):\n'),
                    text.replace('---\n', 'invalid separator\n', 1), text + 'changed trailing content\n']
        for output in variants:
            self.assertNotEqual(expected, self.scoped('B2.1', output, SEARCH_COMMAND))

    def test_only_complete_two_file_find_block_sorts_for_exact_task_command(self):
        from runtime.recorded_context import FIND_COMMAND
        # Replace the one-file ls fixture with the actual two-file B9 listing shape.
        listing = FUSE.replace('-rw------- 1 1000 1000 124 Nov 20 10:52 spec.md\n',
                               '-rw------- 1 1000 1000 68 Nov 20 10:52 facts.json\n'
                               '-rw------- 1 1000 1000 218 Nov 20 10:52 style.md\n')
        first = listing + '/work/facts.json\n/work/style.md\n'
        other = listing + '/work/style.md\n/work/facts.json\n'
        self.assertEqual(self.scoped('B9.1', first, FIND_COMMAND), self.scoped('B9.1', other, FIND_COMMAND))
        for command in (FIND_COMMAND + ' ', 'find /work -type f', 'echo ' + repr(FIND_COMMAND)):
            self.assertNotEqual(self.scoped('B9.1', first, command), self.scoped('B9.1', other, command))
        for output in (listing + '/work/facts.json\n', other + '/work/extra.txt\n',
                       listing + '/work/facts.json\n/work/facts.json\n',
                       other.replace('/work/style.md', '/work/other.md')):
            self.assertNotEqual(self.scoped('B9.1', first, FIND_COMMAND), self.scoped('B9.1', output, FIND_COMMAND))
        self.assertNotEqual(self.scoped('B2.1', first, FIND_COMMAND), self.scoped('B2.1', other, FIND_COMMAND))
