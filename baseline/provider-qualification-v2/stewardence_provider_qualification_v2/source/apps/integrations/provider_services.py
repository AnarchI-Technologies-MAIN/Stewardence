"""Owner preview lifecycle. No paid entitlements, worker access, or automatic jobs."""

import hashlib
import re
import secrets
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from agentledger.tenancy.context import activate_tenant, identity_transaction
from apps.organizations.models import OrganizationMember

from .models import ProviderAttempt, ProviderConnection, ProviderEvent
from .provider_client import ProviderClient, ProviderConfig, opaque, require
from .provider_crypto import decrypt, encrypt, keyring
from .quickbooks_client import OAuthError


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def actor(user, provider):
    config = ProviderConfig.load(provider)
    if (
        not user.is_authenticated
        or not user.is_active
        or str(user.id) != config.owner_user_id
    ):
        raise PermissionDenied("Owner preview access required.")
    return config


def workspace_choices(user, provider):
    actor(user, provider)
    with identity_transaction(user.id):
        return list(
            OrganizationMember.objects.filter(user_id=user.id, role="owner")
            .order_by("organization__name", "organization_id")
            .values("organization_id", "organization__name")
        )


@contextmanager
def authority(user, organization_id, provider):
    require(not connection.in_atomic_block, "outer_transaction_forbidden")
    actor(user, provider)
    try:
        org_id = UUID(str(organization_id))
    except (TypeError, ValueError, AttributeError):
        raise PermissionDenied("Select an authorized workspace.") from None
    with identity_transaction(user.id):
        if not OrganizationMember.objects.filter(
            user_id=user.id, organization_id=org_id, role="owner"
        ).exists():
            raise PermissionDenied("Workspace owner access required.")
        activate_tenant(org_id)
        yield org_id


def owned(user, org_id, provider):
    obj = (
        ProviderConnection.objects.select_for_update()
        .filter(
            organization_id=org_id,
            connected_by_id=user.id,
            provider=provider,
            environment="owner_preview",
        )
        .first()
    )
    if obj is None:
        raise PermissionDenied("Connection unavailable.")
    return obj


def record(obj, kind):
    return ProviderEvent.objects.create(connection=obj, kind=kind)


@sensitive_variables()
def begin(user, org_id, provider, nonce):
    config = actor(user, provider)
    require(re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce) is not None, "invalid_session")
    keyring()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    url = ProviderClient(config).authorization_url(state, verifier)
    with authority(user, org_id, provider) as org_id:
        ProviderConnection.objects.get_or_create(
            organization_id=org_id,
            provider=provider,
            defaults={"connected_by_id": user.id},
        )
        obj = owned(user, org_id, provider)
        require(obj.status == "disconnected", "disconnect_before_reconnect")
        require(
            not ProviderAttempt.objects.filter(
                connection=obj, created_at__gt=timezone.now() - timedelta(seconds=30)
            ).exists(),
            "authorization_rate_limited",
        )
        obj.generation += 1
        obj.save(update_fields=["generation", "updated_at"])
        attempt = ProviderAttempt(
            connection=obj,
            state_hash=digest(state),
            session_hash=digest(nonce),
            generation=obj.generation,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        attempt.encrypted_verifier = encrypt(
            obj, {"verifier": verifier}, "attempt:" + str(attempt.id)
        )
        attempt.save()
        record(obj, "authorization_started")
    return url


@sensitive_variables()
def complete(user, org_id, provider, nonce, query):
    state = query.get("state", "")
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{43}", state) is not None
        and re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce) is not None
        and all(len(query.getlist(k)) == 1 for k in query),
        "invalid_authorization_state",
    )
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        attempt = (
            ProviderAttempt.objects.select_for_update()
            .filter(
                connection=obj,
                state_hash=digest(state),
                session_hash=digest(nonce),
                generation=obj.generation,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        require(
            attempt is not None and obj.status == "disconnected",
            "invalid_authorization_state",
        )
        verifier = decrypt(
            obj, attempt.encrypted_verifier, "attempt:" + str(attempt.id)
        )["verifier"]
        attempt.consumed_at = timezone.now()
        attempt.encrypted_verifier = ""
        attempt.save(update_fields=["consumed_at", "encrypted_verifier"])
        generation = obj.generation
        record(obj, "authorization_consumed")
    # A failed exchange or rejected tenant must not resurrect authorization state.
    require("error" not in query, "authorization_denied")
    code = opaque(query.get("code"), 4096)
    client = ProviderClient(actor(user, provider))
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        require(
            obj.generation == generation and obj.status == "disconnected",
            "authorization_superseded",
        )
        started = timezone.now()
        tokens = client.tokens(code=code, verifier=verifier)
        account = client.bind_account(tokens["access_token"])
        store(obj, account, tokens, started)
        record(obj, "connected")


@sensitive_variables()
def store(obj, account, tokens, started):
    obj.encrypted_credentials = encrypt(
        obj,
        {
            "account": account,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        },
    )
    obj.access_expires_at = started + timedelta(seconds=tokens["expires_in"])
    obj.status = "connected"
    obj.save(
        update_fields=[
            "encrypted_credentials",
            "access_expires_at",
            "status",
            "updated_at",
        ]
    )


@sensitive_variables()
def refresh(user, org_id, provider):
    client = ProviderClient(actor(user, provider))
    failure = None
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        require(obj.status == "connected", "connection_unavailable")
        now = timezone.now()
        if obj.access_expires_at and obj.access_expires_at > now + timedelta(
            seconds=60
        ):
            return "token_still_valid"
        credentials = decrypt(obj, obj.encrypted_credentials)
        try:
            tokens = client.tokens(refresh_token=credentials["refresh_token"])
        except OAuthError as error:
            # Any ambiguous refresh failure requires explicit reconnect. Never race
            # token rotation or silently reuse credentials of uncertain validity.
            failure = error.code
            obj.status = "reconnect"
            obj.save(update_fields=["status", "updated_at"])
            record(obj, "reconnect_required")
        if failure is None:
            store(obj, credentials["account"], tokens, now)
            record(obj, "token_refreshed")
    if failure:
        raise OAuthError(failure)
    return "token_refreshed"


@sensitive_variables()
def verify_account(user, org_id, provider):
    client = ProviderClient(actor(user, provider))
    failure = None
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        require(obj.status == "connected", "connection_unavailable")
        now = timezone.now()
        require(
            obj.access_expires_at
            and obj.access_expires_at > now + timedelta(seconds=60),
            "token_check_required",
        )
        require(
            not ProviderEvent.objects.filter(
                connection=obj,
                kind="account_check_started",
                created_at__gt=now - timedelta(seconds=30),
            ).exists(),
            "account_check_rate_limited",
        )
        credentials = decrypt(obj, obj.encrypted_credentials)
        record(obj, "account_check_started")
        try:
            client.verify_account(credentials["access_token"], credentials["account"])
        except OAuthError as error:
            failure = error.code
            record(obj, "account_check_failed")
            if failure in (
                "reconnect_required",
                "tenant_mismatch",
                "demo_company_required",
            ):
                obj.status = "reconnect"
                obj.save(update_fields=["status", "updated_at"])
        if failure is None:
            record(obj, "account_access_verified")
    if failure:
        raise OAuthError(failure)


@sensitive_variables()
def disconnect(user, org_id, provider):
    # Local disconnect stays available even if the client secret has expired.
    # Current preview configuration/owner authority must still be accessible.
    client = ProviderClient(actor(user, provider))
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        obj.generation += 1
        obj.status = "revoking"
        obj.save(update_fields=["generation", "status", "updated_at"])
        ProviderAttempt.objects.filter(connection=obj, consumed_at__isnull=True).update(
            consumed_at=timezone.now(), encrypted_verifier=""
        )
        record(obj, "disconnect_requested")
    failure = None
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        require(obj.status == "revoking", "connection_unavailable")
        outcome = "local_disconnected"
        if provider == "xero" and obj.encrypted_credentials:
            credentials = decrypt(obj, obj.encrypted_credentials)
            token = credentials["access_token"]
            if (
                not obj.access_expires_at
                or obj.access_expires_at <= timezone.now() + timedelta(seconds=60)
            ):
                tokens = client.tokens(refresh_token=credentials["refresh_token"])
                # Persist rotated token before a possibly failing remote disconnect.
                obj.encrypted_credentials = encrypt(
                    obj,
                    {
                        **credentials,
                        "access_token": tokens["access_token"],
                        "refresh_token": tokens["refresh_token"],
                    },
                )
                obj.access_expires_at = timezone.now() + timedelta(
                    seconds=tokens["expires_in"]
                )
                obj.save(
                    update_fields=[
                        "encrypted_credentials",
                        "access_expires_at",
                        "updated_at",
                    ]
                )
                token = tokens["access_token"]
            try:
                client.disconnect_remote(token, credentials["account"])
            except OAuthError as error:
                failure = error.code
                record(obj, "disconnect_failed")
            outcome = "provider_disconnected"
        if failure is None:
            obj.encrypted_credentials = ""
            obj.access_expires_at = None
            obj.status = "disconnected"
            obj.save(
                update_fields=[
                    "encrypted_credentials",
                    "access_expires_at",
                    "status",
                    "updated_at",
                ]
            )
            record(obj, outcome)
    if failure:
        raise OAuthError(failure)
    return outcome


def status(user, org_id, provider):
    with authority(user, org_id, provider) as org_id:
        obj = ProviderConnection.objects.filter(
            organization_id=org_id, connected_by_id=user.id, provider=provider
        ).first()
        if obj is None:
            return {"status": "Disconnected", "events": []}
        return {
            "status": obj.get_status_display(),
            "events": list(
                ProviderEvent.objects.filter(connection=obj).order_by("-created_at")[:8]
            ),
            "access_expires_at": obj.access_expires_at,
        }


@sensitive_variables()
def forget_failed_connection(user, org_id, provider):
    """Explicit local recovery; never represents provider consent as revoked."""
    require(provider == "xero", "unsupported_operation")
    with authority(user, org_id, provider) as org_id:
        obj = owned(user, org_id, provider)
        require(obj.status in ("revoking", "reconnect"), "recovery_not_required")
        obj.generation += 1
        ProviderAttempt.objects.filter(connection=obj, consumed_at__isnull=True).update(
            consumed_at=timezone.now(), encrypted_verifier=""
        )
        obj.encrypted_credentials = ""
        obj.access_expires_at = None
        obj.status = "disconnected"
        obj.save(
            update_fields=[
                "generation",
                "encrypted_credentials",
                "access_expires_at",
                "status",
                "updated_at",
            ]
        )
        record(obj, "local_disconnected_consent_unverified")
