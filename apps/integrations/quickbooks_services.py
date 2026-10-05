"""Sandbox-only lifecycle. Each service owns its transaction and authority check."""

import hashlib
import re
import secrets
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from agentledger.tenancy.context import activate_tenant, identity_transaction
from apps.organizations.models import OrganizationMember

from .models import QuickBooksAttempt, QuickBooksConnection, QuickBooksEvent
from .quickbooks_client import OAuthConfig, OAuthError, QuickBooksClient
from .quickbooks_crypto import decrypt_credentials, encrypt_credentials, keyring


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def sandbox_workspace_choices(user):
    if (
        not settings.QUICKBOOKS_SANDBOX_ENABLED
        or not user.is_authenticated
        or not user.is_active
        or str(user.id) not in settings.QUICKBOOKS_SANDBOX_USER_IDS
    ):
        raise PermissionDenied("Sandbox integration access is not enabled.")
    with identity_transaction(user.id):
        return list(
            OrganizationMember.objects.filter(user_id=user.id, role="owner")
            .order_by("organization__name", "organization_id")
            .values("organization_id", "organization__name")
        )


@contextmanager
def authority(user, organization_id):
    # No outer request transaction: consumed states and revocation intent must
    # commit before network calls; callback failures must not undo these writes.
    if connection.in_atomic_block:
        raise OAuthError("outer_transaction_forbidden")
    if (
        not settings.QUICKBOOKS_SANDBOX_ENABLED
        or not user.is_authenticated
        or not user.is_active
        or str(user.id) not in settings.QUICKBOOKS_SANDBOX_USER_IDS
    ):
        raise PermissionDenied("Sandbox integration access is not enabled.")
    try:
        organization_id = UUID(str(organization_id))
    except (TypeError, ValueError, AttributeError):
        raise PermissionDenied("Select an authorized workspace.") from None
    with identity_transaction(user.id):
        if not OrganizationMember.objects.filter(
            organization_id=organization_id,
            user_id=user.id,
            role="owner",
        ).exists():
            raise PermissionDenied("Workspace owner access is required.")
        activate_tenant(organization_id)
        yield organization_id


def owned(user, organization_id):
    obj = (
        QuickBooksConnection.objects.select_for_update()
        .filter(
            organization_id=organization_id,
            connected_by_id=user.id,
        )
        .first()
    )
    if obj is None or obj.environment != "sandbox":
        raise PermissionDenied("This connection is not available.")
    return obj


def record(obj, kind):
    return QuickBooksEvent.objects.create(connection=obj, kind=kind)


@sensitive_variables()
def begin(user, organization_id, session_nonce):
    client = QuickBooksClient(OAuthConfig.load())
    keyring()  # Never redirect to consent if we cannot securely persist tokens.
    state = secrets.token_urlsafe(32)
    url = client.authorization_url(state)
    with authority(user, organization_id) as org_id:
        obj, _ = QuickBooksConnection.objects.get_or_create(
            organization_id=org_id,
            defaults={"connected_by_id": user.id},
        )
        obj = owned(user, org_id)
        if obj.status != QuickBooksConnection.Status.DISCONNECTED:
            raise OAuthError("disconnect_before_reconnect")
        if QuickBooksAttempt.objects.filter(
            connection=obj,
            created_at__gt=timezone.now() - timedelta(seconds=30),
        ).exists():
            raise OAuthError("authorization_rate_limited")
        obj.generation += 1
        obj.save(update_fields=["generation", "updated_at"])
        QuickBooksAttempt.objects.create(
            connection=obj,
            state_hash=digest(state),
            session_hash=digest(session_nonce),
            generation=obj.generation,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        record(obj, "authorization_started")
    return url


@sensitive_variables()
def complete(user, organization_id, session_nonce, query):
    state = query.get("state", "")
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{43}", state)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", session_nonce)
        or any(len(query.getlist(k)) != 1 for k in query)
    ):
        raise OAuthError("invalid_authorization_state")
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        attempt = (
            QuickBooksAttempt.objects.select_for_update()
            .filter(
                connection=obj,
                state_hash=digest(state),
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
                generation=obj.generation,
                session_hash=digest(session_nonce),
            )
            .first()
        )
        if attempt is None or obj.status != QuickBooksConnection.Status.DISCONNECTED:
            raise OAuthError("invalid_authorization_state")
        attempt.consumed_at = timezone.now()
        attempt.save(update_fields=["consumed_at"])
        generation = attempt.generation
        record(obj, "authorization_consumed")
    # State is now durably consumed even if the exchange fails or the user denies.
    if "error" in query:
        raise OAuthError("authorization_denied")
    code, realm = query.get("code", ""), query.get("realmId", "")
    if not re.fullmatch(r"[\x21-\x7e]{1,4096}", code) or not re.fullmatch(
        r"[0-9]{1,32}", realm
    ):
        raise OAuthError("invalid_callback")
    client = QuickBooksClient(OAuthConfig.load())
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        if (
            obj.generation != generation
            or obj.status != QuickBooksConnection.Status.DISCONNECTED
        ):
            raise OAuthError("authorization_superseded")
        started = timezone.now()
        tokens = client.tokens(code=code)
        store_tokens(obj, realm, tokens, started)
        record(obj, "connected")


@sensitive_variables()
def store_tokens(obj, realm, tokens, started):
    obj.encrypted_credentials = encrypt_credentials(
        obj,
        {
            "realm_id": realm,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        },
    )
    obj.access_expires_at = started + timedelta(seconds=tokens["expires_in"])
    obj.refresh_expires_at = started + timedelta(
        seconds=tokens["x_refresh_token_expires_in"]
    )
    obj.status = QuickBooksConnection.Status.CONNECTED
    obj.save(
        update_fields=[
            "encrypted_credentials",
            "access_expires_at",
            "refresh_expires_at",
            "status",
            "updated_at",
        ]
    )


@sensitive_variables()
def refresh(user, organization_id):
    client = QuickBooksClient(OAuthConfig.load())
    failure = None
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        if obj.status != QuickBooksConnection.Status.CONNECTED:
            raise OAuthError("connection_unavailable")
        now = timezone.now()
        if obj.refresh_expires_at is None or obj.refresh_expires_at <= now:
            failure = "reconnect_required"
        elif obj.access_expires_at and obj.access_expires_at > now + timedelta(
            seconds=60
        ):
            return "still_valid"
        if failure is None:
            credentials = decrypt_credentials(obj)
            try:
                tokens = client.tokens(refresh_token=credentials["refresh_token"])
            except OAuthError as error:
                if error.code != "reconnect_required":
                    raise
                failure = error.code
            if failure is None:
                store_tokens(obj, credentials["realm_id"], tokens, now)
                record(obj, "token_refreshed")
        if failure:
            obj.status = QuickBooksConnection.Status.RECONNECT
            obj.save(update_fields=["status", "updated_at"])
            record(obj, "reconnect_required")
    # Raise after commit so the blocked status survives the failed operation.
    if failure:
        raise OAuthError(failure)
    return "refreshed"


@sensitive_variables()
def disconnect(user, organization_id):
    client = QuickBooksClient(OAuthConfig.load())
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        obj.generation += 1  # Fence outstanding callbacks before making any request.
        obj.status = QuickBooksConnection.Status.REVOKING
        obj.save(update_fields=["generation", "status", "updated_at"])
        record(obj, "disconnect_requested")
    # Failure leaves revoking status and encrypted token for an explicit retry.
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        if obj.status != QuickBooksConnection.Status.REVOKING:
            raise OAuthError("connection_unavailable")
        if obj.encrypted_credentials:
            credentials = decrypt_credentials(obj)
            client.revoke(credentials["refresh_token"])
        obj.encrypted_credentials = ""
        obj.access_expires_at = None
        obj.refresh_expires_at = None
        obj.status = QuickBooksConnection.Status.DISCONNECTED
        obj.save(
            update_fields=[
                "encrypted_credentials",
                "access_expires_at",
                "refresh_expires_at",
                "status",
                "updated_at",
            ]
        )
        record(obj, "disconnected")


def connection_status(user, organization_id):
    with authority(user, organization_id) as org_id:
        obj = (
            QuickBooksConnection.objects.filter(
                organization_id=org_id,
                connected_by_id=user.id,
            )
            .only("status", "updated_at")
            .first()
        )
        return obj.get_status_display() if obj else "Disconnected"


@sensitive_variables()
def verify_company_access(user, organization_id):
    """Owner-initiated reachability check, without collecting financial records."""
    failure = None
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        if obj.status != QuickBooksConnection.Status.CONNECTED:
            raise OAuthError("connection_unavailable")
        now = timezone.now()
        if (
            not obj.access_expires_at
            or obj.access_expires_at <= now + timedelta(seconds=60)
            or not obj.refresh_expires_at
            or obj.refresh_expires_at <= now
        ):
            raise OAuthError("token_check_required")
        if QuickBooksEvent.objects.filter(
            connection=obj,
            kind="company_check_started",
            created_at__gt=now - timedelta(seconds=30),
        ).exists():
            raise OAuthError("company_check_rate_limited")
        client = QuickBooksClient(OAuthConfig.load())
        credentials = decrypt_credentials(obj)
        record(obj, "company_check_started")
        try:
            client.verify_company_access(
                credentials["realm_id"], credentials["access_token"]
            )
        except OAuthError as error:
            failure = error.code
            record(obj, "company_check_failed")
        else:
            record(obj, "company_access_verified")
    if failure:
        raise OAuthError(failure)


@sensitive_variables()
def export_profit_and_loss(user, organization_id, period):
    from .quickbooks_reports import ReportPeriod, report_evidence

    if not isinstance(period, ReportPeriod):
        raise OAuthError("invalid_report_period")
    failure = None
    evidence = None
    with authority(user, organization_id) as org_id:
        obj = owned(user, org_id)
        now = timezone.now()
        if obj.status != QuickBooksConnection.Status.CONNECTED:
            raise OAuthError("connection_unavailable")
        if (
            not obj.access_expires_at
            or obj.access_expires_at <= now + timedelta(seconds=60)
            or not obj.refresh_expires_at
            or obj.refresh_expires_at <= now
        ):
            raise OAuthError("token_check_required")
        if QuickBooksEvent.objects.filter(
            connection=obj,
            kind="report_export_started",
            created_at__gt=now - timedelta(seconds=60),
        ).exists():
            raise OAuthError("report_export_rate_limited")
        client = QuickBooksClient(OAuthConfig.load())
        credentials = decrypt_credentials(obj)
        record(obj, "report_export_started")
        try:
            raw = client.profit_and_loss(
                credentials["realm_id"], credentials["access_token"], period
            )
            evidence = report_evidence(raw, period)
        except OAuthError as error:
            failure = error.code
            record(obj, "report_export_failed")
        else:
            event = record(obj, "report_export_prepared")
            evidence.update(
                {
                    "workspace_id": str(org_id),
                    "connection_reference": str(obj.id),
                    "connection_generation": obj.generation,
                    "audit_event_id": str(event.id),
                    "prepared_at": event.created_at.isoformat(),
                    "server_retention": (
                        "report body not persisted; lifecycle event retained"
                    ),
                    "delivery_status": (
                        "prepared; browser receipt not independently confirmed"
                    ),
                }
            )
    if failure:
        raise OAuthError(failure)
    return evidence
