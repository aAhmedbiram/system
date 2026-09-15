import threading
import time
import unittest

from flask import Flask, jsonify, request
from werkzeug.serving import make_server


class LocalAttendanceServer:
    def __init__(self):
        self.app = Flask('attendance_selenium_fixture')
        self.offline = False
        self.sync_count = 0
        self._configure_routes()
        self.server = make_server('127.0.0.1', 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def _configure_routes(self):
        @self.app.route('/static/js/attendance_offline.js')
        def script():
            with open('system_app/static/js/attendance_offline.js', encoding='utf-8') as source:
                return source.read(), 200, {'Content-Type': 'application/javascript'}

        @self.app.route('/attendance_table', methods=['GET', 'POST'])
        def attendance_table():
            if request.method == 'POST':
                return self._page(True, self._scope())
            if self.offline:
                return 'temporarily unavailable', 503
            return self._page(request.args.get('enabled') == '1', self._scope())

        @self.app.route('/api/attendance/offline-snapshot')
        def snapshot():
            if self.offline:
                return jsonify(error='temporary_error'), 503
            return jsonify({
                'scope': self._scope(),
                'members': [{'member_id': 7, 'name': 'Fixture Member', 'membership_status': 'VAL', 'end_date': '2099-01-01'}],
                'attendance_rows': [{'num': 1, 'member_id': 7, 'name': 'Existing Row', 'end_date': '2099-01-01', 'membership_status': 'VAL', 'attendance_time': '09:00:00', 'attendance_date': '2026-09-15', 'day': 'Tuesday', 'comment': None}],
                'business_date': '2026-09-15', 'snapshot_timestamp': '2026-09-15T09:00:00+03:00',
            })

        @self.app.route('/api/attendance/offline-sync', methods=['POST'])
        def sync():
            if self.offline:
                return jsonify(error='temporary_error'), 503
            self.sync_count += 1
            operations = request.json.get('operations', [])
            return jsonify(results=[{'client_operation_id': op['client_operation_id'], 'result_code': 'synced'} for op in operations])

    def _scope(self):
        return f"opaque-fixture-scope-user-{request.args.get('user', '1')}"

    def _page(self, enabled, scope):
        user = request.args.get('user', '1')
        script = f'''<script>window.ATTENDANCE_OFFLINE_CONFIG={{scope:"{scope}",snapshotUrl:"/api/attendance/offline-snapshot?user={user}",syncUrl:"/api/attendance/offline-sync?user={user}",reachabilityUrl:"/attendance_table?user={user}"}};</script><script src="/static/js/attendance_offline.js" defer></script>''' if enabled else ''
        banner = '<div id="attendance-offline-status" hidden><strong>Offline Mode</strong><span id="attendance-offline-status-text"></span></div>' if enabled else ''
        return f'''<!doctype html><html><head><title>Attendance Table - Fixture</title></head><body>
        <h1>Rival Gym System - Attendance Table</h1>{banner}
        <form action="/attendance_table" method="post"><input type="hidden" name="csrf_token" value="fixture"><input id="member_id" name="member_id"><button type="submit">Add Attendance</button></form>
        <div class="table-container"><table><tbody><tr><td>1</td><td>7</td><td>Existing Row</td><td>2099-01-01</td><td>VAL</td><td>09:00:00</td><td>2026-09-15</td><td>Tuesday</td><td>-</td><td>-</td></tr></tbody></table></div>{script}</body></html>'''


class TestAttendanceOfflineSelenium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        cls.fixture = LocalAttendanceServer()
        cls.fixture.start()
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.set_page_load_timeout(20)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.fixture.stop()

    def test_disabled_page_is_native_and_enabled_page_survives_live_loss_and_syncs(self):
        from selenium.webdriver.common.by import By

        driver = self.driver
        driver.get(f'{self.fixture.url}/attendance_table?enabled=0')
        self.assertNotIn('attendance_offline.js', driver.page_source)
        self.assertNotIn('Offline Mode', driver.page_source)
        self.assertIsNone(driver.execute_script('return navigator.serviceWorker && navigator.serviceWorker.controller'))

        driver.get(f'{self.fixture.url}/attendance_table?enabled=1&user=1')
        time.sleep(1)
        self.assertIn('Existing Row', driver.page_source)
        self.assertIn('attendance_offline.js', driver.page_source)
        statuses = driver.execute_async_script('''const done=arguments[0]; const db=indexedDB.open('rival-attendance-offline-v2'); db.onsuccess=()=>{const tx=db.result.transaction('operations','readwrite'); const s=tx.objectStore('operations'); s.put({client_operation_id:'fresh-sync-id',scope:'opaque-fixture-scope-user-1',member_id:7,attendance_date:'2026-09-15',status:'syncing',sync_started_at:new Date().toISOString()}); s.put({client_operation_id:'stale-sync-id',scope:'opaque-fixture-scope-user-1',member_id:7,attendance_date:'2026-09-15',status:'syncing',sync_started_at:new Date(Date.now()-3600000).toISOString()}); tx.oncomplete=async()=>{await window.RivalAttendanceOffline.recoverStaleSyncing(Date.now()); const q=db.result.transaction('operations').objectStore('operations').getAll(); q.onsuccess=()=>done(q.result.filter(x=>x.client_operation_id.endsWith('sync-id')).map(x=>[x.client_operation_id,x.status]));};};''')
        self.assertIn(['fresh-sync-id', 'syncing'], statuses)
        self.assertIn(['stale-sync-id', 'local_pending'], statuses)
        driver.execute_script('''const db=indexedDB.open('rival-attendance-offline-v2'); db.onsuccess=()=>{const tx=db.result.transaction('operations','readwrite'); const s=tx.objectStore('operations'); s.delete('fresh-sync-id'); s.delete('stale-sync-id');};''')
        driver.execute_script('window.dispatchEvent(new Event("offline"));')
        time.sleep(0.5)
        self.assertTrue(driver.execute_script('return document.getElementById("attendance-offline-status").hidden'))

        self.fixture.offline = True
        driver.find_element(By.ID, 'member_id').send_keys('7')
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(1)
        self.assertIn('Existing Row', driver.page_source)
        self.assertIn('Pending sync', driver.page_source)
        self.assertFalse(driver.execute_script('return document.getElementById("attendance-offline-status").hidden'))
        count = driver.execute_async_script('''const done=arguments[0]; const r=indexedDB.open('rival-attendance-offline-v2'); r.onsuccess=()=>{const q=r.result.transaction('operations').objectStore('operations').getAll(); q.onsuccess=()=>done(q.result.length);};''')
        self.assertEqual(count, 1)

        self.fixture.offline = False
        driver.get(f'{self.fixture.url}/attendance_table?enabled=1&user=2')
        time.sleep(0.5)
        other_scope_count = driver.execute_async_script('''const done=arguments[0]; const r=indexedDB.open('rival-attendance-offline-v2'); r.onsuccess=()=>{const q=r.result.transaction('operations').objectStore('operations').getAll(); q.onsuccess=()=>done(q.result.filter(x=>x.scope==='opaque-fixture-scope-user-2').length);};''')
        self.assertEqual(other_scope_count, 0)

        driver.get(f'{self.fixture.url}/attendance_table?enabled=1&user=1')
        time.sleep(0.5)
        driver.execute_script('window.dispatchEvent(new Event("online"));')
        deadline = time.time() + 5
        while self.fixture.sync_count < 1 and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.fixture.sync_count, 1)
        self.assertEqual(driver.find_element(By.TAG_NAME, 'h1').text, 'Rival Gym System - Attendance Table')
        self.assertNotIn('Rival Gym — Attendance', driver.page_source)


if __name__ == '__main__':
    unittest.main()
