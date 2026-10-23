# RFQ Reply Pipeline: From Inbox to DIBBS Export File

This document explains, end to end, how an OEM's email reply to an RFQ
becomes a row in the database and, eventually, a line in the 121-field
DIBBS export `.txt` file. It's meant as an onboarding reference for anyone
new to the `solicitations` app.

## High-level flow

```
 [OEM inbox]
     |
     |  1. Scan mailbox (manual trigger or scheduled job)
     v
 [Raw email + attachments]
     |
     |  2. Fetch & extract text (IMAP + PDF/Excel parsing)
     v
 [Email text + attachment text]
     |
     |  3. AI extraction (GPT-4 via Azure OpenAI / OpenAI)
     v
 [Structured fields: NSN, price, quantity, fees, ...]
     |
     |  4. Save as RfqReply row (dedup, computed totals)
     v
 [RfqReply record]
     |
     |  5. Link to the originating RFQ and Solicitation
     v
 [RfqReply linked to RFQ + Solicitation]
     |
     |  6. Build the 121 DIBBS field values (config + business rules)
     v
 [121-value row per RfqReply]
     |
     |  7. Validate mandatory fields
     v
 [Serialize to CSV line]
     |
     |  8. Write / append to the export .txt file
     v
 [DIBBS batch export file]
```

---

## 1. Scanning the mailbox

Each user configures their mailbox once, in `UserEmailConfig`
(`solicitations/models.py`): SMTP host/port/username/password (used both
for sending RFQs and, by reusing the same login, for reading replies),
plus optional IMAP overrides (`custom_imap_host`, `custom_imap_port`,
`custom_sent_folder`).

A scan can start in two ways:

- **Manual**: a user picks a date on the RFQ replies screen, which calls
  `fetch_rfq_replies_by_date` (`solicitations/views.py`). This queues a
  background job on Django-Q rather than blocking the request.
- **Scheduled**: two recurring Django-Q jobs, registered in
  `solicitations/tasks.py`:
  - `check_rfq_auto_fetch` runs every minute and fires a per-user scan at
    the time each user configured in `RfqAutoFetchSettings` (`fetch_time`,
    `day`, `days_back`).
  - `fetch_replied_rfqs_30min` runs every 30 minutes for every user who
    has auto-fetch enabled, independent of their individual schedule.

Both paths end up calling into `extractRfqReplies.py` at the project
root, which does the actual mailbox work.

## 2. Fetching and extracting email content

`RfqReplyExtractor` (in `extractRfqReplies.py`) does the following per
scan:

1. **Connect** — derives an IMAP host from the configured SMTP host (a
   lookup table for the common providers, with a generic fallback) and
   opens a read-only IMAP connection, so incoming mail is never marked as
   read.
2. **Search** — runs an IMAP date-range search (`SINCE`/`BEFORE`) over
   `INBOX` for the requested window.
3. **Fetch each message** — pulls the raw content without changing its
   read/unread state, decodes headers, and extracts the plain-text body.
4. **Extract attachment text** — for PDF attachments it uses `pdfplumber`;
   for Excel it uses `openpyxl`; plain text/CSV is read directly. This
   text is later handed to the AI step alongside the email body.
5. **Pre-filter** — before spending an AI call on a message, it does a
   cheap keyword check (subject/body mentioning "re:", "quote", "rfq",
   "price", "nsn", "solicitation", etc.) to skip obviously unrelated
   email.

## 3. AI extraction

Messages that pass the pre-filter go to `gpt4_email_extractor.py`, which
builds a chat client through `azure_openai_client` (Azure OpenAI or plain
OpenAI, depending on configuration) and sends the email body plus
attachment text to GPT-4o with a prompt asking for a single strict JSON
object containing the RFQ reply's data:

- Identifiers: `rfq_unique_id`, `solicitation_number`, `nsn`,
  `part_number`, `nomenclature`
- Quote details: `quantity`, `unit`, `unit_price`, `total_price`,
  `minimum_order_qty`
- Logistics: `total_shipping_weight`, `shipping_cost_to_company`,
  `oem_delivery_days`
- Terms: `payment_term` (normalized to the DLA field-025 discount codes)
- Fee breakdown: `tax`, `packaging_cost`, `handling_fee`,
  `insurance_cost`, `customs_duty`, `setup_cost`, `minimum_order_charge`,
  `rush_delivery_fee`, `environmental_fee`, `certification_cost`,
  `documentation_fee`
- Sender info: `oem_name`, `replied_email`
- Metadata: `confidence_score`, `extraction_notes`

The prompt instructs the model to strip currency symbols, use `null` for
anything not present, prefer the first line item when a reply quotes
several, and treat "no quote"/"declined" replies as null pricing rather
than guessing.

## 4. Saving the reply

`save_rfq_reply()` takes the AI's structured output plus the raw email
metadata (subject, body, received date, `Message-ID`) and creates an
`RfqReply` row. A few things happen automatically at save time:

- **Deduplication** — `RfqReply` has a `(user, email_message_id)` unique
  constraint, so re-scanning the same date range never creates duplicate
  rows.
- **Total price fallback** — if `total_price` wasn't extracted, the model
  computes it from `unit_price × quantity`.
- **Fee rollup** — `other_oem_charges` is automatically recalculated as
  the sum of the 11 individual fee fields every time the row is saved.

Some fields are intentionally *not* filled in by this pipeline — they're
completed later by a person during bid assessment (packaging/preservation
method, quote-validity days, internal notes).

## 5. Linking to the RFQ and Solicitation

Saving an `RfqReply` also triggers two matching steps:

- **`match_rfq_from_extracted_data()`** links the reply to the specific
  outbound **`RFQ`** record that was originally sent to that OEM. If the
  reply included the RFQ's unique ID, that's an exact match; otherwise it
  scores candidate RFQs by how well solicitation number, NSN, part
  number, quantity, nomenclature and OEM email/name line up, and only
  accepts a confident, unambiguous winner.
- **`find_matching_solicitation()`** links the reply to the underlying
  **`Solicitation`** record (the DIBBS posting itself), used later by the
  export pipeline. It first uses whatever `RFQ` was matched above; failing
  that, it tries progressively looser matches on solicitation number, NSN,
  and part number.

This linkage is what lets the export step pull authoritative solicitation
data (delivery terms, inspection point, quantity, etc.) alongside the
vendor's quoted terms.

## 6. Building the 121 DIBBS field values

When a reply is ready to export, `get_effective_rfq_reply_values()`
(`solicitations/export_utils.py`) assembles the 121-position DIBBS row in
three layers:

1. **Base values** (`build_rfq_reply_values()`) — for each of the 121
   DIBBS positions, pulls a value from the user's saved export
   configuration (`UserExportConfiguration`), which maps each position to
   either a fixed default, or a source field on the matched `Solicitation`
   / `RfqReply`.
2. **Per-RFQ overrides** — if the user manually edited specific fields on
   this particular RFQ's preview screen, those non-empty overrides are
   layered on top of the base values.
3. **DLA business rules** (`apply_dla_field_rules()`) — a single shared
   pass that enforces DIBBS's cross-field conditional logic (e.g. FOB
   City/State/Country must be blank when FOB Point is Destination, various
   fields only apply to certain solicitation types, etc.) and computes the
   Bid Type Code (`BI`/`BW`/`AB`/`DQ`) from every exception-sensitive
   condition in the row.

## 7. Validating mandatory fields

`validate_mandatory_fields()` checks the assembled row against DIBBS's
mandatory/conditional field requirements (required values, valid code
sets, length limits, and the same cross-field dependencies as step 6). A
reply that fails is excluded from the batch with a description of what's
missing, while replies that pass continue to the next step — one
incomplete reply doesn't block exporting the rest of the batch.

## 8. Serializing and writing the file

For each reply that passes validation, `serialize_export_values()` writes
its 121 values as one fully-quoted CSV line. All the lines for a batch are
joined with Windows-style line endings (`\r\n`) — the format DIBBS
expects — and written to a `.txt` file in the exports directory. The
generated filename and the list of any excluded replies (with reasons)
are returned to the UI so the user can see exactly what was and wasn't
included.

---

## Key files reference

| Stage | File | Key function(s) |
|---|---|---|
| Mailbox config | `solicitations/models.py` | `UserEmailConfig` |
| Scan scheduling | `solicitations/tasks.py` | `check_rfq_auto_fetch`, `fetch_replied_rfqs_30min` |
| Manual scan trigger | `solicitations/views.py` | `fetch_rfq_replies_by_date` |
| Mailbox connection & fetch | `extractRfqReplies.py` | `RfqReplyExtractor.connect_to_inbox`, `search_rfq_reply_emails`, `fetch_email_content` |
| Attachment text extraction | `extractRfqReplies.py` | `_extract_text_from_pdf`, `_extract_text_from_excel`, `_check_attachments` |
| AI extraction | `gpt4_email_extractor.py` | `GPT4EmailExtractor` |
| Saving the reply | `extractRfqReplies.py` | `save_rfq_reply` |
| Reply data model | `solicitations/models.py` | `RfqReply` |
| RFQ/Solicitation linking | `solicitations/models.py` | `RfqReply.match_rfq_from_extracted_data`, `RfqReply.find_matching_solicitation` |
| Building the 121-field row | `solicitations/export_utils.py` | `build_rfq_reply_values`, `get_effective_rfq_reply_values`, `apply_dla_field_rules`, `compute_bid_type_code` |
| Mandatory validation | `solicitations/export_utils.py` | `validate_mandatory_fields` |
| Serializing & writing the file | `solicitations/export_utils.py` | `serialize_export_values`, `generate_export_file_for_rfq_replies`, `export_rfq_replies_to_file` |
| Export entry points (UI) | `solicitations/views.py` | `export_replied_rfqs`, `export_selected_rfqs`, `export_single_rfq_reply`, `preview_single_rfq_export` |
