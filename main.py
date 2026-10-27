import os
import sys


# ============================================================
# ★ 0. 最高优先级：设置 Playwright 浏览器路径
# ============================================================
def _resolve_playwright_browsers_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(base, "ms-playwright"),
        os.path.join(base, "_internal", "ms-playwright"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _resolve_playwright_browsers_dir()

# ============================================================
# ★ 1. 版本号
# ============================================================
VERSION = "2.0.0"

# ============================================================
# ★ 2. 此时才允许导入依赖 Playwright 的业务模块
# ============================================================
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QStackedWidget, QDialog, QLabel,
)
from PySide6.QtCore import Qt, QTimer

from page_books import BooksPage
from page_links import LinksPage
from page_search import SearchConsolePage
from page_spider import SpiderPage
from page_complaints import ComplaintsPage
from page_evidence import EvidencePage
from page_platforms import PlatformsPage
from page_profile import ProfilePage

from login_window import LoginWindow
from login_auto import try_auto_login, clear_session
from browser_manager import BrowserManager


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"打盗维权系统_试用版_v{VERSION}")
        self.setStyleSheet("QMainWindow { background-color: #F0F4F1; }")

        # ★ 动态计算初始大小，并设置最大宽高，防止在宽屏上铺得太开
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            # 初始大小限制在 1200x800 以内，并留出边距
            target_w = min(1200, available.width() - 100)
            target_h = min(800, available.height() - 100)
            self.resize(target_w, target_h)

            # 居中显示
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())
        else:
            self.resize(1200, 800)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ================= 左侧菜单栏 =================
        self.left_container = QWidget()  # ★ 加上 self.
        self.left_container.setFixedWidth(160)  # ★ 加上 self.
        self.left_container.setStyleSheet("background-color: #F0F4F1;")  # ★ 加上 self.
        left_layout = QVBoxLayout(self.left_container)  # ★ 加上 self.
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setStyleSheet("""
            QListWidget { background-color: #F0F4F1; color: #4B5563; font-size: 15px; border: none; outline: none; padding-top: 15px; } 
            QListWidget::viewport { background-color: transparent; }
            QListWidget::item { height: 50px; margin: 0; padding-left: 20px; border: none; } 
            QListWidget::item:hover { background-color: #E1E9E3; color: #1F1F1F; }
            QListWidget::item:selected { background-color: #FFFFFF; color: #059669; font-weight: bold; border-left: 4px solid #059669; border-top-right-radius: 0px; border-bottom-right-radius: 0px; }
        """)
        self.sidebar.addItems([
            "📚 作品管理", "🔗 盗文链接", "🌐️ 检索管理", "🕷️ 抓取管理",
            "⚖️ 投诉管理", "🏛️ 投诉平台", "📂 维权资料",
            "👤 个人与帮助",
        ])
        left_layout.addWidget(self.sidebar)

        # ================= 左下角：常驻版本与免责声明区 =================
        version_container = QWidget()
        version_layout = QVBoxLayout(version_container)
        version_layout.setContentsMargins(20, 10, 15, 20)
        version_layout.setSpacing(0)

        version_text = f"""
        <div style='line-height: 1.6; color: #9CA3AF; font-size: 11px;'>
            <p style='margin: 0; color: #A1A1AA;'>本软件仅供维权辅助使用，请严格遵守相关平台法规。</p>
            <p style='margin: 0; margin-bottom: 8px;'>v.{VERSION} ©HowLittle</p>
        </div>
        """
        lbl_version = QLabel(version_text)
        lbl_version.setTextFormat(Qt.RichText)
        lbl_version.setWordWrap(True)
        lbl_version.setStyleSheet("color: #9CA3AF;")
        version_layout.addWidget(lbl_version)
        left_layout.addWidget(version_container)

        layout.addWidget(self.left_container)

        # ================= 右侧页面区 =================
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background-color: #FFFFFF; }")
        layout.addWidget(self.stack)

        self.books_page = BooksPage(self)
        self.links_page = LinksPage(self)
        self.search_page = SearchConsolePage(self)
        self.spider_page = SpiderPage(self)
        self.complaint_page = ComplaintsPage(self)
        self.platforms_page = PlatformsPage()
        self.evidence_page = EvidencePage()
        self.profile_page = ProfilePage(self)

        self.stack.addWidget(self.books_page)
        self.stack.addWidget(self.links_page)
        self.stack.addWidget(self.search_page)
        self.stack.addWidget(self.spider_page)
        self.stack.addWidget(self.complaint_page)
        self.stack.addWidget(self.platforms_page)
        self.stack.addWidget(self.evidence_page)
        self.stack.addWidget(self.profile_page)

        self.sidebar.currentRowChanged.connect(self.change_page)
        self.sidebar.setCurrentRow(0)

        # ★ 新增：全局定时器，每 300 毫秒从浏览器拉取一次数据并补充浮窗
        self.global_browser_timer = QTimer(self)
        self.global_browser_timer.timeout.connect(self.poll_browser)
        self.global_browser_timer.start(300)

    def poll_browser(self):
        """自动补全浮窗并拉取数据"""
        try:
            bm = BrowserManager.instance()
            local = bm._state()
            if not local.context:
                return

            for p in local.context.pages:
                if not p.is_closed():
                    # 1. 顺便检查一下浮窗在不在（防止翻页后没了）
                    bm.ensure_injected(p)
                    # 2. 拉取数据
                    bm.pull_save_queue(p)
        except Exception:
            pass

    def change_page(self, index):
        self.stack.setCurrentIndex(index)
        if index == 1:
            self.links_page.refresh_table()
        elif index == 2:
            self.search_page.load_books()
            self.search_page.refresh_pending_list()
        elif index == 3:
            self.spider_page.refresh_data()
        elif index == 6:
            self.evidence_page.refresh_books()
            self.evidence_page.load_evidences()
        elif index == 7:
            self.profile_page.refresh_profile()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    auto_ok = try_auto_login()

    while True:
        if not auto_ok:
            login = LoginWindow()
            if login.exec() != QDialog.Accepted:
                sys.exit(0)

        auto_ok = False

        window = MainApp()
        window.show()

        exit_code = app.exec()

        if getattr(window, "_logout_requested", False):
            clear_session()
            continue

        sys.exit(exit_code)