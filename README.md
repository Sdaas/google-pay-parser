# Google Pay Statement PDF Extractor

Extracts transaction data from Google Pay PDF statements and produces structured JSON output with built-in verification.

## How It Works

Google Pay PDF statements contain transaction data as positioned text — not as HTML tables or tagged content. The standard `extract_text()` in most PDF libraries concatenates words (e.g., "NAVEEN KUMAR S" becomes "NAVEENKUMARS") because the PDF doesn't encode explicit space characters; it positions each glyph at specific x/y coordinates.

This tool uses **character-level extraction** via [pdfplumber](https://github.com/jsvine/pdfplumber). It reads every character with its pixel position, groups them into lines by y-coordinate, and re-inserts spaces wherever the horizontal gap between consecutive characters exceeds a threshold (2 pixels). This accurately recovers payee names and other fields.

### Verification

The script automatically verifies extracted data by:

1. **Totals reconciliation** — Compares the sum of extracted "sent" transactions against the total printed in the PDF header. Same for "received." A paisa-level match across hundreds of transactions confirms nothing was missed or double-counted.
2. **UPI ID uniqueness** — Checks that all UPI Transaction IDs are unique (no duplicates).
3. **Completeness** — Confirms every transaction has a UPI Transaction ID.

## Prerequisites

- Python 3.10 or later

## Setup

```bash
# 1. (Optional) Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 2. Install dependencies
pip install -r requirements.txt
```

The only dependency is `pdfplumber`, which itself pulls in `pdfminer.six` and a few other lightweight packages.

## Usage

### Basic

```bash
python extract_gpay.py google-pay-statement.pdf
```

This produces `google-pay-statement-transactions.json` in the same directory as the PDF.

### Custom output path

```bash
python extract_gpay.py google-pay-statement.pdf --output my-transactions.json
```

### Quiet mode (skip verification output)

```bash
python extract_gpay.py google-pay-statement.pdf --quiet
```

## Output Format

```json
{
  "transactionPeriod": {
    "start": "01 August 2025",
    "end": "31 January 2026",
    "totalSent": 782334.17,
    "totalReceived": 101.0
  },
  "totalTransactions": 222,
  "transactions": [
    {
      "date": "01 Aug, 2025 06:20 PM",
      "payee": "NAVEEN KUMAR S",
      "amount": 630.0,
      "upiTransactionId": "521314926792"
    }
  ]
}
```

Each transaction record contains:

| Field              | Description                                    |
|--------------------|------------------------------------------------|
| `date`             | Date and time of the transaction               |
| `payee`            | Recipient name (or "Top-up to ..." / "Received from ...") |
| `amount`           | Transaction amount in INR                      |
| `upiTransactionId` | The unique UPI Transaction ID                  |

## Exit Codes

| Code | Meaning                                  |
|------|------------------------------------------|
| 0    | Success, all verification checks passed  |
| 1    | Input error (file not found, wrong type) |
| 2    | Extraction succeeded but verification failed |
