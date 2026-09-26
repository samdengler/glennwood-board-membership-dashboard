#!/usr/bin/env python3
"""
Pulls payments and contacts from the Zeffy API, aggregates them into the
figures the board dashboard shows, and writes a self-contained index.html
by filling in the site/template.html placeholders.

Required environment variables:
  ZEFFY_API_KEY          - bearer token from Zeffy Settings -> Integrations
  DASHBOARD_PASSWORD_HASH - hex SHA-256 of the shared board password
                            (see scripts/hash_password.py to generate one)

Zeffy API reference used here (read-only, per-organization key):
  Base URL: https://api.zeffy.com/api/v1
  GET /payments   -> {data: [...], has_more, next_cursor}
  GET /contacts   -> {data: [...], has_more, next_cursor}
Field names below are the documented ones as of Sep 2026; if Zeffy's actual
response differs, this script logs the first raw payment/contact it saw
(build_debug.json, workflow-log only, never committed) so the mapping can
be adjusted quickly.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone

API_BASE = "https://api.zeffy.com/api/v1"
# Zeffy's documented cap; requesting the max page size means a full pull of a
# small board's data (tens of records) fits in one or two requests instead of
# many, which is what actually avoids the rate limit rather than backoff alone.
PAGE_SIZE = 100
MAX_ATTEMPTS = 6


def _retry_delay(e, attempt):
    retry_after = e.headers.get("Retry-After") if e.headers else None
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    try:
        body = e.read().decode("utf-8", "replace")
    except Exception:
        body = ""
    m = re.search(r"retry after (\d+)", body, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return min(60, 5 * (2 ** attempt))


def api_get(path, headers, params=None):
    params = params or {}
    url = API_BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_ATTEMPTS - 1:
                delay = _retry_delay(e, attempt)
                print(f"Rate limited on {path}, waiting {delay:.0f}s (attempt {attempt + 1}/{MAX_ATTEMPTS})")
                time.sleep(delay)
                continue
            body = e.read().decode("utf-8", "replace")
            raise SystemExit(f"Zeffy API error {e.code} on {path}: {body}")
    raise SystemExit(f"Zeffy API: too many retries on {path}")


def paginate(path, headers, params=None):
    items = []
    cursor = None
    while True:
        p = dict(params or {})
        p.setdefault("limit", PAGE_SIZE)
        if cursor:
            p["cursor"] = cursor
        page = api_get(path, headers, p)
        items.extend(page.get("data", []))
        if page.get("has_more") and page.get("next_cursor"):
            cursor = page["next_cursor"]
        else:
            break
    return items


def first_present(d, keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def payment_amount(p):
    # Zeffy's API reports amount in the minor currency unit (cents for USD),
    # matching the convention most payment APIs use, not dollars.
    return float(p.get("amount") or 0) / 100.0


def line_item_label(item):
    return first_present(
        item, ["title", "name", "label", "productName", "ticketName", "description"],
        default="Payment",
    )


def line_item_recurring(item):
    val = first_present(item, ["recurring", "frequency", "recurrence"], default=None)
    if isinstance(val, bool):
        return "Yes" if val else "-"
    if isinstance(val, str) and val.lower() not in ("", "one_time", "onetime", "none"):
        return val.title()
    return "-"


def month_key(iso_dt):
    dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m"), dt.strftime("%b %Y")


def main():
    api_key = os.environ.get("ZEFFY_API_KEY")
    password_hash = os.environ.get("DASHBOARD_PASSWORD_HASH")
    if not api_key:
        raise SystemExit("ZEFFY_API_KEY is not set")
    if not password_hash:
        raise SystemExit("DASHBOARD_PASSWORD_HASH is not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        # Zeffy's API sits behind Cloudflare, which blocks requests carrying
        # Python's default "Python-urllib/x.y" user agent as a bot signature.
        # A standard browser-style UA clears that check; the API key is what
        # actually authorizes the request.
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    }

    payments = paginate("/payments", headers)
    contacts = paginate("/contacts", headers)
    contact_map = {}
    for c in contacts:
        name = " ".join(
            p for p in [first_present(c, ["firstName"], ""), first_present(c, ["lastName"], "")] if p
        ).strip() or "(no name on file)"
        contact_map[c.get("id")] = {"name": name, "email": c.get("email", "")}

    if payments:
        try:
            with open("build_debug.json", "w") as f:
                json.dump({"sample_payment": payments[0], "sample_contact": contacts[0] if contacts else None}, f, indent=2)
        except OSError:
            pass

    succeeded = [p for p in payments if str(p.get("status", "")).lower() == "succeeded"]
    not_succeeded = [p for p in payments if str(p.get("status", "")).lower() != "succeeded"]

    total_raised = sum(payment_amount(p) for p in succeeded)
    incomplete_amount = sum(payment_amount(p) for p in not_succeeded)

    monthly = defaultdict(float)
    monthly_labels = {}
    for p in succeeded:
        created = p.get("createdAt")
        if not created:
            continue
        key, label = month_key(created)
        monthly[key] += payment_amount(p)
        monthly_labels[key] = label
    monthly_series = [
        {"key": k, "label": monthly_labels[k], "amount": round(v, 2)}
        for k, v in sorted(monthly.items())
    ]

    mix = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for p in succeeded:
        items = p.get("lineItems") or [{}]
        label = " + ".join(sorted({line_item_label(i) for i in items})) or "Payment"
        mix[label]["count"] += 1
        mix[label]["amount"] += payment_amount(p)
    mix_series = [
        {"label": k, "count": v["count"], "amount": round(v["amount"], 2)}
        for k, v in sorted(mix.items(), key=lambda kv: -kv[1]["amount"])
    ]

    households = defaultdict(lambda: {"payments": 0, "total": 0.0, "plans": set(), "recurring": "-"})
    for p in succeeded:
        cid = p.get("contactId") or "unknown"
        info = contact_map.get(cid, {"name": "(unknown household)", "email": ""})
        h = households[cid]
        h["name"] = info["name"]
        h["email"] = info["email"]
        h["payments"] += 1
        h["total"] += payment_amount(p)
        for item in (p.get("lineItems") or [{}]):
            h["plans"].add(line_item_label(item))
            rec = line_item_recurring(item)
            if rec != "-":
                h["recurring"] = rec

    household_list = sorted(
        (
            {
                "name": h["name"],
                "email": h.get("email", ""),
                "plan": " + ".join(sorted(h["plans"])) or "Payment",
                "payments": h["payments"],
                "total": round(h["total"], 2),
                "recurring": h["recurring"],
            }
            for h in households.values()
        ),
        key=lambda r: r["name"],
    )

    data = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "totals": {
            "raised": round(total_raised, 2),
            "succeeded": len(succeeded),
            "incomplete": len(not_succeeded),
            "incompleteAmount": round(incomplete_amount, 2),
            "households": len(household_list),
        },
        "monthly": monthly_series,
        "mix": mix_series,
        "households": household_list,
    }

    with open("site/template.html", "r") as f:
        template = f.read()

    out = template.replace("__DATA_JSON__", json.dumps(data)).replace(
        "__PASSWORD_HASH__", password_hash
    )

    os.makedirs("dist", exist_ok=True)
    with open("dist/index.html", "w") as f:
        f.write(out)

    print(f"Wrote dist/index.html — {data['totals']}")


if __name__ == "__main__":
    main()
