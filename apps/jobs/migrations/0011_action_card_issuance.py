"""Action proposals are issued from the admitted snapshot, not caller text."""
from django.db import migrations

SQL=r"""
CREATE FUNCTION app_private.issue_action_cards(rid uuid,org uuid,actor uuid,snapshot uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; cards jsonb; existing uuid;
BEGIN
 IF session_user='agentledger_app' AND (org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id()) THEN RAISE EXCEPTION 'Action-card context binding invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Action-card admission unavailable';
 END IF;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=snapshot AND organization_id=org;
 IF NOT FOUND THEN RAISE EXCEPTION 'Action-card assessment unresolved'; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('inventory_item_id',item->>'inventory_item_id',
  'rule_id',policy->'rule_id','rule_version',policy->'rule_version','severity',policy->'severity',
  'proposal',policy->'recommended_remediation','authority','proposal_only')
  ORDER BY item->>'inventory_item_id' COLLATE "C",policy->>'rule_id' COLLATE "C",policy->>'rule_version' COLLATE "C"),'[]'::jsonb)
  INTO cards FROM jsonb_array_elements(s.result_payload->'inventory_results') item
  CROSS JOIN LATERAL jsonb_array_elements(item->'policy_results') policy WHERE policy->>'result'='FAIL';
 SELECT id INTO existing FROM public.core_action_card_revisions WHERE organization_id=org AND snapshot_id=snapshot;
 IF FOUND THEN RETURN existing; END IF;
 INSERT INTO public.core_action_card_revisions(id,organization_id,created_by_id,created_at,snapshot_id,input_sha256,cards,sha256)
  VALUES(rid,org,actor,clock_timestamp(),snapshot,s.result_sha256,cards,
   encode(sha256(convert_to(app_private.queue_canonical(cards),'UTF8')),'hex'));
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) TO agentledger_app;
REVOKE INSERT ON public.core_action_card_revisions FROM agentledger_app;
"""

class Migration(migrations.Migration):
    dependencies=[('jobs','0010_job_input_admission')]
    operations=[migrations.RunSQL(SQL)]
