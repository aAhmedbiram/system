document.addEventListener("DOMContentLoaded", () => {
    const table = document.getElementById("queueTable");
    const body = document.getElementById("queueBody");
    const loading = document.getElementById("queueLoading");
    const errorEl = document.getElementById("queueError");
    const emptyEl = document.getElementById("queueEmpty");
    const summaryEl = document.getElementById("queueSummary");
    const prevBtn = document.getElementById("queuePrevBtn");
    const nextBtn = document.getElementById("queueNextBtn");
    const pageIndicator = document.getElementById("queuePageIndicator");
    const tabs = Array.from(document.querySelectorAll(".tab-btn"));

    let currentPage = 1;
    const allowedStatuses = new Set(["overdue", "today", "upcoming"]);
    let currentStatus = allowedStatuses.has(window.CRM_FOLLOW_UP_INITIAL_STATUS) ? window.CRM_FOLLOW_UP_INITIAL_STATUS : "overdue";

    function formatDatetime(dtString) {
        if (!dtString) return "—";
        try {
            return new Intl.DateTimeFormat("en-GB", {
                timeZone: "Africa/Cairo",
                year: "numeric",
                month: "short",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false
            }).format(new Date(dtString));
        } catch (err) {
            return dtString;
        }
    }

    function formatStageLabel(stage) {
        const map = {
            NEW: "New",
            CONTACTED: "Contacted",
            FOLLOW_UP: "Follow-Up",
            INTERESTED: "Interested",
            TRIAL: "Trial",
            WON: "Won",
            LOST: "Lost"
        };
        return map[stage] || stage || "—";
    }

    function formatMemberType(lead) {
        const span = document.createElement("span");
        if (lead.member_id) {
            span.className = "badge member";
            span.textContent = "Member";
        } else {
            span.className = "badge prospect";
            span.textContent = "Prospect";
        }
        return span;
    }

    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    function setActiveTab(status) {
        tabs.forEach(btn => {
            btn.classList.toggle("active", btn.dataset.status === status);
        });
    }

    function clearState() {
        loading.style.display = "block";
        errorEl.style.display = "none";
        emptyEl.style.display = "none";
        table.style.display = "none";
        body.innerHTML = "";
    }

    function renderRows(items) {
        body.innerHTML = "";
        items.forEach(lead => {
            const row = document.createElement("tr");

            const nameCell = document.createElement("td");
            const link = document.createElement("a");
            link.href = `/crm/leads/${lead.id}/view`;
            link.textContent = lead.name || "—";
            link.style.color = "#4caf50";
            link.style.textDecoration = "none";
            link.style.fontWeight = "600";
            nameCell.appendChild(link);
            row.appendChild(nameCell);

            const typeCell = document.createElement("td");
            typeCell.appendChild(formatMemberType(lead));
            row.appendChild(typeCell);

            const phoneCell = document.createElement("td");
            phoneCell.textContent = lead.phone || "—";
            row.appendChild(phoneCell);

            const stageCell = document.createElement("td");
            stageCell.textContent = formatStageLabel(lead.stage);
            row.appendChild(stageCell);

            const assigneeCell = document.createElement("td");
            assigneeCell.textContent = lead.assigned_username || "Unassigned";
            row.appendChild(assigneeCell);

            const followCell = document.createElement("td");
            followCell.textContent = formatDatetime(lead.next_follow_up_at);
            row.appendChild(followCell);

            const sourceCell = document.createElement("td");
            sourceCell.textContent = lead.source || "—";
            row.appendChild(sourceCell);

            const actionCell = document.createElement("td");
            const actionLink = document.createElement("a");
            actionLink.href = `/crm/leads/${lead.id}/view`;
            actionLink.className = "index-btn";
            actionLink.textContent = "Open Lead";
            actionCell.appendChild(actionLink);
            row.appendChild(actionCell);

            body.appendChild(row);
        });
    }

    function loadQueue(page) {
        clearState();
        const params = new URLSearchParams({
            page: String(page),
            per_page: "25",
            status: currentStatus
        });

        apiFetch(`/crm/follow-ups?${params.toString()}`)
            .then(res => {
                if (!res.ok) {
                    throw new Error("Status " + res.status);
                }
                return res.json();
            })
            .then(data => {
                loading.style.display = "none";
                const items = data.items || [];

                summaryEl.textContent = `${(data.total || 0)} lead(s) in ${currentStatus.toUpperCase()} queue`;
                pageIndicator.textContent = `Page ${data.page || 1} of ${data.pages || 1}`;
                prevBtn.disabled = (data.page || 1) <= 1;
                nextBtn.disabled = (data.page || 1) >= (data.pages || 1);

                if (!items.length) {
                    emptyEl.style.display = "block";
                    return;
                }

                renderRows(items);
                table.style.display = "table";
            })
            .catch(err => {
                loading.style.display = "none";
                errorEl.textContent = `Failed to load follow-up queue. ${err.message || ""}`;
                errorEl.style.display = "block";
            });
    }

    tabs.forEach(btn => {
        btn.addEventListener("click", () => {
            currentStatus = btn.dataset.status;
            currentPage = 1;
            setActiveTab(currentStatus);
            loadQueue(currentPage);
        });
    });

    prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage -= 1;
            loadQueue(currentPage);
        }
    });

    nextBtn.addEventListener("click", () => {
        currentPage += 1;
        loadQueue(currentPage);
    });

    setActiveTab(currentStatus);
    loadQueue(currentPage);
});
