"""Suppress callback request diagnostics; lifecycle events live in the database."""

import logging


CALLBACKS = tuple(f"/integrations/{p}/callback" for p in ("quickbooks", "microsoft", "xero"))


class NoOAuthCallbackDiagnostics(logging.Filter):
    def filter(self, record):
        request = getattr(record, "request", None)
        if request and request.path.startswith(CALLBACKS):
            return False
        # Django server/access records may have no request attached.
        if any(path in record.getMessage() for path in CALLBACKS):
            return False
        return True
