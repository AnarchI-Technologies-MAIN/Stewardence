from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import Organization


class AuditEvent(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    occurred_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )
    actor_user_id = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
    )
    event_type = models.CharField(
        max_length=160,
        editable=False,
    )
    entity_type = models.CharField(
        max_length=160,
        editable=False,
    )
    entity_id = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
    )
    data = models.JSONField(
        default=dict,
        editable=False,
    )

    node_hash = models.CharField(  # noqa: DJ001
        max_length=64,
        null=True,
        blank=True,
        editable=False,
    )
    batch_block = models.ForeignKey(
        "AuditMerkleBlock",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
        editable=False,
    )
    batch_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        db_table = "audit_events"
        ordering = ("occurred_at", "id")
        indexes = [
            models.Index(
                fields=("organization", "occurred_at", "id"),
                name="audit_event_order_idx",
            ),
            models.Index(
                fields=("organization", "batch_block", "occurred_at", "id"),
                name="audit_unsealed_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        node_hash__isnull=True,
                        batch_block__isnull=True,
                        batch_position__isnull=True,
                    )
                    | Q(
                        node_hash__isnull=False,
                        batch_block__isnull=False,
                        batch_position__isnull=False,
                    )
                ),
                name="audit_event_seal_state_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} {self.id}"


class AuditChainHead(models.Model):
    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        primary_key=True,
        related_name="audit_chain_head",
    )
    last_block_sequence = models.BigIntegerField(
        default=0,
    )
    last_block_hash = models.CharField(  # noqa: DJ001
        max_length=64,
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = "audit_chain_heads"
        constraints = [
            models.CheckConstraint(
                condition=Q(last_block_sequence__gte=0),
                name="audit_chain_sequence_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        last_block_sequence=0,
                        last_block_hash__isnull=True,
                    )
                    | Q(
                        last_block_sequence__gt=0,
                        last_block_hash__isnull=False,
                    )
                ),
                name="audit_chain_hash_matches_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} sequence={self.last_block_sequence}"


class AuditMerkleBlock(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="audit_merkle_blocks",
    )
    block_sequence = models.BigIntegerField()
    algorithm_version = models.CharField(
        max_length=64,
    )
    canonicalization_version = models.CharField(
        max_length=64,
    )
    event_count = models.PositiveIntegerField()
    first_event_id = models.UUIDField()
    last_event_id = models.UUIDField()
    merkle_root = models.CharField(
        max_length=64,
    )
    previous_block_hash = models.CharField(  # noqa: DJ001
        max_length=64,
        null=True,
        blank=True,
    )
    block_hash = models.CharField(
        max_length=64,
    )
    sealed_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )

    class Meta:
        db_table = "audit_merkle_blocks"
        ordering = ("organization_id", "block_sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "block_sequence"),
                name="audit_block_org_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(block_sequence__gte=1),
                name="audit_block_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(event_count__gte=1),
                name="audit_block_event_count_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "block_sequence"),
                name="audit_block_chain_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id} block={self.block_sequence}"
