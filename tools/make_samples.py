"""Generate the fictional sample invoices in ./samples (all data is made up)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from minipdf import write_pdf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "samples")

INVOICES = [
    # (file, invoice_no, date, customer, subtotal, tax, total)
    ("invoice_A-1042.pdf", "A-1042", "2026-11-02", "Blue Harbor Cafe", "1,163.64", "116.36", "1,280.00"),
    ("invoice_A-1043.pdf", "A-1043", "03/11/2026", "Northwind Studio", "450.00", "45.00", "495.00"),
    ("invoice_A-1044.pdf", "A-1044", "Nov 5, 2026", "Kite & Co.", "2,000.00", "200.00", "2,200.00"),
    # Deliberate problems so the validation report has something to show:
    ("invoice_A-1045.pdf", "A-1045", "2026-11-06", None, "300.00", "30.00", "330.00"),  # missing customer
    ("invoice_A-1046.pdf", "A-1046", "2026-11-07", "Maple Tools", "800.00", "80.00", "890.00"),  # total mismatch
]


def lines_for(inv_no, date, customer, subtotal, tax, total):
    lines = [
        "Example Supplies Ltd.  (fictional sample)",
        "1 Sample Street, Demo City",
        "",
        "INVOICE",
        f"Invoice No: {inv_no}",
        f"Invoice Date: {date}",
    ]
    if customer:
        lines.append(f"Bill To: {customer}")
    lines += [
        "",
        "Description                      Amount",
        "Consulting services              " + subtotal,
        "",
        f"Subtotal: {subtotal}",
        f"Tax (10%): {tax}",
        f"Total Due: USD {total}",
        "",
        "Thank you for your business.",
    ]
    return lines


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for fname, *fields in INVOICES:
        write_pdf(os.path.join(OUT, fname), [lines_for(*fields)])
    print(f"wrote {len(INVOICES)} sample PDFs to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
