(() => {
    'use strict';

    const form = document.querySelector('form[data-private-training-checkin-ajax="true"]');
    if (!form || typeof window.fetch !== 'function' || typeof window.FormData !== 'function') return;

    const input = form.querySelector('[data-private-training-checkin-input="true"]');
    const submitButton = form.querySelector('button[type="submit"]');
    const message = document.getElementById('private-training-checkin-message');
    const error = document.getElementById('private-training-checkin-error');
    const fallback = document.getElementById('private-training-whatsapp-fallback');
    const whatsappLink = document.getElementById('private-training-whatsapp-link');
    const combinedEnabled = form.dataset.privateTrainingWhatsappEnabled === 'true';
    let inFlight = false;
    let operationId = null;
    let popup = null;

    const definitiveErrors = new Set([
        'validation_error', 'invalid_operation_id', 'missing_phone', 'invalid_phone',
        'unauthorized', 'forbidden', 'subscription_not_found',
        'inactive_subscription', 'cancelled_subscription', 'expired_subscription',
        'no_remaining_sessions', 'pending_session_exists', 'feature_unavailable',
        'csrf_failure',
    ]);

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

    function showWhatsApp(url) {
        if (!fallback || !whatsappLink || !url) return;
        whatsappLink.href = String(url);
        fallback.hidden = false;
        if (popup && !popup.closed) {
            try { popup.location.replace(String(url)); return; } catch (_) {}
        }
    }

    function clearOperationIfDefinitive(payload, response) {
        const code = payload && payload.error;
        if (response && response.status >= 500) return;
        if (definitiveErrors.has(code)) operationId = null;
    }

    async function submitAsJson(event) {
        if (inFlight) {
            event.preventDefault();
            return;
        }
        if (combinedEnabled && (!window.crypto || typeof window.crypto.randomUUID !== 'function')) {
            event.preventDefault();
            showError('WhatsApp invitations are unavailable in this browser.');
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
        if (combinedEnabled) {
            if (!operationId) operationId = window.crypto.randomUUID();
            try { popup = window.open('about:blank', '_blank', 'noopener,noreferrer'); } catch (_) { popup = null; }
            if (popup) { try { popup.opener = null; } catch (_) {} }
        }
        try {
            const body = new FormData(form);
            if (combinedEnabled) body.append('client_operation_id', operationId);
            const response = await fetch(form.action, {
                method: (form.method || 'POST').toUpperCase(),
                body,
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
            if (response.status === 401 || response.url.endsWith('/login')) {
                showError('Your session has expired. Please log in again before checking in.');
                if (popup && !popup.closed) { try { popup.close(); } catch (_) {} }
                return;
            }
            if (!contentType.includes('application/json')) {
                showError('The server returned an unexpected response. Check Session History before trying again.');
                if (popup && !popup.closed) { try { popup.close(); } catch (_) {} }
                return;
            }
            const payload = await response.json();
            if (!response.ok || !payload || payload.ok !== true) {
                showError(payload && payload.message ? String(payload.message) : 'Check-in could not be completed.');
                clearOperationIfDefinitive(payload, response);
                if (popup && !popup.closed) { try { popup.close(); } catch (_) {} }
                return;
            }
            applySuccess(payload, scrollX, scrollY);
            if (input) input.value = '';
            if (combinedEnabled) showWhatsApp(payload.whatsapp && payload.whatsapp.url);
        } catch (requestError) {
            showError('The result could not be confirmed. Check Session History before trying again.');
            if (popup && !popup.closed) { try { popup.close(); } catch (_) {} }
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
