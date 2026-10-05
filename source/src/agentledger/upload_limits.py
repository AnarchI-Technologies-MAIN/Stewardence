"""Bound multipart file streams before temporary files can grow without limit."""
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadhandler import FileUploadHandler


class BoundedUploadHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.received_bytes = 0

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length is not None and content_length > settings.CORE_MAX_MULTIPART_BYTES:
            raise SuspiciousOperation("Upload exceeds the request size limit")

    def receive_data_chunk(self, raw_data, start):
        self.received_bytes += len(raw_data)
        if self.received_bytes > settings.CORE_MAX_FILE_BYTES:
            raise SuspiciousOperation("Upload exceeds the file size limit")
        return raw_data

    def file_complete(self, file_size):
        return None
