"""Real resolver path, without starting a listener or worker service."""
import pytest
from agentledger.tenancy.context import tenant_transaction
from apps.jobs.handlers import build_job_handler_resolver
from apps.jobs.models import BackgroundJob
from apps.jobs.worker import execute_claimed_job,JobExecution
from apps.reports.storage import LocalPrivateReportStorage
from apps.reviews.jobs import ReviewReportGenerationHandler
from apps.reviews.models import PackCompletion
from tests.test_review_pack_lifecycle import pack_context,enabled,request,claimed,Renderer

pytestmark=pytest.mark.django_db(transaction=True,databases='__all__')


@pytest.mark.parametrize('missing',[None,'','   '])
def test_review_resolver_missing_identity_denies_before_render_or_storage(pack_context,enabled,tmp_path,missing):
    class NeverRender:
        def render(self,context):
            raise AssertionError('Missing identity reached external rendering')
    request(pack_context)
    job=claimed(pack_context)
    worker=build_job_handler_resolver(using='worker_runtime',worker_id=missing,report_renderer=NeverRender(),report_storage=LocalPrivateReportStorage(tmp_path))(BackgroundJob.Type.REPORT_GENERATION)
    assert isinstance(worker,ReviewReportGenerationHandler)
    with pytest.raises(ValueError,match='identity required'):
        execute_claimed_job(JobExecution(job=job,worker_id='review-qualification'),worker,using='worker_runtime')
    assert not PackCompletion.objects.exists() and list(tmp_path.iterdir())==[]


def test_resolver_configured_identity_completes_review(pack_context,enabled,tmp_path):
    request(pack_context)
    job=claimed(pack_context)
    worker=build_job_handler_resolver(using='worker_runtime',worker_id='review-qualification',report_renderer=Renderer(),report_storage=LocalPrivateReportStorage(tmp_path))(BackgroundJob.Type.REPORT_GENERATION)
    execute_claimed_job(JobExecution(job=job,worker_id='review-qualification'),worker,using='worker_runtime')
    assert PackCompletion.objects.count()==1
