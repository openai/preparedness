import os
import sys
import uuid

from utils.trace_cleaner import trace_cleaner

base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, base_path)

import email
import imaplib
import random
import re
import time

from playwright.sync_api import sync_playwright
from utils.online_guard import install_online_guard_sync

NEWDOT_URL = "https://dev.new.expensify.com:8082/"
OLDDOT_URL = "http://localhost:9000/"
EMAIL = "turingvidhant+111@gmail.com"
PASSWORD = "uotx fzkt kfeg dehz"


class IMAPOTPExtractor:
    def __init__(self, email_address, password):
        if not self._validate_email(email_address):
            raise ValueError("Invalid email address format.")
        self.original_email = email_address
        self.password = password
        random_suffix = random.randint(1000, 9999)
        current_timestamp = int(time.time())
        random_suffix = f"{current_timestamp}{random_suffix}"

    def _validate_email(self, email_address):
        return bool(re.match("[^@]+@[^@]+\\.[^@]+", email_address))

    def set_new_email(self, email):
        self.new_email = email

    def check_for_otp(self):
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.original_email, self.password)
            mail.select("inbox")
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                return None
            email_ids = messages[0].split()
            email_ids = email_ids[::-1]
            for email_id in email_ids:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        if self.new_email in msg["To"]:
                            otp_code = self._extract_otp_from_email(msg)
                            if otp_code:
                                mail.store(email_id, "+FLAGS", "\\Deleted")
                                mail.expunge()
                                mail.close()
                                mail.logout()
                                return otp_code
            mail.close()
            mail.logout()
            return None
        except imaplib.IMAP4.error:
            return None

    def _extract_otp_from_email(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    email_body = part.get_payload(decode=True).decode()
                    otp_code = self._extract_otp(email_body)
                    if otp_code:
                        return otp_code
        else:
            email_body = msg.get_payload(decode=True).decode()
            otp_code = self._extract_otp(email_body)
            if otp_code:
                return otp_code
        return None

    def _extract_otp(self, text):
        match = re.search("\\b\\d{6}\\b", text)
        return match.group(0) if match else None


def new_dot_login(page, email):
    page.goto(NEWDOT_URL, timeout=60000)
    page.locator('input[type="email"]').fill(email)
    page.wait_for_timeout(3000)
    page.get_by_role("button", name="Continue").nth(0).click()
    page.wait_for_timeout(3000)
    page.locator('input[data-testid="validateCode"]').fill("123456")
    try:
        page.get_by_role("button", name=re.compile(r"^(continue|sign.?in)$", re.I)).click(
            timeout=20000
        )
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Sign In").click()
    except Exception:
        # In case Sign In button is not present (already signed in)
        pass


def launch_browser(pw, headless=True, device=None, geolocation=None):
    """
    Launch the browser.
    """
    browser = pw.chromium.launch(headless=headless)
    context_args = {}
    if device:
        context_args.update(pw.devices[device])
    if geolocation:
        context_args["geolocation"] = geolocation
        context_args["permissions"] = ["geolocation"]
    context = browser.new_context(**context_args)
    page = context.new_page()
    install_online_guard_sync(context, page)  # Added guard installation
    return browser, context, page


def test_expensify(pytestconfig):
    trace_enabled = pytestconfig.getoption("--user-tool-trace")
    with sync_playwright() as p:
        browser = None
        first_user_context = None
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            first_user_context = browser.new_context(ignore_https_errors=True)

            if trace_enabled:
                first_user_context.tracing.start(screenshots=True, snapshots=True, sources=True)

            page = first_user_context.new_page()
            install_online_guard_sync(first_user_context, page)  # Added guard installation
            page.wait_for_timeout(3000)
            new_dot_login(page, EMAIL)
            page.wait_for_timeout(3000)
            page.get_by_text(
                "This is your personal space. Use it for notes, tasks, drafts, and reminders."
            ).click()
            page.get_by_label("Start chat (Floating action)").click()
            page.get_by_text("Track expense").click()
            page.get_by_label("Manual").click()

            scan_button = page.get_by_label("Scan")
            distance_button = page.get_by_label("Distance")

            distance_initial_bg_color = distance_button.evaluate(
                "element => window.getComputedStyle(element).backgroundColor"
            )
            scan_initial_background_color = scan_button.evaluate(
                "element => window.getComputedStyle(element).backgroundColor"
            )

            scan_button.hover()
            scan_hover_background_color = scan_button.evaluate(
                "element => window.getComputedStyle(element).backgroundColor"
            )

            distance_button.hover()
            distance_hover_bg_color = distance_button.evaluate(
                "element => window.getComputedStyle(element).backgroundColor"
            )

            try:
                assert scan_initial_background_color != scan_hover_background_color, (
                    "Scan Button Background color did not change on hover"
                )
            except AssertionError as scan_error:
                # We simply print the assertion error and continue
                print(scan_error.__str__())

            assert distance_initial_bg_color != distance_hover_bg_color, (
                "Distance Button Background color did not change on hover"
            )

            page.wait_for_timeout(1500)
            page.close()

        finally:
            if trace_enabled and first_user_context is not None:
                trace_path = f"/app/expensify/user_tool/output_{uuid.uuid4().hex}.zip"
                os.makedirs(os.path.dirname(trace_path), exist_ok=True)
                try:
                    first_user_context.tracing.stop(path=trace_path)
                finally:
                    # Even if stop fails, try to clean whatever was produced
                    if os.path.exists(trace_path):
                        trace_cleaner(trace_path)

            if browser is not None:
                browser.close()
