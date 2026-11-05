(function () {
    "use strict";

    const API_URL = "/transfers/history/";
    const PAGE_SIZE = 10;

    let currentPage = 1;
    let nextUrl = null;
    let previousUrl = null;

    const tableBody = document.getElementById("transfers-table-body");
    const filterForm = document.getElementById("transfer-filter-form");

    function csrfToken() {
        const cookie = document.cookie
            .split("; ")
            .find(row => row.startsWith("csrftoken="));

        return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
    }

    async function apiRequest(url) {
        const response = await fetch(url, {
            method: "GET",
            credentials: "same-origin",
            headers: {
                "Accept": "application/json",
                "X-CSRFToken": csrfToken()
            }
        });

        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.message || `Request failed (${response.status}).`);
        }

        return response.json();
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, char => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;"
        })[char]);
    }

    function formatAmount(amount, currency) {
        const value = Number(amount);
        if (!Number.isFinite(value)) {
            return `${escapeHtml(amount)} ${escapeHtml(currency || "")}`;
        }

        return `${value.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        })} ${escapeHtml(currency || "")}`;
    }

    function formatDate(value) {
        if (!value) return "—";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
    }

    function statusBadge(status) {
        const styles = {
            COMPLETED: "success",
            FAILED: "danger",
            REQUIRES_REVIEW: "warning",
            PENDING: "secondary",
            RESERVING: "info",
            RESERVED: "info",
            CREDITING: "info",
            CREDITED: "info",
            COMMITTING: "info",
            RECOVERING: "primary",
            COMPENSATING: "warning"
        };

        const color = styles[status] || "secondary";
        const label = String(status || "UNKNOWN").replaceAll("_", " ");

        return `<span class="badge bg-${color}-subtle text-${color}">${escapeHtml(label)}</span>`;
    }

    function updateSummary(summary) {
        document.getElementById("total-transfers").textContent = summary.total ?? 0;
        document.getElementById("completed-transfers").textContent = summary.completed ?? 0;
        document.getElementById("processing-transfers").textContent = summary.processing ?? 0;
        document.getElementById("review-transfers").textContent = summary.requires_review ?? 0;
    }

    function showError(message) {
        const box = document.getElementById("transfer-error");
        box.textContent = message;
        box.classList.remove("d-none");
    }

    function clearError() {
        const box = document.getElementById("transfer-error");
        box.textContent = "";
        box.classList.add("d-none");
    }

    function renderTransfers(transfers) {
        if (!transfers || transfers.length === 0) {
            tableBody.innerHTML = `
                <tr><td colspan="7" class="text-center text-muted py-5">
                    No transfers found.
                </td></tr>`;
            return;
        }

        tableBody.innerHTML = transfers.map(transfer => `
            <tr>
                <td class="small text-muted" title="${escapeHtml(transfer.id)}">
                    ${escapeHtml(String(transfer.id).substring(0, 8))}...
                </td>
                <td>${escapeHtml(transfer.source_account_number)}</td>
                <td>${escapeHtml(transfer.destination_account_number)}</td>
                <td class="fw-semibold">${formatAmount(transfer.amount, transfer.currency)}</td>
                <td>${statusBadge(transfer.status)}</td>
                <td>${formatDate(transfer.created_at)}</td>
                <td class="text-end">
                    <button type="button"
                        class="btn btn-sm btn-outline-primary view-transfer"
                        data-id="${escapeHtml(transfer.id)}">
                        <i data-feather="eye" class="me-1"></i> View Details
                    </button>
                </td>
            </tr>
        `).join("");

        if (window.feather) window.feather.replace();
    }

    function buildApiUrl() {
        const params = new URLSearchParams();
        const search = document.getElementById("search-input").value.trim();
        const status = document.getElementById("status-filter").value;
        const dateFrom = document.getElementById("date-from").value;
        const dateTo = document.getElementById("date-to").value;

        if (search) params.set("search", search);
        if (status) params.set("status", status);
        if (dateFrom) params.set("date_from", dateFrom);
        if (dateTo) params.set("date_to", dateTo);
        params.set("page", currentPage);

        return `${API_URL}?${params.toString()}`;
    }

    async function loadTransfers(url = null) {
        clearError();
        tableBody.innerHTML = `
            <tr><td colspan="7" class="text-center py-4">
                <span class="spinner-border spinner-border-sm text-primary me-2"></span>
                Loading transfers...
            </td></tr>`;

        try {
            const data = await apiRequest(url || buildApiUrl());
            const result = data.results || {};

            updateSummary(result.summary || {});
            renderTransfers(result.transfers || []);
            // Open a requested transfer automatically when coming from the dashboard.
            const params = new URLSearchParams(window.location.search);
            const transferId = params.get("transfer_id");

            if (transferId && !window.transferDetailsAutoOpened) {
                window.transferDetailsAutoOpened = true;
                viewTransferDetails(transferId);
            }

            nextUrl = data.next;
            previousUrl = data.previous;

            document.getElementById("previous-page").disabled = !previousUrl;
            document.getElementById("next-page").disabled = !nextUrl;

            const count = data.count || 0;
            const start = count ? ((currentPage - 1) * PAGE_SIZE) + 1 : 0;
            const end = Math.min(currentPage * PAGE_SIZE, count);

            document.getElementById("pagination-info").textContent =
                `Showing ${start} to ${end} of ${count} transfers`;
        } catch (error) {
            tableBody.innerHTML = `
                <tr><td colspan="7" class="text-center text-danger py-4">
                    ${escapeHtml(error.message)}
                </td></tr>`;
            showError(error.message);
        }
    }

    function stepStatusClass(status) {
        if (["SUCCESS", "COMPLETED"].includes(status)) return "success";
        if (["FAILED"].includes(status)) return "failed";
        return "pending";
    }

    function renderExecutionHistory(steps) {
        if (!steps || steps.length === 0) {
            return `<div class="text-muted small py-3">
                No execution history is available for this transfer.
            </div>`;
        }

        return `
            <div class="transfer-timeline">
                ${steps.map(step => {
                    const state = step.status || "PENDING";
                    const markerClass = stepStatusClass(state);
                    const icon = markerClass === "success" ? "✓" :
                                 markerClass === "failed" ? "!" : "•";

                    return `
                        <div class="transfer-timeline-item">
                            <div class="transfer-timeline-marker ${markerClass}">
                                ${icon}
                            </div>
                            <div class="transfer-step-card">
                                <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                                    <div class="transfer-step-name">
                                        ${escapeHtml(String(step.step_name || "").replaceAll("_", " "))}
                                    </div>
                                    ${statusBadge(state)}
                                </div>
                                <div class="d-flex flex-wrap gap-3 mt-2 transfer-step-meta">
                                    <span><i data-feather="repeat" class="me-1"></i>
                                        ${escapeHtml(step.attempt_count ?? 0)} attempt(s)
                                    </span>
                                    <span><i data-feather="clock" class="me-1"></i>
                                        Started: ${escapeHtml(formatDate(step.started_at))}
                                    </span>
                                    ${step.completed_at ? `
                                        <span><i data-feather="check" class="me-1"></i>
                                            Finished: ${escapeHtml(formatDate(step.completed_at))}
                                        </span>` : ""}
                                </div>
                                ${step.error_message ? `
                                    <div class="small text-danger mt-2">
                                        ${escapeHtml(step.error_message)}
                                    </div>` : ""}
                            </div>
                        </div>`;
                }).join("")}
            </div>`;
    }

    async function viewTransferDetails(transferId) {
        const modalElement = document.getElementById("transfer-details-modal");
        const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
        const content = document.getElementById("transfer-details-content");

        document.getElementById("detail-transfer-id").textContent = transferId;
        content.innerHTML = `
            <div class="text-center py-5">
                <div class="spinner-border text-primary" role="status"></div>
                <p class="text-muted mt-3 mb-0">Loading transfer details...</p>
            </div>`;

        modal.show();

        try {
            const data = await apiRequest(`/transfers/${encodeURIComponent(transferId)}/`);
            const transfer = data.transfer || {};
            const status = transfer.status || "UNKNOWN";

            content.innerHTML = `
                <div class="transfer-detail-hero mb-4">
                    <div>
                        <span class="transfer-detail-label">Transfer Amount</span>
                        <div class="transfer-detail-amount">
                            ${formatAmount(transfer.amount, transfer.currency)}
                        </div>
                        <div class="small text-muted mt-2">
                            Created ${escapeHtml(formatDate(transfer.created_at))}
                        </div>
                    </div>
                    <div class="text-md-end">
                        <span class="transfer-detail-label mb-2">Current Status</span>
                        <div>${statusBadge(status)}</div>
                    </div>
                </div>

                <div class="transfer-section-title">Transfer Information</div>
                <div class="row g-3 mb-4">
                    <div class="col-md-6">
                        <div class="transfer-info-card">
                            <span class="transfer-detail-label">Source Account</span>
                            <div class="transfer-info-value">
                                <i data-feather="arrow-up-right" class="text-primary me-1"></i>
                                ${escapeHtml(transfer.source_account_number || "—")}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="transfer-info-card">
                            <span class="transfer-detail-label">Destination Account</span>
                            <div class="transfer-info-value">
                                <i data-feather="arrow-down-left" class="text-success me-1"></i>
                                ${escapeHtml(transfer.destination_account_number || "—")}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="transfer-info-card">
                            <span class="transfer-detail-label">Created At</span>
                            <div class="transfer-info-value">
                                ${escapeHtml(formatDate(transfer.created_at))}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="transfer-info-card">
                            <span class="transfer-detail-label">Completed At</span>
                            <div class="transfer-info-value">
                                ${escapeHtml(formatDate(transfer.completed_at))}
                            </div>
                        </div>
                    </div>
                </div>

                ${data.failure_reason ? `
                    <div class="transfer-failure-box mb-4">
                        <strong><i data-feather="alert-triangle" class="me-1"></i>
                            Transfer information
                        </strong>
                        <div class="small mt-1">${escapeHtml(data.failure_reason)}</div>
                    </div>` : ""}

                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div class="transfer-section-title mb-0">Saga Execution Timeline</div>
                    <span class="small text-muted">
                        ${(data.execution_history || []).length} step(s)
                    </span>
                </div>
                ${renderExecutionHistory(data.execution_history || [])}
            `;

            if (window.feather) window.feather.replace();
        } catch (error) {
            content.innerHTML = `
                <div class="alert alert-danger mb-0">
                    <strong>Unable to load transfer details</strong>
                    <div class="small mt-1">${escapeHtml(error.message)}</div>
                </div>`;
        }
    }

    filterForm.addEventListener("submit", event => {
        event.preventDefault();
        currentPage = 1;
        loadTransfers();
    });

    document.getElementById("reset-filters").addEventListener("click", () => {
        filterForm.reset();
        currentPage = 1;
        loadTransfers();
    });

    document.getElementById("next-page").addEventListener("click", () => {
        if (!nextUrl) return;
        currentPage += 1;
        loadTransfers(nextUrl);
    });

    document.getElementById("previous-page").addEventListener("click", () => {
        if (!previousUrl) return;
        currentPage = Math.max(1, currentPage - 1);
        loadTransfers(previousUrl);
    });

    tableBody.addEventListener("click", event => {
        const button = event.target.closest(".view-transfer");
        if (button) viewTransferDetails(button.dataset.id);
    });

    document.getElementById("copy-transfer-reference").addEventListener("click", async () => {
        const reference = document.getElementById("detail-transfer-id").textContent.trim();
        if (!reference) return;

        try {
            await navigator.clipboard.writeText(reference);
            const feedback = document.getElementById("copy-reference-feedback");
            feedback.classList.remove("d-none");
            window.setTimeout(() => feedback.classList.add("d-none"), 1800);
        } catch (error) {
            showError("Unable to copy the transfer reference. Please copy it manually.");
        }
    });

    loadTransfers();
})();
