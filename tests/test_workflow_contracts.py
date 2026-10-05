from datetime import datetime, UTC
from uuid import uuid4
import pytest
from apps.jobs.contracts import WorkflowRequest, Operation, BranchProfile, validate_branch_settings, logical_evidence_directory


def test_branch_profiles_do_not_reinterpret_each_others_settings():
    assert validate_branch_settings("business.v1", {"name":"Chicago", "jurisdiction":"US-IL"})["profile"] == "business.v1"
    assert validate_branch_settings("development.v1", {"name":"main", "repository_ref":"firm/app", "environment":"production"})["profile"] == "development.v1"
    with pytest.raises(ValueError):
        validate_branch_settings("business.v1", {"name":"main", "repository_ref":"firm/app"})
    with pytest.raises(ValueError):
        validate_branch_settings("other", {"name":"undefined"})
    with pytest.raises(ValueError):
        validate_branch_settings("development.v1", {"name":"main", "repository_ref":"https://token@repo"})


def test_workflow_hash_is_receipt_order_independent_and_tenant_bound():
    organization = uuid4()
    receipts = (uuid4(), uuid4())
    def request(org, ids):
        return WorkflowRequest(org, Operation.REPORT, ids, datetime(2026,10,3,tzinfo=UTC), BranchProfile.BUSINESS)
    assert request(organization, receipts).input_sha256 == request(organization, receipts[::-1]).input_sha256
    assert request(organization, receipts).input_sha256 != request(uuid4(), receipts).input_sha256
    with pytest.raises(ValueError):
        request(organization, ())
    with pytest.raises(ValueError):
        request(organization, (receipts[0], receipts[0]))


def test_directory_taxonomy_rejects_arbitrary_paths():
    assert "/evidence/agents/" in logical_evidence_directory(uuid4(), "agents", uuid4())
    with pytest.raises(ValueError):
        logical_evidence_directory(uuid4(), "../../secrets", uuid4())


@pytest.mark.parametrize("time", [None, "2026-10-03", 42, datetime(2026,10,3)])
def test_malformed_workflow_time_is_rejected_as_input(time):
    with pytest.raises(ValueError):
        WorkflowRequest(uuid4(), Operation.HEALTH, (), time, BranchProfile.BUSINESS)


@pytest.mark.parametrize("reference", ["/etc/passwd", "../../etc/passwd", "org/../repo", "org//repo"])
def test_repository_reference_cannot_be_reused_as_a_path(reference):
    with pytest.raises(ValueError):
        validate_branch_settings("development.v1", {"name":"main", "repository_ref":reference})


@pytest.mark.parametrize("name", ["   ", "trusted\u202eevil", "bad\x7fname"])
def test_branch_identity_rejects_invisible_or_spoofing_controls(name):
    with pytest.raises(ValueError):
        validate_branch_settings("business.v1", {"name":name})
