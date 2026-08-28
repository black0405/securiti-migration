"""Read-only extraction of Securiti DSR module data for migration.

Uses GET endpoints plus read-only POST endpoints (reporting queries, exports,
downloads). Never calls anything that creates, updates, or deletes data.

Usage: fill in the credentials below, then:
    python extract_securiti.py [phase ...]

Phases: reference configs forms lists tickets subtasks messages audit attachments
No args = all phases in that order. Output lands in ./export/ as JSON;
existing files are skipped, so reruns resume where they stopped.
"""
import json
import sys
import time
from pathlib import Path

import requests

# --- fill these in ---
BASE = "https://app.securiti.ai"   # your tenant URL, no trailing slash
TENANT = ""                        # X-TIDENT: Settings > General > Basic Information
CLIENT_ID = ""                     # API key (Settings > Access Management > API Keys)
CLIENT_SECRET = ""                 # its secret
# ---------------------

if not (TENANT and CLIENT_ID and CLIENT_SECRET):
    sys.exit("fill in TENANT, CLIENT_ID, CLIENT_SECRET at top of extract_securiti.py")

OUT = Path(__file__).parent / "export"
PAGE_SIZE = 100

session = requests.Session()
session.headers["X-TIDENT"] = TENANT


def authenticate():
    """OAuth token exchange if available, else API-key-pair header on every call."""
    apikey_header = f"apikey {CLIENT_ID}:{CLIENT_SECRET}"
    try:
        r = session.get(
            f"{BASE}/core/v1/oauth/get_access_token",
            headers={"Authorization": apikey_header},
            timeout=30,
        )
        if r.status_code == 200 and "access_token" in r.json():
            session.headers["Authorization"] = f"oauth {r.json()['access_token']}"
            print("auth: oauth token")
            return
    except (requests.RequestException, ValueError):
        pass
    session.headers["Authorization"] = apikey_header
    print("auth: api key pair")


def call(method, path, json_body=None, ok_statuses=(200,)):
    """One API call with retry on 429/5xx. Returns Response or None on 404."""
    url = f"{BASE}{path}"
    for attempt in range(5):
        r = session.request(method, url, json=json_body, timeout=120)
        if r.status_code == 401:
            authenticate()
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if r.status_code not in ok_statuses:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r
    raise RuntimeError(f"{method} {path} kept failing after retries")


def save(relpath, data):
    p = OUT / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {relpath}")


def done(relpath):
    return (OUT / relpath).exists()


def fetch_json(relpath, method, path, json_body=None):
    """Fetch one endpoint into one file unless already saved. Returns data or None."""
    if done(relpath):
        return json.loads((OUT / relpath).read_text(encoding="utf-8"))
    r = call(method, path, json_body)
    if r is None:
        print(f"404  {path} (skipped)")
        return None
    data = r.json()
    save(relpath, data)
    return data


def reporting_query(relpath, ref, source, extra=None):
    """Paginated read-only reporting query. Saves combined rows, returns them."""
    if done(relpath):
        return json.loads((OUT / relpath).read_text(encoding="utf-8"))
    rows, offset = [], 0
    while True:
        body = {
            "source": source,
            "response_config": {"format": 1},
            "skip_cache": True,
            "order_by": ["-id"],
            "pagination": {"type": "limit-offset", "offset": offset,
                           "limit": PAGE_SIZE, "omit_total": True},
        }
        if extra:
            body.update(extra)
        r = call("POST", f"/reporting/v1/sources/query?ref={ref}", body)
        data = r.json().get("data") or {}
        page = data.get("items") or data.get("rows") or data.get("data") or []
        if isinstance(page, dict):
            page = [page]
        rows.extend(page)
        print(f"{ref}: {len(rows)} rows")
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    save(relpath, rows)
    return rows


# ---------------------------------------------------------------- phases

def phase_reference():
    for rel, path in [
        ("reference/users.json", "/core/v1/admin/users"),
        ("reference/org_units.json", "/core/v1/admin/org_units"),
        ("reference/languages.json", "/privaci/v1/admin/dsr/languages"),
        ("reference/countries.json", "/core/v1/utils/geo/countries"),
        ("reference/license_metrics.json", "/privaci/v1/admin/dsr/license_metrics"),
        ("reference/workflows.json", "/privaci/v1/workflow"),
        ("reference/email_templates.json", "/privaci/v1/user/email_templates/dsr/list"),
        ("reference/process_records.json", "/privaci/v1/admin/data_asset/process_record"),
        ("reference/id_provider_types.json", "/core/v1/admin/dsr_id_provider/list"),
        ("reference/regulation_jurisdictions.json", "/privaci/v1/admin/dsr/regulations/jurisdictions"),
        ("reference/regulation_regions.json", "/privaci/v1/admin/dsr/regulations/regions"),
        ("reference/regulation_industries.json", "/privaci/v1/admin/dsr/regulations/industries"),
    ]:
        fetch_json(rel, "GET", path)


def phase_configs():
    for name in ["subtask_retain", "pause_deadline", "archive", "rescan",
                 "download", "encryption_standard", "hide_securiti_branding",
                 "data_subject_messaging", "restrict_module_owner_access",
                 "id_provider", "pwd_less_login"]:
        fetch_json(f"configs/{name}.json", "GET", f"/privaci/v1/admin/dsr/{name}/config")


def phase_forms():
    forms = fetch_json("forms/forms_list.json", "GET", "/privaci/v1/admin/dsr/forms") or {}
    fetch_json("forms/bind_vars.json", "GET", "/privaci/v1/admin/dsr/forms/bind_vars")
    fetch_json("forms/counts.json", "GET", "/privaci/v1/admin/dsr/forms/counts")
    fetch_json("forms/universal_forms.json", "GET", "/privaci/v1/admin/dsr/universal/forms")
    items = (forms.get("data") or {})
    if isinstance(items, dict):
        items = items.get("items") or items.get("forms") or []
    for f in items:
        fid = f.get("id")
        if fid is None:
            continue
        fetch_json(f"forms/{fid}/detail.json", "GET", f"/privaci/v1/admin/dsr/forms/{fid}")
        fetch_json(f"forms/{fid}/owners.json", "GET", f"/privaci/v1/admin/dsr/forms/{fid}/owners")
        fetch_json(f"forms/{fid}/rules.json", "GET", f"/privaci/v1/admin/dsr/forms/{fid}/rules/list")


def phase_lists():
    reporting_query("lists/tickets.json", "getListOfTickets", "dsr_ticket")
    reporting_query("lists/request_types.json", "getListOfRequestTypes", "dsr_request_type")
    reporting_query("lists/task_templates.json", "getListOfTaskTemplates", "dsr_task_template")
    reporting_query("lists/regulations.json", "getRegulations", "dsr_regulation")
    reporting_query("lists/supplemental_forms.json", "getListOfSupplementalForms",
                    "dsr_supplemental_form")


def ticket_ids():
    rows = json.loads((OUT / "lists/tickets.json").read_text(encoding="utf-8"))
    ids = []
    for row in rows:
        tid = row.get("id") if isinstance(row, dict) else None
        if tid is not None:
            ids.append(tid)
    return ids


def phase_tickets():
    for tid in ticket_ids():
        fetch_json(f"tickets/{tid}/detail.json", "GET", f"/privaci/v1/admin/dsr/tickets/{tid}")
        fetch_json(f"tickets/{tid}/owners.json", "GET", f"/privaci/v1/admin/dsr/ticket/{tid}/owners")
        fetch_json(f"tickets/{tid}/applicable_steps.json", "GET",
                   f"/privaci/v1/admin/dsr/tickets/{tid}/applicable_steps")


def phase_subtasks():
    for tid in ticket_ids():
        rel = f"tickets/{tid}/subtasks.json"
        rows = reporting_query(rel, "getListOfSubtasksForTicket", "dsr_ticket",
                               extra={"filter": {"op": "eq", "field": "ticket_id", "value": tid}})
        for row in rows or []:
            sid = row.get("subtask_id") or row.get("id")
            if sid is None:
                continue
            fetch_json(f"subtasks/{sid}/detail.json", "GET", f"/privaci/v1/admin/dsr/subtasks/{sid}")
            fetch_json(f"subtasks/{sid}/responses.json", "GET",
                       f"/privaci/v1/admin/dsr/subtasks/{sid}/response/")
            fetch_json(f"subtasks/{sid}/owners.json", "GET",
                       f"/privaci/v1/admin/dsr/subtasks/{sid}/owners")


def phase_messages():
    for tid in ticket_ids():
        fetch_json(f"tickets/{tid}/channels.json", "GET",
                   f"/privaci/v1/admin/dsr/tickets/all_messaging_channels/{tid}")
        fetch_json(f"tickets/{tid}/messages.json", "GET",
                   f"/privaci/v1/admin/dsr/ticket/{tid}/messages/")


def phase_audit():
    for tid in ticket_ids():
        rel = f"tickets/{tid}/audit_export_response.json"
        if done(rel):
            continue
        r = call("POST", f"/privaci/v1/admin/dsr/ticket/{tid}/export",
                 {"include_data_subject": True, "include_owner_info": True, "format": "csv"})
        if r is None:
            print(f"404  audit export ticket {tid}")
            continue
        save(rel, r.json() if "json" in r.headers.get("content-type", "") else {"raw": r.text[:2000]})


def phase_attachments():
    # ponytail: only initiates the async bulk zip per ticket; delivery is via
    # Securiti's generated download (email/notification), not this script.
    for tid in ticket_ids():
        rel = f"tickets/{tid}/attachments_initiated.json"
        if done(rel):
            continue
        r = call("POST", f"/privaci/v1/admin/dsr/tickets/{tid}/download/attachments")
        if r is None:
            print(f"404  attachments ticket {tid}")
            continue
        save(rel, r.json())
        # published report listing (read-only browse)
        fetch_json(f"tickets/{tid}/report_files.json", "POST",
                   f"/privaci/v1/admin/dsr/tickets/{tid}/browse", {"item_prefix": "/"})


PHASES = {
    "reference": phase_reference,
    "configs": phase_configs,
    "forms": phase_forms,
    "lists": phase_lists,
    "tickets": phase_tickets,
    "subtasks": phase_subtasks,
    "messages": phase_messages,
    "audit": phase_audit,
    "attachments": phase_attachments,
}


def main():
    wanted = sys.argv[1:] or list(PHASES)
    bad = [w for w in wanted if w not in PHASES]
    if bad:
        sys.exit(f"unknown phase(s) {bad}; valid: {list(PHASES)}")
    OUT.mkdir(exist_ok=True)
    authenticate()
    print("authenticated")
    for name in wanted:
        print(f"--- phase: {name}")
        PHASES[name]()
    print("done")


if __name__ == "__main__":
    main()
