(function () {
    "use strict";

    window.CRM = window.CRM || {};

    function readCsrfToken() {
        if (window.CRM_CSRF_TOKEN) {
            return window.CRM_CSRF_TOKEN;
        }

        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function buildJsonHeaders(extraHeaders) {
        const headers = {
            "Content-Type": "application/json"
        };

        const token = readCsrfToken();
        if (token) {
            headers["X-CSRFToken"] = token;
        }

        if (extraHeaders && typeof extraHeaders === "object") {
            Object.keys(extraHeaders).forEach(function (key) {
                headers[key] = extraHeaders[key];
            });
        }

        return headers;
    }

    window.CRM.getCsrfToken = readCsrfToken;
    window.CRM.jsonHeaders = buildJsonHeaders;
    window.CRM.apiFetch = function (url, options) {
        const requestOptions = options ? Object.assign({}, options) : {};
        const method = (requestOptions.method || "GET").toUpperCase();

        if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
            requestOptions.headers = buildJsonHeaders(requestOptions.headers || {});
        } else if (requestOptions.headers) {
            requestOptions.headers = Object.assign({}, requestOptions.headers);
        }

        requestOptions.credentials = requestOptions.credentials || "same-origin";
        return fetch(url, requestOptions);
    };

    window.CRM.getAssignableUsers = function () {
        if (!window.CRM._assignableUsersPromise) {
            window.CRM._assignableUsersPromise = fetch("/crm/users", { credentials: "same-origin" })
                .then(function (res) {
                    if (!res.ok) {
                        throw new Error("Status " + res.status);
                    }
                    return res.json();
                });
        }
        return window.CRM._assignableUsersPromise;
    };
}());
