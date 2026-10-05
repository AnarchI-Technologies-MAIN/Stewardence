import pytest
from django.core.exceptions import SuspiciousOperation
from django.test import override_settings
from agentledger.upload_limits import BoundedUploadHandler


@override_settings(CORE_MAX_FILE_BYTES=10, CORE_MAX_MULTIPART_BYTES=20)
def test_upload_cap_counts_actual_chunks_across_files_not_claimed_file_size():
    handler = BoundedUploadHandler()
    assert handler.receive_data_chunk(b"123456", 0) == b"123456"
    # A second file starting at zero cannot reset the aggregate budget.
    with pytest.raises(SuspiciousOperation, match="file size limit"):
        handler.receive_data_chunk(b"abcdef", 0)


@override_settings(CORE_MAX_FILE_BYTES=10, CORE_MAX_MULTIPART_BYTES=20)
def test_oversized_multipart_is_rejected_before_temporary_file_handler():
    handler = BoundedUploadHandler()
    with pytest.raises(SuspiciousOperation, match="request size limit"):
        handler.handle_raw_input(None, {}, 21, b"boundary")
    assert handler.received_bytes == 0


@override_settings(CORE_MAX_FILE_BYTES=10, CORE_MAX_MULTIPART_BYTES=20)
def test_missing_content_length_still_has_stream_budget():
    handler = BoundedUploadHandler()
    handler.handle_raw_input(None, {}, None, b"boundary")
    assert handler.receive_data_chunk(b"0123456789", 0) == b"0123456789"
    with pytest.raises(SuspiciousOperation):
        handler.receive_data_chunk(b"x", 10)
