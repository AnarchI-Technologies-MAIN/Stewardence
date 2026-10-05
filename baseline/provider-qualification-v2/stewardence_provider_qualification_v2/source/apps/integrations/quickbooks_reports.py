"""Lossless sandbox report export; no financial or ROI inference."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.views.decorators.debug import sensitive_variables

from .quickbooks_client import OAuthError


@dataclass(frozen=True)
class ReportPeriod:
    start: date
    end: date
    basis: str

    def __post_init__(self):
        if (
            type(self.start) is not date
            or type(self.end) is not date
            or not 0 <= (self.end - self.start).days < 92
            or self.end == date.max
            or self.basis not in ("Cash", "Accrual")
        ):
            raise OAuthError("invalid_report_period")

    def parameters(self):
        return {
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
            "accounting_method": self.basis,
            "summarize_column_by": "Total",
        }


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def reject_constant(value):
    raise ValueError("Non-finite JSON constant")


@sensitive_variables()
def report_evidence(raw, period):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 2 * 1024 * 1024:
        raise OAuthError("invalid_report_response")
    try:
        source = raw.decode("utf-8")
        report = json.loads(
            source,
            object_pairs_hook=unique_keys,
            parse_float=Decimal,
            parse_constant=reject_constant,
        )
        # Bound nesting and structure before accepting a provider document.
        pending = [(report, 0)]
        visited = 0
        while pending:
            value, depth = pending.pop()
            visited += 1
            if depth > 32 or visited > 50000:
                raise ValueError("Report structure exceeds supported bounds")
            if isinstance(value, dict):
                pending.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list):
                pending.extend((v, depth + 1) for v in value)
        header = report["Header"]
        if (
            "Fault" in report
            or header["ReportName"] != "ProfitAndLoss"
            or header["StartPeriod"] != period.start.isoformat()
            or header["EndPeriod"] != period.end.isoformat()
            or header["ReportBasis"] != period.basis
            or header["SummarizeColumnsBy"] != "Total"
            or not isinstance(header["Currency"], str)
            or not re.fullmatch(r"[A-Z]{3}", header["Currency"])
            or not isinstance(report["Columns"]["Column"], list)
            or len(report["Columns"]["Column"]) != 2
            or not isinstance(report["Rows"], dict)
            or not isinstance(report["Rows"].get("Row", []), list)
        ):
            raise ValueError("Report metadata mismatch")
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise OAuthError("invalid_report_response") from None
    return {
        "schema": "stewardence.quickbooks.sandbox-report.v1",
        "validation_rule": "profit-and-loss-header.v1",
        "provider": "quickbooks_online",
        "environment": "sandbox",
        "report_name": "ProfitAndLoss",
        "accounting_basis": period.basis,
        "currency": header["Currency"],
        "period_start": period.start.isoformat(),
        "provider_period_end_inclusive": period.end.isoformat(),
        "period_end_exclusive": (period.end + timedelta(days=1)).isoformat(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_encoding": "utf-8",
        "source_json": source,
        "interpretation": "source_report_only",
        "completeness": "not_independently_established",
        "roi_status": "not_calculated",
        "integrity_note": (
            "SHA256 covers source_json encoded as UTF-8; not a provider signature."
        ),
    }
