"""Evaluator-only inputs/oracles. Never included in the agent's workspace or image.

These checks are hidden from a benchmark session, not secret in this public repo.
Expected answers are literal fixtures, not computed by the replay implementations.
"""


def checks(identifier):
    if identifier == "B6.4":
        return "merge_intervals", [
            ("empty", [], []),
            ("touching", [[3, 5], [1, 3]], [[1, 5]]),
            ("nested", [[1, 9], [2, 3], [4, 8]], [[1, 9]]),
            ("disjoint", [[9, 12], [-3, -1], [2, 4]], [[-3, -1], [2, 4], [9, 12]]),
            ("duplicate", [[2, 5], [2, 5]], [[2, 5]]),
            ("points", [[0, 0], [1, 1], [1, 3], [8, 8]], [[0, 0], [1, 3], [8, 8]]),
            ("bridge", [[8, 10], [0, 3], [2, 9]], [[0, 10]]),
        ]
    if identifier == "C1":
        return "total_cents", [
            ("empty", [], 0),
            ("quantity", [{"price_cents": 125, "quantity": 3}], 375),
            ("zero_quantity", [{"price_cents": 999, "quantity": 0}], 0),
            ("refund", [{"price_cents": 250, "quantity": 4}, {"price_cents": 120, "quantity": -2}], 760),
            ("free", [{"price_cents": 0, "quantity": 100}], 0),
            ("large", [{"price_cents": 1000000000, "quantity": 1000000}], 1000000000000000),
        ]
    if identifier == "C3":
        return "parse_duration", [
            ("mixed", "2h3m4s", 7384),
            ("hours", "100h", 360000),
            ("minutes", "59m", 3540),
            ("zero", "0h0m0s", 0),
            ("skip_unit", "2h5s", 7205),
            ("empty", "", None),
            ("wrong_order", "1s2h", None),
            ("duplicate", "1h2h", None),
            ("range", "60s", None),
            ("leading_zero", "01m", None),
            ("unicode_digits", "２h", None),
            ("whitespace", " 1h", None),
            ("uppercase", "1H", None),
            ("negative", "-1s", None),
            ("unitless", "12", None),
            ("newline", "1h\n", None),
            ("wrong_type", 123, None),
        ]
    if identifier == "B6.1":
        return "slugify", [
            ("empty", "", ""),
            ("separators", " __! \t\n---", ""),
            ("ascii", "A Small Example 123", "a-small-example-123"),
            ("collapse", "--One__Two...THREE--", "one-two-three"),
            ("cyrillic", " Привет, МИР! ", "привет-мир"),
            ("compatibility", "Ｆｏｏ １２３", "foo-123"),
            ("casefold", "Straße", "strasse"),
            ("combining", "Cafe\u0301", "café"),
            ("emoji", "a🚀b 中文", "a-b-中文"),
        ]
    if identifier == "B6.2":
        return "aggregate_logs", [
            ("empty", [], {}),
            ("invalid", ["", "nonsense", "2026-01-01T00:00:00Z|DEBUG|x", "2026-01-01T00:00:00Z|INFO"], {}),
            ("unordered", ["2026-05-02T11:01:00Z|ERROR|b", "2026-05-02T10:59:59Z|INFO|a",
                           "2026-05-02T11:30:00Z|WARNING|c", "2026-05-02T11:01:00Z|ERROR|b"],
             {"2026-05-02T10:00:00Z": {"count": 1, "errors": 0},
              "2026-05-02T11:00:00Z": {"count": 3, "errors": 2}}),
            ("messages", ["2024-02-29T00:00:00Z|INFO|", "2024-02-29T00:00:01Z|ERROR|a|b|c"],
             {"2024-02-29T00:00:00Z": {"count": 2, "errors": 1}}),
            ("calendar", ["1900-02-29T12:00:00Z|INFO|x", "2000-02-29T12:00:00Z|INFO|yes",
                          "2026-04-31T12:00:00Z|ERROR|x", "2024-01-01T24:00:00Z|INFO|x"],
             {"2000-02-29T12:00:00Z": {"count": 1, "errors": 0}}),
            ("strict_format", ["2026-1-01T00:00:00Z|INFO|x", "2026-01-01T0:00:00Z|INFO|x",
                               "2026-01-01T00:00:00+00:00|INFO|x", " 2026-01-01T00:00:00Z|INFO|x",
                               "2026-01-01T00:00:00Z|info|x", "2026-01-01T00:00:60Z|ERROR|x"], {}),
            ("year_boundary", ["2025-12-31T23:59:59Z|ERROR|x", "2026-01-01T00:00:00Z|INFO|y"],
             {"2025-12-31T23:00:00Z": {"count": 1, "errors": 1},
              "2026-01-01T00:00:00Z": {"count": 1, "errors": 0}}),
        ]
    if identifier == "B6.3":
        return "normalize_records", [
            ("empty", [], []),
            ("invalid_entries", [None, 1, [], {}, {"name": 12, "date": "2024-01-01"},
                                 {"name": "x", "date": None}, {"name": " \n", "date": "2024-01-01"}], []),
            ("unicode_dedup", [{"name": " CAFÉ ", "date": "2024-02-29"},
                               {"name": "Cafe\u0301", "date": "2024-02-29", "extra": 1},
                               {"name": "Straße", "date": "2024-02-29"},
                               {"name": "STRASSE", "date": "2024-02-29"}],
             [{"name": "café", "date": "2024-02-29"}, {"name": "strasse", "date": "2024-02-29"}]),
            ("centuries", [{"name": "x", "date": day} for day in
                           ("1900-02-29", "2000-02-29", "2024-02-29", "2100-02-29", "2023-02-29")],
             [{"name": "x", "date": "2000-02-29"}, {"name": "x", "date": "2024-02-29"}]),
            ("strict_dates", [{"name": "x", "date": day} for day in
                              ("20240101", "2024-W01-1", "2024-1-01", "2024-01-01 ", "0000-01-01",
                               "2024-04-31", "2024-13-01", "２０２４-01-01")], []),
            ("sort", [{"name": "ЁЖ", "date": "2025-01-01"}, {"name": "B", "date": "2024-12-31"},
                      {"name": "A", "date": "2024-12-31"}, {"name": "е\u0308ж", "date": "2025-01-01"}],
             [{"name": "a", "date": "2024-12-31"}, {"name": "b", "date": "2024-12-31"},
              {"name": "ёж", "date": "2025-01-01"}]),
            ("bounds", [{"name": "Same", "date": "9999-12-31"}, {"name": "same", "date": "0001-01-01"}],
             [{"name": "same", "date": "0001-01-01"}, {"name": "same", "date": "9999-12-31"}]),
        ]
    raise ValueError("Unknown Python-function task")
