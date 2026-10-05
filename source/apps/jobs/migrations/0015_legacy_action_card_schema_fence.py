"""Fence the legacy action-card entrypoint to its immutable schema-1 contract."""

from django.db import migrations

SQL = r"""
ALTER FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid)
 RENAME TO issue_action_cards_schema1;
REVOKE ALL ON FUNCTION app_private.issue_action_cards_schema1(uuid,uuid,uuid,uuid)
 FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.issue_action_cards(rid uuid,org uuid,actor uuid,snapshot uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
 IF session_user='agentledger_app' AND (org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id()) THEN
  RAISE EXCEPTION 'Action-card context binding invalid';
 END IF;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=snapshot AND organization_id=org;
 IF s.id IS NULL OR s.input_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR s.result_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb THEN
  RAISE EXCEPTION 'Legacy action cards require snapshot schema one';
 END IF;
 RETURN app_private.issue_action_cards_schema1(rid,org,actor,snapshot);
END;$fn$;
ALTER FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid)
 FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid)
 TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [("jobs", "0014_decision_desk")]
    operations = [migrations.RunSQL(SQL)]
