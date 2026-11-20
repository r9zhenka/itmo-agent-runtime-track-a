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
