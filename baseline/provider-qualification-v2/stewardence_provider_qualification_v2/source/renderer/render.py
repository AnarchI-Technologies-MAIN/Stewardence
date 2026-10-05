from __future__ import annotations

import os
import tempfile
import time
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .schema import validate_report_render_payload
from .template import render_report_html

OUTPUT_DIRECTORY = Path("/work/output")
MAX_PDF_BYTES = 16 * 1_048_576
RENDER_TIMEOUT_SECONDS = 60


class RenderFailure(RuntimeError):
    pass


class RenderTimeout(RenderFailure):
    pass


class RenderOutputTooLarge(RenderFailure):
    pass


def _abort_request(route) -> None:
    route.abort()


def _render_child(connection: Connection, payload: Any) -> None:
    try:
        connection.send(("ok", render_pdf(payload)))
    except Exception as error:  # noqa: BLE001 - isolated process error boundary.
        connection.send(("error", type(error).__name__))
    finally:
        connection.close()


def render_pdf_with_hard_timeout(
    payload: Any,
    *,
    timeout_seconds: int = RENDER_TIMEOUT_SECONDS,
) -> bytes:
    validate_report_render_payload(payload)
    context = get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=_render_child, args=(child_connection, payload))
    process.start()
    child_connection.close()
    try:
        if not parent_connection.poll(timeout_seconds):
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
            raise RenderTimeout("PDF rendering exceeded the time limit")
        status, result = parent_connection.recv()
        process.join(2)
        if status != "ok":
            raise RenderFailure(f"PDF rendering failed ({result})")
        return result
    except EOFError as error:
        raise RenderFailure("PDF renderer process exited without output") from error
    finally:
        parent_connection.close()
        if process.is_alive():
            process.kill()
            process.join(2)


def render_pdf(
    payload: Any,
    *,
    output_directory: Path = OUTPUT_DIRECTORY,
    timeout_seconds: int = RENDER_TIMEOUT_SECONDS,
    max_pdf_bytes: int = MAX_PDF_BYTES,
) -> bytes:
    validated = validate_report_render_payload(payload)
    html = render_report_html(validated)
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    started = time.monotonic()
    descriptor, raw_path = tempfile.mkstemp(
        prefix="report-",
        suffix=".pdf",
        dir=output_directory,
    )
    os.close(descriptor)
    output_path = Path(raw_path)
    browser = None
    try:
        with sync_playwright() as playwright:
            # The renderer is sandboxed by its hardened container boundary.
            # Playwright's bundled Chromium aborts during Linux zygote startup
            # when its internal sandbox is enabled in this environment.
            browser = playwright.chromium.launch(
                headless=True,
                chromium_sandbox=False,
            )
            context = browser.new_context(
                java_script_enabled=False,
                service_workers="block",
            )
            context.route("**/*", _abort_request)
            page = context.new_page()
            page.set_content(
                html,
                wait_until="commit",
                timeout=timeout_seconds * 1_000,
            )
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={
                    "top": "16mm",
                    "right": "14mm",
                    "bottom": "18mm",
                    "left": "14mm",
                },
            )
            context.close()
            browser.close()
            browser = None

        if time.monotonic() - started > timeout_seconds:
            raise RenderTimeout("PDF rendering exceeded the time limit")
        if not output_path.is_file():
            raise RenderFailure("PDF renderer produced no output")
        if output_path.stat().st_size > max_pdf_bytes:
            raise RenderOutputTooLarge("PDF output exceeded the size limit")
        return output_path.read_bytes()
    except PlaywrightTimeoutError as error:
        if browser is not None:
            browser.close()
        raise RenderTimeout("PDF rendering exceeded the time limit") from error
    finally:
        output_path.unlink(missing_ok=True)
