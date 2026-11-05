(function () {
    "use strict";

    const LIST_API = "/recovery/monitoring/api/";
    let currentPage = 1;
    let nextUrl = null;
    let previousUrl = null;
    let selectedTransferId = null;
    let selectedTransferStatus = null;
    let selectedDeadLetteredAt = null;
    let selectedRecoveryDeadline = null;

    const tbody = document.getElementById("recovery-table-body");
    const modalElement = document.getElementById("recovery-detail-modal");
    const modal = bootstrap.Modal.getOrCreateInstance(modalElement);

    function csrfToken() {
        const row = document.cookie.split("; ").find(x => x.trim().startsWith("csrftoken="));
        return row ? decodeURIComponent(row.trim().substring("csrftoken=".length)) : "";
    }

    async function request(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers: {
                "Accept": "application/json",
                "X-CSRFToken": csrfToken(),
                ...(options.headers || {})
            }
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.message || data.detail || `Request failed (${response.status}).`);
        }
        return data;
    }

    function esc(value) {
        return String(value ?? "").replace(/[&<>"']/g, c => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
        })[c]);
    }

    function date(value) {
        if (!value) return "—";
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString();
    }

    function badge(status) {
        const map = {
            REQUIRES_REVIEW: ["warning", "Requires review"],
            RECOVERING: ["primary", "Recovering"],
            RESERVING: ["info", "Reserving"],
            RESERVED: ["warning", "Reserved"],
            CREDITING: ["info", "Crediting"],
            CREDITED: ["success", "Credited"],
            COMMITTING: ["info", "Committing"],
            COMPLETED: ["success", "Completed"],
            FAILED: ["danger", "Failed"],
            SUCCESS: ["success", "Success"],
            PENDING: ["secondary", "Pending"],
            RUNNING: ["primary", "Running"]
        };
        const [color, label] = map[status] || ["secondary", String(status || "Unknown").replaceAll("_", " ")];
        return `<span class="badge bg-${color}-subtle text-${color}">${esc(label)}</span>`;
    }

    function showError(message) {
        const el = document.getElementById("recovery-error");
        el.textContent = message;
        el.classList.remove("d-none");
    }

    function clearError() {
        const el = document.getElementById("recovery-error");
        el.textContent = "";
        el.classList.add("d-none");
    }

    function queryUrl() {
        const params = new URLSearchParams();
        const search = document.getElementById("recovery-search").value.trim();
        const bucket = document.getElementById("recovery-bucket").value;
        const status = document.getElementById("recovery-status").value;
        if (search) params.set("search", search);
        if (bucket) params.set("bucket", bucket);
        if (status) params.set("status", status);
        params.set("page", currentPage);
        return `${LIST_API}?${params.toString()}`;
    }

    function renderRows(rows) {
        if (!rows.length) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-5">
                No recovery cases match your filters.
            </td></tr>`;
            return;
        }

        tbody.innerHTML = rows.map(item => `
            <tr>
                <td>
                    <div class="fw-semibold">${esc(item.id.substring(0, 8))}...</div>
                    <small class="text-muted">${esc(item.source_account_number)} → ${esc(item.destination_account_number)}</small>
                </td>
                <td class="fw-semibold">${Number(item.amount).toLocaleString(undefined, {minimumFractionDigits: 2})} ${esc(item.currency)}</td>
                <td>${badge(item.status)}</td>
                <td><small>${esc(String(item.current_step || "—").replaceAll("_", " "))}</small></td>
                <td>${esc(item.retry_count)} / ${esc(item.max_retries)}</td>
                <td><small>${date(item.next_retry_at)}</small></td>
                <td><small>${date(item.recovery_deadline)}</small></td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-primary inspect-recovery" data-id="${esc(item.id)}">
                        Inspect
                    </button>
                </td>
            </tr>
        `).join("");
    }

    async function loadCases(url = null) {
        clearError();
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4">Loading recovery cases...</td></tr>`;
        try {
            const data = await request(url || queryUrl());
            const result = data.results || {};
            const summary = result.summary || {};

            document.getElementById("summary-review").textContent = summary.requires_review ?? 0;
            document.getElementById("summary-recovering").textContent = summary.recovering ?? 0;
            document.getElementById("summary-dead").textContent = summary.dead_lettered ?? 0;
            document.getElementById("summary-retry").textContent = summary.awaiting_retry ?? 0;

            const rows = result.transfers || [];
            renderRows(rows);
            nextUrl = data.next;
            previousUrl = data.previous;
            document.getElementById("recovery-next").disabled = !nextUrl;
            document.getElementById("recovery-previous").disabled = !previousUrl;

            const count = data.count || 0;
            const start = count ? ((currentPage - 1) * 10) + 1 : 0;
            document.getElementById("recovery-pagination-info").textContent =
                `Showing ${start} to ${Math.min(currentPage * 10, count)} of ${count} recovery cases`;
        } catch (error) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">${esc(error.message)}</td></tr>`;
            showError(error.message);
        }
    }

    function renderBankState(label, state, bankName) {
        const status = state?.status || "NO_RECORD";
        const statusLabel = state ? String(status).replaceAll("_", " ") : "No transaction record found";
        const statusClass = !state ? "text-secondary" :
            ["CREDITED", "COMMITTED", "SUCCESS"].includes(status) ? "text-success" :
            ["RELEASED", "FAILED", "REJECTED"].includes(status) ? "text-danger" : "text-warning";

        return `
            <div class="recovery-bank-card">
                <div class="d-flex justify-content-between align-items-start gap-2">
                    <div class="bank-heading">${esc(label)}</div>
                    <span class="badge bg-light text-dark border">${esc(bankName)}</span>
                </div>
                <div class="bank-state ${statusClass}">${esc(statusLabel)}</div>
                <div class="small recovery-muted">
                    <div>Account: <span class="text-body">${esc(state?.account_id || "—")}</span></div>
                    <div>Amount: <span class="text-body">${esc(state?.amount ?? "—")} ${esc(state?.currency || "")}</span></div>
                    ${state?.transaction_id ? `<div>Transaction: <span class="text-body">${esc(state.transaction_id)}</span></div>` : ""}
                </div>
            </div>`;
    }

    function stepTone(status) {
        const value = String(status || "").toUpperCase();
        if (["SUCCESS", "COMPLETED", "SUCCEEDED"].includes(value)) return "success";
        if (["FAILED", "ERROR", "REJECTED"].includes(value)) return "failed";
        if (["RUNNING", "IN_PROGRESS", "PROCESSING"].includes(value)) return "running";
        return "";
    }

    function renderTimeline(steps) {
        if (!steps.length) {
            return `<div class="text-muted small border rounded p-3">No Saga execution steps have been recorded.</div>`;
        }

        return `<div class="recovery-timeline">
            ${steps.map((step, index) => {
                const tone = stepTone(step.status);
                const stepName = String(step.step_name || `Step ${index + 1}`).replaceAll("_", " ");
                return `
                    <div class="recovery-timeline-item">
                        <span class="recovery-timeline-marker ${tone}"></span>
                        <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                            <div class="fw-semibold">${esc(stepName)}</div>
                            <div>${badge(step.status)}</div>
                        </div>
                        <div class="small recovery-muted mt-1">
                            Attempt ${esc(step.attempt_count ?? "—")}
                            <span class="mx-1">·</span> Started: ${esc(date(step.started_at))}
                            <span class="mx-1">·</span> Completed: ${esc(date(step.completed_at))}
                        </div>
                        ${step.error_message ? `
                            <div class="alert alert-danger py-2 px-3 mt-2 mb-0 small">
                                <strong>Step error:</strong> ${esc(step.error_message)}
                            </div>` : ""}
                    </div>`;
            }).join("")}
        </div>`;
    }

    async function inspect(id) {
        selectedTransferId = id;
        document.getElementById("recovery-detail-id").textContent = id;
        document.getElementById("recovery-detail-content").innerHTML =
            `<div class="text-center py-5 text-muted"><span class="spinner-border spinner-border-sm me-2"></span>Checking coordinator and bank transaction states...</div>`;
        document.getElementById("manual-recovery-button").disabled = true;
        modal.show();

        try {
            const detailData = await request(
                `/recovery/monitoring/api/${encodeURIComponent(id)}/`
            );

            const info = detailData.recovery_inspection || {};
            const transfer = detailData.transfer || {};
            selectedTransferStatus = transfer.status;
            selectedDeadLetteredAt = transfer.dead_lettered_at || null;
            selectedRecoveryDeadline = transfer.recovery_deadline || info.recovery_deadline || null;

            const steps = detailData.execution_history || [];
            const leaseUntil = info.recovery_lease_until;
            const deadline = selectedRecoveryDeadline;
            const bankError = detailData.bank_inspection_error;
            const issue = transfer.failure_reason || bankError || "";

            const detailHtml = `
                <div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3">
                    <div>
                        <div class="small text-muted mb-1">Transfer status</div>
                        ${badge(transfer.status)}
                    </div>
                    <div class="text-end">
                        <div class="small text-muted mb-1">Retry attempts</div>
                        <div class="fw-bold fs-5">${esc(transfer.retry_count ?? "—")} <span class="text-muted fw-normal fs-6">/ ${esc(transfer.max_retries ?? "—")}</span></div>
                    </div>
                </div>

                <div class="row g-3 mb-4">
                    <div class="col-md-6">${renderBankState("Bank A transaction state", info.bank_a, "Bank A")}</div>
                    <div class="col-md-6">${renderBankState("Bank B transaction state", info.bank_b, "Bank B")}</div>
                </div>

                <div class="row g-3 mb-4">
                    <div class="col-md-4"><div class="recovery-metric-card"><div class="metric-label">Current Saga step</div><div class="metric-value">${esc(String(transfer.current_step || info.current_step || "—").replaceAll("_", " "))}</div></div></div>
                    <div class="col-md-4"><div class="recovery-metric-card"><div class="metric-label">Recovery lease until</div><div class="metric-value">${esc(date(leaseUntil))}</div></div></div>
                    <div class="col-md-4"><div class="recovery-metric-card"><div class="metric-label">Recovery deadline</div><div class="metric-value">${esc(date(deadline))}</div></div></div>
                </div>

                ${bankError ? `<div class="alert alert-warning d-flex gap-2 align-items-start"><i data-feather="alert-triangle" class="mt-1 flex-shrink-0"></i><div><strong>Bank reconciliation unavailable</strong><div class="small mt-1">The coordinator record and Saga history are shown, but one or both bank services could not be inspected. Verify bank service availability before taking recovery action.</div></div></div>` : ""}

                ${issue ? `<div class="border rounded p-3 mb-4">
                    <div class="d-flex align-items-center gap-2 mb-2"><i data-feather="alert-circle" class="text-warning"></i><strong>Last recorded issue</strong></div>
                    <div class="small text-body">${esc(issue.length > 260 ? issue.slice(0, 260) + "…" : issue)}</div>
                    ${issue.length > 260 ? `<details class="mt-2"><summary class="small text-primary" style="cursor:pointer">Show full technical error</summary><pre class="recovery-error-text bg-light rounded p-2 mt-2 mb-0">${esc(issue)}</pre></details>` : ""}
                </div>` : ""}

                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div><h6 class="fw-bold mb-1">Saga execution timeline</h6><div class="small text-muted">Recorded steps and their execution outcomes</div></div>
                    <span class="badge bg-light text-dark border">${steps.length} step${steps.length === 1 ? "" : "s"}</span>
                </div>
                ${renderTimeline(steps)}
            `;

            document.getElementById("recovery-detail-content").innerHTML = detailHtml;

            const now = Date.now();
            const deadlineMs = deadline ? new Date(deadline).getTime() : 0;
            const leaseMs = leaseUntil ? new Date(leaseUntil).getTime() : 0;
            const isTerminal = ["COMPLETED", "FAILED"].includes(transfer.status);
            const leaseActive = leaseMs > now;
            const deadlineExpired = deadlineMs > 0 && deadlineMs <= now;
            const canAttempt = !isTerminal && !deadlineExpired && !leaseActive && !bankError;

            const recoveryButton = document.getElementById("manual-recovery-button");
            recoveryButton.disabled = !canAttempt;
            recoveryButton.title = bankError ? "Bank reconciliation must be available before manual recovery." :
                leaseActive ? "A recovery worker currently holds the recovery lease." :
                deadlineExpired ? "The recovery deadline has expired; this case requires review." :
                isTerminal ? "This transfer is already in a terminal state." : "";

            if (window.feather) window.feather.replace();
        } catch (error) {
            document.getElementById("recovery-detail-content").innerHTML =
                `<div class="alert alert-danger mb-0"><strong>Unable to load recovery inspection.</strong><div class="small mt-1">${esc(error.message)}</div></div>`;
            document.getElementById("manual-recovery-button").disabled = true;
        }
    }

    tbody.addEventListener("click", event => {
        const button = event.target.closest(".inspect-recovery");
        if (button) inspect(button.dataset.id);
    });

    document.getElementById("apply-recovery-filter").addEventListener("click", () => {
        currentPage = 1;
        loadCases();
    });

    document.getElementById("recovery-search").addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            currentPage = 1;
            loadCases();
        }
    });

    document.getElementById("recovery-bucket").addEventListener("change", () => {
        currentPage = 1;
        loadCases();
    });

    document.getElementById("refresh-recovery").addEventListener("click", () => loadCases());

    document.getElementById("recovery-next").addEventListener("click", () => {
        if (!nextUrl) return;
        currentPage += 1;
        loadCases(nextUrl);
    });

    document.getElementById("recovery-previous").addEventListener("click", () => {
        if (!previousUrl) return;
        currentPage = Math.max(1, currentPage - 1);
        loadCases(previousUrl);
    });

    document.getElementById("manual-recovery-button").addEventListener("click", async () => {
        if (!selectedTransferId) return;

        const confirmed = window.confirm(
            "Attempt recovery for this transfer? The system will first reconcile Bank A and Bank B transaction records. Do not use this action to bypass reconciliation."
        );
        if (!confirmed) return;

        const button = document.getElementById("manual-recovery-button");
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Processing...';

        try {
            const result = await request(
                `/transfers/${encodeURIComponent(selectedTransferId)}/recovery/`,
                { method: "POST" }
            );
            const data = result.data || {};
            alert(data.message || "Recovery request processed.");
            await inspect(selectedTransferId);
            await loadCases();
        } catch (error) {
            alert(error.message);
            button.disabled = false;
            button.innerHTML = '<i data-feather="refresh-cw" class="me-1"></i> Attempt recovery';
            if (window.feather) window.feather.replace();
        }
    });

    loadCases();
})();
