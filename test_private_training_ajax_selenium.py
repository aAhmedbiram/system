import threading
import time
import unittest

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFProtect
from werkzeug.serving import make_server


class LocalPrivateTrainingServer:
    """Isolated local app rendering the production subscription template."""

    def __init__(self):
        self.app = Flask(
            "private_training_real_template_fixture",
            template_folder="system_app/templates",
            static_folder="system_app/static",
        )
        self.app.secret_key = "local-browser-test-only"
        self.csrf = CSRFProtect(self.app)
        self.checkin_count = 0
        self.session_id = 25
        self.slow = False
        self.whatsapp_enabled = False
        self.ambiguous_once = False
        self.operations = {}
        self.received_operations = []
        self._configure_routes()
        self.server = make_server("127.0.0.1", 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def _configure_routes(self):
        @self.app.route("/private-training/subscriptions", endpoint="private_training.subscription_list")
        def subscription_list():
            return "subscription list"

        @self.app.route("/private-training/my-clients", endpoint="private_training.my_clients")
        def my_clients():
            return "my clients"

        @self.app.route("/private-training/subscriptions/new", endpoint="private_training.new_subscription")
        def new_subscription():
            return "new subscription"

        @self.app.route("/", endpoint="index")
        def index():
            return "home"

        @self.app.route("/logout", endpoint="logout")
        def logout():
            return "logout"

        @self.app.route(
            "/private-training/subscriptions/21/cancel",
            methods=["POST"],
            endpoint="private_training.cancel_subscription",
        )
        def cancel_subscription():
            return "normal cancel", 200

        @self.app.route(
            "/private-training/subscriptions/21/portal-token",
            methods=["POST"],
            endpoint="private_training.generate_subscription_portal_token",
        )
        def generate_subscription_portal_token():
            return "normal portal", 200

        @self.app.route(
            "/private-training/subscriptions/21/portal-token/revoke",
            methods=["POST"],
            endpoint="private_training.revoke_subscription_portal_token",
        )
        def revoke_subscription_portal_token():
            return "normal revoke", 200

        @self.app.route("/private-training/subscriptions/21", endpoint="private_training.subscription_detail")
        def detail():
            return render_template(
                "private_training/subscription_detail.html",
                subscription=self._subscription(),
                current_user={
                    "username": "trainer_one",
                    "permissions": {"private_training_trainer": True},
                },
                user_permissions={"private_training_manage": True, "super_admin": False},
                can_cancel_subscription=True,
                can_manage_tokens=True,
                can_check_in=True,
                check_in_status_message=None,
                pending_session=None,
                portal_link_status="No active link",
                show_generate_result=False,
                generated_portal_url=None,
                sessions=self._sessions(),
                private_training_whatsapp_checkin_enabled=self.whatsapp_enabled,
            )

        @self.app.route(
            "/private-training/subscriptions/21/check-in",
            methods=["POST"],
            endpoint="private_training.check_in_subscription",
        )
        @self.csrf.exempt
        def check_in():
            operation_id = request.form.get("client_operation_id")
            if operation_id:
                self.received_operations.append(operation_id)
            workout = request.form.get("workout_name", "")
            if self.slow:
                time.sleep(0.5)
            if self.whatsapp_enabled and operation_id in self.operations:
                payload = dict(self.operations[operation_id])
                payload["replayed"] = True
                return jsonify(payload)
            self.checkin_count += 1
            if workout == "bad":
                return jsonify(
                    ok=False,
                    error="validation_error",
                    message="Please enter a valid workout name.",
                ), 400
            self.session_id += 1
            session_row = {
                "id": self.session_id, "trainer": "Trainer One",
                "checked_in_at": "2026-09-15T18:19:07+00:00", "workout_name": workout,
                "status": "PENDING_MEMBER_APPROVAL", "approved_at": None,
            }
            payload = {
                "ok": True,
                "message": "Session created and WhatsApp invitation prepared." if self.whatsapp_enabled else "Private training session check-in created successfully.",
                "replayed": False,
                "subscription": {"id": 21, "total_sessions": 37, "approved_sessions": 1, "remaining_sessions": 36, "pending_sessions": 1, "effective_status": "ACTIVE"},
                "session": session_row,
                "sessions": [session_row],
            }
            if self.whatsapp_enabled:
                from urllib.parse import urlencode
                import urllib.parse
                portal = f"{self.url}/private-training/member/test-token"
                text = "مرحبًا Long Test Client Name 👋\n\nتم تسجيل جلسة الـ Private Training الخاصة بك.\nالتمرين: {}\nالمدرب: Trainer One With A Long Name\n\nبرجاء فتح الرابط التالي ومراجعة الجلسة وتأكيدها:\n{}\n\nRival Gym 💪".format(workout, portal)
                payload["whatsapp"] = {"url": "https://wa.me/2010012345678?" + urlencode({"text": text})}
                self.operations[operation_id] = dict(payload)
                if self.ambiguous_once:
                    self.ambiguous_once = False
                    return jsonify(ok=False, error="temporary_database_error", message="The result could not be confirmed. Check Session History before trying again."), 503
            return jsonify(payload)

    def _subscription(self):
        return {
            "id": 21,
            "client_type": "MEMBER",
            "client_name": "Long Test Client Name",
            "member_name": "Long Test Client Name",
            "member_id": 7,
            "member_phone": "+20 100 123 4567",
            "gym_membership_packages": "Premium",
            "gym_membership_status": "ACTIVE",
            "gym_starting_date": "2026-01-01",
            "gym_end_date": "2026-12-31",
            "trainer_display_name": "Trainer One With A Long Name",
            "trainer_username": "trainer_one",
            "created_by_display_name": "Admin User",
            "created_by_username": "admin",
            "private_start_date": "2026-09-01",
            "private_expiry_date": "2026-12-31",
            "total_sessions": 37,
            "approved_count": 0,
            "remaining_sessions": 37,
            "pending_count": 0,
            "effective_status": "ACTIVE",
        }

    def _sessions(self):
        return [{
            "id": 25,
            "trainer_display_name": "Trainer One With A Long Name",
            "trainer_username": "trainer_one",
            "checked_in_at": "2026-09-14 18:19:07+00:00",
            "workout_name": "A deliberately long workout name for wrapping",
            "status": "APPROVED",
            "approved_at": "2026-09-14 19:00:00+00:00",
        }]


class TestPrivateTrainingAjaxSelenium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        cls.fixture = LocalPrivateTrainingServer()
        cls.fixture.start()
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        cls.driver = webdriver.Chrome(options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.fixture.stop()

    def setUp(self):
        self.fixture.checkin_count = 0
        self.fixture.session_id = 25
        self.fixture.slow = False
        self.fixture.whatsapp_enabled = False
        self.fixture.ambiguous_once = False
        self.fixture.operations = {}
        self.fixture.received_operations = []

    def open_at(self, width, height):
        self.driver.set_window_size(width, height)
        self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
        })
        self.driver.get(f"{self.fixture.url}/private-training/subscriptions/21")
        time.sleep(0.25)

    def assert_mobile_layout(self, width):
        from selenium.webdriver.common.by import By

        driver = self.driver
        self.open_at(width, 900 if width >= 430 else 800)
        metrics = driver.execute_script("""
            const page = document.querySelector('.page');
            const cards = [...document.querySelectorAll('.card, .panel, .hero')];
            const form = document.getElementById('private-training-checkin-form');
            const button = document.getElementById('private-training-checkin-submit');
            const input = document.getElementById('workout_name');
            const history = document.querySelector('.table-wrap');
            const actions = document.querySelector('.actions');
            return {
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                pageRight: page.getBoundingClientRect().right,
                cardsWithin: cards.every(card => card.getBoundingClientRect().right <= window.innerWidth + 1),
                actionsHeight: actions.getBoundingClientRect().height,
                buttonHeight: button.getBoundingClientRect().height,
                inputHeight: input.getBoundingClientRect().height,
                formVisible: !!form && form.getBoundingClientRect().width > 0,
                historyScrollWidth: history.scrollWidth,
                historyClientWidth: history.clientWidth,
            };
        """)
        self.assertLessEqual(metrics["scrollWidth"], metrics["clientWidth"], width)
        self.assertTrue(metrics["cardsWithin"], width)
        self.assertLessEqual(metrics["pageRight"], width + 1, width)
        self.assertGreater(metrics["actionsHeight"], 44, width)
        self.assertGreaterEqual(metrics["buttonHeight"], 43, width)
        self.assertGreaterEqual(metrics["inputHeight"], 43, width)
        self.assertTrue(metrics["formVisible"], width)
        self.assertGreater(metrics["historyScrollWidth"], metrics["historyClientWidth"], width)
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, ".table-wrap").is_displayed())

    def test_real_template_layout_at_all_required_viewports(self):
        for width, height in ((320, 800), (360, 800), (390, 844), (430, 900), (768, 900)):
            with self.subTest(width=width):
                self.assert_mobile_layout(width)

    def test_real_template_ajax_checkin_preserves_mobile_page(self):
        from selenium.webdriver.common.by import By

        driver = self.driver
        self.open_at(390, 844)
        form = driver.find_element(By.ID, "private-training-checkin-form")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", form)
        initial_url = driver.current_url
        initial_navigation_count = driver.execute_script(
            "return performance.getEntriesByType('navigation').length"
        )
        initial_scroll = driver.execute_script("return window.scrollY")
        initial_rows = len(driver.find_elements(By.CSS_SELECTOR, "#private-training-session-history-body tr"))
        driver.find_element(By.ID, "workout_name").send_keys("Leg Day")
        driver.find_element(By.ID, "private-training-checkin-submit").click()
        deadline = time.time() + 4
        while self.fixture.checkin_count < 1 and time.time() < deadline:
            time.sleep(0.05)
        while not driver.find_element(By.ID, "private-training-checkin-message").text and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.fixture.checkin_count, 1)
        self.assertEqual(driver.current_url, initial_url)
        self.assertEqual(
            driver.execute_script("return performance.getEntriesByType('navigation').length"),
            initial_navigation_count,
        )
        self.assertLessEqual(abs(driver.execute_script("return window.scrollY") - initial_scroll), 12)
        self.assertEqual(driver.find_element(By.ID, "private-training-remaining-count").text, "36")
        self.assertEqual(driver.find_element(By.ID, "private-training-pending-count").text, "1")
        self.assertEqual(
            len(driver.find_elements(By.CSS_SELECTOR, "#private-training-session-history-body tr")),
            initial_rows + 1,
        )
        self.assertEqual(driver.find_element(By.ID, "workout_name").get_attribute("value"), "")

        driver.find_element(By.ID, "workout_name").send_keys("bad")
        validation_scroll = driver.execute_script("return window.scrollY")
        driver.find_element(By.ID, "private-training-checkin-submit").click()
        time.sleep(0.3)
        self.assertIn("Please enter a valid workout name.", driver.find_element(By.ID, "private-training-checkin-error").text)
        self.assertEqual(driver.find_element(By.ID, "workout_name").get_attribute("value"), "bad")
        self.assertLessEqual(abs(driver.execute_script("return window.scrollY") - validation_scroll), 12)
        self.assertEqual(self.fixture.checkin_count, 2)

        self.fixture.slow = True
        driver.find_element(By.ID, "workout_name").clear()
        driver.find_element(By.ID, "workout_name").send_keys("Slow Day")
        driver.execute_script(
            "const f=document.getElementById('private-training-checkin-form'); f.requestSubmit(); f.requestSubmit();"
        )
        time.sleep(1.2)
        self.assertEqual(self.fixture.checkin_count, 3)
        self.assertIsNone(driver.find_element(By.CSS_SELECTOR, 'form[action*="/cancel"]').get_attribute("data-private-training-checkin-ajax"))
        self.assertEqual(
            len(driver.find_elements(By.CSS_SELECTOR, 'form[action*="/portal-token"]')),
            2,
        )

    def test_feature_enabled_real_template_whatsapp_success_and_same_uuid_replay(self):
        from selenium.webdriver.common.by import By
        from urllib.parse import parse_qs, unquote, urlparse

        self.fixture.whatsapp_enabled = True
        self.fixture.ambiguous_once = True
        driver = self.driver
        self.open_at(390, 844)
        form = driver.find_element(By.ID, "private-training-checkin-form")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", form)
        original_url = driver.current_url
        original_navigation_count = driver.execute_script("return performance.getEntriesByType('navigation').length")
        original_scroll = driver.execute_script("return window.scrollY")
        driver.find_element(By.ID, "workout_name").send_keys("Arabic Test & Legs")
        driver.find_element(By.ID, "private-training-checkin-submit").click()
        deadline = time.time() + 4
        while len(self.fixture.received_operations) < 1 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(self.fixture.received_operations), 1)
        first_operation = self.fixture.received_operations[0]
        self.assertTrue(first_operation)
        self.assertEqual(driver.find_element(By.ID, "workout_name").get_attribute("value"), "Arabic Test & Legs")
        while not driver.find_element(By.ID, "private-training-checkin-error").text and time.time() < deadline:
            time.sleep(0.05)
        self.assertIn("Check Session History", driver.find_element(By.ID, "private-training-checkin-error").text)
        self.assertEqual(self.fixture.checkin_count, 1)

        driver.find_element(By.ID, "private-training-checkin-submit").click()
        deadline = time.time() + 4
        while not driver.find_element(By.ID, "private-training-checkin-form").get_attribute("hidden") and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.fixture.received_operations, [first_operation, first_operation])
        self.assertEqual(self.fixture.checkin_count, 1)
        self.assertEqual(driver.current_url, original_url)
        self.assertEqual(driver.execute_script("return performance.getEntriesByType('navigation').length"), original_navigation_count)
        self.assertLessEqual(abs(driver.execute_script("return window.scrollY") - original_scroll), 16)
        self.assertEqual(driver.find_element(By.ID, "workout_name").get_attribute("value"), "")
        fallback = driver.find_element(By.ID, "private-training-whatsapp-link")
        whatsapp_url = fallback.get_attribute("href")
        parsed = urlparse(whatsapp_url)
        self.assertEqual(parsed.netloc, "wa.me")
        self.assertEqual(parsed.path, "/2010012345678")
        decoded_message = parse_qs(parsed.query)["text"][0]
        self.assertIn("مرحبًا Long Test Client Name", decoded_message)
        self.assertIn("Arabic Test & Legs", decoded_message)
        self.assertIn("Trainer One With A Long Name", decoded_message)
        self.assertIn("/private-training/member/test-token", decoded_message)
        self.assertNotIn("subscription", decoded_message.lower())
        self.assertNotIn("session_id", decoded_message.lower())
        self.assertIn("noopener", fallback.get_attribute("rel"))
        self.assertIn("noreferrer", fallback.get_attribute("rel"))

    def test_feature_enabled_popup_failure_keeps_fallback_without_resubmit(self):
        from selenium.webdriver.common.by import By

        self.fixture.whatsapp_enabled = True
        driver = self.driver
        self.open_at(390, 844)
        driver.execute_script("window.open = () => null;")
        driver.find_element(By.ID, "workout_name").send_keys("Popup Fallback")
        driver.find_element(By.ID, "private-training-checkin-submit").click()
        deadline = time.time() + 4
        while self.fixture.checkin_count < 1 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.fixture.checkin_count, 1)
        while not driver.find_element(By.ID, "private-training-whatsapp-fallback").is_displayed() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(driver.find_element(By.ID, "private-training-whatsapp-fallback").is_displayed())
        first_url = driver.find_element(By.ID, "private-training-whatsapp-link").get_attribute("href")
        driver.find_element(By.ID, "private-training-whatsapp-link").click()
        time.sleep(0.2)
        self.assertEqual(self.fixture.checkin_count, 1)
        self.assertEqual(driver.current_url, f"{self.fixture.url}/private-training/subscriptions/21")
        self.assertEqual(driver.find_element(By.ID, "private-training-whatsapp-link").get_attribute("href"), first_url)


if __name__ == "__main__":
    unittest.main()
