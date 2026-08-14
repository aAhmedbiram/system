document.addEventListener("DOMContentLoaded", () => {
    const leadId = window.CRM_LEAD_ID;
    const leadLoading = document.getElementById("leadLoading");
    const leadError = document.getElementById("leadError");
    const leadContext = document.getElementById("leadContext");
    const memberSummaryCard = document.getElementById("memberSummaryCard");
    const workspaceTitle = document.getElementById("workspaceTitle");
    const workspaceNote = document.getElementById("workspaceNote");
    const convertForm = document.getElementById("convertForm");
    const convertBtn = document.getElementById("convertBtn");
    const convertFeedback = document.getElementById("convertFeedback");
    const prospectFields = document.getElementById("prospectFields");

    let currentLead = null;
    let isSubmitting = false;

    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    function showError(message) {
        leadLoading.style.display = "none";
        leadContext.style.display = "none";
        leadError.textContent = message;
        leadError.style.display = "block";
    }

    function showFeedback(message, isError) {
        convertFeedback.textContent = message;
        convertFeedback.className = "feedback " + (isError ? "error" : "success");
        convertFeedback.style.display = "block";
    }

    function clearFeedback() {
        convertFeedback.textContent = "";
        convertFeedback.style.display = "none";
        convertFeedback.className = "feedback";
    }

    function setSubmitting(submitting) {
        isSubmitting = submitting;
        convertBtn.disabled = submitting;
        convertBtn.textContent = submitting ? "Submitting..." : "Submit Conversion";
    }

    function renderLead(lead) {
        currentLead = lead;
        leadLoading.style.display = "none";
        leadContext.style.display = "block";

        document.getElementById("leadName").textContent = lead.name || "—";
        document.getElementById("leadType").textContent = lead.member_id ? "Existing Member Lead" : "Prospect Lead";
        document.getElementById("leadPhone").textContent = lead.phone || "—";
        document.getElementById("leadEmail").textContent = lead.email || "—";
        document.getElementById("leadStage").textContent = lead.stage || "—";
        document.getElementById("leadAssignee").textContent = lead.assigned_username || "Unassigned";

        if (lead.member_id && lead.member) {
            memberSummaryCard.style.display = "block";
            document.getElementById("memberId").textContent = lead.member.id || "—";
            document.getElementById("memberName").textContent = lead.member.name || "—";
            document.getElementById("memberStatus").textContent = lead.member.membership_status || "—";
            document.getElementById("memberEndDate").textContent = lead.member.end_date || "—";
            if (workspaceTitle) workspaceTitle.textContent = "Reactivation Details";
            if (workspaceNote) workspaceNote.textContent = "This lead is linked to an existing member. Only renewal details are required.";
            if (prospectFields) prospectFields.style.display = "none";
        } else {
            memberSummaryCard.style.display = "none";
            if (workspaceTitle) workspaceTitle.textContent = "Conversion Details";
            if (workspaceNote) workspaceNote.textContent = "Enter the member data required for conversion. Backend validation remains authoritative.";
            if (prospectFields) prospectFields.style.display = "block";
        }
    }

    function loadLead() {
        return apiFetch(`/crm/leads/${leadId}`)
            .then(res => {
                if (res.status === 404) {
                    throw new Error("Lead not found.");
                }
                if (!res.ok) {
                    throw new Error("Status " + res.status);
                }
                return res.json();
            })
            .then(renderLead)
            .catch(err => {
                showError(err.message || "Failed to load lead.");
            });
    }

    loadLead();

    convertForm.addEventListener("submit", (e) => {
        e.preventDefault();
        clearFeedback();
        if (isSubmitting) return;

        const payload = {};
        const startingDate = document.getElementById("startingDate").value.trim();
        const actualStartingDate = document.getElementById("actualStartingDate").value.trim();
        const membershipPackages = document.getElementById("membershipPackages").value.trim();
        const membershipFees = document.getElementById("membershipFees").value.trim();

        if (!startingDate) {
            showFeedback("Starting date is required.", true);
            return;
        }
        if (!membershipPackages) {
            showFeedback("Membership package is required.", true);
            return;
        }

        payload.starting_date = startingDate;
        payload.membership_packages = membershipPackages;
        if (actualStartingDate) {
            payload.actual_starting_date = actualStartingDate;
        }
        if (membershipFees !== "") {
            payload.membership_fees = Number(membershipFees);
        }

        if (!currentLead.member_id) {
            const gender = document.getElementById("gender").value.trim();
            const birthdate = document.getElementById("birthdate").value.trim();
            const nationalId = document.getElementById("nationalId").value.trim();
            const comment = document.getElementById("comment").value.trim();

            if (gender) payload.gender = gender;
            if (birthdate) payload.birthdate = birthdate;
            if (nationalId) payload.national_id = nationalId;
            if (comment) payload.comment = comment;
        }

        setSubmitting(true);
        showFeedback("Submitting conversion...", false);

        apiFetch(`/crm/leads/${leadId}/convert`, {
            method: "POST",
            body: JSON.stringify(payload)
        })
            .then(res => res.json().then(data => ({ status: res.status, data })))
            .then(r => {
                if (r.status === 200) {
                    const message = r.data.conversion_type === "reactivation"
                        ? "Member reactivation completed."
                        : "Lead converted to member.";
                    showFeedback(message, false);
                    loadLead();
                    return;
                }
                showFeedback((r.data && r.data.message) ? r.data.message : "Conversion failed.", true);
            })
            .catch(() => {
                showFeedback("Network error while submitting conversion.", true);
            })
            .finally(() => {
                setSubmitting(false);
            });
    });
});
