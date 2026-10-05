from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    class Industry(models.TextChoices):
        ACCOUNTING_BOOKKEEPING = "accounting_bookkeeping", "Accounting & bookkeeping"
        LEGAL = "legal", "Legal"
        HEALTHCARE = "healthcare", "Healthcare"
        CONSTRUCTION = "construction", "Construction"
        AGENCY = "agency", "Agency"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    industry = models.CharField(max_length=32, choices=Industry, default=Industry.OTHER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self) -> str:
        return self.name


class OrganizationMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Administrator"
        ASSESSOR = "assessor", "Assessor"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    role = models.CharField(max_length=16, choices=Role)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="unique_organization_member",
            )
        ]
        indexes = [
            models.Index(fields=("user", "organization"), name="member_user_org_idx"),
        ]
        ordering = ("organization__name", "user__email")

    def __str__(self) -> str:
        return (
            f"{self.user.email} — {self.organization.name} ({self.get_role_display()})"
        )
