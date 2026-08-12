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

    const editFeedback = document.getElementById("editLeadFeedback");
    const submitEditBtn = document.getElementById("submitEditLeadBtn");

    let currentLead = null;

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
        document.getElementById("leadFollowUp").textContent = formatDatetime(lead.next_follow_up_at);
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
            })
            .catch(err => {
                console.error("Error fetching lead parameters:", err);
            });
    }

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

            fetch(`/crm/leads/${leadId}`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json"
                },
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
});

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

    // ---- Initial load (after DOM ready) ----
    document.addEventListener("DOMContentLoaded", function () {
        loadActivities(1);
    });

}());
