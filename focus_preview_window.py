# focus_preview_window.py
"""
通用分屏预览外壳。
负责：左侧留出浏览器空间、窗口置顶、Esc 退出、自动关闭浏览器、恢复主窗口。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QApplication
from PySide6.QtCore import Qt
from browser_manager import BrowserManager


class BaseFocusWindow(QWidget):
    def __init__(self, main_page, workbench_widget, title="专注分屏 (按 Esc 退出)"):
        super().__init__()
        self.main_page = main_page
        self.workbench_widget = workbench_widget

        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("QWidget { background-color: #F8FAFC; }")
        self.setFocusPolicy(Qt.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部关闭按钮
        btn_close = QPushButton("🛑 退出分屏并关闭浏览器 (Esc)")
        btn_close.setStyleSheet(
            "QPushButton { border: 1px solid #FECACA; border-radius: 4px; background: #FEF2F2; color: #DC2626; font-size: 12px; font-weight: bold; padding: 6px; } "
            "QPushButton:hover { background: #FEE2E2; }"
        )
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

        # 将业务方传进来的工作台 Widget 塞进布局
        layout.addWidget(self.workbench_widget, 1)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        # 1. 关闭浏览器
        try:
            BrowserManager.instance().shutdown()
        except Exception:
            pass
        # 2. 恢复主窗口
        self.main_page.window().show()
        # 3. 清理业务页面的状态（让子类去重置变量）
        self.main_page.on_focus_window_closed()
        event.accept()

    def show_and_place(self, left_ratio=0.65):
        """显示窗口并计算左右分屏比例 (默认左侧浏览器 65%, 右侧工作台 35%)"""
        self.main_page.window().hide()

        screen_rect = QApplication.primaryScreen().availableGeometry()
        right_width = int(screen_rect.width() * (1 - left_ratio))
        left_width = screen_rect.width() - right_width

        # 右侧放工作台
        self.setGeometry(
            screen_rect.left() + left_width, screen_rect.top(),
            right_width, screen_rect.height()
        )
        self.show()
        self.setFocus()

        # 返回左侧浏览器应该占用的区域
        return {
            "left": screen_rect.left(),
            "top": screen_rect.top(),
            "width": left_width,
            "height": screen_rect.height()
        }