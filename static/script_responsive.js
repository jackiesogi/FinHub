/* ===== RESPONSIVE UI UTILITIES ===== */

/**
 * 切換側邊欄（移動設備）
 */
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    sidebar.classList.toggle('active');
    overlay.classList.toggle('active');

    // 防止頁面滾動
    document.body.style.overflow = sidebar.classList.contains('active') ? 'hidden' : 'auto';
}

/**
 * 切換側邊欄（桌面設備）
 */
function toggleSidebarDesktop() {
    const sidebar = document.getElementById('sidebar');

    // 在桌面上，我們改變寬度而不是完全隱藏
    if (sidebar.classList.contains('collapsed')) {
        sidebar.classList.remove('collapsed');
        localStorage.setItem('sidebarCollapsed', 'false');
    } else {
        sidebar.classList.add('collapsed');
        localStorage.setItem('sidebarCollapsed', 'true');
    }
}

/**
 * 關閉側邊欄（當用戶點擊時）
 */
function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (sidebar.classList.contains('active')) {
        sidebar.classList.remove('active');
        overlay.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

/**
 * 監聽視窗大小變化
 */
window.addEventListener('resize', () => {
    if (window.innerWidth >= 1024) {
        // 大屏時自動關閉側邊欄
        closeSidebar();
    }
});

/**
 * 切換模態框（帶響應式支持）
 */
function toggleModal() {
    const modal = document.getElementById('modal');

    if (!modal.classList.contains('active')) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';

        // 設定今天的日期
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('txDate').value = today;
    } else {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

/**
 * 切換帳戶模態框
 */
function toggleAccountModal() {
    const modal = document.getElementById('accountModal');

    if (!modal.classList.contains('active')) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    } else {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

/**
 * 切換轉賬模態框
 */
function toggleTransferModal() {
    const modal = document.getElementById('transferModal');

    if (!modal.classList.contains('active')) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        updateTransferSelects();
    } else {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

/**
 * 關閉所有模態框（按下 ESC）
 */
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.getElementById('modal').classList.remove('active');
        document.getElementById('accountModal').classList.remove('active');
        document.getElementById('transferModal').classList.remove('active');
        document.body.style.overflow = 'auto';
    }
});

/**
 * 點擊模態框背景時關閉
 */
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        const modal = e.target.closest('.modal');
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = 'auto';
        }
    });
});

/**
 * 顯示/隱藏頁面部分
 */
/**
 * 從 URL 路徑取得頁面名稱
 *
 * 例如：
 * http://localhost:8000/ → "dashboard"
 * http://localhost:8000/assets → "assets"
 * http://localhost:8000/audit → "audit"
 */
function getPageFromURL() {
    const path = window.location.pathname;

    // 移除開頭和結尾的 /
    const cleanPath = path.replace(/^\/+|\/+$/g, '');

    // 如果路徑為空，默認返回 dashboard
    if (!cleanPath) {
        return 'dashboard';
    }

    // 只取第一段（例如 /audit/details → audit）
    const page = cleanPath.split('/')[0];

    // 驗證頁面名稱
    const validPages = ['dashboard', 'assets', 'audit', 'settings', 'profile'];
    return validPages.includes(page) ? page : 'dashboard';
}

/**
 * 顯示指定的頁面部分
 *
 * 這個函數現在集成了 URL routing：
 * 1. 隱藏所有頁面
 * 2. 顯示選中頁面
 * 3. 更新 URL（使用 History API）
 * 4. 更新導航狀態
 * 5. 觸發頁面初始化
 */
function showSection(sectionName) {
    // 驗證頁面名稱
    const validPages = ['dashboard', 'assets', 'audit', 'settings', 'profile'];
    if (!validPages.includes(sectionName)) {
        sectionName = 'dashboard';
    }

    // ============ 隱藏所有頁面 ============
    document.querySelectorAll('[id^="section-"]').forEach(section => {
        section.classList.add('hidden');
    });

    // ============ 移除導航活躍狀態 ============
    document.querySelectorAll('[id^="nav-"]').forEach(nav => {
        nav.classList.remove('nav-active');
    });

    // ============ 顯示選中頁面 ============
    const section = document.getElementById(`section-${sectionName}`);
    if (section) {
        section.classList.remove('hidden');
    }

    // ============ 更新導航活躍狀態 ============
    const navBtn = document.getElementById(`nav-${sectionName}`);
    if (navBtn) {
        navBtn.classList.add('nav-active');
    }

    // ============ 🚀 更新 URL（最重要！） ============
    const urlPath = sectionName === 'dashboard' ? '/' : `/${sectionName}`;
    const pageTitle = {
        'dashboard': 'Financial Dashboard - FinHub',
        'assets': 'Portfolio Overview - FinHub',
        'audit': 'Security Audit Trail - FinHub',
        'settings': 'Settings - FinHub',
        'profile': 'Profile - FinHub'
    }[sectionName] || 'FinHub';

    window.history.pushState(
        { page: sectionName },           // State object (可選)
        pageTitle,                        // Page title (大多數瀏覽器忽略)
        urlPath                           // URL path (重要！)
    );

    // 更新頁面標題
    document.title = pageTitle;

    // ============ 在移動設備上關閉側邊欄 ============
    if (window.innerWidth < 1024) {
        closeSidebar();
    }

    // ============ 在移動設備上滾動到頂部 ============
    if (window.innerWidth < 1024) {
        window.scrollTo(0, 0);
    }

    // ============ 觸發頁面特定的初始化 ============
    if (sectionName === 'assets') {
        initAssetsSection();
    }
}

/**
 * ===== ASSETS 相關功能 =====
 */

/**
 * 初始化 Assets 頁面
 */
function initAssetsSection() {
    console.log('Initializing Assets section...');
    loadHoldings();
}

/**
 * 從 CJTrade 獲取持倉數據
 */
async function loadHoldings() {
    try {
        // 暫時使用模擬數據，實際應調用 API
        const mockHoldings = [
            { symbol: 'AAPL', quantity: 10, avgCost: 150.25, currentPrice: 175.50, value: 1755.00 },
            { symbol: 'GOOGL', quantity: 5, avgCost: 2800.00, currentPrice: 2950.75, value: 14753.75 },
            { symbol: 'TSLA', quantity: 3, avgCost: 200.00, currentPrice: 242.30, value: 726.90 }
        ];

        updateHoldingsUI(mockHoldings);
    } catch (error) {
        console.error('Error loading holdings:', error);
    }
}

/**
 * 更新持倒表 UI
 */
function updateHoldingsUI(holdings) {
    const table = document.getElementById('holdingsTable');
    const holdingsCount = document.getElementById('holdingsCount');

    if (!holdings || holdings.length === 0) {
        table.innerHTML = `
            <tr class="hover:bg-slate-50 transition">
                <td colspan="7" class="px-4 md:px-8 py-8 text-center text-slate-400 text-sm">
                    No holdings yet • <a href="#" onclick="syncWithCJTrade()" class="text-indigo-600 hover:underline">Sync to load</a>
                </td>
            </tr>
        `;
        holdingsCount.textContent = '0 Holdings';
        updatePortfolioSummary([]);
        return;
    }

    // 計算統計信息
    let totalValue = 0;
    let totalCost = 0;
    let totalUnrealizedPnL = 0;

    const rows = holdings.map(h => {
        const value = h.currentPrice * h.quantity;
        const cost = h.avgCost * h.quantity;
        const unrealizedPnL = value - cost;
        const returnPercent = ((unrealizedPnL / cost) * 100).toFixed(2);

        totalValue += value;
        totalCost += cost;
        totalUnrealizedPnL += unrealizedPnL;

        const pnlColor = unrealizedPnL >= 0 ? 'text-emerald-600' : 'text-red-600';
        const pnlSign = unrealizedPnL >= 0 ? '+' : '';

        return `
            <tr class="hover:bg-slate-50 transition">
                <td class="px-4 md:px-8 py-4 font-semibold text-slate-900">${h.symbol}</td>
                <td class="px-4 md:px-8 py-4 text-right text-slate-600">${h.quantity.toFixed(2)}</td>
                <td class="hidden md:table-cell px-4 md:px-8 py-4 text-right text-slate-600">$${h.avgCost.toFixed(2)}</td>
                <td class="px-4 md:px-8 py-4 text-right text-slate-900 font-semibold">$${h.currentPrice.toFixed(2)}</td>
                <td class="px-4 md:px-8 py-4 text-right text-slate-900 font-semibold">$${value.toFixed(2)}</td>
                <td class="px-4 md:px-8 py-4 text-right font-semibold ${pnlColor}">${pnlSign}$${unrealizedPnL.toFixed(2)}</td>
                <td class="hidden sm:table-cell px-4 md:px-8 py-4 text-right font-semibold ${pnlColor}">${pnlSign}${returnPercent}%</td>
            </tr>
        `;
    }).join('');

    table.innerHTML = rows;
    holdingsCount.textContent = `${holdings.length} Holdings`;
    updatePortfolioSummary({ totalValue, totalCost, totalUnrealizedPnL });
}

/**
 * 更新持倉組合摘要卡片
 */
function updatePortfolioSummary(summary) {
    if (!summary || !summary.totalValue) {
        document.getElementById('portfolioTotalValue').textContent = '$0';
        document.getElementById('portfolioTotalCost').textContent = '$0';
        document.getElementById('portfolioUnrealizedPnL').textContent = '+$0';
        document.getElementById('portfolioUnrealizedPnLPercent').textContent = '+0%';
        document.getElementById('portfolioHoldingCount').textContent = '0';
        return;
    }

    const pnlColor = summary.totalUnrealizedPnL >= 0 ? 'emerald' : 'red';
    const pnlSign = summary.totalUnrealizedPnL >= 0 ? '+' : '';
    const returnPercent = ((summary.totalUnrealizedPnL / summary.totalCost) * 100).toFixed(2);

    document.getElementById('portfolioTotalValue').textContent = `$${summary.totalValue.toFixed(2)}`;
    document.getElementById('portfolioTotalCost').textContent = `$${summary.totalCost.toFixed(2)}`;
    document.getElementById('portfolioUnrealizedPnL').textContent = `${pnlSign}$${summary.totalUnrealizedPnL.toFixed(2)}`;
    document.getElementById('portfolioUnrealizedPnL').className = `text-2xl md:text-3xl font-black text-${pnlColor}-600`;
    document.getElementById('portfolioUnrealizedPnLPercent').textContent = `${pnlSign}${returnPercent}%`;
}

/**
 * 從 CJTrade 同步數據
 */
async function syncWithCJTrade() {
    console.log('Syncing with CJTrade...');

    // 更新最後同步時間
    const now = new Date().toLocaleTimeString();
    document.getElementById('lastUpdateTime').textContent = now;

    // 在此添加實際的 API 調用邏輯
    // 例如：const response = await fetch('/api/v1/cjtrade/sync');

    // 暫時刷新本地數據
    await loadHoldings();
}

/**
 * 手動刷新持倉
 */
async function refreshPortfolio() {
    console.log('Refreshing portfolio...');
    await loadHoldings();
}

/**
 * 導出持倒數據
 */
function exportHoldings() {
    console.log('Exporting holdings...');
    // 導出邏輯待實現
}

/**
 * 響應式工具類
 */
const ResponsiveUtil = {
    /**
     * 檢查是否為移動設備
     */
    isMobile() {
        return window.innerWidth < 768;
    },

    /**
     * 檢查是否為平板設備
     */
    isTablet() {
        return window.innerWidth >= 768 && window.innerWidth < 1024;
    },

    /**
     * 檢查是否為桌面
     */
    isDesktop() {
        return window.innerWidth >= 1024;
    },

    /**
     * 獲取當前屏幕尺寸
     */
    getBreakpoint() {
        if (this.isMobile()) return 'sm';
        if (this.isTablet()) return 'md';
        return 'lg';
    },

    /**
     * 格式化數字（響應式顯示）
     */
    formatNumber(num) {
        if (Math.abs(num) >= 1e6) {
            return (num / 1e6).toFixed(this.isMobile() ? 1 : 2) + 'M';
        } else if (Math.abs(num) >= 1e3) {
            return (num / 1e3).toFixed(this.isMobile() ? 1 : 2) + 'K';
        }
        return num.toFixed(2);
    }
};

/**
 * ============ URL ROUTING 初始化 ============
 */

/**
 * 初始化前端路由系統
 *
 * 這個函數在頁面加載時調用，會根據 URL 顯示正確的頁面
 */
function initializeRouting() {
    // 🔍 從 URL 讀取頁面名稱
    const currentPage = getPageFromURL();

    // 🎯 顯示對應的頁面（不會更新 URL，因為已經是正確的 URL）
    showSection(currentPage);

    console.log(`✅ Routing initialized. Current page: ${currentPage}, URL: ${window.location.pathname}`);
}

/**
 * 監聽瀏覽器的 popstate 事件（前進/後退按鈕）
 *
 * 用戶點擊瀏覽器的前進/後退按鈕時觸發
 */
window.addEventListener('popstate', (event) => {
    // 從 URL 讀取頁面名稱
    const page = getPageFromURL();

    // 顯示對應頁面（無需更新 URL，因為 popstate 已經改變了 URL）

    // 隱藏所有頁面
    document.querySelectorAll('[id^="section-"]').forEach(section => {
        section.classList.add('hidden');
    });

    // 移除導航活躍狀態
    document.querySelectorAll('[id^="nav-"]').forEach(nav => {
        nav.classList.remove('nav-active');
    });

    // 顯示選中頁面
    const section = document.getElementById(`section-${page}`);
    if (section) {
        section.classList.remove('hidden');
    }

    // 更新導航狀態
    const navBtn = document.getElementById(`nav-${page}`);
    if (navBtn) {
        navBtn.classList.add('nav-active');
    }

    // 更新頁面標題
    const pageTitle = {
        'dashboard': 'Financial Dashboard - FinHub',
        'assets': 'Portfolio Overview - FinHub',
        'audit': 'Security Audit Trail - FinHub'
    }[page] || 'FinHub';
    document.title = pageTitle;

    console.log(`↩️ Browser navigation: ${page} (${window.location.pathname})`);
});

/**
 * 初始化響應式功能
 */
document.addEventListener('DOMContentLoaded', () => {
    // ============ 初始化路由系統 ============
    // 根據 URL 顯示正確的頁面
    initializeRouting();

    // 初始化模態框
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        modal.classList.remove('active');
    });

    // 在移動設備上隱藏側邊欄
    if (window.innerWidth < 1024) {
        document.getElementById('sidebar').classList.remove('active');
        document.getElementById('sidebarOverlay').classList.remove('active');
    }

    // 桌面上恢復 Sidebar 狀態
    if (window.innerWidth >= 1024) {
        const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
        const sidebar = document.getElementById('sidebar');
        if (isCollapsed) {
            sidebar.classList.add('collapsed');
        }
    }

    console.log(`Responsive Design Initialized - Breakpoint: ${ResponsiveUtil.getBreakpoint()}`);
});

/**
 * 導出響應式實用工具到全局作用域
 */
window.ResponsiveUtil = ResponsiveUtil;
