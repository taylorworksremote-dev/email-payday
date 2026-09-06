import argparse, imaplib, email, re, json, sys
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from classify_and_report import find_matches  # single source of truth for keyword matching


def decode_mime_words(s):
    if not s:
        return ""
    out = ""
    for text, enc in decode_header(s):
        out += text.decode(enc or "utf-8", errors="replace") if isinstance(text, bytes) else text
    return out


def get_plain_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition") or ""):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    return re.sub("<[^<]+?>", " ", html)
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
        if payload is None:
            return msg.get_payload() or ""
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


def find_junk_mailboxes(imap):
    typ, mailboxes = imap.list()
    found = []
    if typ == "OK":
        for raw in mailboxes:
            line = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
            m = re.search(r'"(?:/|\.)"\s*"?([^"\n]+)"?$', line)
            name = m.group(1) if m else line.split()[-1]
            if re.search(r"junk|spam", name, re.I):
                found.append(name)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True, help="App-specific password from appleid.apple.com")
    ap.add_argument("--since-days", type=int, default=760, help="Lookback window (default ~2 years + buffer)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    since_date = (datetime.now(timezone.utc) - timedelta(days=args.since_days)).strftime("%d-%b-%Y")

    imap = imaplib.IMAP4_SSL("imap.mail.me.com", 993)
    imap.login(args.email, args.password)

    boxes = ["INBOX"] + find_junk_mailboxes(imap)
    print(f"Scanning mailboxes: {boxes}", file=sys.stderr)

    records = []
    for box in boxes:
        typ, _ = imap.select(f'"{box}"', readonly=True)  # readonly: never mark mail as read
        if typ != "OK":
            print(f"Could not open {box}, skipping", file=sys.stderr)
            continue
        typ, data = imap.search(None, f"(SINCE {since_date})")
        if typ != "OK" or not data or not data[0]:
            continue
        uids = data[0].split()
        print(f"{box}: checking {len(uids)} messages since {since_date}", file=sys.stderr)
        for uid in uids:
            typ, msg_data = imap.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_mime_words(msg.get("Subject", ""))
            body = get_plain_text(msg)[:20000]
            matched = find_matches(subject + "\n" + body)
            if not matched:
                continue
            sender_name, sender_email = parseaddr(decode_mime_words(msg.get("From", "")))
            records.append({
                "account": "icloud",
                "folder": "inbox" if box.upper() == "INBOX" else "spam_or_junk",
                "message_id": msg.get("Message-ID") or f"{box}-{uid.decode()}",
                "thread_id": None,
                "sender_name": sender_name or sender_email,
                "sender_email": sender_email,
                "subject": subject,
                "date_raw": msg.get("Date", ""),
                "body_text": body,
                "source_ref": f"iCloud/{box}/UID{uid.decode()}",
            })
    imap.logout()
    Path(args.out).write_text(json.dumps(records, indent=2))
    print(f"Wrote {len(records)} candidate matches to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
