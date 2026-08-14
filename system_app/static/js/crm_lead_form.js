document.addEventListener("DOMContentLoaded", () => {
    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    // Elements
    const openModalBtn = document.getElementById("openCreateModalBtn");
    const modal = document.getElementById("createLeadModal");
    const closeModalSpan = document.getElementById("closeCreateModal");
    const cancelBtn = document.getElementById("cancelCreateLead");

    const modeProspectBtn = document.getElementById("modeProspectBtn");
    const modeMemberBtn = document.getElementById("modeMemberBtn");

    const prospectFields = document.getElementById("prospectFields");
    const memberSelectorSection = document.getElementById("memberSelectorSection");

    const memberSearchInput = document.getElementById("memberSearchInput");
    const memberSearchResults = document.getElementById("memberSearchResults");

    const selectedMemberSummary = document.getElementById("selectedMemberSummary");
    const selMemberId = document.getElementById("selMemberId");
    const selMemberName = document.getElementById("selMemberName");
    const selMemberPhone = document.getElementById("selMemberPhone");
    const selMemberEmail = document.getElementById("selMemberEmail");
    const selMemberStatus = document.getElementById("selMemberStatus");
    const clearMemberBtn = document.getElementById("clearMemberSelection");

    const feedbackPanel = document.getElementById("createLeadFeedback");
    const submitBtn = document.getElementById("submitCreateLeadBtn");
    const createForm = document.getElementById("createLeadForm");

    let currentMode = "prospect"; // prospect | existing_member
    let selectedMemberId = null;
    let searchTimeout = null;

    // Modal open/close
    if (openModalBtn) {
        openModalBtn.addEventListener("click", () => {
            modal.style.display = "block";
            resetForm();
        });
    }

    const closeActions = [closeModalSpan, cancelBtn];
    closeActions.forEach(el => {
        if (el) {
            el.addEventListener("click", () => {
                modal.style.display = "none";
            });
        }
    });

    window.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.style.display = "none";
        }
    });

    // Form Mode Toggles
    modeProspectBtn.addEventListener("click", () => {
        setMode("prospect");
    });

    modeMemberBtn.addEventListener("click", () => {
        setMode("existing_member");
    });

    function setMode(mode) {
        currentMode = mode;
        clearFeedback();
        if (mode === "prospect") {
            modeProspectBtn.style.background = "#4caf50";
            modeProspectBtn.style.color = "white";
            modeMemberBtn.style.background = "rgba(30,30,40,0.8)";
            modeMemberBtn.style.color = "#4caf50";

            prospectFields.style.display = "block";
            memberSelectorSection.style.display = "none";
            clearSelection();
        } else {
            modeMemberBtn.style.background = "#4caf50";
            modeMemberBtn.style.color = "white";
            modeProspectBtn.style.background = "rgba(30,30,40,0.8)";
            modeProspectBtn.style.color = "#4caf50";

            prospectFields.style.display = "none";
            memberSelectorSection.style.display = "block";
        }
    }

    // Reset fields on modal show
    function resetForm() {
        setMode("prospect");
        createForm.reset();
        clearSelection();
        clearFeedback();
        enableSubmitBtn();
    }

    // Member search autocomplete
    memberSearchInput.addEventListener("input", () => {
        clearTimeout(searchTimeout);
        const query = memberSearchInput.value.trim();

        if (query.length < 2) {
            memberSearchResults.style.display = "none";
            memberSearchResults.innerHTML = "";
            return;
        }

        searchTimeout = setTimeout(() => {
        apiFetch(`/crm/members/search?q=${encodeURIComponent(query)}`)
            .then(res => {
                if (!res.ok) throw new Error("HTTP " + res.status);
                return res.json();
            })
                .then(members => {
                    renderSearchResults(members);
                })
                .catch(err => {
                    console.error("Member autocomplete failed:", err);
                });
        }, 300); // 300ms debounce
    });

    function renderSearchResults(members) {
        memberSearchResults.innerHTML = "";

        if (members.length === 0) {
            const noRes = document.createElement("div");
            noRes.style.padding = "10px";
            noRes.style.color = "#888";
            noRes.textContent = "No matching members found.";
            memberSearchResults.appendChild(noRes);
            memberSearchResults.style.display = "block";
            return;
        }

        members.forEach(member => {
            const div = document.createElement("div");
            div.style.padding = "10px";
            div.style.cursor = "pointer";
            div.style.borderBottom = "1px solid rgba(76,175,80,0.1)";
            div.style.color = "#eee";
            div.style.transition = "background 0.2s";

            // Hover state
            div.addEventListener("mouseenter", () => {
                div.style.background = "rgba(76,175,80,0.15)";
            });
            div.addEventListener("mouseleave", () => {
                div.style.background = "transparent";
            });

            // Text display details
            const nameSpan = document.createElement("span");
            nameSpan.style.fontWeight = "bold";
            nameSpan.style.color = "#4caf50";
            nameSpan.textContent = member.name;

            const infoSpan = document.createElement("span");
            infoSpan.style.fontSize = "12px";
            infoSpan.style.color = "#aaa";
            infoSpan.style.marginLeft = "10px";
            infoSpan.textContent = `(ID: ${member.id} | Phone: ${member.phone} | Status: ${member.membership_status})`;

            div.appendChild(nameSpan);
            div.appendChild(infoSpan);

            // Select handler
            div.addEventListener("click", () => {
                selectMember(member);
            });

            memberSearchResults.appendChild(div);
        });

        memberSearchResults.style.display = "block";
    }

    function selectMember(member) {
        selectedMemberId = member.id;

        selMemberId.textContent = member.id;
        selMemberName.textContent = member.name || "—";
        selMemberPhone.textContent = member.phone || "—";
        selMemberEmail.textContent = member.email || "—";
        selMemberStatus.textContent = member.membership_status || "—";

        selectedMemberSummary.style.display = "block";
        memberSearchResults.style.display = "none";
        memberSearchInput.value = "";
    }

    function clearSelection() {
        selectedMemberId = null;
        selMemberId.textContent = "—";
        selMemberName.textContent = "—";
        selMemberPhone.textContent = "—";
        selMemberEmail.textContent = "—";
        selMemberStatus.textContent = "—";
        selectedMemberSummary.style.display = "none";
    }

    clearMemberBtn.addEventListener("click", () => {
        clearSelection();
    });

    // Feedback panel helper
    function showFeedback(contentNode, isError = true) {
        feedbackPanel.innerHTML = "";
        feedbackPanel.appendChild(contentNode);
        feedbackPanel.style.background = isError ? "rgba(244,67,54,0.1)" : "rgba(76,175,80,0.1)";
        feedbackPanel.style.borderColor = isError ? "rgba(244,67,54,0.3)" : "rgba(76,175,80,0.3)";
        feedbackPanel.style.color = isError ? "#f44336" : "#4caf50";
        feedbackPanel.style.display = "block";
    }

    function showTextFeedback(text, isError = true) {
        const div = document.createElement("div");
        div.textContent = text;
        showFeedback(div, isError);
    }

    function clearFeedback() {
        feedbackPanel.innerHTML = "";
        feedbackPanel.style.display = "none";
    }

    function disableSubmitBtn() {
        submitBtn.disabled = true;
        submitBtn.textContent = "Saving Lead...";
        submitBtn.style.opacity = "0.6";
        submitBtn.style.cursor = "not-allowed";
    }

    function enableSubmitBtn() {
        submitBtn.disabled = false;
        submitBtn.textContent = "Save Lead";
        submitBtn.style.opacity = "1";
        submitBtn.style.cursor = "pointer";
    }

    // 409 Conflict handlers
    function handleMemberMatchFound(details) {
        const container = document.createElement("div");
        const title = document.createElement("div");
        title.style.fontWeight = "bold";
        title.style.marginBottom = "8px";
        title.textContent = "Existing member records match this phone or email:";
        container.appendChild(title);

        const list = document.createElement("div");
        list.style.display = "flex";
        list.style.flexDirection = "column";
        list.style.gap = "8px";
        list.style.marginBottom = "12px";

        (details.members || []).forEach(member => {
            const item = document.createElement("div");
            item.style.display = "flex";
            item.style.justifyContent = "space-between";
            item.style.alignItems = "center";
            item.style.background = "rgba(0,0,0,0.2)";
            item.style.padding = "8px";
            item.style.borderRadius = "4px";

            const textDiv = document.createElement("div");
            textDiv.style.fontSize = "12px";
            textDiv.style.color = "#eee";
            textDiv.textContent = `${member.name} (ID: ${member.id} | Phone: ${member.phone})`;
            item.appendChild(textDiv);

            const selectBtn = document.createElement("button");
            selectBtn.type = "button";
            selectBtn.className = "index-btn";
            selectBtn.style.padding = "4px 8px";
            selectBtn.style.fontSize = "11px";
            selectBtn.textContent = "Use Existing Member";
            selectBtn.addEventListener("click", () => {
                setMode("existing_member");
                selectMember(member);
                clearFeedback();
            });
            item.appendChild(selectBtn);
            list.appendChild(item);
        });

        container.appendChild(list);
        showFeedback(container, true);
    }

    function handleActiveLeadExists(message, details) {
        const container = document.createElement("div");
        const msgDiv = document.createElement("div");
        msgDiv.textContent = message;
        container.appendChild(msgDiv);

        if (details && details.existing_lead_id) {
            const link = document.createElement("a");
            link.href = `/crm/leads/${details.existing_lead_id}/view`;
            link.className = "index-btn";
            link.style.display = "inline-block";
            link.style.marginTop = "10px";
            link.style.textDecoration = "none";
            link.style.fontSize = "12px";
            link.style.padding = "6px 12px";
            link.style.background = "linear-gradient(135deg, #2196F3, #42a5f5)";
            link.style.color = "white";
            link.style.fontWeight = "600";
            link.textContent = "View Active Lead";
            container.appendChild(link);
        }

        showFeedback(container, true);
    }

    // Submit handler
    createForm.addEventListener("submit", (e) => {
        e.preventDefault();
        clearFeedback();

        const source = document.getElementById("leadSourceInput").value.trim();
        const notes = document.getElementById("leadNotesInput").value.trim();

        let payload = {};

        if (currentMode === "prospect") {
            const name = document.getElementById("prospectName").value.trim();
            const phone = document.getElementById("prospectPhone").value.trim();
            const email = document.getElementById("prospectEmail").value.trim();

            if (!name) {
                showTextFeedback("Name is required");
                return;
            }
            if (!phone) {
                showTextFeedback("Phone number is required");
                return;
            }
            if (!source) {
                showTextFeedback("Source is required");
                return;
            }

            payload = { name, phone, email, source, notes };
        } else {
            if (!selectedMemberId) {
                showTextFeedback("You must select an existing member");
                return;
            }
            if (!source) {
                showTextFeedback("Source is required");
                return;
            }

            payload = { member_id: selectedMemberId, source, notes };
        }

        disableSubmitBtn();

        apiFetch("/crm/leads", {
            method: "POST",
            body: JSON.stringify(payload)
        })
        .then(res => {
            if (res.status === 201) {
                return res.json().then(data => {
                    if (data && data.id) {
                        window.location.href = `/crm/leads/${data.id}/view`;
                    } else {
                        throw new Error("Created but lead ID is missing in response");
                    }
                });
            }

            return res.json().then(errorData => {
                enableSubmitBtn();
                if (res.status === 409) {
                    if (errorData.error === "member_match_found") {
                        handleMemberMatchFound(errorData.details || {});
                    } else if (errorData.error === "active_lead_exists") {
                        handleActiveLeadExists(errorData.message, errorData.details || {});
                    } else {
                        showTextFeedback(errorData.message || "Conflict occurred.");
                    }
                } else if (res.status === 400) {
                    showTextFeedback("Validation failed: " + (errorData.message || "Invalid inputs"));
                } else if (res.status === 403) {
                    showTextFeedback("Access denied: " + (errorData.message || "Insufficient permissions"));
                } else {
                    showTextFeedback("Error " + res.status + ": " + (errorData.message || "Failed to save lead"));
                }
            });
        })
        .catch(err => {
            console.error("Failed to submit lead:", err);
            enableSubmitBtn();
            showTextFeedback("Network or connection error. Please try again.");
        });
    });
});
