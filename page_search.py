# page_search.py
"""
检索控制台页面（全新左右分栏 + 卡片流布局 + 独立分屏专注窗口）。
"""

import re
import json
import unicodedata
import threading
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QMessageBox, QLayout, QSizePolicy, QApplication, QFrame,
    QTabBar, QTabWidget, QStackedWidget, QDialog, QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle,
    QCheckBox, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGraphicsDropShadowEffect, QProgressBar, QProgressDialog, QGraphicsOpacityEffect
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath
from PySide6.QtCore import Qt, QTimer, QRect, QSize, QPoint, QEvent, QSettings, QThread, Signal, QPropertyAnimation

from db_config import get_conn
from browser_manager import BrowserManager
from app_data import ALL_SUB_PLATFORMS
from app_data.search_templates import get_available_platforms
from app_data.crawl_status_consts import (
    CRAWL_STATUS_PENDING, CRAWL_STATUS_UNMATCHED, CRAWL_STATUS_DONE,
    CRAWL_STATUS_ORGANIZED, CRAWL_STATUS_WHITELIST, CRAWL_STATUS_IGNORED,
    CRAWL_STATUS_DUPLICATE
)
from app_data.crawl_consts import CRAWL_MAX_PAGES
from link_ingest_service import (
    organize_pending_links,
    ensure_db_columns,
    check_drafts_exist,
    clear_all_drafts,
    archive_batch_by_ids
)
from search_batch_queries import get_batch_tables, find_latest_draft_batch
from app_data.copyright_whitelist_consts import COPYRIGHT_WHITELIST_DOMAINS
from app_signals import signals

from focus_preview_window import BaseFocusWindow
from ui_components import ComboCellDelegate, NoWheelComboBox, draw_arrow
from ui_styles import (
    BTN_DANGER, BTN_SECONDARY, BTN_BLUE, BTN_PRIMARY,
    BTN_PRIMARY_OUTLINE, btn_link_style, HEADER_BASE, ROW_SELECTED_BG, TEXT_DARK
)

TAB_NAMES = {
    0: "待处理", 1: "处理中", 2: "已归档"
}


# =========================================================================
# ★ 极低功耗 Toast 提示
# =========================================================================
class ToastLabel(QLabel):
    def __init__(self, parent, text, bg_color="#10B981"):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: white;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.adjustSize()

        parent_rect = parent.rect()
        x = (parent_rect.width() - self.width()) // 2
        y = parent_rect.height() - self.height() - 40
        self.move(x, y)

        self.show()
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity")
        self.anim.setDuration(1800)
        self.anim.setStartValue(1.0)
        self.anim.setKeyValueAt(0.8, 1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()


CARD_STYLES = {
    "明确资源": {"color": "#10B981", "bg": "#ECFDF5", "text": "#065F46", "border": "4px solid #10B981"},
    "未知网站": {"color": "#F59E0B", "bg": "#FEF3C7", "text": "#92400E", "border": "4px solid #F59E0B"},
    "关键词未命中": {"color": "#9CA3AF", "bg": "#F3F4F6", "text": "#374151", "border": "4px solid #9CA3AF"},
    "待解析": {"color": "#3B82F6", "bg": "#EFF6FF", "text": "#1E3A8A", "border": "4px solid #3B82F6"},
    "解析失败": {"color": "#4B5563", "bg": "#F9FAFB", "text": "#374151", "border": "4px solid #4B5563"},
    "已在库": {"color": "#047857", "bg": "#ECFDF5", "text": "#064E3B", "border": "4px solid #047857"},
    "白名单": {"color": "#0EA5E9", "bg": "#F0F9FF", "text": "#0369A1", "border": "4px solid #0EA5E9"},
    "已永删": {"color": "#991B1B", "bg": "#FEF2F2", "text": "#7F1D1D", "border": "4px solid #991B1B"},
}


def get_card_status(record):
    crawl_status = record[10] if len(record) > 10 else 0
    domain_matched = record[11] if len(record) > 11 else 0
    if crawl_status == CRAWL_STATUS_ORGANIZED:
        return "明确资源" if domain_matched == 1 else "未知网站"
    elif crawl_status == CRAWL_STATUS_UNMATCHED:
        return "关键词未命中"
    elif crawl_status == CRAWL_STATUS_PENDING:
        return "待解析"
    elif crawl_status == CRAWL_STATUS_PARSE_FAILED:
        return "解析失败"
    elif crawl_status == CRAWL_STATUS_DUPLICATE:
        return "已在库"
    elif crawl_status == CRAWL_STATUS_WHITELIST:
        return "白名单"
    elif crawl_status == CRAWL_STATUS_IGNORED:
        return "已永删"
    return "未知网站"


def show_topmost_message(parent, title, text, buttons=None, default_button=None, custom_buttons=None):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    label_map = {}
    if custom_buttons:
        for label, role in custom_buttons:
            btn = box.addButton(label, role)
            label_map[btn] = label
            if default_button and label == default_button:
                box.setDefaultButton(btn)
    else:
        box.setStandardButtons(buttons if buttons is not None else QMessageBox.Ok)
        if default_button is not None:
            box.setDefaultButton(default_button)
    if parent:
        try:
            parent.raise_()
            parent.activateWindow()
        except Exception:
            pass
    try:
        QApplication.alert(parent.window() if parent else box, 0)
    except Exception:
        pass
    box.exec()
    clicked = box.clickedButton()
    if custom_buttons:
        return label_map.get(clicked)
    return box.standardButton(clicked) if clicked else None


class CrawlWorker(QThread):
    progress_signal = Signal(str)
    scanned_signal = Signal(int)
    finished_signal = Signal(bool, int, str)

    def __init__(self, platform, kw, ctx, stop_event, pause_event):
        super().__init__()
        self.platform = platform
        self.kw = kw
        self.ctx = ctx
        self.stop_event = stop_event
        self.pause_event = pause_event

    def run(self):
        from search_crawl_service import run_search
        callbacks = {
            "on_progress": lambda msg: self.progress_signal.emit(msg),
            "on_page_scanned": lambda count: self.scanned_signal.emit(count),
            "on_finished": lambda success, total, error: self.finished_signal.emit(success, total, error)
        }
        try:
            run_search(self.platform, self.kw, self.ctx, callbacks, stop_event=self.stop_event,
                       pause_event=self.pause_event)
        except Exception as e:
            self.finished_signal.emit(False, 0, str(e))


class CrawlControlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动化监控中")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(320, 180)
        self.container = QFrame(self)
        self.container.setObjectName("Container")
        self.container.setStyleSheet(
            "#Container { background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E7EB; }")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 50))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(self.container)
        inner_layout = QVBoxLayout(self.container)
        inner_layout.setContentsMargins(20, 15, 20, 15)
        inner_layout.setSpacing(10)
        top_row = QHBoxLayout()
        title_lbl = QLabel("🤖 自动化监控中")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #111827; border: none;")
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(20, 20)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; color: #9CA3AF; border: none; font-size: 14px; } QPushButton:hover { color: #EF4444; }")
        btn_close.clicked.connect(self.accept)
        top_row.addWidget(title_lbl)
        top_row.addStretch()
        top_row.addWidget(btn_close)
        inner_layout.addLayout(top_row)
        self.lbl_status = QLabel("脚本正在自动抓取中，请勿手动操作浏览器")
        self.lbl_status.setStyleSheet("color: #6B7280; font-size: 12px; border: none;")
        inner_layout.addWidget(self.lbl_status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self._set_progress_style("#10B981")
        inner_layout.addWidget(self.progress_bar)
        inner_layout.addSpacing(5)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.btn_pause = QPushButton("⏸️ 暂停脚本")
        self._set_pause_btn_style(paused=False)
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_stop = QPushButton("🛑 停止并退出")
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #FEF2F2; color: #DC2626; padding: 8px; border-radius: 6px; font-weight: bold; border: 1px solid #FECACA; } QPushButton:hover { background: #FEE2E2; }")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_stop)
        inner_layout.addLayout(btn_layout)
        self._is_paused = False
        self._drag_pos = None

    def _set_progress_style(self, color_hex):
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ border: none; border-radius: 3px; background-color: #E5E7EB; }} QProgressBar::chunk {{ border-radius: 3px; background-color: {color_hex}; }}")

    def _set_pause_btn_style(self, paused):
        if paused:
            self.btn_pause.setStyleSheet(
                "QPushButton { background: #ECFDF5; color: #059669; padding: 8px; border-radius: 6px; font-weight: bold; border: 1px solid #A7F3D0; } QPushButton:hover { background: #D1FAE5; }")
        else:
            self.btn_pause.setStyleSheet(
                "QPushButton { background: #F3F4F6; color: #374151; padding: 8px; border-radius: 6px; font-weight: bold; border: 1px solid #D1D5DB; } QPushButton:hover { background: #E5E7EB; }")

    def set_paused(self, paused):
        self._is_paused = paused
        if paused:
            self.btn_pause.setText("▶️ 继续抓取")
            self._set_pause_btn_style(paused=True)
            self.lbl_status.setText("脚本已暂停，您可以手动操作浏览器")
            self.lbl_status.setStyleSheet("color: #D97706; font-size: 12px; border: none; font-weight: bold;")
            self._set_progress_style("#F59E0B")
        else:
            self.btn_pause.setText("⏸️ 暂停脚本")
            self._set_pause_btn_style(paused=False)
            self.lbl_status.setText("脚本正在自动抓取中，请勿手动操作浏览器")
            self.lbl_status.setStyleSheet("color: #6B7280; font-size: 12px; border: none;")
            self._set_progress_style("#10B981")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=5):
        super().__init__(parent)
        self._item_list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        return self._item_list[index] if 0 <= index < len(self._item_list) else None

    def takeAt(self, index):
        return self._item_list.pop(index) if 0 <= index < len(self._item_list) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list: size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _do_layout(self, rect, test_only):
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._item_list:
            space_x, space_y = self._h_spacing, self._v_spacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only: item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()


class ListDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🛡️ 永删 / 白名单 与词库管理")
        self.resize(700, 480)
        layout = QVBoxLayout(self)
        self.tab = QTabWidget()

        self.page_black = QWidget()
        lay_black = QVBoxLayout(self.page_black)
        lay_black.addWidget(QLabel("这里是被永久拉黑的网址/标题，移出后下次搜索会重新出现："))
        self.table_black = QTableWidget()
        self.table_black.setColumnCount(3)
        self.table_black.setHorizontalHeaderLabels(["编号", "标题", "网址"])
        self.table_black.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_black.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_black.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_black.setAlternatingRowColors(True)
        self.table_black.verticalHeader().setVisible(False)
        self.table_black.setStyleSheet("QTableWidget { font-size: 12px; }")
        header = self.table_black.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_black.setColumnWidth(1, 220)
        lay_black.addWidget(self.table_black, 1)
        btn_del = QPushButton("🗑️ 移出黑名单 (允许再次被搜索到)")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._remove_black)
        lay_black.addWidget(btn_del)

        self.page_white = QWidget()
        lay_white = QVBoxLayout(self.page_white)
        self.list_white = QListWidget()
        self.list_white.setStyleSheet("QListWidget { font-size: 12px; }")
        lay_white.addWidget(QLabel("这里是版权方域名白名单（仅展示，无法修改）："))
        lay_white.addWidget(self.list_white)

        self.page_kw = QWidget()
        lay_kw = QVBoxLayout(self.page_kw)
        self.list_kw = QListWidget()
        self.list_kw.setStyleSheet("QListWidget { font-size: 12px; }")
        btn_del_kw = QPushButton("🗑️ 删除选中词")
        btn_del_kw.setStyleSheet(BTN_DANGER)
        btn_del_kw.clicked.connect(self._remove_kw)
        lay_kw.addWidget(QLabel("这里是用户添加的副关键词，用于计算相关度和搜索："))
        lay_kw.addWidget(self.list_kw)
        lay_kw.addWidget(btn_del_kw)

        self.tab.addTab(self.page_black, "🚫 永删拦截库")
        self.tab.addTab(self.page_white, "🛡️ 版权白名单")
        self.tab.addTab(self.page_kw, "📚 副关键词库")
        layout.addWidget(self.tab)
        self.refresh_data()

    def refresh_data(self):
        self.table_black.setRowCount(0)
        conn = get_conn()
        try:
            rows = conn.execute("SELECT id, site_url, title FROM ignored_links ORDER BY id DESC").fetchall()
            self.table_black.setRowCount(len(rows))
            for i, r in enumerate(rows):
                id_item = QTableWidgetItem(str(r[0]))
                id_item.setData(Qt.UserRole, r[0])
                id_item.setTextAlignment(Qt.AlignCenter)
                title_item = QTableWidgetItem(r[2] or "无标题")
                title_item.setToolTip(r[2] or "无标题")
                url_item = QTableWidgetItem(r[1] or "")
                url_item.setToolTip(r[1] or "")
                self.table_black.setItem(i, 0, id_item)
                self.table_black.setItem(i, 1, title_item)
                self.table_black.setItem(i, 2, url_item)
        finally:
            conn.close()

        self.list_white.clear()
        for d in COPYRIGHT_WHITELIST_DOMAINS: self.list_white.addItem(QListWidgetItem(f"🔒 {d}"))

        self.list_kw.clear()
        conn = get_conn()
        try:
            rows = conn.execute("SELECT id, word, add_time FROM user_signals ORDER BY id DESC").fetchall()
            for r in rows:
                text = f"{r[1]}  (添加于: {r[2] or '未知'})"
                list_item = QListWidgetItem(text)
                list_item.setData(Qt.UserRole, r[0])
                self.list_kw.addItem(list_item)
        finally:
            conn.close()

    def _remove_black(self):
        row = self.table_black.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一行要移出的记录。")
            return
        id_item = self.table_black.item(row, 0)
        if not id_item: return
        db_id = id_item.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认移出", "移出后，该链接会在下次搜索时重新被抓取。确定吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        conn = get_conn()
        try:
            conn.execute("DELETE FROM ignored_links WHERE id = ?", (db_id,))
            conn.commit()
        finally:
            conn.close()
        self.refresh_data()

    def _remove_kw(self):
        item = self.list_kw.currentItem()
        if not item: return
        db_id = item.data(Qt.UserRole)
        reply = QMessageBox.question(self, "确认删除", "删除后该词将从词库中移除，不再参与相关度计算。确定吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        conn = get_conn()
        try:
            conn.execute("DELETE FROM user_signals WHERE id = ?", (db_id,))
            conn.commit()
        finally:
            conn.close()
        self.refresh_data()
        if self.parent() and hasattr(self.parent(), "load_user_signals"):
            self.parent().load_user_signals()
            self.parent().refresh_sub_kws()


class DataCard(QFrame):
    def __init__(self, row_idx, record, mode, parent_page):
        super().__init__()
        self.record = record
        self.mode = mode
        self.parent_page = parent_page
        self.db_id = record[0]
        self.title = record[1] or "无标题"
        self.body_text = record[2] or ""
        self.raw_url = record[3] or ""
        self.book_name = record[4] or ""
        self.original_category = record[5] or ""
        self.fetch_time = record[6] or ""
        self.source_site = record[7] if len(record) > 7 else ""
        self.pick_origin = record[12] if len(record) > 12 else ""

        self.status = get_card_status(record)
        self.is_manual = (self.pick_origin == "手动获取")
        style = CARD_STYLES.get(self.status, CARD_STYLES["未知网站"])

        self.setObjectName("DataCard")
        self.setCursor(Qt.ArrowCursor)
        self.setFixedHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"#DataCard {{ background-color: #FFFFFF; border: 1px solid #E5E7EB; border-left: {style['border']}; border-radius: 6px; }} #DataCard:hover {{ background-color: #F8FAFC; border: 1px solid #93C5FD; border-left: {style['border']}; }}")
        self.display_url = "⏳ 等待解析真实链接..." if "baidu.com/link?url=" in self.raw_url else self.raw_url

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        lbl_status = QLabel(self.status)
        lbl_status.setStyleSheet(
            f"background: {style['bg']}; color: {style['text']}; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; border: none;")
        top_row.addWidget(lbl_status)
        if self.is_manual:
            lbl_manual = QLabel("📌 手动拾取")
            lbl_manual.setStyleSheet(
                "background: #FDF4FF; color: #C026D3; border: 1px solid #F0ABFC; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;")
            top_row.addWidget(lbl_manual)
        top_row.addStretch()
        lbl_time = QLabel(self.fetch_time)
        lbl_time.setStyleSheet("color: #9CA3AF; font-size: 12px; border: none;")
        top_row.addWidget(lbl_time)
        layout.addLayout(top_row)

        lbl_title = QLabel(self.title)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #111827; border: none;")
        lbl_title.setWordWrap(False)
        lbl_title.setToolTip(self.title)
        lbl_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(lbl_title)

        if self.body_text:
            display_body = self.body_text[:80] + ("..." if len(self.body_text) > 80 else "")
            lbl_body = QLabel(display_body)
            lbl_body.setStyleSheet("color: #4B5563; font-size: 13px; border: none;")
            lbl_body.setWordWrap(False)
            lbl_body.setToolTip(self.body_text)
            lbl_body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            layout.addWidget(lbl_body)

        display_text = self.display_url
        if len(display_text) > 65: display_text = display_text[:62] + "..."
        lbl_url = QLabel(display_text)
        lbl_url.setStyleSheet("color: #2563EB; font-size: 12px; border: none;")
        lbl_url.setToolTip("双击跳转预览：" + self.raw_url)
        lbl_url.setCursor(Qt.PointingHandCursor)
        lbl_url.setMaximumHeight(18)
        lbl_url.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl_url.mouseDoubleClickEvent = lambda e: self.parent_page._preview_card_url(
            self.db_id, self.raw_url, self.original_category, self.book_name
        )
        layout.addWidget(lbl_url)
        layout.addStretch()

        bottom_row = QHBoxLayout()
        if self.source_site:
            lbl_src = QLabel(f"来源: {self.source_site}")
            lbl_src.setStyleSheet("color: #6B7280; font-size: 12px; border: none;")
            lbl_src.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            bottom_row.addWidget(lbl_src)
        bottom_row.addStretch()

        if self.mode == "actionable":
            self.combo_book = NoWheelComboBox()
            self.combo_book.setStyleSheet(
                "QComboBox { padding: 2px 5px; border: 1px solid #DCDCDC; border-radius: 4px; font-size: 12px; background: #FFF; }")
            self.combo_book.setMaximumWidth(140)
            books = [b["name"] for b in self.parent_page.books_data.values()]
            self.combo_book.addItems(books)
            if self.book_name in books: self.combo_book.setCurrentText(self.book_name)
            self.combo_book.currentTextChanged.connect(self._on_book_changed)
            bottom_row.addWidget(self.combo_book)

            self.combo_cat = NoWheelComboBox()
            self.combo_cat.setStyleSheet(
                "QComboBox { padding: 2px 5px; border: 1px solid #DCDCDC; border-radius: 4px; font-size: 12px; background: #FFF; font-weight: bold; color: #059669; }")
            self.combo_cat.setMaximumWidth(120)
            cur_cat = self.original_category or "其他"
            candidates = [cur_cat] + list(ALL_SUB_PLATFORMS)
            seen = set()
            for opt in candidates:
                if opt in seen: continue
                seen.add(opt)
                self.combo_cat.addItem(opt, f"keep:{opt}")
            idx = self.combo_cat.findData(f"keep:{cur_cat}")
            self.combo_cat.setCurrentIndex(idx if idx != -1 else 0)
            bottom_row.addWidget(self.combo_cat)

            btn_ok = QPushButton("入库")
            btn_ok.setStyleSheet(
                "background: #ECFDF5; color: #059669; border: 1px solid #A7F3D0; border-radius: 4px; padding: 4px 12px; font-weight: bold;")
            btn_ok.setCursor(Qt.PointingHandCursor)
            btn_ok.clicked.connect(
                lambda: self.parent_page._card_action(self.db_id, self.combo_cat.currentData(), "keep"))

            btn_black = QPushButton("永删")
            btn_black.setStyleSheet(
                "background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; border-radius: 4px; padding: 4px 12px; font-weight: bold;")
            btn_black.setCursor(Qt.PointingHandCursor)
            btn_black.clicked.connect(lambda: self.parent_page._card_action(self.db_id, "", "black"))

            btn_drop = QPushButton("忽略")
            btn_drop.setStyleSheet(
                "background: #F9FAFB; color: #6B7280; border: 1px solid #E5E7EB; border-radius: 4px; padding: 4px 12px;")
            btn_drop.setCursor(Qt.PointingHandCursor)
            btn_drop.clicked.connect(lambda: self.parent_page._card_action(self.db_id, "", "drop"))

            bottom_row.addWidget(btn_ok)
            bottom_row.addWidget(btn_black)
            bottom_row.addWidget(btn_drop)
        else:
            lbl_cat = QLabel(f"分类: {self.original_category or '无'}")
            lbl_cat.setStyleSheet("color: #4B5563; font-weight: bold; border: none;")
            bottom_row.addWidget(lbl_cat)
        layout.addLayout(bottom_row)

    def _on_book_changed(self, new_book_name):
        conn = get_conn()
        try:
            conn.execute("UPDATE draft_links SET book_name = ? WHERE id = ?",
                         (new_book_name, self.db_id))
            conn.commit()
        finally:
            conn.close()
        self.book_name = new_book_name


class CardListWidget(QWidget):
    def __init__(self, parent_page, mode="readonly"):
        super().__init__()
        self.parent_page = parent_page
        self.mode = mode
        self.all_records = []
        self.current_page = 1
        self.page_size = 10

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.card_layout = QVBoxLayout(self.scroll_content)
        self.card_layout.setContentsMargins(10, 10, 10, 10)
        self.card_layout.setSpacing(10)
        self.card_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll, 1)

    def set_data(self, records):
        if len(records) == len(self.all_records) and records and self.all_records:
            if records[0][0] == self.all_records[0][0] and records[-1][0] == self.all_records[-1][0]: return
        self.all_records = records
        self.current_page = 1
        self.render_page()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.render_page()
            self.scroll.verticalScrollBar().setValue(0)

    def next_page(self):
        max_page = max(1, (len(self.all_records) + self.page_size - 1) // self.page_size)
        if self.current_page < max_page:
            self.current_page += 1
            self.render_page()
            self.scroll.verticalScrollBar().setValue(0)

    def render_page(self):
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget(): child.widget().deleteLater()

        if not self.all_records:
            lbl_empty = QLabel("暂无数据")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setStyleSheet("color: #9CA3AF; font-size: 14px; margin-top: 50px; border: none;")
            self.card_layout.addWidget(lbl_empty)
            if hasattr(self.parent_page, "update_pagination_ui"): self.parent_page.update_pagination_ui(self)
            return

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        page_records = self.all_records[start_idx:end_idx]
        for i, r in enumerate(page_records):
            global_idx = start_idx + i + 1
            card = DataCard(global_idx, r, self.mode, self.parent_page)
            card.setMaximumWidth(16777215)
            self.card_layout.addWidget(card)
        if hasattr(self.parent_page, "update_pagination_ui"): self.parent_page.update_pagination_ui(self)


class SearchWorkbench(QWidget):
    def __init__(self, parent_page):
        super().__init__()
        self.parent_page = parent_page

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.tab_bar = QTabBar()
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setStyleSheet(
            "QTabBar { background: transparent; } QTabBar::tab { background: #F3F4F6; padding: 8px 24px; border: 1px solid #E5E7EB; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-size: 14px; font-weight: bold; } QTabBar::tab:hover { background: #E5E7EB; } QTabBar::tab:selected { background: white; color: #059669; border-top: 3px solid #059669; border-bottom: 1px solid white; }")
        self.tab_bar.addTab("⚡ 待处理")
        self.tab_bar.addTab("⏳ 处理中")
        self.tab_bar.addTab("🗄️ 已归档")
        layout.addWidget(self.tab_bar)

        self.stack = QStackedWidget()
        self.list_todo = CardListWidget(parent_page, "actionable")
        self.list_pending = CardListWidget(parent_page, "readonly")
        self.list_archive = CardListWidget(parent_page, "readonly")
        self.stack.addWidget(self.list_todo)
        self.stack.addWidget(self.list_pending)
        self.stack.addWidget(self.list_archive)
        self.tab_bar.currentChanged.connect(self.stack.setCurrentIndex)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)

        layout.addWidget(self.stack, 1)

        bottom_layout = QHBoxLayout()
        self.btn_prev = QPushButton("< 上一页")
        self.btn_next = QPushButton("下一页 >")
        self.lbl_page_info = QLabel("第 0 / 0 页")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)

        style = "QPushButton { border: none; background: transparent; color: #4B5563; font-size: 13px; padding: 5px; } QPushButton:hover { color: #111827; } QPushButton:disabled { color: #D1D5DB; }"
        self.btn_prev.setStyleSheet(style)
        self.btn_next.setStyleSheet(style)
        self.lbl_page_info.setStyleSheet("color: #6B7280; font-size: 13px;")

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_prev)
        bottom_layout.addWidget(self.lbl_page_info)
        bottom_layout.addWidget(self.btn_next)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

        self.sync_data()

    def set_active_card(self, db_id):
        for i in range(self.stack.count()):
            list_widget = self.stack.widget(i)
            if not isinstance(list_widget, CardListWidget): continue
            for j in range(list_widget.card_layout.count()):
                item = list_widget.card_layout.itemAt(j)
                if item and item.widget() and isinstance(item.widget(), DataCard):
                    card = item.widget()
                    pass

    def on_tab_changed(self, index):
        lists = [self.list_todo, self.list_pending, self.list_archive]
        if index < 0 or index >= len(lists): return
        current_list = lists[index]
        try:
            self.btn_prev.clicked.disconnect()
            self.btn_next.clicked.disconnect()
        except:
            pass
        self.btn_prev.clicked.connect(current_list.prev_page)
        self.btn_next.clicked.connect(current_list.next_page)
        self.update_pagination_ui(current_list)

    def update_pagination_ui(self, current_list_widget):
        if self.stack.currentWidget() != current_list_widget: return
        if not current_list_widget.all_records:
            self.lbl_page_info.setText("第 0 / 0 页")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return
        total_pages = (
                                  len(current_list_widget.all_records) + current_list_widget.page_size - 1) // current_list_widget.page_size
        self.lbl_page_info.setText(
            f"第 {current_list_widget.current_page} / {total_pages} 页 (共 {len(current_list_widget.all_records)} 条)")
        self.btn_prev.setEnabled(current_list_widget.current_page > 1)
        self.btn_next.setEnabled(current_list_widget.current_page < total_pages)

    def sync_data(self):
        p = self.parent_page
        self.list_todo.set_data(p.list_todo.all_records)
        self.list_pending.set_data(p.list_pending.all_records)
        self.list_archive.set_data(p.list_archive.all_records)
        for i in range(3):
            self.tab_bar.setTabText(i, p.tab_bar.tabText(i))


class SearchConsolePage(QWidget):
    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.books_data = {}
        self.is_crawling = False
        self._is_background_parsing = False
        self.settings = QSettings("AuthorTools", "AntiPiracy")
        self.search_queue = []
        self.current_queue_index = 0
        self.current_batch_id = ""
        self.is_focus_mode = False
        self.focus_window = None
        self.workbench = None
        self.active_preview_db_id = None
        self._summary = None
        self.stop_event = None
        self.pause_event = None
        self.manual_stopped = False
        self.control_dialog = None

        ensure_db_columns()
        self.base_sub_kws = []
        self.dynamic_sub_kws = []
        self.temp_sub_kws = []
        self.selected_sub_kws = set()

        self.current_filter_status = None
        self._cached_tables = {"tab1_todo": [], "tab2_pending": [], "tab3_archive": [], "stats": {}}
        self._is_rendering = False
        self._is_organizing = False
        self._forced_close_handled = False

        self.load_user_signals()
        self.setup_ui()
        self.update_pagination_ui(self.list_todo)
        signals.manual_pick_finished.connect(self._on_manual_pick_finished)
        signals.save_batch_requested.connect(self._on_save_batch_requested)

        # 轮询拉取浏览器队列
        self._pull_timer = QTimer(self)
        self._pull_timer.setInterval(800)
        self._pull_timer.timeout.connect(self._pull_queues_safe)
        self._pull_timer.start()

        # 强关浏览器检测
        self._close_watch_timer = QTimer(self)
        self._close_watch_timer.setInterval(500)
        self._close_watch_timer.timeout.connect(self._check_browser_forced_close)
        self._close_watch_timer.start()

        self.refresh_tables()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.is_crawling:
            self.refresh_tables()

    def load_user_signals(self):
        self.base_sub_kws = ["资源", "txt", "下载", "免费阅读", "提取码", "全文阅读"]
        conn = get_conn()
        try:
            rows = conn.execute("SELECT word FROM user_signals").fetchall()
            for r in rows:
                if r[0] not in self.base_sub_kws: self.base_sub_kws.append(r[0])
        finally:
            conn.close()

    def save_temp_to_db(self):
        if not self.temp_sub_kws: return

        def display_width(s):
            w = 0
            for ch in s: w += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
            return w

        conn = get_conn()
        try:
            for w in self.temp_sub_kws:
                if display_width(w) >= 3:
                    conn.execute("INSERT OR IGNORE INTO user_signals (word, add_time) VALUES (?, ?)",
                                 (w, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        except Exception as e:
            print(f"[词库] 存入失败: {e}")
        finally:
            conn.close()
        self.temp_sub_kws.clear()
        self.load_user_signals()
        self.refresh_sub_kws()

    def refresh_pending_list(self):
        self.refresh_tables()

    def update_pagination_ui(self, current_list_widget):
        if not hasattr(self, "lbl_page_info"): return
        if self.stack.currentWidget() != current_list_widget: return
        if not current_list_widget.all_records:
            self.lbl_page_info.setText("第 0 / 0 页")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return
        total_pages = (
                                  len(current_list_widget.all_records) + current_list_widget.page_size - 1) // current_list_widget.page_size
        self.lbl_page_info.setText(
            f"第 {current_list_widget.current_page} / {total_pages} 页 (共 {len(current_list_widget.all_records)} 条)")
        self.btn_prev.setEnabled(current_list_widget.current_page > 1)
        self.btn_next.setEnabled(current_list_widget.current_page < total_pages)

    def on_tab_changed(self, index):
        lists = [self.list_todo, self.list_pending, self.list_archive]
        if index < 0 or index >= len(lists): return
        current_list = lists[index]
        try:
            self.btn_prev.clicked.disconnect()
            self.btn_next.clicked.disconnect()
        except:
            pass
        self.btn_prev.clicked.connect(current_list.prev_page)
        self.btn_next.clicked.connect(current_list.next_page)

        self.current_filter_status = None
        self.update_current_tab_only(index)

    def setup_ui(self):
        # 全局美化 Tooltip（避免局部按钮样式阻断）
        QApplication.instance().setStyleSheet("""
            QToolTip {
                background-color: #FFFFFF;
                color: #374151;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.left_scroll.setMinimumWidth(360)
        self.left_scroll.setMaximumWidth(420)

        left_panel = QWidget()
        left_panel.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 9, 5, 0)
        left_layout.setSpacing(15)

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(5, 0, 0, 0)
        lbl_auto_search = QLabel("自动搜索")
        lbl_auto_search.setStyleSheet("font-size: 16px; font-weight: bold; color: #111827;")
        title_layout.addWidget(lbl_auto_search)
        title_layout.addStretch()
        left_layout.addLayout(title_layout)

        input_style = "QComboBox, QLineEdit { border: 1px solid #E5E7EB; border-radius: 8px; padding: 8px 12px; background: #FFFFFF; font-size: 13px; color: #374151; } QComboBox:hover, QLineEdit:hover { border: 1px solid #D1D5DB; } QComboBox:focus, QLineEdit:focus { border: 1px solid #059669; background: #F8FAFC; } QComboBox::drop-down { border: none; width: 24px; } QComboBox::down-arrow { image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #6B7280; width: 0; height: 0; margin-right: 8px; } QComboBox::down-arrow:hover { border-top: 5px solid #059669; }"
        form_widget = QWidget()
        grid_layout = QGridLayout(form_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(10)
        grid_layout.setVerticalSpacing(12)

        lbl_book = QLabel("关联作品:")
        lbl_book.setStyleSheet("color:#4B5563; font-size: 13px;")
        lbl_book.setFixedWidth(65)
        lbl_book.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.book_combo = QComboBox()
        self.book_combo.setStyleSheet(input_style)
        self.book_combo.activated.connect(self.on_book_changed)
        grid_layout.addWidget(lbl_book, 0, 0)
        grid_layout.addWidget(self.book_combo, 0, 1)

        lbl_plat = QLabel("搜索引擎:")
        lbl_plat.setStyleSheet("color:#4B5563; font-size: 13px;")
        lbl_plat.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(get_available_platforms())
        self.platform_combo.setStyleSheet(input_style)
        grid_layout.addWidget(lbl_plat, 1, 0)
        grid_layout.addWidget(self.platform_combo, 1, 1)

        lbl_main = QLabel("主关键词:")
        lbl_main.setStyleSheet("color:#4B5563; font-size: 13px;")
        lbl_main.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.main_kw_input = QLineEdit()
        self.main_kw_input.setReadOnly(True)
        self.main_kw_input.setStyleSheet(
            "QLineEdit { border: 1px solid #E5E7EB; border-radius: 8px; padding: 8px 12px; background: #F3F4F6; font-weight: bold; color: #059669; font-size: 13px; }")
        grid_layout.addWidget(lbl_main, 2, 0)
        grid_layout.addWidget(self.main_kw_input, 2, 1)

        self.main_kw_layout = FlowLayout(h_spacing=6, v_spacing=6)
        main_kw_container = QWidget()
        main_kw_container.setLayout(self.main_kw_layout)
        grid_layout.addWidget(main_kw_container, 3, 1)

        lbl_sub = QLabel("副关键词:")
        lbl_sub.setStyleSheet("color:#4B5563; font-size: 13px;")
        lbl_sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sub_kw_input = QLineEdit()
        self.sub_kw_input.setPlaceholderText("输入并回车添加")
        self.sub_kw_input.setStyleSheet(input_style)
        self.sub_kw_input.returnPressed.connect(self.on_add_sub_kw_from_input)
        grid_layout.addWidget(lbl_sub, 4, 0)
        grid_layout.addWidget(self.sub_kw_input, 4, 1)

        self.sub_kw_layout = FlowLayout(h_spacing=6, v_spacing=6)
        sub_kw_container = QWidget()
        sub_kw_container.setLayout(self.sub_kw_layout)
        grid_layout.addWidget(sub_kw_container, 5, 1)

        lbl_history = QLabel("搜索历史:")
        lbl_history.setStyleSheet("color:#4B5563; font-size: 13px;")
        lbl_history.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.history_layout = FlowLayout(h_spacing=6, v_spacing=6)
        history_container = QWidget()
        history_container.setLayout(self.history_layout)
        grid_layout.addWidget(lbl_history, 6, 0)
        grid_layout.addWidget(history_container, 6, 1)

        grid_layout.setColumnStretch(0, 0)
        grid_layout.setColumnStretch(1, 1)
        left_layout.addWidget(form_widget)

        bottom_opts = QHBoxLayout()
        bottom_opts.setAlignment(Qt.AlignVCenter)
        self.chk_save_kw = QCheckBox("搜索成功后写入副关键词库")
        self.chk_save_kw.setStyleSheet(
            "QCheckBox { font-size: 13px; color: #4B5563; padding: 2px 0; } QCheckBox::indicator { width: 14px; height: 14px; }")
        bottom_opts.addWidget(self.chk_save_kw, 0, Qt.AlignVCenter)
        bottom_opts.addStretch()

        lbl_page = QLabel("自动翻页数:")
        lbl_page.setStyleSheet("color: #4B5563; font-size: 13px;")
        bottom_opts.addWidget(lbl_page, 0, Qt.AlignVCenter)

        self.page_limit_combo = QComboBox()
        self.page_limit_combo.addItems([f"{i}页" for i in range(1, 6)])
        self.page_limit_combo.setCurrentIndex(max(0, min(4, CRAWL_MAX_PAGES - 1)))
        page_combo_style = "QComboBox { border: 1px solid #E5E7EB; border-radius: 6px; padding: 2px 6px; background: #FFFFFF; font-size: 13px; color: #374151; } QComboBox:hover { border: 1px solid #D1D5DB; } QComboBox:focus { border: 1px solid #059669; background: #F8FAFC; } QComboBox::drop-down { border: none; width: 20px; } QComboBox::down-arrow { image: none; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 4px solid #6B7280; width: 0; height: 0; margin-right: 5px; } QComboBox::down-arrow:hover { border-top: 4px solid #059669; }"
        self.page_limit_combo.setStyleSheet(page_combo_style)
        self.page_limit_combo.setFixedWidth(65)
        bottom_opts.addWidget(self.page_limit_combo, 0, Qt.AlignVCenter)
        left_layout.addLayout(bottom_opts)

        self.btn_search = QPushButton("🔍 开始搜索")
        self.btn_search.setStyleSheet(
            BTN_PRIMARY + "QPushButton { padding: 12px 0; font-size: 15px; border-radius: 8px; font-weight: bold; }")
        self.btn_search.clicked.connect(self.start_search)
        left_layout.addWidget(self.btn_search)

        self.parse_btn = QPushButton("")
        self.parse_btn.setStyleSheet(
            "background: #F59E0B; color: white; font-weight: bold; padding: 8px; border-radius: 6px; border: none;")
        self.parse_btn.clicked.connect(self.trigger_manual_parse)
        self.parse_btn.hide()

        self.parsing_label = QLabel("⚠️ 正在静默解析中...")
        self.parsing_label.setStyleSheet(
            "color: #DC2626; font-weight: bold; background: #FEE2E2; padding: 8px; border-radius: 6px; border: none;")
        self.parsing_label.hide()

        left_layout.addWidget(self.parse_btn)
        left_layout.addWidget(self.parsing_label)
        left_layout.addStretch()
        self.left_scroll.setWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.tab_bar = QTabBar()
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setStyleSheet(
            "QTabBar { background: transparent; } QTabBar::tab { background: #F3F4F6; padding: 8px 24px; border: 1px solid #E5E7EB; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-size: 14px; font-weight: bold; } QTabBar::tab:hover { background: #E5E7EB; } QTabBar::tab:selected { background: white; color: #059669; border-top: 3px solid #059669; border-bottom: 1px solid white; }")
        self.tab_bar.addTab("⚡ 待处理")
        self.tab_bar.addTab("⏳ 处理中")
        self.tab_bar.addTab("🗄️ 已归档")
        right_layout.addWidget(self.tab_bar)

        self.stats_layout = QHBoxLayout()
        self.stats_layout.setSpacing(10)
        self.stats_layout.setContentsMargins(10, 0, 10, 0)
        right_layout.addLayout(self.stats_layout)

        content_frame = QFrame()
        content_frame.setObjectName("ContentFrame")
        content_frame.setStyleSheet(
            "#ContentFrame { border: 1px solid #E5E7EB; border-top: none; border-radius: 0px 0px 8px 8px; background: white; }")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.list_todo = CardListWidget(self, "actionable")
        self.list_pending = CardListWidget(self, "readonly")
        self.list_archive = CardListWidget(self, "readonly")
        self.stack.addWidget(self.list_todo)
        self.stack.addWidget(self.list_pending)
        self.stack.addWidget(self.list_archive)

        self.tab_bar.currentChanged.connect(self.stack.setCurrentIndex)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        content_layout.addWidget(self.stack, 1)
        right_layout.addWidget(content_frame, 1)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 0, 10, 0)

        self.btn_manage = QPushButton("永删/白名单列表")
        self.btn_manage.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #4B5563; font-size: 13px; padding: 5px; } QPushButton:hover { color: #111827; }")
        self.btn_manage.setCursor(Qt.PointingHandCursor)
        self.btn_manage.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_manage.clicked.connect(self.show_list_manager)
        bottom_layout.addWidget(self.btn_manage)

        bottom_layout.addStretch()

        self.btn_prev = QPushButton("< 上一页")
        self.btn_prev.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #4B5563; font-size: 13px; padding: 5px; } QPushButton:hover { color: #111827; } QPushButton:disabled { color: #D1D5DB; }")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.lbl_page_info = QLabel("第 0 / 0 页")
        self.lbl_page_info.setStyleSheet("color: #6B7280; font-size: 13px; border: none; background: transparent;")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.btn_next = QPushButton("下一页 >")
        self.btn_next.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #4B5563; font-size: 13px; padding: 5px; } QPushButton:hover { color: #111827; } QPushButton:disabled { color: #D1D5DB; }")
        self.btn_next.setCursor(Qt.PointingHandCursor)

        bottom_layout.addWidget(self.btn_prev)
        bottom_layout.addWidget(self.lbl_page_info)
        bottom_layout.addWidget(self.btn_next)

        bottom_layout.addStretch()

        self.btn_del_sel = QPushButton("清空当前分类")
        self.btn_del_sel.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #DC2626; font-size: 13px; padding: 5px; } QPushButton:hover { text-decoration: underline; }")
        self.btn_del_sel.setCursor(Qt.PointingHandCursor)
        self.btn_del_sel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_del_sel.clicked.connect(self.delete_selected_drafts)
        bottom_layout.addWidget(self.btn_del_sel)

        right_layout.addLayout(bottom_layout)

        main_layout.addWidget(self.left_scroll)
        main_layout.addWidget(right_panel, 1)
        self.load_books()

    def refresh_tables(self):
        if self.is_crawling or getattr(self, '_is_rendering', False):
            return

        self._is_rendering = True
        try:
            try:
                BrowserManager.instance().pull_all_queues()
            except Exception:
                pass

            ensure_db_columns()
            if not self.current_batch_id:
                try:
                    latest = find_latest_draft_batch()
                    if latest: self.current_batch_id = latest
                except Exception:
                    pass

            self._cached_tables = get_batch_tables(self.current_batch_id)
            self.update_current_tab_only(self.tab_bar.currentIndex())
        finally:
            self._is_rendering = False

    def update_current_tab_only(self, tab_index):
        if tab_index < 0: return
        tables = self._cached_tables
        stats = tables.get("stats", {})

        if tab_index == 0:
            data = self._filter_records(tables.get("tab1_todo", []))
            self.list_todo.set_data(data)
            self.update_pagination_ui(self.list_todo)
        elif tab_index == 1:
            data = self._filter_records(tables.get("tab2_pending", []))
            self.list_pending.set_data(data)
            self.update_pagination_ui(self.list_pending)
        elif tab_index == 2:
            data = self._filter_records(tables.get("tab3_archive", []))
            self.list_archive.set_data(data)
            self.update_pagination_ui(self.list_archive)

        self._render_tags(stats)

        if self.workbench:
            self.workbench.sync_data()

        pending_count = len(tables.get("tab2_pending", []))
        if pending_count > 0 and not self._is_background_parsing:
            self.parse_btn.setText(f"🔄 发现 {pending_count} 条异常数据，点击重试")
            self.parse_btn.show()
            self.parsing_label.hide()
        elif not self._is_background_parsing:
            self.parse_btn.hide()
            self.parsing_label.hide()

    def _filter_records(self, records):
        if not self.current_filter_status:
            return records
        if self.current_filter_status == "手动拾取":
            return [r for r in records if len(r) > 12 and r[12] == "手动获取"]
        return [r for r in records if get_card_status(r) == self.current_filter_status]

    def _render_tags(self, stats):
        while self.stats_layout.count():
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                del item

        tooltip_map = {
            "明确资源": "建议入库",
            "未知网站": "待分类",
            "关键词未命中": "建议永删"
        }

        if self.tab_bar.currentIndex() == 0:
            tags = [
                ("全部", None, "#F3F4F6", "#374151"),
                ("明确资源", "明确资源", "#ECFDF5", "#065F46"),
                ("未知网站", "未知网站", "#FEF3C7", "#92400E"),
                ("关键词未命中", "关键词未命中", "#F3F4F6", "#374151"),
                ("手动拾取", "手动拾取", "#FDF4FF", "#C026D3"),
            ]
            total_count = stats.get("明确资源", 0) + stats.get("未知网站", 0) + stats.get("关键词未命中", 0)
        elif self.tab_bar.currentIndex() == 1:
            tags = [
                ("全部", None, "#F3F4F6", "#374151"),
                ("待解析", "待解析", "#EFF6FF", "#1E3A8A"),
                ("解析失败", "解析失败", "#F9FAFB", "#374151"),
            ]
            total_count = stats.get("待解析", 0) + stats.get("解析失败", 0)
        else:
            tags = [
                ("全部", None, "#F3F4F6", "#374151"),
                ("已在库", "已在库", "#ECFDF5", "#064E3B"),
                ("白名单", "白名单", "#F0F9FF", "#0369A1"),
                ("已永删", "已永删", "#FEF2F2", "#7F1D1D"),
            ]
            total_count = stats.get("已在库", 0) + stats.get("白名单", 0) + stats.get("已永删", 0)

        from PySide6.QtWidgets import QButtonGroup
        if not hasattr(self, 'tag_group'):
            self.tag_group = QButtonGroup(self)
            self.tag_group.setExclusive(True)

        for text, status_key, bg, color in tags:
            # 修复：使用 total_count 代替 sum(stats.values())
            count = stats.get(status_key, 0) if status_key else total_count
            lbl = QPushButton(f"{text} ({count})")
            if text in tooltip_map:
                lbl.setToolTip(tooltip_map[text])  # ★ 只有在字典里的才显示提示
            lbl.setCheckable(True)
            lbl.setCursor(Qt.PointingHandCursor)

            lbl.setStyleSheet(f"""
                QPushButton {{
                    background: {bg}; 
                    color: {color}; 
                    padding: 4px 12px; 
                    border-radius: 12px; 
                    font-size: 13px; 
                    border: 1px solid transparent;
                }}
                QPushButton:hover, QPushButton:checked {{ 
                    border: 1px solid {color}; 
                }}
            """)

            lbl.clicked.connect(lambda checked, s=status_key: self.on_filter_clicked(s))

            if self.current_filter_status == status_key:
                lbl.setChecked(True)

            self.tag_group.addButton(lbl)
            self.stats_layout.addWidget(lbl)

        self.stats_layout.addStretch()

    def on_filter_clicked(self, status_key):
        self.current_filter_status = status_key
        self.update_current_tab_only(self.tab_bar.currentIndex())

    def _card_action(self, db_id, action_data, action_type):
        if action_type == "keep":
            category = action_data.split(":")[1] if action_data and ":" in action_data else "其他"
            archive_batch_by_ids([(db_id, category)], [], [])
            ToastLabel(self, "✅ 已成功入库", "#10B981")
        elif action_type == "black":
            archive_batch_by_ids([], [], [db_id])
            ToastLabel(self, "🚫 已加入黑名单", "#EF4444")
        elif action_type == "drop":
            archive_batch_by_ids([], [db_id], [])
            ToastLabel(self, "⏭️ 已忽略", "#6B7280")

        self.refresh_tables()
        if self.main_window and hasattr(self.main_window, 'links_page'):
            self.main_window.links_page.refresh_table()

    def _preview_card_url(self, db_id, raw_url, category, book_name=""):
        if not raw_url: return
        picked_category = category or "手动拾取"
        self.active_preview_db_id = db_id

        if not self.current_batch_id:
            self.current_batch_id = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        final_book_id = None
        final_book_name = book_name
        final_keyword = None

        conn = get_conn()
        try:
            # 优先查草稿表
            row = conn.execute(
                "SELECT book_id, book_name, source_keyword, source_platform FROM draft_links WHERE id = ?",
                (db_id,)).fetchone()

            # 如果草稿表没查到，查归档表
            if not row:
                row = conn.execute(
                    "SELECT book_id, book_name, source_keyword, source_platform FROM sites WHERE id = ?",
                    (db_id,)).fetchone()

            # 只要查到了任意一条，就提取数据
            if row:
                final_book_id = row[0]
                final_book_name = row[1] or book_name
                final_keyword = row[2]
                if not category and row[3]:
                    picked_category = row[3]
        finally:
            conn.close()

        # 使用 or 短路求值，这是最优雅的兜底，IDE 绝不会报灰
        final_book_name = final_book_name or self.book_combo.currentText()
        final_keyword = final_keyword or self.main_kw_input.text()

        if not final_book_id:
            # 从 self.books_data 反查 id
            for bid, bdata in self.books_data.items():
                if bdata["name"] == final_book_name:
                    final_book_id = bid
                    break

        if not self.is_focus_mode:
            self.is_focus_mode = True
            self.workbench = SearchWorkbench(self)
            self.focus_window = BaseFocusWindow(self, self.workbench, "检索控制台 - 专注分屏")

            # 拦截分屏窗口的关闭动作，防止漏存数据
            original_close_event = self.focus_window.closeEvent

            def custom_close_event(event):
                try:
                    bm = BrowserManager.instance()
                    pending = bm.get_pending_count()
                except Exception:
                    pending = 0

                if pending > 0:
                    reply = show_topmost_message(
                        self.focus_window,
                        "退出预览",
                        f"检测到 {pending} 条拾取链接尚未保存。\n是否保存并加入待解析队列？\n\n（注：浏览器将保留在后台，供您继续使用）",
                        custom_buttons=[
                            ("保存并解析", QMessageBox.ButtonRole.YesRole),
                            ("丢弃", QMessageBox.ButtonRole.NoRole),
                            ("取消退出", QMessageBox.ButtonRole.RejectRole)
                        ],
                        default_button="保存并解析"
                    )

                    if reply == "保存并解析":
                        self._flush_pending_and_parse()
                    elif reply == "丢弃":
                        bm.clear_pending_picks()
                        ToastLabel(self, "已丢弃暂存拾取", "#6B7280")
                    else:
                        event.ignore()
                        return

                original_close_event(event)
                self.on_focus_window_closed()

            self.focus_window.closeEvent = custom_close_event

            self.workbench.tab_bar.setCurrentIndex(self.tab_bar.currentIndex())
            win_rect = self.focus_window.show_and_place(left_ratio=0.65)
        else:
            win_rect = None

        if self.workbench:
            self.workbench.set_active_card(self.active_preview_db_id)

        try:
            bm = BrowserManager.instance()
            ctx = {
                "book_id": final_book_id,
                "book_name": final_book_name,
                "keyword": final_keyword,
                "source_platform": picked_category,
                "pick_origin": "手动获取",
                "batch_id": self.current_batch_id,
                "source_url": raw_url,
            }
            bm.start_batch_preview([raw_url], ctx, window_bounds=win_rect)
        except Exception as e:
            QMessageBox.warning(self, "预览失败", str(e))

    def on_focus_window_closed(self):
        self.is_focus_mode = False
        self.focus_window = None
        self.workbench = None
        self.active_preview_db_id = None

    def delete_selected_drafts(self):
        current_index = self.tab_bar.currentIndex()
        if current_index == 2:
            QMessageBox.warning(self, "提示", "已归档数据不允许直接删除。")
            return
        current_list = [self.list_todo, self.list_pending, self.list_archive][current_index]
        if not current_list.all_records:
            QMessageBox.information(self, "提示", "当前分类下没有数据。")
            return
        reply = QMessageBox.question(self, "确认清空",
                                     f"当前分类共有 {len(current_list.all_records)} 条草稿，确定全部删除吗？\n（不拉黑，下次搜索还会出现）",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        ids_to_delete = [r[0] for r in current_list.all_records]
        if ids_to_delete:
            conn = get_conn()
            try:
                placeholders = ','.join('?' * len(ids_to_delete))
                conn.execute(f"DELETE FROM draft_links WHERE id IN ({placeholders})", ids_to_delete)
                conn.commit()
            finally:
                conn.close()
            self.refresh_tables()

    def show_list_manager(self):
        dlg = ListDialog(self)
        dlg.exec()

    def load_books(self):
        conn = get_conn()
        try:
            books = conn.execute("SELECT id, name, pen_name, aliases FROM books ORDER BY name").fetchall()
            self.books_data.clear()
            self.book_combo.clear()
            for b in books:
                b_id, b_name, b_pen, b_aliases = b
                self.books_data[b_id] = {"name": b_name, "pen_name": b_pen, "aliases": b_aliases}
                self.book_combo.addItem(b_name, b_id)
        finally:
            conn.close()
        if self.book_combo.count() > 0: self.on_book_changed(0)

    def on_book_changed(self, index=None):
        book_id = self.book_combo.currentData()
        if not book_id or book_id not in self.books_data: return
        book = self.books_data[book_id]
        while self.main_kw_layout.count():
            item = self.main_kw_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        main_kws = [book["name"]]
        if book.get("aliases"):
            for a in re.split(r'[,，/\\|、\s]+', book["aliases"]):
                a = a.strip()
                if a and a not in main_kws: main_kws.append(a)
        self.main_kw_input.setText(book["name"])
        for kw in main_kws:
            btn = QPushButton(kw)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background-color: #F0F4F8; border: 1px solid #D0D7E5; border-radius: 10px; padding: 3px 10px; color: #333; font-size: 11px; } QPushButton:hover { background-color: #E2E8F0; border-color: #059669; color: #059669; }")
            btn.clicked.connect(lambda checked, t=kw: self.main_kw_input.setText(t))
            self.main_kw_layout.addWidget(btn)
        self.dynamic_sub_kws = [book["pen_name"]] if book.get("pen_name") else []
        self.selected_sub_kws.clear()
        self.temp_sub_kws.clear()
        self.refresh_sub_kws()
        self.refresh_history()

    def refresh_sub_kws(self):
        while self.sub_kw_layout.count():
            item = self.sub_kw_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        all_kws = self.dynamic_sub_kws + [kw for kw in self.base_sub_kws if
                                          kw not in self.dynamic_sub_kws] + self.temp_sub_kws
        for kw in all_kws:
            btn = QPushButton(kw)
            btn.setCursor(Qt.PointingHandCursor)
            if kw in self.dynamic_sub_kws:
                btn.setStyleSheet(
                    "QPushButton { border: 1px solid #D97706; border-radius: 10px; padding: 3px 10px; background: #D97706; color: white; font-weight: bold; font-size: 11px; }" if kw in self.selected_sub_kws else "QPushButton { border: 1px dashed #D97706; border-radius: 10px; padding: 3px 10px; background: #FEF3C7; color: #D97706; font-size: 11px; }")
            else:
                btn.setStyleSheet(
                    "QPushButton { border: 1px solid #059669; border-radius: 10px; padding: 3px 10px; background: #059669; color: white; font-size: 11px; }" if kw in self.selected_sub_kws else "QPushButton { border: 1px solid #DCDCDC; border-radius: 10px; padding: 3px 10px; background: #FFF; color: #666; font-size: 11px; }")
            btn.clicked.connect(lambda checked, t=kw: self.toggle_sub_kw(t))
            self.sub_kw_layout.addWidget(btn)

    def toggle_sub_kw(self, kw):
        if kw in self.selected_sub_kws:
            self.selected_sub_kws.remove(kw)
        else:
            self.selected_sub_kws.add(kw)
        self.refresh_sub_kws()

    def on_add_sub_kw_from_input(self):
        text = self.sub_kw_input.text().strip()
        if not text: return
        if text not in self.base_sub_kws and text not in self.dynamic_sub_kws and text not in self.temp_sub_kws:
            self.temp_sub_kws.append(text)
        self.selected_sub_kws.add(text)
        self.sub_kw_input.clear()
        self.refresh_sub_kws()

    def refresh_history(self):
        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        book_id = self.book_combo.currentData()
        try:
            history = json.loads(self.settings.value(f"search_history_{book_id}", "[]"))
        except:
            history = []
        if not history:
            lbl = QLabel("暂无历史记录")
            lbl.setStyleSheet("color: #9CA3AF; font-size: 11px; font-style: italic;")
            self.history_layout.addWidget(lbl)
            return
        for record in history:
            subs = record.get("subs", [])
            display_text = f"{record.get('main_kw', '')} + {'/'.join(subs)}" if subs else f"{record.get('main_kw', '')} (无副词)"
            btn = QPushButton(display_text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #93C5FD; border-radius: 10px; padding: 3px 10px; background: #DBEAFE; color: #1E3A8A; font-size: 11px; } QPushButton:hover { background: #BFDBFE; }")
            btn.clicked.connect(lambda checked, r=record: self.apply_history(r))
            self.history_layout.addWidget(btn)

    def apply_history(self, record):
        self.main_kw_input.setText(record["main_kw"])
        self.selected_sub_kws = set(record["subs"])
        for s in record["subs"]:
            if s not in self.base_sub_kws and s not in self.dynamic_sub_kws and s not in self.temp_sub_kws:
                self.temp_sub_kws.append(s)
        self.refresh_sub_kws()

    def save_history(self, main_kw, subs):
        book_id = self.book_combo.currentData()
        if not book_id: return
        try:
            history = json.loads(self.settings.value(f"search_history_{book_id}", "[]"))
        except:
            history = []
        new_record = {"main_kw": main_kw, "subs": subs}
        history = [h for h in history if h != new_record]
        history.insert(0, new_record)
        self.settings.setValue(f"search_history_{book_id}", json.dumps(history[:5]))
        self.refresh_history()

    def start_search(self):
        if self.is_crawling: return
        self._summary = None
        draft_count = check_drafts_exist()
        if draft_count > 0:
            reply = QMessageBox.question(self, "发现未处理草稿",
                                         f"系统检测到还有 {draft_count} 条未处理的草稿！\n\n继续搜索将会【彻底清空】这些草稿，且无法恢复。\n\n确定要清空并开始全新搜索吗？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                clear_all_drafts()
            else:
                return
        main_kw = self.main_kw_input.text().strip()
        if not main_kw:
            QMessageBox.warning(self, "提示", "主关键词不能为空")
            return
        kw = f"{main_kw} {' '.join(list(self.selected_sub_kws))}".strip()
        self.search_queue = [
            {"platform": self.platform_combo.currentText(), "keyword": kw, "book_id": self.book_combo.currentData(),
             "book_name": self.book_combo.currentText(), "is_exact": False,
             "max_pages": self.page_limit_combo.currentIndex() + 1}]
        self.current_queue_index = 0
        self._run_next_search()

    def _run_next_search(self):
        if self.current_queue_index >= len(self.search_queue):
            self._final_cleanup()
            return
        job = self.search_queue[self.current_queue_index]
        platform = job["platform"]
        kw = job["keyword"]
        self.current_batch_id = f"{platform}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ctx = {"book_id": job["book_id"], "book_name": job["book_name"], "is_exact": job["is_exact"],
               "batch_id": self.current_batch_id, "max_pages": job.get("max_pages", 3)}
        self.is_crawling = True
        self.btn_search.setEnabled(False)
        self.btn_search.setText(f"抓取中({platform})...")
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.manual_stopped = False
        if self.control_dialog: self.control_dialog.close()
        self.control_dialog = CrawlControlDialog(self)

        def toggle_pause():
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.control_dialog.set_paused(False)
            else:
                self.pause_event.set()
                self.control_dialog.set_paused(True)

        self.control_dialog.btn_pause.clicked.connect(toggle_pause)
        self.control_dialog.accepted.connect(self._on_manual_stop)
        self.control_dialog.show()

        self.worker = CrawlWorker(platform, kw, ctx, self.stop_event, self.pause_event)
        self.worker.progress_signal.connect(lambda msg: print(msg))
        self.worker.scanned_signal.connect(lambda count: self.refresh_tables())
        self.worker.finished_signal.connect(
            lambda success, total, error: self._on_crawl_finished(success, total, error, self.current_batch_id,
                                                                  job["is_exact"], platform))
        self.worker.start()

    def _on_manual_stop(self):
        if self.stop_event:
            self.stop_event.set()
            self.pause_event.clear()
            self.manual_stopped = True
            print("[UI] 用户手动停止了脚本，浏览器将保持开启")

    def _on_crawl_finished(self, success, scanned_total, error, batch_id, is_exact, platform):
        if self.control_dialog:
            self.control_dialog.close()
            self.control_dialog = None

        if not success:
            self.is_crawling = False
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 开始搜索")
            QMessageBox.critical(self, "抓取失败", error or "抓取过程中发生异常")
            self.current_queue_index += 1
            QTimer.singleShot(500, self._run_next_search)
            return

        if getattr(self, "manual_stopped", False):
            self.is_crawling = False
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 开始搜索")
            # 中途停止也顺手存一下抓到的数据
            try:
                self._flush_pending_picks()
            except:
                pass
            self.refresh_tables()
            QMessageBox.information(self, "已停止", "脚本已停止，浏览器已为您保留。\n您可以手动处理验证码或关闭浏览器。")
            return

        # ★ 新增：自动搜索结束后，必须把内存里的数据强制落库！
        try:
            n = self._flush_pending_picks()
            if n > 0:
                print(f"[自动抓取] 成功将 {n} 条抓取结果写入数据库草稿箱")
        except Exception as e:
            print(f"[自动抓取] 数据落库失败: {e}")

        self.save_history(self.main_kw_input.text().strip(), list(self.selected_sub_kws))
        if self.chk_save_kw.isChecked(): self.save_temp_to_db()
        self._start_parse(batch_id, is_exact)

    def _start_parse(self, batch_id, is_exact):
        self.btn_search.setText("智能解析中...")
        QApplication.processEvents()
        QTimer.singleShot(100, lambda: self._run_parse_sync(is_exact, batch_id))

    def _run_parse_sync(self, is_exact, batch_id):
        try:
            total, success, failed, ignored_count, wl_skip, bl_skip, matched, unknown, duplicate_count = organize_pending_links(
                is_exact_match=is_exact, batch_id=batch_id, process_events_func=QApplication.processEvents)

            # ================= ★ 核心调试代码 =================
            print("\n" + "=" * 50)
            print(f"【抓取解析结果】批次: {batch_id}")
            print(
                f"解析总数: {total} 条 | 成功: {success} 条 | 失败: {failed} 条 | 同一批次内重复被删: {duplicate_count} 条")
            conn = get_conn()
            try:
                all_count = conn.execute("SELECT COUNT(*) FROM draft_links WHERE batch_id = ?", (batch_id,)).fetchone()[
                    0]
                print(f"【查库】当前批次记录数: {all_count} 条")

                total_all = conn.execute("SELECT COUNT(*) FROM draft_links").fetchone()[0]
                print(f"【查库】全库总草稿数: {total_all} 条")

                recent = conn.execute(
                    "SELECT id, batch_id, site_url, crawl_status FROM draft_links ORDER BY id DESC LIMIT 5").fetchall()
                print(f"【查库】最近 5 条记录: {recent}")
                status_rows = conn.execute(
                    "SELECT crawl_status, COUNT(*) FROM draft_links WHERE batch_id = ? GROUP BY crawl_status",
                    (batch_id,)).fetchall()
                print(f"【查库】各状态分布: {status_rows}")
            except Exception as e:
                print("查库出错:", e)
            print("=" * 50 + "\n")
            # ==================================================

            conn = get_conn()
            try:
                def get_count(status):
                    return conn.execute("SELECT COUNT(*) FROM draft_links WHERE batch_id = ? AND crawl_status = ?",
                                        (batch_id, status)).fetchone()[0]

                real_wl = get_count(CRAWL_STATUS_WHITELIST)
                real_bl = get_count(CRAWL_STATUS_IGNORED)
                real_unmatched = get_count(CRAWL_STATUS_UNMATCHED)
                real_matched = conn.execute(
                    f"SELECT COUNT(*) FROM draft_links WHERE batch_id = ? AND crawl_status = '{CRAWL_STATUS_ORGANIZED}' AND domain_matched = 1",
                    (batch_id,)).fetchone()[0]
                real_unknown = conn.execute(
                    f"SELECT COUNT(*) FROM draft_links WHERE batch_id = ? AND crawl_status = '{CRAWL_STATUS_ORGANIZED}' AND domain_matched = 0",
                    (batch_id,)).fetchone()[0]
            finally:
                conn.close()
            last = {"matched": real_matched, "unknown": real_unknown, "duplicate": duplicate_count,
                    "unmatched": real_unmatched, "failed": failed, "whitelist": real_wl, "blacklist": real_bl}
            if self._summary is None: self._summary = {k: 0 for k in last}
            for k, v in last.items(): self._summary[k] += v
        except Exception as e:
            show_topmost_message(self, "错误", f"自动解析出错: {e}", buttons=QMessageBox.Ok)
        finally:
            self.is_crawling = False
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 开始搜索")
            self.refresh_tables()
            self.current_queue_index += 1
            QTimer.singleShot(500, self._run_next_search)

    def _final_cleanup(self):
        conn = get_conn()
        leftover = conn.execute("SELECT COUNT(*) FROM draft_links WHERE crawl_status = ? AND batch_id = ?",
                                (CRAWL_STATUS_PENDING, self.current_batch_id)).fetchone()[0]
        conn.close()
        if leftover > 0:
            reply = show_topmost_message(self, "扫尾提示", f"当前批次还有 {leftover} 条待解析草稿未处理，是否现在处理？",
                                         buttons=QMessageBox.Yes | QMessageBox.No, default_button=QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self.trigger_manual_parse()
                return
        summary = self._summary
        if summary:
            body = f"本轮处理完成！\n\n✅ 明确资源: {summary['matched']}\n🟡 未知网站: {summary['unknown']}\n📚 已在库: {summary['duplicate']}\n⚪ 关键词未命中: {summary['unmatched']}\n❌ 解析失败: {summary['failed']}\n🛡️ 白名单: {summary['whitelist']}\n🚫 黑名单: {summary['blacklist']}\n\n是否关闭浏览器？\n（如有验证码，请选「保留浏览器」处理后手动关闭）"
        else:
            body = "抓取任务完成。\n\n是否关闭浏览器？\n（如有验证码，请选「保留浏览器」处理后手动关闭）"
        reply = show_topmost_message(self, "抓取结束", body,
                                     custom_buttons=[("关闭浏览器", QMessageBox.ButtonRole.YesRole),
                                                     ("保留浏览器", QMessageBox.ButtonRole.NoRole)],
                                     default_button="关闭浏览器")
        if reply == "关闭浏览器":
            try:
                BrowserManager.instance().shutdown()
            except:
                pass
        self._summary = None

    def trigger_manual_parse(self):
        if self._is_background_parsing: return
        self.parse_btn.hide()
        self.parsing_label.show()
        self._is_background_parsing = True
        QApplication.processEvents()
        QTimer.singleShot(100, self._run_manual_parse_sync)

    def _run_manual_parse_sync(self):
        try:
            organize_pending_links(is_exact_match=False, batch_id=self.current_batch_id,
                                   process_events_func=QApplication.processEvents)
        except Exception as e:
            print(f"后台解析出错: {e}")
        finally:
            self._is_background_parsing = False
            self.parsing_label.hide()
            self.refresh_tables()
            self._is_organizing = False  # ★ 释放互斥锁
            show_topmost_message(self, "解析结束", "当前批次的草稿解析已结束！", buttons=QMessageBox.Ok)

    # =========================================================================
    # ★ 拾取暂存系统新增：轮询、强关检测与入库
    # =========================================================================
    def _pull_queues_safe(self):
        if self.is_crawling or getattr(self, "_is_rendering", False) or getattr(self, "_is_organizing", False):
            return
        try:
            BrowserManager.instance().pull_all_queues()
        except Exception:
            pass

    def _check_browser_forced_close(self):
        if self._is_organizing or self.is_crawling or self._forced_close_handled:
            return
        try:
            bm = BrowserManager.instance()
        except Exception:
            return
        if bm._expect_disconnect:
            return
        if bm._proc is not None and bm._proc.poll() is None:
            return

        self._forced_close_handled = True
        pending = bm.get_pending_count()

        if pending > 0:
            reply = show_topmost_message(
                self, "浏览器已关闭",
                f"检测到 {pending} 条拾取链接尚未保存。\n是否保存并加入待解析队列？",
                custom_buttons=[("保存并解析", QMessageBox.ButtonRole.YesRole),
                                ("丢弃", QMessageBox.ButtonRole.NoRole)],
                default_button="保存并解析",
            )
            if reply == "保存并解析":
                self._flush_pending_and_parse()
            else:
                bm.clear_pending_picks()
                ToastLabel(self, "已丢弃暂存拾取", "#6B7280")
        else:
            if self.focus_window:
                try:
                    self.focus_window.close()
                except:
                    pass
            self.on_focus_window_closed()

        QTimer.singleShot(3000, lambda: setattr(self, "_forced_close_handled", False))

    def _flush_pending_picks(self) -> int:
        from link_ingest_service import save_picked_link
        bm = BrowserManager.instance()
        picks = bm.take_pending_picks()
        inserted = 0
        for p in picks:
            try:
                record, dup, is_new = save_picked_link(
                    url=p["url"], title=p["title"], body=p["body"],
                    source_site=p["source_site"], ctx=p["ctx"],
                    parent_url=p["parent_url"], parent_title=p["parent_title"],
                    is_manual=p["is_manual"],
                )
                if is_new and record:
                    signals.link_saved.emit(record, dup)
                    inserted += 1
            except Exception as e:
                print(f"[flush] 单条失败: {e}")
        return inserted

    def _flush_pending_and_parse(self):
        if getattr(self, "_is_organizing", False):
            return

        self._is_organizing = True
        try:
            n = self._flush_pending_picks()
            self.refresh_tables()
            QApplication.processEvents()

            if n > 0:
                ToastLabel(self, f"✅ 已保存 {n} 条，开始解析", "#10B981")
                self._is_background_parsing = True
                self.parsing_label.show()
                QTimer.singleShot(200, self._run_manual_parse_sync)
            else:
                ToastLabel(self, "无有效新增", "#6B7280")
                self._is_organizing = False
        except Exception as e:
            print(f"[flush] 整体出错: {e}")
            self._is_organizing = False

    def _on_manual_pick_finished(self):
        """浮窗点击“保存暂存并解析”"""
        if getattr(self, "_is_organizing", False):
            ToastLabel(self, "正在处理中，请稍候", "#F59E0B")
            return

        self._flush_pending_and_parse()

        if self.focus_window:
            try:
                self.focus_window.close()
            except:
                pass
        self.on_focus_window_closed()

    # =========================================================================
    # ★ 新增：浮窗点击「保存本批」——只落库解析，不关预览、不关浏览器
    # =========================================================================
    def _on_save_batch_requested(self):
        if getattr(self, "_is_organizing", False):
            ToastLabel(self, "正在处理中，请稍候", "#F59E0B")
            return

        self._is_organizing = True
        try:
            n = self._flush_pending_picks()
            self.refresh_tables()
            QApplication.processEvents()

            if n > 0:
                ToastLabel(self, f"✅ 已保存 {n} 条，后台解析中", "#10B981")
                self._is_background_parsing = True
                self.parsing_label.show()
                QTimer.singleShot(200, self._run_manual_parse_silent)
            else:
                ToastLabel(self, "无有效新增", "#6B7280")
                self._is_organizing = False
        except Exception as e:
            print(f"[save_batch] 出错: {e}")
            ToastLabel(self, f"❌ 保存失败: {e}", "#EF4444")
            self._is_organizing = False

    def _run_manual_parse_silent(self):
        """静默解析：不弹模态框，避免打断预览"""
        try:
            organize_pending_links(
                is_exact_match=False,
                batch_id=self.current_batch_id,
                process_events_func=QApplication.processEvents
            )
        except Exception as e:
            print(f"[save_batch] 解析出错: {e}")
            ToastLabel(self, f"❌ 解析出错: {e}", "#EF4444")
        finally:
            self._is_background_parsing = False
            self.parsing_label.hide()
            self.refresh_tables()
            self._is_organizing = False
            ToastLabel(self, "✅ 本批解析完成", "#10B981")