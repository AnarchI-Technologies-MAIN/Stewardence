"""Admission policy for automated recovery: unknown failures require review."""
import httpx
from botocore.exceptions import EndpointConnectionError, ConnectionClosedError, ReadTimeoutError
from django.core.exceptions import PermissionDenied, ValidationError, ImproperlyConfigured


class RetryableOperationError(RuntimeError):
    """A bounded, repeatable operation failed transiently without changing authority."""


class ReplaySafeErrorWrapper(RuntimeError):
    """Explicit wrapper for deterministic rendering/conditional object operations."""


def permits_retry(error: Exception) -> bool:
    # Traceback suppression never suppresses authority evidence. Inspect both
    # links for vetoes, with a bounded graph walk and cycle detection.
    permanent = (PermissionDenied, ValidationError, ImproperlyConfigured, ValueError)
    transient_types = (RetryableOperationError, httpx.TimeoutException,
        httpx.ConnectError, httpx.ReadError, EndpointConnectionError,
        ConnectionClosedError, ReadTimeoutError)
    active, checked = set(), set()
    transient = False
    def admit_graph(node):
        nonlocal transient
        if node is None or id(node) in checked:
            return True
        if id(node) in active or len(active) + len(checked) >= 64 or isinstance(node, permanent):
            return False
        if isinstance(node, transient_types):
            transient = True
        elif not isinstance(node, ReplaySafeErrorWrapper):
            return False
        active.add(id(node))
        if not admit_graph(node.__cause__) or not admit_graph(node.__context__):
            return False
        active.remove(id(node))
        checked.add(id(node))
        return True
    # Context-only transient evidence is admitted only when every reachable
    # node belongs to this closed replay-safe domain.
    return admit_graph(error) and transient
