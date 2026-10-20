import os
import sys

# ★ 1. 在这里定义版本号，以后每次更新改这里
VERSION = "1.0.0"

from app_paths import APP_DIR

# 先尝试找 exe 同级的，如果没有，就去 _internal 里面找（PyInstaller 6.x 的默认行为）
_browsers_dir = os.path.join(APP_DIR, "ms-playwright")
if not os.path.exists(_browsers_dir):
    _browsers_dir = os.path.join(APP_DIR, "_internal", "ms-playwright")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QListWidget, QStackedWidget, QDialog, QLabel)
from PySide6.QtCore import Qt
from db_config import init_db

from page_books import BooksPage
from page_links import LinksPage
from page_spider import SpiderPage
from page_complaints import ComplaintsPage
from page_evidence import EvidencePage
from page_platforms import PlatformsPage
from page_profile import ProfilePage

# ★ 核心修复：把这两个关键模块的导入移到最顶部
# 这样 PyInstaller 打包时，就一定会把它们抓进 exe 里，防止“闪退找不到模块”
from config import is_dev_mode
from login_window import LoginWindow


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"打盗维权系统_试用版_v{VERSION}")
        self.resize(1200, 800)
        self.setStyleSheet("QMainWindow { background-color: #F0F4F1; }")

        init_db()

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
            "👤 个人与帮助"
        ])
        left_layout.addWidget(self.sidebar)

        # ================= 左下角：常驻版本与免责声明区 =================
        version_container = QWidget()
        version_layout = QVBoxLayout(version_container)
        version_layout.setContentsMargins(20, 10, 15, 20)  # 左边距 20，下边距 20
        version_layout.setSpacing(0)

        # 使用 HTML 富文本进行排版，方便控制换行和行距
        version_text = f"""
        <div style='line-height: 1.6; color: #9CA3AF; font-size: 11px;'>
            <p style='margin: 0; color: #A1A1AA;'>本软件仅供维权辅助使用，请严格遵守相关平台法规。</p>
            <p style='margin: 0; margin-bottom: 8px;'>v.{VERSION} ©HowLittle</p>
        </div>
        """

        lbl_version = QLabel(version_text)
        lbl_version.setTextFormat(Qt.RichText)
        lbl_version.setWordWrap(True)  # 允许自动换行
        lbl_version.setStyleSheet("color: #9CA3AF;")  # 基础颜色

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

    # ★ 因为顶部已经 import 了，这里直接调用即可
    if not is_dev_mode():
        login = LoginWindow()
        if login.exec() != QDialog.Accepted:
            sys.exit(0)

    window = MainApp()
    window.show()
    sys.exit(app.exec())