#!/usr/bin/env python3
"""
Google Pay Statement PDF Extractor

Extracts transaction data from Google Pay PDF statements and outputs
structured JSON. Uses character-level PDF extraction to preserve proper
spacing in payee names.

Usage:
    python extract_gpay.py <pdf_path> [--output <json_path>]

Example:
    python extract_gpay.py data/google-pay-statement.pdf
    python extract_gpay.py data/google-pay-statement.pdf --output transactions.json

Default output: output/<filename>.json (output directory will be created if needed)
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import pdfplumber


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    date: str
    payee: str
    amount: float
    upiTransactionId: str


@dataclass
class TransactionPeriod:
    start: str
    end: str
    totalSent: float
    totalReceived: float


@dataclass
class ExtractionResult:
    transactionPeriod: dict
    totalTransactions: int
    transactions: list


# ---------------------------------------------------------------------------
# PDF text extraction (character-level with gap-based spacing)
# ---------------------------------------------------------------------------

Y_TOLERANCE = 3    # pixels – characters within this vertical distance are on the same line
X_GAP_THRESHOLD = 2  # pixels – horizontal gap larger than this inserts a space


def extract_lines_from_page(page) -> list[str]:
    """
    Extract text lines from a single PDF page using character positions.

    pdfplumber's default extract_text() often concatenates words because the
    PDF doesn't encode explicit space characters — it just positions glyphs
    at specific coordinates. This function reads every character, groups them
    into lines by y-coordinate, and re-inserts spaces wherever the horizontal
    gap between consecutive characters exceeds X_GAP_THRESHOLD pixels.
    """
    chars = page.chars
    if not chars:
        return []

    # Group characters into lines by y-coordinate
    lines_dict: dict[int, list] = {}
    for char in chars:
        y_key = round(char["top"])
        matched_y = _find_nearby_y(lines_dict, y_key)
        if matched_y is not None:
            lines_dict[matched_y].append(char)
        else:
            lines_dict[y_key] = [char]

    # Build text for each line, inserting spaces based on x-position gaps
    result = []
    for y in sorted(lines_dict):
        line_chars = sorted(lines_dict[y], key=lambda c: c["x0"])
        text_parts = []
        prev_x1 = None
        for char in line_chars:
            if prev_x1 is not None and (char["x0"] - prev_x1) > X_GAP_THRESHOLD:
                text_parts.append(" ")
            text_parts.append(char["text"])
            prev_x1 = char.get("x1", char["x0"] + char.get("width", 5))
        line_text = "".join(text_parts).strip()
        if line_text:
            result.append(line_text)

    return result


def _find_nearby_y(lines_dict: dict, y_key: int) -> Optional[int]:
    """Return an existing y-key within Y_TOLERANCE, or None."""
    for existing_y in lines_dict:
        if abs(existing_y - y_key) <= Y_TOLERANCE:
            return existing_y
    return None


# ---------------------------------------------------------------------------
# Transaction parsing
# ---------------------------------------------------------------------------

# Matches: "01 Aug, 2025  Paid to NAVEEN KUMAR S  ₹630"
DATE_DETAIL_RE = re.compile(
    r"^(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),\s*\d{4})"
    r"\s+(Paid to .+?|Top-up to .+?|Received from .+?)"
    r"\s+(₹[\d,]+(?:\.\d+)?)\s*$"
)

# Matches: "06:20 PM  UPI Transaction ID: 521314926792"
TIME_UPI_RE = re.compile(
    r"^(\d{1,2}:\d{2}\s*(?:AM|PM))\s+UPI Transaction ID:\s*(\d+)\s*$"
)

# Matches the header: "01 August 2025 - 31 January 2026  ₹7,82,334.17  ₹101"
PERIOD_RE = re.compile(
    r"^(\d{1,2}\s+\w+\s+\d{4})\s*[-–]\s*(\d{1,2}\s+\w+\s+\d{4})"
    r"\s+(₹[\d,]+(?:\.\d+)?)"
    r"\s+(₹[\d,]+(?:\.\d+)?)\s*$"
)


def parse_amount(raw: str) -> float:
    """Convert '₹7,82,334.17' to 782334.17"""
    return float(raw.replace("₹", "").replace(",", ""))


def extract_payee(detail: str) -> tuple[str, str]:
    """
    Given a detail string like 'Paid to NAVEEN KUMAR S', return
    (payee_name, transaction_type).
    """
    if detail.startswith("Paid to "):
        return detail[8:].strip(), "sent"
    if detail.startswith("Top-up to "):
        return "Top-up to " + detail[10:].strip(), "top-up"
    if detail.startswith("Received from "):
        return "Received from " + detail[14:].strip(), "received"
    return detail, "unknown"


def parse_transactions(pdf_path: str) -> tuple[list[Transaction], Optional[TransactionPeriod]]:
    """
    Open a Google Pay PDF statement and extract all transactions plus
    the statement period metadata.
    """
    transactions: list[Transaction] = []
    period: Optional[TransactionPeriod] = None

    with pdfplumber.open(pdf_path) as pdf:
        all_lines: list[str] = []
        for page in pdf.pages:
            all_lines.extend(extract_lines_from_page(page))

    # First pass: look for the period header
    for line in all_lines:
        m = PERIOD_RE.match(line)
        if m:
            period = TransactionPeriod(
                start=m.group(1),
                end=m.group(2),
                totalSent=parse_amount(m.group(3)),
                totalReceived=parse_amount(m.group(4)),
            )
            break

    # Second pass: parse individual transactions
    i = 0
    while i < len(all_lines):
        m = DATE_DETAIL_RE.match(all_lines[i])
        if m:
            date_str = m.group(1).strip()
            payee, _ = extract_payee(m.group(2).strip())
            amount = parse_amount(m.group(3).strip())

            # Next line should contain time + UPI Transaction ID
            upi_id = ""
            time_str = ""
            if i + 1 < len(all_lines):
                m2 = TIME_UPI_RE.match(all_lines[i + 1])
                if m2:
                    time_str = m2.group(1).strip()
                    upi_id = m2.group(2).strip()
                    i += 1

            full_date = f"{date_str} {time_str}" if time_str else date_str

            transactions.append(Transaction(
                date=full_date,
                payee=payee,
                amount=amount,
                upiTransactionId=upi_id,
            ))
        i += 1

    return transactions, period


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class VerificationResult:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return len(self.failed) == 0

    def report(self) -> str:
        lines = ["\n" + "=" * 60, "VERIFICATION REPORT", "=" * 60]
        for msg in self.passed:
            lines.append(f"  ✓ PASS  {msg}")
        for msg in self.warnings:
            lines.append(f"  ⚠ WARN  {msg}")
        for msg in self.failed:
            lines.append(f"  ✗ FAIL  {msg}")
        lines.append("=" * 60)
        status = "ALL CHECKS PASSED" if self.ok else f"{len(self.failed)} CHECK(S) FAILED"
        lines.append(f"  {status}")
        lines.append("=" * 60)
        return "\n".join(lines)


def verify(transactions: list[Transaction], period: Optional[TransactionPeriod]) -> VerificationResult:
    """Run verification checks on the extracted data."""
    result = VerificationResult()

    # 1. Check all transactions have UPI IDs
    missing_upi = [t for t in transactions if not t.upiTransactionId]
    if missing_upi:
        result.failed.append(f"{len(missing_upi)} transaction(s) missing UPI Transaction ID")
    else:
        result.passed.append(f"All {len(transactions)} transactions have UPI Transaction IDs")

    # 2. Check UPI ID uniqueness
    upi_ids = [t.upiTransactionId for t in transactions if t.upiTransactionId]
    unique_count = len(set(upi_ids))
    if unique_count == len(upi_ids):
        result.passed.append(f"All {unique_count} UPI Transaction IDs are unique")
    else:
        dupes = len(upi_ids) - unique_count
        result.failed.append(f"{dupes} duplicate UPI Transaction ID(s) found")

    # 3. Reconcile totals against PDF header (if period info available)
    if period:
        sent = [t for t in transactions
                if not t.payee.startswith("Top-up to") and not t.payee.startswith("Received from")]
        received = [t for t in transactions if t.payee.startswith("Received from")]
        topups = [t for t in transactions if t.payee.startswith("Top-up to")]

        sent_total = sum(t.amount for t in sent)
        received_total = sum(t.amount for t in received)
        topup_total = sum(t.amount for t in topups)

        # Sent total (excluding top-ups) should match PDF header
        if abs(sent_total - period.totalSent) < 0.02:
            result.passed.append(
                f"Sent total matches PDF header: ₹{sent_total:,.2f} == ₹{period.totalSent:,.2f}"
            )
        else:
            result.failed.append(
                f"Sent total mismatch: extracted ₹{sent_total:,.2f} vs PDF header ₹{period.totalSent:,.2f} "
                f"(diff: ₹{abs(sent_total - period.totalSent):,.2f})"
            )

        # Received total should match PDF header
        if abs(received_total - period.totalReceived) < 0.02:
            result.passed.append(
                f"Received total matches PDF header: ₹{received_total:,.2f} == ₹{period.totalReceived:,.2f}"
            )
        else:
            result.failed.append(
                f"Received total mismatch: extracted ₹{received_total:,.2f} vs PDF header ₹{period.totalReceived:,.2f}"
            )

        # Summary breakdown
        result.passed.append(
            f"Breakdown: {len(sent)} sent (₹{sent_total:,.2f}) | "
            f"{len(topups)} top-ups (₹{topup_total:,.2f}) | "
            f"{len(received)} received (₹{received_total:,.2f})"
        )
    else:
        result.warnings.append("No transaction period header found in PDF — skipping totals reconciliation")

    return result


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def build_output(transactions: list[Transaction], period: Optional[TransactionPeriod]) -> dict:
    """Build the final JSON-serializable dict."""
    period_dict = asdict(period) if period else {}
    return {
        "transactionPeriod": period_dict,
        "totalTransactions": len(transactions),
        "transactions": [asdict(t) for t in transactions],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract transactions from a Google Pay PDF statement into JSON.",
    )
    parser.add_argument(
        "pdf_path",
        help="Path to the Google Pay PDF statement",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output JSON file path (default: output/<pdf_name>.json)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress verification output",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    if not pdf_path.suffix.lower() == ".pdf":
        print(f"Error: Expected a .pdf file, got: {pdf_path.suffix}", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Default: output/<pdf_name>.json
        output_dir = Path("output")
        output_path = output_dir / f"{pdf_path.stem}.json"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Extract
    print(f"Extracting transactions from: {pdf_path}")
    transactions, period = parse_transactions(str(pdf_path))
    print(f"Extracted {len(transactions)} transactions")

    # Verify
    if not args.quiet:
        vr = verify(transactions, period)
        print(vr.report())

    # Write JSON
    output = build_output(transactions, period)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nJSON written to: {output_path}")

    # Exit with error code if verification failed
    if not args.quiet and not vr.ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
