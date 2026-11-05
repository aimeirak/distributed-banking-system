(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('new-transfer-form');
  if (!form) return;
  const source = $('source-account'), destination = $('destination-number');
  const amount = $('transfer-amount'), submit = $('submit-transfer');
  const verify = $('verify-receiver');
  let accounts = [], receiver = null, busy = false, pendingKey = null;
  const token = () => sessionStorage.getItem('banking_access_token');
 let alertTimer = null;
function alertMessage(message, type = "success") {
    const notification = $('transfer-notification');
    const title = $('notification-title');
    const messageElement = $('notification-message');
    const icon = $('notification-icon');

    if (!notification) {
        console.error("Notification element not found.");
        return;
    }

    if (alertTimer) {
        clearTimeout(alertTimer);
    }

    const config = {
        success: {
            title: 'Success!',
            icon: 'fa-check',
            color: '#16a34a',
            background: '#dcfce7'
        },
        danger: {
            title: 'Something went wrong',
            icon: 'fa-times',
            color: '#dc2626',
            background: '#fee2e2'
        },
        warning: {
            title: 'Attention',
            icon: 'fa-exclamation',
            color: '#d97706',
            background: '#fef3c7'
        },
        info: {
            title: 'Information',
            icon: 'fa-info',
            color: '#2563eb',
            background: '#dbeafe'
        }
    };

    const selected = config[type] || config.info;

    title.textContent = selected.title;
    messageElement.textContent = message;

    icon.innerHTML = `<i class="fas ${selected.icon}"></i>`;
    icon.style.color = selected.color;
    icon.style.background = selected.background;

    notification.style.borderLeftColor = selected.color;

    notification.classList.add('show');

    alertTimer = setTimeout(() => {
        closeTransferNotification();
    }, 20000);
}

function closeTransferNotification() {
    const notification = $('transfer-notification');

    if (notification) {
        notification.classList.remove('show');
    }

    if (alertTimer) {
        clearTimeout(alertTimer);
        alertTimer = null;
    }
}

function clearAlert() {
    closeTransferNotification();
}
  function csrf() { return form.querySelector('[name=csrfmiddlewaretoken]')?.value || ''; }
  async function api(url, options = {}) {
    const headers = { Accept: 'application/json', 'X-CSRFToken': csrf(), ...(options.headers || {}) };
    if (token()) headers.Authorization = `Bearer ${token()}`;
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers });
    let data;
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : (data.message || JSON.stringify(data));
      throw new Error(`HTTP ${response.status}: ${detail || 'Request failed'}`);
    }
    return data;
  }
  function selectedAccount() { return accounts.find(a => String(a.id) === source.value); }
  function update() {
    const a = selectedAccount();
    $('summary-from').textContent = a ? `${a.account_number} · ${a.customer_name}` : '—';
    $('summary-to').textContent = receiver ? `${receiver.customer_name} · ${receiver.account_number}` : '—';
    const n = Number(amount.value);
    $('summary-amount').textContent = `${Number.isFinite(n) && n > 0 ? n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0.00'} RWF`;
    $('source-balance').textContent = a ? `Balance: ${a.balance} ${a.currency}` : '';
    submit.disabled = busy || !a || !receiver || a.status !== 'ACTIVE' || receiver.currency !== 'RWF' || !(n > 0) || !Number.isFinite(n);
  }
  function resetReceiver() {
    receiver = null;
    $('receiver-panel').classList.add('d-none');
    update();
  }
  async function loadAccounts() {
    try {
      const data = await api('/accounts/source/');
      accounts = Array.isArray(data.accounts) ? data.accounts : [];
      source.innerHTML = '<option value="">Select your source account</option>';
      accounts.filter(a => a.status === 'ACTIVE' && a.currency === 'RWF').forEach(a => {
        const opt = document.createElement('option'); opt.value = a.id;
        opt.textContent = `${a.account_number} — ${a.customer_name} (${a.balance} RWF)`;
        source.appendChild(opt);
      });
      if (!source.options.length || source.options.length === 1) alertMessage('No active RWF accounts were found for your customer profile.', 'warning');
    } catch (err) {
      source.innerHTML = '<option value="">Unable to load accounts</option>';
      alertMessage(`Could not load source accounts. ${err.message}`);
    }
    update();
  }
  verify.addEventListener('click', async () => {
    resetReceiver(); clearAlert();
    const number = destination.value.trim();
    if (!number) { alertMessage('Enter the Bank B account number.'); return; }
    verify.disabled = true; verify.textContent = 'Verifying...';
    try {
      const data = await api(`/accounts/destination/verify/?account_number=${encodeURIComponent(number)}`);
      const a = data.account;
      if (!data.verified || !a?.account_id || !a?.account_number || !a?.customer_name || a.status !== 'ACTIVE' || a.currency !== 'RWF') throw new Error('Receiver account is not eligible for an RWF transfer.');
      if (destination.value.trim() !== number) return;
      receiver = a;
      $('receiver-name').textContent = a.customer_name;
      $('receiver-account').textContent = `${a.account_number} · Bank B · ${a.currency}`;
      $('receiver-panel').classList.remove('d-none');
    } catch (err) { alertMessage(`Receiver verification failed. ${err.message}`); }
    finally { verify.disabled = false; verify.textContent = 'Verify account'; update(); }
  });
  destination.addEventListener('input', resetReceiver);
  source.addEventListener('change', update);
  amount.addEventListener('input', update);
  form.addEventListener('submit', async event => {
    event.preventDefault(); clearAlert();
    const a = selectedAccount();
    if (busy || !a || !receiver) return;
    const n = Number(amount.value);
    if (!Number.isFinite(n) || n <= 0 || !/^\d+(\.\d{1,2})?$/.test(amount.value.trim())) { alertMessage('Enter a positive amount with at most two decimal places.'); return; }
    if (!confirm(`Send ${n.toFixed(2)} RWF from ${a.account_number} to ${receiver.customer_name} (${receiver.account_number})?`)) return;
    busy = true; update();
    if (!pendingKey) pendingKey = crypto.randomUUID();
    const payload = {
      idempotency_key: pendingKey,
      source_account_id: a.id,
      source_account_number: a.account_number,
      destination_account_id: receiver.account_id,
      destination_account_number: receiver.account_number,
      amount: n.toFixed(2),
      currency: 'RWF'
    };
    try {
      const result = await api('/transfers/', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      const id = result.id || result.transfer_id || result.transfer?.id;
      // alertMessage(`Transfer request accepted. Status: ${result.status || result.transfer?.status || 'Submitted'}${id ? `. Transfer ID: ${id}` : ''}.`, 'success');
      const status = result.status || result.transfer?.status || 'PENDING';

        if (status === 'COMPLETED') {
            alertMessage(
                'Your transfer has been successfully completed.',
                'success'
            );
        } else {
            alertMessage(
                'Your transfer request has been successfully submitted and is currently being processed. Please wait while we complete the transaction. You will be notified once the transfer is completed.',
                'success'
            );
        }
      pendingKey = null;
      form.reset(); resetReceiver();
    } catch (err) {
      alertMessage(`Transfer status is not confirmed: ${err.message}. Do not submit a new request with a different idempotency key until you check the transfer status.`);
    } finally { busy = false; update(); }
  });
  loadAccounts();
})();
