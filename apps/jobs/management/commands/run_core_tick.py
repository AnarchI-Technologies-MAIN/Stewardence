from uuid import UUID
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import PermissionDenied,ValidationError,ObjectDoesNotExist
from apps.jobs.core_workflows import tick


class Command(BaseCommand):
    help='Run one bounded Core tick from admitted records. No listener or provider collection.'

    def add_arguments(self,parser):
        parser.add_argument('--organization-id',required=True,type=UUID)
        parser.add_argument('--actor-id',required=True,type=UUID)

    def handle(self,*args,**options):
        if not getattr(settings,'CORE_WORKFLOWS_ENABLED',False): raise CommandError('Core scheduled execution is disabled')
        try:
            result=tick(organization_id=options['organization_id'],actor_id=options['actor_id'])
        except (PermissionDenied,ValidationError,ObjectDoesNotExist):
            raise CommandError('Core tick admission failed; review owner, entitlement and receipts') from None
        self.stdout.write(f"Core tick: {result['state']}; admitted runs: {len(result['runs'])}")
