import os
import threading
import time

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                               QFrame, QGridLayout)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from playwright.sync_api import sync_playwright

# ★ 引入路径管理
from app_paths import DATA_DIR


class PlatformCard(QFrame):
    def __init__(self, name, desc, url, color):
        super().__init__()
        self.name = name
        self.url = url
        self.setCursor(Qt.PointingHandCursor)

        # 基于主色计算悬停/按下色（不带 alpha，避免 Qt 的 #AARRGGBB 坑）
        base = QColor(color)
        hover_bg = base.darker(112).name()
        pressed_bg = base.darker(130).name()

        self.setStyleSheet(f"""
            QFrame {{
                background-color: #FFFFFF;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
            }}
            QFrame:hover {{
                border: 1px solid {color};
                background-color: #FCFCFC;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title_label = QLabel(name)
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {color}; border: none;")
        layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setStyleSheet("font-size: 13px; color: #666; border: none;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        layout.addStretch()

        url_label = QLabel(f"🔗 {url}")
        url_label.setStyleSheet("font-size: 11px; color: #999; border: none;")
        layout.addWidget(url_label)

        self.btn = QPushButton("🌐 打开投诉后台")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFocusPolicy(Qt.NoFocus)  # 防止点完留焦点虚线框

        self.btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 8px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
                color: #FFFFFF;
            }}
        """)
        self.btn.clicked.connect(self.open_browser)
        layout.addWidget(self.btn)

    def open_browser(self):
        def run_playwright():
            try:
                with sync_playwright() as p:
                    # ★ 核心修复：根据平台名字，决定读取哪个登录态文件夹
                    if "百度" in self.name:
                        dir_name = "login_baidu_data"
                    elif "夸克" in self.name:
                        dir_name = "login_quark_data"
                    else:
                        # 给 UC 预留的，如果以后加了 UC 自动投诉，就用这个
                        dir_name = "login_uc_data"

                    user_data_dir = os.path.join(DATA_DIR, dir_name)

                    browser = p.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=False,
                        args=["--start-maximized"]
                    )
                    page = browser.pages[0]
                    page.goto(self.url)
                    while True:
                        try:
                            if len(browser.pages) == 0:
                                break
                        except Exception:
                            break
                        time.sleep(1)
                    browser.close()
            except Exception as e:
                print(f"Playwright 启动失败: {e}")

        t = threading.Thread(target=run_playwright)
        t.daemon = True
        t.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.open_browser()
        super().mousePressEvent(event)


class PlatformsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = QLabel("【维权投诉平台导航】")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #333;")
        layout.addWidget(title)

        tip = QLabel(
            "点击下方任意卡片，将调用真实浏览器打开平台后台。")
        tip.setStyleSheet("font-size: 14px; color: #666; margin-bottom: 20px;")
        layout.addWidget(tip)

        grid = QGridLayout()
        grid.setSpacing(20)

        grid.addWidget(PlatformCard(
            "夸克侵权投诉平台",
            "管理夸克网盘、夸克搜索的侵权投诉记录，查看处理进度。",
            "https://ipp.quark.cn/#/home",
            "#10B981"), 0, 0)

        grid.addWidget(PlatformCard(
            "UC侵权投诉平台",
            "管理UC网盘的侵权投诉记录，查看处理进度。",
            "https://ipp.uc.cn/#/home",
            "#E67E22"), 0, 1)

        grid.addWidget(PlatformCard(
            "百度版权投诉平台",
            "管理百度网盘、百度贴吧、百度知道等侵权投诉记录。",
            "https://newcopyright.baidu.com/record",
            "#3B82F6"), 1, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()