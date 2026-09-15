(() => {
    'use strict';

    const config = window.ATTENDANCE_OFFLINE_CONFIG || {};
    const DB_NAME = 'rival-attendance-offline-v2';
    const DB_VERSION = 1;
    const STORES = { members: 'members', rows: 'attendance_rows', operations: 'operations', meta: 'metadata' };
    const MAX_BATCH = 50;
    const STALE_SYNCING_MS = 5 * 60 * 1000;
    let dbPromise;
    let writeInFlight = false;
    let syncInFlight = false;
    let reachability = true;

    const status = () => document.getElementById('attendance-offline-status');
    const statusText = () => document.getElementById('attendance-offline-status-text');
    const setStatus = (message, visible = true) => {
        const bar = status();
        if (!bar) return;
        bar.hidden = !visible;
        if (statusText()) statusText().textContent = message;
    };
    const scope = () => String(config.scope || '');
    const form = () => document.querySelector('form[action$="/attendance_table"]');
    const input = () => document.getElementById('member_id');

    function openDatabase() {
        if (dbPromise) return dbPromise;
        dbPromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains(STORES.members)) {
                    const store = database.createObjectStore(STORES.members, { keyPath: 'key' });
                    store.createIndex('scope', 'scope');
                }
                if (!database.objectStoreNames.contains(STORES.rows)) {
                    const store = database.createObjectStore(STORES.rows, { keyPath: 'key' });
                    store.createIndex('scope', 'scope');
                }
                if (!database.objectStoreNames.contains(STORES.operations)) {
                    const store = database.createObjectStore(STORES.operations, { keyPath: 'client_operation_id' });
                    store.createIndex('scope', 'scope');
                    store.createIndex('status', 'status');
                }
                if (!database.objectStoreNames.contains(STORES.meta)) {
                    database.createObjectStore(STORES.meta, { keyPath: 'key' });
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('indexeddb_unavailable'));
        });
        return dbPromise;
    }

    function transaction(storeNames, mode, callback) {
        return openDatabase().then(database => new Promise((resolve, reject) => {
            const transaction = database.transaction(storeNames, mode);
            let result;
            try { result = callback(transaction); } catch (error) { transaction.abort(); reject(error); return; }
            transaction.oncomplete = () => resolve(result);
            transaction.onerror = () => reject(transaction.error || new Error('indexeddb_transaction_failed'));
            transaction.onabort = () => reject(transaction.error || new Error('indexeddb_transaction_aborted'));
        }));
    }

    function getScoped(storeName) {
        return openDatabase().then(database => new Promise((resolve, reject) => {
            const request = database.transaction(storeName, 'readonly').objectStore(storeName).getAll();
            request.onsuccess = () => resolve((request.result || []).filter(item => item.scope === scope()));
            request.onerror = () => reject(request.error || new Error('indexeddb_read_failed'));
        }));
    }

    async function saveSnapshot(data) {
        if (!data || data.scope !== scope()) throw new Error('snapshot_scope_mismatch');
        const members = (data.members || []).map(member => ({
            key: `${scope()}:${member.member_id}`, scope: scope(), member_id: member.member_id,
            name: String(member.name || ''), membership_status: member.membership_status,
            end_date: member.end_date,
        }));
        const rows = (data.attendance_rows || []).map((row, index) => ({
            key: `${scope()}:${row.num ?? index}`, scope: scope(), ...row,
        }));
        await transaction([STORES.members, STORES.rows, STORES.meta], 'readwrite', tx => {
            const replace = (storeName, values) => {
                const store = tx.objectStore(storeName);
                store.openCursor().onsuccess = event => {
                    const cursor = event.target.result;
                    if (cursor) {
                        if (cursor.value.scope === scope()) cursor.delete();
                        cursor.continue();
                    } else values.forEach(value => store.put(value));
                };
            };
            replace(STORES.members, members);
            replace(STORES.rows, rows);
            tx.objectStore(STORES.meta).put({
                key: `snapshot:${scope()}`, scope: scope(), business_date: data.business_date,
                snapshot_timestamp: data.snapshot_timestamp,
            });
        });
    }

    function cairoDate() {
        return new Intl.DateTimeFormat('en-CA', {
            timeZone: 'Africa/Cairo', year: 'numeric', month: '2-digit', day: '2-digit',
        }).format(new Date());
    }

    async function pendingFor(memberId, attendanceDate) {
        const operations = await getScoped(STORES.operations);
        return operations.some(operation => operation.member_id === memberId &&
            operation.attendance_date === attendanceDate &&
            ['local_pending', 'syncing', 'temporary_error', 'auth_required'].includes(operation.status));
    }

    async function recoverStaleSyncing(now = Date.now()) {
        const operations = await getScoped(STORES.operations);
        const recovered = [];
        for (const operation of operations) {
            if (operation.status === 'syncing' &&
                now - Date.parse(operation.sync_started_at || 0) > STALE_SYNCING_MS) {
                operation.status = 'local_pending';
                operation.last_error_code = 'browser_termination_recovery';
                await transaction([STORES.operations], 'readwrite', tx =>
                    tx.objectStore(STORES.operations).put(operation));
                recovered.push(operation);
            }
        }
        return recovered;
    }

    async function addPending(member) {
        const attendanceDate = cairoDate();
        const memberId = Number(member.member_id);
        if (await pendingFor(memberId, attendanceDate)) {
            setStatus('Already pending for this member today.');
            return false;
        }
        const operation = {
            client_operation_id: crypto.randomUUID(), scope: scope(), member_id: memberId,
            attendance_date: attendanceDate, captured_at_device: new Date().toISOString(),
            status: 'local_pending', retry_count: 0, last_error_code: null,
            created_at: new Date().toISOString(), member_name: member.name,
        };
        await transaction([STORES.operations], 'readwrite', tx => tx.objectStore(STORES.operations).add(operation));
        input().value = '';
        appendPendingRow(operation);
        setStatus('Offline Mode — attendance pending synchronization.');
        return true;
    }

    function ensureTable() {
        const container = document.querySelector('.table-container');
        if (!container) return null;
        let table = container.querySelector('table');
        if (!table) {
            container.querySelector('.no-data')?.remove();
            table = document.createElement('table');
            table.innerHTML = '<thead><tr><th>#</th><th>ID</th><th>Name</th><th>End Date</th><th>Status</th><th>Time</th><th>Date</th><th>Day</th><th>Comment</th><th>Actions</th></tr></thead><tbody></tbody>';
            container.appendChild(table);
        }
        return table.querySelector('tbody');
    }

    function appendPendingRow(operation) {
        const body = ensureTable();
        if (!body || body.querySelector(`[data-offline-operation="${operation.client_operation_id}"]`)) return;
        const row = document.createElement('tr');
        row.dataset.offlineOperation = operation.client_operation_id;
        [body.rows.length + 1, operation.member_id, operation.member_name || 'Member', '-', 'Pending', '-', operation.attendance_date, '-', '-', 'Pending sync']
            .forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell); });
        body.appendChild(row);
    }

    async function probe() {
        try {
            const response = await fetch(config.reachabilityUrl, {
                credentials: 'same-origin', cache: 'no-store', redirect: 'manual',
            });
            const body = response.ok ? await response.text() : '';
            const valid = response.ok && !response.redirected &&
                new URL(response.url, location.href).pathname === '/attendance_table' &&
                (response.headers.get('content-type') || '').toLowerCase().includes('text/html') &&
                body.includes('Rival Gym System - Attendance Table');
            if (!valid) throw new Error('server_unreachable');
            reachability = true;
            return response;
        } catch (error) {
            reachability = false;
            return null;
        }
    }

    async function refreshSnapshot() {
        try {
            const response = await fetch(config.snapshotUrl, { credentials: 'same-origin', cache: 'no-store' });
            if (!response.ok) throw new Error('snapshot_unavailable');
            await saveSnapshot(await response.json());
        } catch (error) {
            // A snapshot failure must not affect the native online form.
        }
    }

    async function syncPending() {
        if (syncInFlight || !reachability) return;
        syncInFlight = true;
        try {
            await recoverStaleSyncing();
            const operations = (await getScoped(STORES.operations)).filter(operation =>
                ['local_pending', 'temporary_error', 'auth_required'].includes(operation.status)).slice(0, MAX_BATCH);
            if (!operations.length) return;
            for (const operation of operations) {
                operation.status = 'syncing'; operation.sync_started_at = new Date().toISOString();
                await transaction([STORES.operations], 'readwrite', tx => tx.objectStore(STORES.operations).put(operation));
            }
            let response;
            try {
                response = await fetch(config.syncUrl, {
                    method: 'POST', credentials: 'same-origin', cache: 'no-store',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('input[name="csrf_token"]')?.value || '',
                    },
                    body: JSON.stringify({ operations }),
                });
            } catch (error) {
                await preservePending(operations, 'network_error');
                reachability = false;
                setStatus('Offline Mode — attendance pending synchronization.');
                return;
            }
            if (response.status === 401 || response.status === 403 || response.status === 503) {
                await preservePending(operations, response.status === 503 ? 'temporary_error' : 'auth_required');
                setStatus(response.status === 503 ? 'Pending synchronization will retry.' : 'Login required; pending attendance preserved.');
                return;
            }
            if (!response.ok) { await preservePending(operations, 'temporary_error'); return; }
            let payload;
            try {
                payload = await response.json();
            } catch (error) {
                await preservePending(operations, 'malformed_response');
                return;
            }
            if (!payload || !Array.isArray(payload.results)) {
                await preservePending(operations, 'malformed_response');
                return;
            }
            const resultMap = new Map(payload.results.map(result => [result.client_operation_id, result]));
            let allTerminal = true;
            for (const operation of operations) {
                const result = resultMap.get(operation.client_operation_id);
                const terminal = result && ['synced', 'duplicate_attendance', 'inactive_membership', 'invalid_member', 'validation_error', 'unauthorized'].includes(result.result_code);
                operation.status = terminal ? (
                    result.result_code === 'synced' ? 'synced' :
                    result.result_code === 'duplicate_attendance' ? 'duplicate' : 'rejected'
                ) : 'temporary_error';
                operation.last_error_code = result?.result_code || 'temporary_error';
                await transaction([STORES.operations], 'readwrite', tx => tx.objectStore(STORES.operations).put(operation));
                if (!terminal) allTerminal = false;
            }
            if (allTerminal) window.location.reload();
        } finally {
            syncInFlight = false;
        }
    }

    async function preservePending(operations, code) {
        for (const operation of operations) {
            operation.status = code === 'auth_required' ? 'auth_required' : 'temporary_error';
            operation.last_error_code = code;
            operation.retry_count = Number(operation.retry_count || 0) + 1;
            await transaction([STORES.operations], 'readwrite', tx => tx.objectStore(STORES.operations).put(operation));
        }
    }

    async function init() {
        const attendanceForm = form();
        if (!attendanceForm || !scope()) return;
        try { await openDatabase(); } catch (error) { return; }
        attendanceForm.addEventListener('submit', async event => {
            event.preventDefault();
            if (writeInFlight) return;
            writeInFlight = true;
            const button = attendanceForm.querySelector('button[type="submit"]');
            if (button) button.disabled = true;
            try {
                const response = await probe();
                if (response) { attendanceForm.submit(); return; }
                const memberId = Number(input().value);
                const member = (await getScoped(STORES.members)).find(item => item.member_id === memberId);
                if (!Number.isInteger(memberId) || !member) { setStatus('Offline Mode — member is not in the cached snapshot.'); return; }
                await addPending(member);
            } finally {
                writeInFlight = false;
                if (button) button.disabled = false;
            }
        });
        const logoutForm = document.querySelector('form[action$="/logout"]');
        logoutForm?.addEventListener('submit', event => {
            event.preventDefault();
            (async () => {
                const pending = (await getScoped(STORES.operations)).filter(operation =>
                    ['local_pending', 'syncing', 'temporary_error', 'auth_required'].includes(operation.status));
                if (pending.length && !window.confirm(`${pending.length} pending attendance operation(s) will be preserved. Continue logout?`)) return;
                try { sessionStorage.setItem('rival-attendance-retired-scope', scope()); } catch (error) {}
                logoutForm.submit();
            })();
        });
        const response = await probe();
        if (response) {
            await refreshSnapshot();
            await syncPending();
        } else {
            setStatus('Offline Mode — server reachability not confirmed.');
        }
        window.addEventListener('offline', () => { probe().then(result => { if (!result) setStatus('Offline Mode — server reachability not confirmed.'); }); });
        window.addEventListener('online', async () => { const result = await probe(); if (result) { setStatus('', false); await refreshSnapshot(); await syncPending(); } });
        await recoverStaleSyncing();
        for (const operation of (await getScoped(STORES.operations)).filter(item => ['local_pending', 'syncing', 'temporary_error', 'auth_required'].includes(item.status))) appendPendingRow(operation);
    }

    window.RivalAttendanceOffline = { openDatabase, probe, addPending, syncPending, preservePending, recoverStaleSyncing };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
