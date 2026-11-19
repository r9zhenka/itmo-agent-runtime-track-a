"""B8 multi-source fixtures and synthetic replay, not live-model evidence."""
import json


SALES_SPEC = """Read request.json and all five CSV files listed there. Calculate signed net
sales for the requested quarter: start inclusive, end exclusive. Dates are ISO
calendar dates. Amounts are RUB with exactly two decimal places. Negative amounts
are refunds and must be included. Every row is a separate transaction; do not
deduplicate. All rows are valid. Use exact arithmetic (kopecks or Decimal).
Write answer.json with exactly: quarter (from request), currency ('RUB'),
total_kopecks (integer), sources (list sorted by file path). Each source contains
exactly file, total_kopecks (integer), row_count (integer count of in-period rows).
Include every input file, even if it contributes zero rows. No other fields.
"""

MEETING_SPEC = """Read all ten Markdown protocols in meetings/. Collect only decisions explicitly
accepted or reaffirmed by the meeting, not proposals, discussion or rejected items.
Decision IDs identify the decisions; do not invent or paraphrase IDs. Reaffirmations
of the same ID are one decision with multiple sources, not new decisions. Repeated
accepted mentions agree on owner and deadline. Suggested owners/dates in unaccepted
proposals are not assignments. If no owner or deadline was agreed, use JSON null.
Write answer.json with exactly one key decisions: a list sorted by decision_id.
Each record has exactly decision_id, owner (person's name or null), due_date
(YYYY-MM-DD or null), sources. Sources lists EVERY section explicitly accepting
or reaffirming this decision, sorted by file then section. Each source has exactly
file (relative path) and section (the P1/P2 heading ID). Exclude mentions that only
discuss a decision. Do not add prose summaries; IDs and citations identify its text.
"""

REGULATION_SPEC = """Read request.json, catalog.json and both regulation documents. Select the version
in force on request.as_of: status must be 'approved', effective_from <= as_of;
among eligible versions choose the latest effective_from. Dates are inclusive ISO
calendar dates; there are no ties. A newer approved version may not yet be in force.
Publication date, file name and a larger version number do not override this rule.
Write answer.json with exactly as_of, version, source (selected file), values,
differences. Values lists ALL selected-version clauses sorted by clause_id, each
with exactly clause_id, value (integer or string as specified in the document),
unit (string). Compare against the other document and include only changed clauses
in differences, sorted by clause_id. Each difference has exactly clause_id, unit,
selected_value, other_value, selected_source, other_source. Source fields are
relative file paths; clause_id identifies the cited section in each source.
Both versions have the same clauses and units. No additional fields or assumptions.
"""


def cases():
    sales = {
        "sales/north.csv": "date,amount\n2025-12-31,9999.00\n2026-01-01,100.10\n2026-03-31,200.20\n",
        "sales/south.csv": "date,amount\n2026-02-28,0.10\n2026-03-01,0.20\n2026-04-01,500.00\n",
        "sales/east.csv": "date,amount\n2026-01-15,1234.56\n2026-02-01,-34.56\n",
        "sales/west.csv": "date,amount\n2026-03-31,20.00\n2026-01-01,80.00\n",
        "sales/online.csv": "date,amount\n2025-12-30,700.00\n2026-04-02,900.00\n",
    }
    sales_request = {"quarter": "2026-Q1", "start": "2026-01-01", "end": "2026-04-01",
                     "files": sorted(sales)}
    meetings = {
        "meetings/01.md": """# Meeting 2026-10-01
## P1
D101: The team accepted the decision to add restore drills. Owner: Анна.
The agreed deadline is 2026-10-20.
## P2
D900: Борис suggested replacing the database by 2026-10-15. No decision was made.
""",
        "meetings/02.md": """# Meeting 2026-10-02
## P1
D101 restore drills were discussed. A 2026-10-10 deadline was suggested but NOT
approved; this discussion does not reaffirm or change the earlier decision.
## P2
D901: The proposal to remove audit logs was rejected.
""",
        "meetings/03.md": """# Meeting 2026-10-03
## P1
D102: The team approved publishing the API examples. Owner: Борис.
No deadline was agreed. 2026-10-09 was merely suggested and not accepted.
""",
        "meetings/04.md": """# Meeting 2026-10-04
## P1
D101: The restore-drill decision was explicitly reaffirmed without changes:
Анна owns it and the deadline remains 2026-10-20.
""",
        "meetings/05.md": """# Meeting 2026-10-05
## P1
D103: The team accepted the decision to archive the old dashboard by 2026-10-31.
No owner was assigned. Ирина was suggested, but that assignment was not approved.
""",
        "meetings/06.md": """# Meeting 2026-10-06
## P1
D902: The team discussed migrating the queue. There was no vote or acceptance.
Suggested owner: Анна; suggested deadline: 2026-10-30.
""",
        "meetings/07.md": """# Meeting 2026-10-07
## P1
D104: The team approved a release freeze. Owner: Ирина. Deadline: 2026-11-01.
## P2
D903: Cancelling the release was proposed and rejected.
""",
        "meetings/08.md": """# Meeting 2026-10-08
## P1
D105: The team accepted publishing a glossary. No owner or deadline was assigned.
""",
        "meetings/09.md": """# Meeting 2026-10-09
## P1
D104 was mentioned in a status update only; there was no reaffirmation or amendment.
## P2
D904: A new monitoring vendor was proposed. The choice was deferred.
""",
        "meetings/10.md": """# Meeting 2026-10-10
## P1
D905: The proposal for a weekend release was rejected.
## P2
D106: The team approved documenting the rollback procedure.
Owner: Лев. Deadline: 2026-11-05.
""",
    }
    catalog = {"versions": [
        {"version": "v1", "file": "regulations/v1.md", "status": "approved",
         "published_on": "2026-09-20", "effective_from": "2026-10-01"},
        {"version": "v2", "file": "regulations/v2.md", "status": "approved",
         "published_on": "2026-11-01", "effective_from": "2026-12-01"},
    ]}
    regulations = {
        "request.json": json.dumps({"as_of": "2026-11-19"}),
        "catalog.json": json.dumps(catalog, indent=2),
        "regulations/v1.md": """# Operations regulation v1
Status: approved. Published: 2026-09-20. Effective from: 2026-10-01.
## C1
Retain backups for 30 days. Value type: integer. Unit: days.
## C2
Respond to support requests within 48 hours. Value type: integer. Unit: hours.
## C3
Store data in region EU. Value type: string. Unit: region.
""",
        "regulations/v2.md": """# Operations regulation v2
Status: approved. Published: 2026-11-01. Effective from: 2026-12-01.
This replacement takes effect on that date, not on publication.
## C1
Retain backups for 90 days. Value type: integer. Unit: days.
## C2
Respond to support requests within 24 hours. Value type: integer. Unit: hours.
## C3
Store data in region EU. Value type: string. Unit: region.
""",
    }
    # Replay answers are manually derived and never used by the checker.
    sales_answer = {"quarter": "2026-Q1", "currency": "RUB", "total_kopecks": 160060,
                    "sources": [
                        {"file": "sales/east.csv", "total_kopecks": 120000, "row_count": 2},
                        {"file": "sales/north.csv", "total_kopecks": 30030, "row_count": 2},
                        {"file": "sales/online.csv", "total_kopecks": 0, "row_count": 0},
                        {"file": "sales/south.csv", "total_kopecks": 30, "row_count": 2},
                        {"file": "sales/west.csv", "total_kopecks": 10000, "row_count": 2},
                    ]}
    meeting_answer = {"decisions": [
        {"decision_id": "D101", "owner": "Анна", "due_date": "2026-10-20", "sources": [
            {"file": "meetings/01.md", "section": "P1"}, {"file": "meetings/04.md", "section": "P1"}]},
        {"decision_id": "D102", "owner": "Борис", "due_date": None,
         "sources": [{"file": "meetings/03.md", "section": "P1"}]},
        {"decision_id": "D103", "owner": None, "due_date": "2026-10-31",
         "sources": [{"file": "meetings/05.md", "section": "P1"}]},
        {"decision_id": "D104", "owner": "Ирина", "due_date": "2026-11-01",
         "sources": [{"file": "meetings/07.md", "section": "P1"}]},
        {"decision_id": "D105", "owner": None, "due_date": None,
         "sources": [{"file": "meetings/08.md", "section": "P1"}]},
        {"decision_id": "D106", "owner": "Лев", "due_date": "2026-11-05",
         "sources": [{"file": "meetings/10.md", "section": "P2"}]},
    ]}
    regulation_answer = {
        "as_of": "2026-11-19", "version": "v1", "source": "regulations/v1.md",
        "values": [{"clause_id": "C1", "value": 30, "unit": "days"},
                   {"clause_id": "C2", "value": 48, "unit": "hours"},
                   {"clause_id": "C3", "value": "EU", "unit": "region"}],
        "differences": [
            {"clause_id": "C1", "unit": "days", "selected_value": 30, "other_value": 90,
             "selected_source": "regulations/v1.md", "other_source": "regulations/v2.md"},
            {"clause_id": "C2", "unit": "hours", "selected_value": 48, "other_value": 24,
             "selected_source": "regulations/v1.md", "other_source": "regulations/v2.md"},
        ],
    }
    definitions = [
        ("B8.1", SALES_SPEC, {"request.json": json.dumps(sales_request), **sales}, sales_answer),
        ("B8.2", MEETING_SPEC, meetings, meeting_answer),
        ("B8.3", REGULATION_SPEC, regulations, regulation_answer),
    ]
    return [{
        "id": identifier, "prompt": "Read task.md, combine the specified sources and write answer.json.",
        "fixture": {"task.md": spec, **inputs}, "check": "synthesis",
        "replay": [{"name": "ReadFile", "arguments": {"path": name}} for name in ["task.md", *sorted(inputs)]]
                  + [{"name": "WriteFile", "arguments": {"path": "answer.json", "content": json.dumps(answer)}}],
    } for identifier, spec, inputs, answer in definitions]
