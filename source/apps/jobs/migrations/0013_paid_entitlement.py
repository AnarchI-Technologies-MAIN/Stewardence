"""Protected work consumes separately issued payment coverage at database time."""

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION app_private.core_work_allowed(org uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_subscription s
  JOIN public.billing_billingcustomer c ON c.id=s.billing_customer_id
  JOIN public.organizations_organizationmember m
   ON m.organization_id=s.organization_id AND m.user_id=c.user_id AND m.role='owner'
  WHERE s.organization_id=org AND app_private.paid_subscription_access(s.id))
 AND NOT EXISTS(SELECT 1 FROM public.core_health_controls h
  WHERE organization_id=org AND mode='paused'
   AND NOT EXISTS(SELECT 1 FROM public.core_health_controls successor
    WHERE successor.supersedes_id=h.id))
 AND NOT EXISTS(SELECT 1 FROM (
  SELECT payload,sha256 FROM public.job_recovery_receipts
   WHERE organization_id=org ORDER BY created_at DESC,id DESC LIMIT 50) recent
  WHERE recent.sha256 IS DISTINCT FROM encode(
   sha256(convert_to(app_private.recovery_canonical(recent.payload),'UTF8')),'hex'))
$fn$;
CREATE OR REPLACE FUNCTION app_private.core_owner_entitled(org uuid,actor uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.organizations_organizationmember m
  JOIN public.billing_subscription s ON s.organization_id=m.organization_id
  JOIN public.billing_billingcustomer c
   ON c.id=s.billing_customer_id AND c.user_id=m.user_id
  JOIN public.organization_workflow_profiles p ON p.organization_id=m.organization_id
  WHERE m.organization_id=org AND m.user_id=actor AND m.role='owner'
   AND app_private.paid_subscription_access(s.id)
   AND p.profile IN ('business.v1','development.v1'))
$fn$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0012_core_authority_successor"),
        ("billing", "0006_paid_coverage"),
    ]
    operations = [migrations.RunSQL(SQL)]
