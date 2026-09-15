(() => {
    'use strict';

    const form = document.querySelector('form[data-private-training-checkin-ajax="true"]');
    if (!form || typeof window.fetch !== 'function' || typeof window.FormData !== 'function') return;

    const input = form.querySelector('[data-private-training-checkin-input="true"]');
    const submitButton = form.querySelector('button[type="submit"]');
    const message = document.getElementById('private-training-checkin-message');
    const error = document.getElementById('private-training-checkin-error');
    let inFlight = false;

    function showMessage(text) {
        if (!message) return;
        message.textContent = text || '';
        message.hidden = !text;
    }

    function showError(text) {
        if (!error) return;
        error.textContent = text || '';
        error.hidden = !text;
    }

    function setCounter(selector, value) {
        const element = document.querySelector(selector);
        if (element && value !== undefined && value !== null) element.textContent = String(value);
    }

    function statusLabel(status) {
        return status === 'PENDING_MEMBER_APPROVAL' ? 'PENDING' : String(status || '');
    }

    function statusClass(status) {
        if (status === 'ACTIVE') return 'ok';
        if (status === 'ASSIGNED') return 'warn';
        return 'bad';
    }

    function updateSubscription(subscription) {
        if (!subscription) return;
        setCounter('#private-training-approved-count', subscription.approved_sessions);
        setCounter('#private-training-remaining-count', subscription.remaining_sessions);
        setCounter('#private-training-pending-count', subscription.pending_sessions);
        const status = document.querySelector('[data-private-training-status]');
        if (status && subscription.effective_status) {
            status.textContent = String(subscription.effective_status);
            status.classList.remove('ok', 'warn', 'bad');
            status.classList.add(statusClass(subscription.effective_status));
        }
    }

    function sessionCells(session) {
        return [
            session.id,
            session.trainer,
            session.checked_in_at,
            session.workout_name || '-',
            statusLabel(session.status),
            session.approved_at || '-',
        ];
    }

    function updateHistory(sessions, authoritativeSession) {
        const body = document.getElementById('private-training-session-history-body');
        if (!body) return;

        const rows = Array.isArray(sessions) ? sessions : (authoritativeSession ? [authoritativeSession] : []);
        const session = authoritativeSession || rows[0];
        if (!session || session.id === undefined || session.id === null) return;

        const sessionId = String(session.id);
        let row = Array.from(body.querySelectorAll('[data-private-training-session-id]'))
            .find(candidate => candidate.dataset.privateTrainingSessionId === sessionId);
        if (!row) {
            const emptyRow = body.querySelector('tr td[colspan="6"]');
            if (emptyRow) emptyRow.closest('tr').remove();
            row = document.createElement('tr');
            row.dataset.privateTrainingSessionId = sessionId;
            body.prepend(row);
        }
        row.replaceChildren(...sessionCells(session).map(value => {
            const cell = document.createElement('td');
            cell.textContent = value == null ? '-' : String(value);
            return cell;
        }));
    }

    function applySuccess(payload, scrollX, scrollY) {
        updateSubscription(payload.subscription);
        updateHistory(payload.sessions, payload.session);
        if (payload.subscription && Number(payload.subscription.pending_sessions) > 0) {
            form.hidden = true;
            showMessage('Waiting for Member Approval');
        } else {
            showMessage(payload.message || 'Private training session checked in successfully.');
        }
        showError('');
        if (typeof window.scrollTo === 'function') {
            window.requestAnimationFrame(() => window.scrollTo(scrollX, scrollY));
        }
    }

    async function submitAsJson(event) {
        if (inFlight) {
            event.preventDefault();
            return;
        }
        inFlight = true;
        event.preventDefault();
        const scrollX = window.scrollX || window.pageXOffset || 0;
        const scrollY = window.scrollY || window.pageYOffset || 0;
        const originalText = submitButton ? submitButton.textContent : '';
        form.setAttribute('aria-busy', 'true');
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = 'Saving…';
        }
        showError('');
        try {
            const response = await fetch(form.action, {
                method: (form.method || 'POST').toUpperCase(),
                body: new FormData(form),
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
            if (response.status === 401 || response.url.endsWith('/login')) {
                showError('Your session has expired. Please log in again before checking in.');
                return;
            }
            if (!contentType.includes('application/json')) {
                showError('The server returned an unexpected response. Check Session History before trying again.');
                return;
            }
            const payload = await response.json();
            if (!response.ok || !payload || payload.ok !== true) {
                showError(payload && payload.message ? String(payload.message) : 'Check-in could not be completed.');
                return;
            }
            applySuccess(payload, scrollX, scrollY);
            if (input) input.value = '';
        } catch (requestError) {
            showError('The result could not be confirmed. Check Session History before trying again.');
        } finally {
            form.removeAttribute('aria-busy');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = originalText;
            }
            inFlight = false;
        }
    }

    form.addEventListener('submit', submitAsJson);
})();
