import os
import sys


# ============================================================
# ★ 0. 最高优先级：设置 Playwright 浏览器路径
#    必须在任何可能 import playwright 的模块之前执行
#    （page_books / page_spider 等都会在运行期启动浏览器）
# ============================================================
def _resolve_playwright_browsers_dir() -> str:
    """
    按优先级查找 ms-playwright 目录：
      1) exe/脚本同级目录下的 ms-playwright
      2) exe/脚本同级目录下的 _internal/ms-playwright（PyInstaller 6.x）
    开发模式：项目根目录下的 ms-playwright
    """
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

    # 都不存在时返回首选路径，让 Playwright 自己抛错，便于定位问题
    return candidates[0]


# 用 = 强制覆盖，确保一定走我们指定的目录；
# 如果临时想用本机缓存调试，可以改成 setdefault
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _resolve_playwright_browsers_dir()


# ============================================================
# ★ 1. 版本号（以后每次更新只改这里）
# ============================================================
VERSION = "1.1.0"


# ============================================================
# ★ 2. 此时才允许导入依赖 Playwright 的业务模块
# ============================================================
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QStackedWidget, QDialog, QLabel,
)
from PySide6.QtCore import Qt

# 注意：去掉了 from db_config import init_db，因为已经在 login_window 里执行过了

from page_books import BooksPage
from page_links import LinksPage
from page_spider import SpiderPage
from page_complaints import ComplaintsPage
from page_evidence import EvidencePage
from page_platforms import PlatformsPage
from page_profile import ProfilePage

from login_window import LoginWindow
from login_auto import try_auto_login, clear_session


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"打盗维权系统_试用版_v{VERSION}")
        self.resize(1200, 800)
        self.setStyleSheet("QMainWindow { background-color: #F0F4F1; }")

        # ★ 移除了 init_db()，因为登录成功后已经在 login_window 里调过了

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ================= 左侧菜单栏 =================
        left_container = QWidget()
        left_container.setFixedWidth(160)
        left_container.setStyleSheet("background-color: #F0F4F1;")
        left_layout = QVBoxLayout(left_container)
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
            "📚 作品管理", "🌐 盗文链接", "🔍 抓取管理",
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

        layout.addWidget(left_container)

        # ================= 右侧页面区 =================
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background-color: #FFFFFF; }")
        layout.addWidget(self.stack)

        self.books_page = BooksPage(self)
        self.links_page = LinksPage(self)
        self.spider_page = SpiderPage(self)
        self.complaint_page = ComplaintsPage(self)
        self.platforms_page = PlatformsPage()
        self.evidence_page = EvidencePage()

        self.profile_page = ProfilePage(self)

        self.stack.addWidget(self.books_page)
        self.stack.addWidget(self.links_page)
        self.stack.addWidget(self.spider_page)
        self.stack.addWidget(self.complaint_page)
        self.stack.addWidget(self.platforms_page)
        self.stack.addWidget(self.evidence_page)
        self.stack.addWidget(self.profile_page)

        self.sidebar.currentRowChanged.connect(self.change_page)
        self.sidebar.setCurrentRow(0)

    def change_page(self, index):
        self.stack.setCurrentIndex(index)
        if index == 1:
            self.links_page.refresh_table()
        elif index == 2:
            self.spider_page.refresh_data()
        elif index == 5:
            self.evidence_page.refresh_books()
            self.evidence_page.load_evidences()
        elif index == 6:
            self.profile_page.refresh_profile()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 启动时先尝试一次自动登录（读 session.json → 刷新 token → 校验授权）
    # 成功返回 user_id；失败返回 None，走登录窗口
    auto_ok = try_auto_login()

    while True:
        if not auto_ok:
            # 没有可用的自动登录状态：弹出登录窗口
            login = LoginWindow()
            if login.exec() != QDialog.Accepted:
                sys.exit(0)

        # 自动登录只在第一次启动时生效；
        # 之后若用户主动退出登录，必须回到登录窗口，不能再次自动登录
        auto_ok = False

        # 进入主窗口（login_window / login_auto 内部已完成 set_current_user + init_db）
        window = MainApp()
        window.show()

        # 进入主事件循环，直到主窗口关闭
        exit_code = app.exec()

        # 如果主窗口是通过"退出登录"关闭的，就清掉自动登录指针，回到登录窗口
        if getattr(window, "_logout_requested", False):
            clear_session()
            continue

        # 否则（点 X 关闭主窗口）直接退出整个程序
        sys.exit(exit_code)