"""Extract fields from text-based PDFs into CSV, with a validation report.

Every value is pulled with a field rule (a regular expression), normalized
(dates to ISO 8601, amounts to plain decimals) and checked. Anything missing,
unparsable or inconsistent is written to the validation report instead of
being silently guessed.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from pypdf import PdfReader

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%d.%m.%Y"]
# 1,280.00 / 1280.00 / 1280 / $1,280.00 / USD 1,280.00 / -5.00 (dot = decimal separator, comma = thousands)
MONEY_RE = re.compile(r"(?:[A-Z]{3}[ \t]*|\$)?(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)")
INT_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)")


@dataclass
class FieldRule:
    name: str
    pattern: str
    type: str = "text"  # text | date | money | int
    required: bool = True


@dataclass
class Check:
    """Arithmetic check: sum(parts) must equal `equals` (within 0.01)."""

    parts: list[str]
    equals: str


@dataclass
class Config:
    fields: list[FieldRule]
    checks: list[Check] = field(default_factory=list)


@dataclass
class Issue:
    file: str
    field: str
    status: str  # missing | unparsable | check_failed | unreadable
    detail: str


def load_config(path: str | Path) -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules = [FieldRule(**f) for f in data["fields"]]
    checks = [Check(parts=c["sum"], equals=c["equals"]) for c in data.get("checks", [])]
    return Config(fields=rules, checks=checks)


def read_pdf_text(path: str | Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def normalize(value: str, kind: str) -> str:
    """Return the normalized value or raise ValueError."""
    value = value.strip()
    if kind == "text":
        if not value:
            raise ValueError("empty")
        return value
    if kind == "date":
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        raise ValueError(f"unrecognized date '{value}'")
    if kind == "money":
        # Accept only unambiguous formats; anything else is reported, never "fixed" silently.
        match = MONEY_RE.fullmatch(value)
        if not match:
            raise ValueError(f"unexpected amount format '{value}'")
        try:
            return str(Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01")))
        except InvalidOperation as exc:
            raise ValueError(f"not an amount '{value}'") from exc
    if kind == "int":
        if not INT_RE.fullmatch(value):
            raise ValueError(f"unexpected integer format '{value}'")
        return str(int(value.replace(",", "")))
    raise ValueError(f"unknown field type '{kind}'")


def extract_record(text: str, config: Config, file_label: str) -> tuple[dict[str, str], list[Issue]]:
    record: dict[str, str] = {"source_file": file_label}
    issues: list[Issue] = []
    for rule in config.fields:
        match = re.search(rule.pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            record[rule.name] = ""
            if rule.required:
                issues.append(Issue(file_label, rule.name, "missing", "pattern not found"))
            continue
        raw = match.group(1) if match.groups() else match.group(0)
        try:
            record[rule.name] = normalize(raw, rule.type)
        except ValueError as exc:
            record[rule.name] = ""
            issues.append(Issue(file_label, rule.name, "unparsable", str(exc)))

    for check in config.checks:
        values = [record.get(n, "") for n in check.parts + [check.equals]]
        if not all(values):
            continue  # already reported as missing/unparsable
        total = sum(Decimal(record[n]) for n in check.parts)
        expected = Decimal(record[check.equals])
        if abs(total - expected) > Decimal("0.01"):
            issues.append(
                Issue(
                    file_label,
                    check.equals,
                    "check_failed",
                    f"{' + '.join(check.parts)} = {total} but {check.equals} = {expected}",
                )
            )
    return record, issues


def run(inputs: list[Path], config: Config, out_csv: Path, report_csv: Path) -> tuple[int, int]:
    pdfs: list[Path] = []
    for item in inputs:
        pdfs.extend(sorted(item.glob("*.pdf")) if item.is_dir() else [item])

    records, issues = [], []
    for pdf in pdfs:
        try:
            text = read_pdf_text(pdf)
        except Exception as exc:  # a broken file is reported, the rest still run
            records.append({"source_file": pdf.name})
            issues.append(Issue(pdf.name, "", "unreadable", f"{type(exc).__name__}: {exc}"))
            continue
        record, found = extract_record(text, config, pdf.name)
        records.append(record)
        issues.extend(found)

    columns = ["source_file"] + [f.name for f in config.fields]
    # utf-8-sig so the file opens cleanly in Excel
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    with report_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "field", "status", "detail"])
        for i in issues:
            writer.writerow([i.file, i.field, i.status, i.detail])
    return len(records), len(issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract fields from text-based PDFs into a CSV.")
    parser.add_argument("inputs", nargs="+", type=Path, help="PDF files or folders of PDFs")
    parser.add_argument("--config", required=True, type=Path, help="YAML file with field rules")
    parser.add_argument("--out", default=Path("output.csv"), type=Path)
    parser.add_argument("--report", default=Path("validation_report.csv"), type=Path)
    args = parser.parse_args(argv)

    n_records, n_issues = run(args.inputs, load_config(args.config), args.out, args.report)
    print(f"{n_records} file(s) -> {args.out}")
    print(f"{n_issues} issue(s) -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
