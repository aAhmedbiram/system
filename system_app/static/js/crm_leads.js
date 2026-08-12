document.addEventListener("DOMContentLoaded", () => {
    let currentPage = 1;
    const perPage = 25;
    let searchTimeout = null;

    // Elements
    const searchInput = document.getElementById("searchQuery");
    const stageSelect = document.getElementById("stageFilter");
    const typeSelect = document.getElementById("typeFilter");

    const loadingState = document.getElementById("loadingState");
    const errorState = document.getElementById("errorState");
    const emptyState = document.getElementById("emptyState");
    const leadsTable = document.getElementById("leadsTable");
    const tableBody = document.getElementById("leadsTableBody");

    const prevBtn = document.getElementById("prevBtn");
    const nextBtn = document.getElementById("nextBtn");
    const pageIndicator = document.getElementById("pageIndicator");

    // Fetch and render function
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

                    // Lead ID
                    const tdId = document.createElement("td");
                    tdId.textContent = lead.id;
                    row.appendChild(tdId);

                    // Name
                    const tdName = document.createElement("td");
                    tdName.textContent = lead.name || "—";
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

    // Event listeners
    prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            fetchLeads();
        }
    });

    nextBtn.addEventListener("click", () => {
        currentPage++;
        fetchLeads();
    });

    // Reset pagination on filter changes
    function onFilterChange() {
        currentPage = 1;
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

    // Initial fetch
    fetchLeads();
});
