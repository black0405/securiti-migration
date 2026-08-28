"""Discover the reporting-query field syntax and valid dsr_ticket fields.

Read-only: every call is a limit-1 query. Fill creds in extract_securiti.py
first; this imports them. Run:  python probe_fields.py
Paste the full output back for analysis.
"""
import json

from extract_securiti import BASE, session, authenticate

REF = "getListOfTickets"
SOURCE = "dsr_ticket"

CANDIDATE_NAMES = [
    "id", "uuid", "title", "status", "request_type", "request_types",
    "first_name", "last_name", "email", "created_at", "modified_at",
    "due_date", "deadline", "regulation", "regulations", "form_id",
    "org_unit_id", "data_subject_type", "assignee", "owner", "owners",
    "priority", "source", "appeal_status", "days_left", "completed_at",
    "tags", "country", "state", "language", "ticket_id", "request_id",
]

SHAPES = {
    "plain string": lambda n: n,
    '{"field": name}': lambda n: {"field": n},
    '{"name": name}': lambda n: {"name": n},
    '{"field": name, "alias": name}': lambda n: {"field": n, "alias": n},
}


def query(fields):
    body = {
        "source": SOURCE,
        "response_config": {"format": 1},
        "skip_cache": True,
        "fields": fields,
        "pagination": {"type": "limit-offset", "offset": 0, "limit": 1,
                       "omit_total": True},
    }
    r = session.post(f"{BASE}/reporting/v1/sources/query?ref={REF}",
                     json=body, timeout=60)
    return r.status_code, r.text[:400]


def main():
    authenticate()
    working_shape = None
    for label, make in SHAPES.items():
        code, text = query([make("id")])
        print(f"shape {label}: HTTP {code}  {text[:150]}")
        if code == 200:
            working_shape = make
            print(f"\n>>> working shape: {label}\n")
            break
    if working_shape is None:
        print("\nno shape worked — paste this output back")
        return

    good, bad = [], []
    for name in CANDIDATE_NAMES:
        code, text = query([working_shape(name)])
        (good if code == 200 else bad).append(name)
        print(f"field {name}: {'OK' if code == 200 else 'no (' + str(code) + ')'}")

    print(f"\naccepted fields: {json.dumps(good)}")
    print(f"rejected fields: {json.dumps(bad)}")
    code, text = query([working_shape(n) for n in good])
    print(f"\ncombined query HTTP {code}, sample:\n{text}")


if __name__ == "__main__":
    main()
