"""Synthetic localhost preview with real restricted application DB identity."""
import os
import secrets
import subprocess
import sys
from decimal import Decimal
from urllib.parse import urlsplit,urlunsplit,quote
from provision_database_roles import provision_database_roles,ROLE_NAMES

if os.getenv('STEWARDENCE_ISOLATED_QA')!='1': raise SystemExit('Isolated QA marker required')
dsn=os.environ['DATABASE_URL']
parts=urlsplit(dsn)
if parts.hostname!='qualification-db' or parts.path!='/qualification': raise SystemExit('Isolated database target required')
passwords={role:secrets.token_urlsafe(36) for role in ROLE_NAMES}
provision_database_roles(dsn,passwords)
subprocess.run([sys.executable,'manage.py','migrate','--noinput'],check=True)
import django
django.setup()
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.organizations.models import Organization,OrganizationMember,WorkflowProfile
from apps.billing.models import BillingCustomer,Subscription
from apps.inventory.models import InventoryItem
from apps.roi.engine import ROIInputs,Assumption,AssumptionProvenance
from apps.assessments.snapshots import create_assessment_snapshot
from apps.reports.services import create_report
from apps.jobs.core_workflows import admit_entity,tick

user=get_user_model().objects.create_user('qa-owner@example.invalid',password='QA-only-Stewardence-2026')
org=Organization.objects.create(name='Synthetic accounting firm',industry='accounting_bookkeeping')
OrganizationMember.objects.create(user=user,organization=org,role='owner')
WorkflowProfile.objects.create(organization=org,created_by=user,profile='business.v1',settings={'name':'Synthetic main branch'})
customer=BillingCustomer.objects.create(user=user)
Subscription.objects.create(billing_customer=customer,organization=org,portfolio='core',status='active',current_price_cents=9900)
item=InventoryItem.objects.create(organization=org,display_name='Synthetic payroll assistant',vendor_name='Synthetic vendor',
    data_categories=['payroll'],capabilities=['external_transfer'],human_approval=False)
def declared(v):return Assumption(Decimal(str(v)),AssumptionProvenance.CUSTOMER_SUPPLIED)
roi=ROIInputs(monthly_subscription_cost=declared(99),implementation_cost=declared(300),
    implementation_amortization_months=Assumption(12,AssumptionProvenance.CUSTOMER_SUPPLIED),
    hours_saved_per_month=Assumption(Decimal('0'),AssumptionProvenance.UNKNOWN),loaded_hourly_rate=declared(45),
    attributable_revenue=declared(0),avoided_monthly_cost=declared(0))
snapshot=create_assessment_snapshot(organization_id=org.id,created_by_id=user.id,assessed_item_id=item.id,
    roi_inputs=roi,captured_at=timezone.now(),roi_engine_version='AL-ROI-2',
    evidence_references=({'reference':'SYNTHETIC-DECLARATION','type':'customer_statement'},))
create_report(organization_id=org.id,assessment_snapshot_id=snapshot.id,created_by_id=user.id)
for category,label in [('branches','Synthetic main branch'),('employees','Synthetic employee account'),('ai_accounts','Synthetic assistant account')]:
    admit_entity(organization_id=org.id,actor_id=user.id,category=category,label=label,as_of=timezone.now())
tick(organization_id=org.id,actor_id=user.id)
# The UI runs as the restricted app role, not the setup administrator.
from django.db import connections
connections.close_all()
os.environ['DATABASE_URL']=urlunsplit((parts.scheme,'agentledger_app:'+quote(passwords['agentledger_app'],safe='')+'@qualification-db:5432',parts.path,'',''))
os.environ['DJANGO_SETTINGS_MODULE']='agentledger.settings.qualification'
subprocess.run([sys.executable,'manage.py','collectstatic','--noinput'],check=True)
os.execv(sys.executable,[sys.executable,'manage.py','runserver','0.0.0.0:8000','--noreload'])
