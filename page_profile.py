import os
import json
from datetime import datetime, timezone, timedelta

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QMessageBox, QInputDialog, QTextBrowser, QTabWidget, QApplication)
from PySide6.QtCore import Qt

from app_paths import APP_DIR, DATA_DIR


class ProfilePage(QWidget):
    """个人中心页面：账号信息 / 使用帮助"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth_info = None
        self._build_ui()
        self.refresh_profile()

    # ================= 界面搭建 =================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        # 书签样式
        self.tabs.setStyleSheet("""
            QTabWidget::pane { 
                border: 1px solid #E5E7EB; 
                background-color: #FFFFFF;
                border-radius: 0px 6px 6px 6px;
                top: -1px; 
            }
            QTabBar::tab { 
                background: #F3F4F6; 
                color: #6B7280;
                padding: 8px 24px; 
                font-size: 14px;
                border: 1px solid #E5E7EB;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected { 
                background: #FFFFFF; 
                color: #1F2937; 
                font-weight: bold; 
                border: 1px solid #E5E7EB;
                border-bottom: 1px solid #FFFFFF;
            }
            QTabBar::tab:hover:!selected { 
                color: #059669; 
            }
        """)

        self.tabs.addTab(self._create_account_tab(), "个人中心")
        self.tabs.addTab(self._create_help_tab(), "使用帮助")

        layout.addWidget(self.tabs)

    def _create_account_tab(self):
        """个人中心面板（自定义组件排版，间距宽敞）"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(30)

        # 辅助函数：生成一行统一的布局结构
        def create_row(label_text, value_widget):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(20)

            lbl = QLabel(label_text)
            lbl.setFixedWidth(80)
            lbl.setStyleSheet("font-size: 15px; color: #4B5563; font-weight: 500;")

            row.addWidget(lbl)
            row.addWidget(value_widget)
            row.addStretch()
            return row_widget

        # 统一的圆滑小按钮样式
        btn_small_style = """
            QPushButton {
                border: 1px solid #D1D5DB; 
                border-radius: 11px;
                padding: 0px 10px;
                font-size: 12px;
                color: #6B7280;
                background: #FFFFFF;
            }
            QPushButton:hover { 
                background: #F9FAFB; 
                color: #059669; 
                border-color: #059669;
            }
            QPushButton:pressed {
                background: #F3F4F6;
            }
        """

        # --- 行1：昵称 ---
        self.lbl_nickname = QLabel()
        self.lbl_nickname.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")

        self.btn_rename = QPushButton("修改")
        self.btn_rename.setCursor(Qt.PointingHandCursor)
        self.btn_rename.setFixedHeight(22)
        self.btn_rename.setStyleSheet(btn_small_style)
        self.btn_rename.clicked.connect(self.on_rename_clicked)

        nickname_widget = QWidget()
        nickname_layout = QHBoxLayout(nickname_widget)
        nickname_layout.setContentsMargins(0, 0, 0, 0)
        nickname_layout.setSpacing(12)
        nickname_layout.addWidget(self.lbl_nickname)
        nickname_layout.addWidget(self.btn_rename)
        nickname_layout.addStretch()
        layout.addWidget(create_row("昵称", nickname_widget))

        # --- 行2：登录账号 ---
        self.lbl_email = QLabel()
        self.lbl_email.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")
        layout.addWidget(create_row("登录账号", self.lbl_email))

        # --- 行3：授权状况 ---
        self.lbl_vip = QLabel()
        self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")
        layout.addWidget(create_row("授权状况", self.lbl_vip))

        # --- 行4：用户ID ---
        self.lbl_user_id = QLabel()
        self.lbl_user_id.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")

        self.btn_copy_id = QPushButton("复制")
        self.btn_copy_id.setCursor(Qt.PointingHandCursor)
        self.btn_copy_id.setFixedHeight(22)
        self.btn_copy_id.setStyleSheet(btn_small_style)
        self.btn_copy_id.clicked.connect(self.on_copy_id_clicked)

        id_widget = QWidget()
        id_layout = QHBoxLayout(id_widget)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.setSpacing(12)
        id_layout.addWidget(self.lbl_user_id)
        id_layout.addWidget(self.btn_copy_id)
        id_layout.addStretch()
        layout.addWidget(create_row("用户ID", id_widget))

        # --- 行5：注册日期 ---
        self.lbl_created_at = QLabel()
        self.lbl_created_at.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")
        layout.addWidget(create_row("注册日期", self.lbl_created_at))

        # --- 行6：操作（退出登录） ---
        self.btn_logout = QPushButton("退出登录")
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        self.btn_logout.setFixedSize(100, 32)
        self.btn_logout.setStyleSheet("""
            QPushButton {
                background-color: #F87171; color: white; 
                border-radius: 6px; font-size: 13px; font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #EF4444; }
        """)
        self.btn_logout.clicked.connect(self.on_logout_clicked)
        layout.addWidget(create_row("操作", self.btn_logout))

        layout.addStretch()

        return w

    def _create_help_tab(self):
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("""
            QTextBrowser { border: none; background-color: #FFFFFF;
                           padding: 20px; font-size: 14px; color: #333333; }
        """)

        # ★ 智能寻址：先找根目录，找不到就去 _internal 里找（兼容 PyInstaller 6.x 打包）
        help_path = os.path.join(APP_DIR, "help.md")
        if not os.path.exists(help_path):
            help_path = os.path.join(APP_DIR, "_internal", "help.md")

        if os.path.exists(help_path):
            try:
                with open(help_path, "r", encoding="utf-8") as f:
                    browser.setMarkdown(f.read())
            except Exception as e:
                browser.setPlainText(f"读取帮助文档失败：{e}")
        else:
            browser.setPlainText("帮助文档缺失，请在软件目录下创建 help.md 文件。")

        return browser

    # ================= 数据刷新与事件 =================
    def refresh_profile(self):
        self._auth_info = None
        auth_file = os.path.join(DATA_DIR, "auth_info.json")

        from config import is_dev_mode
        if is_dev_mode() and not os.path.exists(auth_file):
            self.lbl_nickname.setText("开发者")
            self.lbl_email.setText("本地模式")
            self.lbl_vip.setText("无限制")
            self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #10B981;")
            self.lbl_user_id.setText("DEV-MODE-0000")
            self.lbl_created_at.setText(datetime.now().strftime("%Y-%m-%d"))
            self.btn_rename.setEnabled(False)
            self.btn_copy_id.setEnabled(False)
            self.btn_logout.setVisible(False)
            return

        if not os.path.exists(auth_file):
            self.lbl_nickname.setText("未登录")
            self.lbl_email.setText("-")
            self.lbl_vip.setText("-")
            self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2937;")
            self.lbl_user_id.setText("-")
            self.lbl_created_at.setText("-")
            self.btn_rename.setEnabled(False)
            self.btn_copy_id.setEnabled(False)
            self.btn_logout.setVisible(False)
            return

        try:
            with open(auth_file, "r", encoding="utf-8") as f:
                info = json.load(f)
        except Exception:
            self.lbl_nickname.setText("读取失败")
            return

        self._auth_info = info
        self.btn_rename.setEnabled(True)
        self.btn_copy_id.setEnabled(True)
        self.btn_logout.setVisible(True)

        email = info.get("email", "")
        user_id = info.get("user_id", "未知")

        # 1. 昵称
        if user_id == "未知":
            self.lbl_nickname.setText("请重新登录")
        else:
            nickname = info.get("nickname", f"用户_{user_id[:8]}")
            self.lbl_nickname.setText(nickname)

        # 2. 登录账号
        if email:
            self.lbl_email.setText(email)
        else:
            self.lbl_email.setText("未知")

        # 3. 用户ID
        self.lbl_user_id.setText(user_id)

        # 4. 注册日期
        created_at_str = info.get("created_at")
        if created_at_str:
            try:
                dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                self.lbl_created_at.setText(dt.strftime("%Y-%m-%d"))
            except Exception:
                self.lbl_created_at.setText(created_at_str)
        else:
            self.lbl_created_at.setText("未知")

        # 5. 授权状况 (显示具体过期时间)
        expires_at_str = info.get("expires_at")
        if not expires_at_str:
            self.lbl_vip.setText("永久有效")
            self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #10B981;")
        else:
            try:
                utc_time = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                beijing_tz = timezone(timedelta(hours=8))
                beijing_time = utc_time.astimezone(beijing_tz)
                expire_date_str = beijing_time.strftime("%Y-%m-%d %H:%M")

                now = datetime.now(beijing_tz)
                days_left = (beijing_time - now).days

                if days_left < 0:
                    self.lbl_vip.setText(f"已过期（{expire_date_str}）")
                    self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #E74C3C;")
                elif days_left <= 7:
                    self.lbl_vip.setText(f"即将过期（剩 {days_left} 天，{expire_date_str} 到期）")
                    self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #E67E22;")
                else:
                    self.lbl_vip.setText(f"正常（{expire_date_str} 到期）")
                    self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #10B981;")
            except Exception:
                self.lbl_vip.setText("未知")
                self.lbl_vip.setStyleSheet("font-size: 16px; font-weight: bold; color: #6B7280;")

    def on_copy_id_clicked(self):
        if self._auth_info:
            user_id = self._auth_info.get("user_id", "")
            if user_id and user_id != "未知":
                QApplication.clipboard().setText(user_id)
                QMessageBox.information(self, "成功", "用户ID已复制到剪贴板！")

    def on_logout_clicked(self):
        reply = QMessageBox.question(self, "退出登录", "确定要退出当前账号吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            auth_file = os.path.join(DATA_DIR, "auth_info.json")
            if os.path.exists(auth_file):
                try:
                    os.remove(auth_file)
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"无法清除本地登录凭证：{e}")
                    return

            QMessageBox.information(self, "已退出", "已退出登录，软件将自动关闭。请重新打开软件进行登录。")
            QApplication.quit()

    def on_rename_clicked(self):
        info = self._auth_info
        if not info:
            QMessageBox.warning(self, "提示", "未找到本地登录信息，请重新登录。")
            return

        user_id = info.get("user_id", "未知")
        if user_id == "未知":
            QMessageBox.warning(self, "提示", "请在修改前，先退出软件重新登录以同步最新数据！")
            return

        nickname = info.get("nickname", f"用户_{user_id[:8]}")
        new_name, ok = QInputDialog.getText(self, "修改昵称", "请输入新的昵称：", text=nickname)
        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()
        if len(new_name) > 20:
            QMessageBox.warning(self, "提示", "昵称不能超过 20 个字符！")
            return

        import httpx
        from config import SUPABASE_URL, SUPABASE_ANON_KEY
        base_url = SUPABASE_URL.rstrip("/")
        refresh_token = info.get("refresh_token")

        if not refresh_token:
            QMessageBox.warning(self, "修改失败", "本地登录凭证缺失，请重启软件重新登录。")
            return

        try:
            token_resp = httpx.post(
                f"{base_url}/auth/v1/token?grant_type=refresh_token",
                json={"refresh_token": refresh_token},
                headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                timeout=10.0
            )
            if token_resp.status_code != 200:
                QMessageBox.warning(self, "修改失败", "登录态已失效，请重新登录。")
                return
            new_access_token = token_resp.json().get("access_token")

            update_resp = httpx.put(
                f"{base_url}/auth/v1/user",
                json={"data": {"nickname": new_name}},
                headers={"apikey": SUPABASE_ANON_KEY,
                         "Authorization": f"Bearer {new_access_token}",
                         "Content-Type": "application/json"},
                timeout=10.0
            )

            if update_resp.status_code == 200:
                info["nickname"] = new_name
                auth_file = os.path.join(DATA_DIR, "auth_info.json")
                with open(auth_file, "w", encoding="utf-8") as f:
                    json.dump(info, f)

                QMessageBox.information(self, "成功", "昵称修改成功！")
                self.refresh_profile()
            else:
                QMessageBox.warning(self, "失败", f"更新失败：{update_resp.text}")

        except Exception as e:
            QMessageBox.critical(self, "网络错误", f"请求超时或失败：{e}")