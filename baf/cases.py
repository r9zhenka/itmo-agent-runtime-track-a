"""Course B1–B5 task specifications, expanded into reproducible local fixtures.

Replay scripts are synthetic fixtures, NOT recorded successful LLM evaluations.
Checkers only inspect bytes/data; they never execute generated code on the host.
"""
import ast
import csv
import io
import json
import re
import shlex
from pathlib import Path


def command(code):
    return {"name": "RunCommand", "arguments": {"command": "python -c " + shlex.quote(code)}}


def write(path, content):
    return {"name": "WriteFile", "arguments": {"path": path, "content": content}}


def cases():
    contract = "\n".join(f"## Section {i}\n" + "General delivery conditions.\n" * 35 for i in range(1, 16))
    contract += "\nPayment is due within 45 calendar days of acceptance.\n"
    readme = "# Example\n\n## Install\npip install widget==1.2\n\n## History\nVersion 1.2 was released in May.\n"
    files = {f"src/module_{i:03}.py": ("import os\nVALUE = os.environ['DB_URL']\n" if i % 17 == 0
             else "# DB_URL is mentioned in documentation only\nVALUE = 1\n") for i in range(200)}
    countries = 'countries:\n  - "no"\n  - "on"\n'
    tests = """import unittest
from totals import compute_total
class TotalTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(compute_total([]), 0)
    def test_values(self): self.assertEqual(compute_total([2, 3]), 5)
"""
    failing_tests = "import unittest\nclass Example(unittest.TestCase):\n" + "".join(
        f"    def test_{i:02}(self): self.assertEqual({i}, {i + (i in (3, 11, 17))})\n" for i in range(20))
    return [
        {"id": "B1.1", "prompt": "Read config/app.yaml and write only the service port to answer.txt.",
         "fixture": {"config/app.yaml": "service:\n  name: demo\n  port: 8137\n", "README.md": "Development port: 3000 (not the service port).\n"},
         "replay": [{"name": "ReadFile", "arguments": {"path": "config/app.yaml"}}, write("answer.txt", "8137\n")],
         "expected": {"answer.txt": "8137"}},
        {"id": "B1.2", "prompt": "Read contract.md. Write the payment term in calendar days to answer.txt, only the number.",
         "fixture": {"contract.md": contract},
         "replay": [{"name": "ReadFile", "arguments": {"path": "contract.md"}}, write("answer.txt", "45\n")],
         "expected": {"answer.txt": "45"}},
        {"id": "B1.3", "prompt": "What late-payment penalty does contract.md specify? Write it to answer.txt, or НЕТ ДАННЫХ if absent.",
         "fixture": {"contract.md": contract},
         "replay": [{"name": "ReadFile", "arguments": {"path": "contract.md"}}, write("answer.txt", "НЕТ ДАННЫХ\n")],
         "expected": {"answer.txt": "НЕТ ДАННЫХ"}},
        {"id": "B2.1", "prompt": "Find the file defining parse_date. Write its relative path to answer.txt.",
         "fixture": {"src/dates.py": "def parse_date(text):\n    return text.split('-')\n",
                     "src/main.py": "from dates import parse_date\n", "README.md": "parse_date is useful.\n"},
         "replay": [command("from pathlib import Path; p=next(p for p in Path('src').rglob('*.py') if 'def parse_date(' in p.read_text()); Path('answer.txt').write_text(str(p))")],
         "expected": {"answer.txt": "src/dates.py"}},
        {"id": "B2.2", "prompt": "Find every Python file that reads the DB_URL environment variable. Ignore comments. Write sorted relative paths, one per line, to answer.txt.",
         "fixture": files,
         "replay": [command("import ast; from pathlib import Path; out=[]\nfor p in Path('src').rglob('*.py'):\n t=ast.parse(p.read_text())\n if any(isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and n.value.attr=='environ' and isinstance(n.slice,ast.Constant) and n.slice.value=='DB_URL' for n in ast.walk(t)): out.append(str(p))\nPath('answer.txt').write_text('\\n'.join(sorted(out)))")],
         "expected": {"answer.txt": "\n".join(f"src/module_{i:03}.py" for i in range(0, 200, 17))}},
        {"id": "B2.3", "prompt": "Find the parse_date implementation that parses ISO 8601 timestamps and preserves their timezone. Write its relative path to answer.txt.",
         "fixture": {"legacy/dates.py": "from datetime import datetime\ndef parse_date(text):\n    return datetime.strptime(text, '%Y-%m-%d')\n",
                     "current/dates.py": "from datetime import datetime\ndef parse_date(text):\n    return datetime.fromisoformat(text.replace('Z', '+00:00'))\n"},
         "replay": [command("from pathlib import Path; p=next(p for p in Path('.').rglob('dates.py') if 'fromisoformat' in p.read_text()); Path('answer.txt').write_text(str(p))")],
         "expected": {"answer.txt": "current/dates.py"}},
        {"id": "B3.1", "prompt": "Create config.json according to spec.md. Do not add extra fields.",
         "fixture": {"spec.md": 'JSON object: host string "127.0.0.1", port integer 8080, debug boolean false, tags array ["api", "local"]. No other fields.\n'},
         "replay": [write("config.json", json.dumps({"host": "127.0.0.1", "port": 8080, "debug": False, "tags": ["api", "local"]}))],
         "check": "config"},
        {"id": "B3.2", "prompt": "Convert input.csv to report.csv, preserving columns and sorting rows by date ascending.",
         "fixture": {"input.csv": "date,item,amount\n2026-03-02,tea,8\n2026-01-01,coffee,12\n2026-02-14,milk,4\n"},
         "replay": [command("import csv; from pathlib import Path; rows=list(csv.DictReader(Path('input.csv').open())); f=Path('report.csv').open('w',newline=''); w=csv.DictWriter(f,fieldnames=['date','item','amount']); w.writeheader(); w.writerows(sorted(rows,key=lambda r:r['date'])); f.close()")],
         "check": "csv"},
        {"id": "B3.3", "prompt": "Create countries.yaml with countries as a list containing strings no and on. Create postal.yaml with postal as the string 0123. Use quoted scalar values to preserve types.",
         "fixture": {"task.md": "countries: no, on; postal: 0123. All values must remain strings.\n"},
         "replay": [write("countries.yaml", countries), write("postal.yaml", 'postal: "0123"\n')],
         "check": "yaml_strings"},
        {"id": "B4.1", "prompt": "Update widget from version 1.2 to 1.3 only in the Install section of README.md. Preserve all other bytes.",
         "fixture": {"README.md": readme},
         "replay": [command("from pathlib import Path; p=Path('README.md'); p.write_bytes(p.read_bytes().replace(b'widget==1.2',b'widget==1.3'))")],
         "exact": {"README.md": readme.replace("widget==1.2", "widget==1.3").encode()}},
        {"id": "B4.2", "prompt": "Rename calc_total to compute_total throughout the Python project, including imports and tests. Preserve behavior. Run python -m unittest -v.",
         "fixture": {"totals.py": "def calc_total(values):\n    return sum(values)\n",
                     "main.py": "from totals import calc_total\nprint(calc_total([1, 2]))\n",
                     "test_totals.py": tests.replace("compute_total", "calc_total")},
         "replay": [command("from pathlib import Path\nfor p in Path('.').glob('*.py'): p.write_bytes(p.read_bytes().replace(b'calc_total',b'compute_total'))"),
                    {"name": "RunCommand", "arguments": {"command": "python -m unittest -v"}}],
         "check": "rename"},
        {"id": "B4.3", "prompt": "Change only the price of item X to 990 in prices.csv. Preserve cp1251 encoding and CRLF line endings.",
         "fixture": {"prices.csv": "товар,цена\r\nX,100\r\nY,200\r\n".encode("cp1251")},
         "replay": [command("from pathlib import Path; p=Path('prices.csv'); p.write_bytes(p.read_bytes().replace(b'X,100\\r\\n',b'X,990\\r\\n'))")],
         "exact": {"prices.csv": "товар,цена\r\nX,990\r\nY,200\r\n".encode("cp1251")}},
        {"id": "B5.1", "prompt": "Run python stats.py data.csv and write the median it reports to answer.txt.",
         "fixture": {"stats.py": "import statistics,sys\nprint(statistics.median(float(x) for x in open(sys.argv[1]) if x.strip()))\n",
                     "data.csv": "11\n2\n7\n3\n20\n"},
         "replay": [{"name": "RunCommand", "arguments": {"command": "python stats.py data.csv"}}, write("answer.txt", "7.0\n")],
         "check": "median"},
        {"id": "B5.2", "prompt": "Run the unittest suite. Write the short names of failed tests (like test_01), sorted one per line, to failed.txt.",
         "fixture": {"test_examples.py": failing_tests},
         "replay": [{"name": "RunCommand", "arguments": {"command": "python -m unittest -v"}},
                    write("failed.txt", "test_03\ntest_11\ntest_17\n")],
         "expected": {"failed.txt": "test_03\ntest_11\ntest_17"}},
        {"id": "B5.3", "prompt": "Run sh build.sh. Did it succeed? Write yes or no and the reason to answer.txt. Determine success from the exit status.",
         "fixture": {"build.sh": "#!/bin/sh\necho OK\necho 'missing dependency' >&2\nexit 1\n"},
         "replay": [{"name": "RunCommand", "arguments": {"command": "sh build.sh"}},
                    write("answer.txt", "no: exit 1, missing dependency\n")],
         "check": "build"},
    ]


def prompt(case):
    return f"[BAF {case['id']}] {case['prompt']}"


def prepare(case, workdir):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=False)
    for name, value in case["fixture"].items():
        target = workdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value.encode() if isinstance(value, str) else value)


def check(case, workdir, events):
    """Return a verdict; missing/corrupt output is a failure, not a runner crash."""
    root = Path(workdir).resolve()

    def read(name):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Output path escapes workspace")
        with path.open("rb") as file:
            data = file.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError("Output too large")
        return data

    def text(name):
        return read(name).decode("utf-8").strip()

    try:
        for name, expected in case.get("expected", {}).items():
            assert text(name) == expected, f"Incorrect {name}"
        for name, expected in case.get("exact", {}).items():
            assert read(name) == expected, f"Bytes differ in {name}"
        kind = case.get("check")
        if kind == "config":
            data = json.loads(text("config.json"))
            assert data == {"host": "127.0.0.1", "port": 8080, "debug": False, "tags": ["api", "local"]}
            assert type(data["port"]) is int and type(data["debug"]) is bool
        elif kind == "csv":
            rows = list(csv.DictReader(io.StringIO(text("report.csv"))))
            expected = sorted(csv.DictReader(io.StringIO(case["fixture"]["input.csv"])), key=lambda row: row["date"])
            assert rows == expected
        elif kind == "yaml_strings":
            # Accept JSON (a YAML 1.2 subset) or the requested simple quoted YAML.
            country_text, postal_text = text("countries.yaml"), text("postal.yaml")
            if country_text.startswith("{"):
                assert json.loads(country_text) == {"countries": ["no", "on"]}
            else:
                lines = country_text.splitlines()
                assert lines[0] == "countries:" and len(lines) == 3
                assert [ast.literal_eval(line.strip().removeprefix("- ")) for line in lines[1:]] == ["no", "on"]
            if postal_text.startswith("{"):
                assert json.loads(postal_text) == {"postal": "0123"}
            else:
                assert postal_text.startswith("postal:")
                assert ast.literal_eval(postal_text.split(":", 1)[1].strip()) == "0123"
        elif kind == "rename":
            for name, original in case["fixture"].items():
                assert read(name) == original.replace("calc_total", "compute_total").encode()
            assert any(e["type"] == "tool_result" and e.get("tool") == "RunCommand"
                       and e["result"].get("exit_code") == 0
                       and "Ran 2 tests" in e["result"].get("stderr", "") for e in events), "Tests were not observed passing in sandbox"
        elif kind == "median":
            assert float(text("answer.txt")) == 7
        elif kind == "build":
            answer = text("answer.txt").lower()
            assert re.match(r"^no\b", answer) and "missing dependency" in answer and "1" in answer
        return {"pass": True, "reason": "ok"}
    except (AssertionError, ValueError, OSError, KeyError, TypeError, SyntaxError) as exc:
        return {"pass": False, "reason": str(exc) or "Output does not match specification"}
