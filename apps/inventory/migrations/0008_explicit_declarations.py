"""Additive, owner-issued explicit knowledge; legacy records remain unchanged."""

from django.db import migrations, models

SQL = r"""
ALTER TABLE inventory_explicit_declaration_gate OWNER TO agentledger_owner;
REVOKE ALL ON inventory_explicit_declaration_gate FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE inventory_explicit_declaration_gate ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_explicit_declaration_gate FORCE ROW LEVEL SECURITY;
CREATE POLICY explicit_inventory_gate_owner ON inventory_explicit_declaration_gate TO agentledger_owner USING(true) WITH CHECK(true);
INSERT INTO inventory_explicit_declaration_gate(id,enabled) VALUES(1,false);

CREATE FUNCTION app_private.protect_explicit_inventory() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.declaration_contract<>'' THEN RAISE EXCEPTION 'Explicit declarations cannot be deleted'; END IF;
  RETURN OLD;
 END IF;
 IF TG_OP='UPDATE' AND (OLD.declaration_contract IS DISTINCT FROM NEW.declaration_contract
  OR (OLD.declaration_contract<>'' AND (OLD.id<>NEW.id OR OLD.organization_id<>NEW.organization_id
   OR OLD.source_type<>NEW.source_type OR OLD.product_id IS DISTINCT FROM NEW.product_id))) THEN
  RAISE EXCEPTION 'Declaration identity is immutable';
 END IF;
 IF NEW.declaration_contract='' THEN
  IF NEW.declaration_as_of IS NOT NULL THEN RAISE EXCEPTION 'Legacy declaration date cannot be asserted'; END IF;
  RETURN NEW;
 END IF;
 IF current_user<>'agentledger_owner' OR NEW.declaration_contract<>'core.inventory.declarations.v1'
  OR NEW.source_type<>'manual' OR NEW.product_id IS NOT NULL OR NEW.declaration_as_of IS NULL THEN
  RAISE EXCEPTION 'Explicit inventory requires narrow owner issuance'; END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.protect_explicit_inventory() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_explicit_inventory() FROM PUBLIC;
CREATE TRIGGER explicit_inventory_issuance BEFORE INSERT OR UPDATE OR DELETE ON inventory_items
 FOR EACH ROW EXECUTE FUNCTION app_private.protect_explicit_inventory();

CREATE FUNCTION app_private.write_explicit_inventory(iid uuid,org uuid,actor uuid,e jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE old public.inventory_items%ROWTYPE; v jsonb; d jsonb; key text; element jsonb;
 allowed text[]:=ARRAY['display_name','vendor_name','business_owner','department','business_purpose',
 'user_count','seat_count','monthly_cost_cents','human_approval','autonomy_level','status',
 'connected_systems','data_categories','permissions','capabilities'];
 choices jsonb:='{"connected_systems":["accounting","banking","payroll","tax","document_storage","email","customer_records","other"],"data_categories":["public_information","internal_business_information","client_information","financial_records","banking_information","payroll","tax_records","health_information","legal_information","authentication_credentials","personally_identifiable_information"],"permissions":["read","write","delete","transmit","administer"],"capabilities":["content_generation","data_analysis","external_transfer","financial_transaction","record_modification","communication"]}';
 asof date; issued timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR iid IS NULL OR org IS NULL OR actor IS NULL
  OR org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Declaration identity invalid'; END IF;
 IF jsonb_typeof(e) IS DISTINCT FROM 'object' OR octet_length(e::text)>32768
  OR (SELECT count(*) FROM jsonb_object_keys(e))<>4
  OR NOT e ?& ARRAY['schema','declared_fields','as_of','values']
  OR e->>'schema' IS DISTINCT FROM 'core.inventory.declarations.v1'
  OR jsonb_typeof(e->'as_of') IS DISTINCT FROM 'string' OR e->>'as_of' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  OR jsonb_typeof(e->'declared_fields') IS DISTINCT FROM 'array'
  OR jsonb_typeof(e->'values') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Invalid declaration envelope'; END IF;
 d:=e->'declared_fields'; v:=e->'values'; asof:=(e->>'as_of')::date;
 IF (SELECT count(*) FROM jsonb_object_keys(v))<>15 OR NOT v ?& allowed
  OR jsonb_array_length(d)<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(d))
  OR NOT d ? 'display_name' THEN RAISE EXCEPTION 'Invalid declaration field set'; END IF;
 FOR element IN SELECT value FROM jsonb_array_elements(d) LOOP
  IF jsonb_typeof(element)<>'string' OR NOT (element#>>'{}')=ANY(allowed) THEN RAISE EXCEPTION 'Unsupported declaration field'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['display_name','vendor_name','business_owner','department','business_purpose','status'] LOOP
  IF jsonb_typeof(v->key) IS DISTINCT FROM 'string'
   OR length(v->>key)>(CASE WHEN key='business_purpose' THEN 4096 ELSE 255 END)
   OR (d ? key AND length(btrim(v->>key))=0)
   OR (NOT d ? key AND v->>key IS DISTINCT FROM (CASE WHEN key='status' THEN 'reviewing' ELSE '' END)) THEN
   RAISE EXCEPTION 'Invalid scalar declaration'; END IF;
 END LOOP;
 IF v->>'status' NOT IN ('active','trial','inactive','reviewing') THEN RAISE EXCEPTION 'Invalid use declaration'; END IF;
 FOREACH key IN ARRAY ARRAY['user_count','seat_count','monthly_cost_cents','autonomy_level'] LOOP
  IF jsonb_typeof(v->key) IS DISTINCT FROM 'number' OR v->>key !~ '^[0-9]{1,10}$'
   OR (v->>key)::numeric>2147483647 OR (NOT d ? key AND (v->>key)::integer<>0) THEN
   RAISE EXCEPTION 'Invalid numeric declaration'; END IF;
 END LOOP;
 IF (v->>'autonomy_level')::integer>4 OR jsonb_typeof(v->'human_approval') IS DISTINCT FROM 'boolean'
  OR (NOT d ? 'human_approval' AND v->'human_approval'<>'true'::jsonb) THEN RAISE EXCEPTION 'Invalid approval declaration'; END IF;
 FOREACH key IN ARRAY ARRAY['connected_systems','data_categories','permissions','capabilities'] LOOP
  IF jsonb_typeof(v->key) IS DISTINCT FROM 'array' OR jsonb_array_length(v->key)>16
   OR jsonb_array_length(v->key)<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(v->key))
   OR (NOT d ? key AND v->key<>'[]'::jsonb) THEN RAISE EXCEPTION 'Invalid list declaration'; END IF;
  FOR element IN SELECT value FROM jsonb_array_elements(v->key) LOOP
   IF jsonb_typeof(element)<>'string' OR NOT (choices->key) @> jsonb_build_array(element) THEN
    RAISE EXCEPTION 'Unsupported declared value'; END IF;
  END LOOP;
 END LOOP;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':inventory',0));
 IF NOT COALESCE((SELECT enabled FROM public.inventory_explicit_declaration_gate WHERE id=1 FOR SHARE),false)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Explicit declarations unavailable'; END IF;
 SELECT * INTO old FROM public.inventory_items WHERE id=iid FOR UPDATE;
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Explicit declarations unavailable after row admission'; END IF;
 issued:=clock_timestamp();
 IF asof>(issued AT TIME ZONE 'UTC')::date THEN RAISE EXCEPTION 'Future declaration date invalid'; END IF;
 IF FOUND THEN
  IF old.organization_id<>org OR old.declaration_contract<>'core.inventory.declarations.v1' OR old.archived_at IS NOT NULL THEN
   RAISE EXCEPTION 'Declaration target invalid'; END IF;
  UPDATE public.inventory_items SET display_name=v->>'display_name',vendor_name=v->>'vendor_name',
   business_owner=v->>'business_owner',department=v->>'department',business_purpose=v->>'business_purpose',
   user_count=(v->>'user_count')::integer,seat_count=(v->>'seat_count')::integer,monthly_cost_cents=(v->>'monthly_cost_cents')::integer,
   autonomy_level=(v->>'autonomy_level')::integer,human_approval=(v->>'human_approval')::boolean,status=v->>'status',
   connected_systems=v->'connected_systems',data_categories=v->'data_categories',permissions=v->'permissions',capabilities=v->'capabilities',
   declared_fields=d,declaration_as_of=asof,updated_at=issued WHERE id=iid;
 ELSE
  INSERT INTO public.inventory_items(id,organization_id,product_id,display_name,vendor_name,business_owner,department,business_purpose,
   user_count,seat_count,monthly_cost_cents,autonomy_level,human_approval,status,connected_systems,data_categories,permissions,capabilities,
   source_type,discovery_fingerprint,declared_fields,declaration_contract,declaration_as_of,created_at,updated_at)
  VALUES(iid,org,NULL,v->>'display_name',v->>'vendor_name',v->>'business_owner',v->>'department',v->>'business_purpose',
   (v->>'user_count')::integer,(v->>'seat_count')::integer,(v->>'monthly_cost_cents')::integer,(v->>'autonomy_level')::integer,
   (v->>'human_approval')::boolean,v->>'status',v->'connected_systems',v->'data_categories',v->'permissions',v->'capabilities',
   'manual','',d,'core.inventory.declarations.v1',asof,issued,issued);
 END IF;
 RETURN iid;
END;$fn$;
ALTER FUNCTION app_private.write_explicit_inventory(uuid,uuid,uuid,jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.write_explicit_inventory(uuid,uuid,uuid,jsonb) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.write_explicit_inventory(uuid,uuid,uuid,jsonb) TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0007_inventoryitem_declared_fields"),
        ("jobs", "0013_paid_entitlement"),
    ]
    operations = [
        migrations.AddField(
            model_name="inventoryitem",
            name="declaration_contract",
            field=models.CharField(default="", editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="inventoryitem",
            name="declaration_as_of",
            field=models.DateField(blank=True, editable=False, null=True),
        ),
        migrations.CreateModel(
            name="ExplicitDeclarationGate",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "inventory_explicit_declaration_gate",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1),
                        name="explicit_inventory_gate_singleton",
                    )
                ],
            },
        ),
        migrations.RunSQL(SQL),
    ]
