(function () {
    'use strict';

    var form = document.querySelector('[data-renewal-filter-form]');
    var urgencyFilter = document.querySelector('[data-renewal-urgency-filter]');
    var workflowFilters = document.querySelectorAll('[data-renewal-auto-filter]');

    if (!form || !urgencyFilter) {
        return;
    }

    var submitting = false;

    form.addEventListener('submit', function (event) {
        if (submitting) {
            event.preventDefault();
            return;
        }
        submitting = true;
    });

    urgencyFilter.addEventListener('change', function () {
        if (submitting) {
            return;
        }

        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
            return;
        }

        submitting = true;
        form.submit();
    });

    Array.prototype.forEach.call(workflowFilters, function (filter) {
        filter.addEventListener('change', function () {
            if (submitting) {
                return;
            }

            if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
                return;
            }

            submitting = true;
            form.submit();
        });
    });
}());
