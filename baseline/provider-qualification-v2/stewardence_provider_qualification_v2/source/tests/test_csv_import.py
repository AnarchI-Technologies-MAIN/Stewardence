from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.imports.models import ImportBatch, ImportRow
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from tests.conftest import grant_core_entitlement

pytestmark = pytest.mark.django_db


CSV_HEADER = (
    "display_name,vendor_name,business_owner,department,user_count,"
    "business_purpose,monthly_cost,seat_count,autonomy_level,"
    "human_approval,status\n"
)


@pytest.fixture
def import_context(client):
    user = get_user_model().objects.create_user("csv@example.com")
    organization = Organization.objects.create(name="CSV Firm")
    OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )
    grant_core_entitlement(user, organization)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    return user, organization


def upload_file(text: str, name: str = "software.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def valid_csv_row(name="Ledger Helper", vendor="Example Vendor", cost="49.95"):
    return (
        f'{name},{vendor},Jordan,Bookkeeping,7,"Monthly close",{cost},5,2,yes,active\n'
    )


def corrected_payload(row):
    prefix = f"row-{row.row_number}"
    data = row.data
    return {
        f"{prefix}-display_name": data["display_name"],
        f"{prefix}-vendor_name": data["vendor_name"],
        f"{prefix}-business_owner": data["business_owner"],
        f"{prefix}-department": data["department"],
        f"{prefix}-user_count": str(data["user_count"]),
        f"{prefix}-business_purpose": data["business_purpose"],
        f"{prefix}-monthly_cost": f"{data['monthly_cost_cents'] / 100:.2f}",
        f"{prefix}-seat_count": str(data["seat_count"]),
        f"{prefix}-autonomy_level": str(data["autonomy_level"]),
        f"{prefix}-human_approval": "yes" if data["human_approval"] else "no",
        f"{prefix}-status": data["status"],
    }


def stage_csv(client, text):
    response = client.post(
        reverse("imports:upload"),
        {"spreadsheet": upload_file(text)},
    )
    assert response.status_code == 302
    return ImportBatch.objects.get()


def test_valid_csv_uses_all_three_steps_and_only_final_post_writes_inventory(
    client, import_context
):
    _user, organization = import_context
    upload_page = client.get(reverse("imports:upload"))
    assert b"Step 1 of 3" in upload_page.content

    batch = stage_csv(client, CSV_HEADER + valid_csv_row())
    assert batch.organization == organization
    assert InventoryItem.objects.count() == 0
    review = client.get(reverse("imports:review", args=(batch.id,)))
    assert b"Step 2 of 3" in review.content

    row = batch.rows.get()
    proceed = client.post(
        reverse("imports:review", args=(batch.id,)),
        corrected_payload(row),
    )
    assert proceed.status_code == 302
    final = client.get(proceed.url)
    assert b"Step 3 of 3" in final.content
    assert b"$49.95" in final.content
    assert InventoryItem.objects.count() == 0

    confirm_url = reverse("imports:confirm", args=(batch.id,))
    assert client.get(confirm_url).status_code == 405
    assert client.post(confirm_url).status_code == 302
    item = InventoryItem.objects.get()
    assert item.organization == organization
    assert item.source_type == InventoryItem.SourceType.CSV
    assert item.monthly_cost_cents == 4995
    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.IMPORTED
    assert batch.imported_count == 1
    assert batch.rows.count() == 0
    events = list(AuditEvent.objects.order_by("occurred_at", "id"))
    assert [event.event_type for event in events] == [
        "inventory.created",
        "reconciliation.accepted",
    ]
    assert events[0].entity_id == item.id
    assert events[0].data == {
        "import_batch_id": str(batch.id),
        "source_type": "csv",
    }
    assert events[1].entity_id == batch.id
    assert events[1].data == {"imported_count": "1"}


def test_invalid_row_uses_row_specific_business_language(client, import_context):
    batch = stage_csv(client, CSV_HEADER + valid_csv_row(name="", cost=""))
    row = batch.rows.get()

    assert batch.status == ImportBatch.Status.REVIEWING
    assert row.row_number == 2
    assert "Enter the software or AI name." in row.errors
    assert "Enter the monthly cost in dollars, such as 49.00." in row.errors
    response = client.get(reverse("imports:review", args=(batch.id,)))
    assert b"Spreadsheet row 2" in response.content
    assert b"Enter the software or AI name." in response.content
    assert InventoryItem.objects.count() == 0


def test_user_can_correct_an_invalid_row_before_final_approval(client, import_context):
    batch = stage_csv(client, CSV_HEADER + valid_csv_row(name="", cost=""))
    row = batch.rows.get()
    payload = corrected_payload(row)
    prefix = f"row-{row.row_number}"
    payload[f"{prefix}-display_name"] = "Corrected Assistant"
    payload[f"{prefix}-monthly_cost"] = "12.34"

    response = client.post(reverse("imports:review", args=(batch.id,)), payload)

    assert response.status_code == 302
    assert response.url == reverse("imports:final", args=(batch.id,))
    batch.refresh_from_db()
    row.refresh_from_db()
    assert batch.status == ImportBatch.Status.READY
    assert row.errors == []
    assert row.data["monthly_cost_cents"] == 1234
    assert InventoryItem.objects.count() == 0


def test_missing_required_header_creates_no_staging_or_inventory(
    client, import_context
):
    response = client.post(
        reverse("imports:upload"),
        {"spreadsheet": upload_file("display_name,vendor_name\nTool,Vendor\n")},
    )

    assert response.status_code == 200
    assert b"missing required columns: monthly_cost" in response.content
    assert ImportBatch.objects.count() == 0
    assert InventoryItem.objects.count() == 0


def test_duplicate_rows_require_correction(client, import_context):
    text = (
        CSV_HEADER
        + valid_csv_row()
        + valid_csv_row(
            name="ledger helper",
            vendor="EXAMPLE VENDOR",
        )
    )
    batch = stage_csv(client, text)

    assert batch.status == ImportBatch.Status.REVIEWING
    assert "appear more than once" in batch.rows.get(row_number=3).errors[0]
    assert InventoryItem.objects.count() == 0


def test_cancel_is_post_only_and_removes_staging_without_inventory(
    client, import_context
):
    batch = stage_csv(client, CSV_HEADER + valid_csv_row())
    cancel_url = reverse("imports:cancel", args=(batch.id,))

    assert client.get(cancel_url).status_code == 405
    assert client.post(cancel_url).status_code == 302
    assert ImportBatch.objects.count() == 0
    assert ImportRow.objects.count() == 0
    assert InventoryItem.objects.count() == 0


def test_one_hundred_rows_stage_and_import_atomically(client, import_context):
    rows = "".join(
        valid_csv_row(name=f"Software {number}", vendor=f"Vendor {number}")
        for number in range(1, 101)
    )
    batch = stage_csv(client, CSV_HEADER + rows)

    assert batch.row_count == 100
    assert batch.rows.count() == 100
    assert InventoryItem.objects.count() == 0
    assert client.get(reverse("imports:final", args=(batch.id,))).status_code == 200
    response = client.post(reverse("imports:confirm", args=(batch.id,)))
    assert response.status_code == 302
    assert InventoryItem.objects.count() == 100


def test_more_than_one_hundred_rows_are_rejected_without_staging(
    client, import_context
):
    buffer = StringIO()
    buffer.write(CSV_HEADER)
    for number in range(101):
        buffer.write(valid_csv_row(name=f"Software {number}"))

    response = client.post(
        reverse("imports:upload"),
        {"spreadsheet": upload_file(buffer.getvalue())},
    )

    assert response.status_code == 200
    assert b"no more than 100" in response.content
    assert ImportBatch.objects.count() == 0
    assert InventoryItem.objects.count() == 0


def test_final_database_failure_rolls_back_without_partial_inventory(
    client, import_context
):
    batch = stage_csv(client, CSV_HEADER + valid_csv_row())
    confirm_url = reverse("imports:confirm", args=(batch.id,))

    with (
        patch(
            "apps.imports.views.InventoryItem.objects.bulk_create",
            side_effect=RuntimeError("simulated database failure"),
        ),
        pytest.raises(RuntimeError, match="simulated database failure"),
    ):
        client.post(confirm_url)

    batch.refresh_from_db()
    assert batch.status == ImportBatch.Status.READY
    assert batch.imported_count == 0
    assert batch.rows.count() == 1
    assert InventoryItem.objects.count() == 0


def test_viewer_cannot_start_csv_import(client, import_context):
    user, organization = import_context
    membership = OrganizationMember.objects.get(user=user, organization=organization)
    membership.role = OrganizationMember.Role.VIEWER
    membership.save(update_fields=("role",))

    response = client.post(
        reverse("imports:upload"),
        {"spreadsheet": upload_file(CSV_HEADER + valid_csv_row())},
    )

    assert response.status_code == 403
    assert ImportBatch.objects.count() == 0
