from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


class SmokeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


@dataclass(frozen=True)
class Workspace:
    email: str
    password: str
    organization_name: str
    organization_id: str


def absolute_url(base_url: str, path: str) -> str:
    return urljoin(f"{base_url}/", path.lstrip("/"))


def create_workspace(
    page: Page,
    *,
    base_url: str,
    email: str,
    password: str,
    organization_name: str,
    start_choice: str,
) -> Workspace:
    response = page.goto(absolute_url(base_url, "/accounts/signup/"))
    require(response is not None and response.status == 200, "Signup did not load.")
    page.get_by_label("First name", exact=True).fill("Release")
    page.get_by_label("Last name", exact=True).fill("Verifier")
    page.get_by_label("Work email", exact=True).fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_label("Confirm password", exact=True).fill(password)
    page.get_by_role(
        "button", name="Continue to organization setup", exact=True
    ).click()
    if urlparse(page.url).path != "/workspaces/new/":
        errors = page.locator(".errorlist, .error-panel").all_inner_texts()
        raise SmokeFailure(
            "Signup validation failed: " + " | ".join(errors or ["no form error"])
        )

    page.get_by_label("Organization name", exact=True).fill(organization_name)
    page.get_by_label("Industry", exact=True).select_option("accounting_bookkeeping")
    page.get_by_role("button", name="Continue", exact=True).click()
    page.wait_for_url(re.compile(r"/workspaces/new/start/$"))
    page.locator(f"input[name='start_choice'][value='{start_choice}']").check()
    page.get_by_role("button", name="Review setup", exact=True).click()
    page.wait_for_url(re.compile(r"/workspaces/new/review/$"))
    require(
        organization_name in page.locator("body").inner_text(),
        "Organization review omitted the organization name.",
    )
    page.get_by_role("button", name="Create workspace", exact=True).click()
    page.goto(absolute_url(base_url, "/workspaces/"))

    card = page.locator("article.workspace-card").filter(has_text=organization_name)
    require(card.count() == 1, "Created workspace was not uniquely listed.")
    organization_id = card.locator("input[name='organization_id']").get_attribute(
        "value"
    )
    require(bool(organization_id), "Created workspace identifier was unavailable.")
    with page.expect_navigation():
        card.get_by_role("button").click()
    require(
        urlparse(page.url).path == "/workspaces/",
        "Workspace activation did not return to workspace selection.",
    )
    inventory_response = page.goto(absolute_url(base_url, "/inventory/"))
    require(
        inventory_response is not None and inventory_response.status == 200,
        "Activated workspace inventory did not load.",
    )

    return Workspace(
        email=email,
        password=password,
        organization_name=organization_name,
        organization_id=str(organization_id),
    )


def add_manual_inventory(page: Page, *, base_url: str, item_name: str) -> str:
    page.goto(absolute_url(base_url, "/inventory/add/"))
    page.get_by_label("AI application or agent", exact=True).fill(item_name)
    page.get_by_label("Vendor", exact=True).fill("Stewardence Test Vendor")
    page.get_by_label("Person responsible for this software", exact=True).fill(
        "Release Verifier"
    )
    page.get_by_label("Team or department", exact=True).fill("Bookkeeping")
    page.get_by_label("How many people use it?", exact=True).fill("7")
    page.get_by_label("What does the firm use it for?", exact=True).fill(
        "Verify payroll review and external-transfer controls"
    )
    page.get_by_label("Monthly subscription cost", exact=True).fill("100.00")
    page.get_by_label("Paid seats", exact=True).fill("5")
    page.locator("input[name='connected_systems'][value='payroll']").check()
    page.locator("input[name='connected_systems'][value='banking']").check()
    page.locator("input[name='data_categories'][value='payroll']").check()
    page.locator("input[name='permissions'][value='transmit']").check()
    page.locator("input[name='capabilities'][value='external_transfer']").check()
    page.locator("input[name='autonomy_level'][value='4']").check()
    page.get_by_label("A person must approve important actions", exact=True).uncheck()
    page.get_by_label("How is the firm using it now?", exact=True).select_option(
        "active"
    )
    page.get_by_role("button", name="Save software", exact=True).click()
    page.wait_for_url(re.compile(r"/inventory/[0-9a-f-]+/$"))
    body = page.locator("body").inner_text()
    require(item_name in body, "Manual inventory detail omitted the item.")
    require("Critical" in body, "Expected critical deterministic risk was absent.")
    require(
        "Why did this receive this score?" in body,
        "Risk explanation was absent.",
    )
    return page.url


def import_csv(page: Page, *, base_url: str, item_name: str) -> None:
    csv_payload = (
        "display_name,vendor_name,business_owner,department,user_count,"
        "business_purpose,monthly_cost,seat_count,autonomy_level,"
        "human_approval,status\n"
        f"{item_name},Stewardence Test Vendor,Release Verifier,Operations,3,"
        '"Verify staged CSV approval",25.00,3,2,yes,active\n'
    )
    page.goto(absolute_url(base_url, "/imports/new/"))
    page.locator("input[type='file']").set_input_files(
        {
            "name": "stewardence-smoke.csv",
            "mimeType": "text/csv",
            "buffer": csv_payload.encode(),
        }
    )
    page.get_by_role("button", name="Check spreadsheet", exact=True).click()
    page.wait_for_url(re.compile(r"/imports/[0-9a-f-]+/review/$"))
    require(
        page.get_by_role(
            "heading",
            name="Check and confirm your imported data",
            exact=True,
        ).is_visible(),
        "CSV review step was skipped.",
    )
    page.get_by_role("button", name="Continue to final review", exact=True).click()
    page.wait_for_url(re.compile(r"/imports/[0-9a-f-]+/final/$"))
    require(
        page.get_by_role(
            "heading",
            name="Final review and approval",
            exact=True,
        ).is_visible(),
        "CSV final-approval step was skipped.",
    )
    page.get_by_role("button", name="Save and finish setup", exact=True).click()
    page.wait_for_url(re.compile(r"/inventory/$"))
    require(
        item_name in page.locator("body").inner_text(),
        "Approved CSV item was absent from inventory.",
    )


def create_and_test_rule(
    page: Page,
    *,
    base_url: str,
    rule_name: str,
    item_name: str,
) -> None:
    page.goto(absolute_url(base_url, "/rules/add/"))
    page.get_by_label("Rule name").fill(rule_name)
    page.get_by_label("This software accesses").select_option("payroll")
    page.get_by_label("This software can").select_option("external_transfer")
    page.get_by_label("Minimum risk level").select_option("HIGH")
    page.get_by_label("Require this control").select_option("human_approval")
    page.get_by_label("Finding to create").fill(
        "Payroll transfer lacks recorded human approval."
    )
    page.get_by_label("Review to recommend").fill(
        "Confirm recipient and approval boundaries."
    )
    page.get_by_label("When this rule matches").select_option("FAIL")
    page.get_by_label("Finding severity").select_option("HIGH")
    page.get_by_label("Explain why this matters").fill(
        "Payroll data transfer requires an accountable person."
    )
    page.get_by_label("Recommended next step").fill(
        "Require recorded approval before every external transfer."
    )
    page.get_by_label("Use this rule in assessments").set_checked(True)
    page.get_by_label("Try this rule against").select_option(label=item_name)
    page.get_by_role("button", name="Test without saving", exact=True).click()
    require(
        "Test result:" in page.locator("body").inner_text(),
        "Rule test result was not displayed.",
    )
    page.get_by_role("button", name="Save rule", exact=True).click()
    page.wait_for_url(re.compile(r"/rules/[0-9a-f-]+/$"))
    require(
        rule_name in page.locator("body").inner_text(),
        "Saved rule detail omitted the rule name.",
    )


def create_assessment(page: Page, *, item_url: str) -> str:
    page.goto(urljoin(item_url, "roi/"))
    values = {
        "Monthly subscription cost": "100.00",
        "One-time implementation cost": "1200.00",
        "Months used to spread the implementation cost": "12",
        "Hours saved each month": "10.00",
        "Hourly labor cost including benefits": "50.00",
        "Additional monthly revenue attributable to this software": "200.00",
        "Monthly operational cost avoided": "100.00",
    }
    provenance = {
        "monthly_subscription_cost_provenance": "Customer supplied",
        "implementation_cost_provenance": "Customer supplied",
        "implementation_amortization_months_provenance": "Estimated",
        "hours_saved_per_month_provenance": "Measured",
        "loaded_hourly_rate_provenance": "Customer supplied",
        "attributable_revenue_provenance": "Estimated",
        "avoided_monthly_cost_provenance": "Measured",
    }
    for label, value in values.items():
        page.get_by_label(label, exact=True).fill(value)
    for name, value in provenance.items():
        page.locator(f"select[name='{name}']").select_option(value)

    page.get_by_role("button", name="Calculate ROI", exact=True).click()
    body = page.locator("body").inner_text()
    require("Monthly net value: $600.00" in body, "ROI net value was incorrect.")
    require("300.00%" in body, "ROI percentage was incorrect.")
    page.get_by_role("button", name="Save immutable assessment", exact=True).click()
    page.wait_for_url(re.compile(r"/assessments/[0-9a-f-]+/$"))
    require(
        "Hashes match the stored snapshot" in page.locator("body").inner_text(),
        "Assessment integrity check did not pass.",
    )
    return page.url


def create_report(page: Page) -> tuple[str, str]:
    page.get_by_role("button", name="Open browser report", exact=True).click()
    page.wait_for_url(re.compile(r"/reports/[0-9a-f-]+/$"))
    body = page.locator("body").inner_text()
    for heading in (
        "Executive summary",
        "AI and software inventory",
        "Overall risk overview",
        "Failed and warning policy findings",
        "Return on investment",
        "Evidence sources",
    ):
        require(heading in body, f"Browser report omitted {heading!r}.")
    report_url = page.url
    download_path = page.get_by_role(
        "link", name="Download PDF", exact=True
    ).get_attribute("href")
    require(bool(download_path), "PDF download URL was absent.")
    return report_url, urljoin(report_url, str(download_path))


def wait_for_pdf(context: BrowserContext, download_url: str) -> dict[str, object]:
    deadline = time.monotonic() + 150
    last_status = 0
    while time.monotonic() < deadline:
        response = context.request.get(download_url)
        last_status = response.status
        if response.status == 200:
            content_type = response.headers.get("content-type", "")
            cache_control = response.headers.get("cache-control", "")
            body = response.body()
            require(content_type == "application/pdf", "Download was not a PDF.")
            require(cache_control == "private, no-store", "PDF cache policy changed.")
            require(body.startswith(b"%PDF-"), "Downloaded PDF signature was invalid.")
            return {
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        response.dispose()
        time.sleep(3)
    raise SmokeFailure(f"PDF was not ready; last HTTP status was {last_status}.")


def logout_and_reverify_history(
    page: Page,
    context: BrowserContext,
    *,
    base_url: str,
    workspace: Workspace,
    assessment_url: str,
    report_url: str,
    download_url: str,
) -> None:
    page.get_by_role("button", name="Log out", exact=True).click()
    page.wait_for_url(re.compile(r"/accounts/login/$"))
    page.get_by_label("Email address", exact=True).fill(workspace.email)
    page.get_by_label("Password", exact=True).fill(workspace.password)
    page.get_by_role("button", name="Log in", exact=True).click()
    page.wait_for_url(re.compile(r"/workspaces/$"))
    card = page.locator("article.workspace-card").filter(
        has_text=workspace.organization_name
    )
    with page.expect_navigation():
        card.get_by_role("button").click()
    require(
        urlparse(page.url).path == "/workspaces/",
        "Workspace activation failed after login.",
    )
    inventory_response = page.goto(absolute_url(base_url, "/inventory/"))
    require(
        inventory_response is not None and inventory_response.status == 200,
        "Workspace inventory failed after login.",
    )

    assessment_response = page.goto(assessment_url)
    require(
        assessment_response is not None and assessment_response.status == 200,
        "Historical assessment was not available after login.",
    )
    report_response = page.goto(report_url)
    require(
        report_response is not None and report_response.status == 200,
        "Historical report was not available after login.",
    )
    download_response = context.request.get(download_url)
    require(
        download_response.status == 200,
        "Authorized historical PDF download failed after login.",
    )
    require(
        download_response.body().startswith(b"%PDF-"),
        "Historical download was not a PDF.",
    )


def verify_cross_tenant_denials(
    page: Page,
    context: BrowserContext,
    *,
    base_url: str,
    foreign_organization_id: str,
    item_url: str,
    report_url: str,
    download_url: str,
) -> None:
    item_response = page.goto(item_url)
    require(
        item_response is not None and item_response.status == 404,
        "Foreign inventory detail was not denied.",
    )
    report_response = page.goto(report_url)
    require(
        report_response is not None and report_response.status == 404,
        "Foreign browser report was not denied.",
    )
    download_response = context.request.get(download_url)
    require(
        download_response.status == 404,
        "Foreign PDF download was not denied.",
    )

    page.goto(absolute_url(base_url, "/workspaces/"))
    csrf_cookie = next(
        (
            cookie["value"]
            for cookie in context.cookies()
            if cookie["name"] == "csrftoken"
        ),
        "",
    )
    require(bool(csrf_cookie), "CSRF cookie was absent for activation denial.")
    activation_response = context.request.post(
        absolute_url(base_url, "/workspaces/activate/"),
        form={"organization_id": foreign_organization_id},
        headers={
            "X-CSRFToken": csrf_cookie,
            "Referer": absolute_url(base_url, "/workspaces/"),
        },
    )
    require(
        activation_response.status == 403,
        "Foreign workspace activation was not denied.",
    )


def launch_browser(playwright) -> Browser:
    return playwright.chromium.launch(headless=True)


def main() -> int:
    base_url = os.environ.get(
        "STEWARDENCE_BASE_URL",
        "https://web-production-ef568.up.railway.app",
    ).rstrip("/")
    parsed = urlparse(base_url)
    require(parsed.scheme == "https" and bool(parsed.hostname), "HTTPS URL required.")
    run_id = re.sub(
        r"[^a-zA-Z0-9-]", "-", os.environ.get("STEWARDENCE_SMOKE_RUN_ID", "local")
    )[:48]
    random_suffix = secrets.token_hex(4)
    marker = f"{run_id}-{random_suffix}"
    password_a = f"Stewardence!{secrets.token_urlsafe(24)}7a"
    password_b = f"Stewardence!{secrets.token_urlsafe(24)}7b"
    email_a = f"smoke-{marker}-a@example.com"
    email_b = f"smoke-{marker}-b@example.com"
    organization_a = f"Stewardence Release Smoke A {marker}"
    organization_b = f"Stewardence Release Smoke B {marker}"
    manual_item = f"Payroll Transfer Verifier {marker}"
    csv_item = f"CSV Ledger Verifier {marker}"
    rule_name = f"Payroll Approval Gate {marker}"

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context_a = browser.new_context()
        context_b = browser.new_context()
        page_a = context_a.new_page()
        page_b = context_b.new_page()
        page_a.set_default_timeout(30_000)
        page_b.set_default_timeout(30_000)

        entry_response = page_a.goto(base_url)
        require(
            entry_response is not None and entry_response.status == 200,
            "Public HTTPS entry failed.",
        )
        require(
            entry_response.headers.get("strict-transport-security", ""),
            "HSTS header was absent.",
        )
        require(
            entry_response.headers.get("x-frame-options") == "DENY",
            "Frame-denial header changed.",
        )
        entry_body = page_a.locator("body").inner_text()
        require("Stewardence" in entry_body, "Current brand was absent.")
        require("AgentLedger" not in entry_body, "Retired brand leaked publicly.")

        workspace_a = create_workspace(
            page_a,
            base_url=base_url,
            email=email_a,
            password=password_a,
            organization_name=organization_a,
            start_choice="manual",
        )
        item_url = add_manual_inventory(
            page_a,
            base_url=base_url,
            item_name=manual_item,
        )
        import_csv(page_a, base_url=base_url, item_name=csv_item)
        create_and_test_rule(
            page_a,
            base_url=base_url,
            rule_name=rule_name,
            item_name=manual_item,
        )
        assessment_url = create_assessment(page_a, item_url=item_url)
        report_url, download_url = create_report(page_a)
        pdf_evidence = wait_for_pdf(context_a, download_url)
        logout_and_reverify_history(
            page_a,
            context_a,
            base_url=base_url,
            workspace=workspace_a,
            assessment_url=assessment_url,
            report_url=report_url,
            download_url=download_url,
        )

        create_workspace(
            page_b,
            base_url=base_url,
            email=email_b,
            password=password_b,
            organization_name=organization_b,
            start_choice="explore",
        )
        verify_cross_tenant_denials(
            page_b,
            context_b,
            base_url=base_url,
            foreign_organization_id=workspace_a.organization_id,
            item_url=item_url,
            report_url=report_url,
            download_url=download_url,
        )
        browser.close()

    print(
        json.dumps(
            {
                "status": "PASS",
                "base_url": base_url,
                "run_marker": marker,
                "synthetic_accounts": [email_a, email_b],
                "pdf": pdf_evidence,
                "checks": [
                    "https_and_security_headers",
                    "signup_and_login",
                    "guided_workspace_setup",
                    "manual_inventory_and_risk_explanation",
                    "csv_three_step_approval",
                    "rule_test_and_save",
                    "roi_arithmetic_and_immutable_assessment",
                    "browser_report_and_private_pdf",
                    "logout_login_and_historical_retrieval",
                    "cross_tenant_inventory_report_download_and_activation_denials",
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
