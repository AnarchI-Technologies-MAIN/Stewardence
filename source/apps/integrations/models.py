import uuid

from django.conf import settings
from django.db import models


class QuickBooksConnection(models.Model):
    class Status(models.TextChoices):
        DISCONNECTED = "disconnected", "Disconnected"
        CONNECTED = "connected", "Connected"
        RECONNECT = "reconnect", "Reconnect required"
        REVOKING = "revoking", "Disconnect pending"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
    )
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    # Sandbox only: production gets a separate qualification and configuration gate.
    environment = models.CharField(max_length=16, default="sandbox", editable=False)
    status = models.CharField(
        max_length=16, choices=Status, default=Status.DISCONNECTED
    )
    encrypted_credentials = models.TextField(blank=True)
    access_expires_at = models.DateTimeField(null=True)
    refresh_expires_at = models.DateTimeField(null=True)
    generation = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.id)


class QuickBooksAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(QuickBooksConnection, on_delete=models.CASCADE)
    state_hash = models.CharField(max_length=64, unique=True)
    session_hash = models.CharField(max_length=64)
    generation = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.id)


class QuickBooksEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(QuickBooksConnection, on_delete=models.PROTECT)
    kind = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.id)


class ProviderConnection(models.Model):
    """A separate owner-preview connection; worker credentials are not exposed."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT)
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    provider = models.CharField(max_length=16, choices=[('microsoft', 'Microsoft'), ('xero', 'Xero')])
    environment = models.CharField(max_length=16, default='owner_preview', editable=False)
    status = models.CharField(max_length=16, choices=QuickBooksConnection.Status,
                              default=QuickBooksConnection.Status.DISCONNECTED)
    encrypted_credentials = models.TextField(blank=True)
    access_expires_at = models.DateTimeField(null=True)
    generation = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'provider'], name='one_provider_per_workspace')]

    def __str__(self):
        return str(self.id)


class ProviderAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(ProviderConnection, on_delete=models.CASCADE)
    state_hash = models.CharField(max_length=64, unique=True)
    session_hash = models.CharField(max_length=64)
    generation = models.PositiveIntegerField()
    encrypted_verifier = models.TextField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.id)


class ProviderEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(ProviderConnection, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.id)
