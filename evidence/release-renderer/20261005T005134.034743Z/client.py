import hashlib, importlib.util, json, os, time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
import django
django.setup()
assert os.getuid() == 10001
assert importlib.util.find_spec("renderer") is None
assert importlib.util.find_spec("pytest") is None
from apps.assessments.capture_v1 import build_capture_payloads
from apps.inventory.provenance import DECLARED, INVENTORY_FACT_FIELDS, UNKNOWN
from apps.reviews.capture_context import digest
from apps.reviews.capture_context_v3 import build_capture_v4_pack_context
from apps.reviews.capture_event_v2 import validate_frozen_capture_selection
from apps.reviews.proposals_v1 import APPLICABILITY_VERSION, build_review_proposals
from apps.reports.render_client import HTTPReportRenderer, ReportRenderError
def record(identity=None):
    return {'id': str(identity or uuid4()), 'product_id': None, **dict.fromkeys(INVENTORY_FACT_FIELDS), 'display_name': 'Tool', 'source_type': 'manual', 'declaration_contract': 'core.inventory.declarations.v1', 'declaration_as_of': '2026-10-04', 'archived_at': None, 'provenance': {**{field: DECLARED if field == 'display_name' else UNKNOWN for field in INVENTORY_FACT_FIELDS}, 'product_id': UNKNOWN, 'source_type': DECLARED}}

def args(industry='accounting_bookkeeping', records=None):
    return dict(organization_id=uuid4(), created_by_id=uuid4(), assessment_id=uuid4(), assessment_version=1, captured_at=datetime(2026, 10, 4, 12, tzinfo=UTC), industry=industry, workflow_profile_id=uuid4(), workflow_profile='business.v1', workflow_settings={'name': 'Company'}, inventory_records=[record()] if records is None else records)

def capture_projection(industry='other'):
    pins = args(industry)
    envelope = build_capture_payloads(**pins)
    inputs, results = (envelope['input_payload'], envelope['result_payload'])
    snapshot = {'snapshot_id': inputs['assessment']['id'], 'assessment_id': inputs['assessment']['id'], 'assessment_version': 1, 'input_sha256': envelope['input_sha256'], 'result_sha256': envelope['result_sha256'], 'captured_at': inputs['captured_at'], 'snapshot_schema': 2, 'workflow_profile_id': str(pins['workflow_profile_id']), 'workflow_profile': pins['workflow_profile'], 'workflow_settings_sha256': inputs['workflow_profile']['settings_sha256'], 'rules_sha256': digest(inputs['rulesets']), 'configuration_sha256': digest(inputs['risk_configuration']), 'engine_versions': inputs['engine_versions'], 'capture_contract': inputs['capture_contract']}
    manifest = {'schema': 'stewardence.review_pack.v3', 'cycle_id': str(uuid4()), 'organization_id': str(pins['organization_id']), 'baseline_pack_id': None, 'snapshot': snapshot, 'selected_decisions': [], 'selection_scope': 'empty_capture_kernel', 'artifact_state': 'not_created', 'baseline_promotion': 'blocked', 'capture': {'receipt_id': snapshot['snapshot_id'], 'request_sha256': 'b' * 64, 'contract': 'core.capture.declarations.v1', 'exposure_contract': 'core.exposure.declarations.v1'}}
    projection = {'schema': 'stewardence.review_worker_projection.v2', **{key: str(uuid4()) for key in ('request_id', 'job_id', 'report_id', 'pack_id')}, 'organization_id': str(pins['organization_id']), 'manifest': manifest, 'manifest_sha256': digest(manifest), 'snapshot_input': inputs, 'snapshot_result': results, 'selected_decisions': []}
    metadata = {'report_identifier': 'AL-2026-000001', 'organization_display_name': 'Synthetic owner firm', 'assessment_date': snapshot['captured_at'], 'assessment_id': snapshot['assessment_id'], 'assessment_version': 1, 'assessment_snapshot_id': snapshot['snapshot_id'], 'input_sha256': snapshot['input_sha256'], 'result_sha256': snapshot['result_sha256']}
    return (metadata, projection)

def v4_projection(industry='other'):
    metadata, p = capture_projection(industry)
    pin = p['manifest']['snapshot']
    envelope = {'input_payload': p['snapshot_input'], 'result_payload': p['snapshot_result'], 'input_sha256': pin['input_sha256'], 'result_sha256': pin['result_sha256']}
    proposals = build_review_proposals(snapshot_id=UUID(pin['snapshot_id']), capture_envelope=envelope)
    qualification = digest({'schema': APPLICABILITY_VERSION, 'industry_applicability': p['snapshot_input']['industry_applicability'], 'ruleset': p['snapshot_input']['rulesets']['industry'], 'engine_versions': p['snapshot_input']['engine_versions']})
    receipt, revision = (str(uuid4()), str(uuid4()))
    selected = [{'proposal_receipt_id': receipt, 'revision_id': revision, 'revision_sha256': digest(proposals), 'card_index': i, 'card_sha256': digest(proposal), 'qualification_sha256': qualification, 'proposal': proposal} for i, proposal in enumerate(proposals)]
    p['schema'] = 'stewardence.review_worker_projection.v3'
    p['selected_proposals'] = selected
    p['manifest'].update(schema='stewardence.review_pack.v4', selected_proposals=deepcopy(selected), selection_scope='issued_capture_proposals', proposal_contract_version='stewardence.core_review_proposal.v1')
    p['manifest_sha256'] = digest(p['manifest'])
    return (metadata, p)

def add_statements(p):
    entry = p['selected_proposals'][0]
    proposal = entry['proposal']
    prior = None
    for sequence, (kind, state) in enumerate((('disposition', 'act'), ('execution', 'completion_recorded')), 1):
        body = {'schema': 'stewardence.core_decision_event.v2', 'id': str(uuid4()), 'organization_id': p['organization_id'], 'created_by_id': p['snapshot_input']['created_by_id'], 'created_at': p['manifest']['snapshot']['captured_at'], 'revision_id': entry['revision_id'], 'revision_sha256': entry['revision_sha256'], 'snapshot_id': proposal['snapshot_id'], 'snapshot_result_sha256': proposal['snapshot_result_sha256'], 'card_index': 0, 'card_sha256': entry['card_sha256'], 'previous_event_id': prior, 'sequence': sequence, 'event_kind': kind, 'state': state, 'responsible_label': 'Named owner', 'due_date': None, 'notes': '<script>owner statement</script>', 'links': ['https://example.invalid/reference'], 'owner_statement_only': True, 'resolution_verified': False, 'proposal_id': proposal['proposal_id'], 'proposal_sha256': proposal['sha256'], 'proposal_contract': proposal['schema'], 'proposal_receipt_id': entry['proposal_receipt_id'], 'source_class': proposal['source']['class'], 'source_identity': proposal['source']['identity'], 'source_digest': proposal['source']['digest'], 'original_outcome': proposal['original_outcome'], 'resolution_effect': 'none', 'source_state_immutable': True}
        p['selected_decisions'].append({'event_id': body['id'], 'event_sha256': digest(body), 'payload': body})
        prior = body['id']
    p['manifest']['selected_decisions'] = deepcopy(p['selected_decisions'])
    p['manifest_sha256'] = digest(p['manifest'])
original_args = args
def args(industry):
    pins = original_args(industry)
    if industry == "accounting_bookkeeping":
        row = pins["inventory_records"][0]
        for key, value in {"data_categories":["payroll"],"capabilities":["external_transfer"],"human_approval":False}.items():
            row[key], row["provenance"][key] = value, "Declared"
    return pins
results=[]
renderer=HTTPReportRenderer(base_url="http://release-renderer:8080",timeout_seconds=70)
for industry in ("other","accounting_bookkeeping"):
    metadata, projection=v4_projection(industry)
    add_statements(projection)
    context=build_capture_v4_pack_context(metadata,projection)
    if industry == "accounting_bookkeeping":
        assert any(e["proposal"]["source"]["class"] == "accounting_fail" for e in projection["selected_proposals"])
    start=time.monotonic()
    pdf=renderer.render(context)
    elapsed=time.monotonic()-start
    stem=Path("/qualification")/industry
    stem.with_suffix(".pdf").write_bytes(pdf)
    stem.with_suffix(".json").write_text(json.dumps(context,ensure_ascii=False),encoding="utf-8")
    results.append({"industry":industry,"elapsed_seconds":elapsed,"pdf_bytes":len(pdf),"pdf_sha256":hashlib.sha256(pdf).hexdigest(),"context_sha256":digest(context),"context_bytes":len(json.dumps(context,ensure_ascii=False,separators=(",",":")).encode()),"transport":"actual_app_HTTPReportRenderer_to_actual_renderer_v1_render","database_issuance":False})
try:
    renderer.render({"context_version":"unadmitted_unknown"})
    raise AssertionError("Malformed HTTP render payload was admitted")
except ReportRenderError as error:
    assert "HTTP 422" in str(error)
Path("/qualification/http-results.json").write_text(json.dumps(results,indent=2))
print(json.dumps({"actual_app_uid":os.getuid(),"renderer_package_absent":True,"pytest_absent":True,"http_specimens":len(results)}))
