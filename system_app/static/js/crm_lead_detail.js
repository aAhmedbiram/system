document.addEventListener("DOMContentLoaded", () => {
    const leadId = window.CRM_LEAD_ID;
    if (!leadId) {
        showError("Invalid lead identifier");
        return;
    }

    const loader = document.getElementById("loadingDetails");
    const errorState = document.getElementById("errorDetails");
    const container = document.getElementById("detailsContainer");

    function showError(message) {
        loader.style.display = "none";
        container.style.display = "none";
        errorState.textContent = message || "Failed to load lead details.";
        errorState.style.display = "block";
    }

    fetch(`/crm/leads/${leadId}`)
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
            }

            container.style.display = "block";
        })
        .catch(err => {
            console.error("Error fetching lead parameters:", err);
        });

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
