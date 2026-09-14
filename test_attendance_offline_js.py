import json
import subprocess
import unittest


class TestAttendanceOfflineJavaScript(unittest.TestCase):
    def test_terminal_results_and_scoped_snapshot_replacement(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('system_app/static/js/attendance_offline.js', 'utf8');
const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
const window = { ATTENDANCE_OFFLINE_CONFIG: {}, addEventListener() {} };
const context = { window, document, localStorage: { getItem() { return 'scope-a'; }, setItem() {}, removeItem() {} },
  indexedDB: {}, crypto: { randomUUID() { return 'id'; } }, navigator: { onLine: false }, console };
vm.createContext(context);
vm.runInContext(source, context);
const api = window.RivalAttendanceOffline;
for (const code of ['synced', 'duplicate_attendance', 'invalid_member', 'inactive_membership', 'validation_error', 'unauthorized']) {
  const result = api.applySyncResult({status: 'syncing'}, {result_code: code, replayed: true});
  if (code === 'synced' && result.status !== 'synced') throw new Error(code);
  if (code !== 'synced' && result.status === 'synced') throw new Error(code);
}
if (api.classifyEnhancedResponse(0, true) !== 'pending_network_error') throw new Error('network fallback');
if (api.classifyEnhancedResponse(503, false) !== 'pending_temporary_error') throw new Error('503 fallback');
if (api.classifyEnhancedResponse(401, false) !== 'pending_login_required') throw new Error('401 fallback');
if (api.classifyEnhancedResponse(403, false) !== 'pending_login_required') throw new Error('403 fallback');
if (api.classifyEnhancedResponse(200, false) !== 'authoritative') throw new Error('success');
if (api.classifyEnhancedResponse(409, false) !== 'permanent_rejection') throw new Error('duplicate/rejection');
if (!api.onlineResultAction('synced').refresh) throw new Error('synced refresh');
if (api.onlineResultAction('duplicate_attendance').refresh) throw new Error('duplicate refresh');
if (api.onlineResultAction('inactive_membership').refresh) throw new Error('inactive refresh');
if (api.onlineResultAction('invalid_member').refresh) throw new Error('invalid refresh');
if (!api.shouldReloadAfterBatch([{status: 'synced'}], true)) throw new Error('batch reload');
if (api.shouldReloadAfterBatch([{status: 'pending'}], true)) throw new Error('pending reload');
if (api.shouldReloadAfterBatch([{status: 'failed'}], true)) throw new Error('failed reload');
if (api.onlineResultAction('validation_error').message.includes('retry')) throw new Error('permanent retry wording');
if (!source.includes('clearMemberInput()')) throw new Error('input clear missing');
if (!source.includes('attendance operations waiting')) throw new Error('pending count missing');
if (!source.includes('pageTransitioning')) throw new Error('transition lock missing');
const visibleFailureRefreshes = (source.match(/await refreshOperations\(\);/g) || []).length;
if (visibleFailureRefreshes < 8) throw new Error('early failure visibility refreshes missing');
if (!source.includes("setStatus('error', 'Login required; pending attendance preserved.')")) throw new Error('auth pending wording');
if (!source.includes("setStatus('error', 'Pending; synchronization will retry.')")) throw new Error('temporary pending wording');
if (!source.includes("setStatus('error', 'Some attendance operations were rejected; review details')")) throw new Error('permanent failure wording');
if (!source.includes('scheduleAttendanceReload();')) throw new Error('success reload missing');
if (!source.includes("if (cursor.value.scope === scope) cursor.delete()")) throw new Error('scope delete missing');
if (!source.includes("cursorRequest.onsuccess")) throw new Error('atomic replacement missing');
console.log(JSON.stringify({ok: true}));
'''
        completed = subprocess.run(
            ['node', '-e', script], capture_output=True, text=True, check=True
        )
        self.assertEqual(json.loads(completed.stdout.strip())['ok'], True)


if __name__ == '__main__':
    unittest.main()
