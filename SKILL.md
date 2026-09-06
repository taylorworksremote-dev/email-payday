---
name: fdcpa-inbox-scan
description: Scans Gmail and/or iCloud Mail (Inbox and Spam/Junk) for debt-collection and payment-demand language, restricts results to the last 2 years (or since the last run, in scheduled mode), flags every matching email received outside 8am-9pm Eastern as a potential FDCPA time-of-day violation, and stores the results in a dated Google Sheet. Supports a lightweight incremental mode for recurring/scheduled runs. Trigger this whenever the user asks to scan, search, or audit their email for debt collector or collection agency messages, late-payment/payment-reminder emails, FDCPA or FCCPA violations, creditor harassment, or evidence of off-hours collection contact -- even if they don't say "FDCPA" by name.
---

# FDCPA Inbox Scan

## What this produces

A Google Sheet listing every email that mentions debt-collection/payment language, pulled from Gmail and/or iCloud Mail (Inbox + Spam/Junk). Every match is listed on an "All Matches" tab; the subset that arrived outside 8am-9pm Eastern time gets highlighted and copied to a second "Potential FDCPA Claims" tab, because the Fair Debt Collection Practices Act (and some state mirror statutes, like Florida's FCCPA, which -- unlike the federal law -- also cover original creditors, not just third-party collectors) presumes contact before 8am or after 9pm the consumer's local time is inconvenient and therefore a violation absent evidence otherwise.

This is a general-purpose screening tool for anyone's inbox -- it has no connection to any specific person, company, or dispute, and shouldn't be treated as though it does. It's a screening pass, not legal advice: it surfaces candidates for a human (or an attorney) to review, it doesn't determine that a violation actually occurred. Whether the sender is a "debt collector" under the FDCPA (generally third parties collecting someone else's debt, not the original creditor) versus covered only under a state law like the FCCPA matters a lot for which statute applies, and this tool doesn't try to make that legal distinction -- just say so plainly when you hand over the results.

## Why the keyword list is broad on purpose

The search terms are: `payment due`, `late payment`, `payment reminder`, `due`, `make a payment`, `past due`, `pay now`. Several of these (especially bare "due" and "pay now") will also match ordinary subscription receipts, utility bills, and newsletters -- that's expected and intentional. The point of this tool is recall, not precision: better to hand the user a slightly noisy list they can sort/filter in the sheet than to silently drop a real collection email because a keyword filter was too clever. Don't try to tighten the keyword list on your own initiative; if the user wants it narrower, that's their call to make after seeing a first pass.

## Requirements

This skill was built for a Claude environment with a **Gmail** MCP connector (and, for the Google Sheets output, a **Google Drive** MCP connector) already available -- e.g. Claude in Cowork with those connectors enabled. If you're running this in Claude Code or another environment, you'll need equivalent MCP servers configured for Gmail and Google Drive, or you'll need to adapt Steps 2 and 5 to call the Gmail API and Drive API directly (for example with a Python script using `google-api-python-client` and your own OAuth credentials). iCloud collection (Step 3) needs no MCP connector -- it talks to iCloud over IMAP directly using the bundled `scripts/scan_icloud.py`.

## Step 0: Confirm scope

If the user hasn't already told you in this conversation, ask which account(s) to scan (Gmail, iCloud, or both) -- a Gmail connector may or may not be available in the current session, and iCloud always requires the app-specific password step below. Default to "both" only if the user has already said so. If a Google Drive connector isn't available either, say so up front and fall back to delivering local files (see Step 5). A scheduled/recurring invocation (see Step 2b) may already specify the scope and a since-date itself -- only ask interactively when running this on demand in a live conversation.

## Step 1: Set up a scratch folder and use the two scripts

All the matching, date-cutoff, timezone, and off-hours logic lives in one script (`scripts/classify_and_report.py`) so it's applied identically regardless of which mailbox the email came from -- don't reimplement this logic by eye when looking at search results, and don't let a subagent or your own judgment substitute for running it. Both scripts are bundled in this skill's `scripts/` directory (they must stay siblings -- `scan_icloud.py` imports from `classify_and_report.py`). Copy them into your working scratch folder before running, or run them in place from the skill's own directory.

See `scripts/classify_and_report.py` and `scripts/scan_icloud.py` in this skill folder for the full source.

## Step 2: Collect from Gmail (if in scope and a Gmail connector is available)

Gmail's own search already does full-text matching, so use it as a cheap first pass to find candidate threads, then pull full message detail for those candidates only -- don't try to page through the entire mailbox by hand.

1. Build one query combining all the keywords with OR, restricted to the last 2 years by default (see Step 2b for scheduled/incremental runs, which use a different lower bound), searched everywhere (so Spam is included):
2.    `newer_than:2y in:anywhere ("payment due" OR "late payment" OR "payment reminder" OR due OR "make a payment" OR "past due" OR "pay now")`
3.2. Call `search_threads` with that query, `pageSize: 50`, paging with `pageToken` until exhausted. Collect the distinct thread IDs.
  3. For each thread ID, call `get_thread` with `messageFormat: "PLAIN_TEXT"`. This returns every message in the thread with its own `label_ids`, `sender`, `subject`, `date`, and `plaintext_body`.
  4. 4. For each message in each thread, keep it only if `label_ids` contains `INBOX` or `SPAM` (this is what actually restricts you to "inbox and junk" -- `in:anywhere` in the search step was deliberately broad so nothing gets missed, and this is where you narrow back down). Build one record per kept message in this shape and collect them into a list:
     5. ```json
        {
          "account": "gmail",
          "folder": "inbox_or_spam_derived_from_label_ids",
          "message_id": "...",
          "thread_id": "...",
          "sender_name": "...",
          "sender_email": "...",
          "subject": "...",
          "date_raw": "...as returned by the API, whatever format that turns out to be...",
          "body_text": "...plaintext_body, uncut...",
          "source_ref": "https://mail.google.com/mail/u/0/#all/<thread_id>"
        }
        ```
        5. Write the full list to `gmail_raw.json` in your scratch folder.
       
        6. Note: a reply's plaintext body can include quoted text from earlier messages in the thread, which can occasionally cause a keyword to show up in a message that didn't originally contain it. The excerpt column in the final report exists so this is easy to eyeball and dismiss -- mention this caveat when you hand over results.
       
        7. ## Step 2b: Incremental mode (for scheduled/recurring runs)
       
        8. A recurring scheduled run shouldn't re-scan the entire 2-year window every time -- that's slow and, since each run creates its own Sheet (see Step 5), it would also duplicate years of history into every new file. When you're told this is a scheduled/incremental run with a specific since-date (rather than a one-off manual request in a live conversation), replace `newer_than:2y` in the Gmail query with `after:<since-date, formatted YYYY/MM/DD>` instead, where the since-date is a few days before the last run to leave an overlap buffer (duplicate matches across runs are harmless -- they just show up on both dated sheets). Everything else about the collection and classification logic (Steps 2, 4) works exactly the same on a narrower date range; `classify_and_report.py`'s own 2-year cutoff is just a safety net and won't drop anything from a recent incremental window, so it needs no changes.
       
        9. Skip iCloud collection entirely during scheduled runs -- there's no one present to paste in an app-specific password, so iCloud stays a manual-only path run on demand in a live conversation.
       
        10. ## Step 3: Collect from iCloud (if in scope)
       
        11. iCloud has no direct connector, so this goes through IMAP with an app-specific password (not the user's regular Apple ID password -- those are blocked for third-party apps). If the user doesn't already have one, they generate it at appleid.apple.com under Sign-In and Security > App-Specific Passwords, then paste it into the chat when you ask. Use it only for this run: pass it straight to the script as a command-line argument and don't write it to disk, memory, or anywhere else it would outlive this run.
       
        12. Run: `python scripts/scan_icloud.py --email <their icloud address> --password <the app-specific password they pasted> --out icloud_raw.json`
       
        13. ## Step 4: Build the report file
       
        14. `python scripts/classify_and_report.py --input gmail_raw.json icloud_raw.json --out-prefix fdcpa_scan` (pass whichever raw files actually exist -- one or both). This applies the 2-year safety-net cutoff, converts every timestamp to America/New_York, flags anything outside 8am-9pm, guesses a company name from the sender's domain, and writes `fdcpa_scan.csv` and `fdcpa_scan.xlsx` to the scratch folder. The XLSX is what carries the two-tab structure ("All Matches" + "Potential FDCPA Claims") and the highlight fill, which is why it's built locally first rather than assembled directly in Sheets.
       
        15. If `openpyxl` isn't installed, install it first (`pip install openpyxl --break-system-packages`) so the XLSX actually gets built.
       
        16. ## Step 5: Store it in a Google Sheet
       
        17. The deliverable is a Google Sheet, not a downloaded file. Read `fdcpa_scan.xlsx` and base64-encode its bytes, then call `mcp__Google_Drive__create_file` with:
        18. - `title`: `FDCPA Inbox Scan - <today's date>` for a one-off manual run, or `FDCPA Inbox Scan - Gmail - <today's date>` for a scheduled/incremental run (spelling out the scope makes it obvious at a glance that it's a partial-window scan, not the full history) -- always give each run its own dated title rather than reusing one, since a plain file-create call can only create new files, not append rows to or overwrite an existing sheet's content. A single ever-growing master sheet across runs isn't possible with a create-only Drive tool; if the user wants a combined view later, that's a manual step of comparing the dated sheets, not something this skill automates.
            - - `base64Content`: the base64-encoded xlsx bytes
              - - `contentMimeType`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
                - - leave `disableConversionToGoogleType` unset (false) so Drive converts the upload into a native Google Sheet -- this is what preserves both tabs and the highlight fill, rather than dropping into a flat CSV import
                  - - `parentId`: only set this if the user named a specific Drive folder; look its id up with `search_files` first. Otherwise the sheet lands in the root of their Drive, which is fine as a default.
                   
                    - The response carries the new file's id and link. Share that link with the user directly -- don't just say a sheet was created without handing over how to open it. On a scheduled run with no one watching in real time, still record the link (see Step 6) so it's there when the user checks back.
                   
                    - If no Google Drive connector is available in the current session, don't silently substitute something else: tell the user Drive isn't reachable right now, and deliver the local `fdcpa_scan.csv`/`fdcpa_scan.xlsx` files instead so the work isn't lost.
                   
                    - ## Step 6: Summarize
                   
                    - Give the total match count and the off-hours (potential FDCPA) count, and note in plain language that: (a) this is a screening pass, not a legal conclusion -- an email being flagged just means it arrived outside the 8am-9pm window and mentioned collection-adjacent language, and (b) whether the FDCPA or a state analog applies depends on whether the sender is a debt collector versus the original creditor, which this tool doesn't determine. Keep this factual and general -- don't assume or imply the scan relates to any particular company, person, or dispute unless the user has said so themselves.
                    - 
