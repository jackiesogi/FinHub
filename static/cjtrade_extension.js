/**
 * FinHub × CJTrade Extension
 * ===========================
 * Polls the CJTrade lightweight API server (default: http://localhost:8899)
 * once per minute and refreshes only the affected DOM sections without
 * triggering a full-page reload.
 *
 * Design goals
 * ------------
 * - Zero full-page refresh.  Only the "Assets" holdings table and summary
 *   cards are updated when new data arrives.
 * - Auth is simple: login once on page load, store the CJTrade bearer token
 *   in sessionStorage.  Any username is accepted by CJTrade for now.
 * - The extension overrides the stub functions `loadHoldings()` and
 *   `syncWithCJTrade()` that already exist in script_responsive.js.
 */

const CJTRADE_BASE_URL = 'http://localhost:8899';
const CJTRADE_TOKEN_KEY = 'cjtrade_token';
const CJTRADE_POLL_INTERVAL_MS = 60_000;   // 1 minute

let _cjtradePollingTimer = null;

// ── Auth ─────────────────────────────────────────────────────────────────────

/**
 * Obtain a CJTrade bearer token and cache it in sessionStorage.
 * CJTrade accepts any username; we reuse the FinHub username when available.
 */
async function cjtradeLogin() {
    const fhUsername = _getFinHubUsername();
    try {
        const res = await fetch(`${CJTRADE_BASE_URL}/api/v1/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: fhUsername }),
        });
        if (!res.ok) throw new Error(`CJTrade login failed: ${res.status}`);
        const data = await res.json();
        sessionStorage.setItem(CJTRADE_TOKEN_KEY, data.access_token);
        console.log(`[CJTrade] Authenticated as ${data.username}`);
        return data.access_token;
    } catch (err) {
        console.warn('[CJTrade] Login error:', err.message);
        return null;
    }
}

/** Get a valid token, logging in first if needed. */
async function _cjtradeToken() {
    let token = sessionStorage.getItem(CJTRADE_TOKEN_KEY);
    if (!token) token = await cjtradeLogin();
    return token;
}

/** Extract the current FinHub username from localStorage (set on login). */
function _getFinHubUsername() {
    try {
        const raw = localStorage.getItem('token');
        if (!raw) return 'anonymous';
        // JWT payload is the second segment
        const payload = JSON.parse(atob(raw.split('.')[1]));
        return payload.sub || 'anonymous';
    } catch {
        return 'anonymous';
    }
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function _cjtradeGet(path) {
    const token = await _cjtradeToken();
    const res = await fetch(`${CJTRADE_BASE_URL}${path}`, {
        headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`CJTrade GET ${path} → ${res.status}`);
    return res.json();
}

// ── Data fetchers (partial DOM update) ───────────────────────────────────────

/**
 * Fetch current positions from CJTrade and update the Assets holdings table
 * and summary cards — without touching any other part of the page.
 */
async function fetchCJTradePositions() {
    try {
        const holdings = await _cjtradeGet('/api/v1/positions');
        updateHoldingsUI(holdings.map(p => ({
            symbol:       p.symbol,
            quantity:     p.quantity,
            avgCost:      p.avg_cost,
            currentPrice: p.current_price,
            value:        p.market_value,
            unrealizedPnL: p.unrealized_pnl,
        })));
    } catch (err) {
        console.warn('[CJTrade] fetchCJTradePositions error:', err.message);
    }
}

/**
 * Fetch account summary from CJTrade and update the "last updated" timestamp.
 * Does NOT override the FinHub KPI cards (balance/income/expense) — those
 * come from FinHub's own database.
 */
async function fetchCJTradeAccount() {
    try {
        const data = await _cjtradeGet('/api/v1/account');
        const timeStr = new Date().toLocaleTimeString();
        const el = document.getElementById('lastUpdateTime');
        if (el) el.textContent = `${timeStr}  (equity $${data.equity?.toLocaleString() ?? '—'}, P&L ${data.pnl >= 0 ? '+' : ''}$${data.pnl?.toLocaleString() ?? '—'})`;
    } catch (err) {
        console.warn('[CJTrade] fetchCJTradeAccount error:', err.message);
    }
}

// ── Polling ───────────────────────────────────────────────────────────────────

/**
 * Start 1-minute auto-refresh of the Assets section.
 * Safe to call multiple times — it cancels any existing timer first.
 */
function startCJTradePolling() {
    if (_cjtradePollingTimer) {
        clearInterval(_cjtradePollingTimer);
    }
    // Immediate first fetch
    _cjtradePartialRefresh();
    _cjtradePollingTimer = setInterval(_cjtradePartialRefresh, CJTRADE_POLL_INTERVAL_MS);
    console.log(`[CJTrade] Polling started (every ${CJTRADE_POLL_INTERVAL_MS / 1000}s)`);
}

function stopCJTradePolling() {
    if (_cjtradePollingTimer) {
        clearInterval(_cjtradePollingTimer);
        _cjtradePollingTimer = null;
        console.log('[CJTrade] Polling stopped');
    }
}

async function _cjtradePartialRefresh() {
    await Promise.all([
        fetchCJTradePositions(),
        fetchCJTradeAccount(),
    ]);
}

// ── Override stubs from script_responsive.js ─────────────────────────────────

/**
 * Replace the mock-data stub in script_responsive.js with a real API call.
 * Called by initAssetsSection() when the user navigates to the Assets page.
 */
async function loadHoldings() {
    await fetchCJTradePositions();
    await fetchCJTradeAccount();
}

/**
 * Replace the no-op stub — full manual sync triggered by the "Sync CJTrade" button.
 */
async function syncWithCJTrade() {
    console.log('[CJTrade] Manual sync triggered');
    await _cjtradePartialRefresh();
}

// ── Reset & Sync ──────────────────────────────────────────────────────────────

/**
 * Clear the selected account's transaction history and re-import from CJTrade.
 *
 * Uses the currently selected account from the header dropdown, or prompts
 * the user to select one if "ALL ACCOUNTS" is selected.
 */
async function resetAndSyncCJTrade() {
    // Resolve target account from the header filter dropdown
    const select = document.getElementById('headerAccountFilter');
    const accountId = select ? select.value : 'all';

    if (!accountId || accountId === 'all') {
        alert('Please select a specific account from the dropdown before syncing.');
        return;
    }

    const confirmed = confirm(
        '⚠️  This will DELETE all transactions for the selected account\n' +
        'and re-import data from CJTrade.\n\n' +
        'Continue?'
    );
    if (!confirmed) return;

    const fhToken = localStorage.getItem('token');
    if (!fhToken) { alert('Not logged in.'); return; }

    try {
        const res = await fetch(
            `/api/v1/cjtrade/sync/${accountId}?cjtrade_url=${encodeURIComponent(CJTRADE_BASE_URL)}`,
            {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${fhToken}` },
            }
        );
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || res.statusText);

        alert(
            `✅ Sync complete!\n` +
            `Mode: ${data.launch_mode}\n` +
            `Imported: ${data.imported} entries\n` +
            `New balance: $${data.new_balance?.toLocaleString()}`
        );

        // Refresh the dashboard data
        if (typeof refreshDataSync === 'function') {
            await refreshDataSync(parseInt(accountId));
        }
    } catch (err) {
        alert(`Sync failed: ${err.message}`);
        console.error('[CJTrade] resetAndSyncCJTrade error:', err);
    }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

/**
 * Kick everything off once the page is ready.
 * Login happens here so the token is cached before any data request.
 */
document.addEventListener('DOMContentLoaded', async () => {
    // Only init when FinHub user is logged in
    if (!localStorage.getItem('token')) return;

    await cjtradeLogin();
    startCJTradePolling();

    // Stop polling when the user leaves (avoid ghost requests after logout)
    window.addEventListener('beforeunload', stopCJTradePolling);
});
