from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from apps.inventory.models import InventoryItem

MAX_IMPORT_ROWS = 100
MAX_UPLOAD_BYTES = 1_000_000
REQUIRED_HEADERS = ("display_name", "vendor_name", "monthly_cost")
OPTIONAL_HEADERS = (
    "business_owner",
    "department",
    "user_count",
    "business_purpose",
    "seat_count",
    "autonomy_level",
    "human_approval",
    "status",
)


class ImportFileError(ValueError):
    pass


def _clean_integer(value: str, label: str, errors: list[str]) -> int:
    try:
        result = int(value or "0")
    except ValueError:
        errors.append(f"{label} must be a whole number.")
        return 0
    if result < 0:
        errors.append(f"{label} cannot be negative.")
        return 0
    return result


def validate_row(raw: dict[str, str]) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    display_name = (raw.get("display_name") or "").strip()
    vendor_name = (raw.get("vendor_name") or "").strip()
    if not display_name:
        errors.append("Enter the software or AI name.")
    if not vendor_name:
        errors.append("Enter the vendor name.")

    monthly_cost_text = (raw.get("monthly_cost") or "").strip()
    monthly_cost_cents = 0
    try:
        monthly_cost = Decimal(monthly_cost_text)
        if (
            not monthly_cost.is_finite()
            or monthly_cost < 0
            or monthly_cost.as_tuple().exponent < -2
        ):
            raise InvalidOperation
        monthly_cost_cents = int(monthly_cost * Decimal(100))
    except (InvalidOperation, ValueError):
        errors.append("Enter the monthly cost in dollars, such as 49.00.")

    autonomy_level = _clean_integer(
        (raw.get("autonomy_level") or "0").strip(),
        "Independent action",
        errors,
    )
    if autonomy_level not in InventoryItem.Autonomy.values:
        errors.append("Choose an independent-action option from 0 through 4.")
        autonomy_level = 0

    status = (raw.get("status") or InventoryItem.Status.REVIEWING).strip().lower()
    if status not in InventoryItem.Status.values:
        errors.append("Choose active, trial, inactive, or reviewing for status.")
        status = InventoryItem.Status.REVIEWING

    approval_text = (raw.get("human_approval") or "yes").strip().lower()
    approval_values = {
        "yes": True,
        "true": True,
        "1": True,
        "no": False,
        "false": False,
        "0": False,
    }
    if approval_text not in approval_values:
        errors.append("Human approval must be yes or no.")
    human_approval = approval_values.get(approval_text, True)

    return (
        {
            "display_name": display_name,
            "vendor_name": vendor_name,
            "business_owner": (raw.get("business_owner") or "").strip(),
            "department": (raw.get("department") or "").strip(),
            "user_count": _clean_integer(raw.get("user_count") or "0", "Users", errors),
            "business_purpose": (raw.get("business_purpose") or "").strip(),
            "monthly_cost_cents": monthly_cost_cents,
            "seat_count": _clean_integer(
                raw.get("seat_count") or "0", "Paid seats", errors
            ),
            "autonomy_level": autonomy_level,
            "human_approval": human_approval,
            "status": status,
        },
        errors,
    )


def parse_csv_upload(upload) -> list[tuple[int, dict[str, object], list[str]]]:
    if upload.size > MAX_UPLOAD_BYTES:
        raise ImportFileError("Choose a CSV file smaller than 1 MB.")
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportFileError(
            "Save the spreadsheet as a UTF-8 CSV and try again."
        ) from error

    reader = csv.DictReader(io.StringIO(text))
    headers = tuple(reader.fieldnames or ())
    missing = [header for header in REQUIRED_HEADERS if header not in headers]
    if missing:
        raise ImportFileError(
            "The CSV is missing required columns: " + ", ".join(missing) + "."
        )
    rows = list(reader)
    if not rows:
        raise ImportFileError("The CSV does not contain any software rows.")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ImportFileError("Import no more than 100 software rows at one time.")

    results = []
    seen: set[tuple[str, str]] = set()
    for row_number, raw in enumerate(rows, start=2):
        data, errors = validate_row(raw)
        duplicate_key = (
            str(data["display_name"]).casefold(),
            str(data["vendor_name"]).casefold(),
        )
        if duplicate_key in seen:
            errors.append("This software and vendor appear more than once in the CSV.")
        seen.add(duplicate_key)
        results.append((row_number, data, errors))
    return results
