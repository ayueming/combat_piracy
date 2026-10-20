import time
import re
import os
import openpyxl

from openpyxl import Workbook #冗余行，可删可不删
from playwright.sync_api import sync_playwright
from PySide6.QtCore import QObject, Signal

# ★ 引入路径管理
from app_paths import DATA_DIR, get_temp_dir


class AutoComplaintSignals(QObject):
    progress = Signal(str)


def run_auto_complaint(complaints_data, signals: AutoComplaintSignals = None, is_all=False):
    def log(msg):
        print(msg)
        if signals:
            signals.progress.emit(msg)

    log("正在生成临时 Excel...")
    # 临时文件生成在 data/temp 目录下
    temp_excel_path = os.path.join(get_temp_dir(), "temp_quark_import.xlsx")

    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.cell(row=1, column=1, value="侵权链接")
        ws.cell(row=1, column=2, value="原创链接")
        ws.cell(row=1, column=3, value="作品名（选填）")
        start_row = 2

        for row_idx, item in enumerate(complaints_data, start=start_row):
            url = item["url"]
            book_name = item["book"]
            p_id = item.get("platform_id", "")
            original_url = f"https://www.jjwxc.net/onebook.php?novelid={p_id}" if p_id else "https://www.jjwxc.net/"

            ws.cell(row=row_idx, column=1, value=url)
            ws.cell(row=row_idx, column=2, value=original_url)
            ws.cell(row=row_idx, column=3, value=book_name)

        wb.save(temp_excel_path)
    except Exception as e:
        log(f"❌ 生成临时 Excel 失败: {e}")
        return False

    p = sync_playwright().start()
    try:
        # ★ 修改：重命名为 login_quark_data，并放在 data 目录下
        user_data_dir = os.path.join(DATA_DIR, "login_quark_data")
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            args=["--start-maximized"]
        )
        page = browser.pages[0]

        log("正在打开夸克投诉页...")
        page.goto("https://ipp.quark.cn/#/home")

        log("⏳ 请在浏览器扫码登录 (等待登录中，成功后将自动继续)...")
        try:
            page.wait_for_selector("text=发起侵权投诉", timeout=60000)
            time.sleep(2)
        except Exception:
            log("⚠️ 等待登录超时（60秒），尝试强行继续执行...")

        page.mouse.wheel(0, 3000)
        time.sleep(1)
        try:
            button = page.get_by_text("发起侵权投诉", exact=True)
            if button.count() > 0:
                button.first.scroll_into_view_if_needed()
                time.sleep(0.5)
                button.first.click(timeout=5000)
            else:
                page.locator("text=发起侵权投诉").click(timeout=5000)
            page.wait_for_selector("text=您的身份", timeout=10000)
            time.sleep(2)
        except:
            pass

        log("正在自动勾选固定选项...")
        try:
            page.locator("label").filter(has_text="权利人").click(timeout=3000)
        except:
            pass

        first_holder = complaints_data[0].get("rights_holder", "")
        if first_holder:
            log(f"正在自动选择具体权利人: {first_holder}")
            try:
                dropdown = page.locator("#obligee_id")
                if dropdown.count() > 0:
                    dropdown.scroll_into_view_if_needed()
                    time.sleep(0.5)
                    dropdown.click(force=True)
                    dropdown.dispatch_event("mousedown")
                    dropdown.dispatch_event("mouseup")
                    time.sleep(1.5)

                    option = page.locator(".ant-select-dropdown-menu-item").filter(has_text=first_holder).first
                    if option.count() > 0 and option.is_visible():
                        option.click(force=True)
                    else:
                        page.keyboard.press("ArrowDown")
                        time.sleep(0.5)
                        page.keyboard.press("Enter")
                else:
                    page.locator("text=请选择具体权利人").first.click(force=True)
                    time.sleep(1)
                    option = page.locator(".ant-select-dropdown-menu-item").filter(has_text=first_holder).first
                    if option.count() > 0:
                        option.click(force=True)
                time.sleep(1)
            except Exception as e:
                log(f"⚠️ 自动选择权利人失败: {e}")

        try:
            page.get_by_text("知识产权").click(timeout=3000)
            page.get_by_text("著作权(含视频、图文、图集等)").click(timeout=3000)
        except:
            pass

        first_cat = complaints_data[0].get("cat", "")
        try:
            if "网盘" in first_cat or "uc" in first_cat.lower():
                page.get_by_text("夸克网盘", exact=True).click(timeout=3000)
            else:
                page.get_by_text("夸克搜索", exact=True).click(timeout=3000)
        except:
            pass
        try:
            page.get_by_text("小说", exact=True).click(timeout=3000)
        except:
            pass

        log("正在执行【批量导入】...")
        try:
            page.locator("text=批量导入").first.click()
            time.sleep(2)

            with page.expect_file_chooser() as fc_info:
                page.locator("text=上传文件").first.click()

            file_chooser = fc_info.value
            file_chooser.set_files(os.path.abspath(temp_excel_path))
            time.sleep(4)

            log("正在点击【解析数据】...")
            parse_btn = page.get_by_role("button", name="解析数据")
            if parse_btn.count() == 0:
                parse_btn = page.locator("div, span").filter(has_text="解析数据").last

            parse_btn.wait_for(state="visible", timeout=5000)
            parse_btn.click(force=True)
            log("✅ 解析数据点击成功！正在等待填充...")
            time.sleep(5)
        except Exception as e:
            log(f"❌ 解析过程出错: {e}")

        log("正在填写投诉描述...")
        try:
            first_item = complaints_data[0]
            book_name = first_item.get("book", "未知作品")
            aliases = first_item.get("aliases", "")
            p_id = first_item.get("platform_id", "")

            name_str = f"《{book_name}（原名：{aliases}）》" if aliases else f"《{book_name}》"
            url_str = f"https://www.jjwxc.net/onebook.php?novelid={p_id}" if p_id else ""

            desc_text = (
                f"晋江文学城授权作品{name_str}，"
                f"首发网址：{url_str} ，"
                f"被盗文网站非法获取，贵站出现大量盗文txt分享，持续侵犯作者的个人利益。"
                f"作者已经按照规则提交了作者的作品授权书，首发平台截图和后台截图，"
                f"希望贵站能够严肃处理这一问题，删除原帖和txt分享链接。"
            )

            desc_textarea = page.locator("textarea[placeholder*='请客观公正描述']")
            if desc_textarea.count() > 0:
                desc_textarea.fill(desc_text)
                time.sleep(0.5)
        except Exception as e:
            log(f"填写描述失败: {e}")

        pdf_path = complaints_data[0].get("evidence_path", "")
        log("正在上传证明材料 PDF...")
        try:
            if pdf_path and os.path.exists(pdf_path):
                file_input_pdf = page.locator("input[type='file'][accept*='.pdf']").first
                if file_input_pdf.count() > 0:
                    file_input_pdf.set_input_files(pdf_path)
                    time.sleep(3)
        except Exception as e:
            log(f"PDF上传失败: {e}")

        log("正在滚动到底部...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        log("正在勾选同意协议...")
        try:
            checkboxes = page.locator("input.ant-checkbox-input")
            for i in range(checkboxes.count()):
                cb = checkboxes.nth(i)
                if cb.is_visible() and not cb.is_checked():
                    cb.check(force=True)
                    time.sleep(0.5)
        except Exception as e:
            log(f"⚠️ 勾选协议失败: {e}")

        # ================= 核心修改部分开始 =================
        log("准备点击提交按钮...")
        submit_ok = False
        try:
            btn = page.locator(".ant-tabs-tabpane-active button.ant-btn-primary").filter(has_text="提交").first

            if btn.count() > 0:
                btn.scroll_into_view_if_needed()
                time.sleep(1)
                btn.evaluate("node => node.click()")
                log("✅ 已通过 JS 触发提交点击！")
            else:
                log("⚠️ 未找到激活页面中的提交按钮，尝试点击页面最后一个可见主按钮...")
                page.locator("button.ant-btn-primary:visible").last.click(force=True)

            time.sleep(2)

            # 处理二次确认弹窗（有些情况不需要，以防万一保留）
            try:
                confirm_btn = page.locator("button.ant-btn-primary:visible").filter(
                    has_text=re.compile("确定|确认")).first
                if confirm_btn.count() > 0 and confirm_btn.is_visible():
                    confirm_btn.evaluate("node => node.click()")
                    log("✅ 已点击二次确认弹窗！")
                    time.sleep(2)
            except:
                pass

            # 核心：通过截图中的 UI 弹窗判断成功
            log("正在等待提交成功的弹窗响应...")
            # ★ 修复：直接用 text=提交成功 就能匹配到包含该字样的弹窗了
            page.wait_for_selector("text=提交成功", timeout=15000)
            log("🎉 检测到「提交成功」弹窗，本批次投诉确认成功！")
            submit_ok = True

            # 顺手把弹窗关掉或者点掉
            if is_all:
                try:
                    page.get_by_role("button", name="投诉列表").click(timeout=3000)
                    time.sleep(1)
                except:
                    pass

        except Exception as e:
            log(f"❌ 提交失败或未检测到成功提示: {e}")
            # 兜底：如果失败了，截个图保存在本地，方便你查明原因
            try:
                # ★ 修改：失败截图也放到 data/error_screenshots 里
                error_screenshot_dir = os.path.join(DATA_DIR, "error_screenshots")
                os.makedirs(error_screenshot_dir, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(error_screenshot_dir, f"fail_{ts}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                log(f"📸 已保存失败现场截图: {screenshot_path}")
            except:
                pass

        if not submit_ok:
            return False
        # ================= 核心修改部分结束 =================

        # 根据是否全批模式来分流
        if is_all:
            log("✅ 提交完成！检测到全批模式，正在自动关闭当前窗口去处理下一批...")
            time.sleep(2)  # 稍微等一等，让网络请求发出去
            browser.close()
            return True
        else:
            log("👉 单次投诉模式，请确认结果后【手动关闭浏览器窗口】。")
            while True:
                try:
                    if page.is_closed():
                        log("检测到浏览器已关闭，本批次处理结束。")
                        return True
                except:
                    return True
                time.sleep(1)

    except Exception as e:
        log(f"❌ 运行遇到问题：{e}")
        return False
    finally:
        # 清理临时 Excel
        if os.path.exists(temp_excel_path):
            try:
                os.remove(temp_excel_path)
            except:
                pass
        p.stop()