from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization

DEMO_ITEMS = (
    {
        "display_name": "ChatGPT",
        "vendor_name": "OpenAI",
        "department": "Advisory",
        "business_owner": "Client advisory manager",
        "business_purpose": "Draft internal outlines for staff-reviewed client work",
        "monthly_cost_cents": 15000,
        "user_count": 5,
        "seat_count": 5,
        "connected_systems": [],
        "data_categories": ["internal_business_information"],
        "permissions": ["read"],
        "capabilities": ["content_generation"],
        "autonomy_level": InventoryItem.Autonomy.SUGGESTS,
        "human_approval": True,
    },
    {
        "display_name": "Microsoft Copilot",
        "vendor_name": "Microsoft",
        "department": "Operations",
        "business_owner": "Operations manager",
        "business_purpose": "Summarize internal meetings and draft office documents",
        "monthly_cost_cents": 24000,
        "user_count": 8,
        "seat_count": 8,
        "connected_systems": ["email", "document_storage"],
        "data_categories": ["internal_business_information"],
        "permissions": ["read"],
        "capabilities": ["content_generation", "data_analysis"],
        "autonomy_level": InventoryItem.Autonomy.SUGGESTS,
        "human_approval": True,
    },
    {
        "display_name": "Google Gemini",
        "vendor_name": "Google",
        "department": "Client service",
        "business_owner": "Client service lead",
        "business_purpose": (
            "Analyze de-identified client-service notes for staff review"
        ),
        "monthly_cost_cents": 10000,
        "user_count": 4,
        "seat_count": 4,
        "connected_systems": [],
        "data_categories": ["client_information"],
        "permissions": ["read"],
        "capabilities": ["data_analysis"],
        "autonomy_level": InventoryItem.Autonomy.SUGGESTS,
        "human_approval": True,
    },
    {
        "display_name": "QuickBooks",
        "vendor_name": "Intuit",
        "department": "Accounting",
        "business_owner": "Controller",
        "business_purpose": (
            "Maintain books and prepare staff-reviewed financial records"
        ),
        "monthly_cost_cents": 8000,
        "user_count": 8,
        "seat_count": 8,
        "connected_systems": ["accounting", "banking"],
        "data_categories": ["financial_records", "banking_information"],
        "permissions": ["read", "write"],
        "capabilities": ["data_analysis", "record_modification"],
        "autonomy_level": InventoryItem.Autonomy.AFTER_APPROVAL,
        "human_approval": True,
    },
    {
        "display_name": "Grammarly",
        "vendor_name": "Grammarly",
        "department": "Administration",
        "business_owner": "Office manager",
        "business_purpose": "Improve public-facing office communications before review",
        "monthly_cost_cents": 3600,
        "user_count": 3,
        "seat_count": 3,
        "connected_systems": [],
        "data_categories": ["public_information"],
        "permissions": [],
        "capabilities": ["content_generation"],
        "autonomy_level": InventoryItem.Autonomy.SUGGESTS,
        "human_approval": True,
    },
    {
        "display_name": "Canva",
        "vendor_name": "Canva",
        "department": "Marketing",
        "business_owner": "Marketing coordinator",
        "business_purpose": "Create staff-reviewed educational graphics",
        "monthly_cost_cents": 4500,
        "user_count": 3,
        "seat_count": 3,
        "connected_systems": [],
        "data_categories": ["public_information"],
        "permissions": [],
        "capabilities": ["content_generation"],
        "autonomy_level": InventoryItem.Autonomy.SUGGESTS,
        "human_approval": True,
    },
    {
        "display_name": "Otter",
        "vendor_name": "Otter.ai",
        "department": "Operations",
        "business_owner": "Operations manager",
        "business_purpose": "Prepare internal meeting notes for participant review",
        "monthly_cost_cents": 5000,
        "user_count": 5,
        "seat_count": 5,
        "connected_systems": ["email"],
        "data_categories": ["internal_business_information"],
        "permissions": ["read"],
        "capabilities": ["content_generation"],
        "autonomy_level": InventoryItem.Autonomy.SUGGESTS,
        "human_approval": True,
    },
    {
        "display_name": "Zapier",
        "vendor_name": "Zapier",
        "department": "Operations",
        "business_owner": "Automation lead",
        "business_purpose": "Route approved internal tasks between office systems",
        "monthly_cost_cents": 12000,
        "user_count": 2,
        "seat_count": 2,
        "connected_systems": ["email", "document_storage"],
        "data_categories": ["internal_business_information"],
        "permissions": ["read", "write"],
        "capabilities": ["data_analysis"],
        "autonomy_level": InventoryItem.Autonomy.LIMITED_AUTOMATIC,
        "human_approval": True,
    },
    {
        "display_name": "LedgerWise AI Bookkeeping Assistant",
        "vendor_name": "LedgerWise",
        "department": "Payroll",
        "business_owner": "Payroll manager",
        "business_purpose": "Prepare payroll transfers for review",
        "monthly_cost_cents": 30000,
        "user_count": 4,
        "seat_count": 4,
        "connected_systems": ["payroll", "banking"],
        "data_categories": ["payroll", "banking_information"],
        "permissions": ["read", "write", "transmit"],
        "capabilities": ["external_transfer", "financial_transaction"],
        "autonomy_level": InventoryItem.Autonomy.SIGNIFICANT_AUTOMATIC,
        "human_approval": False,
    },
    {
        "display_name": "Unknown AI Tool",
        "vendor_name": "Unknown vendor",
        "department": "Bookkeeping",
        "business_owner": "Review unassigned",
        "business_purpose": "Purpose and access require confirmation",
        "monthly_cost_cents": 0,
        "user_count": 1,
        "seat_count": 0,
        "connected_systems": [],
        "data_categories": [],
        "permissions": [],
        "capabilities": [],
        "autonomy_level": InventoryItem.Autonomy.NONE,
        "human_approval": True,
    },
)


def create_demo_inventory(organization: Organization) -> list[InventoryItem]:
    if InventoryItem.objects.filter(organization=organization).exists():
        raise CommandError("Demo inventory requires an organization with no items")

    return InventoryItem.objects.bulk_create(
        [
            InventoryItem(
                organization=organization,
                status=InventoryItem.Status.ACTIVE,
                source_type=InventoryItem.SourceType.MANUAL,
                **values,
            )
            for values in DEMO_ITEMS
        ]
    )


class Command(BaseCommand):
    help = "Create the bounded ten-item bookkeeping demonstration inventory."

    def add_arguments(self, parser):
        parser.add_argument("organization_id", type=str)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            organization_id = UUID(options["organization_id"])
        except (TypeError, ValueError) as error:
            raise CommandError("organization_id must be a UUID") from error

        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist as error:
            raise CommandError("The organization does not exist") from error

        create_demo_inventory(organization)
        self.stdout.write(
            self.style.SUCCESS("Created 10 demonstration inventory items.")
        )
