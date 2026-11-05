(() => {
  const form = document.getElementById("filterForm");
  const tbody = document.getElementById("ledgerRows");
  const errorBox = document.getElementById("ledgerError");
  let page = 1;
  let currentRows = [];
  let totalPages = 1;

  function params() {
    const p = new URLSearchParams(new FormData(form));
    p.set("page", page);
    p.set("page_size", 25);
    for (const [key, value] of [...p.entries()]) if (!value) p.delete(key);
    return p;
  }
  function money(value, currency) {
    return `${Number(value || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${currency || "RWF"}`;
  }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  async function load() {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">Loading...</td></tr>';
    errorBox.classList.add("d-none");
    try {
      const response = await fetch(`/transactions/api/?${params().toString()}`, {
        headers: {"X-Requested-With": "XMLHttpRequest"}
      });
      if (!response.ok) throw new Error(`Unable to load ledger (${response.status}).`);
      const data = await response.json();
      currentRows = data.results || [];
      totalPages = data.total_pages || 1;
      document.getElementById("sumReservation").textContent = money(data.summary?.RESERVATION);
      document.getElementById("sumDebit").textContent = money(data.summary?.DEBIT);
      document.getElementById("sumCredit").textContent = money(data.summary?.CREDIT);
      document.getElementById("sumRelease").textContent = money(data.summary?.RELEASE);
      if (!currentRows.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No ledger entries found.</td></tr>';
      } else {
        tbody.innerHTML = currentRows.map(r => `<tr>
          <td>${escapeHtml(r.created_at ? new Date(r.created_at).toLocaleString() : "")}</td>
          <td><span class="badge bg-light text-dark">${escapeHtml(r.bank)}</span></td>
          <td>${escapeHtml(r.account_number)}</td>
          <td><small>${escapeHtml(r.transfer_id)}</small></td>
          <td>${escapeHtml(r.entry_type)}</td>
          <td class="text-end fw-semibold">${money(r.amount, r.currency)}</td>
          <td>${escapeHtml(r.description)}</td>
        </tr>`).join("");
      }
      document.getElementById("pageInfo").textContent = `Page ${data.page} of ${Math.max(totalPages, 1)} · ${data.count} entries`;
      document.getElementById("previousPage").disabled = page <= 1;
      document.getElementById("nextPage").disabled = page >= totalPages;
      if (data.partial) {
        errorBox.textContent = `Some bank data could not be retrieved: ${(data.source_errors || []).map(e => `${e.bank}: ${e.message}`).join("; ")}`;
        errorBox.classList.remove("d-none");
      }
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-4">Could not load ledger entries.</td></tr>';
      errorBox.textContent = e.message;
      errorBox.classList.remove("d-none");
    }
  }
  form.addEventListener("submit", e => { e.preventDefault(); page = 1; load(); });
  form.addEventListener("reset", () => setTimeout(() => { page = 1; load(); }, 0));
  document.getElementById("previousPage").addEventListener("click", () => { if (page > 1) { page--; load(); } });
  document.getElementById("nextPage").addEventListener("click", () => { if (page < totalPages) { page++; load(); } });
  document.getElementById("exportCsv").addEventListener("click", () => {
    if (!currentRows.length) return;
    const cols = ["created_at","bank","account_number","transfer_id","entry_type","amount","currency","description"];
    const csv = [cols.join(","), ...currentRows.map(r => cols.map(k => `"${String(r[k] ?? "").replace(/"/g, '""')}"`).join(","))].join("\r\n");
    const blob = new Blob([csv], {type: "text/csv;charset=utf-8;"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "transaction-ledger-page.csv"; a.click();
    URL.revokeObjectURL(url);
  });
  load();
})();
