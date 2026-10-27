# browser_manager.py
import os
import sys
import time
import subprocess
import threading
import atexit
import shutil
import random
from playwright.sync_api import sync_playwright

try:
    import winreg
except ImportError:
    winreg = None

from app_paths import get_user_dir, DIR_BROWSER_PROFILE, BROWSER_LOCK_FILES, FILE_DEVTOOLS_ACTIVE_PORT
from db_config import get_current_user
from link_picker_injector import get_picker_script
from app_signals import signals
from browser_thread import BrowserThread


class BrowserManager:
    _instance = None
    _init_lock = threading.Lock()

    @classmethod
    def instance(cls):
        # 如果实例不存在，或者 BrowserThread 已死（被 shutdown 过），则重建
        if cls._instance is None or not cls._instance._bt.is_alive():
            with cls._init_lock:
                if cls._instance is None or not cls._instance._bt.is_alive():
                    user_id = get_current_user()
                    if not user_id:
                        raise Exception("未登录")
                    profile_dir = os.path.join(get_user_dir(user_id), DIR_BROWSER_PROFILE)
                    cls._instance = cls(profile_dir)
                    atexit.register(cls._instance.shutdown)
        return cls._instance

    def __init__(self, profile_dir):
        self.profile_dir = profile_dir

        self._bt = BrowserThread()
        self._bt.start()

        self._pw = None
        self._browser = None
        self._context = None

        self._proc = None
        self._shutdown_lock = threading.Lock()

        self.preview_page = None
        self.is_shutting_down = False
        self._picker_injected = False

        self.batch_urls = []
        self.batch_index = 0
        self.batch_ctx = {}
        self._batch_ctx_list = []
        self.window_bounds = None

        self._pull_pending = False
        self._pull_lock = threading.Lock()

        # 新增：全局暂存区（暂存拾取结果，不直接落库）
        self._pending_picks = []
        self._pending_lock = threading.Lock()

        # 新增：用于区分主动关闭还是用户强关
        self._expect_disconnect = False
        # 新增：记录当前上下文，用于新 Tab 继承
        self._current_ctx = None

    def run_in_browser_thread(self, fn, *args, block=True, timeout=None, **kwargs):
        return self._bt.submit(fn, *args, block=block, timeout=timeout, **kwargs)

    def ensure_started(self, minimized=False):
        try:
            self._bt.submit(self._ensure_started_impl, minimized)
        except Exception as e:
            print(f"[BrowserManager] ensure_started 失败: {e}")

    def new_page(self, url=None, force_new=False):
        return self._bt.submit(self._new_page_impl, url, force_new)

    def get_work_page(self, force_new=False, prefer_about_blank=True):
        return self._bt.submit(self._get_work_page_impl, force_new, prefer_about_blank)

    def push_context(self, page, ctx):
        try:
            self._bt.submit(self._push_context_impl, page, ctx)
        except Exception as e:
            print(f"[BrowserManager] push_context 失败: {e}")

    def ensure_injected(self, page):
        try:
            self._bt.submit(self._ensure_injected_impl, page)
        except Exception:
            pass

    def pull_all_queues(self):
        with self._pull_lock:
            if self._pull_pending:
                return
            self._pull_pending = True

        def _job():
            try:
                self._pull_all_queues_impl()
            finally:
                with self._pull_lock:
                    self._pull_pending = False

        try:
            self._bt.submit(_job, block=False)
        except Exception as e:
            with self._pull_lock:
                self._pull_pending = False
            print(f"[BrowserManager] pull_all_queues 失败: {e}")

    def start_batch_preview(self, urls, ctx=None, ctx_list=None, window_bounds=None):
        try:
            self._bt.submit(
                self._start_batch_preview_impl,
                urls, ctx, ctx_list, window_bounds,
                block=False,
            )
        except Exception as e:
            print(f"[BrowserManager] start_batch_preview 失败: {e}")

    def navigate_preview(self, direction):
        try:
            self._bt.submit(self._navigate_preview_impl, direction, block=False)
        except Exception as e:
            print(f"[BrowserManager] navigate_preview 失败: {e}")

    def resolve_short_url(self, url):
        return self._bt.submit(self._resolve_short_url_impl, url)

    # ===== 暂存区管理 API =====
    def get_pending_count(self):
        with self._pending_lock:
            return len(self._pending_picks)

    def take_pending_picks(self):
        with self._pending_lock:
            picks = list(self._pending_picks)
            self._pending_picks.clear()
        return picks

    def clear_pending_picks(self):
        with self._pending_lock:
            self._pending_picks.clear()
        signals.pending_count_changed.emit(0)

    def shutdown(self, force=False):
        with self._shutdown_lock:
            if self.is_shutting_down:
                return
            self.is_shutting_down = True

        self._expect_disconnect = True

        try:
            if force:
                self._kill_proc(hard=True)
                return
            if self._bt.is_alive():
                self._bt.submit(self._shutdown_impl, block=True, timeout=20)
            else:
                self._kill_proc(hard=True)
        except Exception as e:
            print(f"[BrowserManager] shutdown 投递失败: {e}")
            self._kill_proc(hard=True)
        finally:
            try:
                self._bt.stop()
            except Exception:
                pass
            self.is_shutting_down = False
            self._expect_disconnect = False

    def _ensure_started_impl(self, minimized):
        if self._proc is not None and self._proc.poll() is None:
            if self._context is None:
                port = self._read_port_file()
                if port:
                    self._attach(port)
            return
        self._launch_new(minimized=minimized)

    def _launch_new(self, minimized=False):
        os.makedirs(self.profile_dir, exist_ok=True)
        self._cleanup_stale()

        # 强制清理旧资源，防止重启报 Event loop closed
        if self._browser:
            try:
                self._browser.close()
            except:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except:
                pass
        self._browser = None
        self._context = None
        self._pw = None
        self.preview_page = None
        self._picker_injected = False

        exe = self._get_chromium_exe()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        cmd = [
            exe,
            f"--user-data-dir={self.profile_dir}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--no-sandbox",
            "--test-type",
            "--ignore-certificate-errors",
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN",
            f"--user-agent={user_agent}",
            "about:blank",
        ]

        if minimized:
            cmd.append("--start-minimized")
        else:
            cmd.append("--start-maximized")

        self._proc = subprocess.Popen(cmd, creationflags=flags)
        port_file = os.path.join(self.profile_dir, FILE_DEVTOOLS_ACTIVE_PORT)
        port = None
        for _ in range(120):
            if self._proc.poll() is not None:
                raise RuntimeError("浏览器异常退出")
            if os.path.exists(port_file):
                p = self._read_port_file()
                if p:
                    port = p
                    break
            time.sleep(0.1)
        if not port:
            raise RuntimeError("等待调试端口超时")
        time.sleep(0.4)
        self._attach(port)

    def _read_port_file(self):
        f = os.path.join(self.profile_dir, FILE_DEVTOOLS_ACTIVE_PORT)
        if not os.path.exists(f):
            return None
        try:
            with open(f) as fp:
                p = fp.readline().strip()
            return int(p) if p else None
        except Exception:
            return None

    def _cleanup_stale(self):
        for fname in BROWSER_LOCK_FILES:
            path = os.path.join(self.profile_dir, fname)
            try:
                if os.path.islink(path) or os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def _get_chromium_exe(self):
        def get_from_registry(reg_key, exe_name):
            if not winreg:
                return None
            try:
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_key, 0,
                                             winreg.KEY_READ | view)
                        value, _ = winreg.QueryValueEx(key, "Path")
                        winreg.CloseKey(key)
                        if value:
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

        chrome_in_path = shutil.which("chrome.exe")
        if chrome_in_path and os.path.exists(chrome_in_path):
            return chrome_in_path
        chrome_in_reg = get_from_registry(
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe", "chrome.exe")
        if chrome_in_reg:
            return chrome_in_reg
        chrome_paths = [
            os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for path in chrome_paths:
            if path and os.path.exists(path):
                return path

        edge_in_path = shutil.which("msedge.exe")
        if edge_in_path and os.path.exists(edge_in_path):
            return edge_in_path
        raise RuntimeError("找不到可用浏览器")

    def _get_stealth_js(self):
        return """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin' },
                    { name: 'Chrome PDF Viewer' },
                    { name: 'Native Client' }
                ]
            });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel(R) UHD Graphics 620';
                return getParameter.apply(this, arguments);
            };
        """

    def _attach(self, port):
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        self._context = self._browser.contexts[0]

        if not self._picker_injected:
            self._context.add_init_script(self._get_stealth_js())
            self._context.add_init_script(get_picker_script())
            self._picker_injected = True

        self._context.on("page", self._on_new_page)

    def _on_new_page(self, new_page):
        try:
            def _on_load():
                self._ensure_injected_impl(new_page)
                opener_info = {}
                try:
                    opener_page = new_page.opener()
                    if opener_page:
                        opener_info = {"url": opener_page.url, "title": opener_page.title()}
                except Exception:
                    pass

                if self._current_ctx:
                    ctx = dict(self._current_ctx)
                    if opener_info:
                        ctx["_opener_url"] = opener_info["url"]
                        ctx["_opener_title"] = opener_info["title"]
                    self._push_context_impl(new_page, ctx)

            new_page.on("load", _on_load)
        except Exception:
            pass

    def _ensure_injected_impl(self, page):
        try:
            if page.is_closed() or not page.url.startswith("http"):
                return
            exists = page.evaluate("() => !!document.getElementById('__apt_picker_host__')")
            if not exists:
                page.evaluate(get_picker_script())
        except Exception:
            pass

    def _safe_new_page(self):
        try:
            return self._context.new_page()
        except Exception as e:
            err_msg = str(e)
            if ("Target.createTarget" in err_msg
                    or "Target closed" in err_msg
                    or "Connection closed" in err_msg):
                print(f"[BrowserManager] 浏览器连接已断开，正在尝试重启... ({err_msg})")
                try:
                    if self._browser:
                        self._browser.close()
                except Exception:
                    pass
                try:
                    if self._pw:
                        self._pw.stop()
                except Exception:
                    pass
                self._browser = None
                self._context = None
                self._pw = None
                self._picker_injected = False
                self._kill_proc(hard=False)
                self._proc = None
                self._ensure_started_impl(minimized=False)
                return self._context.new_page()
            raise

    def _new_page_impl(self, url=None, force_new=False):
        self._ensure_started_impl(minimized=False)
        page = None

        if not force_new:
            for p in self._context.pages:
                try:
                    if p.url == "about:blank":
                        page = p
                        break
                except Exception:
                    pass

        if page is None:
            page = self._safe_new_page()

        self._force_activate(page)
        if url:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"页面加载超时: {e}")
        self._ensure_injected_impl(page)
        return page

    def _get_work_page_impl(self, force_new=False, prefer_about_blank=True):
        self._ensure_started_impl(minimized=False)

        if force_new:
            return self._safe_new_page()

        try:
            pages = [p for p in self._context.pages if not p.is_closed()]
        except Exception:
            pages = []

        if prefer_about_blank:
            for p in pages:
                try:
                    if p.url == "about:blank":
                        return p
                except Exception:
                    pass

        for p in pages:
            try:
                if p.url not in ("", "about:blank"):
                    return p
            except Exception:
                pass

        return self._safe_new_page()

    def _force_activate(self, page):
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            cdp = self._context.new_cdp_session(page)
            try:
                cdp.send("Page.bringToFront")
            finally:
                cdp.detach()
        except Exception:
            pass
        try:
            page.evaluate("window.focus()")
        except Exception:
            pass

    def _pull_all_queues_impl(self):
        if not self._context:
            return

        finish_requested = False
        save_batch_requested = False   # ★ 新增
        appended = 0

        for page in list(self._context.pages):
            try:
                if page.is_closed():
                    continue
                items = page.evaluate("""() => {
                    if (!window.__aptSaveQueue || window.__aptSaveQueue.length === 0) return [];
                    const q = window.__aptSaveQueue; window.__aptSaveQueue = []; return q;
                }""")
                if not items:
                    continue

                for payload in items:
                    action = payload.get("action", "")

                    if action in ("finish_analyze", "close_browser"):
                        finish_requested = True
                        continue
                    elif action == "save_batch":  # ★ 新增
                        save_batch_requested = True
                        continue
                    elif action == "preview_nav":
                        self._navigate_preview_impl(payload.get("url", ""))
                        continue

                    ctx = payload.get("ctx", {}) or {}
                    is_manual = (ctx.get("pick_origin") == "手动获取")

                    with self._pending_lock:
                        self._pending_picks.append({
                            "url": payload.get("url", ""),
                            "title": payload.get("title", ""),
                            "body": payload.get("body", ""),
                            "source_site": payload.get("source_site", ""),
                            "ctx": ctx,
                            "parent_url": payload.get("parent_url", ""),
                            "parent_title": payload.get("parent_title", ""),
                            "is_manual": is_manual,
                        })
                    appended += 1
            except Exception:
                pass

        if appended > 0:
            total = self.get_pending_count()
            signals.pending_count_changed.emit(total)
            for page in list(self._context.pages):
                try:
                    if not page.is_closed():
                        page.evaluate("(n) => { if (window.__aptUpdateSavedCount) window.__aptUpdateSavedCount(n); }",
                                      total)
                except Exception:
                    pass

        if save_batch_requested:  # ★ 新增
            signals.save_batch_requested.emit()

        if finish_requested:
            signals.manual_pick_finished.emit()

    def _push_context_impl(self, page, ctx):
        try:
            exists = page.evaluate("() => !!document.getElementById('__apt_picker_host__')")
            if not exists:
                page.evaluate(get_picker_script())
            page.evaluate("(c) => { if (window.__aptUpdateCtx) window.__aptUpdateCtx(c); }", ctx)
            page.evaluate("(n) => { if (window.__aptUpdateSavedCount) window.__aptUpdateSavedCount(n); }",
                          self.get_pending_count())
        except Exception:
            pass

    def _start_batch_preview_impl(self, urls, ctx=None, ctx_list=None, window_bounds=None):
        if not urls:
            return
        self.batch_urls = urls
        self.batch_index = 0
        self.batch_ctx = ctx or {}
        self._batch_ctx_list = ctx_list or []
        self.window_bounds = window_bounds
        self._load_preview_url_impl()

    def _load_preview_url_impl(self):
        if not self.batch_urls or self.batch_index < 0 or self.batch_index >= len(self.batch_urls):
            return

        self._ensure_started_impl(minimized=False)

        if self.preview_page is None or self.preview_page.is_closed():
            page = None
            for p in self._context.pages:
                try:
                    if p.url == "about:blank":
                        page = p
                        break
                except Exception:
                    pass
            if page is None:
                page = self._safe_new_page()
            self.preview_page = page
            self.preview_page.on("load", lambda: self._ensure_injected_impl(self.preview_page))

        self._force_activate(self.preview_page)

        if getattr(self, "window_bounds", None):
            try:
                cdp = self._context.new_cdp_session(self.preview_page)
                window_info = cdp.send("Browser.getWindowForTarget")
                window_id = window_info["windowId"]

                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "normal"},
                })

                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {
                        "left": self.window_bounds["left"],
                        "top": self.window_bounds["top"],
                        "width": self.window_bounds["width"],
                        "height": self.window_bounds["height"],
                    },
                })
                cdp.detach()
            except Exception as e:
                print(f"调整浏览器窗口失败: {e}")
            finally:
                self.window_bounds = None

        url = self.batch_urls[self.batch_index]

        base_ctx = dict(self.batch_ctx)
        if self._batch_ctx_list and self.batch_index < len(self._batch_ctx_list):
            per = self._batch_ctx_list[self.batch_index] or {}
            base_ctx.update(per)

        ctx_with_nav = dict(base_ctx)
        ctx_with_nav.update({
            "batch_total": len(self.batch_urls),
            "batch_index": self.batch_index + 1,
        })

        self._current_ctx = dict(ctx_with_nav)

        try:
            try:
                self.preview_page.evaluate(
                    "sessionStorage.removeItem('__aptCtx'); sessionStorage.removeItem('__aptPickingMode');")
            except Exception:
                pass

            self.preview_page.goto(url, wait_until="domcontentloaded", timeout=15000)
            self._ensure_injected_impl(self.preview_page)
            self._push_context_impl(self.preview_page, ctx_with_nav)
        except Exception as e:
            print(f"预览加载失败: {e}")

    def _navigate_preview_impl(self, direction):
        if not self.batch_urls:
            return
        if direction == "next" and self.batch_index < len(self.batch_urls) - 1:
            self.batch_index += 1
            self._load_preview_url_impl()
        elif direction == "prev" and self.batch_index > 0:
            self.batch_index -= 1
            self._load_preview_url_impl()

    def _resolve_short_url_impl(self, url):
        self._ensure_started_impl(minimized=False)
        page = self._safe_new_page()
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=8000)
            except Exception as nav_err:
                if ("interrupted by another navigation" not in str(nav_err)
                        and "ERR_ABORTED" not in str(nav_err)):
                    raise
            try:
                page.mouse.wheel(0, random.randint(200, 500))
                page.wait_for_timeout(700)
            except Exception:
                pass
            return page.url
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _shutdown_impl(self):
        try:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

            self._browser = None
            self._context = None
            self._pw = None
            self.preview_page = None
            self.batch_urls = []
            self._batch_ctx_list = []
            self._picker_injected = False
            self._current_ctx = None

        if self._proc and self._proc.poll() is None:
            try:
                self._proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                print("[BrowserManager] 浏览器未按时退出，terminate()")
                self._kill_proc(hard=False)
        self._proc = None

    def _kill_proc(self, hard=True):
        try:
            if not self._proc or self._proc.poll() is not None:
                return
            if hard:
                self._proc.kill()
            else:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        except Exception:
            pass