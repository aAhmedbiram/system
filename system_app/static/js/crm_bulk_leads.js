document.addEventListener("DOMContentLoaded", () => {
    const SOURCE_EXISTING_MEMBER = "EXISTING_MEMBER";
    const SOURCE_INVITATIONS = "INVITATIONS";
    const canCreate = String(window.CRM_BULK_CAN_CREATE) === "true";
    const canAssign = String(window.CRM_BULK_CAN_ASSIGN) === "true";
    const initialState = window.CRM_BULK_INITIAL_STATE || null;
    const perPage = Number(window.CRM_BULK_PAGE_SIZE || 50);

    const bulkNotice = document.getElementById("bulkNotice");
    const selectionInfo = document.getElementById("selectionInfo");
    const selectionSectionTitle = document.getElementById("selectionSectionTitle");
    const selectionSectionNote = document.getElementById("selectionSectionNote");
    const selectedCount = document.getElementById("selectedCount");
    const matchingCount = document.getElementById("matchingCount");
    const selectionModeLabel = document.getElementById("selectionModeLabel");
    const bulkSourceMembersBtn = document.getElementById("bulkSourceMembersBtn");
    const bulkSourceInvitationsBtn = document.getElementById("bulkSourceInvitationsBtn");

    const bulkSearchId = document.getElementById("bulkSearchId");
    const bulkSearchName = document.getElementById("bulkSearchName");
    const bulkSearchPhone = document.getElementById("bulkSearchPhone");
    const bulkViewFilter = document.getElementById("bulkViewFilter");
    const bulkExpiresWithin = document.getElementById("bulkExpiresWithin");
    const bulkExpiresMonth = document.getElementById("bulkExpiresMonth");
    const bulkExpiresYear = document.getElementById("bulkExpiresYear");
    const bulkReloadMembersBtn = document.getElementById("bulkReloadMembersBtn");
    const selectVisibleBtn = document.getElementById("selectVisibleBtn");
    const clearVisibleBtn = document.getElementById("clearVisibleBtn");
    const selectFilteredBtn = document.getElementById("selectFilteredBtn");
    const clearAllBtn = document.getElementById("clearAllBtn");
    const previewDistributionBtn = document.getElementById("previewDistributionBtn");
    const memberFiltersPanel = document.getElementById("memberFiltersPanel");
    const invitationFiltersPanel = document.getElementById("invitationFiltersPanel");
    const bulkInvitationSearchName = document.getElementById("bulkInvitationSearchName");
    const bulkInvitationSearchPhone = document.getElementById("bulkInvitationSearchPhone");
    const bulkInvitationUsedBy = document.getElementById("bulkInvitationUsedBy");
    const bulkInvitationMonth = document.getElementById("bulkInvitationMonth");
    const bulkInvitationYear = document.getElementById("bulkInvitationYear");

    const membersLoading = document.getElementById("membersLoading");
    const membersError = document.getElementById("membersError");
    const bulkMembersTable = document.getElementById("bulkMembersTable");
    const bulkMembersTableHead = document.getElementById("bulkMembersTableHead");
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
        source: SOURCE_EXISTING_MEMBER,
        sourceState: {
            [SOURCE_EXISTING_MEMBER]: {
                page: 1,
                totalPages: 1,
                totalCount: 0,
                members: [],
                selectedIds: new Set(),
                allFilteredSelected: false,
                selectionMode: "ids",
                loadingMembers: false
            },
            [SOURCE_INVITATIONS]: {
                page: 1,
                totalPages: 1,
                totalCount: 0,
                members: [],
                selectedIds: new Set(),
                allFilteredSelected: false,
                selectionMode: "ids",
                loadingMembers: false
            }
        },
        page: 1,
        totalPages: 1,
        totalCount: 0,
        members: [],
        filters: {
            view: "all",
            expires_within: "",
            expires_month: "",
            expires_year: "",
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

    function activeSourceState() {
        return state.sourceState[state.source] || state.sourceState[SOURCE_EXISTING_MEMBER];
    }

    Object.defineProperties(state, {
        page: {
            get() { return activeSourceState().page; },
            set(value) { activeSourceState().page = Number(value) || 1; }
        },
        totalPages: {
            get() { return activeSourceState().totalPages; },
            set(value) { activeSourceState().totalPages = Number(value) || 1; }
        },
        totalCount: {
            get() { return activeSourceState().totalCount; },
            set(value) { activeSourceState().totalCount = Number(value) || 0; }
        },
        members: {
            get() { return activeSourceState().members; },
            set(value) { activeSourceState().members = Array.isArray(value) ? value : []; }
        },
        selectedIds: {
            get() { return activeSourceState().selectedIds; },
            set(value) { activeSourceState().selectedIds = value instanceof Set ? value : new Set(value || []); }
        },
        allFilteredSelected: {
            get() { return activeSourceState().allFilteredSelected; },
            set(value) { activeSourceState().allFilteredSelected = Boolean(value); }
        },
        selectionMode: {
            get() { return activeSourceState().selectionMode; },
            set(value) { activeSourceState().selectionMode = value || "ids"; }
        },
        loadingMembers: {
            get() { return activeSourceState().loadingMembers; },
            set(value) { activeSourceState().loadingMembers = Boolean(value); }
        }
    });

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

    function currentSourceLabel() {
        return state.source === SOURCE_INVITATIONS ? "Invitation" : "Member";
    }

    function currentSourceLabelPlural() {
        return state.source === SOURCE_INVITATIONS ? "Invitations" : "Members";
    }

    function currentSourceInputBundle() {
        if (state.source === SOURCE_INVITATIONS) {
            return {
                searchName: bulkInvitationSearchName,
                searchPhone: bulkInvitationSearchPhone,
                usedBy: bulkInvitationUsedBy,
                month: bulkInvitationMonth,
                year: bulkInvitationYear
            };
        }
        return {
            searchId: bulkSearchId,
            searchName: bulkSearchName,
            searchPhone: bulkSearchPhone,
            view: bulkViewFilter,
            expiresWithin: bulkExpiresWithin,
            month: bulkExpiresMonth,
            year: bulkExpiresYear
        };
    }

    function sourceQueryPath() {
        return state.source === SOURCE_INVITATIONS ? "/crm/leads/bulk/invitations" : "/crm/leads/bulk/members";
    }

    function updateSourceSelector() {
        if (bulkSourceMembersBtn) {
            bulkSourceMembersBtn.classList.toggle("active", state.source === SOURCE_EXISTING_MEMBER);
        }
        if (bulkSourceInvitationsBtn) {
            bulkSourceInvitationsBtn.classList.toggle("active", state.source === SOURCE_INVITATIONS);
        }
        if (selectionSectionTitle) {
            selectionSectionTitle.textContent = state.source === SOURCE_INVITATIONS ? "Invitation Selection" : "Member Selection";
        }
        if (selectionSectionNote) {
            selectionSectionNote.textContent = state.source === SOURCE_INVITATIONS
                ? "Use filters or pick invitation candidates manually. Select-all-filtered uses the current filters and remains authoritative on preview."
                : "Use filters or pick members manually. Select-all-filtered uses the current filters and remains authoritative on preview.";
        }
        if (memberFiltersPanel) {
            setClassVisibility(memberFiltersPanel, state.source === SOURCE_EXISTING_MEMBER, "grid");
        }
        if (invitationFiltersPanel) {
            setClassVisibility(invitationFiltersPanel, state.source === SOURCE_INVITATIONS, "grid");
        }
        if (bulkReloadMembersBtn) {
            bulkReloadMembersBtn.textContent = state.source === SOURCE_INVITATIONS ? "Refresh Invitations" : "Refresh Members";
        }
    }

    function updateTableHeader() {
        if (!bulkMembersTableHead) return;
        clearNode(bulkMembersTableHead);
        const tr = document.createElement("tr");
        const headers = state.source === SOURCE_INVITATIONS
            ? ["Sel", "Friend Name", "Phone", "Email", "Inviter Name", "Used By", "Used Date"]
            : ["Sel", "Member ID", "Name", "Phone", "Package", "End Date", "Status", "CRM"];
        headers.forEach((header) => {
            const th = document.createElement("th");
            th.textContent = header;
            if (header === "Sel") {
                th.style.width = "54px";
            }
            tr.appendChild(th);
        });
        bulkMembersTableHead.appendChild(tr);
    }

    function updateBrowserSourceParam(nextSource, previewToken) {
        const url = new URL(window.location.href);
        url.searchParams.delete("preview_token");
        if (nextSource && nextSource !== SOURCE_EXISTING_MEMBER) {
            url.searchParams.set("source", nextSource);
        } else {
            url.searchParams.delete("source");
        }
        if (previewToken) {
            url.searchParams.set("preview_token", previewToken);
        }
        window.history.replaceState({}, "", url.toString());
    }

    function sourceFromLocation() {
        const params = new URLSearchParams(window.location.search);
        const raw = params.get("source");
        return raw === SOURCE_INVITATIONS ? SOURCE_INVITATIONS : SOURCE_EXISTING_MEMBER;
    }

    function applyFiltersToInputs(source, filters) {
        const sourceKey = source === SOURCE_INVITATIONS ? SOURCE_INVITATIONS : SOURCE_EXISTING_MEMBER;
        const payload = filters || {};
        if (sourceKey === SOURCE_INVITATIONS) {
            if (bulkInvitationSearchName) bulkInvitationSearchName.value = payload.search_name || "";
            if (bulkInvitationSearchPhone) bulkInvitationSearchPhone.value = payload.search_phone || "";
            if (bulkInvitationUsedBy) bulkInvitationUsedBy.value = payload.used_by || "";
            if (bulkInvitationMonth) bulkInvitationMonth.value = payload.invitation_month || "";
            if (bulkInvitationYear) bulkInvitationYear.value = payload.invitation_year || "";
            return;
        }
        if (bulkSearchId) bulkSearchId.value = payload.search_id || "";
        if (bulkSearchName) bulkSearchName.value = payload.search_name || "";
        if (bulkSearchPhone) bulkSearchPhone.value = payload.search_phone || "";
        if (bulkViewFilter) bulkViewFilter.value = payload.view || "all";
        if (bulkExpiresWithin) bulkExpiresWithin.value = payload.expires_within || "";
        if (bulkExpiresMonth) bulkExpiresMonth.value = payload.expires_month || "";
        if (bulkExpiresYear) bulkExpiresYear.value = payload.expires_year || "";
    }

    function normalizeSourceState(source) {
        const normalized = source === SOURCE_INVITATIONS ? SOURCE_INVITATIONS : SOURCE_EXISTING_MEMBER;
        return state.sourceState[normalized] || state.sourceState[SOURCE_EXISTING_MEMBER];
    }

    function setActiveSource(source, options = {}) {
        const normalized = source === SOURCE_INVITATIONS ? SOURCE_INVITATIONS : SOURCE_EXISTING_MEMBER;
        state.source = normalized;
        updateSourceSelector();
        updateTableHeader();
        syncPaginationButtons();
        if (!options.keepPreview) {
            resetPreviewState();
            clearExecutionFeedback();
        }
        updateSelectionSummary();
        updateDistributionEstimate();
        if (!state.previewToken && previewSource) {
            previewSource.textContent = state.source;
        }
        if (options.updateUrl !== false) {
            updateBrowserSourceParam(normalized, options.previewToken || "");
        }
    }

    function activeSelectionPayload() {
        if (state.source === SOURCE_INVITATIONS) {
            return Array.from(state.selectedIds)
                .map((value) => String(value).trim())
                .filter(Boolean)
                .sort((a, b) => a.localeCompare(b));
        }
        return Array.from(state.selectedIds)
            .map((value) => Number(value))
            .filter((value) => !Number.isNaN(value))
            .sort((a, b) => a - b);
    }

    function sortedSelectedEmployeeIds() {
        return Array.from(state.selectedEmployeeIds).sort((a, b) => a - b);
    }

    function currentFilters() {
        if (state.source === SOURCE_INVITATIONS) {
            return {
                search_name: bulkInvitationSearchName ? bulkInvitationSearchName.value.trim() : "",
                search_phone: bulkInvitationSearchPhone ? bulkInvitationSearchPhone.value.trim() : "",
                used_by: bulkInvitationUsedBy ? bulkInvitationUsedBy.value.trim() : "",
                invitation_month: bulkInvitationMonth ? bulkInvitationMonth.value || "" : "",
                invitation_year: bulkInvitationYear ? bulkInvitationYear.value || "" : ""
            };
        }
        return {
            view: bulkViewFilter ? bulkViewFilter.value || "all" : "all",
            expires_within: bulkExpiresWithin ? bulkExpiresWithin.value || "" : "",
            expires_month: bulkExpiresMonth ? bulkExpiresMonth.value || "" : "",
            expires_year: bulkExpiresYear ? bulkExpiresYear.value || "" : "",
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
        return state.source === SOURCE_INVITATIONS ? "Explicit Keys" : "Explicit IDs";
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
            setNotice(selectionInfo, `All ${state.totalCount || 0} ${currentSourceLabelPlural().toLowerCase()} matching the current filters are selected.`, "success");
            return;
        }

        if (state.selectedIds.size > 0) {
            const selectedLabel = state.source === SOURCE_INVITATIONS ? "candidate(s)" : "member(s)";
            setNotice(selectionInfo, `${state.selectedIds.size} ${selectedLabel} selected across pages.`, "success");
            return;
        }

        setNotice(selectionInfo, `No ${currentSourceLabelPlural().toLowerCase()} selected yet.`, "warning");
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
            bulkExpiresMonth,
            bulkExpiresYear,
            bulkInvitationSearchName,
            bulkInvitationSearchPhone,
            bulkInvitationUsedBy,
            bulkInvitationMonth,
            bulkInvitationYear,
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
        if (snapshot.source) {
            state.source = snapshot.source === SOURCE_INVITATIONS ? SOURCE_INVITATIONS : SOURCE_EXISTING_MEMBER;
        }
        state.distributionMode = (snapshot.distribution || {}).mode || "unassigned";

        if (snapshot.selection && snapshot.selection.mode === "ids") {
            state.selectionMode = "ids";
            if (state.source === SOURCE_INVITATIONS) {
                state.selectedIds = new Set((snapshot.selection.selected_candidate_keys || snapshot.selection.candidate_keys || snapshot.selection.selected_member_ids || []).map((value) => String(value)));
            } else {
                state.selectedIds = new Set((snapshot.selection.selected_member_ids || []).map((value) => String(value)));
            }
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
        if (snapshot.selection && snapshot.selection.filters) {
            applyFiltersToInputs(state.source, snapshot.selection.filters);
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

        updateSourceSelector();
        updateTableHeader();
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
        intro.textContent = `Estimated split for ${selected} selected ${currentSourceLabelPlural().toLowerCase()}:`;
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
        if (membersLoading) {
            membersLoading.textContent = isLoading
                ? `Loading ${currentSourceLabelPlural().toLowerCase()}...`
                : `No ${currentSourceLabelPlural().toLowerCase()} loaded yet.`;
        }
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
        if (state.source === SOURCE_INVITATIONS) {
            items.forEach((candidate) => {
                const tr = document.createElement("tr");
                const checkboxCell = document.createElement("td");
                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.value = String(candidate.candidate_key || "");
                checkbox.checked = state.allFilteredSelected || state.selectedIds.has(String(candidate.candidate_key || ""));
                checkbox.disabled = state.locked || state.allFilteredSelected;
                checkbox.addEventListener("change", () => {
                    const key = String(candidate.candidate_key || "");
                    if (checkbox.checked) {
                        state.selectedIds.add(key);
                    } else {
                        state.selectedIds.delete(key);
                    }
                    state.selectionMode = "ids";
                    state.allFilteredSelected = false;
                    updateSelectionSummary();
                    updateDistributionEstimate();
                });
                checkboxCell.appendChild(checkbox);
                tr.appendChild(checkboxCell);

                [
                    candidate.name || "",
                    candidate.phone || "",
                    candidate.email || "",
                    candidate.inviter_name || "",
                    candidate.used_by || "",
                    candidate.used_date || ""
                ].forEach((value) => {
                    const td = document.createElement("td");
                    td.textContent = value;
                    tr.appendChild(td);
                });

                tr.dataset.candidateKey = String(candidate.candidate_key || "");
                bulkMembersTableBody.appendChild(tr);
            });
            setClassVisibility(bulkMembersTable, true, "table");
            return;
        }
        items.forEach((member) => {
            const tr = document.createElement("tr");
            const hasActiveLead = Boolean(member.has_active_crm_lead);
            const checkboxCell = document.createElement("td");
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = String(member.id);
            checkbox.checked = state.allFilteredSelected || state.selectedIds.has(String(member.id));
            checkbox.disabled = state.locked || hasActiveLead || state.allFilteredSelected;
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) {
                    state.selectedIds.add(String(member.id));
                } else {
                    state.selectedIds.delete(String(member.id));
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
            const response = await apiFetch(`${sourceQueryPath()}?${buildMembersQuery(state.page)}`, { method: "GET" });
            const data = await response.json();
            if (!response.ok) {
                throw new Error((data && data.message) ? data.message : `Failed to load ${currentSourceLabelPlural().toLowerCase()}.`);
            }
            state.members = data.items || [];
            state.totalCount = Number(data.total_count ?? data.total ?? 0);
            state.totalPages = Number(data.total_pages ?? data.pages ?? 1);
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
                membersError.textContent = error && error.message ? error.message : `Failed to load ${currentSourceLabelPlural().toLowerCase()}.`;
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
        if (previewSource) previewSource.textContent = state.source || SOURCE_EXISTING_MEMBER;
        if (previewSelected) previewSelected.textContent = "0";
        if (previewEligible) previewEligible.textContent = "0";
        if (previewSkipped) previewSkipped.textContent = "0";
        if (previewMissing) previewMissing.textContent = "0";
        if (previewPlanCount) previewPlanCount.textContent = "0";
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
        let selection = null;
        if (state.allFilteredSelected) {
            selection = { mode: "filters", filters: normalizeFilterPayload(filters) };
        } else if (state.source === SOURCE_INVITATIONS) {
            selection = { mode: "ids", candidate_keys: activeSelectionPayload() };
        } else {
            selection = { mode: "ids", member_ids: activeSelectionPayload() };
        }
        const distribution = state.distributionMode === "equal"
            ? { mode: "equal", user_ids: sortedSelectedEmployeeIds() }
            : { mode: "unassigned" };
        return {
            selection,
            distribution,
            source: state.source
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
            setExecutionFeedback(`Select at least one ${currentSourceLabel().toLowerCase()} before previewing.`, "error");
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
            const nextUrl = `/crm/leads/bulk?preview_token=${encodeURIComponent(data.preview_token)}${state.source === SOURCE_INVITATIONS ? `&source=${encodeURIComponent(state.source)}` : ""}`;
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
        [bulkViewFilter, bulkExpiresWithin, bulkExpiresMonth, bulkExpiresYear].forEach((input) => {
            if (input) {
                input.addEventListener("change", handler);
            }
        });
        [bulkInvitationSearchName, bulkInvitationSearchPhone, bulkInvitationUsedBy].forEach((input) => {
            if (input) {
                input.addEventListener("input", debouncedHandler);
            }
        });
        [bulkInvitationMonth, bulkInvitationYear].forEach((input) => {
            if (input) {
                input.addEventListener("change", handler);
            }
        });
    }

    function populateYearOptions(selectEl) {
        if (!selectEl) return;
        const currentYear = new Date().getFullYear();
        const startYear = currentYear - 3;
        const endYear = currentYear + 5;
        const existingValue = selectEl.value;
        selectEl.replaceChildren();

        const anyOption = document.createElement("option");
        anyOption.value = "";
        anyOption.textContent = "Any";
        selectEl.appendChild(anyOption);

        for (let year = startYear; year <= endYear; year += 1) {
            const option = document.createElement("option");
            option.value = String(year);
            option.textContent = String(year);
            selectEl.appendChild(option);
        }

        if (existingValue) {
            selectEl.value = existingValue;
        }
    }

    function populateExpiryYearOptions() {
        populateYearOptions(bulkExpiresYear);
        populateYearOptions(bulkInvitationYear);
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
                    if (state.source === SOURCE_INVITATIONS) {
                        if (member.candidate_key) {
                            state.selectedIds.add(String(member.candidate_key));
                        }
                    } else if (!member.has_active_crm_lead) {
                        state.selectedIds.add(String(member.id));
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
                    if (state.source === SOURCE_INVITATIONS) {
                        state.selectedIds.delete(String(member.candidate_key || ""));
                    } else {
                        state.selectedIds.delete(String(member.id));
                    }
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

    function wireSourceHandlers() {
        if (bulkSourceMembersBtn) {
            bulkSourceMembersBtn.addEventListener("click", () => {
                if (state.source === SOURCE_EXISTING_MEMBER) return;
                setActiveSource(SOURCE_EXISTING_MEMBER, { keepPreview: false, updateUrl: true });
                loadMembers(1).then(() => {
                    renderCurrentPage();
                });
            });
        }
        if (bulkSourceInvitationsBtn) {
            bulkSourceInvitationsBtn.addEventListener("click", () => {
                if (state.source === SOURCE_INVITATIONS) return;
                setActiveSource(SOURCE_INVITATIONS, { keepPreview: false, updateUrl: true });
                loadMembers(1).then(() => {
                    renderCurrentPage();
                });
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
                const nextUrl = new URL("/crm/leads/bulk", window.location.origin);
                if (state.source === SOURCE_INVITATIONS) {
                    nextUrl.searchParams.set("source", SOURCE_INVITATIONS);
                }
                window.location.href = nextUrl.toString();
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
        const urlSource = sourceFromLocation();
        if (initialState && initialState.preview_token) {
            state.previewToken = initialState.preview_token || "";
            state.status = initialState.status || null;
            state.previewState = initialState;
            state.previewExecution = initialState.execution || null;
            if (previewTokenDebug) {
                previewTokenDebug.textContent = state.previewToken;
            }

            const snapshot = initialState.snapshot || {};
            state.source = snapshot.source === SOURCE_INVITATIONS ? SOURCE_INVITATIONS : SOURCE_EXISTING_MEMBER;
            setActiveSource(state.source, { keepPreview: true, updateUrl: false });
            state.distributionMode = (snapshot.distribution || {}).mode || "unassigned";
            if (snapshot.selection && snapshot.selection.mode === "ids") {
                state.selectionMode = "ids";
                if (state.source === SOURCE_INVITATIONS) {
                    state.selectedIds = new Set((snapshot.selection.selected_candidate_keys || snapshot.selection.candidate_keys || []).map((value) => String(value)));
                } else {
                    state.selectedIds = new Set((snapshot.selection.selected_member_ids || []).map((value) => String(value)));
                }
                state.allFilteredSelected = false;
            } else if (snapshot.selection && snapshot.selection.mode === "filters") {
                state.selectionMode = "filters";
                state.allFilteredSelected = true;
                state.selectedIds = new Set();
            }
            if (snapshot.distribution && snapshot.distribution.mode === "equal") {
                state.selectedEmployeeIds = new Set(snapshot.distribution.user_ids || []);
            }
            if (snapshot.selection && snapshot.selection.filters) {
                applyFiltersToInputs(state.source, snapshot.selection.filters);
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
                confirmBulkBtn.disabled = Boolean(requiresAssign);
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
            updateSourceSelector();
            updateTableHeader();
            return;
        }

        state.source = urlSource;
        setActiveSource(state.source, { keepPreview: true, updateUrl: false });
        updateOperationBadge();
        updateSelectionSummary();
        updateConfirmState();
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
        updateSourceSelector();
        updateTableHeader();
        syncPaginationButtons();
        renderMembers(state.members);
        updateSelectionSummary();
        updateDistributionEstimate();
    }

    showPermissionState();
    populateExpiryYearOptions();
    wireFilterChangeHandlers();
    wireSelectionHandlers();
    wireSourceHandlers();
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
