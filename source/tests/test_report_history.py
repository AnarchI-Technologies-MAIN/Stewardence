import pytest
from django.urls import reverse
from apps.reports.services import create_report
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def test_history_requires_login(client):
    response = client.get(reverse("reports:history"))
    assert response.status_code == 302
    assert "login" in response.url


def test_history_empty_and_current_firm_only(client, report_context):
    user, organization, _, _, snapshot = report_context
    url = reverse("reports:history")
    assert b"No reports yet" in client.get(url).content
    report = create_report(organization_id=organization.id,
        assessment_snapshot_id=snapshot.id, created_by_id=user.id)
    response = client.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert report.report_identifier.encode() in response.content
    assert b"PDF not stored yet" in response.content
    # Changing the active firm never grants membership or reveals the old firm.
    other = Organization.objects.create(name="Unrelated firm")
    session = client.session
    session["active_organization_id"] = str(other.id)
    session.save()
    denied = client.get(url)
    assert report.report_identifier.encode() not in denied.content
    assert denied.status_code in (302, 403, 404)


def test_history_is_read_only_and_handles_invalid_page(client, report_context):
    assert client.post(reverse("reports:history")).status_code == 405
    assert client.get(reverse("reports:history"), {"page":"invalid"}).status_code == 200
