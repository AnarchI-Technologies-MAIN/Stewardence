from dataclasses import dataclass, asdict
import hashlib
import json
from types import MappingProxyType

AUDIENCES = ("accounting", "freelancer", "small_business")
CAPABILITIES = ("core.tool_record.v1", "core.exposure_review.v1", "core.decision_desk.v1", "core.evidence_compare.v1", "core.evidence_pack.v1")
BROWSER_EVENTS = ("page_view", "scenario_started", "scenario_completed")
AUDIENCE_CONTEXT = MappingProxyType({
    "accounting": "Example: a bookkeeping workflow preparing a client review. Separate declared client-data handling from dated permission and approval evidence. This preview does not assess compliance.",
    "freelancer": "Example: a consultant preparing a client deliverable. Distinguish your workflow ownership from the client's account authority and approval responsibility.",
    "small_business": "Example: a team preparing a customer handoff. Name the accountable owner and separate tool presence, declared use and supported account access.",
})
SCENARIO_STEPS = MappingProxyType({
    "tool-exposure": (
        ("What does the synthetic inventory establish?", (("installed", "Installed tool record", "An installation observation establishes presence at its evidence date. Active use, data access and approval remain unknown."), ("declared", "Owner declares a workflow", "A declaration establishes what the owner reports. It does not independently prove permissions or active use."))),
        ("What additional permission evidence exists?", (("unknown", "No permission evidence", "Keep permissions unknown. Ask the accountable owner for dated evidence."), ("grant", "A dated account grant", "The synthetic grant supports that specific account permission at its date. It does not prove every access path or current use."))),
    ),
    "decision-owner": (
        ("Who owns the proposed decision?", (("unknown", "No owner recorded", "An unassigned proposal has no established accountable owner. Name one before treating follow-up as assigned."), ("named", "A named accountable owner", "An owner is recorded for this proposal. That does not authorize provider execution."))),
        ("How is completion recorded?", (("reported", "Customer reports completion", "Record reported completion and its reason. This is not verified resolution."), ("evidence", "A supporting document is attached", "Review what the document supports and its date. Attachment alone does not establish complete resolution."))),
    ),
    "offboarding-evidence": (
        ("What account evidence exists?", (("checklist", "Completed offboarding checklist", "The checklist records a reported process. It does not establish removal of every permission."), ("disabled", "Dated disablement record for one account", "This supports that specific account's recorded disablement at its date. Other accounts and grants remain separate questions."))),
        ("What is known about other grants?", (("unknown", "Other grants are unknown", "Keep residual access unknown. Assign a scoped evidence-gathering proposal."), ("listed", "Some grants are listed", "A partial list is not a comprehensive access inventory. Record its scope and unresolved grants."))),
    ),
    "review-changes": (
        ("Which inputs changed in the synthetic snapshot?", (("same", "Inputs unchanged", "The recorded input versions match. This alone does not establish the rule versions are equal."), ("changed", "Inputs changed", "Show the changed input paths and evidence dates. A changed result alone does not establish causation."))),
        ("Which rule version was used?", (("same", "Same rule version", "A shared rule version permits a bounded comparison, while other differences must still be disclosed."), ("changed", "Rule version changed", "Display the rule-version change separately. If inputs also changed, do not assign the result to a single cause."))),
    ),
})


def scenario_sample(bundle):
    return {"sample_id": bundle.sample_id, "synthetic": True,
        "steps": [{"question": question, "choices": [{"id": key, "label": label, "takeaway": takeaway}
            for key, label, takeaway in choices]} for question, choices in SCENARIO_STEPS[bundle.scenario]],
        "audiences": dict(AUDIENCE_CONTEXT)}


@dataclass(frozen=True)
class ExperienceBundle:
    scenario: str
    version: str
    title: str
    recognition: str
    evidence_gap: str
    takeaway: str
    capabilities: tuple[str, ...]
    sample_id: str
    publication_state: str = "draft"
    locale: str = "en"
    offer_identity: str = "core.standard.monthly.v1"

    def payload(self):
        result = asdict(self)
        result["synthetic"] = True
        result["capability_maturity"] = "proposed_pending_qualification"
        result["sample"] = scenario_sample(self)
        return result

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


REGISTRY = MappingProxyType({b.scenario: b for b in (
    ExperienceBundle("tool-exposure", "2", "What do your AI tools actually touch?",
        "A familiar tool can support several different workflows.",
        "A named or installed tool does not establish data access, active use or approval.",
        "Record purpose and owner, then distinguish declared data from permission evidence and unknowns.",
        (CAPABILITIES[0], CAPABILITIES[1], CAPABILITIES[4]), "sample.exposure.v2"),
    ExperienceBundle("decision-owner", "2", "Who owns the next decision?",
        "A tool owner and the person accountable for follow-up may be different.",
        "A recommendation does not establish approval or completed work.",
        "Name the decision owner, due date and reason. Customer-reported completion is not verified resolution.",
        (CAPABILITIES[0], CAPABILITIES[2], CAPABILITIES[4]), "sample.decision.v2"),
    ExperienceBundle("offboarding-evidence", "2", "Someone left. What can you establish about access?",
        "Offboarding involves accounts, approvals and evidence from different places.",
        "A completed checklist does not prove every relevant permission was removed.",
        "Collect dated account and offboarding evidence; record unresolved questions and accountable proposals.",
        (CAPABILITIES[1], CAPABILITIES[2], CAPABILITIES[4]), "sample.offboarding.v2"),
    ExperienceBundle("review-changes", "2", "What changed since your last review?",
        "A useful review separates changed inputs from changed assessment rules.",
        "A changed finding alone does not identify its cause, especially when inputs and rules both changed.",
        "Compare dated snapshots, preserve both versions and show input and rule changes separately.",
        (CAPABILITIES[3], CAPABILITIES[4]), "sample.compare.v2"),
)})


def admission(bundle, *, qualified_capabilities, approved_digests):
    """All authority comes from server-owned exact bundle/capability admission."""
    return bool(
        bundle.publication_state == "approved"
        and bundle.locale == "en"
        and bundle.digest in approved_digests
        and bundle.offer_identity == "core.standard.monthly.v1"
        and bundle.capabilities
        and set(bundle.capabilities).issubset(CAPABILITIES)
        and set(bundle.capabilities).issubset(qualified_capabilities)
    )


def audience_choice(explicit=None, campaign=None):
    if explicit in AUDIENCES:
        return explicit
    if campaign in AUDIENCES:
        return campaign
    return "small_business"


def validate_event(value):
    """Closed coarse engagement contract only; no active collector exists."""
    keys = {"event", "scenario", "bundle_version", "locale", "audience", "consent"}
    if type(value) is not dict or set(value) != keys:
        raise ValueError("Unsupported engagement event")
    if value["consent"] is not True or any(type(value[key]) is not str for key in keys - {"consent"}):
        raise ValueError("Event fields must be identifiers")
    bundle = REGISTRY.get(value["scenario"])
    if (value["event"] not in BROWSER_EVENTS or bundle is None
        or value["bundle_version"] != bundle.version or value["locale"] != "en"
        or value["audience"] not in AUDIENCES):
        raise ValueError("Event is outside the reviewed contract")
    return dict(value)
