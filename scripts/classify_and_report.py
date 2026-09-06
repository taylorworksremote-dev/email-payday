import argparse, json, sys, re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

KEYWORDS = [
    "payment due",
    "late payment",
    "payment reminder",
    "due",
    "make a payment",
    "past due",
    "pay now",
]

_KEYWORD_PATTERNS = [(kw, re.compile(re.escape(kw), re.IGNORECASE)) for kw in KEYWORDS]


def find_matches(text):
    if not text:
        return []
    return [kw for kw, pat in _KEYWORD_PATTERNS if pat.search(text)]


def parse_date_any(date_raw):
    """Best-effort parse of a date string from either the Gmail API or an RFC 2822
    email header into an aware UTC datetime. Returns None if unparseable."""
    if date_raw is None:
        return None
    if isinstance(date_raw, (int, float)):
        ts = date_raw / 1000 if date_raw > 10**12 else date_raw
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(date_raw).strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        ts = float(s)
        ts = ts / 1000 if ts > 10**12 else ts
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        pass
    return None


def guess_company(sender_email, sender_name):
    domain = (sender_email or "").split("@")[-1].lower()
    generic = {"gmail.com", "yahoo.com", "icloud.com", "outlook.com", "hotmail.com",
               "aol.com", "me.com", "protonmail.com"}
    if domain and domain not in generic:
        parts = domain.split(".")
        core = parts[-2] if len(parts) >= 2 else parts[0]
        return core.replace("-", " ").title()
    return (sender_name or "").strip() or "Unknown"


def load_records(paths):
    records = []
    for p in paths:
        p = Path(p)
        files = list(p.glob("*.json")) if p.is_dir() else [p]
        for f in files:
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    records.extend(data)
            except Exception as e:
                print(f"Skipping {f}: {e}", file=sys.stderr)
    return records


def write_outputs(rows, out_prefix):
    import csv
    columns = ["date_local_str", "day_of_week", "account", "folder", "sender_name",
               "sender_email", "company_guess", "subject", "matched_keywords",
               "potential_fdcpa_flag", "excerpt", "source_ref"]
    csv_path = f"{out_prefix}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in columns})
    print(f"Wrote {csv_path}", file=sys.stderr)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        print("openpyxl not installed (pip install openpyxl --break-system-packages) "
              "-- CSV was still written.", file=sys.stderr)
        return

    headers = ["Date/Time (Local)", "Day", "Account", "Folder", "Sender Name", "Sender Email",
               "Company (guess)", "Subject", "Matched Keyword(s)", "Potential FDCPA Flag",
               "Excerpt", "Reference"]
    wb = Workbook()
    ws_all = wb.active
    ws_all.title = "All Matches"
    ws_flag = wb.create_sheet("Potential FDCPA Claims")
    fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    bold = Font(bold=True)
    for ws in (ws_all, ws_flag):
        ws.append(headers)
        for cell in ws[1]:
            cell.font = bold

    for r in rows:
        vals = [r["date_local_str"], r["day_of_week"], r["account"], r["folder"],
                r["sender_name"], r["sender_email"], r["company_guess"], r["subject"],
                r["matched_keywords"], r["potential_fdcpa_flag"], r["excerpt"], r["source_ref"]]
        ws_all.append(vals)
        if r["potential_fdcpa_flag"] == "Yes":
            for cell in ws_all[ws_all.max_row]:
                cell.fill = fill
            ws_flag.append(vals)

    for ws in (ws_all, ws_flag):
        for col_cells in ws.columns:
            length = max((len(str(c.value)) if c.value else 0) for c in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 60)

    xlsx_path = f"{out_prefix}.xlsx"
    wb.save(xlsx_path)
    print(f"Wrote {xlsx_path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", nargs="+", required=True,
                     help="One or more raw JSON files (or directories of them)")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--flag-start-hour", type=int, default=21)
    ap.add_argument("--flag-end-hour", type=int, default=8)
    args = ap.parse_args()

    tz = ZoneInfo(args.tz)
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(args.years * 365.25))

    raw_records = load_records(args.input)
    seen, rows = set(), []
    dropped_old = dropped_no_match = dropped_bad_date = 0

    for r in raw_records:
        key = (r.get("account"), r.get("message_id"))
        if key in seen:
            continue
        seen.add(key)

        subject = r.get("subject") or ""
        body = r.get("body_text") or ""
        matched = find_matches(subject + "\n" + body)
        if not matched:
            dropped_no_match += 1
            continue

        dt_utc = parse_date_any(r.get("date_raw"))
        if dt_utc is None:
            dropped_bad_date += 1
            continue
        if dt_utc < cutoff:
            dropped_old += 1
            continue

        dt_local = dt_utc.astimezone(tz)
        hour = dt_local.hour
        is_flagged = hour >= args.flag_start_hour or hour < args.flag_end_hour

        rows.append({
            "date_local": dt_local,
            "date_local_str": dt_local.strftime("%Y-%m-%d %I:%M %p %Z"),
            "day_of_week": dt_local.strftime("%A"),
            "account": r.get("account", ""),
            "folder": r.get("folder", ""),
            "sender_name": r.get("sender_name", ""),
            "sender_email": r.get("sender_email", ""),
            "company_guess": guess_company(r.get("sender_email"), r.get("sender_name")),
            "subject": subject,
            "matched_keywords": ", ".join(matched),
            "potential_fdcpa_flag": "Yes" if is_flagged else "No",
            "excerpt": (body[:300] + "...") if len(body) > 300 else body,
            "source_ref": r.get("source_ref", ""),
        })

    rows.sort(key=lambda x: x["date_local"], reverse=True)

    print(f"Loaded {len(raw_records)} raw records", file=sys.stderr)
    print(f"  Dropped (no keyword match on final check): {dropped_no_match}", file=sys.stderr)
    print(f"  Dropped (older than {args.years} years): {dropped_old}", file=sys.stderr)
    print(f"  Dropped (unparseable date): {dropped_bad_date}", file=sys.stderr)
    print(f"  Final matches: {len(rows)}", file=sys.stderr)
    print(f"  Potential FDCPA (off-hours) matches: "
          f"{sum(1 for r in rows if r['potential_fdcpa_flag'] == 'Yes')}", file=sys.stderr)

    write_outputs(rows, args.out_prefix)


if __name__ == "__main__":
    main()
