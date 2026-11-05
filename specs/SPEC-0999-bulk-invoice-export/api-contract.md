# Bulk invoice export: API contract

Owned by the spec [SPEC-0999 Bulk invoice export](spec.md).
Changes here must stay in step with 3.2 and 3.4 in the spec.

## POST /v1/invoice-exports

Starts an export job for every invoice matching the filters.

Request:

```json
{
  "filters": {
    "issued_from": "2026-09-01",
    "issued_to": "2026-09-30",
    "status": ["open", "paid", "overdue"],
    "customer_ids": [],
    "currency": "USD"
  },
  "invoice_ids": [],
  "format": "csv_and_pdf"
}
```

| Field | Type | Notes |
|---|---|---|
| `filters` | object | Same filters as `GET /v1/invoices`. Ignored when `invoice_ids` is set. |
| `invoice_ids` | string[] | Optional. Export exactly these invoices (row selection). |
| `format` | enum | `csv`, `pdf_zip`, `csv_and_pdf` |

Response `202 Accepted`: an [export job](#export-job).

Errors:

| Status | Code | When |
|---|---|---|
| 403 | `missing_permission` | Caller lacks `billing.export` |
| 422 | `too_many_invoices` | More than 10,000 invoices match |
| 422 | `no_invoices` | Nothing matches |

## GET /v1/invoice-exports/{id}

Returns the [export job](#export-job).

## Export job

```json
{
  "id": "iexp_8Hq2",
  "status": "running",
  "format": "csv_and_pdf",
  "invoice_count": 1240,
  "progress": 0.42,
  "download_url": null,
  "expires_at": null,
  "created_by": "usr_31f",
  "created_at": "2026-10-27T14:02:11Z"
}
```

`status` is one of `queued`, `running`, `completed`, `failed`, `expired`.
`download_url` and `expires_at` are set only when `status` is `completed`.
Links expire 7 days after completion.

## Webhook: invoice_export.completed

Sent when a job reaches `completed` or `failed`. The `data` object is the
export job above.

## CSV columns

One row per invoice line item. Header fields repeat on every row of the same
invoice. Column order is part of the contract (version `1`).

| # | Column | Example | Notes |
|---|---|---|---|
| 1 | `invoice_number` | `INV-2026-00412` | |
| 2 | `invoice_date` | `2026-09-14` | ISO 8601 |
| 3 | `due_date` | `2026-10-14` | |
| 4 | `customer_id` | `cus_77a` | |
| 5 | `customer_name` | `Müller GmbH` | UTF-8 |
| 6 | `currency` | `EUR` | ISO 4217 |
| 7 | `line_number` | `1` | 1-based |
| 8 | `line_description` | `Pro plan, Sep 2026` | |
| 9 | `quantity` | `12` | |
| 10 | `unit_amount` | `49.00` | dot decimal, no thousands separator |
| 11 | `line_tax_rate` | `0.19` | |
| 12 | `line_tax_amount` | `111.72` | |
| 13 | `line_total` | `699.72` | |
| 14 | `invoice_total` | `1399.44` | |
| 15 | `invoice_status` | `paid` | `open`, `paid`, `overdue`, `void` |
| 16 | `amount_paid` | `1399.44` | |
| 17 | `paid_at` | `2026-09-30` | empty if unpaid |
