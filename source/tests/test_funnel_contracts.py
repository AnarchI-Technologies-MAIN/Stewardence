from dataclasses import replace, FrozenInstanceError
import pytest
from apps.funnels.contracts import REGISTRY, CAPABILITIES, admission, audience_choice, validate_event, scenario_sample, BROWSER_EVENTS


def test_registry_has_four_distinct_immutable_draft_families():
    assert len(REGISTRY) == 4
    assert len({b.sample_id for b in REGISTRY.values()}) == 4
    with pytest.raises(TypeError):
        REGISTRY["injected"] = next(iter(REGISTRY.values()))
    bundle = next(iter(REGISTRY.values()))
    with pytest.raises(FrozenInstanceError):
        bundle.publication_state = "approved"
    for bundle in REGISTRY.values():
        assert not admission(bundle, qualified_capabilities=CAPABILITIES, approved_digests=(bundle.digest,))


def test_publication_requires_exact_approval_and_every_qualified_capability():
    bundle = replace(REGISTRY["tool-exposure"], publication_state="approved")
    assert admission(bundle, qualified_capabilities=CAPABILITIES, approved_digests=(bundle.digest,))
    assert not admission(bundle, qualified_capabilities=(), approved_digests=(bundle.digest,))
    assert not admission(bundle, qualified_capabilities=CAPABILITIES, approved_digests=())
    edited = replace(bundle, takeaway="Changed copy")
    assert not admission(edited, qualified_capabilities=CAPABILITIES, approved_digests=(bundle.digest,))
    unknown = replace(bundle, capabilities=("enterprise.listener",))
    assert not admission(unknown, qualified_capabilities=unknown.capabilities, approved_digests=(unknown.digest,))


def test_translation_and_offer_changes_require_separate_contracts():
    for changes in ({"locale":"es"},{"offer_identity":"enterprise.founder"}):
        bundle = replace(REGISTRY["tool-exposure"], publication_state="approved", **changes)
        assert not admission(bundle, qualified_capabilities=CAPABILITIES, approved_digests=(bundle.digest,))


def test_visitor_context_wins_without_becoming_authority():
    assert audience_choice("freelancer", "accounting") == "freelancer"
    assert audience_choice("invalid", "accounting") == "accounting"
    assert audience_choice("invalid", "invalid") == "small_business"


def test_closed_engagement_schema_rejects_answers_payment_and_unknown_events():
    event = dict(event="page_view", scenario="tool-exposure", bundle_version="2", locale="en", audience="accounting", consent=True)
    assert validate_event(event) == event
    for changed in ({**event,"answers":"private"},{**event,"event":"payment_success"},{**event,"bundle_version":"1"},{**event,"locale":"es"},{**event,"consent":False},{**event,"consent":1}):
        with pytest.raises(ValueError):
            validate_event(changed)


@pytest.mark.parametrize("event_name", ["checkout_started","signup_completed","payment_completed","report_delivered","renewal_paid"])
def test_downstream_outcomes_cannot_be_forged_as_browser_engagement(event_name):
    with pytest.raises(ValueError):
        validate_event(dict(event=event_name,scenario="tool-exposure",bundle_version="2",locale="en",audience="accounting",consent=True))


def test_four_distinct_samples_and_three_audiences_bound_to_digest():
    samples=[scenario_sample(bundle) for bundle in REGISTRY.values()]
    assert len({str(sample["steps"]) for sample in samples})==4
    for bundle,sample in zip(REGISTRY.values(),samples):
        assert sample["synthetic"] is True
        assert set(sample["audiences"])=={"accounting","freelancer","small_business"}
        assert len(set(sample["audiences"].values()))==3
        assert bundle.payload()["sample"]==sample
        sample["steps"][0]["choices"][0]["label"]="tampered returned copy"
        assert bundle.payload()["sample"]!=sample


@pytest.mark.parametrize("event_name", BROWSER_EVENTS)
def test_only_consented_minimal_engagement_vocabulary(event_name):
    event=dict(event=event_name,scenario="tool-exposure",bundle_version="2",locale="en",audience="accounting",consent=True)
    assert validate_event(event)==event
