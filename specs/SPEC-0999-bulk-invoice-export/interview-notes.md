# Bulk invoice export: interview notes

Eight 30-minute calls with finance admins, 2026-09-29 to 2026-10-10.
Interviewer: @audimar8. Notes are paraphrased unless quoted.

## Summary of themes

1. Month-end downloading is the biggest single complaint (7 of 8).
2. Admins want line items in the export, not just invoice totals (6 of 8).
3. Nobody asked for XLSX specifically. Two said "Excel", and both import CSVs into Excel today.
4. Three asked about scheduled exports, but only one would use it every month.

## Interviews

### 1. Controller, logistics company (~650 invoices/month)

- "Close takes me two days and half of the first day is your download button."
- Imports into NetSuite with a saved CSV mapping. Worried about columns changing.

### 2. AP/AR lead, SaaS company (~220 invoices/month)

- Downloads PDFs for auditors once a quarter. Wants one ZIP for a date range.
- Would like files named by invoice number so they sort.

### 3. Finance manager, agency (~90 invoices/month)

- Volume is low enough that one-by-one is "annoying but fine".
- Wants an unpaid-only export for chasing overdue clients.

### 4. Bookkeeper, multi-entity retailer (~1,100 invoices/month)

- Exports per currency and entity. Filters must carry into the export.
- "If it's more than a few minutes, just email it to me."

### 5. Head of finance, marketplace (~4,800 invoices/month)

- Asked whether there is a limit. Would hit 5,000 most months.
- Would use a webhook to drop files into their data warehouse.

### 6. Accountant, consultancy (~140 invoices/month)

- Uses Xero. Mentioned direct sync would be ideal but CSV is fine for now.
- Asked about scheduled exports on the 1st of every month.

### 7. Finance ops, healthcare SaaS (~300 invoices/month)

- Needs an audit trail of who exported what (compliance).
- German customers' names break in their current CSV export ("Ã¼" instead of "ü").

### 8. CFO, small manufacturer (~60 invoices/month)

- Low volume. Main interest is giving the external auditor a ZIP.
- Prefers a flat folder over per-customer folders.
