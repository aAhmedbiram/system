document.addEventListener("DOMContentLoaded", () => {
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
        if (mode === "prospect") {
            modeProspectBtn.style.background = "#4caf50";
            modeProspectBtn.style.color = "white";
            modeMemberBtn.style.background = "rgba(30,30,40,0.8)";
            modeMemberBtn.style.color = "#4caf50";

            prospectFields.style.display = "block";
            memberSelectorSection.style.display = "none";
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
        document.getElementById("createLeadForm").reset();
        clearSelection();
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
            fetch(`/crm/members/search?q=${encodeURIComponent(query)}`)
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
});
