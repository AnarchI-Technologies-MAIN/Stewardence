from __future__ import annotations

from uuid import UUID, uuid5

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Product, ProductIdentifier, Vendor

CATALOG_NAMESPACE = UUID("bc8f71ad-eaa1-43fc-8305-cdb315a4db8d")

CATALOG_PRODUCTS = (
    ("OpenAI", "ChatGPT", "General assistant", "chatgpt.com"),
    ("Anthropic", "Claude", "General assistant", "claude.ai"),
    ("Google", "Gemini", "General assistant", "gemini.google.com"),
    ("Microsoft", "Microsoft 365 Copilot", "Productivity", "m365.cloud.microsoft"),
    ("GitHub", "GitHub Copilot", "Software development", "github.com"),
    ("Intuit", "QuickBooks Online", "Accounting", "quickbooks.intuit.com"),
    ("Xero", "Xero", "Accounting", "xero.com"),
    ("Sage", "Sage Intacct", "Accounting", "sage.com"),
    ("FreshBooks", "FreshBooks", "Accounting", "freshbooks.com"),
    ("Dext", "Dext Prepare", "Bookkeeping", "dext.com"),
    ("BILL", "BILL", "Accounts payable", "bill.com"),
    ("Gusto", "Gusto", "Payroll", "gusto.com"),
    ("TaxDome", "TaxDome", "Practice management", "taxdome.com"),
    ("Karbon", "Karbon", "Practice management", "karbonhq.com"),
    ("Keeper", "Keeper", "Bookkeeping", "keeper.app"),
    ("Ramp", "Ramp", "Expense management", "ramp.com"),
    ("Brex", "Brex", "Expense management", "brex.com"),
    ("Expensify", "Expensify", "Expense management", "expensify.com"),
    ("HubSpot", "HubSpot", "Customer management", "hubspot.com"),
    ("Salesforce", "Salesforce", "Customer management", "salesforce.com"),
    ("Intercom", "Intercom", "Customer support", "intercom.com"),
    ("Zendesk", "Zendesk", "Customer support", "zendesk.com"),
    ("Mailchimp", "Mailchimp", "Marketing", "mailchimp.com"),
    ("Canva", "Canva", "Design", "canva.com"),
    ("Adobe", "Adobe Acrobat AI Assistant", "Documents", "adobe.com"),
    ("Dropbox", "Dropbox", "File storage", "dropbox.com"),
    ("DocuSign", "DocuSign", "Electronic signature", "docusign.com"),
    ("Notion", "Notion AI", "Knowledge management", "notion.so"),
    ("Slack", "Slack", "Communication", "slack.com"),
    ("Zoom", "Zoom AI Companion", "Communication", "zoom.us"),
    ("Grammarly", "Grammarly", "Writing", "grammarly.com"),
    ("Zapier", "Zapier", "Automation", "zapier.com"),
    ("Asana", "Asana", "Project management", "asana.com"),
    ("monday.com", "monday.com", "Project management", "monday.com"),
    ("Atlassian", "Jira", "Project management", "atlassian.com"),
    ("Linear", "Linear", "Project management", "linear.app"),
    ("Calendly", "Calendly", "Scheduling", "calendly.com"),
    ("Otter.ai", "Otter", "Meeting notes", "otter.ai"),
    ("Fireflies.ai", "Fireflies.ai", "Meeting notes", "fireflies.ai"),
    ("Fathom", "Fathom", "Meeting notes", "fathom.video"),
)


class Command(BaseCommand):
    help = "Seed the bounded version-one product catalog as reviewable metadata."

    @transaction.atomic
    def handle(self, *args, **options):
        for vendor_name, product_name, category, domain in CATALOG_PRODUCTS:
            vendor_id = uuid5(CATALOG_NAMESPACE, f"vendor:{vendor_name}")
            product_id = uuid5(
                CATALOG_NAMESPACE,
                f"product:{vendor_name}:{product_name}:1",
            )
            vendor, _created = Vendor.objects.get_or_create(
                id=vendor_id,
                defaults={
                    "name": vendor_name,
                    "website_domain": domain,
                    "status": Vendor.Status.UNVERIFIED,
                },
            )
            product, _created = Product.objects.get_or_create(
                id=product_id,
                defaults={
                    "vendor": vendor,
                    "name": product_name,
                    "category": category,
                    "is_ai_product": True,
                    "catalog_version": 1,
                },
            )
            ProductIdentifier.objects.get_or_create(
                product=product,
                identifier_type=ProductIdentifier.Type.PRODUCT_NAME,
                canonical_value=product_name.casefold(),
                provider_scope=None,
                defaults={
                    "raw_value": product_name,
                    "verified": True,
                },
            )
            ProductIdentifier.objects.get_or_create(
                product=product,
                identifier_type=ProductIdentifier.Type.HOSTNAME,
                canonical_value=domain,
                provider_scope=None,
                defaults={
                    "raw_value": domain,
                    "verified": False,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog contains {len(CATALOG_PRODUCTS)} bounded product records."
            )
        )
