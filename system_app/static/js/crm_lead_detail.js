document.addEventListener("DOMContentLoaded", () => {
    const leadId = window.CRM_LEAD_ID;
    if (!leadId) {
        showError("Invalid lead identifier");
        return;
    }

    const loader = document.getElementById("loadingDetails");
    const errorState = document.getElementById("errorDetails");
    const container = document.getElementById("detailsContainer");

    // Modal elements
    const openEditModalBtn = document.getElementById("openEditModalBtn");
    const editModal = document.getElementById("editLeadModal");
    const closeEditModalSpan = document.getElementById("closeEditModal");
    const cancelEditBtn = document.getElementById("cancelEditLead");
    const editForm = document.getElementById("editLeadForm");
    const editMemberWarning = document.getElementById("editMemberWarning");
    const openConvertWorkspaceBtn = document.getElementById("openConvertWorkspaceBtn");

    const editFeedback = document.getElementById("editLeadFeedback");
    const submitEditBtn = document.getElementById("submitEditLeadBtn");

    let currentLead = null;

    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    function showError(message) {
        loader.style.display = "none";
        container.style.display = "none";
        errorState.textContent = message || "Failed to load lead details.";
        errorState.style.display = "block";
    }

    function renderLead(lead) {
        // Header Elements
        document.getElementById("leadName").textContent = lead.name || "—";
        document.getElementById("leadIdDisplay").textContent = lead.id;

        // badges
        const typeBadge = document.getElementById("typeBadge");
        if (lead.member_id) {
            typeBadge.className = "badge member";
            typeBadge.textContent = "Member";
        } else {
            typeBadge.className = "badge prospect";
            typeBadge.textContent = "Prospect";
        }

        const stageBadge = document.getElementById("stageBadge");
        stageBadge.className = "badge stage";
        if (lead.stage === "WON") {
            stageBadge.className = "badge stage-won";
        } else if (lead.stage === "LOST") {
            stageBadge.className = "badge stage-lost";
        }
        stageBadge.textContent = formatStageLabel(lead.stage);

        if (lead.is_archived) {
            document.getElementById("archivedBadge").style.display = "inline-block";
        } else {
            document.getElementById("archivedBadge").style.display = "none";
        }

        // Contact Info
        document.getElementById("leadPhone").textContent = lead.phone || "—";
        document.getElementById("leadEmail").textContent = lead.email || "—";

        // CRM Info
        document.getElementById("leadSource").textContent = lead.source || "—";
        document.getElementById("leadAssignee").textContent = lead.assigned_username || "Unassigned";
        renderFollowUpVal(lead.next_follow_up_at);
        document.getElementById("leadCreated").textContent = formatDatetime(lead.created_at);
        document.getElementById("leadNotes").textContent = lead.notes || "—";

        // Member summary details (conditional cards)
        if (lead.member_id && lead.member) {
            document.getElementById("memberId").textContent = lead.member.id || "—";
            document.getElementById("memberName").textContent = lead.member.name || "—";
            document.getElementById("memberStatus").textContent = lead.member.membership_status || "—";
            document.getElementById("memberEndDate").textContent = lead.member.end_date || "—";
            document.getElementById("memberSummaryCard").style.display = "block";
        } else {
            document.getElementById("memberSummaryCard").style.display = "none";
        }

        if (openConvertWorkspaceBtn) {
            const canConvert = !!window.CRM_USER_CAN_CONVERT && !lead.is_archived && lead.stage !== "WON" && lead.stage !== "LOST";
            if (canConvert) {
                openConvertWorkspaceBtn.style.display = "inline-block";
                openConvertWorkspaceBtn.href = `/crm/leads/${lead.id}/convert/view`;
                openConvertWorkspaceBtn.textContent = lead.member_id ? "🔁 Reactivate" : "🔁 Convert";
            } else {
                openConvertWorkspaceBtn.style.display = "none";
                openConvertWorkspaceBtn.href = "#";
            }
        }
    }

    function loadLead() {
        return fetch(`/crm/leads/${leadId}`)
            .then(res => {
                if (res.status === 404) {
                    showError("Lead not found");
                    throw new Error("404");
                }
                if (res.status === 403) {
                    showError("Access denied");
                    throw new Error("403");
                }
                if (!res.ok) {
                    showError("Server error occurred (" + res.status + ")");
                    throw new Error("Status " + res.status);
                }
                return res.json();
            })
            .then(lead => {
                loader.style.display = "none";
                currentLead = lead;
                renderLead(lead);
                container.style.display = "block";
                // Notify composer that lead data is available
                document.dispatchEvent(new CustomEvent("crm:leadLoaded", { detail: lead }));
            })
            .catch(err => {
                console.error("Error fetching lead parameters:", err);
            });
    }

    // Expose for composer cross-module reload
    window.reloadLead = loadLead;

    // Initial load
    loadLead();

    // Modal controls
    if (openEditModalBtn) {
        openEditModalBtn.addEventListener("click", () => {
            if (!currentLead) return;
            clearEditFeedback();
            enableSaveBtn();

            // Populate form values
            document.getElementById("editName").value = currentLead.name || "";
            document.getElementById("editPhone").value = currentLead.phone || "";
            document.getElementById("editEmail").value = currentLead.email || "";
            document.getElementById("editSource").value = currentLead.source || "";
            document.getElementById("editNotes").value = currentLead.notes || "";

            // Show warning if linked member
            if (currentLead.member_id) {
                editMemberWarning.style.display = "block";
            } else {
                editMemberWarning.style.display = "none";
            }

            editModal.style.display = "block";
        });
    }

    const closeActions = [closeEditModalSpan, cancelEditBtn];
    closeActions.forEach(el => {
        if (el) {
            el.addEventListener("click", () => {
                editModal.style.display = "none";
            });
        }
    });

    window.addEventListener("click", (e) => {
        if (e.target === editModal) {
            editModal.style.display = "none";
        }
    });

    // Feedback helpers
    function showEditFeedback(text) {
        editFeedback.textContent = text;
        editFeedback.style.display = "block";
    }

    function clearEditFeedback() {
        editFeedback.textContent = "";
        editFeedback.style.display = "none";
    }

    function disableSaveBtn() {
        submitEditBtn.disabled = true;
        submitEditBtn.textContent = "Saving...";
        submitEditBtn.style.opacity = "0.6";
        submitEditBtn.style.cursor = "not-allowed";
    }

    function enableSaveBtn() {
        submitEditBtn.disabled = false;
        submitEditBtn.textContent = "Save Changes";
        submitEditBtn.style.opacity = "1";
        submitEditBtn.style.cursor = "pointer";
    }

    // Submit PATCH handler
    if (editForm) {
        editForm.addEventListener("submit", (e) => {
            e.preventDefault();
            clearEditFeedback();

            const name = document.getElementById("editName").value.trim();
            const phone = document.getElementById("editPhone").value.trim();
            const email = document.getElementById("editEmail").value.trim();
            const source = document.getElementById("editSource").value.trim();
            const notes = document.getElementById("editNotes").value.trim();

            // Client-side validations
            if (!name) {
                showEditFeedback("Name is required");
                return;
            }
            if (!phone) {
                showEditFeedback("Phone number is required");
                return;
            }
            if (!source) {
                showEditFeedback("Source is required");
                return;
            }

            disableSaveBtn();

            apiFetch(`/crm/leads/${leadId}`, {
                method: "PATCH",
                body: JSON.stringify({ name, phone, email, source, notes })
            })
            .then(res => {
                if (res.ok) {
                    return res.json().then(() => {
                        editModal.style.display = "none";
                        loadLead(); // Refresh UI authoritatively
                    });
                }

                return res.json().then(errorData => {
                    enableSaveBtn();
                    if (res.status === 400) {
                        showEditFeedback("Validation failed: " + (errorData.message || "Invalid inputs"));
                    } else if (res.status === 403) {
                        showEditFeedback("Access denied: " + (errorData.message || "Insufficient permissions"));
                    } else if (res.status === 404) {
                        showEditFeedback("Lead no longer exists.");
                    } else {
                        showEditFeedback("Error " + res.status + ": " + (errorData.message || "Failed to update lead"));
                    }
                });
            })
            .catch(err => {
                console.error("Failed to update lead:", err);
                enableSaveBtn();
                showEditFeedback("Network or connection error. Please try again.");
            });
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

    // ---- Follow-up Cairo-aware urgency display ----
    // Computes today_start / today_end in Africa/Cairo using Cairo calendar parts.
    function getCairoDayBoundaries() {
        const now = new Date();
        const parts = new Intl.DateTimeFormat("en-CA", {
            timeZone: "Africa/Cairo",
            year: "numeric",
            month: "2-digit",
            day: "2-digit"
        }).formatToParts(now);
        const partMap = {};
        parts.forEach(function (part) {
            partMap[part.type] = part.value;
        });
        const cairoDateStr = partMap.year + "-" + partMap.month + "-" + partMap.day;
        const todayStart = new Date(cairoDateStr + "T00:00:00+03:00");
        const todayEnd = new Date(todayStart.getTime() + 24 * 60 * 60 * 1000);
        return { todayStart, todayEnd };
    }

    function renderFollowUpVal(dtString) {
        const container = document.getElementById("leadFollowUp");
        container.innerHTML = "";
        container.className = "info-val";

        if (!dtString) {
            container.textContent = "No follow-up scheduled";
            return;
        }

        const dt = new Date(dtString);
        if (isNaN(dt.getTime())) {
            container.textContent = dtString;
            return;
        }

        const { todayStart, todayEnd } = getCairoDayBoundaries();

        // Format the time in Cairo
        const formatted = new Intl.DateTimeFormat("en-GB", {
            timeZone: "Africa/Cairo",
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false
        }).format(dt);

        // Determine urgency
        let urgencyClass = null;
        let urgencyLabel = null;
        if (dt < todayStart) {
            urgencyClass = "overdue";
            urgencyLabel = "Overdue";
        } else if (dt >= todayStart && dt < todayEnd) {
            urgencyClass = "today";
            urgencyLabel = "Today";
        } else {
            urgencyClass = "upcoming";
            urgencyLabel = "Upcoming";
        }

        // Wrap in flex container
        container.className = "info-val followup-val-wrap";

        const timeSpan = document.createElement("span");
        timeSpan.textContent = formatted;
        container.appendChild(timeSpan);

        const badge = document.createElement("span");
        badge.className = "followup-urgency " + urgencyClass;
        badge.textContent = urgencyLabel;
        container.appendChild(badge);
    }
});

// ============================================================
// Activity Composer — independent module, own closure
// Requires: window.CRM_LEAD_ID, window.CRM_USER_CAN_EDIT
// Relies on the timeline module exposing window.reloadTimeline
// ============================================================
(function () {
    "use strict";

    // Wait for DOM
    document.addEventListener("DOMContentLoaded", function () {

        if (!window.CRM_USER_CAN_EDIT) return; // Non-editor: no composer in DOM

        const leadId       = window.CRM_LEAD_ID;
        const submitBtn    = document.getElementById("submitActivityBtn");
        const clearBtn     = document.getElementById("clearFollowUpBtn");
        const typeSelect   = document.getElementById("composerType");
        const noteTA       = document.getElementById("composerNote");
        const resultTA     = document.getElementById("composerResult");
        const followUpIn   = document.getElementById("composerFollowUp");
        const feedbackEl   = document.getElementById("composerFeedback");

        if (!submitBtn || !leadId) return;

        // ---- Double-submit guard ----
        let isSubmitting = false;

        // ---- Follow-up intent state ----
        // null  = omit (keep current)
        // false = explicit clear (send null)
        // dt    = ISO string (set)
        let followUpIntent = null; // null means omit
        let clearIntentActive = false;

        // ---- Cairo timezone constant ----
        // Africa/Cairo is UTC+3 year-round (no DST)
        const CAIRO_OFFSET_HOURS = 3;

        // ---- Convert datetime-local value to Cairo-aware ISO 8601 string ----
        // datetime-local gives "YYYY-MM-DDTHH:MM" without timezone.
        // We treat it as Cairo local time and append +03:00.
        function toCaroISO(localStr) {
            if (!localStr) return null;
            // Ensure seconds are present
            const withSeconds = localStr.length === 16 ? localStr + ":00" : localStr;
            return withSeconds + "+03:00";
        }

        // ---- Feedback helpers ----
        function showFeedback(message, type) {
            feedbackEl.textContent = "";
            feedbackEl.className = "composer-feedback " + type;
            feedbackEl.textContent = message;
            feedbackEl.style.display = "block";
        }

        function clearFeedback() {
            feedbackEl.style.display = "none";
            feedbackEl.textContent = "";
            feedbackEl.className = "composer-feedback";
        }

        // ---- Button state helpers ----
        function disableSubmit() {
            submitBtn.disabled = true;
            submitBtn.textContent = "Saving...";
        }

        function enableSubmit() {
            submitBtn.disabled = false;
            submitBtn.textContent = "Log Activity";
        }

        // ---- Reset form after success ----
        function resetComposer() {
            if (typeSelect) typeSelect.value = "CALL";
            if (noteTA)   noteTA.value = "";
            if (resultTA) resultTA.value = "";
            if (followUpIn) followUpIn.value = "";
            clearIntentActive = false;
            followUpIntent = null;
            if (clearBtn) clearBtn.style.display = "none";
            clearFeedback();
        }

        // ---- Clear Follow-Up button ----
        // Shown only when the current lead has a scheduled follow-up
        // It is wired to send explicit null
        if (clearBtn) {
            clearBtn.addEventListener("click", function () {
                clearIntentActive = true;
                if (followUpIn) followUpIn.value = ""; // Clear the datetime input too
                clearBtn.style.display = "none";
                showFeedback("Follow-up will be cleared when you log the next activity.", "success");
            });
        }

        // ---- After lead loads, show Clear button if follow-up exists ----
        // We poll window.currentLeadData set by the profile module
        // Instead, listen for a custom event dispatched by loadLead
        document.addEventListener("crm:leadLoaded", function (e) {
            const lead = e.detail;
            if (clearBtn) {
                if (lead && lead.next_follow_up_at) {
                    clearBtn.style.display = "inline-block";
                } else {
                    clearBtn.style.display = "none";
                }
            }
        });

        // ---- Submit activity ----
        submitBtn.addEventListener("click", function () {
            if (isSubmitting) return; // Double-submit guard

            clearFeedback();

            const actType = typeSelect ? typeSelect.value : "";
            const note    = noteTA    ? noteTA.value.trim()    : "";
            const result  = resultTA  ? resultTA.value.trim()  : "";
            const fuRaw   = followUpIn ? followUpIn.value      : "";

            // Build payload
            const payload = { activity_type: actType };
            if (note)   payload.note   = note;
            if (result) payload.result = result;

            // Follow-up semantics:
            if (clearIntentActive) {
                // Explicit clear — send null key
                payload.next_follow_up_at = null;
            } else if (fuRaw) {
                // User filled the datetime input — convert to Cairo-aware ISO
                payload.next_follow_up_at = toCaroISO(fuRaw);
            }
            // If neither: omit next_follow_up_at entirely (key not present = keep current)

            // Client-side guard for FOLLOW_UP type
            if (actType === "FOLLOW_UP" && !note && !payload.next_follow_up_at && !clearIntentActive) {
                showFeedback("Follow-Up activity requires either a note or a scheduled follow-up time.", "error");
                return;
            }

            isSubmitting = true;
            disableSubmit();

            apiFetch("/crm/leads/" + leadId + "/activities", {
                method: "POST",
                body: JSON.stringify(payload)
            })
            .then(function (res) {
                return res.json().then(function (data) {
                    return { status: res.status, data: data };
                });
            })
            .then(function (r) {
                isSubmitting = false;
                enableSubmit();

                if (r.status === 201) {
                    resetComposer();
                    // Reload timeline from page 1 (authoritative) and refresh lead data
                    if (typeof window.reloadTimeline === "function") {
                        window.reloadTimeline();
                    }
                    if (typeof window.reloadLead === "function") {
                        window.reloadLead();
                    }
                    return;
                }

                // Error cases
                const msg = (r.data && r.data.message) ? r.data.message : "Failed to log activity.";
                if (r.status === 400) {
                    showFeedback("Validation error: " + msg, "error");
                } else if (r.status === 403) {
                    showFeedback("Access denied: " + msg, "error");
                } else if (r.status === 404) {
                    showFeedback("Lead not found.", "error");
                } else if (r.status === 409) {
                    showFeedback("Conflict: " + msg, "error");
                } else {
                    showFeedback("Error " + r.status + ": " + msg, "error");
                }
            })
            .catch(function (err) {
                isSubmitting = false;
                enableSubmit();
                showFeedback("Network error. Please try again.", "error");
                console.error("[Composer] POST activity failed:", err);
            });
        });

    }); // end DOMContentLoaded

}());

// ============================================================
// Operational Controls — stage management and assignment
// ============================================================
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const leadId = window.CRM_LEAD_ID;
        const canStage = !!window.CRM_USER_CAN_STAGE;
        const canAssign = !!window.CRM_USER_CAN_ASSIGN;

        const stagePanel = document.getElementById("stageControlPanel");
        const stageSelect = document.getElementById("stageSelect");
        const lostReasonWrap = document.getElementById("lostReasonWrap");
        const lostReasonSelect = document.getElementById("lostReasonSelect");
        const reopenStageWrap = document.getElementById("reopenStageWrap");
        const reopenStageSelect = document.getElementById("reopenStageSelect");
        const changeStageBtn = document.getElementById("changeStageBtn");
        const reopenLeadBtn = document.getElementById("reopenLeadBtn");
        const stageFeedback = document.getElementById("stageFeedback");

        const assignmentPanel = document.getElementById("assignmentControlPanel");
        const currentAssigneeDisplay = document.getElementById("currentAssigneeDisplay");
        const assignUserSelect = document.getElementById("assignUserSelect");
        const assignLeadBtn = document.getElementById("assignLeadBtn");
        const unassignLeadBtn = document.getElementById("unassignLeadBtn");
        const assignmentFeedback = document.getElementById("assignmentFeedback");

        let currentLead = null;
        let assignUsersLoaded = false;
        let stageBusy = false;
        let assignmentBusy = false;

        function apiFetch(url, options) {
            if (window.CRM && typeof window.CRM.apiFetch === "function") {
                return window.CRM.apiFetch(url, options);
            }
            return fetch(url, options);
        }

        function showFeedback(el, text, isError) {
            if (!el) return;
            el.textContent = text;
            el.className = "control-feedback " + (isError ? "error" : "success");
            el.style.display = "block";
        }

        function clearFeedback(el) {
            if (!el) return;
            el.textContent = "";
            el.className = "control-feedback";
            el.style.display = "none";
        }

        function syncStageUi(lead) {
            if (!stagePanel || !stageSelect) return;

            if (lead.stage === "WON") {
                stagePanel.style.display = "none";
                return;
            }

            stagePanel.style.display = "block";
            if (lead.stage === "LOST") {
                stageSelect.value = "FOLLOW_UP";
                if (lostReasonWrap) lostReasonWrap.style.display = "none";
                if (reopenStageWrap) reopenStageWrap.style.display = "block";
                if (changeStageBtn) changeStageBtn.style.display = "none";
                if (reopenLeadBtn) reopenLeadBtn.style.display = "inline-block";
                if (reopenStageSelect && !reopenStageSelect.value) {
                    reopenStageSelect.value = "FOLLOW_UP";
                }
                return;
            }

            stageSelect.value = lead.stage || "NEW";
            if (changeStageBtn) changeStageBtn.style.display = "inline-block";
            if (reopenLeadBtn) reopenLeadBtn.style.display = "none";
            if (reopenStageWrap) reopenStageWrap.style.display = "none";
            if (lostReasonWrap) {
                lostReasonWrap.style.display = stageSelect.value === "LOST" ? "block" : "none";
            }
        }

        function syncAssignmentUi(lead) {
            if (!assignmentPanel) return;

            if (currentAssigneeDisplay) {
                currentAssigneeDisplay.textContent = lead.assigned_username || "Unassigned";
            }

            if (assignLeadBtn) {
                assignLeadBtn.textContent = lead.assigned_user_id ? "Reassign" : "Assign";
            }

            if (unassignLeadBtn) {
                unassignLeadBtn.style.display = lead.assigned_user_id ? "inline-block" : "none";
            }

            if (assignUserSelect && lead.assigned_user_id) {
                assignUserSelect.value = String(lead.assigned_user_id);
            }
        }

        function populateAssignUsers(users) {
            if (!assignUserSelect) return;
            assignUserSelect.replaceChildren();
            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = "Select user";
            assignUserSelect.appendChild(placeholder);

            users.forEach(function (user) {
                const option = document.createElement("option");
                option.value = String(user.id);
                option.textContent = user.username + (user.is_approved ? "" : " (unapproved)");
                assignUserSelect.appendChild(option);
            });

            assignUsersLoaded = true;
            if (currentLead && currentLead.assigned_user_id) {
                assignUserSelect.value = String(currentLead.assigned_user_id);
            }
        }

        function ensureUsersLoaded() {
            if (!canAssign || !assignUserSelect || assignUsersLoaded) {
                return Promise.resolve();
            }
            assignUserSelect.disabled = true;
            assignUserSelect.replaceChildren();
            const loadingOption = document.createElement("option");
            loadingOption.value = "";
            loadingOption.textContent = "Loading users...";
            assignUserSelect.appendChild(loadingOption);
            return window.CRM.getAssignableUsers()
                .then(function (users) {
                    populateAssignUsers(users || []);
                })
                .catch(function () {
                    if (assignUserSelect) {
                        assignUserSelect.replaceChildren();
                        const failedOption = document.createElement("option");
                        failedOption.value = "";
                        failedOption.textContent = "Failed to load users";
                        assignUserSelect.appendChild(failedOption);
                    }
                })
                .finally(function () {
                    if (assignUserSelect) assignUserSelect.disabled = false;
                });
        }

        function refreshAfterMutation() {
            if (typeof window.reloadTimeline === "function") {
                window.reloadTimeline();
            }
            if (typeof window.reloadLead === "function") {
                window.reloadLead();
            }
        }

        function handleLeadLoaded(lead) {
            currentLead = lead;
            if (canStage) {
                syncStageUi(lead);
                clearFeedback(stageFeedback);
            }
            if (canAssign) {
                syncAssignmentUi(lead);
                clearFeedback(assignmentFeedback);
                ensureUsersLoaded().then(function () {
                    if (lead.assigned_user_id && assignUserSelect) {
                        assignUserSelect.value = String(lead.assigned_user_id);
                    }
                });
            }
        }

        if (canStage && stageSelect) {
            stageSelect.addEventListener("change", function () {
                if (stageSelect.value === "LOST") {
                    if (lostReasonWrap) lostReasonWrap.style.display = "block";
                } else {
                    if (lostReasonWrap) lostReasonWrap.style.display = "none";
                    if (lostReasonSelect) lostReasonSelect.value = "";
                }
            });
        }

        if (canStage && changeStageBtn) {
            changeStageBtn.addEventListener("click", function () {
                if (stageBusy || !currentLead) return;

                const targetStage = stageSelect ? stageSelect.value : "";
                const payload = { stage: targetStage };
                const lostReason = lostReasonSelect ? lostReasonSelect.value : "";

                if (!targetStage) {
                    showFeedback(stageFeedback, "Please choose a stage.", true);
                    return;
                }
                if (targetStage === "LOST" && !lostReason) {
                    showFeedback(stageFeedback, "Lost reason is required when marking a lead as LOST.", true);
                    return;
                }
                if (lostReason) {
                    payload.lost_reason = lostReason;
                }

                stageBusy = true;
                changeStageBtn.disabled = true;
                showFeedback(stageFeedback, "Saving stage...", false);

                apiFetch(`/crm/leads/${leadId}/stage`, {
                    method: "POST",
                    body: JSON.stringify(payload)
                })
                    .then(function (res) {
                        return res.json().then(function (data) {
                            return { status: res.status, data: data };
                        });
                    })
                    .then(function (r) {
                        if (r.status === 200) {
                            clearFeedback(stageFeedback);
                            refreshAfterMutation();
                            return;
                        }
                        showFeedback(stageFeedback, (r.data && r.data.message) ? r.data.message : "Failed to update stage.", true);
                    })
                    .catch(function () {
                        showFeedback(stageFeedback, "Network error while updating stage.", true);
                    })
                    .finally(function () {
                        stageBusy = false;
                        changeStageBtn.disabled = false;
                    });
            });
        }

        if (canStage && reopenLeadBtn) {
            reopenLeadBtn.addEventListener("click", function () {
                if (stageBusy || !currentLead) return;

                const reopenStage = reopenStageSelect ? reopenStageSelect.value : "FOLLOW_UP";
                stageBusy = true;
                reopenLeadBtn.disabled = true;
                showFeedback(stageFeedback, "Reopening lead...", false);

                apiFetch(`/crm/leads/${leadId}/reopen`, {
                    method: "POST",
                    body: JSON.stringify({ stage: reopenStage })
                })
                    .then(function (res) {
                        return res.json().then(function (data) {
                            return { status: res.status, data: data };
                        });
                    })
                    .then(function (r) {
                        if (r.status === 200) {
                            clearFeedback(stageFeedback);
                            refreshAfterMutation();
                            return;
                        }
                        showFeedback(stageFeedback, (r.data && r.data.message) ? r.data.message : "Failed to reopen lead.", true);
                    })
                    .catch(function () {
                        showFeedback(stageFeedback, "Network error while reopening lead.", true);
                    })
                    .finally(function () {
                        stageBusy = false;
                        reopenLeadBtn.disabled = false;
                    });
            });
        }

        if (canAssign && assignLeadBtn) {
            assignLeadBtn.addEventListener("click", function () {
                if (assignmentBusy || !currentLead) return;
                const userId = assignUserSelect ? assignUserSelect.value : "";
                if (!userId) {
                    showFeedback(assignmentFeedback, "Choose a target user first.", true);
                    return;
                }

                assignmentBusy = true;
                assignLeadBtn.disabled = true;
                if (unassignLeadBtn) unassignLeadBtn.disabled = true;
                showFeedback(assignmentFeedback, "Saving assignment...", false);

                apiFetch(`/crm/leads/${leadId}/assign`, {
                    method: "POST",
                    body: JSON.stringify({ user_id: Number(userId) })
                })
                    .then(function (res) {
                        return res.json().then(function (data) {
                            return { status: res.status, data: data };
                        });
                    })
                    .then(function (r) {
                        if (r.status === 200) {
                            clearFeedback(assignmentFeedback);
                            refreshAfterMutation();
                            return;
                        }
                        showFeedback(assignmentFeedback, (r.data && r.data.message) ? r.data.message : "Failed to save assignment.", true);
                    })
                    .catch(function () {
                        showFeedback(assignmentFeedback, "Network error while saving assignment.", true);
                    })
                    .finally(function () {
                        assignmentBusy = false;
                        assignLeadBtn.disabled = false;
                        if (unassignLeadBtn) unassignLeadBtn.disabled = false;
                    });
            });
        }

        if (canAssign && unassignLeadBtn) {
            unassignLeadBtn.addEventListener("click", function () {
                if (assignmentBusy || !currentLead) return;

                assignmentBusy = true;
                assignLeadBtn.disabled = true;
                unassignLeadBtn.disabled = true;
                showFeedback(assignmentFeedback, "Clearing assignment...", false);

                apiFetch(`/crm/leads/${leadId}/unassign`, {
                    method: "POST",
                    body: JSON.stringify({})
                })
                    .then(function (res) {
                        return res.json().then(function (data) {
                            return { status: res.status, data: data };
                        });
                    })
                    .then(function (r) {
                        if (r.status === 200) {
                            clearFeedback(assignmentFeedback);
                            refreshAfterMutation();
                            return;
                        }
                        showFeedback(assignmentFeedback, (r.data && r.data.message) ? r.data.message : "Failed to clear assignment.", true);
                    })
                    .catch(function () {
                        showFeedback(assignmentFeedback, "Network error while clearing assignment.", true);
                    })
                    .finally(function () {
                        assignmentBusy = false;
                        assignLeadBtn.disabled = false;
                        unassignLeadBtn.disabled = false;
                    });
            });
        }

        document.addEventListener("crm:leadLoaded", function (event) {
            handleLeadLoaded(event.detail || {});
        });

        if (currentLead) {
            handleLeadLoaded(currentLead);
        }
    });
}());

// ============================================================
// Activity Timeline — independent module, own closure
// Shares window.CRM_LEAD_ID set by the Jinja template.
// Does NOT share state with the lead profile module above.
// ============================================================
(function () {
    "use strict";

    // ---- Constants ----
    const PER_PAGE = 25;

    // ---- State ----
    let currentPage = 0;
    let totalPages = 1;
    let isLoadingActivities = false;
    let loadSequence = 0;

    // ---- DOM refs ----
    const activityLoading = document.getElementById("activityLoading");
    const activityError   = document.getElementById("activityError");
    const activityList    = document.getElementById("activityList");
    const activityLoadMore= document.getElementById("activityLoadMore");
    const loadMoreBtn     = document.getElementById("loadMoreActivitiesBtn");
    const countBadge      = document.getElementById("activityCountBadge");

    // ---- Utility: Cairo-aware timestamp formatter ----
    function formatCairoDatetime(dtString) {
        if (!dtString) return "—";
        try {
            const date = new Date(dtString);
            return new Intl.DateTimeFormat("en-GB", {
                timeZone: "Africa/Cairo",
                day: "2-digit",
                month: "short",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false
            }).format(date);
        } catch (e) {
            return dtString;
        }
    }

    // ---- Activity type metadata ----
    const TYPE_META = {
        CALL:        { label: "Call",         icon: "📞", css: "type-call"     },
        WHATSAPP:    { label: "WhatsApp",     icon: "💬", css: "type-whatsapp" },
        VISIT:       { label: "Visit",        icon: "🏃", css: "type-visit"    },
        NOTE:        { label: "Note",         icon: "📝", css: "type-note"     },
        FOLLOW_UP:   { label: "Follow-Up",    icon: "🔔", css: "type-followup" },
        STAGE_CHANGE:{ label: "Stage Changed",icon: "🔄", css: "type-system"   },
        ASSIGNED:    { label: "Assigned",     icon: "👤", css: "type-system"   },
        REASSIGNED:  { label: "Reassigned",   icon: "👤", css: "type-system"   },
        CONVERTED:   { label: "Converted",    icon: "✅", css: "type-won"      },
        REACTIVATED: { label: "Reactivated",  icon: "♻️", css: "type-system"   },
        LOST:        { label: "Lost",         icon: "❌", css: "type-lost"     },
        REOPENED:    { label: "Reopened",     icon: "🔓", css: "type-reopened" }
    };

    function getTypeMeta(activityType) {
        if (TYPE_META[activityType]) return TYPE_META[activityType];
        // Graceful fallback for unknown/future types
        const humanLabel = activityType
            .split("_")
            .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
            .join(" ");
        return { label: humanLabel, icon: "📋", css: "type-system" };
    }

    // ---- Stage label mapper ----
    const STAGE_LABELS = {
        NEW: "New", CONTACTED: "Contacted", FOLLOW_UP: "Follow-Up",
        INTERESTED: "Interested", TRIAL: "Trial", WON: "Won", LOST: "Lost"
    };
    function stageLabel(s) {
        return s ? (STAGE_LABELS[s] || s) : null;
    }

    // ---- FOLLOW_UP_CLEARED marker handling ----
    // Possible stored formats (confirmed from services.py):
    //   "FOLLOW_UP_CLEARED"
    //   "<user text> [FOLLOW_UP_CLEARED]"
    const CLEARED_STANDALONE = "FOLLOW_UP_CLEARED";
    const CLEARED_SUFFIX     = " [FOLLOW_UP_CLEARED]";

    function parseResult(resultStr) {
        if (!resultStr) return { userText: null, cleared: false };
        let cleared = false;
        let userText = resultStr;

        if (resultStr === CLEARED_STANDALONE) {
            return { userText: null, cleared: true };
        }
        if (resultStr.endsWith(CLEARED_SUFFIX)) {
            cleared = true;
            userText = resultStr.slice(0, resultStr.length - CLEARED_SUFFIX.length).trim() || null;
        }
        return { userText, cleared };
    }

    // ---- Safe text node helper ----
    function textEl(tag, text, className) {
        const el = document.createElement(tag);
        if (className) el.className = className;
        el.textContent = text;
        return el;
    }

    // ---- Render a single activity item ----
    function renderActivityItem(item) {
        const meta   = getTypeMeta(item.activity_type || "");
        const actor  = item.user_username_snapshot || "System";
        const ts     = formatCairoDatetime(item.created_at);

        // Outer row
        const row = document.createElement("div");
        row.className = "timeline-item";

        // Icon circle
        const iconDiv = document.createElement("div");
        iconDiv.className = "timeline-icon";
        iconDiv.textContent = meta.icon;
        row.appendChild(iconDiv);

        // Body
        const body = document.createElement("div");
        body.className = "timeline-body";

        // Header row: [type badge] [actor] [timestamp]
        const headerRow = document.createElement("div");
        headerRow.className = "timeline-header-row";

        const typeBadge = document.createElement("span");
        typeBadge.className = "timeline-type-badge " + meta.css;
        typeBadge.textContent = meta.label;
        headerRow.appendChild(typeBadge);

        const actorSpan = document.createElement("span");
        actorSpan.className = "timeline-actor";
        actorSpan.textContent = actor;
        headerRow.appendChild(actorSpan);

        const tsSpan = document.createElement("span");
        tsSpan.className = "timeline-ts";
        tsSpan.textContent = ts;
        headerRow.appendChild(tsSpan);

        body.appendChild(headerRow);

        // Note (if present)
        if (item.note) {
            body.appendChild(textEl("div", item.note, "timeline-note"));
        }

        // Result (strip/present FOLLOW_UP_CLEARED marker)
        if (item.result) {
            const parsed = parseResult(item.result);
            if (parsed.userText) {
                body.appendChild(textEl("div", parsed.userText, "timeline-result"));
            }
            if (parsed.cleared) {
                const clearedBadge = document.createElement("span");
                clearedBadge.className = "badge-cleared";
                clearedBadge.textContent = "Follow-up cleared";
                body.appendChild(clearedBadge);
            }
        }

        // Stage change metadata (STAGE_CHANGE, LOST, REOPENED)
        const oldSt = stageLabel(item.old_stage);
        const newSt = stageLabel(item.new_stage);
        if (oldSt || newSt) {
            const metaRow = document.createElement("div");
            metaRow.className = "timeline-meta-row";

            const lbl = document.createElement("span");
            lbl.className = "timeline-meta-label";
            lbl.textContent = "Stage:";
            metaRow.appendChild(lbl);

            if (oldSt) {
                metaRow.appendChild(textEl("span", oldSt, null));
                const arrow = document.createElement("span");
                arrow.className = "timeline-stage-arrow";
                arrow.textContent = " → ";
                metaRow.appendChild(arrow);
            }
            if (newSt) {
                metaRow.appendChild(textEl("span", newSt, null));
            }
            body.appendChild(metaRow);
        }

        // Assignment metadata — only show user IDs since no snapshot for old/new assignees
        // (backend only stores old_assigned_user_id / new_assigned_user_id, no username snapshots for them)
        const oldAssign = item.old_assigned_user_id;
        const newAssign = item.new_assigned_user_id;
        if (newAssign !== null && newAssign !== undefined) {
            const metaRow = document.createElement("div");
            metaRow.className = "timeline-meta-row";
            const lbl = document.createElement("span");
            lbl.className = "timeline-meta-label";
            lbl.textContent = "Assigned to:";
            metaRow.appendChild(lbl);
            metaRow.appendChild(textEl("span", "User #" + newAssign, null));
            body.appendChild(metaRow);
        } else if (oldAssign !== null && oldAssign !== undefined &&
                   (item.activity_type === "ASSIGNED" || item.activity_type === "REASSIGNED")) {
            // Reassigned to unassigned (cleared assignment)
            const metaRow = document.createElement("div");
            metaRow.className = "timeline-meta-row";
            const lbl = document.createElement("span");
            lbl.className = "timeline-meta-label";
            lbl.textContent = "Assignment:";
            metaRow.appendChild(lbl);
            metaRow.appendChild(textEl("span", "Unassigned", null));
            body.appendChild(metaRow);
        }

        // Scheduled follow-up timestamp on this activity record
        if (item.follow_up_at) {
            const metaRow = document.createElement("div");
            metaRow.className = "timeline-meta-row";
            const lbl = document.createElement("span");
            lbl.className = "timeline-meta-label";
            lbl.textContent = "Follow-up scheduled:";
            metaRow.appendChild(lbl);
            metaRow.appendChild(textEl("span", formatCairoDatetime(item.follow_up_at), null));
            body.appendChild(metaRow);
        }

        row.appendChild(body);
        return row;
    }

    // ---- Show/hide timeline UI states ----
    function showTimelineLoading() {
        activityLoading.style.display = "block";
        activityError.style.display   = "none";
    }

    function hideTimelineLoading() {
        activityLoading.style.display = "none";
    }

    function showTimelineError(message) {
        activityLoading.style.display = "none";
        activityError.textContent     = message;
        activityError.style.display   = "block";
    }

    // ---- Load a page of activities ----
    function loadActivities(page) {
        if (isLoadingActivities) return;
        const leadId = window.CRM_LEAD_ID;
        if (!leadId) return;

        isLoadingActivities = true;
        const requestSequence = ++loadSequence;

        if (loadMoreBtn) {
            loadMoreBtn.disabled    = true;
            loadMoreBtn.textContent = "Loading...";
        }

        if (page === 1) {
            showTimelineLoading();
        }

        fetch("/crm/leads/" + leadId + "/activities?page=" + page + "&per_page=" + PER_PAGE)
            .then(function (res) {
                if (res.status === 403) {
                    throw new Error("Access denied to activity timeline.");
                }
                if (res.status === 404) {
                    throw new Error("Lead not found.");
                }
                if (!res.ok) {
                    throw new Error("Timeline request failed (" + res.status + ").");
                }
                return res.json();
            })
            .then(function (data) {
                if (requestSequence !== loadSequence) {
                    return;
                }
                hideTimelineLoading();

                currentPage = data.page;
                totalPages  = data.pages;

                // Update count badge
                if (countBadge) {
                    countBadge.textContent = data.total;
                    countBadge.style.display = "inline-block";
                }

                const items = data.items || [];

                if (page === 1 && items.length === 0) {
                    // Empty state
                    const emptyEl = document.createElement("div");
                    emptyEl.className = "timeline-empty";
                    emptyEl.textContent = "No CRM activity has been recorded for this lead yet.";
                    activityList.appendChild(emptyEl);
                } else {
                    // Append items (page 2+ appends below existing)
                    items.forEach(function (item) {
                        activityList.appendChild(renderActivityItem(item));
                    });
                }

                // Load More button visibility
                if (currentPage < totalPages) {
                    activityLoadMore.style.display = "block";
                    if (loadMoreBtn) {
                        loadMoreBtn.disabled    = false;
                        loadMoreBtn.textContent = "Load More";
                    }
                } else {
                    activityLoadMore.style.display = "none";
                }

                isLoadingActivities = false;
            })
            .catch(function (err) {
                if (requestSequence !== loadSequence) {
                    return;
                }
                hideTimelineLoading();
                isLoadingActivities = false;
                // Re-enable load more for retry if on page > 1
                if (page > 1) {
                    activityLoadMore.style.display = "block";
                    if (loadMoreBtn) {
                        loadMoreBtn.disabled    = false;
                        loadMoreBtn.textContent = "Retry";
                    }
                }
                showTimelineError("Could not load activity timeline. " + (err.message || ""));
            });
    }

    // ---- Load More button handler ----
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener("click", function () {
            if (!isLoadingActivities && currentPage < totalPages) {
                loadActivities(currentPage + 1);
            }
        });
    }

    // ---- Expose public reload for composer cross-module use ----
    // Resets pagination state and reloads from page 1.
    window.reloadTimeline = function () {
        loadSequence += 1;
        currentPage = 0;
        totalPages  = 1;
        isLoadingActivities = false;
        if (activityList) activityList.innerHTML = "";
        if (activityLoadMore) activityLoadMore.style.display = "none";
        if (countBadge) countBadge.style.display = "none";
        loadActivities(1);
    };

    // ---- Initial load (after DOM ready) ----
    document.addEventListener("DOMContentLoaded", function () {
        loadActivities(1);
    });

}());
