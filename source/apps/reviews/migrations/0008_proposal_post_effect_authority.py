"""Recheck proposal authority after admitted caller-chosen PK insert waits."""

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION app_private.issue_core_exposure_proposals(rid uuid,org uuid,actor uuid,sid uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; capture public.assessment_capture_receipts%ROWTYPE;
 previous public.review_capture_proposal_receipts%ROWTYPE; revision public.core_action_card_revisions%ROWTYPE;
 cards jsonb; card_hash text; qualification_hash text; issued timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR rid IS NULL OR org IS NULL OR actor IS NULL OR sid IS NULL THEN
  RAISE EXCEPTION 'Proposal admission requires explicit identities and read committed'; END IF;
 IF org IS DISTINCT FROM app_private.current_organization_id() OR actor IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Proposal identity context invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':proposal:'||sid::text,0));
 PERFORM 1 FROM public.review_core_proposal_gate WHERE id=1 FOR SHARE;
 IF NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org) THEN
  RAISE EXCEPTION 'Proposal admission unavailable'; END IF;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org FOR KEY SHARE;
 SELECT * INTO capture FROM public.assessment_capture_receipts WHERE snapshot_id=sid AND organization_id=org FOR KEY SHARE;
 SELECT * INTO revision FROM public.core_action_card_revisions WHERE snapshot_id=sid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.organization_workflow_profiles WHERE organization_id=org FOR SHARE;
 cards:=app_private.recompute_capture_proposals_v1(sid,org);
 card_hash:=encode(sha256(convert_to(app_private.queue_canonical(cards),'UTF8')),'hex');
 qualification_hash:=encode(sha256(convert_to(app_private.queue_canonical(jsonb_build_object('schema','stewardence.core_review_proposal_applicability.v1',
  'industry_applicability',s.input_payload->'industry_applicability','ruleset',s.input_payload->'rulesets'->'industry','engine_versions',s.input_payload->'engine_versions')),'UTF8')),'hex');
 issued:=clock_timestamp();
 IF NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org)
  OR s.created_by_id IS DISTINCT FROM actor OR capture.created_by_id IS DISTINCT FROM actor OR s.captured_at>issued THEN
  RAISE EXCEPTION 'Proposal authority unavailable after waits'; END IF;
 SELECT * INTO previous FROM public.review_capture_proposal_receipts WHERE snapshot_id=sid AND organization_id=org;
 IF FOUND THEN
  IF revision.id IS DISTINCT FROM previous.revision_id OR revision.created_by_id IS DISTINCT FROM actor
   OR previous.created_by_id IS DISTINCT FROM actor OR previous.capture_receipt_id IS DISTINCT FROM capture.id
   OR previous.contract IS DISTINCT FROM 'stewardence.core_review_proposal.v1'
   OR previous.input_sha256 IS DISTINCT FROM s.input_sha256 OR previous.result_sha256 IS DISTINCT FROM s.result_sha256
   OR previous.revision_sha256 IS DISTINCT FROM card_hash OR previous.qualification_sha256 IS DISTINCT FROM qualification_hash
   OR revision.cards IS DISTINCT FROM cards OR revision.sha256 IS DISTINCT FROM card_hash OR revision.input_sha256 IS DISTINCT FROM s.result_sha256 THEN
   RAISE EXCEPTION 'Issued proposal replay pins invalid'; END IF;
  RETURN revision.id;
 END IF;
 IF revision.id IS NOT NULL THEN RAISE EXCEPTION 'Unissued legacy revision conflicts with proposal contract'; END IF;
 INSERT INTO public.core_action_card_revisions(id,organization_id,created_by_id,created_at,snapshot_id,input_sha256,cards,sha256)
 VALUES(rid,org,actor,issued,sid,s.result_sha256,cards,card_hash);
 INSERT INTO public.review_capture_proposal_receipts(id,organization_id,created_by_id,created_at,snapshot_id,revision_id,capture_receipt_id,
 contract,input_sha256,result_sha256,revision_sha256,qualification_sha256)
 VALUES(gen_random_uuid(),org,actor,issued,sid,rid,capture.id,'stewardence.core_review_proposal.v1',s.input_sha256,s.result_sha256,card_hash,qualification_hash);
 -- A caller-selected revision UUID can wait on a foreign uncommitted
 -- primary key after the earlier FK locks and authority observation. Receipt
 -- insertion can also wait. Recheck after all effects; an exception rolls
 -- both immutable rows back within the caller's database transaction.
 issued:=clock_timestamp();
 IF NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org)
  OR s.created_by_id IS DISTINCT FROM actor OR capture.created_by_id IS DISTINCT FROM actor OR s.captured_at>issued THEN
  RAISE EXCEPTION 'Proposal authority unavailable after waits'; END IF;
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.issue_core_exposure_proposals(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_core_exposure_proposals(uuid,uuid,uuid,uuid) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_core_exposure_proposals(uuid,uuid,uuid,uuid) TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [("reviews", "0007_unused_stop")]
    operations = [migrations.RunSQL(SQL)]
