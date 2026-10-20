# login_window.py
import os
import re
import json
import httpx

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QApplication, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor, QAction, QPixmap, QPainter, QPen, QIcon, QColor
from app_paths import DATA_DIR

# ★ 引入重命名后的设备指纹模块和配置
from login_device_id import get_machine_id
from config import SUPABASE_URL, SUPABASE_ANON_KEY, has_supabase_config


def _auth_cache_path():
    return os.path.join(DATA_DIR, "auth_info.json")


# ★ 使用纯代码绘制“眼睛”图标
def create_eye_icon(is_open=True):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(Qt.GlobalColor.darkGray, 1.5)
    painter.setPen(pen)

    if is_open:
        painter.drawEllipse(4, 7, 16, 10)
        painter.setBrush(Qt.GlobalColor.darkGray)
        painter.drawEllipse(9, 9, 6, 6)
    else:
        painter.drawLine(4, 12, 20, 12)
        painter.drawLine(4, 12, 2, 10)
        painter.drawLine(12, 12, 12, 9)
        painter.drawLine(20, 12, 22, 10)

    painter.end()
    return QIcon(pixmap)


class LoginWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("打盗维权系统 - 登录")
        self.setFixedSize(420, 500)
        self.is_register_mode = False

        # ★ 增加非法输入时的浅红色底纹样式 QLineEdit[error="true"]
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; }
            QLabel { color: #333; }
            QLineEdit {
                border: 1px solid #DCDCDC; border-radius: 4px;
                padding: 8px 10px; font-size: 13px; background: #FAFAFA;
            }
            QLineEdit:focus { border: 1px solid #10B981; background: #FFFFFF; }
            QLineEdit[error="true"] { 
                background-color: #FEF2F2; 
                border: 1px solid #EF4444; 
            }
            QPushButton#mainBtn {
                background: #10B981; color: white; font-weight: bold;
                padding: 10px; border: none; border-radius: 4px; font-size: 14px;
            }
            QPushButton#mainBtn:hover { background: #059669; }
            QPushButton#mainBtn:disabled { background: #9CA3AF; }
            QLabel#linkLbl { color: #10B981; font-size: 12px; }
            QLabel#linkLbl:hover { text-decoration: underline; }

            QCheckBox::indicator {
                width: 16px; height: 16px;
                border: 1px solid #DCDCDC; border-radius: 3px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #10B981; 
                border: 1px solid #10B981;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiNmZmZmZmYiIHN0cm9rZS13aWR0aD0iNCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cG9seWxpbmUgcG9pbnRzPSIyMCA2IDkgMTcgNCAxMiI+PC9wb2x5bGluZT48L3N2Zz4=);
            }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(35, 30, 35, 30)
        layout.setSpacing(14)

        self.title_lbl = QLabel("打盗维权系统")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)
        self.title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_lbl)

        self.subtitle = QLabel("请登录后使用")
        self.subtitle.setStyleSheet("color: #888; font-size: 12px;")
        self.subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.subtitle)
        layout.addSpacing(10)

        # ★ 邮箱输入框
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("邮箱")
        # 输入时清除错误状态和底部提示
        self.email_input.textChanged.connect(lambda: self._clear_error(self.email_input))
        # 失去焦点或回车时自动校验
        self.email_input.editingFinished.connect(self._check_email_on_focus_out)
        layout.addWidget(self.email_input)

        # ★ 密码输入框
        self.pwd_input = QLineEdit()
        self.pwd_input.setPlaceholderText("密码（至少6位）")
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.returnPressed.connect(self.on_main_action)
        self.pwd_input.textChanged.connect(lambda: self._clear_error(self.pwd_input))
        self.pwd_input.editingFinished.connect(self._check_pwd_on_focus_out)

        self.toggle_pwd_action = QAction(create_eye_icon(is_open=True), "", self)
        self.toggle_pwd_action.triggered.connect(self._toggle_pwd_visibility)
        self.pwd_input.addAction(self.toggle_pwd_action, QLineEdit.TrailingPosition)
        layout.addWidget(self.pwd_input)

        self.reg_tip_label = QLabel("提示：密码请不要和自己的重要密码相关联，666666也可以。")
        self.reg_tip_label.setStyleSheet("color: #F59E0B; font-size: 12px;")
        self.reg_tip_label.setWordWrap(True)
        self.reg_tip_label.hide()
        layout.addWidget(self.reg_tip_label)

        self.remember_cb = QCheckBox("记住登录状态")
        self.remember_cb.setChecked(True)
        self.remember_cb.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.remember_cb)

        self.tip_label = QLabel("")
        self.tip_label.setStyleSheet("color: #E74C3C; font-size: 12px;")
        self.tip_label.setWordWrap(True)
        self.tip_label.setMinimumHeight(32)
        layout.addWidget(self.tip_label)

        self.main_btn = QPushButton("登 录")
        self.main_btn.setObjectName("mainBtn")
        self.main_btn.setCursor(Qt.PointingHandCursor)
        self.main_btn.clicked.connect(self.on_main_action)
        layout.addWidget(self.main_btn)

        self.switch_lbl = QLabel("还没有账号？点击免费注册试用")
        self.switch_lbl.setObjectName("linkLbl")
        self.switch_lbl.setAlignment(Qt.AlignCenter)
        self.switch_lbl.setCursor(QCursor(Qt.PointingHandCursor))
        self.switch_lbl.mousePressEvent = self.toggle_mode
        layout.addWidget(self.switch_lbl)
        layout.addStretch()

    # ================= ★ 辅助方法：控制浅红底纹与提示 =================

    def _set_input_error(self, widget, is_error):
        """设置输入框是否为错误状态（浅红底纹）"""
        widget.setProperty("error", "true" if is_error else "false")
        # 强制刷新样式
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _clear_error(self, widget):
        """用户重新输入时清除错误状态"""
        self._set_input_error(widget, False)
        self.tip_label.setText("")

    def _check_email_on_focus_out(self):
        """失去焦点时检查邮箱格式（仅在输入不为空时校验）"""
        email = self.email_input.text().strip()
        if not email:
            return
        email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_pattern, email):
            self._set_input_error(self.email_input, True)
            self._show_error("邮箱格式不正确，请检查。")
        else:
            self._set_input_error(self.email_input, False)

    def _check_pwd_on_focus_out(self):
        """失去焦点时检查密码（仅在输入不为空时校验）"""
        pwd = self.pwd_input.text()
        if not pwd:
            return

        has_error = False
        error_msg = ""

        if len(pwd) < 6:
            has_error = True
            error_msg = "密码长度至少为 6 位"
        elif re.search(r'[\u4e00-\u9fa5]', pwd):
            has_error = True
            error_msg = "密码不能包含中文字符"

        if has_error:
            self._set_input_error(self.pwd_input, True)
            self._show_error(error_msg)
        else:
            self._set_input_error(self.pwd_input, False)

    # ================= 核心逻辑 =================

    def _toggle_pwd_visibility(self):
        if self.pwd_input.echoMode() == QLineEdit.Password:
            self.pwd_input.setEchoMode(QLineEdit.Normal)
            self.toggle_pwd_action.setIcon(create_eye_icon(is_open=False))
        else:
            self.pwd_input.setEchoMode(QLineEdit.Password)
            self.toggle_pwd_action.setIcon(create_eye_icon(is_open=True))

    def toggle_mode(self, event):
        self.is_register_mode = not self.is_register_mode

        # 清空所有提示和错误状态
        self.tip_label.setText("")
        self._set_input_error(self.email_input, False)
        self._set_input_error(self.pwd_input, False)

        self.pwd_input.clear()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.toggle_pwd_action.setIcon(create_eye_icon(is_open=True))

        if self.is_register_mode:
            self.title_lbl.setText("注册新账号")
            self.subtitle.setText("请填写邮箱和密码进行注册")
            self.main_btn.setText("注 册")
            self.remember_cb.hide()
            self.reg_tip_label.show()
            self.switch_lbl.setText("已有账号？返回登录")
        else:
            self.title_lbl.setText("打盗维权系统")
            self.subtitle.setText("请登录后使用")
            self.main_btn.setText("登 录")
            self.remember_cb.show()
            self.reg_tip_label.hide()
            self.switch_lbl.setText("还没有账号？点击免费注册试用")

    def on_main_action(self):
        email = self.email_input.text().strip()
        pwd = self.pwd_input.text()

        # 提交前，先重置所有错误状态
        self._set_input_error(self.email_input, False)
        self._set_input_error(self.pwd_input, False)
        self.tip_label.setText("")

        if not email:
            self._set_input_error(self.email_input, True)
            self._show_error("请输入邮箱")
            return
        if not pwd:
            self._set_input_error(self.pwd_input, True)
            self._show_error("请输入密码")
            return

        # ★ 注册模式下的格式校验
        if self.is_register_mode:
            email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
            if not re.match(email_pattern, email):
                self._set_input_error(self.email_input, True)
                self._show_error("请输入正确的邮箱格式（如：name@example.com）")
                return

            if len(pwd) < 6:
                self._set_input_error(self.pwd_input, True)
                self._show_error("密码长度至少为 6 位")
                return

            if re.search(r'[\u4e00-\u9fa5]', pwd):
                self._set_input_error(self.pwd_input, True)
                self._show_error("密码不能包含中文字符")
                return

        self._set_loading(True)
        try:
            if not has_supabase_config():
                self._show_error("未配置 Supabase 服务，请联系开发者。")
                return

            base_url = SUPABASE_URL.rstrip("/")

            if self.is_register_mode:
                self._do_register(base_url, email, pwd)
            else:
                self._do_login(base_url, email, pwd)
        finally:
            self._set_loading(False)

    def _do_register(self, base_url, email, pwd):
        url = f"{base_url}/auth/v1/signup"
        headers = {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}
        payload = {"email": email, "password": pwd}

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        except Exception as e:
            self._show_error(f"网络连接失败：{e}")
            return

        if resp.status_code != 200:
            err_data = resp.json()
            err_msg = err_data.get("msg", "") or err_data.get("error_description", "")
            self._show_error(f"注册失败：{err_msg}")
            return

        QMessageBox.information(self, "注册成功", "账号注册成功，请直接登录。")
        self.toggle_mode(None)

    def _do_login(self, base_url, email, pwd):
        auth_url = f"{base_url}/auth/v1/token?grant_type=password"
        headers = {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}
        payload = {"email": email, "password": pwd}

        try:
            resp = httpx.post(auth_url, json=payload, headers=headers, timeout=15.0)
        except Exception as e:
            self._show_error(f"网络连接失败：{e}")
            return

        if resp.status_code != 200:
            err_data = resp.json()
            err_msg = err_data.get("error_description", "") or err_data.get("msg", "")
            if "Invalid login credentials" in err_msg:
                self._show_error("邮箱或密码错误")
                self._set_input_error(self.pwd_input, True)  # 登录失败密码框变红
            else:
                self._show_error(f"登录失败：{err_msg}")
            return

        auth_data = resp.json()
        access_token = auth_data.get("access_token")
        refresh_token = auth_data.get("refresh_token")
        if not access_token:
            self._show_error("登录失败：未获取到凭证")
            return

        device_id = get_machine_id()
        func_url = f"{base_url}/functions/v1/verify-license"
        func_headers = {"Authorization": f"Bearer {access_token}", "apikey": SUPABASE_ANON_KEY,
                        "Content-Type": "application/json"}

        try:
            resp_func = httpx.post(func_url, json={"device_id": device_id}, headers=func_headers, timeout=30.0)
        except Exception as e:
            self._show_error(f"授权校验网络异常：{e}")
            return

        if resp_func.status_code != 200:
            self._show_error(f"授权校验请求失败 (HTTP {resp_func.status_code})")
            return

        result = resp_func.json()

        if not result.get("ok"):
            reason = result.get("reason", "")
            if reason == "device_limit_reached":
                max_dev = result.get("max", 1)
                reply = QMessageBox.question(self, "设备达到上限",
                                             f"当前账号最多绑 {max_dev} 台设备。\n是否解绑【最早登录的旧设备】以继续？",
                                             QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self._do_reset_device(base_url, func_headers)
                return

            msg_map = {
                "unauthorized": "登录态无效",
                "no_license": "尚未授权，请联系管理员",
                "inactive": "账号已被停用，请联系管理员",
            }
            self._show_error(msg_map.get(reason, f"校验未通过（{reason}）"))
            return

        expires_at = result.get("expires_at")
        user_data = auth_data.get("user", {})
        user_id = user_data.get("id", "")

        metadata = user_data.get("user_metadata", {})
        default_nickname = f"用户_{user_id[:8]}" if user_id else "未知用户"
        nickname = metadata.get("nickname") or default_nickname

        self._save_auth_info(email, nickname, user_id, refresh_token, expires_at)

        from license_manager import license_mgr
        license_mgr.refresh_status()

        if license_mgr.is_expired:
            QMessageBox.warning(
                self, "授权已过期",
                "登录成功，但您的授权已过期。\n\n"
                "您可以进入软件查看历史数据，但无法使用自动投诉、导出维权书等高级功能。\n"
                "如需继续使用，请联系管理员续费。"
            )

        self.accept()

    def _do_reset_device(self, base_url, func_headers):
        reset_url = f"{base_url}/functions/v1/reset-devices"
        try:
            reset_resp = httpx.post(reset_url, headers=func_headers, timeout=30.0)
            if reset_resp.status_code == 200 and reset_resp.json().get("ok"):
                self._show_error("已解绑最早设备！请再次点击“登录”。")
            else:
                r_json = reset_resp.json()
                if r_json.get("reason") == "cooldown":
                    self._show_error(f"解绑失败：冷却中，还需等待 {r_json.get('days_left')} 天。")
                else:
                    self._show_error(f"解绑失败：{r_json}")
        except Exception as e:
            self._show_error(f"解绑网络异常：{e}")

    def _save_auth_info(self, email, nickname, user_id, refresh_token, expires_at):
        try:
            data = {
                "email": email,
                "nickname": nickname,
                "user_id": user_id,
                "refresh_token": refresh_token,
                "expires_at": expires_at
            }
            with open(_auth_cache_path(), "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _set_loading(self, loading: bool):
        self.main_btn.setEnabled(not loading)
        self.main_btn.setText("处理中..." if loading else ("注 册" if self.is_register_mode else "登 录"))
        self.email_input.setEnabled(not loading)
        self.pwd_input.setEnabled(not loading)
        QApplication.processEvents()

    def _show_error(self, msg: str):
        self.tip_label.setText(msg)