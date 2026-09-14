(() => {
    'use strict';

    const DB_NAME = 'rival-attendance-offline-v1';
    const DB_VERSION = 1;
    const MEMBER_STORE = 'members';
    const OPERATION_STORE = 'operations';
    const META_STORE = 'metadata';
    const SYNCING_TIMEOUT_MS = 5 * 60 * 1000;
    const MAX_SYNC_RETRY_DELAY_MS = 5 * 60 * 1000;
    const RELOAD_MARKER = 'rival-attendance-reload-once';
    let syncInFlight = false;
    let offlineSubmitInFlight = false;
    let pageTransitioning = false;

    const config = window.ATTENDANCE_OFFLINE_CONFIG || {};
    const statusBar = () => document.getElementById('attendance-offline-status');
    const statusText = () => document.getElementById('attendance-offline-status-text');

    function userScope() {
        const configured = config.userScope == null ? '' : String(config.userScope);
        if (configured) {
            localStorage.setItem('rival-attendance-active-scope', configured);
            return configured;
        }
        return localStorage.getItem('rival-attendance-active-scope') || '';
    }

    function setStatus(state, text) {
        const bar = statusBar();
        if (bar) bar.dataset.state = state;
        if (statusText()) statusText().textContent = text;
    }

    function clearMemberInput() {
        const input = document.getElementById('member_id');
        if (input) input.value = '';
    }

    function scheduleAttendanceReload() {
        if (pageTransitioning || sessionStorage.getItem(RELOAD_MARKER)) return false;
        sessionStorage.setItem(RELOAD_MARKER, '1');
        pageTransitioning = true;
        setTimeout(() => window.location.reload(), 350);
        return true;
    }

    function operationErrorMessage(code) {
        return {
            duplicate_attendance: 'Already attended today.',
            inactive_membership: 'Membership is inactive or expired.',
            invalid_member: 'Member was not found.',
            validation_error: 'Attendance data was rejected.',
            login_required: 'Login required; pending attendance preserved.',
            temporary_error: 'Pending; synchronization will retry.',
            network_error: 'Pending; synchronization will retry.',
        }[code] || 'Attendance data was rejected.';
    }

    function onlineResultAction(resultCode) {
        return {
            refresh: resultCode === 'synced',
            message: resultCode === 'synced'
                ? 'Attendance recorded successfully.'
                : operationErrorMessage(resultCode),
        };
    }

    function shouldReloadAfterBatch(remaining, batchRecorded) {
        return batchRecorded &&
            !remaining.some(item => ['pending', 'syncing', 'failed'].includes(item.status));
    }

    function openDatabase() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const db = request.result;
                if (!db.objectStoreNames.contains(MEMBER_STORE)) {
                    const members = db.createObjectStore(MEMBER_STORE, { keyPath: 'key' });
                    members.createIndex('scope', 'scope', { unique: false });
                }
                if (!db.objectStoreNames.contains(OPERATION_STORE)) {
                    const operations = db.createObjectStore(OPERATION_STORE, { keyPath: 'client_operation_id' });
                    operations.createIndex('scope', 'scope', { unique: false });
                    operations.createIndex('status', 'status', { unique: false });
                }
                if (!db.objectStoreNames.contains(META_STORE)) {
                    db.createObjectStore(META_STORE, { keyPath: 'key' });
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('indexeddb_unavailable'));
        });
    }

    function transaction(db, stores, mode, action) {
        return new Promise((resolve, reject) => {
            const tx = db.transaction(stores, mode);
            let result;
            try { result = action(tx); } catch (error) { tx.abort(); reject(error); return; }
            tx.oncomplete = () => resolve(result);
            tx.onerror = () => reject(tx.error || new Error('indexeddb_transaction_failed'));
            tx.onabort = () => reject(tx.error || new Error('indexeddb_transaction_aborted'));
        });
    }

    function requestResult(request) {
        return new Promise((resolve, reject) => {
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('indexeddb_request_failed'));
        });
    }

    async function getScopedRecords(storeName) {
        const scope = userScope();
        if (!scope) return [];
        const db = await openDatabase();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(storeName, 'readonly');
            const request = tx.objectStore(storeName).getAll();
            request.onsuccess = () => resolve((request.result || []).filter(item => item.scope === scope));
            request.onerror = () => reject(request.error || new Error('indexeddb_read_failed'));
        });
    }

    async function saveMembers(members, snapshotVersion, businessDate) {
        const scope = userScope();
        if (!scope) return;
        const db = await openDatabase();
        await transaction(db, [MEMBER_STORE, META_STORE], 'readwrite', tx => {
            const memberStore = tx.objectStore(MEMBER_STORE);
            const cursorRequest = memberStore.openCursor();
            cursorRequest.onerror = () => tx.abort();
            cursorRequest.onsuccess = event => {
                const cursor = event.target.result;
                if (cursor) {
                    if (cursor.value.scope === scope) cursor.delete();
                    cursor.continue();
                    return;
                }
                (members || []).forEach(member => {
                    memberStore.put({
                        key: `${scope}:${member.member_id}`,
                        scope,
                        member_id: member.member_id,
                        name: String(member.name || ''),
                        membership_status: member.membership_status,
                        end_date: member.end_date,
                    });
                });
                tx.objectStore(META_STORE).put({
                    key: `snapshot:${scope}`,
                    scope,
                    snapshot_version: snapshotVersion,
                    business_date: businessDate,
                });
            };
        });
    }

    async function loadMembers() {
        return getScopedRecords(MEMBER_STORE);
    }

    async function saveOperation(operation) {
        const db = await openDatabase();
        await transaction(db, [OPERATION_STORE], 'readwrite', tx => {
            tx.objectStore(OPERATION_STORE).put(operation);
        });
    }

    async function updateOperation(operation) {
        return saveOperation(operation);
    }

    function provisionalCairoDate() {
        return new Intl.DateTimeFormat('en-CA', {
            timeZone: 'Africa/Cairo', year: 'numeric', month: '2-digit', day: '2-digit'
        }).format(new Date());
    }

    function newOperation(member) {
        const uuid = crypto.randomUUID ? crypto.randomUUID() : ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
            (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
        return {
            client_operation_id: uuid,
            scope: userScope(),
            member_id: Number(member.member_id),
            member_name: String(member.name || ''),
            attendance_date: provisionalCairoDate(),
            captured_at_device: new Date().toISOString(),
            status: 'pending',
            retry_count: 0,
            last_error_code: null,
            created_at: new Date().toISOString(),
            synced_at: null,
        };
    }

    function applySyncResult(operation, result) {
        if (!result || result.result_code === 'temporary_error') {
            return { ...operation, status: 'pending', last_error_code: 'temporary_error' };
        }
        if (result.result_code === 'synced') {
            return { ...operation, status: 'synced', synced_at: new Date().toISOString(), last_error_code: null };
        }
        if (result.result_code === 'duplicate_attendance') {
            return { ...operation, status: 'duplicate', last_error_code: result.result_code };
        }
        return { ...operation, status: 'failed', last_error_code: result.result_code || 'validation_error' };
    }

    function classifyEnhancedResponse(status, networkFailure) {
        if (networkFailure) return 'pending_network_error';
        if (status === 401 || status === 403) return 'pending_login_required';
        if (status === 503) return 'pending_temporary_error';
        if (status >= 200 && status < 300) return 'authoritative';
        return 'permanent_rejection';
    }

    async function pendingOperationExists(memberId, attendanceDate) {
        const records = await getScopedRecords(OPERATION_STORE);
        return records.some(operation =>
            operation.member_id === Number(memberId) &&
            operation.attendance_date === attendanceDate &&
            ['pending', 'syncing'].includes(operation.status)
        );
    }

    function renderOperations(records) {
        const queue = document.getElementById('attendance-offline-queue');
        const container = document.getElementById('attendance-offline-operations');
        if (!queue || !container) return;
        container.replaceChildren();
        const visible = records.filter(record => ['pending', 'syncing', 'duplicate', 'failed'].includes(record.status));
        queue.hidden = visible.length === 0;
        const waiting = visible.filter(record => ['pending', 'syncing'].includes(record.status)).length;
        const failed = visible.filter(record => record.status === 'failed').length;
        const retryable = records.some(record =>
            ['pending', 'syncing'].includes(record.status) ||
            ['temporary_error', 'network_error', 'login_required'].includes(record.last_error_code)
        );
        if (!syncInFlight && failed && retryable) setStatus('error', 'Synchronization failed; retry available');
        else if (!syncInFlight && failed) setStatus('error', 'Some attendance operations were rejected; review details');
        else if (!syncInFlight && waiting) setStatus(navigator.onLine ? 'online' : 'offline', `${waiting} attendance operations waiting`);
        visible.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))).forEach(record => {
            const row = document.createElement('div');
            row.className = 'offline-operation';
            const label = document.createElement('span');
            label.textContent = `${record.member_name || 'Member'} (#${record.member_id}) — ${record.attendance_date}: `;
            const state = document.createElement('span');
            state.className = record.status === 'failed' ? 'failed' : 'pending';
            state.textContent = record.status === 'failed'
                ? operationErrorMessage(record.last_error_code)
                : record.status === 'duplicate' ? operationErrorMessage('duplicate_attendance') : record.status === 'syncing' ? 'Synchronizing' : 'Pending sync';
            row.append(label, state);
            container.appendChild(row);
        });
    }

    async function refreshOperations() {
        const records = await getScopedRecords(OPERATION_STORE);
        renderOperations(records);
        return records;
    }

    async function refreshSnapshot() {
        if (!navigator.onLine || !userScope()) return;
        try {
            const response = await fetch(config.snapshotUrl, { credentials: 'same-origin', cache: 'no-store' });
            if (response.status === 401 || response.status === 403) {
                setStatus('error', 'Login required to prepare offline attendance');
                return;
            }
            if (!response.ok) throw new Error('snapshot_unavailable');
            const data = await response.json();
            await saveMembers(data.members, data.snapshot_version, data.business_date);
        } catch (error) {
            // Keep the last known good snapshot.
            setStatus('error', 'Could not refresh cached members; retry available');
        }
    }

    async function markTemporaryFailure(operation, code) {
        operation.status = 'pending';
        operation.retry_count = Number(operation.retry_count || 0) + 1;
        operation.last_error_code = code;
        await updateOperation(operation);
    }

    function retryDelay(retryCount) {
        const base = Math.min(MAX_SYNC_RETRY_DELAY_MS, 1000 * (2 ** Math.min(retryCount, 8)));
        return Math.floor(base * (0.75 + Math.random() * 0.5));
    }

    async function syncNow() {
        if (syncInFlight || !navigator.onLine || !userScope()) return;
        syncInFlight = true;
        const button = document.getElementById('attendance-offline-sync');
        if (button) button.disabled = true;
        try {
            let records = await getScopedRecords(OPERATION_STORE);
            const now = Date.now();
            records = records.filter(record => {
                if (record.status === 'syncing' && now - Date.parse(record.sync_started_at || 0) > SYNCING_TIMEOUT_MS) {
                    record.status = 'pending';
                    updateOperation(record);
                }
                return record.status === 'pending';
            });
            if (!records.length) {
                const current = await refreshOperations();
                if (current.some(item => item.status === 'failed')) {
                    setStatus('error', 'Some attendance operations were rejected; review details');
                } else {
                    setStatus(navigator.onLine ? 'synced' : 'offline', navigator.onLine ? 'All changes synchronized' : 'Offline');
                }
                return;
            }
            setStatus('syncing', 'Synchronizing');
            records.forEach(record => {
                record.status = 'syncing';
                record.sync_started_at = new Date().toISOString();
            });
            for (const record of records) await updateOperation(record);

            let response;
            try {
                response = await fetch(config.syncUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    cache: 'no-store',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': config.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '',
                    },
                    body: JSON.stringify({ operations: records }),
                });
            } catch (error) {
                for (const record of records) await markTemporaryFailure(record, 'network_error');
                await refreshOperations();
                setStatus('error', 'Pending; synchronization will retry.');
                setTimeout(() => { if (navigator.onLine) syncNow(); }, retryDelay(records[0].retry_count));
                return;
            }
            if (response.status === 401 || response.status === 403) {
                for (const record of records) await markTemporaryFailure(record, 'login_required');
                await refreshOperations();
                setStatus('error', 'Login required; pending attendance preserved.');
                return;
            }
            if (response.status === 503) {
                for (const record of records) await markTemporaryFailure(record, 'temporary_error');
                await refreshOperations();
                setStatus('error', 'Pending; synchronization will retry.');
                setTimeout(() => { if (navigator.onLine) syncNow(); }, retryDelay(records[0].retry_count));
                return;
            }
            if (!response.ok) {
                if (response.status >= 500) {
                    for (const record of records) await markTemporaryFailure(record, 'temporary_error');
                    await refreshOperations();
                    setStatus('error', 'Pending; synchronization will retry.');
                } else {
                    for (const record of records) {
                        record.status = 'failed';
                        record.last_error_code = 'validation_error';
                        await updateOperation(record);
                    }
                    await refreshOperations();
                    setStatus('error', 'Some attendance operations were rejected; review details');
                }
                return;
            }
            const resultMap = new Map((await response.json()).results.map(result => [result.client_operation_id, result]));
            let batchRecorded = false;
            for (const record of records) {
                const result = resultMap.get(record.client_operation_id);
                if (!result || result.result_code === 'temporary_error') {
                    await markTemporaryFailure(record, 'temporary_error');
                } else {
                    const updatedOperation = applySyncResult(record, result);
                    batchRecorded = batchRecorded || updatedOperation.status === 'synced';
                    await updateOperation(updatedOperation);
                }
            }
            await refreshOperations();
            const remaining = await getScopedRecords(OPERATION_STORE);
            const hasPending = remaining.some(item => ['pending', 'syncing'].includes(item.status));
            const hasRejected = remaining.some(item => item.status === 'failed');
            if (hasRejected) {
                setStatus('error', 'Some attendance operations were rejected; review details');
            } else if (hasPending) {
                setStatus('error', 'Pending; synchronization will retry.');
            } else {
                setStatus('synced', 'All changes synchronized');
                if (shouldReloadAfterBatch(remaining, batchRecorded)) scheduleAttendanceReload();
            }
        } finally {
            syncInFlight = false;
            if (button) button.disabled = false;
        }
    }

    async function addOfflineAttendance(member) {
        const operation = newOperation(member);
        if (await pendingOperationExists(operation.member_id, operation.attendance_date)) {
            setStatus('error', 'This member/date is already waiting to synchronize');
            return;
        }
        await saveOperation(operation);
        clearMemberInput();
        const current = await refreshOperations();
        const waiting = current.filter(item => ['pending', 'syncing'].includes(item.status)).length;
        setStatus('offline', `${waiting} attendance operations waiting`);
        return true;
    }

    async function submitEnhancedAttendance(member) {
        const operation = newOperation(member);
        if (await pendingOperationExists(operation.member_id, operation.attendance_date)) {
            setStatus('error', 'This member/date is already waiting to synchronize');
            return;
        }
        operation.status = 'syncing';
        operation.sync_started_at = new Date().toISOString();
        await saveOperation(operation);
        try {
            const response = await fetch(config.syncUrl, {
                method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': config.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '',
                },
                body: JSON.stringify({ operations: [operation] }),
            });
            const responseClass = classifyEnhancedResponse(response.status, false);
            if (responseClass === 'pending_login_required') {
                await markTemporaryFailure(operation, 'login_required');
                await refreshOperations();
                setStatus('error', 'Login required; pending attendance preserved.');
                return;
            }
            if (responseClass === 'pending_temporary_error') {
                await markTemporaryFailure(operation, 'temporary_error');
                await refreshOperations();
                setStatus('error', 'Pending; synchronization will retry.');
                return;
            }
            if (!response.ok) {
                operation.status = 'failed';
                operation.last_error_code = 'validation_error';
                await updateOperation(operation);
                await refreshOperations();
                setStatus('error', 'Some attendance operations were rejected; review details');
                return;
            }
            const result = (await response.json()).results?.[0];
            const updatedOperation = applySyncResult(operation, result);
            await updateOperation(updatedOperation);
            await refreshOperations();
            const action = onlineResultAction(result?.result_code);
            if (updatedOperation.status === 'synced') {
                clearMemberInput();
                setStatus('success', action.message);
                scheduleAttendanceReload();
            } else if (updatedOperation.status === 'duplicate') {
                setStatus('error', action.message);
            } else {
                setStatus('error', action.message);
            }
        } catch (error) {
            await markTemporaryFailure(operation, 'network_error');
            await refreshOperations();
            setStatus('error', 'Pending; synchronization will retry.');
        }
    }

    async function renderMemberSearch(value) {
        const results = document.getElementById('attendance-member-results');
        if (!results) return;
        results.replaceChildren();
        const query = String(value || '').trim().toLowerCase();
        if (!query) return;
        const members = (await loadMembers()).filter(member =>
            String(member.member_id).includes(query) || String(member.name || '').toLowerCase().includes(query)
        ).slice(0, 20);
        members.forEach(member => {
            const result = document.createElement('button');
            result.type = 'button';
            result.className = 'offline-member-result';
            result.textContent = `#${member.member_id} ${member.name || ''}`;
            result.addEventListener('click', () => {
                document.getElementById('member_id').value = member.member_id;
                results.replaceChildren();
            });
            results.appendChild(result);
        });
    }

    async function init() {
        if (sessionStorage.getItem(RELOAD_MARKER)) sessionStorage.removeItem(RELOAD_MARKER);
        try { await openDatabase(); } catch (error) {
            setStatus('error', 'Offline storage is unavailable on this device');
            return;
        }
        const search = document.getElementById('attendance-member-search');
        search?.addEventListener('input', event => renderMemberSearch(event.target.value));
        document.getElementById('attendance-offline-sync')?.addEventListener('click', syncNow);
        document.getElementById('attendance-form')?.addEventListener('submit', async event => {
            event.preventDefault();
            if (offlineSubmitInFlight || pageTransitioning) return;
            offlineSubmitInFlight = true;
            const submitButton = event.currentTarget.querySelector('button[type="submit"]');
            if (submitButton) submitButton.disabled = true;
            try {
                const memberId = Number(document.getElementById('member_id')?.value);
                const member = (await loadMembers()).find(item => item.member_id === memberId) || {
                    member_id: memberId,
                    name: '',
                };
                if (!Number.isInteger(memberId) || memberId <= 0) {
                    setStatus('error', 'Enter a valid member ID');
                    return;
                }
                if (!navigator.onLine) {
                    if (!member.name && !(await loadMembers()).some(item => item.member_id === memberId)) {
                        setStatus('error', 'Connect to the internet once to prepare offline attendance');
                        return;
                    }
                    await addOfflineAttendance(member);
                } else {
                    await submitEnhancedAttendance(member);
                }
            } finally {
                offlineSubmitInFlight = false;
                if (submitButton) submitButton.disabled = pageTransitioning;
            }
        });
        document.getElementById('attendance-logout-form')?.addEventListener('submit', async event => {
            const pending = (await getScopedRecords(OPERATION_STORE))
                .filter(operation => ['pending', 'syncing'].includes(operation.status));
            if (pending.length && !window.confirm(`${pending.length} attendance operation(s) are waiting to synchronize. Log out and keep them for later?`)) {
                event.preventDefault();
                return;
            }
            localStorage.removeItem('rival-attendance-active-scope');
        });
        window.addEventListener('online', async () => {
            await ensureOnlineConfig();
            setStatus('online', 'Online');
            await refreshSnapshot();
            syncNow();
        });
        window.addEventListener('offline', () => setStatus('offline', 'Offline — date is provisional until synchronization'));
        await ensureOnlineConfig();
        await refreshSnapshot();
        await refreshOperations();
        if (!navigator.onLine && !(await loadMembers()).length) {
            setStatus('offline', 'Connect to the internet once to prepare offline attendance');
        } else if (navigator.onLine) {
            syncNow();
        } else {
            setStatus('offline', 'Offline — date is provisional until synchronization');
        }
    }

    async function ensureOnlineConfig() {
        if (config.csrfToken || !navigator.onLine) return;
        try {
            const response = await fetch('/attendance_table', { credentials: 'same-origin', cache: 'no-store' });
            if (!response.ok) return;
            const html = await response.text();
            const documentParser = new DOMParser().parseFromString(html, 'text/html');
            config.csrfToken = documentParser.querySelector('meta[name="csrf-token"]')?.content || '';
            const scriptText = [...documentParser.scripts].map(script => script.textContent).join('\n');
            const scopeMatch = scriptText.match(/userScope:\s*("(?:\\.|[^"])*")/);
            if (scopeMatch) {
                config.userScope = JSON.parse(scopeMatch[1]);
                userScope();
            }
        } catch (error) {
            // A later online event or manual sync can retry configuration.
        }
    }

    window.RivalAttendanceOffline = {
        openDatabase, saveMembers, saveOperation, syncNow, newOperation,
        pendingOperationExists, applySyncResult, classifyEnhancedResponse, onlineResultAction,
        shouldReloadAfterBatch, submitEnhancedAttendance, DB_NAME, DB_VERSION,
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
