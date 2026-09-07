# fdcpa-inbox-scan

A Claude Code / Claude skill that scans an email inbox (Gmail and/or iCloud Mail — Inbox and Spam/Junk) for debt-collection and payment-demand language, restricts results to a configurable lookback window (2 years by default), and flags any matching email that arrived outside 8am-9pm **in your own local time zone** as a **potential FDCPA time-of-day violation**. Each match gets an embedded screenshot of the actual email, so the report can be handed straight to an attorney.

This is a general-purpose personal screening tool. It has no connection to any specific person, company, or dispute — it just looks for a fixed set of keywords in your own mail and tells you when they showed up outside normal hours. It produces a screening pass, not a legal conclusion.

## What it does

1. Searches the configured mailbox(es) for these terms (case-insensitive): `payment due`, `late payment`, `payment reminder`, `due`, `make a payment`, `past due`, `pay now`.
2. Restricts matches to the last 2 years (or, in incremental/scheduled mode, since the last run).
3. Converts every timestamp to **your actual local timezone** (you specify it — this is never assumed to be Eastern) and flags anything that arrived between 9pm and 8am as a "Potential FDCPA Claim."
4. Renders a screenshot of each matched email (using its real HTML content when available) via headless Chromium, so the report carries visual evidence, not just extracted text.
5. Builds a two-tab report — "All Matches" and "Potential FDCPA Claims" — as an `.xlsx` file with the flagged rows highlighted and a screenshot embedded next to each row.
6. In a Claude environment with a Google Drive connector, uploads that report as a native Google Sheet and hands back the link. Without Drive, it just leaves the local CSV/XLSX files in place.

## Why the keyword list is broad

Terms like bare `due` and `pay now` will also match ordinary subscription receipts and bills — that's intentional. This tool favors recall over precision: better to hand over a slightly noisy list to sort through than to silently miss a real collection email because the filter was too clever.

## Requirements

- **To run as a Claude skill** (Claude Code, or Claude in Cowork/claude.ai with skills enabled): a **Gmail** MCP connector for mail search, and optionally a **Google Drive** MCP connector for the Sheets output. Both are first-party Google connectors available in Claude's connector settings. iCloud collection needs no connector — it authenticates directly over IMAP.
- **Python 3.9+** for the bundled scripts, with [`openpyxl`](https://pypi.org/project/openpyxl/) installed (`pip install openpyxl --break-system-packages` or `pip install openpyxl` in a virtualenv) to produce the `.xlsx` report. Without it, the script still writes a `.csv`.
- **[Playwright](https://playwright.dev/python/) with Chromium** to render the email screenshots: `pip install playwright --break-system-packages` then `playwright install chromium`. Without it, the report still builds — it just skips the screenshot column.
- **For iCloud Mail**: an app-specific password from [appleid.apple.com](https://appleid.apple.com) (Sign-In and Security > App-Specific Passwords) — your regular Apple ID password will not work over IMAP.

## Installation

Drop this folder into wherever your Claude environment loads skills from (for Claude Code, typically a `skills/` directory it's configured to read from) so `SKILL.md` and the `scripts/` folder stay together as siblings — `scripts/scan_icloud.py` imports from `scripts/classify_and_report.py` at runtime.

Once installed, just ask Claude to scan your inbox for debt-collection or payment-reminder emails, or for potential FDCPA violations — the skill's description is written to trigger on that kind of request automatically.

## Files

- `SKILL.md` — the skill definition Claude reads: when to trigger, and the full step-by-step procedure (scope confirmation, Gmail collection via the connector, iCloud collection via IMAP, report generation, Google Sheets upload, summary).
- `scripts/classify_and_report.py` — the single source of truth for keyword matching, date-cutoff, timezone conversion, off-hours flagging, and screenshot rendering. Takes one or more raw JSON files (Gmail and/or iCloud records) and writes a combined CSV + XLSX report.
- `scripts/scan_icloud.py` — connects to iCloud Mail over IMAP (read-only — it never marks messages as read), searches the Inbox and any Junk/Spam mailbox, and writes matching messages (plaintext and HTML body) to a raw JSON file for `classify_and_report.py` to consume.

## Running the scripts directly (outside a Claude session)

```bash
# iCloud collection
python scripts/scan_icloud.py --email you@icloud.com --password <app-specific-password> --out icloud_raw.json

# Build the report from one or more raw JSON files -- --tz is required, use your own IANA timezone
python scripts/classify_and_report.py --input gmail_raw.json icloud_raw.json --out-prefix fdcpa_scan --tz America/New_York
```

Other useful flags on `classify_and_report.py`:
- `--tz` (required) — your IANA timezone, e.g. `America/New_York`, `America/Chicago`, `America/Denver`, `America/Los_Angeles`, `America/Phoenix`. This is never assumed — pick the zone for where you actually live.
- `--screenshots {all,flagged,none}` (default `all`) — which rows get an embedded screenshot. `flagged` only screenshots the potential-FDCPA rows (faster on a large result set); `none` skips screenshots entirely.
- `--years` (default `2.0`) — lookback window.

This produces `fdcpa_scan.csv` and `fdcpa_scan.xlsx`. Gmail collection itself (`gmail_raw.json`) is driven by Claude through the Gmail connector per the steps in `SKILL.md` — there's no standalone Gmail script here because it relies on Claude's own connector tools rather than direct API calls.

## Scheduling

This skill supports an incremental mode (`SKILL.md` Step 2b) intended for recurring/scheduled runs: instead of re-scanning the full lookback window every time, it scans only mail since the last run and writes each run's results to its own dated Google Sheet (Drive's upload tool can create files but not append to existing ones). How you schedule recurring runs depends on your Claude environment — for example, Claude's own scheduled tasks feature, if available, can fire this on a cadence and pass along the since-date.

## Disclaimer

This tool surfaces candidates for a human (or an attorney) to review — it does not determine that a violation actually occurred, and it does not determine whether the sender is a "debt collector" under the FDCPA versus an original creditor (which matters for which statute, if any, applies). Nothing here is legal advice.

## License

MIT — see `LICENSE`.
