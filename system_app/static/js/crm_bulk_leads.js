document.addEventListener("DOMContentLoaded", () => {
    const previewTokenInput = document.getElementById("previewTokenInput");
    const loadPreviewBtn = document.getElementById("loadPreviewBtn");
    const executeBulkBtn = document.getElementById("executeBulkBtn");
    const executeFeedback = document.getElementById("executeFeedback");
    const resultPanel = document.getElementById("resultPanel");
    const resultRequested = document.getElementById("resultRequested");
    const resultCreated = document.getElementById("resultCreated");
    const resultSkipped = document.getElementById("resultSkipped");
    const resultFailed = document.getElementById("resultFailed");
    const resultAssignments = document.getElementById("resultAssignments");
    const resultSkippedItems = document.getElementById("resultSkippedItems");

    const previewSummaryCard = document.getElementById("previewSummaryCard");
    const previewSummaryEmpty = document.getElementById("previewSummaryEmpty");
    const previewSource = document.getElementById("previewSource");
    const previewSelected = document.getElementById("previewSelected");
    const previewEligible = document.getElementById("previewEligible");
    const previewSkipped = document.getElementById("previewSkipped");
    const previewMissing = document.getElementById("previewMissing");
    const previewPlanCount = document.getElementById("previewPlanCount");
    const previewDistribution = document.getElementById("previewDistribution");
    const previewTokenDisplay = document.getElementById("previewTokenDisplay");

    function apiFetch(url, options) {
        if (window.CRM && typeof window.CRM.apiFetch === "function") {
            return window.CRM.apiFetch(url, options);
        }
        return fetch(url, options);
    }

    function setFeedback(message, isError) {
        if (!executeFeedback) return;
        executeFeedback.style.display = "block";
        executeFeedback.className = isError ? "feedback error" : "feedback success";
        executeFeedback.textContent = message;
    }

    function clearFeedback() {
        if (!executeFeedback) return;
        executeFeedback.textContent = "";
        executeFeedback.style.display = "none";
        executeFeedback.className = "feedback";
    }

    function setButtonBusy(isBusy) {
        if (!executeBulkBtn) return;
        executeBulkBtn.disabled = isBusy;
        executeBulkBtn.textContent = isBusy ? "Executing..." : "Execute Bulk Leads";
    }

    function navigateToLoadedPreview() {
        const token = (previewTokenInput && previewTokenInput.value || "").trim();
        if (!token) {
            setFeedback("Preview token is required.", true);
            return;
        }
        window.location.href = "/crm/leads/bulk?preview_token=" + encodeURIComponent(token);
    }

    function clearChildren(node) {
        if (!node) return;
        node.replaceChildren();
    }

    function appendSummaryItem(listNode, text) {
        if (!listNode) return;
        const li = document.createElement("li");
        li.textContent = text;
        listNode.appendChild(li);
    }

    function renderPreviewSummary(summary) {
        if (!summary || !previewSummaryCard) return;
        if (previewSummaryEmpty) {
            previewSummaryEmpty.style.display = "none";
        }
        previewSummaryCard.style.display = "block";

        if (previewSource) previewSource.textContent = summary.source || "EXISTING_MEMBER";
        if (previewSelected) previewSelected.textContent = String(summary.selected_count ?? 0);
        if (previewEligible) previewEligible.textContent = String(summary.eligible_count ?? 0);
        if (previewSkipped) previewSkipped.textContent = String(summary.skipped_count ?? 0);
        if (previewMissing) previewMissing.textContent = String(summary.missing_count ?? 0);
        if (previewPlanCount) previewPlanCount.textContent = String(summary.assignment_plan_count ?? 0);
        if (previewTokenDisplay) previewTokenDisplay.textContent = summary.preview_token || "";

        clearChildren(previewDistribution);
        (summary.distribution || []).forEach((row) => {
            const label = row && row.username ? row.username : "User " + String(row.user_id ?? "");
            appendSummaryItem(
                previewDistribution,
                label + " (" + String(row.user_id ?? "n/a") + ") - " + String(row.lead_count ?? 0) + " planned"
            );
        });
        if (!summary.distribution || summary.distribution.length === 0) {
            appendSummaryItem(previewDistribution, "Unassigned");
        }
    }

    function renderExecutionResult(result) {
        if (!resultPanel) return;
        resultPanel.style.display = "block";
        if (resultRequested) resultRequested.textContent = String(result.requested ?? 0);
        if (resultCreated) resultCreated.textContent = String(result.created ?? 0);
        if (resultSkipped) resultSkipped.textContent = String(result.skipped ?? 0);
        if (resultFailed) resultFailed.textContent = String(result.failed ?? 0);

        clearChildren(resultAssignments);
        (result.assignments || []).forEach((row) => {
            const li = document.createElement("li");
            const label = row && row.username ? row.username : "User " + String(row.user_id ?? "");
            li.textContent = label + " (" + String(row.user_id ?? "n/a") + ") - " + String(row.created ?? 0) + " created";
            resultAssignments.appendChild(li);
        });
        if (!result.assignments || result.assignments.length === 0) {
            appendSummaryItem(resultAssignments, "No employee assignments");
        }

        if (resultSkippedItems) {
            resultSkippedItems.textContent = JSON.stringify(result.skipped_items || [], null, 2);
        }
    }

    if (window.CRM_BULK_PREVIEW_TOKEN && previewTokenInput) {
        previewTokenInput.value = window.CRM_BULK_PREVIEW_TOKEN;
    }

    if (window.CRM_BULK_PREVIEW_SUMMARY) {
        renderPreviewSummary(window.CRM_BULK_PREVIEW_SUMMARY);
    }

    if (previewTokenInput && executeBulkBtn) {
        const syncExecuteState = () => {
            executeBulkBtn.disabled = !previewTokenInput.value.trim();
        };
        previewTokenInput.addEventListener("input", syncExecuteState);
        syncExecuteState();
    }

    if (loadPreviewBtn) {
        loadPreviewBtn.addEventListener("click", navigateToLoadedPreview);
    }

    if (executeBulkBtn) {
        executeBulkBtn.addEventListener("click", () => {
            const token = (previewTokenInput && previewTokenInput.value || "").trim();
            if (!token) {
                setFeedback("Preview token is required.", true);
                return;
            }

            clearFeedback();
            setButtonBusy(true);

            apiFetch("/crm/leads/bulk/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ preview_token: token })
            })
                .then((response) => {
                    return response.json().then((data) => ({ response, data }));
                })
                .then(({ response, data }) => {
                    if (!response.ok) {
                        const message = (data && data.message) ? data.message : "Bulk execution failed.";
                        setFeedback(message, true);
                        return;
                    }

                    renderExecutionResult(data);
                    setFeedback(
                        "Bulk execution completed. Created " + String(data.created ?? 0) +
                        " lead(s), skipped " + String(data.skipped ?? 0) + ".",
                        false
                    );
                })
                .catch(() => {
                    setFeedback("Network error while executing bulk leads.", true);
                })
                .finally(() => {
                    setButtonBusy(false);
                });
        });
    }
});
