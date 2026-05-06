/**
 * FINTECH HUB - FULL CORE ENGINE (STABLE V3)
 * NO LOGIC REMOVED. Enhanced to maintain account filter context after CRUD operations.
 */

// --- [1] GLOBAL STATE & CONSTANTS ---
const token = localStorage.getItem('token');
let categoryChart = null, trendChart = null;
let allAccounts = [];
let currentSort = 'date_desc';
let editingTxId = null;

// PAGINATION STATE
let currentPage = 1;
const pageSize = 10;
let totalVisibleTxs = []; // CRITICAL: Cache for index-based editing/deleting

// --- [2] AUTH & ROUTE GUARD ---
function checkAuth() {
    const path = window.location.pathname;
    if (!token && !path.includes('login') && !path.includes('register')) {
        window.location.href = '/login';
        return false;
    }
    return true;
}

// --- [3] UI NAVIGATION ---
function showSection(name) {
    const dash = document.getElementById('section-dashboard');
    const audit = document.getElementById('section-audit');
    const navDash = document.getElementById('nav-dashboard');
    const navAudit = document.getElementById('nav-audit');

    if (name === 'dashboard') {
        dash.classList.remove('hidden'); audit.classList.add('hidden');
        navDash.classList.add('bg-slate-100', 'text-slate-950');
        navAudit.classList.remove('bg-slate-100', 'text-slate-950');
    } else {
        dash.classList.add('hidden'); audit.classList.remove('hidden');
        navAudit.classList.add('bg-slate-100', 'text-slate-950');
        navDash.classList.remove('bg-slate-100', 'text-slate-950');
        fetchAuditLogs();
    }
}

// --- [4] API DATA SYNCHRONIZATION ---
async function applyFilter() {
    if (!token) return;
    const accId = document.getElementById('headerAccountFilter').value;
    const start = document.getElementById('startDate').value;
    const end = document.getElementById('endDate').value;

    let url = `/api/v1/transactions?page=${currentPage}&size=${pageSize}&sort_by=${currentSort}&`;
    if (accId !== 'all') url += `account_id=${accId}&`;
    if (start) url += `start_date=${start}&`;
    if (end) url += `end_date=${end}`;

    try {
        const res = await fetch(url, { headers: { 'Authorization': `Bearer ${token}` } });
        if (!res.ok) throw new Error(`Fetch failed with status: ${res.status}`);

        const data = await res.json();
        const txList = Array.isArray(data) ? data : (data.items || []);
        totalVisibleTxs = txList;

        renderTable(txList);
        updatePaginationUI(data);

        const dashUrl = `/api/v1/dashboard${accId !== 'all' ? `?account_id=${accId}` : ''}`;
        const dashRes = await fetch(dashUrl, { headers: { 'Authorization': `Bearer ${token}` } });
        const summary = await dashRes.json();

        updateKPIs(summary);
        renderBar(summary.total_income || 0, summary.total_expense || 0);
        renderCategoryChart(generateCategoryData(txList));
    } catch (err) {
        console.error("Sync Error:", err);
    }
}

/**
 * REFRESH DATA SYNC
 * Fetches latest accounts and transactions while preserving the current account selection.
 */
async function refreshDataSync(targetId) {
    try {
        const acctRes = await fetch('/api/v1/accounts', { headers: { 'Authorization': `Bearer ${token}` } });
        allAccounts = await acctRes.json();

        // Update UI but force the previous active ID to stay selected
        updateAccountUI(allAccounts, targetId);

        // Execute the filter to refresh the table for that specific ID
        await applyFilter();
    } catch (err) { console.error("Refresh Error:", err); }
}

async function fetchAuditLogs() {
    const tbody = document.getElementById('auditLogTable');
    tbody.innerHTML = `<tr><td colspan="4" class="px-8 py-10 text-center text-slate-400 italic">Syncing trail...</td></tr>`;
    try {
        const res = await fetch('/api/v1/audit-logs', { headers: { 'Authorization': `Bearer ${token}` } });
        const logs = await res.json();
        tbody.innerHTML = logs.map(log => {
            const date = new Date(log.timestamp).toLocaleString();
            return `<tr class="border-b border-slate-50"><td class="px-8 py-4 text-xs font-mono text-slate-400">${date}</td><td class="px-8 py-4 uppercase text-[10px] font-bold text-indigo-500">${log.action}</td><td class="px-8 py-4 text-xs">#${log.target_id||'SYS'}</td><td class="px-8 py-4 text-sm">${log.details}</td></tr>`;
        }).join('');
    } catch (err) { tbody.innerHTML = `<tr><td colspan="4">Sync failed</td></tr>`; }
}

// --- [5] UI RENDERING ---
function renderTable(txs) {
    const tbody = document.getElementById('transactionTable');
    if (txs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="px-8 py-10 text-center text-slate-400 italic">Empty ledger slice.</td></tr>`;
        return;
    }
    tbody.innerHTML = txs.map((tx, idx) => {
        const isTransfer = tx.category?.toUpperCase() === 'TRANSFER';
        const amtClass = tx.transaction_type === 'income' ? 'text-emerald-600' : 'text-rose-500';
        return `
            <tr class="hover:bg-slate-50 border-b border-slate-50 last:border-0">
                <td class="px-8 py-4 text-xs font-medium text-slate-400">${new Date(tx.date).toLocaleDateString()}</td>
                <td class="px-8 py-4 text-sm font-bold text-slate-700">${tx.description}</td>
                <td class="px-8 py-4"><span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-100 text-slate-500 uppercase">${tx.category}</span></td>
                <td class="px-8 py-4 text-right font-mono font-bold ${amtClass}">${tx.transaction_type==='income'?'+':'-'}$${tx.amount.toLocaleString()}</td>
                <td class="px-8 py-4 text-right space-x-3">
                    ${isTransfer ?
                        `<span class="text-[10px] font-bold text-slate-300 italic">Locked</span>` :
                        `<button onclick="handleEditClick(${idx})" class="text-[10px] font-black text-indigo-600 hover:text-indigo-900 uppercase transition-all">Edit</button>`
                    }
                    <button onclick="deleteTx(${tx.id})" class="text-[10px] font-black text-rose-400 hover:text-rose-600 uppercase transition-all">Delete</button>
                </td>
            </tr>`;
    }).join('');
}

function updateKPIs(data) {
    document.getElementById('statBalance').innerText = `$${(data.balance || 0).toLocaleString()}`;
    document.getElementById('statIncome').innerText = `+$${(data.total_income || 0).toLocaleString()}`;
    document.getElementById('statExpense').innerText = `-$${(data.total_expense || 0).toLocaleString()}`;
}

function updatePaginationUI(data) {
    const pageInfo = document.getElementById('pageInfo');
    const curr = data.page || 1;
    const total = data.total_pages || 1;
    if(pageInfo) pageInfo.innerText = `Page ${curr} of ${total}`;
    document.getElementById('prevBtn').disabled = (curr <= 1);
    document.getElementById('nextBtn').disabled = (curr >= total);
}

function changePage(step) {
    currentPage += step;
    applyFilter();
}

function toggleSort(f) {
    currentSort = (currentSort === f + '_desc') ? f + '_asc' : f + '_desc';
    applyFilter();
}

// --- [6] DATA VISUALIZATION ---
function generateCategoryData(txs) {
    const cats = {};
    txs.filter(t => t.transaction_type === 'expense' && t.category?.toUpperCase() !== 'TRANSFER').forEach(t => {
        cats[t.category || 'General'] = (cats[t.category || 'General'] || 0) + t.amount;
    });
    return Object.keys(cats).map(k => ({ category: k, amount: cats[k] }));
}

function renderCategoryChart(data) {
    const ctx = document.getElementById('categoryChart').getContext('2d');
    if (categoryChart) categoryChart.destroy();
    categoryChart = new Chart(ctx, { type: 'doughnut', data: { labels: data.map(d => d.category), datasets: [{ data: data.map(d => d.amount), backgroundColor: ['#0f172a', '#6366f1', '#10b981', '#f43f5e', '#f59e0b'], borderWidth: 0 }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '80%', plugins: { legend: { position: 'bottom', labels: { boxWidth: 8, font: { size: 10, weight: 'bold' } } } } } });
}

function renderBar(inc, exp) {
    const ctx = document.getElementById('trendChart').getContext('2d');
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(ctx, { type: 'bar', data: { labels: ['Summary'], datasets: [{ label: 'Income', data: [inc], backgroundColor: '#10b981', borderRadius: 6 }, { label: 'Expense', data: [exp], backgroundColor: '#cbd5e1', borderRadius: 6 }] }, options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true }, x: { grid: { display: false } } } } });
}

// --- [7] TRANSACTION & FORM HANDLERS ---
function handleEditClick(index) {
    const tx = totalVisibleTxs[index];
    editingTxId = tx.id;
    document.getElementById('accountSelect').value = tx.account_id;
    document.getElementById('txDate').value = tx.date.split('T')[0];
    document.getElementById('desc').value = tx.description;
    document.getElementById('amt').value = tx.amount;
    document.getElementById('type').value = tx.transaction_type;
    document.getElementById('cat').value = tx.category;
    document.getElementById('modalTitle').innerText = "Edit Ledger Entry";
    document.getElementById('submitTxBtn').innerText = "Update Transaction";
    toggleModal();
}

/**
 * TRANSACTION SUBMISSION
 * Corrected: Now captures the active account filter before saving,
 * ensuring the user stays on the same account view after the refresh.
 */
document.getElementById('transactionForm').onsubmit = async (e) => {
    e.preventDefault();
    const currentActive = document.getElementById('headerAccountFilter').value;

    const amtValue = parseFloat(document.getElementById('amt').value);
    if (isNaN(amtValue) || amtValue <= 0) {
        alert("請輸入大於 0 的合法金額！"); // 擋住負數與 0
        document.getElementById('amt').focus();
        return;
    }

    const payload = {
        account_id: parseInt(document.getElementById('accountSelect').value),
        description: document.getElementById('desc').value,
        amount: parseFloat(document.getElementById('amt').value),
        category: document.getElementById('cat').value || "General",
        transaction_type: document.getElementById('type').value,
        date: document.getElementById('txDate').value
    };

    const method = editingTxId ? 'PUT' : 'POST';
    const url = editingTxId ? `/api/v1/transactions/${editingTxId}` : '/api/v1/transactions';

    const res = await fetch(url, {
        method,
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (res.ok) {
        toggleModal();
        editingTxId = null;
        document.getElementById('transactionForm').reset();
        // Sycn state without jumping back to 'all'
        await refreshDataSync(currentActive);
    }
};

document.getElementById('transferForm').onsubmit = async (e) => {
    e.preventDefault();
    const currentActive = document.getElementById('headerAccountFilter').value;
    const fromAccId = document.getElementById('fromAccSelect').value;
    const toAccId = document.getElementById('toAccSelect').value;
    const amountVal = document.getElementById('transferAmt').value;
    const descVal = document.getElementById('transferDesc').value;

    if (!fromAccId || !toAccId || !amountVal) { alert("Please complete all fields."); return; }

    const payload = {
        from_account_id: parseInt(fromAccId),
        to_account_id: parseInt(toAccId),
        amount: parseFloat(amountVal),
        description: descVal || "Internal Transfer",
        date: new Date().toISOString().split('T')[0]
    };

    try {
        const res = await fetch('/api/v1/transfers', { method: 'POST', headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (res.ok) {
            toggleTransferModal();
            document.getElementById('transferForm').reset();
            await refreshDataSync(currentActive);
        } else {
            const errData = await res.json();
            alert(`Transfer Failed: ${errData.detail || "Error"}`);
        }
    } catch (err) { console.error("Transfer Error:", err); }
};

document.getElementById('accountForm').onsubmit = async (e) => {
    e.preventDefault();
    const payload = { name: document.getElementById('accName').value, balance: parseFloat(document.getElementById('accBalance').value) };
    const res = await fetch('/api/v1/accounts', { method: 'POST', headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (res.ok) { toggleAccountModal(); document.getElementById('accountForm').reset(); initDashboard(); }
};

async function deleteTx(id) {
    if (confirm("Delete this?")) {
        const currentActive = document.getElementById('headerAccountFilter').value;
        const res = await fetch(`/api/v1/transactions/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
        if (res.ok) await refreshDataSync(currentActive);
    }
}

function exportCSV() {
    let csv = "Date,Description,Category,Amount,Type\n";
    totalVisibleTxs.forEach(t => csv += `${t.date},${t.description},${t.category},${t.amount},${t.transaction_type}\n`);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'ledger_export.csv'; a.click();
}

// --- [8] INITIALIZATION & SIDEBAR ---
function selectAccountFromSidebar(id) {
    const filterSelect = document.getElementById('headerAccountFilter');
    if (filterSelect) {
        filterSelect.value = id;
        currentPage = 1;
        applyFilter();
        updateAccountUI(allAccounts, id);
    }
}

/**
 * SIDEBAR AND DROPDOWN RENDERING
 * Enhanced to support 'activeId' highlighting and persistent filter state.
 */
function updateAccountUI(accounts, activeId = 'all') {
    const sidebar = document.getElementById('accountBalances');
    const filterSelect = document.getElementById('headerAccountFilter');

    // Maintain the active filter logic
    const currentActive = activeId || filterSelect.value;

    sidebar.innerHTML = accounts.map(a => {
        const isActive = String(currentActive) === String(a.id);
        const bgClass = isActive ? 'bg-slate-200 ring-1 ring-slate-300' : 'hover:bg-white';

        return `
            <div onclick="selectAccountFromSidebar('${a.id}')"
                 class="group flex justify-between items-center p-2.5 rounded-xl transition-all cursor-pointer ${bgClass}">
                <div class="flex flex-col">
                    <span class="text-slate-900 font-bold text-xs truncate w-24">${a.name}</span>
                    <span class="text-[11px] font-black text-slate-500">$${a.balance.toLocaleString()}</span>
                </div>

                <button onclick="event.stopPropagation(); deleteAccount(${a.id})"
                        class="opacity-0 group-hover:opacity-100 px-2 py-1 text-[10px] font-black text-rose-400 hover:text-rose-600 uppercase transition-all">
                    Delete
                </button>
            </div>`;
    }).join('');

    filterSelect.innerHTML = '<option value="all">ALL ACCOUNTS</option>' + accounts.map(a => `<option value="${a.id}">${a.name.toUpperCase()}</option>`).join('');
    filterSelect.value = currentActive;

    document.getElementById('accountSelect').innerHTML = accounts.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
}

async function initDashboard() {
    if (!checkAuth()) return;
    try {
        const acctRes = await fetch('/api/v1/accounts', { headers: { 'Authorization': `Bearer ${token}` } });
        if (acctRes.status === 401) { logout(); return; }
        allAccounts = await acctRes.json();
        updateAccountUI(allAccounts, 'all');
        applyFilter();
        document.getElementById('currentUserDisplay').innerText = `Active Session`;


        await fetchAdminStats();

    } catch (err) { console.error("Init Error", err); }
}

function toggleModal() {
    document.getElementById('modal').classList.toggle('opacity-0');
    document.getElementById('modal').classList.toggle('pointer-events-none');
    // Reset modal title if closing
    if (document.getElementById('modal').classList.contains('opacity-0')) {
        document.getElementById('modalTitle').innerText = "New Ledger Entry";
        document.getElementById('submitTxBtn').innerText = "Confirm Entry";
        document.getElementById('transactionForm').reset();
        editingTxId = null;
    }
}
function toggleAccountModal() { document.getElementById('accountModal').classList.toggle('opacity-0'); document.getElementById('accountModal').classList.toggle('pointer-events-none'); }
function toggleTransferModal() {
    const m = document.getElementById('transferModal');
    m.classList.toggle('opacity-0'); m.classList.toggle('pointer-events-none');
    if (!m.classList.contains('opacity-0')) {
        const options = allAccounts.map(a => `<option value="${a.id}">${a.name} ($${a.balance})</option>`).join('');
        document.getElementById('fromAccSelect').innerHTML = options;
        document.getElementById('toAccSelect').innerHTML = options;
    }
}

function logout() { localStorage.removeItem('token'); window.location.href = '/login'; }

window.onload = initDashboard;

async function deleteAccount(id) {
    if (confirm("刪除帳號會連同該帳號的交易紀錄一併刪除，確定嗎？")) {
        const res = await fetch(`/api/v1/accounts/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            initDashboard();
        } else {
            const err = await res.json();
            alert(`刪除失敗: ${err.detail}`);
        }
    }
}

/**
 * ADMIN ENGINE: Fetches system-wide user statistics.
 * Only executes successfully if the logged-in user has admin rights.
 */
async function fetchAdminStats() {
    try {
        const res = await fetch('/api/v1/admin/users', {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (res.ok) {
            const users = await res.json();
            console.log("--- ADMIN SYSTEM REPORT ---");
            console.table(users); // Displays a neat table in your Browser Console (F12)

            // Optional: You can render this to a specific DIV in your HTML later
        } else {
            console.log("Access to Admin API restricted.");
        }
    } catch (err) {
        console.error("Admin Sync Error:", err);
    }
}

// [IMPORTANT] Add this call at the end of your existing initDashboard() function:
// await fetchAdminStats();
