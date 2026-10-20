import sqlite3
import os
import shutil
import uuid
import re
import csv
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
                               QAbstractItemView, QFileDialog, QSizePolicy, QDialog, QGroupBox,
                               QStyledItemDelegate, QStyle)
from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QColor, QPainter
from db_config import get_conn
from ui_components import CenteredCheckBoxDelegate


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(30)
        self.setToolTip(text)
        super().setText(text)

    def setFullText(self, text):
        self._full_text = text
        self.setToolTip(text)
        self._apply_elide()

    def _apply_elide(self):
        fm = self.fontMetrics()
        avail = max(self.width() - 2, 0)
        super().setText(fm.elidedText(self._full_text, Qt.ElideMiddle, avail))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()


# ================= ID 列专用 delegate：离开单元格立即标红 =================
class IdDelegate(QStyledItemDelegate):
    """平台ID / 百度ID：通过重写 paint 绕过 QSS 限制，实现在选中状态下依然显示红底红字"""
    INVALID_BG = QColor("#FADBD8")
    INVALID_BG_SELECTED = QColor("#F4C2C2")  # 选中时稍深的红色
    INVALID_FG = QColor("#C0392B")
    BORDER_COLOR = QColor("#E9ECEF")
    SELECT_BORDER = QColor("#10B981")  # 选中时画个绿边框

    @staticmethod
    def is_valid(text):
        """空值允许（可先留空后补），非空必须全是英文字母/数字"""
        text = (text or "").strip()
        return (not text) or bool(re.fullmatch(r'[A-Za-z0-9]+', text))

    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole) or ""

        if self.is_valid(text):
            # 合法：走默认逻辑，享受系统的选中效果
            super().paint(painter, option, index)
        else:
            # 非法：强行接管绘制，无视 QSS 的覆盖
            painter.save()

            if option.state & QStyle.State_Selected:
                # 选中状态：画深红底 + 绿边框
                painter.fillRect(option.rect.adjusted(0, 0, 0, -1), self.INVALID_BG_SELECTED)
                painter.setPen(self.SELECT_BORDER)
                painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
            else:
                # 未选中：画淡红底
                painter.fillRect(option.rect.adjusted(0, 0, 0, -1), self.INVALID_BG)

            # 画红字
            painter.setPen(self.INVALID_FG)
            painter.drawText(option.rect.adjusted(4, 0, -4, 0), Qt.AlignLeft | Qt.AlignVCenter, text)

            # 补上 QSS 里的底边框
            painter.setPen(self.BORDER_COLOR)
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

            painter.restore()

    def setModelData(self, editor, model, index):
        # 编辑器关闭时，直接写回模型，paint 会自动根据内容判断是否标红
        text = editor.text().strip()
        model.setData(index, text, Qt.EditRole)


class EvidenceWidget(QWidget):
    def __init__(self, file_path, parent_page, row_index):
        super().__init__()
        self.file_path = file_path
        self.parent_page = parent_page
        self.row_index = row_index

        # ★ 修复提示框变黑的 BUG：删除了导致样式继承污染的 transparent 设置
        # self.setStyleSheet("background-color: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)

        if not self.file_path:
            id_item = parent_page.table.item(row_index, 1) if (parent_page and hasattr(parent_page, 'table')) else None
            db_id = id_item.data(Qt.UserRole) if id_item else ""

            if db_id:
                self.upload_btn = self._link_button("📎 上传维权书", "#00B87C", "#00996A", bold=True)
                self.upload_btn.clicked.connect(self.upload_file)
                layout.addWidget(self.upload_btn)

            layout.addStretch()
        else:
            file_name = os.path.basename(self.file_path)

            self.name_label = ElidedLabel(f"📄 {file_name}")
            self.name_label.setStyleSheet("color: #2C3E50; font-size: 12px; background: transparent;")
            layout.addWidget(self.name_label, 1)

            self.preview_btn = self._link_button("预览", "#3B82F6", "#2563EB")
            self.preview_btn.clicked.connect(self.preview_file)

            self.reupload_btn = self._link_button("重新上传", "#E67E22", "#C96A12")
            self.reupload_btn.clicked.connect(self.upload_file)

            self.delete_btn = self._link_button("删除", "#E74C3C", "#C0392B")
            self.delete_btn.clicked.connect(self.delete_file)

            layout.addWidget(self.preview_btn)
            layout.addWidget(self.reupload_btn)
            layout.addWidget(self.delete_btn)

    def _link_button(self, text, color, hover_color, bold=False):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFlat(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setStyleSheet(f"""
            QPushButton {{
                color: {color};
                background: transparent;
                border: none;
                padding: 2px 2px;
                font-size: 12px;
                {'font-weight: bold;' if bold else ''}
            }}
            QPushButton:hover {{
                color: {hover_color};
                text-decoration: underline;
            }}
            QPushButton:pressed {{
                color: {hover_color};
            }}
        """)
        return btn

    def _row(self):
        table = self.parent_page.table
        idx = table.indexAt(self.mapTo(table.viewport(), self.rect().center()))
        return idx.row() if idx.isValid() else self.row_index

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self.window(), "选择维权书文件", "", "PDF 文件 (*.pdf)")
        if path:
            if not path.lower().endswith('.pdf'):
                QMessageBox.warning(self.window(), "格式错误", "仅支持上传 PDF 格式的维权书文件！")
                return

            row = self._row()
            item = self.parent_page.table.item(row, 1)
            db_id = item.data(Qt.UserRole) if item else None
            platform_id = self.parent_page.table.item(row, 1).text().strip() if self.parent_page.table.item(row,
                                                                                                            1) else ""

            if not db_id:
                QMessageBox.warning(self.window(), "提示", "请先填写作品名称并保存后，再上传维权书！")
                return

            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                data_dir = os.path.join(base_dir, "evidences_data")
                if not os.path.exists(data_dir):
                    os.makedirs(data_dir)

                prefix_id = platform_id if platform_id else f"book_{db_id}"
                safe_prefix = re.sub(r'[\\/:*?"<>|]', '_', prefix_id)

                ext = os.path.splitext(path)[1].lower()
                random_str = uuid.uuid4().hex[:4]
                new_filename = f"{safe_prefix}_作品维权书_{random_str}{ext}"
                new_file_path = os.path.join(data_dir, new_filename)

                shutil.copy2(path, new_file_path)

                conn = get_conn()
                conn.execute("UPDATE books SET evidence_path=? WHERE id=?", (new_file_path, db_id))
                conn.commit()
                conn.close()

                self._remove_old_file_if_owned(self.file_path, new_file_path)

                self.parent_page.refresh_table()
            except Exception as e:
                QMessageBox.warning(self.window(), "错误", f"保存文件失败: {str(e)}")

    def _remove_old_file_if_owned(self, old_path, new_path):
        if not old_path or not os.path.exists(old_path):
            return
        if os.path.abspath(old_path) == os.path.abspath(new_path):
            return
        conn = get_conn()
        try:
            shared = conn.execute("SELECT 1 FROM evidences WHERE file_path=?", (old_path,)).fetchone()
        finally:
            conn.close()
        if shared:
            return
        if "evidences_data" not in old_path:
            return
        try:
            os.remove(old_path)
        except OSError:
            pass

    def preview_file(self):
        if self.file_path and os.path.exists(self.file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.file_path))
        else:
            QMessageBox.warning(self.window(), "提示", "文件不存在，可能已被移动或删除。")

    def delete_file(self):
        # ★ 修复：将 self 改为 self.window()，避免弹窗继承透明背景导致黑屏
        reply = QMessageBox.question(
            self.window(), "确认",
            "确定要删除这份维权书吗？\n\n（只删除维权书.pdf，相关原始证明图片资料不受影响）",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        row = self._row()
        item = self.parent_page.table.item(row, 1)
        db_id = item.data(Qt.UserRole) if item else None
        if not db_id:
            return

        conn = get_conn()
        conn.execute("UPDATE books SET evidence_path=NULL WHERE id=?", (db_id,))
        conn.commit()
        conn.close()

        self._remove_old_file_if_owned(self.file_path, new_path="")
        self.parent_page.refresh_table()


class ImportBooksDialog(QDialog):
    def __init__(self, parent_page):
        super().__init__(parent_page)
        self.parent_page = parent_page
        self.setWindowTitle("批量导入作品")
        self.setFixedSize(480, 300)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        group_template = QGroupBox("第一步：下载标准模板")
        group_template.setStyleSheet("QGroupBox { font-weight: bold; color: #333; }")
        layout_template = QVBoxLayout(group_template)

        lbl_tip1 = QLabel("为了确保数据能正确导入，请先下载模板，并按照表头格式填写您的作品信息。")
        lbl_tip1.setStyleSheet("color: #666; font-weight: normal;")
        lbl_tip1.setWordWrap(True)
        layout_template.addWidget(lbl_tip1)

        btn_download = QPushButton("下载 Excel 模板")
        btn_download.setStyleSheet("""
            QPushButton { 
                padding: 8px; background-color: #F8F9FA; color: #333;
                border: 1px solid #DCDFE6; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #F0F0F0; border-color: #1F1F1F; }
        """)
        btn_download.clicked.connect(self.download_template)
        layout_template.addWidget(btn_download)

        layout.addWidget(group_template)

        group_upload = QGroupBox("第二步：上传已填写的文件")
        group_upload.setStyleSheet("QGroupBox { font-weight: bold; color: #333; }")
        layout_upload = QVBoxLayout(group_upload)

        lbl_tip2 = QLabel("请选择填写好的 Excel (.xlsx) 或 CSV (.csv) 文件进行导入。如果作品名已存在，将会自动跳过。")
        lbl_tip2.setStyleSheet("color: #666; font-weight: normal;")
        lbl_tip2.setWordWrap(True)
        layout_upload.addWidget(lbl_tip2)

        btn_upload = QPushButton("选择文件并导入")
        btn_upload.setStyleSheet("""
            QPushButton { 
                padding: 8px; background-color: #00B87C; color: white;
                border: none; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #00996A; }
        """)
        btn_upload.clicked.connect(self.upload_file)
        layout_upload.addWidget(btn_upload)

        layout.addWidget(group_upload)
        layout.addStretch()

    def download_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存作品导入模板", "作品导入模板.xlsx", "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            import openpyxl
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "作品列表"

            headers = ["平台ID(必填)", "作品名(必填)", "作品曾用名", "笔名", "权利人(必填)", "百度ID(必填)"]
            for col, header in enumerate(headers, 1):
                ws.cell(row=1, column=col, value=header)

            for col in range(1, 7):
                ws.column_dimensions[chr(64 + col)].width = 20

            wb.save(path)
            QMessageBox.information(self, "下载成功", f"标准模板已保存至：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"保存模板失败：{e}")

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择作品数据文件", "", "表格文件 (*.csv *.xlsx)")
        if not path: return

        ext = os.path.splitext(path)[1].lower()
        rows = []
        try:
            if ext == '.csv':
                with open(path, 'r', encoding='utf-8-sig') as f:
                    rows = list(csv.reader(f))
            elif ext == '.xlsx':
                import openpyxl
                wb = openpyxl.load_workbook(path, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    if any(row):
                        rows.append([str(cell) if cell is not None else "" for cell in row])
            else:
                QMessageBox.warning(self, "提示", "不支持的文件格式！")
                return
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"读取文件出错：{e}")
            return

        if not rows or len(rows) <= 1:
            QMessageBox.warning(self, "提示", "文件为空或没有有效数据！")
            return

        header = rows[0]
        col_idx = {"platform_id": 0, "name": 1, "aliases": 2, "pen_name": 3, "rights_holder": 4, "baidu_id": 5}
        for i, h in enumerate(header):
            h_str = str(h).strip().lower()
            if "平台" in h_str or "id" in h_str and "百度" not in h_str:
                col_idx["platform_id"] = i
            elif "作品名" in h_str or "书名" in h_str:
                col_idx["name"] = i
            elif "曾用名" in h_str or "别名" in h_str:
                col_idx["aliases"] = i
            elif "笔名" in h_str:
                col_idx["pen_name"] = i
            elif "权利" in h_str:
                col_idx["rights_holder"] = i
            elif "百度" in h_str:
                col_idx["baidu_id"] = i

        conn = get_conn()
        cursor = conn.cursor()
        success_count = 0
        duplicate_count = 0
        invalid_count = 0

        for row in rows[1:]:
            if len(row) <= col_idx["name"]: continue

            name = str(row[col_idx["name"]]).strip()
            if not name or name == "None": continue

            platform_id = str(row[col_idx["platform_id"]]).strip() if len(row) > col_idx["platform_id"] else ""
            baidu_id = str(row[col_idx["baidu_id"]]).strip() if len(row) > col_idx["baidu_id"] else ""
            aliases = str(row[col_idx["aliases"]]).strip() if len(row) > col_idx["aliases"] else ""
            pen_name = str(row[col_idx["pen_name"]]).strip() if len(row) > col_idx["pen_name"] else ""
            rights = str(row[col_idx["rights_holder"]]).strip() if len(row) > col_idx["rights_holder"] else ""

            if not IdDelegate.is_valid(platform_id) or not IdDelegate.is_valid(baidu_id):
                invalid_count += 1
                continue

            try:
                cursor.execute(
                    "INSERT INTO books (platform_id, baidu_id, name, pen_name, aliases, rights_holder) VALUES (?,?,?,?,?,?)",
                    (platform_id, baidu_id, name, pen_name, aliases, rights))
                success_count += 1
            except sqlite3.IntegrityError as e:
                if "CHECK" in str(e).upper():
                    invalid_count += 1
                else:
                    duplicate_count += 1
                continue

        conn.commit()
        conn.close()

        self.parent_page.refresh_table()

        msg = f"成功导入 {success_count} 部作品！\n跳过重复 {duplicate_count} 部。"
        if invalid_count > 0:
            msg += f"\n\n⚠️ 有 {invalid_count} 条记录因【平台ID/百度ID 含非法字符】被跳过（仅支持英文字母和数字）。"
        QMessageBox.information(self, "导入完成", msg)
        self.accept()


class BooksPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.settings = QSettings("AuthorTools", "AntiPiracy")
        self._is_updating = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title_layout = QHBoxLayout()
        title_label = QLabel("【作品库】")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #1F1F1F;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        tool_layout = QHBoxLayout()
        tool_layout.setSpacing(10)

        tip_label = QLabel("💡 平台ID/百度ID 仅支持英文字母和数字，非法会立即标红。")
        tip_label.setStyleSheet("color: #666;")
        tip_label.setWordWrap(False)
        tool_layout.addWidget(tip_label)
        tool_layout.addStretch()

        common_btn_style = """
            QPushButton { 
                background-color: #FFFFFF; color: #333333; border: 1px solid #CCCCCC; 
                border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #F5F5F5; }
        """

        make_evidence_btn = QPushButton("制作维权书（单选）")
        make_evidence_btn.setStyleSheet("""
            QPushButton { 
                background-color: #00B87C; color: white; border: none; 
                border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #00996A; }
        """)
        make_evidence_btn.clicked.connect(self.go_to_make_evidence)
        tool_layout.addWidget(make_evidence_btn)

        import_btn = QPushButton("批量导入表格")
        import_btn.setStyleSheet(common_btn_style)
        import_btn.clicked.connect(self.open_import_dialog)
        tool_layout.addWidget(import_btn)

        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.setStyleSheet("""
            QPushButton { 
                background-color: #FFFFFF; color: #E74C3C; border: 1px solid #CCCCCC; 
                border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { border-color: #E74C3C; background-color: #FFF0F0; }
        """)
        del_btn.clicked.connect(self.delete_book)
        tool_layout.addWidget(del_btn)

        layout.addLayout(tool_layout)
        layout.addSpacing(10)

        self.table = QTableWidget()
        self.table.setColumnCount(8)

        self.table.setHorizontalHeaderLabels(
            ["选择", "平台ID(必填)", "作品名(必填)", "作品曾用名", "笔名", "权利人(必填)",
             "百度ID(必填)", "维权书(必填)"])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(7, QHeaderView.Interactive)

        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(7, 320)

        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #FFFFFF;
                alternate-background-color: #F8F9FA;
                color: #333333;
                gridline-color: #E9ECEF;
                outline: none;
            }
            QTableWidget::item {
                margin: 0px;
                padding: 0px;
                border-bottom: 1px solid #E9ECEF;
            }
            QTableWidget::item:selected {
                background-color: #E8F5E9;
                color: #333333;
            }
        """)

        self.table.setItemDelegateForColumn(0, CenteredCheckBoxDelegate(self.table))
        self.table.setItemDelegateForColumn(1, IdDelegate(self.table))
        self.table.setItemDelegateForColumn(6, IdDelegate(self.table))

        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked |
            QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)

        self.table.itemChanged.connect(self.on_item_changed)
        self.table.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.table.verticalScrollBar().valueChanged.connect(self.save_scroll)

        layout.addWidget(self.table)
        self.refresh_table()

    def _row_ids_valid(self, row):
        for col in (1, 6):
            cell = self.table.item(row, col)
            if cell and not IdDelegate.is_valid(cell.text()):
                return False
        return True

    def save_scroll(self, value):
        if self._is_updating: return
        self.settings.setValue("books_scroll_pos", value)

    def on_selection_changed(self, selected, deselected):
        if self._is_updating:
            return
        self._is_updating = True
        try:
            selected_rows = set(idx.row() for idx in selected.indexes())
            deselected_rows = set(idx.row() for idx in deselected.indexes())
            deselected_rows -= selected_rows

            for r in deselected_rows:
                chk = self.table.item(r, 0)
                if chk and (chk.flags() & Qt.ItemIsUserCheckable):
                    if chk.checkState() != Qt.Unchecked:
                        chk.setCheckState(Qt.Unchecked)

            for r in selected_rows:
                chk = self.table.item(r, 0)
                if chk and (chk.flags() & Qt.ItemIsUserCheckable) and chk.data(Qt.UserRole):
                    if chk.checkState() != Qt.Checked:
                        chk.setCheckState(Qt.Checked)
        finally:
            self._is_updating = False

    def open_import_dialog(self):
        dialog = ImportBooksDialog(self)
        dialog.exec()

    def go_to_make_evidence(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先在表格中选中一本需要制作维权书的作品！")
            return

        id_item = self.table.item(current_row, 1)
        if not id_item:
            return

        db_id = id_item.data(Qt.UserRole)
        if not db_id:
            QMessageBox.warning(self, "提示", "请先保存该作品后再制作维权书！")
            return

        self.main_window.sidebar.setCurrentRow(5)

        if hasattr(self.main_window, 'evidence_page'):
            ep = self.main_window.evidence_page
            ep.refresh_books()
            ep.tabs.setCurrentWidget(ep.book_tab)

            idx = ep.book_tab.book_combo.findData(int(db_id))
            if idx >= 0:
                if idx == ep.book_tab.book_combo.currentIndex():
                    ep.book_tab.load_materials()
                else:
                    ep.book_tab.book_combo.setCurrentIndex(idx)

    def add_blank_row(self, set_focus=False):
        self._is_updating = True
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)

        chk_item = QTableWidgetItem()
        chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        chk_item.setCheckState(Qt.Unchecked)
        chk_item.setData(Qt.UserRole, "")
        self.table.setItem(row, 0, chk_item)

        id_item = QTableWidgetItem("")
        id_item.setData(Qt.UserRole, "")
        self.table.setItem(row, 1, id_item)

        for i in range(2, 7):
            self.table.setItem(row, i, QTableWidgetItem(""))

        evidence_widget = EvidenceWidget("", self, row)
        self.table.setCellWidget(row, 7, evidence_widget)

        self.table.blockSignals(False)
        self._is_updating = False

        if set_focus:
            self.table.setCurrentCell(row, 1)

    def delete_book(self):
        rows_to_delete = []
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 0)
            if chk and chk.checkState() == Qt.Checked:
                db_id = chk.data(Qt.UserRole)
                if db_id:
                    rows_to_delete.append((r, db_id))

        if not rows_to_delete:
            QMessageBox.information(self.window(), "提示", "请先勾选要删除的作品！（点击行即可勾选）")
            return

        reply = QMessageBox.question(
            self.window(), "确认删除",
            f"确定要删除选中的 {len(rows_to_delete)} 部作品吗？\n\n"
            f"这会同时清空这些作品在 Evidence 页的原始资料记录。",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            conn = get_conn()
            for row, db_id in sorted(rows_to_delete, reverse=True):
                conn.execute("DELETE FROM books WHERE id=?", (db_id,))
                conn.execute("DELETE FROM evidences WHERE owner_type='book' AND owner_key=?", (str(db_id),))
                self.table.removeRow(row)
            conn.commit()
            conn.close()
            self.refresh_table()

    def on_item_changed(self, item):
        if self._is_updating: return
        if item.column() == 0: return
        if item.column() == 7: return

        row = item.row()

        # ★ 整行任一 ID 非法 → 拒绝保存
        if not self._row_ids_valid(row):
            return

        platform_id = self.table.item(row, 1).text().strip() if self.table.item(row, 1) else ""
        name = self.table.item(row, 2).text().strip() if self.table.item(row, 2) else ""

        if not name: return

        alias = self.table.item(row, 3).text().strip() if self.table.item(row, 3) else ""
        pen = self.table.item(row, 4).text().strip() if self.table.item(row, 4) else ""
        rights = self.table.item(row, 5).text().strip() if self.table.item(row, 5) else ""
        baidu_id = self.table.item(row, 6).text().strip() if self.table.item(row, 6) else ""

        id_item = self.table.item(row, 1)
        db_id = id_item.data(Qt.UserRole) if id_item else ""

        conn = get_conn()
        cursor = conn.cursor()
        try:
            if not db_id:
                cursor.execute(
                    "INSERT INTO books (platform_id, baidu_id, name, pen_name, aliases, rights_holder) VALUES (?,?,?,?,?,?)",
                    (platform_id, baidu_id, name, pen, alias, rights))
                conn.commit()
                new_id = str(cursor.lastrowid)
                self.table.blockSignals(True)
                self.table.item(row, 1).setData(Qt.UserRole, new_id)
                chk = self.table.item(row, 0)
                if chk:
                    chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    chk.setData(Qt.UserRole, new_id)
                self.table.blockSignals(False)

                if row == self.table.rowCount() - 1:
                    self.add_blank_row(set_focus=False)
            else:
                cursor.execute(
                    "UPDATE books SET platform_id=?, baidu_id=?, name=?, pen_name=?, aliases=?, rights_holder=? WHERE id=?",
                    (platform_id, baidu_id, name, pen, alias, rights, db_id))
                conn.commit()
        except sqlite3.IntegrityError as e:
            if "CHECK" in str(e).upper():
                QMessageBox.warning(self.window(), "格式错误", "平台ID / 百度ID 仅支持英文字母和数字！")
                self.refresh_table()
            else:
                QMessageBox.warning(self.window(), "冲突", "作品名不能重复！")
        finally:
            conn.close()

        if not db_id:
            self.refresh_table()

    def refresh_table(self):
        self._is_updating = True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        conn = get_conn()

        records = conn.execute(
            "SELECT id, platform_id, baidu_id, name, pen_name, aliases, evidence_path, rights_holder FROM books").fetchall()

        for data in records:
            row = self.table.rowCount()
            self.table.insertRow(row)

            db_id = data[0]
            platform_id = data[1]
            baidu_id = data[2]
            name = data[3]
            pen = data[4]
            alias = data[5]
            evidence_path = data[6]
            rights = data[7]

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk_item.setCheckState(Qt.Unchecked)
            chk_item.setData(Qt.UserRole, str(db_id))
            self.table.setItem(row, 0, chk_item)

            id_item = QTableWidgetItem(str(platform_id) if platform_id else "")
            id_item.setData(Qt.UserRole, str(db_id))
            self.table.setItem(row, 1, id_item)

            self.table.setItem(row, 2, QTableWidgetItem(str(name)))
            self.table.setItem(row, 3, QTableWidgetItem(str(alias) if alias else ""))
            self.table.setItem(row, 4, QTableWidgetItem(str(pen) if pen else ""))
            self.table.setItem(row, 5, QTableWidgetItem(str(rights) if rights else ""))

            baidu_item = QTableWidgetItem(str(baidu_id) if baidu_id else "")
            self.table.setItem(row, 6, baidu_item)

            evidence_widget = EvidenceWidget(evidence_path, self, row)
            self.table.setCellWidget(row, 7, evidence_widget)

        conn.close()

        self.add_blank_row(set_focus=False)

        self.table.blockSignals(False)
        self._is_updating = False

        saved_pos = int(self.settings.value("books_scroll_pos", 0))
        self.table.verticalScrollBar().setValue(saved_pos)