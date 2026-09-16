"""Pure tests for the feature-gated WhatsApp invitation primitives."""

import hashlib
import hmac
import unittest
import uuid

# The application import establishes the repository's normal CRM blueprint
# initialization order; standalone CRM/private-training reverse imports retain
# their pre-existing behavior.
import system_app.app  # noqa: F401

from system_app.private_training.routes import _whatsapp_message
from system_app.private_training.services import (
    PrivateTrainingPhoneError,
    _deterministic_portal_token,
    normalize_whatsapp_phone,
)


class WhatsAppPhoneTests(unittest.TestCase):
    def test_egyptian_mobile_formats(self):
        expected = "201012345678"
        for value in ("01012345678", "+201012345678", "00201012345678", "201012345678", "(010) 123-45678"):
            self.assertEqual(normalize_whatsapp_phone(value), expected)
        self.assertEqual(normalize_whatsapp_phone("011 1234 5678"), "201112345678")
        self.assertEqual(normalize_whatsapp_phone("012-123-45678"), "201212345678")
        self.assertEqual(normalize_whatsapp_phone("01512345678"), "201512345678")

    def test_rejects_missing_malformed_landline_and_ambiguous(self):
        for value in (None, "", "010123", "0223456789", "20101234567", "0101234567x", "2010123456789"):
            with self.subTest(value=value):
                with self.assertRaises(PrivateTrainingPhoneError):
                    normalize_whatsapp_phone(value)

    def test_explicit_international_number_is_digits_only(self):
        self.assertEqual(normalize_whatsapp_phone("+14155552671"), "14155552671")
        with self.assertRaises(PrivateTrainingPhoneError):
            normalize_whatsapp_phone("14155552671")


class DeterministicTokenTests(unittest.TestCase):
    def test_same_context_reconstructs_the_same_hash_only_token(self):
        operation = uuid.UUID("11111111-1111-4111-8111-111111111111")
        first = _deterministic_portal_token("x" * 32, operation, 7, 21, 25)
        second = _deterministic_portal_token("x" * 32, operation, 7, 21, 25)
        self.assertEqual(first, second)
        self.assertTrue(hmac.compare_digest(hashlib.sha256(first.encode()).hexdigest(), hashlib.sha256(second.encode()).hexdigest()))

    def test_weak_key_is_rejected(self):
        with self.assertRaises(Exception):
            _deterministic_portal_token("weak", uuid.uuid4(), 1, 2, 3)


class WhatsAppMessageTests(unittest.TestCase):
    def test_assigned_trainer_is_used_not_checkin_user(self):
        message = _whatsapp_message(
            {"client_name": "Member", "trainer_display_name": "Hossam"},
            {"workout_name": "Leg Day", "trainer_display_name": "Rino"},
            "https://example.test/portal",
        )
        self.assertIn("المدرب: Hossam", message)
        self.assertNotIn("المدرب: Rino", message)

    def test_missing_assigned_trainer_omits_the_line(self):
        message = _whatsapp_message(
            {"client_name": "Member"}, {"workout_name": "Leg Day"}, "https://example.test/portal"
        )
        self.assertNotIn("المدرب:", message)


if __name__ == "__main__":
    unittest.main()
