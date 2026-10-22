import sqlite3
import os
import subprocess
import json
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QHeaderView, QMessageBox, QButtonGroup, QAbstractItemView,
                               QFileDialog, QTableView, QApplication, QDialog, QGroupBox,
                               QComboBox, QStyledItemDelegate, QStyle, QStylePainter, QStyleOptionComboBox)
from PySide6.QtCore import Qt, QSettings, QItemSelectionModel, QEvent, QPoint, QTimer
from PySide6.QtGui import QColor, QFont, QStandardItemModel, QStandardItem, QPainter, QPolygon
from db_config import get_conn
from feature_extractor import extract_pure_feature, get_platform_category
from data_importer import import_sites_from_file
from ui_components import ExcelFilterProxyModel, FilterHeaderView, CenteredCheckBoxDelegate
from complaint_service import prepare_complaints_data


def draw_arrow(painter, rect):
    """公共函数：绘制灰色常驻小三角"""
    x = rect.right() - 16
    y = rect.center().y() - 2
    points = [QPoint(x, y), QPoint(x + 8, y), QPoint(x + 4, y + 5)]
    painter.setBrush(QColor("#999999"))
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(QPolygon(points))


class LinksTableView(QTableView):
    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            # 如果是第 0 列（勾选列）
            if index.column() == 0:
                sel_model = self.selectionModel()
                is_selected = sel_model.isRowSelected(index.row(), index.parent())
                mods = event.modifiers()

                self.setCurrentIndex(index)

                if mods & (Qt.ControlModifier | Qt.ShiftModifier):
                    if is_selected:
                        sel_model.select(index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
                    else:
                        sel_model.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                else:
                    if is_selected:
                        sel_model.select(index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
                    else:
                        sel_model.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

                event.accept()
                return

            # ★ 第 1 列(作品)、第 2 列(分类)、第 9 列(资源状态)，单击直接进入编辑状态
            elif index.column() in (1, 2, 9):
                model = self.model()
                if index.column() == 9:
                    comp_time = model.index(index.row(), 8).data()  # 第8列是投诉时间
                    if comp_time and str(comp_time).strip():
                        return

                self.setCurrentIndex(index)
                self.edit(index)
                event.accept()
                return

        super().mousePressEvent(event)


class NoWheelComboBox(QComboBox):
    """屏蔽滚轮，且选中（空白）时自身不显示文字，只显示纯白框"""

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)

        if option.currentText == "（空白）":
            option.currentText = ""

        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)


class BookComboDelegate(QStyledItemDelegate):
    """关联作品下拉：强制只能选已有作品"""

    def __init__(self, parent=None, book_list=None):
        super().__init__(parent)
        self.book_list = book_list or []

    def createEditor(self, parent, option, index):
        combo = NoWheelComboBox(parent)
        combo.setStyleSheet("QComboBox { border: 1px solid #ccc; padding-left: 5px; background: #fff; }")
        combo.setFocusPolicy(Qt.StrongFocus)

        for _, name, _, _ in self.book_list:
            combo.addItem(name, name)

        if combo.count() > 0:
            combo.view().setTextElideMode(Qt.ElideNone)
            combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 20)
            QTimer.singleShot(10, combo.showPopup)
        return combo

    def setEditorData(self, editor, index):
        if not editor: return
        text = index.data(Qt.DisplayRole) or ""
        idx = editor.findText(text)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        if not editor: return
        val = editor.currentData()
        if val is None: val = ""
        model.setData(index, val, Qt.EditRole)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#E8F5E9"))
        else:
            painter.fillRect(option.rect, QColor("#FFFFFF"))

        text = index.data(Qt.DisplayRole)
        if text:
            painter.setPen(QColor("#333333"))
            painter.drawText(option.rect.adjusted(5, 0, -20, 0), Qt.AlignLeft | Qt.AlignVCenter, str(text))

        draw_arrow(painter, option.rect)
        painter.restore()


class CategoryComboDelegate(QStyledItemDelegate):
    """资源分类下拉：固定 8 个选项，不允许空白"""

    def createEditor(self, parent, option, index):
        combo = NoWheelComboBox(parent)
        combo.setStyleSheet("QComboBox { border: 1px solid #ccc; padding-left: 5px; background: #fff; }")
        combo.setFocusPolicy(Qt.StrongFocus)

        cats = ["百度网盘", "百度知道", "百度贴吧", "百度搜索", "夸克网盘", "夸克搜索", "uc网盘", "其他"]
        for c in cats:
            combo.addItem(c, c)

        combo.view().setTextElideMode(Qt.ElideNone)
        combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 20)
        QTimer.singleShot(10, combo.showPopup)
        return combo

    def setEditorData(self, editor, index):
        if not editor: return
        text = index.data(Qt.DisplayRole) or ""
        idx = editor.findText(text)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        if not editor: return
        val = editor.currentData()
        if val is None: val = ""
        model.setData(index, val, Qt.EditRole)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#E8F5E9"))
        else:
            painter.fillRect(option.rect, QColor("#FFFFFF"))

        text = index.data(Qt.DisplayRole)
        if text:
            painter.setPen(QColor("#333333"))
            painter.drawText(option.rect.adjusted(5, 0, -20, 0), Qt.AlignLeft | Qt.AlignVCenter, str(text))

        draw_arrow(painter, option.rect)
        painter.restore()


class StatusComboDelegate(QStyledItemDelegate):
    """专门用于“资源状态”列：常驻倒三角，单击展开，屏蔽滚轮，有投诉时间禁改"""

    def createEditor(self, parent, option, index):
        model = index.model()
        comp_time = model.index(index.row(), 8).data()
        if comp_time and str(comp_time).strip():
            return None

        combo = NoWheelComboBox(parent)
        combo.setStyleSheet("QComboBox { border: 1px solid #ccc; padding-left: 5px; background: #fff; }")
        combo.setFocusPolicy(Qt.StrongFocus)

        combo.addItem("（空白）", "")
        combo.addItem("已失效", "已失效")

        combo.view().setTextElideMode(Qt.ElideNone)
        combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 20)
        QTimer.singleShot(10, combo.showPopup)
        return combo

    def setEditorData(self, editor, index):
        if not editor: return
        text = index.data(Qt.DisplayRole)
        if not text or str(text).strip() == "":
            text = "（空白）"
        idx = editor.findText(text)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        if not editor: return
        val = editor.currentData()
        if val is None: val = ""
        model.setData(index, val, Qt.EditRole)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#E8F5E9"))
        else:
            painter.fillRect(option.rect, QColor("#FFFFFF"))

        val = index.data(Qt.DisplayRole)
        text = str(val).strip() if val else ""

        if text == "已失效":
            painter.setPen(QColor("#10B981"))
            font = option.font
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(option.rect.adjusted(5, 0, -20, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        elif text:
            painter.setPen(QColor("#333333"))
            painter.drawText(option.rect.adjusted(5, 0, -20, 0), Qt.AlignLeft | Qt.AlignVCenter, text)

        comp_time = index.model().index(index.row(), 8).data()
        if not (comp_time and str(comp_time).strip()):
            draw_arrow(painter, option.rect)

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            comp_time = model.index(index.row(), 8).data()
            if comp_time and str(comp_time).strip():
                return False
            return True
        return super().editorEvent(event, model, option, index)


class ImportLinksDialog(QDialog):
    def __init__(self, parent_page):
        super().__init__(parent_page)
        self.parent_page = parent_page
        self.setWindowTitle("批量导入盗版链接")
        self.setFixedSize(480, 300)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        group_template = QGroupBox("第一步：下载标准模板")
        group_template.setStyleSheet("QGroupBox { font-weight: bold; color: #333; }")
        layout_template = QVBoxLayout(group_template)

        lbl_tip1 = QLabel("为了确保数据能正确导入，请先下载模板，并按照表头格式填写您的链接信息。")
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

        lbl_tip2 = QLabel("请选择填写好的 Excel (.xlsx) 或 CSV (.csv) 文件进行导入。如果特征码已存在，系统会自动跳过。")
        lbl_tip2.setStyleSheet("color: #666; font-weight: normal;")
        lbl_tip2.setWordWrap(True)
        layout_upload.addWidget(lbl_tip2)

        btn_upload = QPushButton("选择文件并导入")
        btn_upload.setStyleSheet("""
            QPushButton { 
                padding: 8px; background-color: #10B981; color: white;
                border: none; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_upload.clicked.connect(self.upload_file)
        layout_upload.addWidget(btn_upload)

        layout.addWidget(group_upload)
        layout.addStretch()

    def download_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存链接导入模板", "链接导入模板.xlsx", "Excel 文件 (*.xlsx)")
        if not path: return
        try:
            import openpyxl
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "盗版链接"

            headers = ["关联作品(必填)", "资源分类", "资源链接(必填)", "名称", "属性", "投诉时间", "状态"]
            for col, header in enumerate(headers, 1):
                ws.cell(row=1, column=col, value=header)

            for col in range(1, 8):
                ws.column_dimensions[chr(64 + col)].width = 20

            wb.save(path)
            QMessageBox.information(self, "下载成功", f"标准模板已保存至：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"保存模板失败：{e}")

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择导入文件", "",
                                              "表格文件 (*.csv *.xlsx);;CSV 文件 (*.csv);;Excel 文件 (*.xlsx)")
        if not path: return

        try:
            success, duplicate = import_sites_from_file(path)
            self.parent_page.refresh_table()
            QMessageBox.information(self, "导入完成",
                                    f"成功导入了 {success} 条新记录！\n(自动跳过了 {duplicate} 条重复)")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))


class LinksPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.settings = QSettings("AuthorTools", "AntiPiracy")

        self.cat_map = {
            "全部链接": ["全部资源"],
            "百度投诉": ["百度搜索", "百度网盘", "百度知道", "百度贴吧"],
            "夸克投诉": ["夸克搜索", "夸克网盘"],
            "uc投诉": ["uc网盘"],
            "百度搜索": ["百度搜索"],
            "百度网盘": ["百度网盘"],
            "百度知道": ["百度知道"],
            "百度贴吧": ["百度贴吧"],
            "夸克搜索": ["夸克搜索"],
            "夸克网盘": ["夸克网盘"],
            "uc网盘": ["uc网盘"],
            "其他": ["其他"]
        }

        self.book_list = []
        self._is_updating = False

        # ★ 筛选持久化数据结构
        self._current_cat = "全部链接"
        self.filters_by_cat = {}

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self.cat_group = QButtonGroup(self)
        self.cat_group.setExclusive(True)

        btn_style = """
            QPushButton { background-color: #FFFFFF; color: #333333; border: 1px solid #CCCCCC; border-radius: 4px; font-size: 13px; }
            QPushButton:hover { background-color: #F5F5F5; }
            QPushButton:checked { background-color: #10B981; color: #FFFFFF; border: 1px solid #10B981; font-weight: bold; }
        """
        main_btn_style = """
            QPushButton { background-color: #F0F0F0; color: #1F1F1F; border: 1px solid #D0D0D0; border-radius: 4px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #E5E5E5; }
            QPushButton:checked { background-color: #10B981; color: #FFFFFF; border: 1px solid #10B981; }
        """

        filter_v_layout = QVBoxLayout()
        filter_v_layout.setSpacing(12)

        main_row = QHBoxLayout()
        main_row.setSpacing(8)

        lbl_main = QLabel("快捷分组:")
        lbl_main.setStyleSheet("color: #666; font-weight: bold; font-size: 13px;")
        lbl_main.setFixedWidth(65)
        main_row.addWidget(lbl_main)

        all_btn = QPushButton("全部链接")
        all_btn.setCheckable(True)
        all_btn.setStyleSheet(main_btn_style)
        all_btn.setCursor(Qt.PointingHandCursor)
        all_btn.setFixedSize(85, 32)
        self.cat_group.addButton(all_btn)
        main_row.addWidget(all_btn)
        all_btn.setChecked(True)

        baidu_main = QPushButton("百度投诉")
        baidu_main.setCheckable(True)
        baidu_main.setStyleSheet(main_btn_style)
        baidu_main.setCursor(Qt.PointingHandCursor)
        baidu_main.setFixedSize(85, 32)
        self.cat_group.addButton(baidu_main)
        main_row.addWidget(baidu_main)

        quark_main = QPushButton("夸克投诉")
        quark_main.setCheckable(True)
        quark_main.setStyleSheet(main_btn_style)
        quark_main.setCursor(Qt.PointingHandCursor)
        quark_main.setFixedSize(85, 32)
        self.cat_group.addButton(quark_main)
        main_row.addWidget(quark_main)

        uc_main = QPushButton("UC投诉")
        uc_main.setCheckable(True)
        uc_main.setStyleSheet(main_btn_style)
        uc_main.setCursor(Qt.PointingHandCursor)
        uc_main.setFixedSize(85, 32)
        self.cat_group.addButton(uc_main)
        main_row.addWidget(uc_main)

        main_row.addStretch()
        filter_v_layout.addLayout(main_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)

        lbl_sub = QLabel("具体平台:")
        lbl_sub.setStyleSheet("color: #666; font-weight: bold; font-size: 13px;")
        lbl_sub.setFixedWidth(65)
        sub_row.addWidget(lbl_sub)

        sub_names = ["百度网盘", "百度知道", "百度贴吧", "百度搜索", "夸克网盘", "夸克搜索", "uc网盘", "其他"]
        for name in sub_names:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setStyleSheet(btn_style)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(85, 32)
            self.cat_group.addButton(btn)
            sub_row.addWidget(btn)
        sub_row.addStretch()
        filter_v_layout.addLayout(sub_row)

        layout.addLayout(filter_v_layout)

        action_layout = QHBoxLayout()
        tip_label = QLabel("💡 提示：带有淡红底色的单元格为必填项未填写。点击资源状态列可展开修改。")
        tip_label.setStyleSheet("color: #666;")
        action_layout.addWidget(tip_label)

        action_layout.addStretch()

        # ★ 新增：右上角统计提示条
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #666; font-size: 13px;")
        action_layout.addWidget(self.stats_label)

        self.report_btn = QPushButton(" 一键发起投诉 (勾选)")
        self.report_btn.setStyleSheet("""
            QPushButton { background-color: #E74C3C; color: white; padding: 6px 16px; border-radius: 4px; font-weight: bold; } 
            QPushButton:hover { background-color: #C0392B; }
        """)
        self.report_btn.clicked.connect(self.send_to_complaints)
        action_layout.addWidget(self.report_btn)

        import_btn = QPushButton("批量导入表格")
        import_btn.setStyleSheet("""
            QPushButton { 
                background-color: #FFFFFF; color: #333333; border: 1px solid #CCCCCC; 
                border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #F5F5F5; }
        """)
        import_btn.clicked.connect(self.open_import_dialog)
        action_layout.addWidget(import_btn)

        export_btn = QPushButton("导出勾选数据")
        export_btn.setStyleSheet("""
            QPushButton { 
                background-color: #FFFFFF; color: #333333; border: 1px solid #CCCCCC; 
                border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #F5F5F5; }
        """)
        export_btn.clicked.connect(self.export_to_excel)
        action_layout.addWidget(export_btn)

        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.setStyleSheet("color: red; padding: 6px 12px;")
        del_btn.clicked.connect(self.delete_site)
        action_layout.addWidget(del_btn)
        layout.addLayout(action_layout)

        self.model = QStandardItemModel(0, 10, self)
        self.model.setHorizontalHeaderLabels(
            ["勾选", "关联作品(必填)", "资源分类(必填)", "资源链接(必填)", "名称", "属性", "特征码", "抓取状态",
             "投诉时间", "资源状态"])
        self.model.itemChanged.connect(self.on_item_changed)

        self.proxy_model = ExcelFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)

        # ★ 信号绑定：用户点筛选弹窗“确定”或重置筛选时，触发保存和统计更新
        self.proxy_model.filterChanged.connect(self._on_filter_changed)

        self.table = LinksTableView()
        self.table.setModel(self.proxy_model)

        custom_header = FilterHeaderView(Qt.Horizontal, self.table)
        self.table.setHorizontalHeader(custom_header)

        header = self.table.horizontalHeader()
        header.setFixedHeight(35)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.table.verticalHeader().setFixedWidth(35)

        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 120)  # 作品
        self.table.setColumnWidth(2, 100)  # 分类
        # 3 是拉伸列
        self.table.setColumnWidth(4, 60)  # 名称
        self.table.setColumnWidth(5, 60)  # 属性
        self.table.setColumnWidth(6, 90)  # 特征码
        self.table.setColumnWidth(7, 80)  # 抓取状态
        self.table.setColumnWidth(8, 90)  # 投诉时间
        self.table.setColumnWidth(9, 80)  # 资源状态

        self.table.setItemDelegateForColumn(0, CenteredCheckBoxDelegate(self.table))
        self.table.setItemDelegateForColumn(1, BookComboDelegate(self.table, self.book_list))
        self.table.setItemDelegateForColumn(2, CategoryComboDelegate(self.table))
        self.table.setItemDelegateForColumn(9, StatusComboDelegate(self.table))

        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        self.table.setMouseTracking(True)

        self.table.selectionModel().selectionChanged.connect(self.on_selection_changed)

        layout.addWidget(self.table, 1)

        # ★ 1. 监听列宽变化并恢复
        self.table.horizontalHeader().sectionResized.connect(self._save_column_widths)
        self._load_column_widths()

        # ★ 2. 监听分类按钮点击 (不再直接 connect refresh_table，而是走独立槽函数)
        self.cat_group.buttonClicked.connect(self._on_cat_clicked)

        # ★ 3. 恢复分类按钮状态和筛选状态
        self._load_ui_state()

        self.refresh_books()
        self.refresh_table()

    # ================= 状态持久化：列宽 =================
    def _save_column_widths(self):
        if not hasattr(self, '_col_width_timer'):
            self._col_width_timer = QTimer(self)
            self._col_width_timer.setSingleShot(True)
            self._col_width_timer.timeout.connect(self._do_save_column_widths)
        self._col_width_timer.start(400)

    def _do_save_column_widths(self):
        header = self.table.horizontalHeader()
        widths = {}
        for col in range(self.model.columnCount()):
            if col == 3: continue
            widths[str(col)] = header.sectionSize(col)
        self.settings.setValue("links_col_widths", json.dumps(widths))

    def _load_column_widths(self):
        raw = self.settings.value("links_col_widths", "")
        if raw:
            try:
                widths = json.loads(raw)
                header = self.table.horizontalHeader()
                header.blockSignals(True)
                for col_str, width in widths.items():
                    col = int(col_str)
                    if col != 3:
                        header.resizeSection(col, width)
                header.blockSignals(False)
            except Exception:
                pass

    # ================= 状态持久化：分类与筛选 =================
    def _load_ui_state(self):
        # 1. 恢复当前分类按钮
        self._current_cat = self.settings.value("links_current_cat", "全部链接")
        for btn in self.cat_group.buttons():
            if btn.text() == self._current_cat:
                btn.setChecked(True)
                break
        else:
            # 如果没找到 (比如旧版本的名字)，回退到全部链接
            self.cat_group.buttons()[0].setChecked(True)
            self._current_cat = "全部链接"

        # 2. 恢复所有分类的筛选字典
        raw = self.settings.value("links_filters_by_cat", "")
        if raw:
            try:
                self.filters_by_cat = json.loads(raw)
            except Exception:
                self.filters_by_cat = {}

        # 3. 将当前分类的筛选应用到 proxy
        self._apply_filters_to_proxy()

    def _on_cat_clicked(self, btn):
        new_cat = btn.text()
        if new_cat == self._current_cat:
            return

        # 先更新当前分类
        self._current_cat = new_cat

        # 从内存字典中取出新分类的筛选并应用
        self._apply_filters_to_proxy()

        # 保存当前分类名到 QSettings
        self.settings.setValue("links_current_cat", self._current_cat)

        # 刷新表格
        self.refresh_table()

    def _apply_filters_to_proxy(self):
        """把 self.filters_by_cat[self._current_cat] 里的数据应用到 proxy_model"""
        self._is_updating = True
        # 先把原来的清掉
        self.proxy_model.filter_dict.clear()

        # 取出当前分类的筛选字典 (格式: {"列index": [允许的值...]})
        cat_filter = self.filters_by_cat.get(self._current_cat, {})
        for col_str, allowed_list in cat_filter.items():
            self.proxy_model.filter_dict[int(col_str)] = set(allowed_list)

        self.proxy_model.invalidateFilter()
        # 强制刷新表头
        self.table.horizontalHeader().viewport().update()
        self._is_updating = False

    def _on_filter_changed(self):
        """用户点击了筛选弹窗的确定，或者点了清空"""
        if self._is_updating:
            return

        # 1. 把 proxy 当前的 filter_dict 转成可以被 JSON 序列化的格式
        current_filter = {}
        for col, allowed_set in self.proxy_model.filter_dict.items():
            current_filter[str(col)] = list(allowed_set)

        # 2. 存入内存字典
        self.filters_by_cat[self._current_cat] = current_filter

        # 3. 写入 QSettings
        self.settings.setValue("links_filters_by_cat", json.dumps(self.filters_by_cat))

        # 4. 更新右上角统计条
        self._update_stats()

    # ================= 统计条更新 =================
    def _update_stats(self):
        total_count = max(0, self.model.rowCount() - 15)
        visible_count = max(0, self.proxy_model.rowCount() - 15)
        has_filter = bool(self.proxy_model.filter_dict)

        if not has_filter:
            self.stats_label.setText(f"共 {total_count} 条链接")
            self.stats_label.setStyleSheet("color: #666; font-size: 13px;")
        elif visible_count == 0:
            self.stats_label.setText(f"⚠️ 当前筛选无结果 (共 {total_count} 条)")
            self.stats_label.setStyleSheet("color: #E74C3C; font-size: 13px; font-weight: bold;")
        else:
            self.stats_label.setText(f"筛选结果: {visible_count} / {total_count} 条")
            self.stats_label.setStyleSheet("color: #10B981; font-size: 13px; font-weight: bold;")

    # ================= 其他原有逻辑 =================
    def open_import_dialog(self):
        dialog = ImportLinksDialog(self)
        dialog.exec()

    def export_to_excel(self):
        checked_rows = []
        for row in range(self.model.rowCount()):
            chk_item = self.model.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                url_item = self.model.item(row, 3)
                if url_item and url_item.text().strip():
                    checked_rows.append(row)

        if not checked_rows:
            QMessageBox.warning(self, "提示", "请先在左侧勾选需要导出的数据！")
            return

        current_display = self._current_cat
        default_name = f"盗版链接导出_{current_display}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "保存Excel文件", default_name, "Excel 文件 (*.xlsx)")
        if not path: return

        try:
            import openpyxl
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment

            wb = Workbook()
            ws = wb.active
            ws.title = "盗版链接"

            headers = ["关联作品(必填)", "资源分类", "资源链接(必填)", "名称", "属性", "投诉时间", "状态"]
            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center")

            for row_idx, r in enumerate(checked_rows, start=2):
                book_name = self.model.item(r, 1).text().strip()
                cat = self.model.item(r, 2).text().strip()
                url = self.model.item(r, 3).text().replace(" (重复资源链接)", "").strip()
                name = self.model.item(r, 4).text().strip()
                attr = self.model.item(r, 5).text().strip()
                comp_time = self.model.item(r, 8).text().strip()
                res_status = self.model.item(r, 9).text().strip()

                ws.cell(row=row_idx, column=1, value=book_name)
                ws.cell(row=row_idx, column=2, value=cat)
                ws.cell(row=row_idx, column=3, value=url)
                ws.cell(row=row_idx, column=4, value=name)
                ws.cell(row=row_idx, column=5, value=attr)
                ws.cell(row=row_idx, column=6, value=comp_time)
                ws.cell(row=row_idx, column=7, value=res_status)

            ws.column_dimensions['A'].width = 20
            ws.column_dimensions['B'].width = 15
            ws.column_dimensions['C'].width = 50
            ws.column_dimensions['D'].width = 20
            ws.column_dimensions['E'].width = 20
            ws.column_dimensions['F'].width = 20
            ws.column_dimensions['G'].width = 15

            wb.save(path)
            QMessageBox.information(self, "导出成功", f"已成功导出 {len(checked_rows)} 条勾选数据！")
            folder_path = os.path.dirname(path)
            subprocess.Popen(f'explorer "{folder_path}"')
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"生成 Excel 时出错：{e}")

    def on_selection_changed(self, selected, deselected):
        if self._is_updating: return

        selected_rows = set(idx.row() for idx in selected.indexes())
        deselected_rows = set(idx.row() for idx in deselected.indexes())
        deselected_rows -= selected_rows

        self._is_updating = True
        try:
            for r in deselected_rows:
                src_idx = self.proxy_model.mapToSource(self.proxy_model.index(r, 0))
                item = self.model.item(src_idx.row(), 0)
                if item and item.data(Qt.UserRole) is not None:
                    if item.checkState() != Qt.Unchecked:
                        item.setCheckState(Qt.Unchecked)

            for r in selected_rows:
                src_idx = self.proxy_model.mapToSource(self.proxy_model.index(r, 0))
                item = self.model.item(src_idx.row(), 0)
                if item and item.data(Qt.UserRole) is not None:
                    if item.checkState() != Qt.Checked:
                        item.setCheckState(Qt.Checked)
        finally:
            self._is_updating = False

        self.table.horizontalHeader().viewport().update()

    def send_to_complaints(self):
        missing_rows = []
        for r in range(self.model.rowCount()):
            chk_item = self.model.item(r, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                book = self.model.item(r, 1).text().strip()
                cat = self.model.item(r, 2).text().strip()
                url = self.model.item(r, 3).text().replace(" (重复资源链接)", "").strip()

                if not book or not cat or not url:
                    missing_rows.append(str(r + 1))

        if missing_rows:
            rows_text = "、".join(missing_rows[:10])
            if len(missing_rows) > 10:
                rows_text += " 等"
            QMessageBox.critical(
                self, "⛔ 拦截：必填项缺失",
                f"检测到以下行存在必填项未填写：\n\n👉 第 {rows_text} 行\n\n"
                f"请把红底单元格补充完整后再发起投诉！"
            )
            return

        batches, missing_books = prepare_complaints_data(self.model, self.book_list)

        if not batches:
            QMessageBox.warning(self, "提示", "请先勾选需要投诉的条目！")
            return

        if missing_books:
            missing_str = "、".join(missing_books)
            QMessageBox.critical(
                self, "⛔ 拦截：作品信息不完整",
                f"检测到以下作品未配置【平台作品ID】或未上传【授权书PDF】或未填写【权利人】：\n\n"
                f"👉 {missing_str}\n\n"
                f"请先前往【📚 作品管理】页面，补充完整后再来发起投诉！\n"
            )
            return

        self.main_window.sidebar.setCurrentRow(3)
        self.main_window.complaint_page.load_batches(batches)

    def refresh_books(self):
        conn = get_conn()
        self.book_list = conn.execute("SELECT id, name, platform_id, evidence_path FROM books").fetchall()
        conn.close()
        if hasattr(self, 'table'):
            self.table.setItemDelegateForColumn(1, BookComboDelegate(self.table, self.book_list))

    def on_item_changed(self, item):
        if self._is_updating: return

        row = item.row()
        col = item.column()

        self.update_row_style(row)

        if col == 0:
            self.table.horizontalHeader().viewport().update()
            return

        if col == 3:
            raw_url = item.text().strip()

            current_display = self._current_cat  # ★ 改为使用内存记录的当前分类
            auto_cat = get_platform_category(raw_url)
            sub_cats = ["百度搜索", "百度网盘", "百度知道", "百度贴吧", "夸克搜索", "夸克网盘", "uc网盘"]

            strict_cats = ["百度网盘", "夸克网盘", "uc网盘", "百度贴吧", "百度知道"]

            if current_display in sub_cats:
                if current_display in strict_cats and auto_cat != current_display:
                    msg = f"系统识别该链接可能不属于【{current_display}】。"
                    if auto_cat:
                        msg += f"（系统识别为【{auto_cat}】）"

                    reply = QMessageBox.question(
                        self, "⚠️ 分类不匹配提示",
                        f"{msg}\n\n请核对链接，是否强制将其保留在当前分类下？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )

                    if reply != QMessageBox.Yes:
                        self._is_updating = True
                        item.setText("")
                        self.model.item(row, 2).setText("")
                        self._is_updating = False
                        self.update_row_style(row)
                        self.save_row_to_db(row)
                        return

                self._is_updating = True
                self.model.item(row, 2).setText(current_display)

            elif current_display == "其他":
                self._is_updating = True
                self.model.item(row, 2).setText("其他")
            else:
                self._is_updating = True
                if auto_cat and not self.model.item(row, 2).text().strip():
                    self.model.item(row, 2).setText(auto_cat)

            self._is_updating = True
            pure_code = extract_pure_feature(raw_url)
            self.model.item(row, 6).setText(pure_code)

            db_id = self.model.item(row, 0).data(Qt.UserRole)
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sites WHERE feature_code = ? AND id != ?", (pure_code, db_id or "0"))
            is_duplicate = cursor.fetchone()[0] > 0
            conn.close()

            if is_duplicate:
                base_url = raw_url.replace(" (重复资源链接)", "")
                item.setText(f"{base_url} (重复资源链接)")
                item.setForeground(QColor("red"))
                item.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
            else:
                item.setForeground(QColor("#000000"))
                item.setFont(QFont("Microsoft YaHei", 9, QFont.Normal))
            self._is_updating = False

        self.save_row_to_db(row)

    def update_row_style(self, row):
        items = [self.model.item(row, c) for c in [1, 2, 3]]
        if not all(items): return

        texts = [it.text().replace(" (重复资源链接)", "").strip() for it in items]
        db_id = self.model.item(row, 0).data(Qt.UserRole)

        is_blank_new_row = all(not t for t in texts) and not db_id

        bg_color = QColor("#FADBD8")
        transparent = QColor(0, 0, 0, 0)

        self._is_updating = True
        for i, item in enumerate(items):
            if not is_blank_new_row and not texts[i]:
                item.setBackground(bg_color)
            else:
                item.setBackground(transparent)
        self._is_updating = False

    def save_row_to_db(self, row):
        self._is_updating = True
        db_id = self.model.item(row, 0).data(Qt.UserRole)
        book_name = self.model.item(row, 1).text().strip()
        cat = self.model.item(row, 2).text().strip()
        url = self.model.item(row, 3).text().replace(" (重复资源链接)", "").strip()
        name = self.model.item(row, 4).text().strip()
        attr = self.model.item(row, 5).text().strip()

        code = self.model.item(row, 6).text().strip()
        crawl_status = self.model.item(row, 7).text().strip()
        comp_time = self.model.item(row, 8).text().strip()
        display_status = self.model.item(row, 9).text().strip()

        res_status = "已失效" if display_status == "已失效" else ""

        if not url and not book_name and not cat and not name and not attr and not comp_time:
            if db_id:
                conn = get_conn()
                conn.execute("DELETE FROM sites WHERE id=?", (db_id,))
                conn.commit()
                conn.close()

                self.model.item(row, 0).setData(None, Qt.UserRole)
                self.model.item(row, 6).setText("")
                self.update_row_style(row)

            self._is_updating = False
            return

        book_id = None
        if book_name:
            for b_id, b_n, _, _ in self.book_list:
                if b_n == book_name:
                    book_id = b_id
                    break

        conn = get_conn()
        cursor = conn.cursor()
        try:
            if not db_id:
                cursor.execute('''INSERT INTO sites
                                  (category, site_url, name, attr, feature_code, complaint_time, resource_status,
                                   book_id, book_name, crawl_status)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                               (cat, url, name, attr, code, comp_time, res_status, book_id, book_name, crawl_status))
                conn.commit()
                self.model.item(row, 0).setData(str(cursor.lastrowid), Qt.UserRole)
            else:
                cursor.execute('''UPDATE sites
                                  SET category=?,
                                      site_url=?,
                                      name=?,
                                      attr=?,
                                      feature_code=?,
                                      complaint_time=?,
                                      resource_status=?,
                                      book_id=?,
                                      book_name=?,
                                      crawl_status=?
                                  WHERE id = ?''',
                               (cat, url, name, attr, code, comp_time, res_status, book_id, book_name, crawl_status,
                                db_id))
                conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()
            self._is_updating = False

    def delete_site(self):
        selected_rows = set()
        for index in self.table.selectionModel().selectedRows():
            selected_rows.add(index.row())
        if not selected_rows: return

        reply = QMessageBox.question(self, "确认删除", f"确定要删除选中的 {len(selected_rows)} 行记录吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return

        conn = get_conn()
        for proxy_row in sorted(list(selected_rows), reverse=True):
            proxy_idx = self.proxy_model.index(proxy_row, 0)
            source_idx = self.proxy_model.mapToSource(proxy_idx)
            real_row = source_idx.row()
            db_id = self.model.item(real_row, 0).data(Qt.UserRole)
            if db_id:
                conn.execute("DELETE FROM sites WHERE id=?", (db_id,))
        conn.commit()
        conn.close()
        self.refresh_table()

    def refresh_table(self):
        self._is_updating = True
        self.model.removeRows(0, self.model.rowCount())

        target_cats = self.cat_map.get(self._current_cat, ["全部资源"])

        if target_cats == ["全部资源"]:
            self.report_btn.hide()
        else:
            self.report_btn.show()

        conn = get_conn()
        cursor = conn.cursor()
        query_base = "SELECT id, category, site_url, name, attr, feature_code, complaint_time, resource_status, book_id, book_name, crawl_status FROM sites"

        if target_cats == ["全部资源"]:
            records = cursor.execute(f"{query_base} ORDER BY id ASC").fetchall()
        else:
            placeholders = ','.join(['?'] * len(target_cats))
            query = f"{query_base} WHERE category IN ({placeholders}) OR category IS NULL OR category = '' ORDER BY id ASC"
            records = cursor.execute(query, target_cats).fetchall()

        all_features_query = "SELECT feature_code, COUNT(*) FROM sites GROUP BY feature_code"
        feature_counts = dict(cursor.execute(all_features_query).fetchall())

        for row_data in records:
            db_id, cat, url, name, attr, code, comp_time, res_status, b_id, b_name, crawl_status = row_data
            book_display = ""
            if b_id:
                for bid, bname, _, _ in self.book_list:
                    if bid == b_id:
                        book_display = bname
                        break
            elif b_name:
                book_display = b_name

            chk_item = QStandardItem()
            chk_item.setCheckable(True)
            chk_item.setCheckState(Qt.Unchecked)
            chk_item.setData(str(db_id), Qt.UserRole)

            item_book = QStandardItem(book_display)
            item_cat = QStandardItem(cat or "")
            url_item = QStandardItem(url or "")

            if feature_counts.get(code, 0) > 1:
                url_item.setText(f"{url} (重复资源链接)")
                url_item.setForeground(QColor("red"))
                url_item.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))

            display_status = ""
            if not (comp_time and str(comp_time).strip()):
                display_status = "已失效" if res_status == "已失效" else ""

            item_res_status = QStandardItem(display_status)

            self.model.appendRow([
                chk_item, item_book, item_cat, url_item,
                QStandardItem(name or ""),
                QStandardItem(attr or ""),
                QStandardItem(code or ""),
                QStandardItem(crawl_status or ""),
                QStandardItem(comp_time or ""),
                item_res_status
            ])

            self.update_row_style(self.model.rowCount() - 1)

        conn.close()

        for _ in range(15):
            chk_item = QStandardItem()
            chk_item.setCheckable(True)
            chk_item.setCheckState(Qt.Unchecked)
            chk_item.setData(None, Qt.UserRole)
            self.model.appendRow([chk_item] + [QStandardItem("") for _ in range(9)])

        # ★ 不再清理 filter_dict，交给 _apply_filters_to_proxy 和 _on_filter_changed 管理
        # self.proxy_model.filter_dict.clear()

        # 如果是首次加载或分类发生改变，确保 proxy 应用的是最新保存的筛选
        if not getattr(self, '_initialized_filter', False):
            self._apply_filters_to_proxy()
            self._initialized_filter = True

        self.proxy_model.invalidateFilter()
        self.table.clearSelection()
        self._is_updating = False

        # ★ 更新右上角统计条
        self._update_stats()