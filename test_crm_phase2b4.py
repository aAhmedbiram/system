import unittest
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase2B4(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_view_user', 'crm_edit_user', 'regular_user')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_view_user', 'view@test.com', 'pwd', TRUE, '{"crm_view": true}'),
            (20003, 'crm_edit_user', 'edit@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_edit": true}'),
            (20004, 'regular_user', 'reg@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

        # Clean leads and members
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE id = 50001", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE id = 50001", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20002, 20003, 20004)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def test_edit_ui_visibility_crm_edit_allowed(self):
        """Lead detail page shows Edit UI under crm_edit permission."""
        self.login_as('crm_edit_user', 20003)
        res = self.client.get('/crm/leads/101/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'openEditModalBtn', res.data)
        self.assertIn(b'editLeadModal', res.data)

    def test_edit_ui_visibility_crm_view_only_hidden(self):
        """Lead detail page hides Edit UI for view-only users."""
        self.login_as('crm_view_user', 20002)
        res = self.client.get('/crm/leads/101/view')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'openEditModalBtn', res.data)
        self.assertNotIn(b'editLeadModal', res.data)

    def test_patch_success_and_persistance(self):
        """Valid PATCH fields succeed and persist modifications."""
        self.login_as('crm_edit_user', 20003)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (101, 'Old Name', '111', 'WALK_IN', 'NEW', 20003)", commit=True
        )

        res = self.client.patch('/crm/leads/101', json={
            "name": "Updated Name",
            "phone": "999",
            "email": "updated@test.com",
            "source": "INSTAGRAM",
            "notes": "some notes"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['status'], 'updated')

        # Read back
        lead = query_db("SELECT * FROM crm_leads WHERE id = 101", one=True)
        self.assertEqual(lead['name'], 'Updated Name')
        self.assertEqual(lead['phone'], '999')
        self.assertEqual(lead['email'], 'updated@test.com')
        self.assertEqual(lead['source'], 'INSTAGRAM')
        self.assertEqual(lead['notes'], 'some notes')

    def test_patch_protected_field_rejected(self):
        """PATCH request containing protected parameters is rejected."""
        self.login_as('crm_edit_user', 20003)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (101, 'Name', '111', 'WALK_IN', 'NEW', 20003)", commit=True
        )

        res = self.client.patch('/crm/leads/101', json={
            "name": "New Name",
            "stage": "WON"
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data['error'], 'protected_field')
        self.assertIn('stage', data['fields'])

    def test_patch_unauthorized_blocked(self):
        """User without crm_edit permission fails PATCH submission."""
        self.login_as('crm_view_user', 20002)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (101, 'Name', '111', 'WALK_IN', 'NEW', 20002)", commit=True
        )

        res = self.client.patch('/crm/leads/101', json={
            "name": "Intruder Name"
        })
        self.assertEqual(res.status_code, 302)  # Redirected by permission guard

    def test_linked_member_edit_does_not_modify_members_table(self):
        """Editing linked CRM lead details does not modify member operational record."""
        self.login_as('crm_edit_user', 20003)
        query_db("INSERT INTO members (id, name, phone) VALUES (50001, 'Original Member Name', '123')", commit=True)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, member_id, assigned_user_id) "
            "VALUES (101, 'Original Member Name', '123', 'WALK_IN', 'NEW', 50001, 20003)", commit=True
        )

        # Update CRM Lead
        res = self.client.patch('/crm/leads/101', json={
            "name": "Different CRM Name",
            "phone": "999",
            "source": "WALK_IN"
        })
        self.assertEqual(res.status_code, 200)

        # Check members record
        member = query_db("SELECT * FROM members WHERE id = 50001", one=True)
        self.assertEqual(member['name'], 'Original Member Name')
        self.assertEqual(member['phone'], '123')
