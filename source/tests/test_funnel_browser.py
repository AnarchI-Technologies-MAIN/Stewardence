"""Real Chromium against candidate Django-rendered HTML and exact local assets.

This qualifies the preview presentation/interaction, not middleware/deployment.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
import os

import pytest
from django.test import RequestFactory
from playwright.sync_api import sync_playwright

from apps.funnels.views import experience


@pytest.mark.skipif(os.getenv("STEWARDENCE_REAL_PDF_QUALIFICATION") != "1", reason="Actual Chromium qualification image required")
@pytest.mark.parametrize("scenario", ["tool-exposure","decision-owner","offboarding-evidence","review-changes"])
@pytest.mark.parametrize("width", [390,768,1280])
def test_candidate_preview_keyboard_privacy_and_mobile(settings,scenario,width):
    settings.FUNNEL_PREVIEW_ENABLED=True
    settings.DEBUG=True
    settings.FUNNEL_DEVELOPMENT_PREVIEW=True
    request=RequestFactory().get("/explore/preview/"+scenario+"/?audience=freelancer&campaign_audience=accounting")
    request.user=SimpleNamespace(is_authenticated=False,is_staff=False,is_superuser=False)
    response=experience(request,scenario,preview=True)
    static=Path(__file__).resolve().parents[1]/"static"
    assets={"/":(response.content,"text/html; charset=utf-8"),
        "/static/funnels.css":((static/"funnels.css").read_bytes(),"text/css"),
        "/static/funnels.js":((static/"funnels.js").read_bytes(),"application/javascript")}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in assets:
                self.send_error(404);return
            body,content_type=assets[self.path]
            self.send_response(200)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(body)))
            if self.path=="/":
                for name,value in response.items():
                    if name.lower()!="content-type":self.send_header(name,value)
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args):
            pass

    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                context=browser.new_context(viewport={"width":width,"height":900},reduced_motion="reduce",service_workers="block")
                page=context.new_page();requests=[];errors=[]
                page.on("request",lambda req:requests.append((req.method,req.url)))
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(origin+"/",wait_until="networkidle")
                initial_requests=list(requests)
                assert not errors
                assert page.locator("#audience").input_value()=="freelancer"
                assert "consultant" in page.locator("#context-copy").inner_text()
                page.locator("#audience").select_option("accounting")
                assert "bookkeeping" in page.locator("#context-copy").inner_text()
                page.locator("#audience").select_option("small_business")
                assert "customer handoff" in page.locator("#context-copy").inner_text()
                assert page.locator(".cta").is_disabled()
                assert not page.locator('a[href*="billing"]').count()
                page.locator("#scenario-start").focus();page.keyboard.press("Enter")
                assert page.locator("#scenario-question").evaluate("node=>node===document.activeElement")
                first=page.locator("#scenario-choices button").first
                first.focus();page.keyboard.press("Enter")
                assert first.get_attribute("aria-pressed")=="true"
                assert not page.locator("#scenario-next").is_disabled()
                evidence=Path("/qualification-evidence")
                if evidence.is_dir() and width in (390,1280):
                    page.screenshot(path=str(evidence/f"funnel-{scenario}-{width}-choice.png"),full_page=True)
                page.locator("#scenario-next").focus();page.keyboard.press("Enter")
                page.locator("#scenario-skip").focus();page.keyboard.press("Enter")
                assert "scenario complete" in page.locator("#scenario-progress").inner_text()
                assert "establish no facts" in page.locator("#scenario-takeaway").inner_text()
                if evidence.is_dir() and width in (390,1280):
                    page.screenshot(path=str(evidence/f"funnel-{scenario}-{width}-completed.png"),full_page=True)
                page.locator("#context").fill("synthetic private draft sentinel")
                page.locator("#details").fill("not sent or saved")
                page.locator("#clear").click()
                assert page.locator("#context").input_value()==page.locator("#details").input_value()==""
                assert page.locator("#scenario-flow").is_hidden()
                page.locator("#context").fill("second synthetic unsaved sentinel")
                page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide'))")
                assert page.locator("#context").input_value()==""
                assert page.evaluate("localStorage.length===0 && sessionStorage.length===0")
                assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert all(method=="GET" and url.startswith(origin+"/") for method,url in requests)
                assert requests==initial_requests
                assert not errors
                evidence=Path("/qualification-evidence")
                if evidence.is_dir():
                    page.screenshot(path=str(evidence/f"funnel-{scenario}-{width}.png"),full_page=True)
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
