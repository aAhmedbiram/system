import json
import unittest
from pathlib import Path

from PIL import Image
from flask import Response

from system_app.app import app, _inject_pwa_markup_into_html


class TestPWAPhase1(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_01_manifest_exposes_installable_metadata(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/manifest+json", response.content_type)

        manifest = json.loads(response.data.decode())
        self.assertEqual(manifest["name"], "Rival Gym System")
        self.assertEqual(manifest["short_name"], "Rival Gym")
        self.assertEqual(manifest["id"], "/")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["orientation"], "any")
        self.assertEqual(manifest["theme_color"], "#0a0a0a")
        self.assertEqual(manifest["background_color"], "#0a0a0a")

        icon_sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertEqual(icon_sizes, {"192x192", "512x512"})
        purposes = {icon["purpose"] for icon in manifest["icons"]}
        self.assertEqual(purposes, {"any", "maskable"})

    def test_02_service_worker_is_root_scoped_and_network_only_for_navigation(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/javascript", response.content_type)
        self.assertEqual(response.headers.get("Service-Worker-Allowed"), "/")

        sw = response.data.decode()
        self.assertIn("rival-pwa-static-v1", sw)
        self.assertIn("request.method !== 'GET'", sw)
        self.assertIn("request.mode === 'navigate'", sw)
        self.assertIn("event.respondWith(fetch(request));", sw)
        self.assertIn("/static/icon-192.png", sw)
        self.assertIn("/static/icon-512.png", sw)
        self.assertIn("/static/icon-maskable-512.png", sw)
        self.assertIn("/static/apple-touch-icon.png", sw)
        self.assertIn("/manifest.webmanifest", sw)
        self.assertIn("/static/manifest.webmanifest", sw)
        self.assertIn("/static/js/ui-enhancements.js", sw)
        self.assertNotIn("/private-training/member/", sw)

    def test_03_login_and_logout_pages_expose_pwa_metadata(self):
        login_response = self.client.get("/login")
        self.assertEqual(login_response.status_code, 200)
        login_html = login_response.data.decode()
        self.assertIn('rel="manifest"', login_html)
        self.assertIn('href="/manifest.webmanifest"', login_html)
        self.assertIn('name="theme-color"', login_html)
        self.assertIn('href="/static/apple-touch-icon.png"', login_html)
        self.assertIn("apple-mobile-web-app-capable", login_html)
        self.assertIn("apple-mobile-web-app-status-bar-style", login_html)
        self.assertIn("apple-mobile-web-app-title", login_html)
        self.assertIn("navigator.serviceWorker.register('/sw.js'", login_html)
        self.assertIn("scope: '/'", login_html)

        logout_response = self.client.get("/logout", follow_redirects=True)
        self.assertEqual(logout_response.status_code, 200)
        logout_html = logout_response.data.decode()
        self.assertIn('rel="manifest"', logout_html)
        self.assertIn("navigator.serviceWorker.register('/sw.js'", logout_html)

    def test_04_private_training_member_portal_is_not_augmented_by_pwa_injection(self):
        with app.test_request_context("/private-training/member/demo-token"):
            response = Response("<html><head></head><body></body></html>", mimetype="text/html")
            output = _inject_pwa_markup_into_html(response)
            html = output.get_data(as_text=True)
            self.assertNotIn('rel="manifest"', html)
            self.assertNotIn("navigator.serviceWorker.register", html)
            self.assertNotIn("apple-mobile-web-app-capable", html)

    def test_05_generated_icon_assets_exist_and_match_sizes(self):
        icon_192 = Image.open(Path("system_app/static/icon-192.png"))
        icon_512 = Image.open(Path("system_app/static/icon-512.png"))
        icon_maskable = Image.open(Path("system_app/static/icon-maskable-512.png"))
        apple_icon = Image.open(Path("system_app/static/apple-touch-icon.png"))

        self.assertEqual(icon_192.size, (192, 192))
        self.assertEqual(icon_512.size, (512, 512))
        self.assertEqual(icon_maskable.size, (512, 512))
        self.assertEqual(apple_icon.size, (180, 180))


if __name__ == "__main__":
    unittest.main()
