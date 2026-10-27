# search_crawl_service.py
import random
import time
from PySide6.QtWidgets import QApplication
from browser_manager import BrowserManager
from app_data.search_templates import get_search_url
from app_data.crawl_consts import CRAWL_MAX_PAGES, CRAWL_PAGE_TIMEOUT_MS
from search_crawl_strategies import get_crawl_strategy


def _simulate_human_scroll(page):
    try:
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(400, 900))
            page.wait_for_timeout(random.randint(300, 800))
        if random.random() > 0.4:
            page.mouse.wheel(0, -random.randint(100, 300))
            page.wait_for_timeout(random.randint(200, 500))
    except Exception:
        pass


def _find_next_page(page, selectors):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                return loc
        except Exception:
            pass
    return None


def _click_next_page(page, next_btn, paging_wait_ms_range, on_progress):
    try:
        next_btn.scroll_into_view_if_needed(timeout=2000)
        page.wait_for_timeout(random.randint(500, 1000))
    except Exception:
        pass

    wait_ms = random.uniform(*paging_wait_ms_range)
    on_progress(f"翻页...等待 {wait_ms / 1000:.1f} 秒防封")

    try:
        box = next_btn.bounding_box()
        if box:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            next_btn.click(timeout=5000)
    except Exception:
        try:
            next_btn.dispatch_event("click")
        except Exception:
            pass

    page.wait_for_timeout(wait_ms)


def run_search(platform, keyword, ctx, callbacks, stop_event=None, pause_event=None):
    """
    同步执行一次搜索抓取。
    ★ 整个流程投递到 BrowserThread：page 从头到尾只在浏览器线程里被操作，
      内部的 bm.new_page / bm.push_context / bm.pull_all_queues 会因重入判断直接执行。
    """
    bm = BrowserManager.instance()
    return bm.run_in_browser_thread(
        _run_search_impl,
        platform, keyword, ctx, callbacks, stop_event, pause_event,
        block=True, timeout=None,
    )


def _run_search_impl(platform, keyword, ctx, callbacks, stop_event=None, pause_event=None):
    """只在 BrowserThread 内运行；对 page 的所有操作都是安全的。"""
    on_progress = callbacks.get("on_progress") or (lambda msg: None)
    on_page_scanned = callbacks.get("on_page_scanned") or (lambda count: None)
    on_finished = callbacks.get("on_finished") or (lambda ok, total, err: None)

    strategy = get_crawl_strategy(platform)
    scanned_total = 0

    max_pages = ctx.get("max_pages", CRAWL_MAX_PAGES)
    paging_mode = strategy.get("paging_mode", "click")

    empty_scan_count = 0
    MAX_EMPTY_SCANS = 3

    bm = BrowserManager.instance()

    try:
        is_exact = bool(ctx.get("is_exact", False))
        url = get_search_url(platform, keyword, exact=is_exact)

        page = bm.new_page(url, force_new=True)   # 重入：直接在当前线程执行

        push_ctx = {
            "book_id": ctx.get("book_id"),
            "book_name": ctx.get("book_name"),
            "keyword": keyword,
            "source_platform": platform,
            "source_url": url,
            "batch_id": ctx.get("batch_id"),
            "pick_origin": "机器人获取",
        }
        bm.push_context(page, push_ctx)

        for page_num in range(1, max_pages + 1):
            while pause_event and pause_event.is_set():
                on_progress("⏸️ 脚本已暂停，等待继续...")
                QApplication.processEvents()
                time.sleep(0.5)
                if stop_event and stop_event.is_set():
                    break

            if stop_event and stop_event.is_set():
                on_progress("🛑 接收到人工停止指令，脚本已中止，浏览器为您保留。")
                break

            try:
                page.wait_for_load_state("domcontentloaded", timeout=CRAWL_PAGE_TIMEOUT_MS)
            except Exception:
                pass
            page.wait_for_timeout(strategy.get("first_wait_ms", 3000))
            QApplication.processEvents()

            if strategy.get("simulate_scroll", True):
                _simulate_human_scroll(page)
                QApplication.processEvents()

            while pause_event and pause_event.is_set():
                QApplication.processEvents()
                time.sleep(0.5)
                if stop_event and stop_event.is_set():
                    break
            if stop_event and stop_event.is_set():
                break

            scan_func = strategy["auto_scan_func"]
            try:
                count = page.evaluate(f"window.{scan_func} && window.{scan_func}()")
            except Exception as e:
                on_progress(f"第 {page_num} 页扫描失败: {e}")
                count = 0
            count = count or 0
            scanned_total += count
            on_progress(f"第 {page_num} 页扫描到 {count} 条")

            bm.pull_all_queues()
            on_page_scanned(count)

            if page_num >= max_pages:
                on_progress(f"已达到设定页数上限（{max_pages}页），停止抓取")
                break

            if paging_mode == "scroll":
                if count == 0:
                    empty_scan_count += 1
                else:
                    empty_scan_count = 0

                if empty_scan_count >= MAX_EMPTY_SCANS:
                    on_progress(f"连续 {MAX_EMPTY_SCANS} 次未发现新结果，提前结束滚动")
                    break

                on_progress("滚动加载更多结果...")

                try:
                    page.mouse.wheel(0, random.randint(300, 500))
                    page.wait_for_timeout(random.randint(300, 600))
                    page.mouse.wheel(0, random.randint(300, 500))
                    page.wait_for_timeout(random.randint(300, 600))

                    page.keyboard.press("End")
                    page.wait_for_timeout(1000)
                    page.keyboard.press("End")
                except Exception as e:
                    on_progress(f"滚动动作异常: {e}")

                page.wait_for_timeout(2000)

                try:
                    total_cards = page.evaluate("document.querySelectorAll('.qk-card').length")
                    on_progress(f"（调试）当前页面总计有 {total_cards} 个结果卡片")
                except Exception:
                    pass
            else:
                next_btn = _find_next_page(page, strategy["next_page_selectors"])
                if not next_btn:
                    on_progress("未找到下一页按钮，抓取结束")
                    break
                _click_next_page(page, next_btn, strategy["paging_wait_ms_range"], on_progress)

        on_finished(True, scanned_total, "")
        return True

    except Exception as e:
        on_finished(False, scanned_total, str(e))
        return False