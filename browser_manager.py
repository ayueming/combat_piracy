# browser_manager.py
import os
import sys
import time
import subprocess
import threading
import atexit
import shutil
from playwright.sync_api import sync_playwright

# 兼容非 Windows 系统导入 winreg
try:
    import winreg
except ImportError:
    winreg = None

# ★ 引入路径和用户配置
from app_paths import get_user_dir
from db_config import get_current_user


class BrowserManager:
    _instance = None
    _init_lock = threading.Lock()

    @classmethod
    def instance(cls):
        """全自动单例入口，无需传参"""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    user_id = get_current_user()
                    if not user_id:
                        raise Exception("未登录，无法启动浏览器")

                    # 统一存到 data/users/你的id/browser_profile/
                    profile_dir = os.path.join(get_user_dir(user_id), "browser_profile")
                    cls._instance = cls(profile_dir)
                    atexit.register(cls._instance.shutdown)
        return cls._instance

    def __init__(self, profile_dir):
        self.profile_dir = profile_dir
        self._proc = None
        self._pw = None
        self._browser = None
        self._context = None
        self._lock = threading.Lock()

    def _get_chromium_exe(self):
        """
        ★ 终极查找策略：
        1. 查环境变量 (PATH)
        2. 查注册表 (App Paths)
        3. 查常规硬编码路径
        4. 查 Playwright 自带目录
        """

        def get_from_registry(reg_key, exe_name):
            if not winreg:
                return None
            try:
                # 尝试读取 64 位和 32 位注册表
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_key, 0, winreg.KEY_READ | view)
                        value, _ = winreg.QueryValueEx(key, "Path")
                        winreg.CloseKey(key)
                        if value:
                            # 注册表可能返回目录，也可能直接返回 exe 路径
                            if value.lower().endswith(".exe"):
                                if os.path.exists(value):
                                    return value
                            else:
                                exe_path = os.path.join(value, exe_name)
                                if os.path.exists(exe_path):
                                    return exe_path
                    except Exception:
                        pass
            except Exception:
                pass
            return None

        # ================= 1. 找 Google Chrome =================
        # 1.1 环境变量
        chrome_in_path = shutil.which("chrome.exe")
        if chrome_in_path and os.path.exists(chrome_in_path):
            return chrome_in_path

        # 1.2 注册表
        chrome_in_reg = get_from_registry(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                                          "chrome.exe")
        if chrome_in_reg:
            return chrome_in_reg

        # 1.3 常规路径（使用 os.path.join 规避转义字符警告）
        chrome_paths = [
            os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for path in chrome_paths:
            if path and os.path.exists(path):
                return path

        # ================= 2. 找 Microsoft Edge =================
        # 2.1 环境变量
        edge_in_path = shutil.which("msedge.exe")
        if edge_in_path and os.path.exists(edge_in_path):
            return edge_in_path

        # 2.2 注册表
        edge_in_reg = get_from_registry(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe", "msedge.exe")
        if edge_in_reg:
            return edge_in_reg

        # 2.3 常规路径
        edge_paths = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
        for path in edge_paths:
            if path and os.path.exists(path):
                return path

        # ================= 3. 找 Playwright 自带的 Chromium =================
        # ★ 绝对不在这里启动 sync_playwright，只查路径，防止 asyncio 冲突
        base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        if not base:
            if getattr(sys, "frozen", False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.abspath(__file__))

            for sub in ("ms-playwright", "_internal/ms-playwright"):
                p = os.path.join(base, sub)
                if os.path.isdir(p):
                    base = p
                    break

        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                # 过滤掉 headless_shell，只找带界面的版本
                if name.startswith("chromium-") and not name.startswith("chromium_headless_shell"):
                    exe = os.path.join(base, name, "chrome-win", "chrome.exe")
                    if os.path.exists(exe):
                        return exe

        raise RuntimeError("找不到任何可用的浏览器 (Chrome/Edge/Playwright)")

    def ensure_started(self):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            port = self._read_port_file()
            if port:
                try:
                    self._attach(port)
                    return
                except Exception:
                    self._cleanup_stale()
            self._launch_new()

    def _read_port_file(self):
        f = os.path.join(self.profile_dir, "DevToolsActivePort")
        if not os.path.exists(f):
            return None
        try:
            with open(f) as fp:
                p = fp.readline().strip()
            return int(p) if p else None
        except Exception:
            return None

    def _cleanup_stale(self):
        for fname in ("DevToolsActivePort", "SingletonLock", "SingletonCookie", "SingletonSocket"):
            path = os.path.join(self.profile_dir, fname)
            try:
                if os.path.islink(path) or os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def _launch_new(self):
        os.makedirs(self.profile_dir, exist_ok=True)
        self._cleanup_stale()
        exe = self._get_chromium_exe()

        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW

        self._proc = subprocess.Popen(
            [
                exe,
                f"--user-data-dir={self.profile_dir}",
                "--remote-debugging-port=0",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--start-maximized",
                # ★ 防闪退参数（针对无管理员权限或精简系统）
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # ★ 强制启动时打开干净的空白页，避免 chrome://newtab 拦截跳转
                "about:blank"
            ],
            creationflags=flags,
        )

        port_file = os.path.join(self.profile_dir, "DevToolsActivePort")
        port = None
        for _ in range(120):
            if self._proc.poll() is not None:
                raise RuntimeError("浏览器异常退出，可能用户配置被占用。")
            if os.path.exists(port_file):
                p = self._read_port_file()
                if p:
                    port = p
                    break
            time.sleep(0.1)
        if not port:
            raise RuntimeError("等待浏览器调试端口超时")
        time.sleep(0.4)
        self._attach(port)

    def _attach(self, port):
        # 清理残留的 pw 实例，防止 asyncio 报错
        if self._pw:
            try:
                self._pw.stop()
            except:
                pass

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        self._context = self._browser.contexts[0]

        # 隐藏 webdriver 特征
        stealth_js = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """
        self._context.add_init_script(stealth_js)

    def _force_activate(self, page):
        """多重保险：把目标页强制切到浏览器前台"""
        try:
            page.bring_to_front()
        except Exception:
            pass

        try:
            cdp = self._context.new_cdp_session(page)
            try:
                cdp.send("Page.bringToFront")
            finally:
                try:
                    cdp.detach()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            page.evaluate("window.focus()")
        except Exception:
            pass

    def new_page(self, url=None):
        self.ensure_started()

        page = None
        # 精准复用 about:blank 空白页
        for p in self._context.pages:
            try:
                if p.url == "about:blank":
                    page = p
                    break
            except Exception:
                pass

        if page is None:
            page = self._context.new_page()

        # 切到前台
        self._force_activate(page)

        if url:
            try:
                # 使用 commit 立即返回，绝不卡 UI
                page.goto(url, wait_until="commit", timeout=10000)
            except Exception as e:
                print(f"页面正在后台加载中（超时忽略）: {e}")

        return page

    def shutdown(self):
        try:
            if self._browser: self._browser.close()
        except Exception:
            pass
        try:
            if self._pw: self._pw.stop()
        except Exception:
            pass
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except Exception:
                    self._proc.kill()
        except Exception:
            pass