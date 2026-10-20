import os
import threading
import time
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QListWidget, QTableWidget, QTableWidgetItem, QHeaderView,
                               QFileDialog, QMessageBox, QSplitter, QAbstractItemView,
                               QProgressBar, QTabWidget, QDialog, QFrame)
from PySide6.QtCore import Qt, Signal
from datetime import datetime
from db_config import get_conn

from auto_complaint_quark import run_auto_complaint as run_quark, AutoComplaintSignals
from auto_complaint_baidu import run_auto_complaint_baidu as run_baidu

# ★ 引入全局权限管理器
from license_manager import license_mgr


# ============================================================
# 安全小窗：独立运行 + 关闭即中断信号
# ============================================================
class ProcessDialog(QDialog):
    closed_by_user = Signal()

    def __init__(self, parent=None):
        super().__init__(None)
        self.setFixedSize(400, 160)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; border: 1px solid #D0D0D0; border-radius: 8px; }
        """)
        self._drag_offset = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet("""
            QWidget { background-color: #F5F5F5; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QLabel { background: transparent; border: none; color: #333; font-weight: bold; font-size: 13px; }
            QPushButton { border: none; background: transparent; color: #999; font-size: 15px; }
            QPushButton:hover { color: #E74C3C; }
        """)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(12, 0, 6, 0)
        title_lbl = QLabel("自动投诉运行状态")
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        tb_layout.addWidget(close_btn)

        title_bar.mousePressEvent = self._tb_press
        title_bar.mouseMoveEvent = self._tb_move
        title_bar.mouseReleaseEvent = self._tb_release
        layout.addWidget(title_bar)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(15, 10, 15, 15)
        c_layout.setSpacing(10)

        self.label = QLabel("初始化中...")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "color: #333; font-weight: bold; font-size: 13px; border: none; background: transparent;")
        c_layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #E0E0E0; border-radius: 4px; background: #FFF; }
            QProgressBar::chunk { background-color: #10B981; border-radius: 3px; }
        """)
        c_layout.addWidget(self.progress_bar)

        tip = QLabel("若遇到卡死，点击右上角 ✕ 即可强行终止脚本并恢复主界面。")
        tip.setAlignment(Qt.AlignCenter)
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #999; font-size: 11px; border: none; background: transparent;")
        c_layout.addWidget(tip)
        layout.addWidget(content)

    def _tb_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _tb_move(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def _tb_release(self, event):
        self._drag_offset = None
        event.accept()

    def update_text(self, text):
        self.label.setText(text)
        self.label.setToolTip(text)

    def closeEvent(self, event):
        self.closed_by_user.emit()
        event.accept()


# ============================================================
# 投诉页主类
# ============================================================
class ComplaintsPage(QWidget):
    refresh_links_signal = Signal()
    task_finished = Signal()
    batch_done = Signal(object)

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.batches = []
        self.auto_running = False
        self.current_signals = None
        self.progress_dialog = None

        self.refresh_links_signal.connect(self.do_refresh_links)
        self.task_finished.connect(self._on_task_finished)
        self.batch_done.connect(self._on_batch_done)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #DCDCDC; background: #FFFFFF; top: -1px; }
            QTabBar::tab { background: #F5F5F5; color: #666666; padding: 8px 24px; border: 1px solid #DCDCDC; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
            QTabBar::tab:hover { background: #EBEBEB; }
            QTabBar::tab:selected { background: #FFFFFF; color: #1F1F1F; font-weight: bold; border-bottom: 1px solid #FFFFFF; }
        """)
        layout.addWidget(self.tabs)

        # ================= Tab 1: 投诉队列 =================
        self.queue_tab = QWidget()
        queue_layout = QVBoxLayout(self.queue_tab)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("【投诉批次中心】 系统已按“分类 + 书籍”智能拆分（单批上限200条）。"))
        top_layout.addStretch()

        self.clear_btn = QPushButton("清空当前批次")
        self.clear_btn.setStyleSheet("""
            QPushButton { border: 1px solid #DCDFE6; border-radius: 4px; padding: 4px 12px; background: #FFF; color: #606266; }
            QPushButton:hover { border-color: #1F1F1F; color: #1F1F1F; }
            QPushButton:disabled { color: #BBB; border-color: #EEE; }
        """)
        self.clear_btn.clicked.connect(self.clear_batches)
        top_layout.addWidget(self.clear_btn)
        queue_layout.addLayout(top_layout)

        splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_title = QLabel("批次列表:")
        left_title.setStyleSheet("font-weight: bold; color: #1F1F1F; margin-bottom: 4px;")
        left_layout.addWidget(left_title)

        self.batch_list = QListWidget()
        self.batch_list.setStyleSheet("""
            QListWidget { border: 1px solid #E9ECEF; border-radius: 4px; outline: none; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #F2F2F2; }
            QListWidget::item:selected { background-color: #F5F5F5; color: #1F1F1F; font-weight: bold; border-left: 3px solid #1F1F1F; }
        """)
        self.batch_list.currentRowChanged.connect(self.on_batch_selected)
        left_layout.addWidget(self.batch_list)
        splitter.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_spacer = QLabel("投诉明细:")
        right_spacer.setStyleSheet("font-weight: bold; color: #1F1F1F; margin-bottom: 4px;")
        right_layout.addWidget(right_spacer)

        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(3)
        self.queue_table.setHorizontalHeaderLabels(["关联作品", "分类", "侵权链接"])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_table.setStyleSheet("""
            QTableWidget { border: 1px solid #E9ECEF; border-radius: 4px; }
            QHeaderView::section { background-color: #F8F9FA; font-weight: bold; padding: 6px; border: none; border-bottom: 1px solid #E9ECEF; }
        """)
        right_layout.addWidget(self.queue_table)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # 全批自动投诉
        self.auto_all_btn = QPushButton("全批自动投诉 (循环提交)")
        self.auto_all_btn.setStyleSheet("""
            QPushButton { background-color: #1F1F1F; color: white; padding: 8px 16px; font-weight: bold; border-radius: 4px; border: none; }
            QPushButton:hover { background-color: #333333; }
            QPushButton:disabled { background-color: #9CA3AF; color: #E5E7EB; }
        """)
        self.auto_all_btn.clicked.connect(lambda: self.trigger_auto_fill(is_all=True))
        btn_layout.addWidget(self.auto_all_btn)

        # 单批自动填表
        self.auto_btn = QPushButton("单批自动填表")
        self.auto_btn.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; padding: 8px 16px; font-weight: bold; border-radius: 4px; border: none; }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #9CA3AF; color: #E5E7EB; }
        """)
        self.auto_btn.clicked.connect(lambda: self.trigger_auto_fill(is_all=False))
        btn_layout.addWidget(self.auto_btn)

        # 导出Excel
        self.export_btn = QPushButton("导出为Excel")
        self.export_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; padding: 8px 16px; font-weight: bold; border-radius: 4px; border: 1px solid #DCDFE6; }
            QPushButton:hover { border-color: #1F1F1F; color: #1F1F1F; }
            QPushButton:disabled { color: #9CA3AF; border-color: #E5E7EB; }
        """)
        self.export_btn.clicked.connect(self.export_current_batch)
        btn_layout.addWidget(self.export_btn)

        # 手动标记
        self.mark_done_btn = QPushButton("手动标记本批已投诉")
        self.mark_done_btn.setStyleSheet("""
            QPushButton { background-color: #E74C3C; color: white; padding: 8px 16px; font-weight: bold; border-radius: 4px; border: none; }
            QPushButton:hover { background-color: #C0392B; }
            QPushButton:disabled { background-color: #9CA3AF; color: #E5E7EB; }
        """)
        self.mark_done_btn.clicked.connect(self.mark_batch_done)
        btn_layout.addWidget(self.mark_done_btn)

        right_layout.addLayout(btn_layout)
        splitter.addWidget(right_widget)

        splitter.setSizes([280, 720])
        queue_layout.addWidget(splitter)

        self.tabs.addTab(self.queue_tab, "投诉队列")

        # ================= Tab 2: 历史记录 =================
        self.history_tab = QWidget()
        history_layout = QVBoxLayout(self.history_tab)

        h_top_layout = QHBoxLayout()
        h_top_layout.addWidget(QLabel("【历史投诉记录】 以下是您所有的投诉批次汇总。"))
        h_top_layout.addStretch()
        refresh_btn = QPushButton("刷新记录")
        refresh_btn.setStyleSheet("""
            QPushButton { border: 1px solid #DCDFE6; border-radius: 4px; padding: 4px 12px; background: #FFF; color: #606266; }
            QPushButton:hover { border-color: #1F1F1F; color: #1F1F1F; }
        """)
        refresh_btn.clicked.connect(self.load_history)
        h_top_layout.addWidget(refresh_btn)
        history_layout.addLayout(h_top_layout)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["投诉时间", "关联作品", "分类", "投诉链接数量"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setStyleSheet("""
            QTableWidget { border: 1px solid #E9ECEF; border-radius: 4px; alternate-background-color: #FAFAFA; }
            QHeaderView::section { background-color: #F8F9FA; font-weight: bold; padding: 6px; border: none; border-bottom: 1px solid #E9ECEF; }
        """)
        history_layout.addWidget(self.history_table)

        self.tabs.addTab(self.history_tab, "历史记录")
        self.load_history()

        # ★ 初始化时检查权限
        self._set_running_ui(False)

    # ==================== 状态控制与权限拦截 ====================
    def _set_running_ui(self, running):
        is_exp = license_mgr.is_expired

        self.clear_btn.setEnabled(not running)

        # ★ 核心拦截：如果过期，直接禁用底部 4 个按钮
        self.auto_all_btn.setEnabled(not running and not is_exp)
        self.auto_btn.setEnabled(not running and not is_exp)
        self.export_btn.setEnabled(not running and not is_exp)
        self.mark_done_btn.setEnabled(not running and not is_exp)

        self.batch_list.setEnabled(not running)

        # 如果过期了，把按钮的提示文字加上
        if is_exp:
            tip = "您的会员已过期，无法使用投诉相关功能。请联系管理员续费。"
            self.auto_all_btn.setToolTip(tip)
            self.auto_btn.setToolTip(tip)
            self.export_btn.setToolTip(tip)
            self.mark_done_btn.setToolTip(tip)
        else:
            self.auto_all_btn.setToolTip("")
            self.auto_btn.setToolTip("")
            self.export_btn.setToolTip("")
            self.mark_done_btn.setToolTip("")

        if not running:
            self.on_batch_selected(self.batch_list.currentRow())

    def _on_task_finished(self):
        self.auto_running = False
        self.current_signals = None

        if getattr(self, "progress_dialog", None):
            try:
                self.progress_dialog.closed_by_user.disconnect()
                self.progress_dialog.close()
            except Exception:
                pass
            self.progress_dialog = None

        self._set_running_ui(False)

    def _on_dialog_closed(self):
        if not self.auto_running:
            return
        self.auto_running = False
        self.current_signals = None
        self._set_running_ui(False)
        self.progress_dialog = None

    def _on_batch_done(self, batch):
        if batch in self.batches:
            self.batches.remove(batch)
        self._rebuild_batch_list()
        self.refresh_links_signal.emit()

    def _rebuild_batch_list(self):
        self.batch_list.blockSignals(True)
        self.batch_list.clear()
        for i, b in enumerate(self.batches):
            if b:
                cat = b[0].get("cat", "未知分类")
                book = b[0].get("book", "未知作品")
                self.batch_list.addItem(f"[{cat}] {book} ({len(b)} 条)")
            else:
                self.batch_list.addItem(f"第 {i + 1} 批 (0 条)")
        self.batch_list.blockSignals(False)

        if self.batches:
            self.batch_list.setCurrentRow(0)
        else:
            self.queue_table.setRowCount(0)

    # ==================== 历史记录 / 刷新 ====================
    def load_history(self):
        self.history_table.setRowCount(0)
        conn = get_conn()
        query = """
                SELECT complaint_time, book_name, category, COUNT(*) as count
                FROM sites
                WHERE complaint_time IS NOT NULL AND complaint_time != ''
                GROUP BY complaint_time, book_name, category
                ORDER BY complaint_time DESC
                """
        records = conn.execute(query).fetchall()
        conn.close()

        for comp_time, book_name, cat, count in records:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(comp_time))
            self.history_table.setItem(row, 1, QTableWidgetItem(book_name or "未关联"))
            self.history_table.setItem(row, 2, QTableWidgetItem(cat or "未分类"))
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignCenter)
            font = count_item.font()
            font.setBold(True)
            count_item.setFont(font)
            count_item.setForeground(Qt.darkGreen)
            self.history_table.setItem(row, 3, count_item)

    def do_refresh_links(self):
        if hasattr(self.main_window, 'links_page'):
            self.main_window.links_page.refresh_table()
        self.load_history()

    # ==================== 批次管理 ====================
    def load_batches(self, batches):
        self.batches = batches
        self.batch_list.clear()
        for i, batch in enumerate(self.batches):
            if batch:
                cat = batch[0].get("cat", "未知分类")
                book = batch[0].get("book", "未知作品")
                self.batch_list.addItem(f"[{cat}] {book} ({len(batch)} 条)")
            else:
                self.batch_list.addItem(f"第 {i + 1} 批 (0 条)")

        if self.batches:
            self.batch_list.setCurrentRow(0)
            self.tabs.setCurrentIndex(0)

    def clear_batches(self):
        if self.auto_running:
            return
        self.batches = []
        self.batch_list.clear()
        self.queue_table.setRowCount(0)

    def on_batch_selected(self, index):
        if index < 0 or index >= len(self.batches):
            return
        current_batch = self.batches[index]
        self.queue_table.setRowCount(0)
        for row_data in current_batch:
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            self.queue_table.setItem(row, 0, QTableWidgetItem(row_data["book"]))
            self.queue_table.setItem(row, 1, QTableWidgetItem(row_data["cat"]))
            self.queue_table.setItem(row, 2, QTableWidgetItem(row_data["url"]))

        if self.auto_running:
            return

        # ★ 结合权限判断百度和夸克
        if current_batch:
            cat = current_batch[0].get("cat", "")
            if "百度" in cat:
                self.auto_all_btn.setEnabled(False)
                self.auto_all_btn.setText("百度无法全批 (需手动)")
            else:
                # 不是百度，再看有没有过期
                self.auto_all_btn.setEnabled(not license_mgr.is_expired)
                self.auto_all_btn.setText("全批自动投诉 (循环提交)")

    # ==================== 自动投诉入口 ====================
    def trigger_auto_fill(self, is_all=False):
        # ★ 逻辑层拦截，防止绕过 UI
        if license_mgr.is_expired:
            QMessageBox.warning(self, "授权已过期",
                                "您的会员已过期，无法发起自动投诉。\n请前往【个人中心】查看详情或联系管理员续费。")
            return

        if self.auto_running:
            QMessageBox.warning(self, "提示", "自动任务正在运行中，请勿重复点击！")
            return

        if not self.batches:
            QMessageBox.warning(self, "提示", "当前没有可处理的批次数据！")
            return

        if is_all:
            if not self.batches[0]:
                QMessageBox.warning(self, "提示", "首批数据为空，无法开始！")
                return
            target_cat = self.batches[0][0].get("cat", "")
            initial_batch = None
        else:
            index = self.batch_list.currentRow()
            if index < 0 or index >= len(self.batches):
                QMessageBox.warning(self, "提示", "请先选择一个批次！")
                return
            initial_batch = self.batches[index]
            if not initial_batch:
                QMessageBox.warning(self, "提示", "当前批次为空！")
                return
            target_cat = initial_batch[0].get("cat", "")

        if is_all and "百度" in target_cat:
            QMessageBox.warning(self, "提示", "百度投诉需要频繁登录，无法无人值守全批运行，请使用单批填表！")
            return

        self.progress_dialog = ProcessDialog()
        self.progress_dialog.closed_by_user.connect(self._on_dialog_closed)

        self.current_signals = AutoComplaintSignals()
        self.current_signals.progress.connect(self.progress_dialog.update_text)

        self.auto_running = True
        self._set_running_ui(True)

        t = threading.Thread(
            target=self.run_task_thread,
            args=(is_all, target_cat, initial_batch),
        )
        t.daemon = True
        t.start()

        self.progress_dialog.show()

    def run_task_thread(self, is_all, target_cat, initial_batch):
        try:
            is_baidu = "百度" in target_cat

            if not is_all:
                if initial_batch is None:
                    return
                if is_baidu:
                    success = run_baidu(initial_batch, self.current_signals, is_all=False)
                else:
                    success = run_quark(initial_batch, self.current_signals, is_all=False)

                if success:
                    self.mark_specific_batch_done(initial_batch)
            else:
                queue_snapshot = list(self.batches)
                total = len(queue_snapshot)

                for idx, batch in enumerate(queue_snapshot):
                    if not batch:
                        continue
                    cat = batch[0].get("cat", "")
                    book = batch[0].get("book", "未知作品")

                    if "百度" in cat:
                        if self.current_signals:
                            self.current_signals.progress.emit("遇到百度批次，需人工介入，全批暂停！")
                        break

                    remaining = total - idx
                    if self.current_signals:
                        self.current_signals.progress.emit(
                            f"正在处理: [{cat}] {book} (剩余 {remaining} 批)...")

                    success = run_quark(batch, self.current_signals, is_all=True)

                    if success:
                        if self.current_signals:
                            self.current_signals.progress.emit("本批提交成功！正在标记并进入下一批...")
                        self.mark_specific_batch_done(batch)
                        time.sleep(3)
                    else:
                        if self.current_signals:
                            self.current_signals.progress.emit("本批提交失败或遇到验证码，全批任务暂停！")
                        break

        except Exception as e:
            try:
                if self.current_signals:
                    self.current_signals.progress.emit(f"❌ 自动投诉线程异常: {e}")
            except Exception:
                pass
        finally:
            if self.auto_running:
                self.task_finished.emit()

    def mark_specific_batch_done(self, batch):
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_conn()
        try:
            for item in batch:
                conn.execute("UPDATE sites SET complaint_time=? WHERE id=?", (today, item["id"]))
            conn.commit()
        finally:
            conn.close()

        self.batch_done.emit(batch)

    # ==================== 导出 / 手动标记 ====================
    def export_current_batch(self):
        # ★ 逻辑层拦截
        if license_mgr.is_expired:
            QMessageBox.warning(self, "功能受限", "您的授权已过期，无法导出 Excel。")
            return

        index = self.batch_list.currentRow()
        if index < 0:
            return
        current_batch = self.batches[index]
        if not current_batch:
            return

        category_name = current_batch[0].get("cat", "未知分类")
        book_name = current_batch[0].get("book", "未知作品")
        time_str = datetime.now().strftime("%Y%m%d%H%M")
        default_name = f"{book_name}_{category_name}投诉_{time_str}.xlsx"

        path, _ = QFileDialog.getSaveFileName(self, "保存文件", default_name, "Excel 文件 (*.xlsx)")
        if not path:
            return

        try:
            import openpyxl
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Sheet1"

            is_baidu = "百度" in category_name

            if is_baidu:
                ws.cell(row=1, column=1, value="序号")
                ws.cell(row=1, column=2, value="链接名称")
                ws.cell(row=1, column=3, value="链接地址")

                for row_idx, item in enumerate(current_batch, start=2):
                    ws.cell(row=row_idx, column=1, value=row_idx - 1)
                    ws.cell(row=row_idx, column=2, value="盗版链接")
                    ws.cell(row=row_idx, column=3, value=item["url"])
            else:
                ws.cell(row=1, column=1, value="侵权链接")
                ws.cell(row=1, column=2, value="原创链接")
                ws.cell(row=1, column=3, value="作品名（选填）")

                for row_idx, item in enumerate(current_batch, start=2):
                    url = item["url"]
                    b_name = item["book"]
                    p_id = item.get("platform_id", "")
                    original_url = f"https://www.jjwxc.net/onebook.php?novelid={p_id}" if p_id else "https://www.jjwxc.net/"

                    ws.cell(row=row_idx, column=1, value=url)
                    ws.cell(row=row_idx, column=2, value=original_url)
                    ws.cell(row=row_idx, column=3, value=b_name)

            wb.save(path)
            QMessageBox.information(self, "导出成功", f"已生成适用于【{category_name}】的 Excel 模板！")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def mark_batch_done(self):
        # ★ 逻辑层拦截
        if license_mgr.is_expired:
            QMessageBox.warning(self, "功能受限", "您的授权已过期，无法进行标记。")
            return

        if self.auto_running:
            return
        index = self.batch_list.currentRow()
        if index < 0:
            return
        current_batch = self.batches[index]
        reply = QMessageBox.question(self, "确认", f"确定将这批 ({len(current_batch)}条) 标记为已投诉吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.mark_specific_batch_done(current_batch)