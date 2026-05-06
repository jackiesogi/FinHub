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
function showSection(sectionName) {
    // 隱藏所有部分
    document.querySelectorAll('[id^="section-"]').forEach(section => {
        section.classList.add('hidden');
    });

    // 移除所有導航按鈕的活躍狀態
    document.querySelectorAll('[id^="nav-"]').forEach(nav => {
        nav.classList.remove('nav-active');
    });

    // 顯示選中的部分
    const section = document.getElementById(`section-${sectionName}`);
    if (section) {
        section.classList.remove('hidden');
    }

    // 設定導航按鈕的活躍狀態
    const navBtn = document.getElementById(`nav-${sectionName}`);
    if (navBtn) {
        navBtn.classList.add('nav-active');
    }

    // 在移動設備上關閉側邊欄
    if (window.innerWidth < 1024) {
        closeSidebar();
    }

    // 更新頁面標題
    const titles = {
        'dashboard': 'Financial Overview',
        'audit': 'Security Audit Trail'
    };
    document.getElementById('pageTitle').textContent = titles[sectionName] || 'Dashboard';
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
 * 初始化響應式功能
 */
document.addEventListener('DOMContentLoaded', () => {
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
