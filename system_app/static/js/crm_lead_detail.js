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
