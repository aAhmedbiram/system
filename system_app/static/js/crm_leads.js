document.addEventListener("DOMContentLoaded", () => {
    let currentPage = 1;
    const perPage = 25;
    let searchTimeout = null;
    let sourceTimeout = null;
    let assignedUserFilterValue = "";
    const canBulkAssign = !!window.CRM_USER_CAN_ASSIGN;
    const selectedLeadIds = new Set();

    // Elements
    const searchInput = document.getElementById("searchQuery");
    const stageSelect = document.getElementById("stageFilter");
    const typeSelect = document.getElementById("typeFilter");
    const sourceInput = document.getElementById("sourceFilter");
    const assignedUserSelect = document.getElementById("assignedUserFilter");

    const loadingState = document.getElementById("loadingState");
    const errorState = document.getElementById("errorState");
    const emptyState = document.getElementById("emptyState");
    const leadsTable = document.getElementById("leadsTable");
    const tableBody = document.getElementById("leadsTableBody");

    const prevBtn = document.getElementById("prevBtn");
    const nextBtn = document.getElementById("nextBtn");
    const pageIndicator = document.getElementById("pageIndicator");

    const bulkAssignToolbar = document.getElementById("bulkAssignToolbar");
    const selectVisibleLeads = document.getElementById("selectVisibleLeads");
    const selectAllLeads = document.getElementById("selectAllLeads");
    const selectedLeadCount = document.getElementById("selectedLeadCount");
    const bulkAssignUserSelect = document.getElementById("bulkAssignUserSelect");
    const bulkAssignBtn = document.getElementById("bulkAssignBtn");
    const clearLeadSelectionBtn = document.getElementById("clearLeadSelectionBtn");
    const bulkAssignFeedback = document.getElementById("bulkAssignFeedback");

    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    // Restore state from URL
    function restoreStateFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.has("page")) {
            currentPage = parseInt(urlParams.get("page")) || 1;
        }
        if (urlParams.has("search")) {
            searchInput.value = urlParams.get("search");
        }
        if (urlParams.has("stage")) {
            stageSelect.value = urlParams.get("stage");
        }
        if (urlParams.has("member_status")) {
            typeSelect.value = urlParams.get("member_status");
        }
        if (urlParams.has("source")) {
            sourceInput.value = urlParams.get("source");
        }
        if (urlParams.has("assigned_user_id")) {
            assignedUserFilterValue = urlParams.get("assigned_user_id");
        }
    }

    // Update URL state
    function updateUrlState() {
        const params = new URLSearchParams();
        if (currentPage > 1) {
            params.append("page", currentPage);
        }
        const search = searchInput.value.trim();
        if (search) {
            params.append("search", search);
        }
        const stage = stageSelect.value;
        if (stage) {
            params.append("stage", stage);
        }
        const type = typeSelect.value;
        if (type) {
            params.append("member_status", type);
        }
        const source = sourceInput.value.trim();
        if (source) {
            params.append("source", source);
        }
        if (assignedUserFilterValue) {
            params.append("assigned_user_id", assignedUserFilterValue);
        }

        const newSearch = params.toString();
        const newUrl = window.location.pathname + (newSearch ? "?" + newSearch : "");
        history.replaceState(null, "", newUrl);
    }

    function showBulkFeedback(message, isError) {
        if (!bulkAssignFeedback) return;
        bulkAssignFeedback.style.display = "block";
        bulkAssignFeedback.textContent = message;
        bulkAssignFeedback.style.background = isError ? "rgba(244,67,54,0.1)" : "rgba(76,175,80,0.1)";
        bulkAssignFeedback.style.border = isError ? "1px solid rgba(244,67,54,0.3)" : "1px solid rgba(76,175,80,0.3)";
        bulkAssignFeedback.style.color = isError ? "#f44336" : "#4caf50";
    }

    function clearBulkFeedback() {
        if (!bulkAssignFeedback) return;
        bulkAssignFeedback.style.display = "none";
        bulkAssignFeedback.textContent = "";
    }

    function syncAssignedUserSelect() {
        if (!assignedUserSelect) return;
        assignedUserSelect.value = assignedUserFilterValue || "";
    }

    function loadAssignedUserOptions() {
        if (!assignedUserSelect) return Promise.resolve();

        const loadingOption = document.createElement("option");
        loadingOption.value = "";
        loadingOption.textContent = "Loading employees...";
        assignedUserSelect.replaceChildren(loadingOption);

        return apiFetch("/crm/filter-users", { method: "GET" })
            .then(res => {
                if (!res.ok) {
                    throw new Error("Status " + res.status);
                }
                return res.json();
            })
            .then(users => {
                assignedUserSelect.replaceChildren();

                const allOption = document.createElement("option");
                allOption.value = "";
                allOption.textContent = "All Employees";
                assignedUserSelect.appendChild(allOption);

                const unassignedOption = document.createElement("option");
                unassignedOption.value = "unassigned";
                unassignedOption.textContent = "Unassigned";
                assignedUserSelect.appendChild(unassignedOption);

                (users || []).forEach(user => {
                    const option = document.createElement("option");
                    option.value = String(user.id);
                    option.textContent = user.username;
                    assignedUserSelect.appendChild(option);
                });

                syncAssignedUserSelect();
            })
            .catch(err => {
                console.error("Failed to load assigned-to filter users:", err);
                assignedUserSelect.replaceChildren();

                const allOption = document.createElement("option");
                allOption.value = "";
                allOption.textContent = "All Employees";
                assignedUserSelect.appendChild(allOption);

                const unassignedOption = document.createElement("option");
                unassignedOption.value = "unassigned";
                unassignedOption.textContent = "Unassigned";
                assignedUserSelect.appendChild(unassignedOption);

                syncAssignedUserSelect();
            });
    }

    function updateSelectionCount() {
        if (!selectedLeadCount) return;
        selectedLeadCount.textContent = `${selectedLeadIds.size} selected`;
        if (bulkAssignBtn) {
            bulkAssignBtn.disabled = selectedLeadIds.size === 0;
        }
        const visibleRowCheckboxes = tableBody.querySelectorAll('input[type="checkbox"][data-lead-id]');
        const visibleSelected = Array.from(visibleRowCheckboxes).filter(cb => cb.checked).length;
        if (selectAllLeads) {
            selectAllLeads.checked = visibleRowCheckboxes.length > 0 && visibleSelected === visibleRowCheckboxes.length;
            selectAllLeads.indeterminate = visibleSelected > 0 && visibleSelected < visibleRowCheckboxes.length;
        }
        if (selectVisibleLeads) {
            selectVisibleLeads.checked = visibleRowCheckboxes.length > 0 && visibleSelected === visibleRowCheckboxes.length;
            selectVisibleLeads.indeterminate = visibleSelected > 0 && visibleSelected < visibleRowCheckboxes.length;
        }
    }

    function clearSelection() {
        selectedLeadIds.clear();
        tableBody.querySelectorAll('input[type="checkbox"][data-lead-id]').forEach(cb => {
            cb.checked = false;
        });
        if (selectAllLeads) {
            selectAllLeads.checked = false;
            selectAllLeads.indeterminate = false;
        }
        updateSelectionCount();
    }

    function syncSelectionFromCheckboxes() {
        selectedLeadIds.clear();
        tableBody.querySelectorAll('input[type="checkbox"][data-lead-id]').forEach(cb => {
            if (cb.checked) {
                selectedLeadIds.add(Number(cb.dataset.leadId));
            }
        });
        updateSelectionCount();
    }

    function loadBulkAssignUsers() {
        if (!canBulkAssign || !bulkAssignUserSelect) return;
        if (bulkAssignUserSelect.dataset.loaded === "true") return;

        window.CRM.getAssignableUsers()
            .then(users => {
                bulkAssignUserSelect.replaceChildren();
                const placeholder = document.createElement("option");
                placeholder.value = "";
                placeholder.textContent = "Select target user";
                bulkAssignUserSelect.appendChild(placeholder);

                (users || []).forEach(user => {
                    const option = document.createElement("option");
                    option.value = String(user.id);
                    option.textContent = user.username;
                    bulkAssignUserSelect.appendChild(option);
                });
                bulkAssignUserSelect.dataset.loaded = "true";
            })
            .catch(() => {
                bulkAssignUserSelect.replaceChildren();
                const option = document.createElement("option");
                option.value = "";
                option.textContent = "Failed to load users";
                bulkAssignUserSelect.appendChild(option);
            });
    }

    // Fetch and render pipeline cards
    function loadPipelineSummary() {
        fetch("/crm/pipeline")
            .then(res => {
                if (!res.ok) throw new Error("Status " + res.status);
                return res.json();
            })
            .then(data => {
                let total = 0;
                const stages = ["NEW", "CONTACTED", "FOLLOW_UP", "INTERESTED", "TRIAL", "WON", "LOST"];

                stages.forEach(stage => {
                    const count = data[stage] || 0;
                    total += count;
                    const elId = "stat" + stage.replace("_", "").toLowerCase().split(" ").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join("");
                    const el = document.getElementById(elId);
                    if (el) el.textContent = count;
                });

                const totalEl = document.getElementById("statTotal");
                if (totalEl) totalEl.textContent = total;
            })
            .catch(err => {
                console.error("Failed to load pipeline stats:", err);
            });
    }

    // Fetch and render follow-up cards
    function loadFollowUpSummary() {
        fetch("/crm/follow-ups/summary")
            .then(res => {
                if (!res.ok) throw new Error("Status " + res.status);
                return res.json();
            })
            .then(data => {
                document.getElementById("followOverdue").textContent = data.overdue ?? 0;
                document.getElementById("followToday").textContent = data.today ?? 0;
                document.getElementById("followUpcoming").textContent = data.upcoming ?? 0;
            })
            .catch(err => {
                console.error("Failed to load follow-up stats:", err);
            });
    }

    // Fetch and render table rows
    function fetchLeads() {
        // Show loading state
        loadingState.style.display = "block";
        leadsTable.style.display = "none";
        errorState.style.display = "none";
        emptyState.style.display = "none";

        const params = new URLSearchParams({
            page: currentPage,
            per_page: perPage
        });

        const searchQuery = searchInput.value.trim();
        if (searchQuery) {
            params.append("search", searchQuery);
        }

        const stage = stageSelect.value;
        if (stage) {
            params.append("stage", stage);
        }

        const memberStatus = typeSelect.value;
        if (memberStatus) {
            params.append("member_status", memberStatus);
        }

        const source = sourceInput.value.trim();
        if (source) {
            params.append("source", source);
        }
        if (assignedUserFilterValue) {
            params.append("assigned_user_id", assignedUserFilterValue);
        }

        updateUrlState();

        fetch(`/crm/leads?${params.toString()}`)
            .then(res => {
                if (!res.ok) {
                    throw new Error("HTTP error " + res.status);
                }
                return res.json();
            })
            .then(data => {
                loadingState.style.display = "none";
                const items = data.items || [];

                if (items.length === 0) {
                    emptyState.style.display = "block";
                    return;
                }

                // Render table
                tableBody.innerHTML = "";
                items.forEach(lead => {
                    const row = document.createElement("tr");
                    row.dataset.leadId = lead.id;

                    if (canBulkAssign) {
                        const tdSelect = document.createElement("td");
                        const cb = document.createElement("input");
                        cb.type = "checkbox";
                        cb.dataset.leadId = lead.id;
                        cb.checked = selectedLeadIds.has(Number(lead.id));
                        cb.addEventListener("change", () => {
                            if (cb.checked) {
                                selectedLeadIds.add(Number(lead.id));
                            } else {
                                selectedLeadIds.delete(Number(lead.id));
                            }
                            updateSelectionCount();
                        });
                        tdSelect.appendChild(cb);
                        row.appendChild(tdSelect);
                    }

                    // Lead ID
                    const tdId = document.createElement("td");
                    tdId.textContent = lead.id;
                    row.appendChild(tdId);

                    // Name
                    const tdName = document.createElement("td");
                    const nameLink = document.createElement("a");
                    nameLink.href = `/crm/leads/${lead.id}/view`;
                    nameLink.textContent = lead.name || "—";
                    nameLink.style.color = "#4caf50";
                    nameLink.style.textDecoration = "none";
                    nameLink.style.fontWeight = "600";
                    tdName.appendChild(nameLink);
                    row.appendChild(tdName);

                    // Phone
                    const tdPhone = document.createElement("td");
                    tdPhone.textContent = lead.phone || "—";
                    row.appendChild(tdPhone);

                    // Type (Prospect vs Existing Member)
                    const tdType = document.createElement("td");
                    const typeSpan = document.createElement("span");
                    if (lead.member_id) {
                        typeSpan.className = "badge member";
                        typeSpan.textContent = "Member";
                    } else {
                        typeSpan.className = "badge prospect";
                        typeSpan.textContent = "Prospect";
                    }
                    tdType.appendChild(typeSpan);
                    row.appendChild(tdType);

                    // Member ID
                    const tdMemberId = document.createElement("td");
                    tdMemberId.textContent = lead.member_id || "—";
                    row.appendChild(tdMemberId);

                    // End Date
                    const tdEndDate = document.createElement("td");
                    const memberEndDate = lead.member_end_date == null ? "" : String(lead.member_end_date).trim();
                    tdEndDate.textContent = memberEndDate || "—";
                    row.appendChild(tdEndDate);

                    // Stage
                    const tdStage = document.createElement("td");
                    const stageSpan = document.createElement("span");
                    stageSpan.className = "badge stage";
                    if (lead.stage === "WON") {
                        stageSpan.className = "badge stage-won";
                    } else if (lead.stage === "LOST") {
                        stageSpan.className = "badge stage-lost";
                    }
                    stageSpan.textContent = formatStageLabel(lead.stage);
                    tdStage.appendChild(stageSpan);
                    row.appendChild(tdStage);

                    // Source
                    const tdSource = document.createElement("td");
                    tdSource.textContent = lead.source || "—";
                    row.appendChild(tdSource);

                    // Assigned To
                    const tdAssign = document.createElement("td");
                    tdAssign.textContent = lead.assigned_username || "Unassigned";
                    row.appendChild(tdAssign);

                    // Next Follow-Up
                    const tdFollow = document.createElement("td");
                    tdFollow.textContent = formatDatetime(lead.next_follow_up_at);
                    row.appendChild(tdFollow);

                    // Latest Activity
                    const tdLatestActivity = document.createElement("td");
                    const latestNote = lead.latest_activity_note == null ? "" : String(lead.latest_activity_note).trim();
                    const latestAt = lead.latest_activity_at ? formatDatetime(lead.latest_activity_at) : "";
                    if (!latestNote && !latestAt) {
                        tdLatestActivity.textContent = "—";
                    } else {
                        const activityWrap = document.createElement("div");
                        activityWrap.className = "lead-activity-cell";

                        if (latestNote) {
                            const noteLine = document.createElement("span");
                            noteLine.className = "lead-activity-note";
                            noteLine.textContent = truncateText(latestNote, 56);
                            noteLine.title = latestNote;
                            activityWrap.appendChild(noteLine);
                        } else {
                            const dashLine = document.createElement("span");
                            dashLine.textContent = "—";
                            activityWrap.appendChild(dashLine);
                        }

                        if (latestAt) {
                            const timeLine = document.createElement("span");
                            timeLine.className = "lead-activity-time";
                            timeLine.textContent = latestAt;
                            activityWrap.appendChild(timeLine);
                        }

                        tdLatestActivity.appendChild(activityWrap);
                    }
                    row.appendChild(tdLatestActivity);

                    // Created At
                    const tdCreated = document.createElement("td");
                    tdCreated.textContent = formatDatetime(lead.created_at);
                    row.appendChild(tdCreated);

                    tableBody.appendChild(row);
                });

                leadsTable.style.display = "table";

                // Setup pagination state
                const totalPages = data.pages || 1;
                pageIndicator.textContent = `Page ${currentPage} of ${totalPages}`;
                prevBtn.disabled = currentPage <= 1;
                nextBtn.disabled = currentPage >= totalPages;

                if (canBulkAssign) {
                    updateSelectionCount();
                    loadBulkAssignUsers();
                }
            })
            .catch(err => {
                console.error("Error loading leads:", err);
                loadingState.style.display = "none";
                errorState.style.display = "block";
            });
    }

    function formatStageLabel(stage) {
        if (!stage) return "—";
        const map = {
            "NEW": "New",
            "CONTACTED": "Contacted",
            "FOLLOW_UP": "Follow-Up",
            "INTERESTED": "Interested",
            "TRIAL": "Trial",
            "WON": "Won",
            "LOST": "Lost"
        };
        return map[stage] || stage;
    }

    function formatDatetime(dtString) {
        if (!dtString) return "—";
        try {
            const date = new Date(dtString);
            return date.toLocaleString();
        } catch (e) {
            return dtString;
        }
    }

    function truncateText(text, maxLength) {
        const value = text == null ? "" : String(text);
        if (value.length <= maxLength) {
            return value;
        }
        return value.slice(0, Math.max(0, maxLength - 1)).trimEnd() + "…";
    }

    // Event listeners
    prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            if (canBulkAssign) {
                clearSelection();
            }
            fetchLeads();
        }
    });

    nextBtn.addEventListener("click", () => {
        currentPage++;
        if (canBulkAssign) {
            clearSelection();
        }
        fetchLeads();
    });

    // Reset pagination on filter changes
    function onFilterChange() {
        currentPage = 1;
        if (canBulkAssign) {
            clearSelection();
        }
        fetchLeads();
    }

    stageSelect.addEventListener("change", onFilterChange);
    typeSelect.addEventListener("change", onFilterChange);

    searchInput.addEventListener("input", () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            onFilterChange();
        }, 300); // 300ms debounce
    });

    sourceInput.addEventListener("input", () => {
        clearTimeout(sourceTimeout);
        sourceTimeout = setTimeout(() => {
            onFilterChange();
        }, 300); // 300ms debounce
    });

    if (assignedUserSelect) {
        assignedUserSelect.addEventListener("change", () => {
            assignedUserFilterValue = assignedUserSelect.value;
            onFilterChange();
        });
    }

    if (canBulkAssign) {
        if (selectVisibleLeads) {
            selectVisibleLeads.addEventListener("change", () => {
                tableBody.querySelectorAll('input[type="checkbox"][data-lead-id]').forEach(cb => {
                    cb.checked = selectVisibleLeads.checked;
                    if (cb.checked) {
                        selectedLeadIds.add(Number(cb.dataset.leadId));
                    } else {
                        selectedLeadIds.delete(Number(cb.dataset.leadId));
                    }
                });
                updateSelectionCount();
            });
        }

        if (selectAllLeads) {
            selectAllLeads.addEventListener("change", () => {
                const checked = selectAllLeads.checked;
                tableBody.querySelectorAll('input[type="checkbox"][data-lead-id]').forEach(cb => {
                    cb.checked = checked;
                });
                syncSelectionFromCheckboxes();
            });
        }

        if (clearLeadSelectionBtn) {
            clearLeadSelectionBtn.addEventListener("click", () => {
                clearSelection();
                clearBulkFeedback();
            });
        }

        if (bulkAssignBtn) {
            bulkAssignBtn.addEventListener("click", () => {
                if (selectedLeadIds.size === 0) {
                    showBulkFeedback("Select at least one lead first.", true);
                    return;
                }
                const targetUserId = bulkAssignUserSelect ? bulkAssignUserSelect.value : "";
                if (!targetUserId) {
                    showBulkFeedback("Choose a target user first.", true);
                    return;
                }

                bulkAssignBtn.disabled = true;
                showBulkFeedback("Saving bulk assignment...", false);

                apiFetch("/crm/leads/bulk-assign", {
                    method: "POST",
                    body: JSON.stringify({
                        lead_ids: Array.from(selectedLeadIds),
                        user_id: Number(targetUserId)
                    })
                })
                    .then(res => res.json().then(data => ({ status: res.status, data })))
                    .then(r => {
                        if (r.status === 200) {
                            clearSelection();
                            clearBulkFeedback();
                            fetchLeads();
                            return;
                        }
                        showBulkFeedback((r.data && r.data.message) ? r.data.message : "Failed to bulk assign leads.", true);
                    })
                    .catch(() => {
                        showBulkFeedback("Network error while bulk assigning leads.", true);
                    })
                    .finally(() => {
                        bulkAssignBtn.disabled = selectedLeadIds.size === 0;
                    });
            });
        }
    }

    // Initial setup and load
    restoreStateFromUrl();
    loadPipelineSummary();
    loadFollowUpSummary();
    loadAssignedUserOptions();
    if (canBulkAssign) {
        loadBulkAssignUsers();
    }
    fetchLeads();
});
