"""Public B6 specifications and synthetic replay solutions (not quality evidence)."""
import textwrap


SLUG_SPEC = """Implement slugify(text: str) -> str in solution.py using only the Python standard library.
Normalize text with Unicode NFKC, then casefold(). Keep characters for which
str.isalnum() is true (including non-Latin letters). Replace each maximal run of
all other characters, including underscores and whitespace, with one ASCII '-'.
Remove leading/trailing '-'. Do not transliterate. Empty input or input containing
only separators produces ''. Inputs are always strings. Do not print anything.
"""

LOG_SPEC = """Implement aggregate_logs(lines: list[str]) -> dict in solution.py.
Each valid line is YYYY-MM-DDTHH:MM:SSZ|LEVEL|message, with exact zero-padded ASCII
digits, a real Gregorian calendar date/time (no leap seconds), and LEVEL one of
INFO, WARNING, ERROR. Split on the first two pipes; the message may be empty or
contain more pipes. Ignore invalid lines; do not strip or repair them.
Group valid lines by UTC hour, using keys YYYY-MM-DDTHH:00:00Z and values
{'count': <integer total>, 'errors': <integer ERROR count>}. Count duplicates.
Input order does not matter; dictionary key order does not matter. Empty input
returns {}. Inputs are lists of strings. Use only the standard library; do not print.
"""

RECORD_SPEC = """Implement normalize_records(records: list) -> list[dict] in solution.py.
Keep only dictionary entries with string fields 'name' and 'date'; ignore extra
fields. Normalize name by strip(), Unicode NFC, casefold(), then NFC again.
Skip names empty after normalization. Date must be exactly YYYY-MM-DD using
zero-padded ASCII digits and be a valid Gregorian date, years 0001..9999.
Do not trim dates or accept alternative ISO formats. Skip invalid entries.
Deduplicate by (normalized name, date). Return dictionaries containing only 'name'
and 'date', sorted by date ascending, then name in Python string order.
Empty input returns []. Preserve Unicode (no transliteration). Handle leap years,
including the century rule. Use only the standard library; do not print.
"""

REFERENCES = {
    "B6.1": textwrap.dedent('''\
        import re
        import unicodedata

        def slugify(text):
            text = unicodedata.normalize('NFKC', text).casefold()
            chars = ''.join(c if c.isalnum() else '-' for c in text)
            return re.sub('-+', '-', chars).strip('-')
        '''),
    "B6.2": textwrap.dedent('''\
        import re
        from datetime import datetime

        def aggregate_logs(lines):
            result = {}
            for line in lines:
                parts = line.split('|', 2)
                if len(parts) != 3:
                    continue
                stamp, level, _ = parts
                if level not in ('INFO', 'WARNING', 'ERROR'):
                    continue
                if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', stamp):
                    continue
                try:
                    datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
                except ValueError:
                    continue
                bucket = result.setdefault(stamp[:13] + ':00:00Z', {'count': 0, 'errors': 0})
                bucket['count'] += 1
                bucket['errors'] += int(level == 'ERROR')
            return result
        '''),
    "B6.3": textwrap.dedent('''\
        import re
        import unicodedata
        from datetime import date

        def normalize_records(records):
            unique = set()
            for record in records:
                if not isinstance(record, dict):
                    continue
                name, day = record.get('name'), record.get('date')
                if not isinstance(name, str) or not isinstance(day, str):
                    continue
                name = unicodedata.normalize('NFC', unicodedata.normalize('NFC', name.strip()).casefold())
                if not name or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day):
                    continue
                try:
                    date.fromisoformat(day)
                except ValueError:
                    continue
                unique.add((name, day))
            return [{'name': name, 'date': day} for name, day in sorted(unique, key=lambda p: (p[1], p[0]))]
        '''),
}


def cases():
    definitions = [
        ("B6.1", "slugify", "text", SLUG_SPEC,
         [("Hello World", "hello-world"), ("  A___B! ", "a-b")]),
        ("B6.2", "aggregate_logs", "lines", LOG_SPEC,
         [([], {}), (["2026-01-01T10:15:00Z|INFO|hello", "2026-01-01T10:45:01Z|ERROR|oops"],
                     {"2026-01-01T10:00:00Z": {"count": 2, "errors": 1}})]),
        ("B6.3", "normalize_records", "records", RECORD_SPEC,
         [([], []), ([{"name": " Alice ", "date": "2024-02-29"}],
                     [{"name": "alice", "date": "2024-02-29"}])]),
    ]
    result = []
    for identifier, function, argument, spec, examples in definitions:
        public = ("import unittest\nfrom solution import " + function + "\n\n"
                  "class PublicTests(unittest.TestCase):\n")
        for index, (value, expected) in enumerate(examples):
            public += f"    def test_example_{index}(self):\n        self.assertEqual({function}({value!r}), {expected!r})\n"
        result.append({
            "id": identifier, "prompt": f"Read task.md and implement {function} in solution.py. Run the public tests.",
            "fixture": {"task.md": spec + "\nRun examples: python -m unittest test_public -v\n"
                        "Only solution.py is graded; do not depend on other local files.\n",
                        "solution.py": f"def {function}({argument}):\n    raise NotImplementedError\n",
                        "test_public.py": public},
            "check": "python_function",
            "replay": [{"name": "ReadFile", "arguments": {"path": "task.md"}},
                       {"name": "WriteFile", "arguments": {"path": "solution.py", "content": REFERENCES[identifier]}},
                       {"name": "RunCommand", "arguments": {"command": "python -m unittest test_public -v"}}],
        })
    return result
