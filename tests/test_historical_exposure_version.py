"""Historical pack semantics cannot follow a changed current entrypoint."""

from uuid import uuid4

import pytest
import rfc8785

from agentledger.tenancy.context import tenant_transaction
from apps.reviews import exposure
from apps.reviews.exposure_v1 import review_record as permanent_v1
from tests.test_review_pack_lifecycle import claimed, handler, request
from tests.test_review_pack_lifecycle import enabled as enabled
from tests.test_review_pack_lifecycle import pack_context as pack_context

__all__ = ["enabled", "pack_context"]


@pytest.mark.parametrize(
    "schema", [None, "", "stewardence.review_pack.v1", "stewardence.review_pack.v3"]
)
def test_unregistered_historical_schema_is_not_reinterpreted(schema):
    with pytest.raises(ValueError, match="Unsupported historical"):
        exposure.historical_review_record({"id": str(uuid4())}, schema)


def test_current_alias_successor_cannot_change_historical_v2(monkeypatch):
    record = {"id": str(uuid4())}
    expected = permanent_v1(record)
    monkeypatch.setattr(exposure, "VERSION", "core.exposure.declarations.v2")
    monkeypatch.setattr(
        exposure, "review_record", lambda _: {"schema": exposure.VERSION}
    )
    assert exposure.review_record(record)["schema"] == "core.exposure.declarations.v2"
    assert (
        exposure.historical_review_record(record, "stewardence.review_pack.v2")
        == expected
    )


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_actual_worker_context_keeps_permanent_exposure_version(
    pack_context, enabled, tmp_path, monkeypatch
):
    _, org, snapshot, pack = pack_context
    request(pack_context)
    job = claimed(pack_context)

    def forbidden_current(_):
        raise AssertionError("Historical rendering used the current exposure alias")

    monkeypatch.setattr(exposure, "review_record", forbidden_current)
    with tenant_transaction(org.id, using="worker_runtime"):
        context = handler(tmp_path).prepare(job).report_context
    assert context["review_pack"]["manifest"] == pack.manifest
    assert rfc8785.dumps(
        [entry["review"] for entry in context["review_pack"]["exposure_reviews"]]
    ) == rfc8785.dumps(
        [permanent_v1(record) for record in snapshot.input_payload["inventory"]]
    )
