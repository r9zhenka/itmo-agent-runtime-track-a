"""Public B7 inputs and synthetic replay answers; not model-quality evidence."""
import json


TRANSFER_SPEC = """Read journey.json and determine whether the passenger can board the connection.
All timestamps use YYYY-MM-DDTHH:MM, in the same fixed local timezone without DST.
Dates matter, including across midnight. The passenger is ready at arrival plus
walk_minutes. Boarding closes boarding_closes_minutes_before minutes before
departure. Boarding is possible exactly at closing time (ready <= closes).
Write answer.json with exactly these keys:
can_transfer (boolean), ready_at and boarding_closes_at (timestamps in the same
format), margin_minutes (integer: closing time minus ready time, negative if late).
No additional delays or assumptions apply.
"""

POLICY_SPEC = """Read policy.yaml (JSON syntax, a YAML 1.2 subset).
Determine access to the exact action/resource in query for EVERY role.
Roles inherit all rules of all ancestors, transitively, as well as their own rules.
The inheritance graph is acyclic. Match BOTH action and resource exactly.
Any matching deny overrides all matching allows, including a child's own allow.
Without a matching allow, access is denied by default. Rule IDs are unique.
Write answer.json with exactly two keys:
allowed_roles: sorted list of allowed role names;
decisions: list sorted by role name, with one object per role containing exactly
role (string), allowed (boolean), allow_rules and deny_rules (sorted lists of all
matching inherited/local rule IDs, each ID once even with diamond inheritance).
Include evidence even when an allow is overridden by a deny.
"""

CONFLICT_SPEC = """Read rules.json. Find every pair of rules that contradict each other in
at least one of the supplied contexts. Each 'when' mapping is a conjunction of
exact field/value matches against a context's facts; an empty mapping always
matches. Rules do not infer new facts. Unspecified facts do not match.
A contradiction means BOTH rules apply in the SAME supplied context, name the
SAME action AND resource, and have opposite effects (allow versus deny).
All rules have equal priority; there is no deny-overrides resolution in this task.
Consider only the supplied contexts, not hypothetical ones. Same-effect overlaps
are not contradictions. Write answer.json with exactly one key 'conflicts':
a list of objects containing exactly 'rules' (the two rule IDs sorted ascending)
and 'contexts' (all matching context IDs sorted ascending, each once).
Sort conflicts lexicographically by the pair of rule IDs. Report every pair once;
an empty list means there are no contradictions.
"""


def cases():
    journey = {"arrival": "2026-11-19T14:12", "walk_minutes": 15,
               "departure": "2026-11-19T14:35", "boarding_closes_minutes_before": 10}
    policy = {
        "query": {"action": "read", "resource": "reports"},
        "roles": {
            "guest": {"inherits": [], "rules": []},
            "reader": {"inherits": [], "rules": ["A1"]},
            "analyst": {"inherits": ["reader"], "rules": []},
            "editor": {"inherits": ["reader"], "rules": ["D2", "D3"]},
            "suspended": {"inherits": ["reader"], "rules": ["D1"]},
            "lead": {"inherits": ["analyst", "suspended"], "rules": ["A2"]},
        },
        "rules": [
            {"id": "A1", "action": "read", "resource": "reports", "effect": "allow"},
            {"id": "A2", "action": "read", "resource": "reports", "effect": "allow"},
            {"id": "D1", "action": "read", "resource": "reports", "effect": "deny"},
            {"id": "D2", "action": "write", "resource": "reports", "effect": "deny"},
            {"id": "D3", "action": "read", "resource": "payroll", "effect": "deny"},
        ],
    }
    rules = {
        "contexts": [
            {"id": "C1", "facts": {"employment": "intern", "day": "weekday"}},
            {"id": "C2", "facts": {"employment": "staff", "day": "weekday"}},
            {"id": "C3", "facts": {"employment": "staff", "day": "weekend"}},
        ],
        "rules": [
            {"id": "R1", "when": {}, "action": "read", "resource": "reports", "effect": "allow"},
            {"id": "R2", "when": {"employment": "intern"}, "action": "read", "resource": "reports", "effect": "deny"},
            {"id": "R3", "when": {"day": "weekend"}, "action": "read", "resource": "reports", "effect": "deny"},
            {"id": "R4", "when": {"employment": "intern", "day": "weekend"}, "action": "read", "resource": "reports", "effect": "allow"},
            {"id": "R5", "when": {"employment": "staff"}, "action": "write", "resource": "reports", "effect": "deny"},
            {"id": "R6", "when": {"employment": "staff"}, "action": "read", "resource": "payroll", "effect": "deny"},
            {"id": "R7", "when": {"employment": "staff"}, "action": "read", "resource": "reports", "effect": "allow"},
        ],
    }
    # Manually derived replay answers. The checker independently computes its
    # expectations from the original fixture; it never imports these answers.
    definitions = [
        ("B7.1", "journey.json", journey, TRANSFER_SPEC,
         {"can_transfer": False, "ready_at": "2026-11-19T14:27",
          "boarding_closes_at": "2026-11-19T14:25", "margin_minutes": -2}),
        ("B7.2", "policy.yaml", policy, POLICY_SPEC,
         {"allowed_roles": ["analyst", "editor", "reader"], "decisions": [
             {"role": "analyst", "allowed": True, "allow_rules": ["A1"], "deny_rules": []},
             {"role": "editor", "allowed": True, "allow_rules": ["A1"], "deny_rules": []},
             {"role": "guest", "allowed": False, "allow_rules": [], "deny_rules": []},
             {"role": "lead", "allowed": False, "allow_rules": ["A1", "A2"], "deny_rules": ["D1"]},
             {"role": "reader", "allowed": True, "allow_rules": ["A1"], "deny_rules": []},
             {"role": "suspended", "allowed": False, "allow_rules": ["A1"], "deny_rules": ["D1"]},
         ]}),
        ("B7.3", "rules.json", rules, CONFLICT_SPEC,
         {"conflicts": [{"rules": ["R1", "R2"], "contexts": ["C1"]},
                        {"rules": ["R1", "R3"], "contexts": ["C3"]},
                        {"rules": ["R3", "R7"], "contexts": ["C3"]}]}),
    ]
    return [{
        "id": identifier,
        "prompt": "Read task.md and " + filename + ". Solve the reasoning task and write answer.json.",
        "fixture": {"task.md": spec, filename: json.dumps(data, indent=2) + "\n"},
        "check": "reasoning", "input_file": filename,
        "replay": [{"name": "ReadFile", "arguments": {"path": "task.md"}},
                   {"name": "ReadFile", "arguments": {"path": filename}},
                   {"name": "WriteFile", "arguments": {"path": "answer.json", "content": json.dumps(answer) + "\n"}}],
    } for identifier, filename, data, spec, answer in definitions]
