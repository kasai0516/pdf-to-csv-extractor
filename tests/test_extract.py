import csv
import tempfile
import unittest
from pathlib import Path

from pdf2csv.extract import extract_record, load_config, normalize, run

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "fields.example.yaml")
SAMPLES = ROOT / "samples"


class NormalizeTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(normalize("2026-11-02", "date"), "2026-11-02")
        self.assertEqual(normalize("03/11/2026", "date"), "2026-11-03")  # day/month/year
        self.assertEqual(normalize("Nov 5, 2026", "date"), "2026-11-05")
        with self.assertRaises(ValueError):
            normalize("sometime soon", "date")

    def test_money(self):
        self.assertEqual(normalize("USD 1,280.00", "money"), "1280.00")
        self.assertEqual(normalize("$450", "money"), "450.00")
        with self.assertRaises(ValueError):
            normalize("n/a", "money")

    def test_ambiguous_numbers_are_rejected_not_changed(self):
        for bad in ["1.280,00", "11.009", "12,34.5"]:
            with self.assertRaises(ValueError, msg=bad):
                normalize(bad, "money")
        with self.assertRaises(ValueError):
            normalize("1.5", "int")
        self.assertEqual(normalize("1,200", "int"), "1200")


class ExtractTests(unittest.TestCase):
    def test_clean_invoice_has_no_issues(self):
        text = "Invoice No: A-1\nInvoice Date: 2026-11-02\nBill To: X\nSubtotal: 10.00\nTax (10%): 1.00\nTotal Due: USD 11.00"
        record, issues = extract_record(text, CONFIG, "a.pdf")
        self.assertEqual(issues, [])
        self.assertEqual(record["total"], "11.00")

    def test_missing_field_is_reported_not_guessed(self):
        text = "Invoice No: A-1\nInvoice Date: 2026-11-02\nSubtotal: 10.00\nTax (10%): 1.00\nTotal Due: 11.00"
        record, issues = extract_record(text, CONFIG, "a.pdf")
        self.assertEqual(record["customer"], "")
        self.assertEqual([(i.field, i.status) for i in issues], [("customer", "missing")])

    def test_empty_field_does_not_borrow_next_line(self):
        text = "Invoice No: A-1\nInvoice Date: 2026-11-02\nBill To:\nSubtotal: 10.00\nTax (10%): 1.00\nTotal Due: 11.00"
        record, issues = extract_record(text, CONFIG, "a.pdf")
        self.assertEqual(record["customer"], "")
        self.assertIn(("customer", "missing"), [(i.field, i.status) for i in issues])

    def test_spaced_amount_is_reported_not_truncated(self):
        text = "Invoice No: A-1\nInvoice Date: 2026-11-02\nBill To: X\nSubtotal: 1 280.00\nTax (10%): 0.00\nTotal Due: USD 1 280.00"
        record, issues = extract_record(text, CONFIG, "a.pdf")
        self.assertEqual(record["subtotal"], "")
        self.assertIn(("subtotal", "unparsable"), [(i.field, i.status) for i in issues])
        self.assertIn(("total", "unparsable"), [(i.field, i.status) for i in issues])

    def test_arithmetic_check(self):
        text = "Invoice No: A-1\nInvoice Date: 2026-11-02\nBill To: X\nSubtotal: 10.00\nTax (10%): 1.00\nTotal Due: 12.00"
        _, issues = extract_record(text, CONFIG, "a.pdf")
        self.assertEqual([(i.field, i.status) for i in issues], [("total", "check_failed")])


class EndToEndTests(unittest.TestCase):
    def test_sample_pdfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, report = Path(tmp, "out.csv"), Path(tmp, "report.csv")
            n_records, n_issues = run([SAMPLES], CONFIG, out, report)
            self.assertEqual((n_records, n_issues), (5, 2))
            with out.open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["invoice_no"], "A-1042")
            self.assertEqual(rows[0]["total"], "1280.00")

    def test_broken_pdf_is_reported_and_others_still_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "in")
            folder.mkdir()
            (folder / "broken.pdf").write_bytes(b"not a pdf")
            (folder / "good.pdf").write_bytes((SAMPLES / "invoice_A-1042.pdf").read_bytes())
            out, report = Path(tmp, "out.csv"), Path(tmp, "report.csv")
            n_records, _ = run([folder], CONFIG, out, report)
            self.assertEqual(n_records, 2)
            with report.open(encoding="utf-8-sig") as f:
                statuses = [(r["file"], r["status"]) for r in csv.DictReader(f)]
            self.assertIn(("broken.pdf", "unreadable"), statuses)


if __name__ == "__main__":
    unittest.main()
