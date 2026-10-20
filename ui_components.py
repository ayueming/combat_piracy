from PySide6.QtWidgets import (QHeaderView, QStyleOptionButton, QApplication,
                               QStyle, QStyledItemDelegate, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QLabel,
                               QLineEdit)
from PySide6.QtCore import (Qt, QSortFilterProxyModel, QPoint, QRect, QEvent,
                            QItemSelection, QItemSelectionModel, QModelIndex)
from PySide6.QtGui import QColor, QPainter, QPolygon, QPen, QPainterPath

# ================= 统一默认样式常量（可被子页面传参覆盖） =================
CHECK_BG_COLOR = "#10B981"
CHECK_MARK_COLOR = "#FFFFFF"
CHECK_BORDER_COLOR = "#DCDCDC"
CHECK_BOX_SIZE = 16
CHECK_BOX_RADIUS = 4

HEADER_BG_COLOR = "#F5F5F5"
HEADER_FILTERED_BG_COLOR = "#FFF3E0"
HEADER_TRIANGLE_COLOR = "#666666"
HEADER_TRIANGLE_ACTIVE_COLOR = "#D32F2F"

ROW_SELECTED_BG = "#E8F5E9"
ROW_HOVER_BG = "#F5F5F5"


# ================= 统一勾选框绘制工具 =================
def draw_checkbox(painter, rect, checked,
                  size=CHECK_BOX_SIZE,
                  radius=CHECK_BOX_RADIUS,
                  bg_color=CHECK_BG_COLOR,
                  mark_color=CHECK_MARK_COLOR,
                  border_color=CHECK_BORDER_COLOR,
                  border_width=1,
                  mark_width=2):
    """
    全软件统一的勾选框绘制工具。
    - 所有 delegate / header 默认都调用它，保证默认视觉一致；
    - 每个参数都可覆盖 → 子页面想“引用默认但改颜色/尺寸”时不用改 ui_components；
    - 子页面想完全自定义时，自己写 delegate，根本不调用它即可。
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    box_x = rect.center().x() - size // 2
    box_y = rect.center().y() - size // 2
    box_rect = QRect(box_x, box_y, size, size)

    if checked:
        painter.setBrush(QColor(bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(box_rect, radius, radius)

        pen = QPen(QColor(mark_color))
        pen.setWidth(mark_width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        # 对勾按 size 比例缩放（基准 16）
        s = size / 16.0
        p1 = QPoint(box_rect.left() + int(4 * s), box_rect.top() + int(8 * s))
        p2 = QPoint(box_rect.left() + int(7 * s), box_rect.top() + int(11 * s))
        p3 = QPoint(box_rect.left() + int(12 * s), box_rect.top() + int(5 * s))
        path = QPainterPath(p1)
        path.lineTo(p2)
        path.lineTo(p3)
        painter.drawPath(path)
    else:
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor(border_color), border_width))
        painter.drawRoundedRect(box_rect, radius, radius)

    painter.restore()


class ExcelFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_dict = {}

    def set_filter(self, column, allowed_values):
        if allowed_values is None:
            self.filter_dict.pop(column, None)
        else:
            self.filter_dict[column] = allowed_values
        self.invalidateFilter()

        if self.parent() and hasattr(self.parent(), 'horizontalHeader'):
            self.parent().horizontalHeader().viewport().update()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        for col, allowed in self.filter_dict.items():
            idx = model.index(source_row, col, source_parent)
            val = model.data(idx, Qt.DisplayRole)
            if val is None:
                val = ""
            if col == 0:
                continue

            if str(val) not in allowed:
                return False
        return True


class CheckListDelegate(QStyledItemDelegate):
    """筛选弹窗内部列表的勾选框 delegate（自动复用 draw_checkbox）。"""

    def __init__(self, parent_widget, list_widget, **style_kwargs):
        super().__init__(list_widget)
        self.parent_widget = parent_widget
        self.list_widget = list_widget
        self.style_kwargs = style_kwargs

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor("#F5F5F5"))

        item = self.list_widget.item(index.row())
        is_checked = item.checkState() == Qt.Checked if item else False

        # ★ 修复核心：构造一个靠左的局部矩形，宽 30px，高同整行
        # 这样 draw_checkbox 就会在这个局部矩形的中心（即距离左侧 15px 处）画勾
        left_box_rect = QRect(rect.left() + 5, rect.top(), 30, rect.height())
        draw_checkbox(painter, left_box_rect, is_checked, **self.style_kwargs)

        # 文本（因为勾选框在左侧占了 35px 左右，所以文本从 40px 开始，刚刚好）
        text = index.data(Qt.DisplayRole)
        text_rect = QRect(rect.left() + 40, rect.top(), rect.width() - 140, rect.height())
        painter.setPen(QColor("#333333"))
        font = option.font
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)

        # hover 时显示“仅筛选此项”
        if option.state & QStyle.State_MouseOver:
            btn_text = "仅筛选此项"
            btn_width = 80
            btn_height = 24
            btn_rect = QRect(rect.right() - btn_width - 10,
                             rect.top() + (rect.height() - btn_height) // 2,
                             btn_width, btn_height)
            painter.setBrush(QColor("#E8F5E9"))
            painter.setPen(QPen(QColor("#10B981"), 1))
            painter.drawRoundedRect(btn_rect, 4, 4)
            painter.setPen(QColor("#10B981"))
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(btn_rect, Qt.AlignCenter, btn_text)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            rect = option.rect
            btn_text = "仅筛选此项"
            btn_width = 80
            btn_height = 24
            btn_rect = QRect(rect.right() - btn_width - 10,
                             rect.top() + (rect.height() - btn_height) // 2,
                             btn_width, btn_height)
            if btn_rect.contains(event.pos()):
                if hasattr(self.parent_widget, 'filter_only_this_row'):
                    self.parent_widget.filter_only_this_row(index.row())
                return True
            item = self.list_widget.item(index.row())
            if item:
                new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)
                if hasattr(self.parent_widget, 'update_select_all_btn_state'):
                    self.parent_widget.update_select_all_btn_state()
                self.list_widget.viewport().update()
            return True
        return super().editorEvent(event, model, option, index)


class AdvancedFilterWidget(QWidget):
    def __init__(self, column, unique_values, current_allowed, parent=None):
        super().__init__(parent)
        self.column = column
        self.unique_values = unique_values
        self.current_allowed = current_allowed
        self.proxy_model = parent.parent().model() if parent else None

        self.setWindowFlags(Qt.Popup)
        self.setFixedWidth(360)
        self.resize(360, 420)

        self.setStyleSheet("""
            QWidget { background-color: #FFFFFF; border-radius: 6px; }
            QListWidget { border: none; outline: none; background-color: transparent; }
            QPushButton { border: none; background: transparent; color: #333; font-size: 13px; padding: 2px 4px; }
            QPushButton:hover { color: #10B981; }
            QLineEdit { border: 1px solid #DCDCDC; border-radius: 4px; padding: 3px 6px; font-size: 12px; background-color: #FAFAFA; }
            QLineEdit:focus { border: 1px solid #10B981; background-color: #FFFFFF; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(2)

        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(self.toggle_select_all)

        btn_invert = QPushButton("反选")
        btn_invert.clicked.connect(self.invert_select)

        btn_dup = QPushButton("重复项")
        btn_dup.clicked.connect(self.select_dup)

        btn_unique = QPushButton("唯一项")
        btn_unique.clicked.connect(self.select_unique)

        def add_separator(lay):
            line = QLabel("|")
            line.setStyleSheet("color: #E0E0E0; font-size: 12px;")
            lay.addWidget(line)

        top_layout.addWidget(self.btn_select_all)
        add_separator(top_layout)
        top_layout.addWidget(btn_invert)
        add_separator(top_layout)
        top_layout.addWidget(btn_dup)
        add_separator(top_layout)
        top_layout.addWidget(btn_unique)
        top_layout.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("模糊筛选...")
        self.search_input.setFixedWidth(85)
        self.search_input.textChanged.connect(self.filter_list_items)
        top_layout.addWidget(self.search_input)

        layout.addLayout(top_layout)

        self.list_widget = QListWidget()
        self.list_widget.setMouseTracking(True)
        self.list_widget.setSelectionMode(QListWidget.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)

        self.delegate = CheckListDelegate(self, self.list_widget)
        self.list_widget.setItemDelegate(self.delegate)
        layout.addWidget(self.list_widget)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(
            "padding: 5px 15px; border: 1px solid #ccc; border-radius: 4px; background-color: #fff;")
        btn_cancel.clicked.connect(self.close)

        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet(
            "background-color: #10B981; color: white; border-radius: 4px; padding: 5px 20px; font-weight: bold;")
        btn_ok.clicked.connect(self.apply_filter)

        bottom_layout.addWidget(btn_cancel)
        bottom_layout.addWidget(btn_ok)
        layout.addLayout(bottom_layout)

        self.populate_list()

    def populate_list(self):
        self.list_widget.clear()
        counts = {}
        model = self.proxy_model.sourceModel()
        for row in range(model.rowCount()):
            idx = model.index(row, self.column)
            val = str(model.data(idx, Qt.DisplayRole) or "")
            counts[val] = counts.get(val, 0) + 1
        sorted_vals = sorted(counts.keys())
        for val in sorted_vals:
            count = counts[val]
            display_text = f"{val if val else '(空白)'} ({count})"
            item = QListWidgetItem(display_text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if val in self.current_allowed else Qt.Unchecked)
            item.setData(Qt.UserRole, val)
            self.list_widget.addItem(item)
        self.update_select_all_btn_state()

    def filter_list_items(self, text):
        text = text.lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text not in item.text().lower())

    def toggle_select_all(self):
        total_count = self.list_widget.count()
        if total_count == 0:
            return
        checked_count = sum(1 for i in range(total_count)
                            if self.list_widget.item(i).checkState() == Qt.Checked)
        target_state = Qt.Unchecked if checked_count == total_count else Qt.Checked
        self.list_widget.blockSignals(True)
        for i in range(total_count):
            self.list_widget.item(i).setCheckState(target_state)
        self.list_widget.blockSignals(False)
        self.update_select_all_btn_state()
        self.list_widget.viewport().update()

    def update_select_all_btn_state(self):
        total_count = self.list_widget.count()
        if total_count == 0:
            self.btn_select_all.setText("全选")
            return
        checked_count = sum(1 for i in range(total_count)
                            if self.list_widget.item(i).checkState() == Qt.Checked)
        self.btn_select_all.setText(f"全选 ({checked_count}/{total_count})")

    def filter_only_this_row(self, row):
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            it.setCheckState(Qt.Checked if i == row else Qt.Unchecked)
        self.list_widget.viewport().update()
        self.apply_filter()

    def invert_select(self):
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
        self.update_select_all_btn_state()
        self.list_widget.viewport().update()

    def select_dup(self):
        counts = {}
        model = self.proxy_model.sourceModel()
        for row in range(model.rowCount()):
            val = str(model.data(model.index(row, self.column), Qt.DisplayRole) or "")
            counts[val] = counts.get(val, 0) + 1
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            val = it.data(Qt.UserRole)
            it.setCheckState(Qt.Checked if counts.get(val, 0) > 1 else Qt.Unchecked)
        self.update_select_all_btn_state()
        self.list_widget.viewport().update()

    def select_unique(self):
        counts = {}
        model = self.proxy_model.sourceModel()
        for row in range(model.rowCount()):
            val = str(model.data(model.index(row, self.column), Qt.DisplayRole) or "")
            counts[val] = counts.get(val, 0) + 1
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            val = it.data(Qt.UserRole)
            it.setCheckState(Qt.Checked if counts.get(val, 0) == 1 else Qt.Unchecked)
        self.update_select_all_btn_state()
        self.list_widget.viewport().update()

    def apply_filter(self):
        selected_vals = set()
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.checkState() == Qt.Checked:
                selected_vals.add(it.data(Qt.UserRole))
        if len(selected_vals) == self.list_widget.count():
            self.proxy_model.set_filter(self.column, None)
        else:
            self.proxy_model.set_filter(self.column, selected_vals)
        self.close()


class FilterHeaderView(QHeaderView):
    """全软件统一表头：第 0 列全选，其余列点击打开筛选弹窗。"""

    def __init__(self, orientation, parent=None,
                 header_bg=HEADER_BG_COLOR,
                 header_filtered_bg=HEADER_FILTERED_BG_COLOR,
                 triangle_color=HEADER_TRIANGLE_COLOR,
                 triangle_active_color=HEADER_TRIANGLE_ACTIVE_COLOR,
                 **check_style_kwargs):
        super().__init__(orientation, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.active_popup = None

        self.header_bg = header_bg
        self.header_filtered_bg = header_filtered_bg
        self.triangle_color = triangle_color
        self.triangle_active_color = triangle_active_color
        self.check_style_kwargs = check_style_kwargs

    def paintSection(self, painter, rect, logical_index):
        if logical_index == -1:
            painter.fillRect(rect, QColor(self.header_bg))
            return

        model = self.parent().model()

        # 第 0 列：全选
        if logical_index == 0:
            painter.fillRect(rect, QColor(self.header_bg))
            all_checked = True
            has_data = False
            for row in range(model.rowCount()):
                idx = model.index(row, 0)
                if not model.data(idx, Qt.UserRole):
                    continue
                has_data = True
                if model.data(idx, Qt.CheckStateRole) != Qt.Checked:
                    all_checked = False
                    break
            if not has_data:
                all_checked = False
            draw_checkbox(painter, rect, all_checked, **self.check_style_kwargs)
            return

        # 其它列
        is_filtered = hasattr(model, 'filter_dict') and logical_index in model.filter_dict
        painter.save()
        painter.fillRect(rect, QColor(self.header_filtered_bg if is_filtered else self.header_bg))
        super().paintSection(painter, rect, logical_index)
        painter.restore()

        # 筛选三角
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(self.triangle_active_color if is_filtered else self.triangle_color))
        painter.setPen(Qt.NoPen)
        tw, th = 8, 5
        x = rect.right() - 16
        y = rect.top() + (rect.height() - th) / 2
        painter.drawPolygon(QPolygon([QPoint(x, y),
                                      QPoint(x + tw, y),
                                      QPoint(x + tw / 2, y + th)]))
        painter.restore()

    def mousePressEvent(self, event):
        logical_index = self.logicalIndexAt(event.pos())
        if logical_index != -1:
            if logical_index == 0:
                self.toggle_all_visible()
            else:
                self.show_advanced_filter(logical_index, event.globalPos())
        super().mousePressEvent(event)

    def toggle_all_visible(self):
        view = self.parent()
        model = view.model()
        sel_model = view.selectionModel()

        valid_rows = [r for r in range(model.rowCount())
                      if model.data(model.index(r, 0), Qt.UserRole)]
        if not valid_rows:
            return

        all_selected = all(sel_model.isRowSelected(r, model.index(r, 0).parent())
                           for r in valid_rows)

        if all_selected:
            sel_model.clearSelection()
        else:
            last_col = model.columnCount() - 1
            selection = QItemSelection()
            for r in valid_rows:
                selection.select(model.index(r, 0), model.index(r, last_col))
            sel_model.select(selection,
                             QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def show_advanced_filter(self, column, global_pos):
        view = self.parent()
        model = view.model()
        source_model = model.sourceModel() if hasattr(model, 'sourceModel') else model
        unique_values = set()
        for row in range(source_model.rowCount()):
            val = source_model.data(source_model.index(row, column), Qt.DisplayRole)
            unique_values.add(str(val) if val is not None else "")
        current_allowed = model.filter_dict.get(column, unique_values)
        if self.active_popup:
            self.active_popup.close()
        self.active_popup = AdvancedFilterWidget(column, unique_values, current_allowed, self)
        screen = QApplication.screenAt(global_pos)
        if screen:
            sr = screen.availableGeometry()
            x = global_pos.x()
            y = global_pos.y() + 20
            w = self.active_popup.width()
            h = self.active_popup.height()
            if x + w > sr.right():
                x = x - w + 20
            if y + h > sr.bottom():
                y = global_pos.y() - h - 10
            self.active_popup.move(x, y)
        else:
            self.active_popup.move(global_pos.x(), global_pos.y() + 20)
        self.active_popup.show()


class CenteredCheckBoxDelegate(QStyledItemDelegate):
    """
    主表格统一勾选框 delegate。
    - 默认样式与全局一致；
    - 想改颜色/尺寸，构造时传参即可（无需改本文件）；
    - 想完全自定义，自己写 delegate 就好（本类不会被调用）。
    """

    def __init__(self, parent=None,
                 selected_bg=ROW_SELECTED_BG,
                 hover_bg=ROW_HOVER_BG,
                 **style_kwargs):
        super().__init__(parent)
        self.selected_bg = selected_bg
        self.hover_bg = hover_bg
        self.style_kwargs = style_kwargs

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(self.selected_bg))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor(self.hover_bg))

        checked = (index.data(Qt.CheckStateRole) == Qt.Checked) or \
                  bool(option.state & QStyle.State_Selected)

        draw_checkbox(painter, option.rect, checked, **self.style_kwargs)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            return True
        return super().editorEvent(event, model, option, index)