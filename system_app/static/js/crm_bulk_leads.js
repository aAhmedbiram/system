document.addEventListener("DOMContentLoaded", () => {
    const canCreate = String(window.CRM_BULK_CAN_CREATE) === "true";
    const canAssign = String(window.CRM_BULK_CAN_ASSIGN) === "true";
    const initialState = window.CRM_BULK_INITIAL_STATE || null;
    const perPage = Number(window.CRM_BULK_PAGE_SIZE || 50);

    const bulkNotice = document.getElementById("bulkNotice");
    const selectionInfo = document.getElementById("selectionInfo");
    const selectedCount = document.getElementById("selectedCount");
    const matchingCount = document.getElementById("matchingCount");
    const selectionModeLabel = document.getElementById("selectionModeLabel");

    const bulkSearchId = document.getElementById("bulkSearchId");
    const bulkSearchName = document.getElementById("bulkSearchName");
    const bulkSearchPhone = document.getElementById("bulkSearchPhone");
    const bulkViewFilter = document.getElementById("bulkViewFilter");
    const bulkExpiresWithin = document.getElementById("bulkExpiresWithin");
    const bulkReloadMembersBtn = document.getElementById("bulkReloadMembersBtn");
    const selectVisibleBtn = document.getElementById("selectVisibleBtn");
    const clearVisibleBtn = document.getElementById("clearVisibleBtn");
    const selectFilteredBtn = document.getElementById("selectFilteredBtn");
    const clearAllBtn = document.getElementById("clearAllBtn");
    const previewDistributionBtn = document.getElementById("previewDistributionBtn");

    const membersLoading = document.getElementById("membersLoading");
    const membersError = document.getElementById("membersError");
    const bulkMembersTable = document.getElementById("bulkMembersTable");
    const bulkMembersTableBody = document.getElementById("bulkMembersTableBody");
    const membersPrevBtn = document.getElementById("membersPrevBtn");
    const membersNextBtn = document.getElementById("membersNextBtn");
    const membersPageIndicator = document.getElementById("membersPageIndicator");

    const distributionUnassigned = document.getElementById("distributionUnassigned");
    const distributionEqual = document.getElementById("distributionEqual");
    const employeePanel = document.getElementById("employeePanel");
    const employeeLoading = document.getElementById("employeeLoading");
    const employeeError = document.getElementById("employeeError");
    const employeeList = document.getElementById("employeeList");
    const employeeCountLabel = document.getElementById("employeeCountLabel");
    const distributionEstimate = document.getElementById("distributionEstimate");

    const operationStatusBadge = document.getElementById("operationStatusBadge");
    const previewLockedNotice = document.getElementById("previewLockedNotice");
    const previewResultNotice = document.getElementById("previewResultNotice");
    const confirmBulkBtn = document.getElementById("confirmBulkBtn");
    const newPreviewBtn = document.getElementById("newPreviewBtn");
    const executionFeedback = document.getElementById("executionFeedback");
    const previewTokenDebug = document.getElementById("previewTokenDebug");

    const previewSource = document.getElementById("previewSource");
    const previewSelected = document.getElementById("previewSelected");
    const previewEligible = document.getElementById("previewEligible");
    const previewSkipped = document.getElementById("previewSkipped");
    const previewMissing = document.getElementById("previewMissing");
    const previewPlanCount = document.getElementById("previewPlanCount");
    const previewDistributionEmpty = document.getElementById("previewDistributionEmpty");
    const previewDistributionList = document.getElementById("previewDistributionList");
    const previewSkippedReasonsEmpty = document.getElementById("previewSkippedReasonsEmpty");
    const previewSkippedReasonsList = document.getElementById("previewSkippedReasonsList");

    const resultRequested = document.getElementById("resultRequested");
    const resultCreated = document.getElementById("resultCreated");
    const resultSkipped = document.getElementById("resultSkipped");
    const resultFailed = document.getElementById("resultFailed");
    const resultAssignmentsEmpty = document.getElementById("resultAssignmentsEmpty");
    const resultAssignmentsList = document.getElementById("resultAssignmentsList");
    const resultSkippedItems = document.getElementById("resultSkippedItems");

    const state = {
        page: 1,
        totalPages: 1,
        totalCount: 0,
        members: [],
        filters: {
            view: "all",
            expires_within: "",
            search_id: "",
            search_name: "",
            search_phone: ""
        },
        selectedIds: new Set(),
        allFilteredSelected: false,
        selectionMode: "ids",
        distributionMode: "unassigned",
        assignableUsers: [],
        selectedEmployeeIds: new Set(),
        loadingMembers: false,
        loadingEmployees: false,
        previewToken: "",
        previewState: null,
        previewExecution: null,
        locked: false,
        status: null,
        memberLoadTimer: null,
        employeeLoadTimer: null
    };

    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    function setClassVisibility(node, visible, displayValue) {
        if (!node) return;
        if (visible) {
            node.classList.remove("hidden");
            if (displayValue) {
                node.style.display = displayValue;
            } else {
                node.style.removeProperty("display");
            }
        } else {
            node.classList.add("hidden");
            node.style.display = "none";
        }
    }

    function setNotice(node, message, kind) {
        if (!node) return;
        node.textContent = message || "";
        node.className = "notice";
        if (kind) {
            node.classList.add(kind);
        }
        node.style.display = message ? "block" : "none";
    }

    function clearNode(node) {
        if (!node) return;
        node.replaceChildren();
    }

    function sortedSelectedEmployeeIds() {
        return Array.from(state.selectedEmployeeIds).sort((a, b) => a - b);
    }

    function currentFilters() {
        return {
            view: bulkViewFilter ? bulkViewFilter.value || "all" : "all",
            expires_within: bulkExpiresWithin ? bulkExpiresWithin.value || "" : "",
            search_id: bulkSearchId ? bulkSearchId.value.trim() : "",
            search_name: bulkSearchName ? bulkSearchName.value.trim() : "",
            search_phone: bulkSearchPhone ? bulkSearchPhone.value.trim() : ""
        };
    }

    function normalizeFilterPayload(filters) {
        const payload = {};
        Object.entries(filters).forEach(([key, value]) => {
            if (value !== "" && value !== null && value !== undefined) {
                payload[key] = value;
            }
        });
        return payload;
    }

    function effectiveSelectedCount() {
        if (state.locked && state.previewState && state.previewState.summary) {
            return Number(state.previewState.summary.selected_count || 0);
        }
        if (state.allFilteredSelected) {
            return Number(state.totalCount || 0);
        }
        return state.selectedIds.size;
    }

    function effectiveModeLabel() {
        if (state.locked && state.status) {
            return "Frozen Preview";
        }
        if (state.allFilteredSelected) {
            return "All Filtered";
        }
        return "Explicit IDs";
    }

    function updateSelectionSummary() {
        if (selectedCount) {
            selectedCount.textContent = String(effectiveSelectedCount());
        }
        if (matchingCount) {
            if (state.locked && state.previewState && state.previewState.summary) {
                matchingCount.textContent = String(state.previewState.summary.selected_count || 0);
            } else {
                matchingCount.textContent = String(state.totalCount || 0);
            }
        }
        if (selectionModeLabel) {
            selectionModeLabel.textContent = effectiveModeLabel();
        }

        if (state.locked) {
            setNotice(selectionInfo, "Preview is frozen. Create a new preview to change filters, selection, or employees.", "warning");
            return;
        }

        if (state.allFilteredSelected) {
            setNotice(selectionInfo, `All ${state.totalCount || 0} members matching the current filters are selected.`, "success");
            return;
        }

        if (state.selectedIds.size > 0) {
            setNotice(selectionInfo, `${state.selectedIds.size} member(s) selected across pages.`, "success");
            return;
        }

        setNotice(selectionInfo, "No members selected yet.", "warning");
    }

    function updateOperationBadge() {
        if (!operationStatusBadge) return;
        operationStatusBadge.className = "badge";
        const status = state.status || "NONE";
        if (status === "PREVIEW") {
            operationStatusBadge.classList.add("badge-warn");
            operationStatusBadge.textContent = "Preview Ready";
        } else if (status === "COMPLETED") {
            operationStatusBadge.classList.add("badge-ok");
            operationStatusBadge.textContent = "Completed";
        } else if (status === "FAILED") {
            operationStatusBadge.classList.add("badge-danger");
            operationStatusBadge.textContent = "Failed";
        } else {
            operationStatusBadge.classList.add("badge-warn");
            operationStatusBadge.textContent = "No Preview Yet";
        }
    }

    function updateConfirmState() {
        if (!confirmBulkBtn || !newPreviewBtn) return;
        const hasPreview = Boolean(state.previewToken);
        const canExecuteEqual = state.distributionMode !== "equal" || canAssign;
        const canExecute = hasPreview && state.status === "PREVIEW" && canExecuteEqual;
        confirmBulkBtn.disabled = !canExecute;
        newPreviewBtn.disabled = !hasPreview && state.status !== "COMPLETED" && state.status !== "FAILED";
    }

    function setLockedUi(locked) {
        state.locked = locked;
        const controls = [
            bulkSearchId,
            bulkSearchName,
            bulkSearchPhone,
            bulkViewFilter,
            bulkExpiresWithin,
            bulkReloadMembersBtn,
            selectVisibleBtn,
            clearVisibleBtn,
            selectFilteredBtn,
            clearAllBtn,
            previewDistributionBtn,
            distributionUnassigned,
            distributionEqual,
            membersPrevBtn,
            membersNextBtn
        ];
        controls.forEach((el) => {
            if (el) {
                el.disabled = locked;
            }
        });
        if (state.locked || state.allFilteredSelected) {
            updateSelectionSummary();
        }
    }

    function setPreviewStateFromServer(serverState) {
        const snapshot = serverState ? (serverState.snapshot || {}) : {};
        const summary = serverState ? (serverState.summary || null) : null;
        state.previewState = serverState;
        state.previewToken = serverState && serverState.preview_token ? serverState.preview_token : "";
        state.status = serverState ? serverState.status : null;
        state.previewExecution = serverState ? (serverState.execution || null) : null;
        state.distributionMode = (snapshot.distribution || {}).mode || "unassigned";

        if (snapshot.selection && snapshot.selection.mode === "ids") {
            state.selectionMode = "ids";
            state.selectedIds = new Set(snapshot.selection.selected_member_ids || []);
            state.allFilteredSelected = false;
        } else if (snapshot.selection && snapshot.selection.mode === "filters") {
            state.selectionMode = "filters";
            state.selectedIds = new Set();
            state.allFilteredSelected = true;
        }

        if (snapshot.distribution && snapshot.distribution.mode === "equal") {
            state.selectedEmployeeIds = new Set(snapshot.distribution.user_ids || []);
        } else {
            state.selectedEmployeeIds = new Set();
        }

        if (previewTokenDebug) {
            previewTokenDebug.textContent = state.previewToken || "";
        }

        if (summary) {
            renderPreviewSummary(summary);
        }
        if (state.previewExecution) {
            renderExecutionResult(state.previewExecution);
        }

        setLockedUi(Boolean(state.previewToken));
        updatePreviewLockNotice();
        updateOperationBadge();
        updateConfirmState();
        updateDistributionEstimate();
        updateEmployeeSelectionCount();
    }

    function updatePreviewLockNotice() {
        if (!previewLockedNotice) return;
        if (!state.previewToken) {
            setClassVisibility(previewLockedNotice, false);
            return;
        }

        const summary = state.previewState && state.previewState.summary ? state.previewState.summary : null;
        const isCompleted = state.status === "COMPLETED";
        const isFailed = state.status === "FAILED";
        const isPreview = state.status === "PREVIEW";

        if (isCompleted) {
            setNotice(previewLockedNotice, "This preview was executed successfully. Create a new preview to start another bulk operation.", "success");
        } else if (isFailed) {
            setNotice(previewLockedNotice, "This bulk execution failed. Create a new preview to try again.", "error");
        } else if (isPreview) {
            const requiresAssign = summary && summary.distribution_mode === "equal" && !canAssign;
            if (requiresAssign) {
                setNotice(previewLockedNotice, "This preview requires crm_assign and the current user no longer has it. Create a new unassigned preview or restore permission.", "error");
            } else {
                setNotice(previewLockedNotice, "Preview loaded. The configuration is frozen until you confirm execution or create a new preview.", "warning");
            }
        } else {
            setClassVisibility(previewLockedNotice, false);
        }
    }

    function updateEmployeeSelectionCount() {
        if (!employeeCountLabel) return;
        employeeCountLabel.textContent = `${state.selectedEmployeeIds.size} selected`;
    }

    function updateEmployeesPanelVisibility() {
        if (!employeePanel) return;
        const show = state.distributionMode === "equal" && canAssign;
        setClassVisibility(employeePanel, show, "block");
    }

    function updateDistributionEstimate() {
        if (!distributionEstimate) return;
        if (state.distributionMode !== "equal") {
            distributionEstimate.textContent = "Unassigned mode selected. No employee distribution will be applied.";
            return;
        }
        if (!canAssign) {
            distributionEstimate.textContent = "Equal distribution is unavailable without crm_assign.";
            return;
        }
        const employeeIds = sortedSelectedEmployeeIds();
        const chosenEmployees = employeeIds
            .map((userId) => state.assignableUsers.find((row) => Number(row.id) === Number(userId)))
            .filter(Boolean)
            .sort((a, b) => Number(a.id) - Number(b.id));
        const selected = effectiveSelectedCount();
        if (employeeIds.length === 0) {
            distributionEstimate.textContent = "Select employees to see the estimated split.";
            return;
        }
        const base = employeeIds.length ? Math.floor(selected / employeeIds.length) : 0;
        const remainder = employeeIds.length ? (selected % employeeIds.length) : 0;
        const lines = chosenEmployees.map((employee, index) => {
            const leadCount = base + (index < remainder ? 1 : 0);
            return `${employee.username} (#${employee.id}) — ${leadCount}`;
        });
        distributionEstimate.replaceChildren();
        const intro = document.createElement("div");
        intro.textContent = `Estimated split for ${selected} selected member(s):`;
        distributionEstimate.appendChild(intro);
        const list = document.createElement("div");
        list.className = "summary-list";
        lines.forEach((line) => {
            const row = document.createElement("div");
            row.className = "summary-row";
            const label = document.createElement("strong");
            label.textContent = line.split(" — ")[0];
            const value = document.createElement("span");
            value.textContent = line.split(" — ")[1] || "";
            row.appendChild(label);
            row.appendChild(value);
            list.appendChild(row);
        });
        distributionEstimate.appendChild(list);
    }

    function renderPreviewSummary(summary) {
        if (!summary) return;
        if (previewSource) previewSource.textContent = summary.source || "EXISTING_MEMBER";
        if (previewSelected) previewSelected.textContent = String(summary.selected_count ?? 0);
        if (previewEligible) previewEligible.textContent = String(summary.eligible_count ?? 0);
        if (previewSkipped) previewSkipped.textContent = String(summary.skipped_count ?? 0);
        if (previewMissing) previewMissing.textContent = String(summary.missing_count ?? 0);
        if (previewPlanCount) previewPlanCount.textContent = String(summary.assignment_plan_count ?? 0);
        if (previewTokenDebug) previewTokenDebug.textContent = summary.preview_token || state.previewToken || "";

        const distribution = Array.isArray(summary.distribution) ? summary.distribution : [];
        if (previewDistributionList && previewDistributionEmpty) {
            clearNode(previewDistributionList);
            if (distribution.length === 0) {
                setClassVisibility(previewDistributionList, false);
                setClassVisibility(previewDistributionEmpty, true, "block");
                previewDistributionEmpty.textContent = "Unassigned preview.";
            } else {
                setClassVisibility(previewDistributionEmpty, false);
                setClassVisibility(previewDistributionList, true, "grid");
                distribution.forEach((row) => {
                    const entry = document.createElement("div");
                    entry.className = "summary-row";
                    const left = document.createElement("strong");
                    left.textContent = `${row.username || ("User " + String(row.user_id ?? ""))} (#${String(row.user_id ?? "n/a")})`;
                    const right = document.createElement("span");
                    right.textContent = `${String(row.lead_count ?? 0)} planned`;
                    entry.appendChild(left);
                    entry.appendChild(right);
                    previewDistributionList.appendChild(entry);
                });
            }
        }

        const skippedReasons = summary.skipped_reasons || {};
        if (previewSkippedReasonsList && previewSkippedReasonsEmpty) {
            clearNode(previewSkippedReasonsList);
            const entries = Object.entries(skippedReasons);
            if (entries.length === 0) {
                setClassVisibility(previewSkippedReasonsList, false);
                setClassVisibility(previewSkippedReasonsEmpty, true, "block");
                previewSkippedReasonsEmpty.textContent = "No skipped reasons.";
            } else {
                setClassVisibility(previewSkippedReasonsEmpty, false);
                setClassVisibility(previewSkippedReasonsList, true, "grid");
                entries.forEach(([reason, count]) => {
                    const row = document.createElement("div");
                    row.className = "summary-row";
                    const left = document.createElement("strong");
                    left.textContent = reason;
                    const right = document.createElement("span");
                    right.textContent = String(count);
                    row.appendChild(left);
                    row.appendChild(right);
                    previewSkippedReasonsList.appendChild(row);
                });
            }
        }
    }

    function renderExecutionResult(result) {
        if (!result) return;
        if (resultRequested) resultRequested.textContent = String(result.requested ?? 0);
        if (resultCreated) resultCreated.textContent = String(result.created ?? 0);
        if (resultSkipped) resultSkipped.textContent = String(result.skipped ?? 0);
        if (resultFailed) resultFailed.textContent = String(result.failed ?? 0);
        if (resultSkippedItems) {
            resultSkippedItems.textContent = JSON.stringify(result.skipped_items || [], null, 2);
        }

        const assignments = Array.isArray(result.assignments) ? result.assignments : [];
        if (resultAssignmentsList && resultAssignmentsEmpty) {
            clearNode(resultAssignmentsList);
            if (assignments.length === 0) {
                setClassVisibility(resultAssignmentsList, false);
                setClassVisibility(resultAssignmentsEmpty, true, "block");
                resultAssignmentsEmpty.textContent = "No per-employee assignment totals.";
            } else {
                setClassVisibility(resultAssignmentsEmpty, false);
                setClassVisibility(resultAssignmentsList, true, "grid");
                assignments.forEach((row) => {
                    const entry = document.createElement("div");
                    entry.className = "summary-row";
                    const left = document.createElement("strong");
                    left.textContent = `${row.username || ("User " + String(row.user_id ?? ""))} (#${String(row.user_id ?? "n/a")})`;
                    const right = document.createElement("span");
                    right.textContent = `${String(row.created ?? 0)} created`;
                    entry.appendChild(left);
                    entry.appendChild(right);
                    resultAssignmentsList.appendChild(entry);
                });
            }
        }
    }

    function updatePreviewResultNotice(message, kind) {
        if (!previewResultNotice) return;
        setNotice(previewResultNotice, message, kind || "warning");
    }

    function setExecutionFeedback(message, kind) {
        if (!executionFeedback) return;
        setNotice(executionFeedback, message, kind || "success");
    }

    function clearExecutionFeedback() {
        if (!executionFeedback) return;
        setClassVisibility(executionFeedback, false);
        executionFeedback.textContent = "";
    }

    function getEmployeesForEstimate() {
        return sortedSelectedEmployeeIds()
            .map((userId) => state.assignableUsers.find((row) => Number(row.id) === Number(userId)))
            .filter(Boolean)
            .sort((a, b) => Number(a.id) - Number(b.id));
    }

    function renderEmployeeList() {
        if (!employeeList) return;
        clearNode(employeeList);
        const users = state.assignableUsers.slice().sort((a, b) => Number(a.id) - Number(b.id));
        users.forEach((user) => {
            const row = document.createElement("label");
            row.className = "checkbox-row";
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = String(user.id);
            checkbox.checked = state.selectedEmployeeIds.has(Number(user.id));
            checkbox.disabled = state.locked;
            const labelWrap = document.createElement("span");
            const strong = document.createElement("strong");
            strong.textContent = `${user.username} (#${user.id})`;
            const sub = document.createElement("div");
            sub.className = "small-note";
            sub.textContent = user.email || "";
            labelWrap.appendChild(strong);
            if (user.email) {
                labelWrap.appendChild(sub);
            }
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) {
                    state.selectedEmployeeIds.add(Number(user.id));
                } else {
                    state.selectedEmployeeIds.delete(Number(user.id));
                }
                updateEmployeeSelectionCount();
                updateDistributionEstimate();
            });
            row.appendChild(checkbox);
            row.appendChild(labelWrap);
            employeeList.appendChild(row);
        });
        updateEmployeeSelectionCount();
        updateDistributionEstimate();
    }

    function setEmployeePanelLoading(isLoading) {
        state.loadingEmployees = isLoading;
        setClassVisibility(employeeLoading, isLoading, "block");
    }

    async function loadAssignableUsers() {
        if (!canAssign || state.loadingEmployees || state.assignableUsers.length > 0) {
            updateEmployeesPanelVisibility();
            renderEmployeeList();
            return;
        }
        setEmployeePanelLoading(true);
        setClassVisibility(employeeError, false);
        try {
            const response = await apiFetch("/crm/users", { method: "GET" });
            const data = await response.json();
            if (!response.ok) {
                throw new Error((data && data.message) ? data.message : "Unable to load assignable employees.");
            }
            state.assignableUsers = Array.isArray(data) ? data.slice().sort((a, b) => Number(a.id) - Number(b.id)) : [];
            renderEmployeeList();
        } catch (error) {
            if (employeeError) {
                employeeError.textContent = error && error.message ? error.message : "Unable to load assignable employees.";
                setClassVisibility(employeeError, true, "block");
            }
        } finally {
            setEmployeePanelLoading(false);
            updateEmployeesPanelVisibility();
        }
    }

    function buildMembersQuery(page) {
        const params = new URLSearchParams();
        params.set("page", String(page));
        params.set("per_page", String(perPage));
        Object.entries(currentFilters()).forEach(([key, value]) => {
            if (value !== "" && value !== null && value !== undefined) {
                params.set(key, String(value));
            }
        });
        return params.toString();
    }

    function setMembersLoading(isLoading) {
        state.loadingMembers = isLoading;
        setClassVisibility(membersLoading, isLoading, "block");
        if (bulkMembersTable && isLoading) {
            setClassVisibility(bulkMembersTable, false);
        }
    }

    function clearMembersError() {
        setClassVisibility(membersError, false);
        if (membersError) {
            membersError.textContent = "";
        }
    }

    function renderMembers(items) {
        if (!bulkMembersTableBody || !bulkMembersTable) return;
        clearNode(bulkMembersTableBody);
        items.forEach((member) => {
            const tr = document.createElement("tr");
            const hasActiveLead = Boolean(member.has_active_crm_lead);
            const checkboxCell = document.createElement("td");
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = String(member.id);
            checkbox.checked = state.allFilteredSelected || state.selectedIds.has(Number(member.id));
            checkbox.disabled = state.locked || hasActiveLead || state.allFilteredSelected;
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) {
                    state.selectedIds.add(Number(member.id));
                } else {
                    state.selectedIds.delete(Number(member.id));
                }
                state.selectionMode = "ids";
                state.allFilteredSelected = false;
                updateSelectionSummary();
                updateDistributionEstimate();
            });
            checkboxCell.appendChild(checkbox);
            tr.appendChild(checkboxCell);

            const columns = [
                String(member.id || ""),
                member.name || "",
                member.phone || "",
                member.membership_packages || "",
                member.end_date || "",
                member.membership_status || ""
            ];
            columns.forEach((value) => {
                const td = document.createElement("td");
                td.textContent = value;
                tr.appendChild(td);
            });

            const crmCell = document.createElement("td");
            const badge = document.createElement("span");
            badge.className = hasActiveLead ? "badge badge-danger" : "badge badge-ok";
            badge.textContent = hasActiveLead ? "Already in CRM" : "Available";
            crmCell.appendChild(badge);
            tr.appendChild(crmCell);

            if (hasActiveLead) {
                tr.classList.add("row-muted");
                tr.title = "This member already has an active CRM lead and will be skipped by preview/execution.";
            }

            bulkMembersTableBody.appendChild(tr);
        });
        setClassVisibility(bulkMembersTable, true, "table");
    }

    async function loadMembers(page) {
        state.page = Number(page || state.page || 1);
        setMembersLoading(true);
        clearMembersError();
        try {
            const response = await apiFetch(`/crm/leads/bulk/members?${buildMembersQuery(state.page)}`, { method: "GET" });
            const data = await response.json();
            if (!response.ok) {
                throw new Error((data && data.message) ? data.message : "Failed to load members.");
            }
            state.members = data.items || [];
            state.totalCount = Number(data.total_count || 0);
            state.totalPages = Number(data.total_pages || 1);
            if (membersPageIndicator) {
                membersPageIndicator.textContent = `Page ${state.page} of ${state.totalPages}`;
            }
            if (membersPrevBtn) {
                membersPrevBtn.disabled = state.locked || state.page <= 1;
            }
            if (membersNextBtn) {
                membersNextBtn.disabled = state.locked || state.page >= state.totalPages;
            }
            renderMembers(state.members);
            updateSelectionSummary();
            updateDistributionEstimate();
        } catch (error) {
            if (membersError) {
                membersError.textContent = error && error.message ? error.message : "Failed to load members.";
                setClassVisibility(membersError, true, "block");
            }
        } finally {
            setMembersLoading(false);
        }
    }

    function resetSelectionState() {
        state.selectedIds = new Set();
        state.allFilteredSelected = false;
        state.selectionMode = "ids";
        updateSelectionSummary();
    }

    function resetPreviewState() {
        state.previewToken = "";
        state.previewState = null;
        state.previewExecution = null;
        state.status = null;
        if (previewTokenDebug) {
            previewTokenDebug.textContent = "";
        }
        if (resultRequested) resultRequested.textContent = "0";
        if (resultCreated) resultCreated.textContent = "0";
        if (resultSkipped) resultSkipped.textContent = "0";
        if (resultFailed) resultFailed.textContent = "0";
        if (resultSkippedItems) resultSkippedItems.textContent = "[]";
        clearNode(resultAssignmentsList);
        setClassVisibility(resultAssignmentsList, false);
        setClassVisibility(resultAssignmentsEmpty, true, "block");
        resultAssignmentsEmpty.textContent = "No execution result yet.";
        setClassVisibility(previewDistributionList, false);
        setClassVisibility(previewDistributionEmpty, true, "block");
        previewDistributionEmpty.textContent = "No preview loaded yet.";
        setClassVisibility(previewSkippedReasonsList, false);
        setClassVisibility(previewSkippedReasonsEmpty, true, "block");
        previewSkippedReasonsEmpty.textContent = "No skipped reasons yet.";
        if (previewLockedNotice) {
            setClassVisibility(previewLockedNotice, false);
        }
        if (previewResultNotice) {
            setClassVisibility(previewResultNotice, false);
        }
        updateOperationBadge();
        setLockedUi(false);
        if (confirmBulkBtn) confirmBulkBtn.disabled = true;
        if (newPreviewBtn) newPreviewBtn.disabled = true;
        updateConfirmState();
        setExecutionFeedback("", "success");
    }

    function collectPreviewPayload() {
        const filters = currentFilters();
        const selection = state.allFilteredSelected
            ? { mode: "filters", filters: normalizeFilterPayload(filters) }
            : { mode: "ids", member_ids: Array.from(state.selectedIds).sort((a, b) => a - b) };
        const distribution = state.distributionMode === "equal"
            ? { mode: "equal", user_ids: sortedSelectedEmployeeIds() }
            : { mode: "unassigned" };
        return {
            selection,
            distribution,
            source: "EXISTING_MEMBER"
        };
    }

    async function previewDistribution() {
        if (!canCreate) {
            return;
        }
        if (state.locked) {
            return;
        }
        const selectedCountValue = effectiveSelectedCount();
        if (selectedCountValue <= 0) {
            setExecutionFeedback("Select at least one member before previewing.", "error");
            return;
        }
        if (state.distributionMode === "equal" && canAssign && state.selectedEmployeeIds.size === 0) {
            setExecutionFeedback("Select at least one employee for equal distribution.", "error");
            return;
        }

        clearExecutionFeedback();
        if (previewDistributionBtn) {
            previewDistributionBtn.disabled = true;
            previewDistributionBtn.textContent = "Previewing...";
        }

        try {
            const payload = collectPreviewPayload();
            const response = await apiFetch("/crm/leads/bulk/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error((data && data.message) ? data.message : "Preview failed.");
            }
            const nextUrl = `/crm/leads/bulk?preview_token=${encodeURIComponent(data.preview_token)}`;
            window.location.href = nextUrl;
        } catch (error) {
            setExecutionFeedback(error && error.message ? error.message : "Preview failed.", "error");
        } finally {
            if (previewDistributionBtn) {
                previewDistributionBtn.disabled = state.locked;
                previewDistributionBtn.textContent = "Preview Distribution";
            }
        }
    }

    async function executeBulkLeads() {
        if (!state.previewToken || state.status !== "PREVIEW") {
            return;
        }
        if (state.distributionMode === "equal" && !canAssign) {
            setExecutionFeedback("This preview requires crm_assign permission.", "error");
            return;
        }

        clearExecutionFeedback();
        if (confirmBulkBtn) {
            confirmBulkBtn.disabled = true;
            confirmBulkBtn.textContent = "Executing...";
        }
        setNotice(previewResultNotice, "Executing bulk leads...", "warning");

        try {
            const response = await apiFetch("/crm/leads/bulk/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ preview_token: state.previewToken })
            });
            const contentType = response.headers.get("content-type") || "";
            let data = null;
            if (contentType.includes("application/json")) {
                data = await response.json();
            } else {
                const text = await response.text();
                data = { message: text };
            }

            if (!response.ok) {
                const message = (data && data.message) ? data.message : "Bulk execution failed.";
                setExecutionFeedback(message, "error");
                state.status = "FAILED";
                updateOperationBadge();
                updatePreviewLockNotice();
                if (confirmBulkBtn) {
                    confirmBulkBtn.disabled = true;
                    confirmBulkBtn.textContent = "Confirm & Create Leads";
                }
                return;
            }

            state.previewExecution = data;
            state.status = data.status || "COMPLETED";
            renderExecutionResult(data);
            updateOperationBadge();
            updatePreviewLockNotice();
            setExecutionFeedback(`Bulk execution completed. Created ${String(data.created ?? 0)} lead(s), skipped ${String(data.skipped ?? 0)}.`, "success");
            if (confirmBulkBtn) {
                confirmBulkBtn.disabled = true;
                confirmBulkBtn.textContent = "Completed";
            }
            if (newPreviewBtn) {
                newPreviewBtn.disabled = false;
            }
        } catch (error) {
            setExecutionFeedback(error && error.message ? error.message : "Bulk execution failed.", "error");
        } finally {
            if (confirmBulkBtn && state.status === "PREVIEW") {
                confirmBulkBtn.disabled = false;
                confirmBulkBtn.textContent = "Confirm & Create Leads";
            }
            if (confirmBulkBtn && state.status === "COMPLETED") {
                confirmBulkBtn.disabled = true;
            }
        }
    }

    function syncPaginationButtons() {
        if (membersPrevBtn) {
            membersPrevBtn.disabled = state.locked || state.page <= 1;
        }
        if (membersNextBtn) {
            membersNextBtn.disabled = state.locked || state.page >= state.totalPages;
        }
        if (membersPageIndicator) {
            membersPageIndicator.textContent = `Page ${state.page} of ${state.totalPages}`;
        }
    }

    function wireFilterChangeHandlers() {
        const handler = () => {
            if (state.locked) return;
            resetSelectionState();
            state.page = 1;
            loadMembers(1);
        };
        const debounce = (fn, delay) => {
            let timer = null;
            return () => {
                if (timer) clearTimeout(timer);
                timer = setTimeout(() => fn(), delay);
            };
        };
        const debouncedHandler = debounce(handler, 250);
        [bulkSearchId, bulkSearchName, bulkSearchPhone].forEach((input) => {
            if (input) {
                input.addEventListener("input", debouncedHandler);
            }
        });
        [bulkViewFilter, bulkExpiresWithin].forEach((input) => {
            if (input) {
                input.addEventListener("change", handler);
            }
        });
    }

    function wireDistributionHandlers() {
        if (distributionUnassigned) {
            distributionUnassigned.addEventListener("change", () => {
                if (!distributionUnassigned.checked || state.locked) return;
                state.distributionMode = "unassigned";
                setClassVisibility(employeePanel, false);
                updateDistributionEstimate();
                updateConfirmState();
            });
        }
        if (distributionEqual) {
            distributionEqual.addEventListener("change", () => {
                if (!distributionEqual.checked || state.locked) return;
                state.distributionMode = "equal";
                updateEmployeesPanelVisibility();
                loadAssignableUsers();
                updateDistributionEstimate();
                updateConfirmState();
            });
        }
    }

    function wireSelectionHandlers() {
        if (selectVisibleBtn) {
            selectVisibleBtn.addEventListener("click", () => {
                if (state.locked || state.allFilteredSelected) return;
                state.members.forEach((member) => {
                    if (!member.has_active_crm_lead) {
                        state.selectedIds.add(Number(member.id));
                    }
                });
                state.selectionMode = "ids";
                updateSelectionSummary();
                renderMembers(state.members);
                updateDistributionEstimate();
            });
        }

        if (clearVisibleBtn) {
            clearVisibleBtn.addEventListener("click", () => {
                if (state.locked || state.allFilteredSelected) return;
                state.members.forEach((member) => {
                    state.selectedIds.delete(Number(member.id));
                });
                state.selectionMode = "ids";
                updateSelectionSummary();
                renderMembers(state.members);
                updateDistributionEstimate();
            });
        }

        if (selectFilteredBtn) {
            selectFilteredBtn.addEventListener("click", () => {
                if (state.locked) return;
                state.selectionMode = "filters";
                state.allFilteredSelected = true;
                state.selectedIds.clear();
                updateSelectionSummary();
                renderMembers(state.members);
                updateDistributionEstimate();
            });
        }

        if (clearAllBtn) {
            clearAllBtn.addEventListener("click", () => {
                if (state.locked) return;
                resetSelectionState();
                renderMembers(state.members);
                updateDistributionEstimate();
            });
        }
    }

    function wirePaginationHandlers() {
        if (membersPrevBtn) {
            membersPrevBtn.addEventListener("click", () => {
                if (state.locked || state.page <= 1) return;
                loadMembers(state.page - 1);
            });
        }
        if (membersNextBtn) {
            membersNextBtn.addEventListener("click", () => {
                if (state.locked || state.page >= state.totalPages) return;
                loadMembers(state.page + 1);
            });
        }
        if (bulkReloadMembersBtn) {
            bulkReloadMembersBtn.addEventListener("click", () => {
                if (state.locked) return;
                loadMembers(state.page);
            });
        }
    }

    function wireActionHandlers() {
        if (previewDistributionBtn) {
            previewDistributionBtn.addEventListener("click", previewDistribution);
        }
        if (confirmBulkBtn) {
            confirmBulkBtn.addEventListener("click", executeBulkLeads);
        }
        if (newPreviewBtn) {
            newPreviewBtn.addEventListener("click", () => {
                window.location.href = "/crm/leads/bulk";
            });
        }
    }

    function syncDistributionRadiosFromState() {
        if (state.distributionMode === "equal" && distributionEqual) {
            distributionEqual.checked = true;
            state.selectionMode = state.selectionMode || "ids";
            updateEmployeesPanelVisibility();
        } else if (distributionUnassigned) {
            distributionUnassigned.checked = true;
        }
        updateConfirmState();
    }

    function applyInitialState() {
        if (!initialState || !initialState.preview_token) {
            updateOperationBadge();
            updateSelectionSummary();
            updateConfirmState();
            return;
        }

        state.previewToken = initialState.preview_token || "";
        state.status = initialState.status || null;
        state.previewState = initialState;
        state.previewExecution = initialState.execution || null;
        if (previewTokenDebug) {
            previewTokenDebug.textContent = state.previewToken;
        }

        const snapshot = initialState.snapshot || {};
        state.distributionMode = (snapshot.distribution || {}).mode || "unassigned";
        if (snapshot.selection && snapshot.selection.mode === "ids") {
            state.selectionMode = "ids";
            state.selectedIds = new Set(snapshot.selection.selected_member_ids || []);
            state.allFilteredSelected = false;
        } else if (snapshot.selection && snapshot.selection.mode === "filters") {
            state.selectionMode = "filters";
            state.allFilteredSelected = true;
            state.selectedIds = new Set();
        }
        if (snapshot.distribution && snapshot.distribution.mode === "equal") {
            state.selectedEmployeeIds = new Set(snapshot.distribution.user_ids || []);
        }

        updateOperationBadge();
        setLockedUi(true);
        syncDistributionRadiosFromState();
        setClassVisibility(previewLockedNotice, true, "block");
        updatePreviewLockNotice();
        updateSelectionSummary();
        updateConfirmState();
        updateDistributionEstimate();
        if (initialState.summary) {
            renderPreviewSummary(initialState.summary);
        }
        if (initialState.execution) {
            renderExecutionResult(initialState.execution);
            if (state.status === "COMPLETED") {
                setExecutionFeedback(`Bulk execution completed. Created ${String(initialState.execution.created ?? 0)} lead(s), skipped ${String(initialState.execution.skipped ?? 0)}.`, "success");
            } else if (state.status === "FAILED") {
                setExecutionFeedback("Bulk execution failed.", "error");
            }
        }
        if (state.status === "PREVIEW" && state.previewState && state.previewState.summary) {
            const requiresAssign = state.previewState.summary.distribution_mode === "equal" && !canAssign;
            if (requiresAssign) {
                confirmBulkBtn.disabled = true;
            } else {
                confirmBulkBtn.disabled = false;
            }
        }
        if (state.status === "COMPLETED") {
            confirmBulkBtn.disabled = true;
            confirmBulkBtn.textContent = "Completed";
            newPreviewBtn.disabled = false;
        }
        if (state.status === "FAILED") {
            confirmBulkBtn.disabled = true;
            newPreviewBtn.disabled = false;
        }
    }

    function showPermissionState() {
        if (!canCreate && bulkNotice) {
            setNotice(bulkNotice, "Bulk leads require crm_create permission.", "error");
        }
        if (!canAssign && distributionEqual) {
            distributionEqual.disabled = true;
        }
    }

    function renderCurrentPage() {
        syncPaginationButtons();
        renderMembers(state.members);
        updateSelectionSummary();
        updateDistributionEstimate();
    }

    showPermissionState();
    wireFilterChangeHandlers();
    wireSelectionHandlers();
    wireDistributionHandlers();
    wirePaginationHandlers();
    wireActionHandlers();
    syncDistributionRadiosFromState();

    if (canAssign) {
        loadAssignableUsers();
    } else {
        updateEmployeesPanelVisibility();
        setClassVisibility(employeePanel, false);
        setClassVisibility(employeeLoading, false);
    }

    applyInitialState();
    loadMembers(1).then(() => {
        renderCurrentPage();
    });

    updateConfirmState();
    updateOperationBadge();
    updateSelectionSummary();
    updateDistributionEstimate();
});
