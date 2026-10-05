from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .render import RenderFailure, render_pdf_with_hard_timeout
from .schema import MAX_PAYLOAD_BYTES, InvalidReportRenderPayload

LISTEN_HOST = "0.0.0.0"  # noqa: S104 - private container network only.
LISTEN_PORT = 8080


class RendererRequestHandler(BaseHTTPRequestHandler):
    server_version = "StewardenceRenderer/1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._write_response(HTTPStatus.OK, b'{"status":"ok"}', "application/json")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/render":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(HTTPStatus.BAD_REQUEST, "Chunked requests are not accepted")
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(HTTPStatus.LENGTH_REQUIRED)
            return
        if content_length < 2 or content_length > MAX_PAYLOAD_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            pdf = render_pdf_with_hard_timeout(payload)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            InvalidReportRenderPayload,
        ) as error:
            self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
            return
        except RenderFailure as error:
            print(f"render_failed:{error}", file=sys.stderr, flush=True)
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "PDF rendering failed")
            return
        self._write_response(HTTPStatus.OK, pdf, "application/pdf")

    def _write_response(
        self, status: HTTPStatus, body: bytes, content_type: str
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), RendererRequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
