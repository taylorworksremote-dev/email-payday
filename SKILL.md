---
name: email-payday-scan
description: Scans Gmail and/or iCloud Mail (Inbox and Spam/Junk) for debt-collection and payment-demand language, restricts results to the last 2 years (or since the last run, in scheduled mode), and reports only the matching emails received outside 8am-9pm in the user's own local time as potential FDCPA time-of-day violations, each with an embedded screenshot, stored in a dated Google Sheet. Supports a lightweight incremental mode for recurring/scheduled runs. Trigger this whenever the user asks to scan, search, or audit their email for debt collector or collection agency messages, late-payment/payment-reminder emails, FDCPA or FCCPA violations, creditor harassment, or evidence of off-hours collection contact -- even if they don't say "FDCPA" by name.
---

# Email Payday Scan

## What this produces

A Google Sheet listing only the emails that (a) mention debt-collection/payment language and (b) arrived outside 8am-9pm in the user's own local time — each a potential FDCPA time-of-day violation, with an embedded screenshot of the actual email next to it. The Fair Debt Collection Practices Act (and some state mirror statutes, like Florida's FCCPA, which — unlike the federal law — also cover original creditors, not just third-party collectors) presumes contact before 8am or after 9pm the consumer's local time is inconvenient and therefore a violation absent evidence otherwise. The local timezone always comes from where the user actually lives (see Step 0) — never assume Eastern time just because that's common.

A keyword match that arrived during normal hours (8am-9pm local) is not a potential violation and does not appear anywhere in the report — the broad keyword list (see below) exists only to make sure nothing off-hours gets missed, not to hand the user a big list of ordinary in-hours mail to sort through themselves. If the scan finds keyword matches but none of them are off-hours, say so plainly and don't hand over a file at all.

This is a general-purpose screening tool for anyone's inbox — it has no connection to any specific person, company, or dispute, and shouldn't be treated as though it does. It's a screening pass, not legal advice: it surfaces candidates for a human (or an attorney) to review, it doesn't determine that a violation actually occurred. Whether the sender is a "debt collector" under the FDCPA (generally third parties collecting someone else's debt, not the original creditor) versus covered only under a state law like the FCCPA matters a lot for which statute applies, and this tool doesn't try to make that legal distinction — just say so plainly when you hand over the results.

## Why the keyword list is broad on purpose

The search terms are: `payment due`, `late payment`, `payment reminder`, `due`, `make a payment`, `past due`, `pay now`. Several of these (especially bare "due" and "pay now") will also match ordinary subscription receipts, utility bills, and newsletters — that's expected. The point of casting this wide net is recall at the matching stage, not precision — but `classify_and_report.py` immediately narrows back down for you: anything that matched a keyword but arrived during normal hours (8am-9pm local) is silently dropped and never shown to the user. Only genuine off-hours hits make it into the report. Don't try to tighten the keyword list on your own initiative; if the user wants it narrower, that's their call to make after seeing a first pass.

**Known failure mode — do not "clean up" or narrow the search query, ever.** In one real run, the Gmail search query actually sent to `search_threads` quietly dropped the bare `due` term and substituted narrower phrases like `due date` and `minimum payment` instead — plausible-looking, but strictly narrower. This caused a genuine off-hours violation to be missed entirely: a property manager's email whose only matching text was "amount **due** on June 1", buried in quoted reply history several messages down — a substring that bare `due` catches but no multi-word phrase does. The message never got past the search step, so it never reached `classify_and_report.py`'s own (correct) keyword check at all, and the miss wasn't caught until the user independently knew the email existed and asked for it by name. The lesson: the seven-term OR query in Step 2 item 1 must be sent to `search_threads` **verbatim** — copy it, don't retype it from memory or "tidy" it into different phrasing, and never drop bare `due` in favor of longer, cleaner-looking phrases. If you delegate the Gmail collection step to a subagent (via the Agent/Task tool), paste the exact query string from Step 2 item 1 into that subagent's instructions in full — do not summarize, paraphrase, or reconstruct it from your own memory of the keyword list, and do not let a subagent construct its own "equivalent" query. The same applies to the `in:anywhere` scope and the `INBOX`/`SPAM` label filter in Step 2 items 1 and 4 — a subagent that narrows to `in:inbox` or invents its own scope will silently drop legitimate Spam-folder hits the same way.

## Requirements

This skill was built for a Claude environment with a **Gmail** MCP connector (and, for the Google Sheets output, a **Google Drive** MCP connector) already available — e.g. Claude in Cowork with those connectors enabled. If you're running this in Claude Code or another environment, you'll need equivalent MCP servers configured for Gmail and Google Drive, or you'll need to adapt Steps 2 and 5 to call the Gmail API and Drive API directly (for example with a Python script using `google-api-python-client` and your own OAuth credentials). iCloud collection (Step 3) needs no MCP connector — it talks to iCloud over IMAP directly using the bundled `scripts/scan_icloud.py`.

The report script also needs **Playwright with Chromium** to render the email screenshots (`pip install playwright --break-system-packages` then `playwright install chromium`, if not already available in your environment) and **openpyxl** for the XLSX itself (`pip install openpyxl --break-system-packages`). Both failures degrade gracefully — a missing Playwright just skips screenshots (the rest of the report still builds), and a missing openpyxl leaves you with only the CSV — but installing both is what gets you the real deliverable.

## Step 0: Confirm scope, account address, and location

If the user hasn't already told you in this conversation, ask which account(s) to scan (Gmail, iCloud, or both) — a Gmail connector may or may not be available in the current session, and iCloud always requires the app-specific password step below. Default to "both" only if the user has already said so. If a Google Drive connector isn't available either, say so up front and fall back to delivering local files (see Step 5). A scheduled/recurring invocation (see Step 2b) may already specify the scope and a since-date itself — only ask interactively when running this on demand in a live conversation.

For each account in scope, also get its actual email address (e.g. `taylorworksremote@gmail.com`, `t.lefevere@icloud.com`) — this is what gets written into the report's "Account" column so the user can tell at a glance which inbox a hit came from, especially if they ever run this across more than one mailbox. For iCloud this is just whatever address the user gives you for Step 3. For Gmail, if the user hasn't stated it, don't guess or leave it generic ("gmail") — either ask, or read it off the `toRecipients`/`to` field of any message already pulled from the connected mailbox's own Inbox (that's reliably the account owner's address, since Gmail search only ever searches the connected account).

Also ask what state (or city/region, if their state spans more than one time zone) the user actually lives in, if you don't already know — this determines the local timezone used for the 8am-9pm cutoff in Step 4, and it's required, not optional. Don't default this to Eastern time. Map their answer to the correct IANA timezone yourself, for example: Florida, New York, most of the East Coast → `America/New_York`; Illinois, most of Texas → `America/Chicago`; Colorado, most of the Mountain states → `America/Denver`; Arizona (no DST) → `America/Phoenix`; California, Washington, most of the West Coast → `America/Los_Angeles`. If their state spans multiple zones (Texas, Indiana, Michigan, Florida's own panhandle, etc.), ask which city or region specifically rather than guessing.

## Step 1: Set up a scratch folder and use the two scripts

All the matching, date-cutoff, timezone, off-hours, and screenshot-rendering logic lives in one script (`scripts/classify_and_report.py`) so it's applied identically regardless of which mailbox the email came from — don't reimplement this logic by eye when looking at search results, and don't let a subagent or your own judgment substitute for running it. Both scripts are bundled in this skill's `scripts/` directory (they must stay siblings — `scan_icloud.py` imports from `classify_and_report.py`). Copy them into your working scratch folder before running, or run them in place from the skill's own directory.

See `scripts/classify_and_report.py` and `scripts/scan_icloud.py` in this skill folder for the full source.

## Step 2: Collect from Gmail (if in scope and a Gmail connector is available)

Gmail's own search already does full-text matching, so use it as a cheap first pass to find candidate threads, then pull full message detail for those candidates only — don't try to page through the entire mailbox by hand.

1. Build one query combining all the keywords with OR, restricted to the last 2 years by default (see Step 2b for scheduled/incremental runs, which use a different lower bound), searched everywhere (so Spam is included):
   `newer_than:2y in:anywhere ("payment due" OR "late payment" OR "payment reminder" OR due OR "make a payment" OR "past due" OR "pay now")`
   Use this exact string (with only the date-range portion swapped per Step 2b). Do not substitute, drop, reorder, or "improve" any of the seven OR terms — in particular, never drop the bare `due` term in favor of longer phrases like `due date` or `minimum payment`; they look like a superset but are not, and a real run was already burned by exactly this substitution (see the "Known failure mode" callout above). If this query is being handed to a subagent to execute, paste it into that subagent's prompt character-for-character.
2. Call `search_threads` with that query, `pageSize: 50`, paging with `pageToken` until exhausted (there must be no `nextPageToken` left — if you delegated this to a subagent, have it confirm exhaustion explicitly rather than taking a partial run's word for it). Collect the distinct thread IDs.
3. For each thread ID, call `get_thread` with `messageFormat: "FULL_CONTENT"` (not `PLAIN_TEXT` — you need the HTML body too, for the screenshot step; `PLAIN_TEXT` silently degrades every screenshot to the plain-text fallback rendering instead of the real email layout). This returns every message in the thread with its own `label_ids`, `sender`, `subject`, `date`, `plaintext_body`, and `html_body`.
4. For each message in each thread, keep it only if `label_ids` contains `INBOX` or `SPAM` (this is what actually restricts you to "inbox and junk" — `in:anywhere` in the search step was deliberately broad so nothing gets missed, and this is where you narrow back down). Build one record per kept message in this shape and collect them into a list:
```json
{
  "account": "the actual mailbox address from Step 0, e.g. taylorworksremote@gmail.com -- never the literal string \"gmail\"",
  "folder": "inbox_or_spam_derived_from_label_ids",
  "message_id": "...",
  "thread_id": "...",
  "sender_name": "...",
  "sender_email": "...",
  "subject": "...",
  "date_raw": "...as returned by the API, whatever format that turns out to be...",
  "body_text": "...plaintext_body, uncut...",
  "body_html": "...html_body, uncut (empty string if the message has none)...",
  "source_ref": "https://mail.google.com/mail/u/0/#all/<thread_id>"
}
```
5. Write the full list to `gmail_raw.json` in your scratch folder.

Note: a reply's plaintext body can include quoted text from earlier messages in the thread, which can occasionally cause a keyword to show up in a message that didn't originally contain it. The excerpt column in the final report exists so this is easy to eyeball and dismiss — mention this caveat when you hand over results.

## Step 2b: Incremental mode (for scheduled/recurring runs)

A recurring scheduled run shouldn't re-scan the entire 2-year window every time — that's slow and, since each run creates its own Sheet (see Step 5), it would also duplicate years of history into every new file. When you're told this is a scheduled/incremental run with a specific since-date (rather than a one-off manual request in a live conversation), replace `newer_than:2y` in the Gmail query with `after:<since-date, formatted YYYY/MM/DD>` instead, where the since-date is a few days before the last run to leave an overlap buffer (duplicate matches across runs are harmless — they just show up on both dated sheets). Everything else about the collection and classification logic (Steps 2, 4) works exactly the same on a narrower date range; `classify_and_report.py`'s own 2-year cutoff is just a safety net and won't drop anything from a recent incremental window, so it needs no changes. The user's timezone (Step 0) should already be known from the first run — carry it forward rather than asking again every time.

Skip iCloud collection entirely during scheduled runs — there's no one present to paste in an app-specific password, so iCloud stays a manual-only path run on demand in a live conversation.

## Step 3: Collect from iCloud (if in scope)

iCloud has no direct connector, so this goes through IMAP with an app-specific password (not the user's regular Apple ID password — those are blocked for third-party apps). If the user doesn't already have one, they generate it at appleid.apple.com under Sign-In and Security > App-Specific Passwords, then paste it into the chat when you ask. Use it only for this run: pass it straight to the script as a command-line argument and don't write it to disk, memory, or anywhere else it would outlive this run.

Run: `python scripts/scan_icloud.py --email <their icloud address> --password <the app-specific password they pasted> --out icloud_raw.json`

This script already captures both the plaintext and raw HTML body of each match (the latter for screenshot rendering in Step 4) — no extra flags needed. It also writes the `--email` address itself into each record's `account` field, so the report shows the real mailbox, same as Gmail.

## Step 4: Build the report file

`python scripts/classify_and_report.py --input gmail_raw.json icloud_raw.json --out-prefix payday_scan --tz <the IANA timezone from Step 0>` (pass whichever raw files actually exist — one or both; `--tz` is required, not optional — see Step 0). This applies the 2-year safety-net cutoff, converts every timestamp to the user's actual local timezone, keeps only messages that arrived outside 8am-9pm local (everything else is silently dropped — see "What this produces"), guesses a company name from the sender's domain, renders a screenshot of each remaining match (using the real HTML body when available, or a formatted view of the plain text otherwise) via headless Chromium, and writes `payday_scan.csv` and `payday_scan.xlsx` to the scratch folder. The XLSX has a single "Potential FDCPA Claims" sheet — since every row that survives the filter is already a potential violation, there's no separate "all matches" tab — with columns for the local date (`MM/DD/YYYY`, no day-of-week) and local time as two separate columns, the real account address, and the embedded screenshot. This is why it's built locally first rather than assembled directly in Sheets.

By default every row that makes it into the report gets a screenshot (`--screenshots all`); `--screenshots none` skips screenshots entirely (faster if the user just wants the data). There's no `flagged`-only mode anymore since every output row is already a flagged (off-hours) hit. If `openpyxl` isn't installed, install it first (`pip install openpyxl --break-system-packages`) so the XLSX actually gets built; if Playwright/Chromium isn't installed, screenshots are silently skipped and everything else still works — install it (see Requirements) if the user wants the visual evidence.

If this step reports zero rows, that means nothing matched the keywords outside 8am-9pm local — don't build or upload an empty Sheet; just tell the user that directly (see Step 6).

## Step 5: Store it in a Google Sheet

The deliverable is a Google Sheet, not a downloaded file. Read `payday_scan.xlsx` and base64-encode its bytes, then call `mcp__Google_Drive__create_file` with:
- `title`: `Email Payday Scan - <today's date>` for a one-off manual run, or `Email Payday Scan - Gmail - <today's date>` for a scheduled/incremental run (spelling out the scope makes it obvious at a glance that it's a partial-window scan, not the full history) — always give each run its own dated title rather than reusing one, since a plain file-create call can only create new files, not append rows to or overwrite an existing sheet's content. A single ever-growing master sheet across runs isn't possible with a create-only Drive tool; if the user wants a combined view later, that's a manual step of comparing the dated sheets, not something this skill automates.
- `base64Content`: the base64-encoded xlsx bytes
- `contentMimeType`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- leave `disableConversionToGoogleType` unset (false) so Drive converts the upload into a native Google Sheet — this is what preserves the embedded screenshots, rather than dropping into a flat CSV import
- `parentId`: only set this if the user named a specific Drive folder; look its id up with `search_files` first. Otherwise the sheet lands in the root of their Drive, which is fine as a default.

Embedded screenshots make the xlsx meaningfully larger than a text-only report. Because most runs will only have a handful of genuine off-hours violations (not every keyword match, per Step 4's filtering), the file is usually small even `--screenshots all`. But the base64-encoded xlsx has to be passed as a single inline value to `create_file`, and there's a practical ceiling on how much text can go into one tool call this way -- past roughly a couple MB of base64 (a few hundred KB of actual xlsx) it can become impractical to pass through in one call. If a run has an unusually large number of off-hours hits and the xlsx comes out large, fall back to `--screenshots none` for that run (Step 4) to keep the upload small, and tell the user screenshots were skipped for that reason -- don't silently drop rows to force it to fit.

The response carries the new file's id and link. Share that link with the user directly — don't just say a sheet was created without handing over how to open it. On a scheduled run with no one watching in real time, still record the link (see Step 6) so it's there when the user checks back.

If no Google Drive connector is available in the current session, don't silently substitute something else: tell the user Drive isn't reachable right now, and deliver the local `payday_scan.csv`/`payday_scan.xlsx` files instead so the work isn't lost.

## Step 6: Summarize

Give the count of potential FDCPA violations in the report (that's the only number in it now — there's no separate "total matches" figure to report since in-hours matches are never shown to the user at all), and note in plain language that: (a) this is a screening pass, not a legal conclusion — a row being in the report just means it arrived outside the 8am-9pm window (in the user's own local time) and mentioned collection-adjacent language, and (b) whether the FDCPA or a state analog applies depends on whether the sender is a debt collector versus the original creditor, which this tool doesn't determine. Keep this factual and general — don't assume or imply the scan relates to any particular company, person, or dispute unless the user has said so themselves. If the count is zero, say so plainly and don't create or link a Sheet at all (see Step 4).
