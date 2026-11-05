(() => {
  const rows = document.getElementById("sourceAccountRows");
  const alertBox = document.getElementById("accountAlert");
  const resultBox = document.getElementById("destinationResult");

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pick = (obj, keys, fallback = "—") => {
    for (const key of keys) if (obj?.[key] !== undefined && obj[key] !== null && obj[key] !== "") return obj[key];
    return fallback;
  };
  const unwrap = data => Array.isArray(data) ? data :
    (data?.accounts || data?.results || data?.data || []);
  function alert(message) { alertBox.className = "alert alert-danger"; alertBox.textContent = message; }

  async function loadAccounts() {
    alertBox.className = "alert d-none";
    rows.innerHTML = '<tr><td colspan="5" class="text-center py-4">Loading accounts...</td></tr>';
    try {
      const response = await fetch("/accounts/source/", {credentials:"same-origin", headers:{"Accept":"application/json"}});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || `Account request failed (${response.status}).`);
      const accounts = unwrap(data);
      document.getElementById("totalAccounts").textContent = accounts.length;
      document.getElementById("activeAccounts").textContent = accounts.filter(a =>
        ["ACTIVE","OPEN"].includes(String(pick(a,["status","account_status","state"],"")).toUpperCase())).length;
      document.getElementById("currencyCount").textContent =
        new Set(accounts.map(a => pick(a,["currency"],"")).filter(Boolean)).size;
      if (!accounts.length) {
        rows.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No accounts found for this customer.</td></tr>';
        return;
      }
      rows.innerHTML = accounts.map(a => {
        const currency = pick(a,["currency"]);
        const state = String(pick(a,["status","account_status","state"],"UNKNOWN")).toUpperCase();
        const badge = ["ACTIVE","OPEN"].includes(state) ? "success" : "secondary";
        return `<tr>
          <td class="fw-semibold">${esc(pick(a,["account_number","accountNumber"]))}</td>
          <td>${esc(pick(a,["account_name","name","holder_name","customer_name"]))}</td>
          <td>${esc(currency)}</td>
          <td class="text-end">${esc(pick(a,["available_balance","balance","availableBalance"],"0.00"))} ${esc(currency === "—" ? "" : currency)}</td>
          <td><span class="badge bg-${badge}">${esc(state)}</span></td>
        </tr>`;
      }).join("");
    } catch (e) {
      rows.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-4">Unable to load accounts.</td></tr>';
      alert(e.message);
    }
  }

  document.getElementById("refreshAccounts").addEventListener("click", loadAccounts);
  document.getElementById("destinationLookupForm").addEventListener("submit", async event => {
    event.preventDefault();
    resultBox.innerHTML = '<div class="text-muted">Verifying account...</div>';
    const number = document.getElementById("destinationAccountNumber").value.trim();
    const button = document.getElementById("verifyDestinationButton");
    button.disabled = true;
    try {
      const response = await fetch(`/accounts/destination/verify/?account_number=${encodeURIComponent(number)}`,
        {credentials:"same-origin", headers:{"Accept":"application/json"}});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.verified) throw new Error(data.message || "Destination account was not verified.");
      const a = data.account || {};
      resultBox.innerHTML = `<div class="alert alert-success mb-0">
        <strong>Destination account verified</strong>
        <div>Account number: ${esc(pick(a,["account_number","accountNumber"],number))}</div>
        <div>Account name: ${esc(pick(a,["account_name","name","holder_name","customer_name"]))}</div>
        <div>Currency: ${esc(pick(a,["currency"]))}</div>
        <div>Status: ${esc(pick(a,["status","account_status"],"Verified"))}</div>
      </div>`;
    } catch (e) {
      resultBox.innerHTML = `<div class="alert alert-warning mb-0">${esc(e.message)}</div>`;
    } finally { button.disabled = false; }
  });
  loadAccounts();
})();
