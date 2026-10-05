from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import io

import pytest
from botocore.exceptions import ClientError
from apps.reports.storage import LocalPrivateReportStorage, S3PrivateReportStorage, ReportStorageError


def test_local_concurrent_publish_never_overwrites_or_leaves_partial_files(tmp_path):
    storage = LocalPrivateReportStorage(tmp_path)
    barrier = Barrier(2)
    contents = [b"%PDF-first", b"%PDF-second"]
    def publish(content):
        barrier.wait()
        try:
            storage.put(key="firm/report.pdf", content=content, content_type="application/pdf")
            return content
        except ReportStorageError:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, contents))
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert storage.get(key="firm/report.pdf") == winner
    assert list((tmp_path/"firm").glob(".report-*")) == []
    assert (tmp_path/"firm/report.pdf").stat().st_mode & 0o077 == 0


def test_oversized_remote_object_is_bounded_and_closed():
    from apps.reports.storage import MAX_PDF_BYTES
    class Body:
        closed=False
        def read(self,amount):
            assert amount==MAX_PDF_BYTES+1
            return b'x'*amount
        def close(self): self.closed=True
    body=Body()
    class Client:
        def get_object(self,**kwargs):return {'Body':body}
    storage=S3PrivateReportStorage(bucket_name='test',endpoint_url='https://example.invalid',
        access_key_id='test',secret_access_key='test',client=Client())
    with pytest.raises(ReportStorageError,match='size bound'): storage.get(key='synthetic.pdf')
    assert body.closed


@pytest.mark.parametrize("code", ["PreconditionFailed", "ConditionalRequestConflict"])
@pytest.mark.parametrize("same", [True, False])
def test_s3_concurrent_creation_verifies_winner_without_overwriting(code, same):
    content = b"%PDF-requested"
    winner = content if same else b"%PDF-other"
    class Client:
        calls = 0
        def get_object(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ClientError({"Error": {"Code":"NoSuchKey"}}, "GetObject")
            return {"Body":io.BytesIO(winner)}
        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            raise ClientError({"Error": {"Code":code}}, "PutObject")
    storage = S3PrivateReportStorage(bucket_name="test", endpoint_url="https://example.invalid",
        access_key_id="test", secret_access_key="test", client=Client())
    if same:
        storage.put(key="report.pdf", content=content, content_type="application/pdf")
    if not same:
        with pytest.raises(ReportStorageError, match="creation conflict"):
            storage.put(key="report.pdf", content=content, content_type="application/pdf")
