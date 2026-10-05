"""Permanent v1 exposure semantics for historical review-pack v2 identities.

PASS means a bounded declaration is present, never that a control was tested.
No live provider, detector, network request or permission grant occurs here.
Semantic changes require a new module and a new admitted pack schema; retain
this implementation for historical rendering. Do not dispatch it through the
current exposure entrypoint.
"""

import hashlib
from dataclasses import asdict, dataclass
from enum import StrEnum
from uuid import UUID

import rfc8785

DECLARED = "Declared"
VERSION = "core.exposure.declarations.v1"


class Outcome(StrEnum):
    PASS = "PASS"  # noqa: S105 - review outcome, not a credential.
    CONCERN = "CONCERN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ReviewQuestion:
    question_id: str
    outcome: Outcome
    explanation: str
    source_fields: tuple[str, ...]
    basis: str = "customer_declaration"
    verification: str = "not_established"


def review_record(record: dict) -> dict:
    """Review an immutable snapshot record; caller supplies tenant admission.

    Unknown/default provenance never becomes a declaration. Historical
    snapshots without field provenance remain unknown under this new contract.
    """
    if type(record) is not dict:
        raise ValueError("Captured inventory record must be an object")
    identity = str(UUID(record["id"]))
    provenance = record.get("provenance", {})
    if type(provenance) is not dict:
        raise ValueError("Field provenance must be an object")
    questions = []

    def declared(field):
        return provenance.get(field) == DECLARED and field in record

    def add(key, outcome, explanation, fields):
        questions.append(
            ReviewQuestion(
                key,
                outcome,
                explanation,
                fields,
                basis="unknown"
                if outcome == Outcome.UNKNOWN
                else "customer_declaration",
            )
        )

    for field, label in (
        ("business_owner", "Responsible person"),
        ("business_purpose", "Business purpose"),
    ):
        if not declared(field):
            add(field, Outcome.UNKNOWN, f"{label} has not been declared.", (field,))
        elif type(record[field]) is not str:
            raise ValueError("Text declarations must contain text")
        elif not record[field].strip():
            add(
                field,
                Outcome.CONCERN,
                f"{label} is blank in the declaration.",
                (field,),
            )
        else:
            add(field, Outcome.PASS, f"{label} is recorded as a declaration.", (field,))

    for field, label in (
        ("data_categories", "Information categories"),
        ("permissions", "Permissions"),
        ("capabilities", "Actions"),
    ):
        if not declared(field):
            add(field, Outcome.UNKNOWN, f"{label} have not been declared.", (field,))
            continue
        value = record[field]
        if type(value) is not list or any(type(item) is not str for item in value):
            raise ValueError("List declarations must contain text values")
        add(
            field,
            Outcome.PASS,
            f"{label} are recorded as declarations, including any stated empty list.",
            (field,),
        )

    approval_fields = (
        "human_approval",
        "autonomy_level",
        "capabilities",
        "permissions",
    )
    if not all(declared(field) for field in approval_fields):
        add(
            "approval",
            Outcome.UNKNOWN,
            "The declared action and approval boundary is incomplete.",
            approval_fields,
        )
    else:
        approval = record["human_approval"]
        autonomy = record["autonomy_level"]
        if (
            type(approval) is not bool
            or type(autonomy) is not int
            or autonomy not in range(5)
        ):
            raise ValueError("Unsupported approval or autonomy declaration")
        # Unknown permission/action vocabulary never implies harmlessness.
        has_actions = bool(record["capabilities"] or record["permissions"] or autonomy)
        if not has_actions:
            add(
                "approval",
                Outcome.NOT_APPLICABLE,
                "No actions or permissions are declared; approval applicability "
                "follows that declaration only.",
                approval_fields,
            )
        elif approval:
            add(
                "approval",
                Outcome.PASS,
                "A human approval requirement is declared; "
                "enforcement has not been checked.",
                approval_fields,
            )
        else:
            add(
                "approval",
                Outcome.CONCERN,
                "Actions or permissions are declared without a human approval "
                "requirement; review the intended boundary.",
                approval_fields,
            )

    add(
        "account_identity",
        Outcome.UNKNOWN,
        "This captured inventory schema does not identify "
        "the executing account or principal.",
        (),
    )
    add(
        "access_removal",
        Outcome.UNKNOWN,
        "This captured inventory schema does not record an access-removal procedure.",
        (),
    )
    result = {
        "schema": VERSION,
        "inventory_item_id": identity,
        "record_sha256": hashlib.sha256(rfc8785.dumps(record)).hexdigest(),
        "questions": [asdict(question) for question in questions],
        "authority": "proposal_only",
        "verification": "not_established",
    }
    return {**result, "sha256": hashlib.sha256(rfc8785.dumps(result)).hexdigest()}
