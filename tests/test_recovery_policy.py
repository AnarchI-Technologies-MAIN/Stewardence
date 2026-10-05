import httpx
import pytest
from django.core.exceptions import PermissionDenied, ImproperlyConfigured
from apps.jobs.recovery import permits_retry
from apps.reports.render_client import HTTPReportRenderer, ReportRenderError


@pytest.mark.parametrize("error", [ValueError("bad payload"), PermissionDenied("wrong firm"),
    ImproperlyConfigured("missing configuration"), RuntimeError("unclassified")])
def test_unknown_or_authority_failures_require_review(error):
    assert not permits_retry(error)


def test_wrapped_transport_timeout_is_retryable_but_permission_denial_is_not():
    cause = httpx.ReadTimeout("private transport details")
    wrapped = ReportRenderError("request failed")
    wrapped.__cause__ = cause
    assert permits_retry(wrapped)
    denied = PermissionDenied("scope unresolved")
    denied.__cause__ = cause
    assert not permits_retry(denied)


@pytest.mark.parametrize("permanent", [PermissionDenied("denied"), ValueError("invalid")])
def test_nested_permanent_failure_vetoes_transient_cause_in_either_order(permanent):
    from apps.jobs.recovery import RetryableOperationError
    outer = RuntimeError("wrapper")
    outer.__cause__ = permanent
    permanent.__cause__ = httpx.ReadTimeout("transport")
    assert not permits_retry(outer)
    marker = RetryableOperationError("transient marker")
    marker.__cause__ = permanent
    assert not permits_retry(marker)


def test_causal_cycle_is_not_retry_admission():
    timeout = httpx.ReadTimeout("transport")
    wrapper = RuntimeError("wrapper")
    timeout.__cause__ = wrapper
    wrapper.__cause__ = timeout
    assert not permits_retry(wrapper)


def test_unknown_wrapper_does_not_admit_transport_retry():
    wrapper = RuntimeError('unknown operation')
    wrapper.__cause__ = httpx.ReadTimeout('transport')
    assert not permits_retry(wrapper)


def test_suppressed_unknown_context_requires_review():
    from apps.jobs.recovery import RetryableOperationError
    try:
        try: raise RuntimeError('unclassified failure')
        except RuntimeError: raise RetryableOperationError('transient marker') from None
    except RetryableOperationError as error:
        assert not permits_retry(error)


@pytest.mark.parametrize('suppress',[False,True])
def test_implicit_or_suppressed_authority_context_always_vetoes_retry(suppress):
    try:
        try:
            raise PermissionDenied('denied')
        except PermissionDenied:
            if suppress:
                raise httpx.ReadTimeout('transport') from None
            raise httpx.ReadTimeout('transport')
    except httpx.ReadTimeout as error:
        assert not permits_retry(error)


@pytest.mark.parametrize("status,retry", [(400,False),(401,False),(403,False),(429,True),(503,True)])
def test_renderer_status_admits_only_bounded_transient_recovery(status, retry):
    renderer = HTTPReportRenderer(base_url="http://renderer", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text="provider secret must never propagate")))
    with pytest.raises(ReportRenderError) as error:
        renderer.render({})
    assert permits_retry(error.value) is retry
    assert "provider secret" not in str(error.value)
