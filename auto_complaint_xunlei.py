# auto_complaint_xunlei.py
import time
import os
import datetime
import calendar
from PySide6.QtCore import QObject, Signal

from app_paths import get_user_dir, DIR_TEMP, DIR_TEMPLATES, FILE_AUTHORIZATION_PDF, TEMP_EXCEL_TPL
from db_config import get_current_user
from browser_manager import BrowserManager
from complaint_excel_utils import generate_platform_excel
from complaint_common import DESC_TEMPLATE, take_error_screenshot

# ★ 平台代号常量
from app_data import PLATFORM_XUNLEI


class AutoComplaintXunleiSignals(QObject):
    progress = Signal(str)


def run_auto_complaint_xunlei(complaints_data, signals=None, is_all=False, stop_event=None, login_event=None,
                              dialog_signal=None):
    def log(msg):
        print(msg)
        if signals:
            signals.progress.emit(msg)

    if not complaints_data:
        return False

    user_id = get_current_user()
    if not user_id:
        log("❌ 错误：未获取到当前登录用户")
        return False
    user_dir = get_user_dir(user_id)

    first_item = complaints_data[0]
    book_name = first_item.get("book", "未知作品").strip("《》")
    PROOF_FILE_PATH = os.path.join(user_dir, DIR_TEMPLATES, FILE_AUTHORIZATION_PDF)

    def wait_for_user_handle(page, error_msg=""):
        log(f"❌ 运行中断: {error_msg}")
        log("🛑 脚本已暂停，未关闭浏览器。请在弹出的窗口中查看当前状态。")
        log("👉 您可以手动接管完成后续操作，或者直接点击小窗右上角的 X，程序会自动结束。")
        shot_path = take_error_screenshot(page, user_dir, "xunlei")
        if shot_path:
            log(f"📸 已保存当前画面截图至: {shot_path}")
        while True:
            if stop_event and stop_event.is_set():
                log("✅ 检测到用户主动停止信号，任务结束。")
                return False
            try:
                if page.is_closed():
                    log("✅ 检测到当前标签页已关闭，任务结束。")
                    return False
            except:
                return False
            time.sleep(2)

    log("正在生成本次投诉的 Excel 文件...")
    temp_excel_path = os.path.join(user_dir, DIR_TEMP, TEMP_EXCEL_TPL.format(platform=PLATFORM_XUNLEI))
    os.makedirs(os.path.dirname(temp_excel_path), exist_ok=True)
    if os.path.exists(temp_excel_path):
        try:
            os.remove(temp_excel_path)
        except:
            pass

    try:
        if not generate_platform_excel(complaints_data, PLATFORM_XUNLEI, temp_excel_path):
            log("❌ 生成 Excel 文件失败")
            return False
    except Exception as e:
        log(f"❌ 生成 Excel 异常: {e}")
        return False

    page = None
    try:
        log("正在唤醒统一浏览器...")
        try:
            bm = BrowserManager.instance()
            page = bm.new_page()
        except Exception as launch_err:
            log(f"❌ 浏览器启动失败: {launch_err}")
            return False

        log("正在打开迅雷版权投诉页...")
        page.goto("https://copyright.xunlei.com/legal/#/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        if "login" in page.url:
            log("👉 【需要人工干预】检测到未登录！请在浏览器中完成登录...")
            max_login_wait = 300
            waited_login = 0
            logged_in = False
            while waited_login < max_login_wait:
                if stop_event and stop_event.is_set():
                    return False
                time.sleep(3)
                waited_login += 3
                if waited_login % 10 == 0:
                    log(f"⏳ 等待登录中...（已等待 {waited_login} 秒）")
                if "login" not in page.url:
                    log("✅ 登录成功！")
                    logged_in = True
                    page.wait_for_timeout(2000)
                    break
            if not logged_in:
                return wait_for_user_handle(page, "等待登录超时（5分钟）")

        log("正在点击【同意并发起投诉】...")
        try:
            start_btn = page.locator("button:has-text('同意并发起投诉'):visible").first
            start_btn.wait_for(state="visible", timeout=10000)
            start_btn.click()
            page.wait_for_url("**/appeal**", timeout=15000)
            page.wait_for_timeout(2000)
        except Exception as e:
            return wait_for_user_handle(page, f"无法进入投诉填表页: {e}")

        log("正在填写投诉表单...")
        page.locator("input[placeholder*='作品名称']").fill(book_name)
        page.wait_for_timeout(500)

        log("-> 选择单选框...")
        page.locator("label:has-text('视听作品')").click()
        page.locator("label:has-text('信息网络传播权')").click()
        page.locator("label:has-text('原始取得')").click()

        # ★ 核心修复：根据配置点击网页文字，而不是写死“云盘服务”
        #   默认值改为空字符串，缺失时明确报错，避免用错误默认值静默匹配失败
        web_text = first_item.get("web_text", "")
        if not web_text:
            log("❌ 缺少 web_text 配置，无法选择服务类型，脚本已停止。")
            return wait_for_user_handle(page, "web_text 为空，无法确定服务类型")
        try:
            page.locator(f"label:has-text('{web_text}')").click(timeout=5000)
            log(f"✅ 已选择服务类型: {web_text}")
        except Exception as e:
            log(f"❌ 选择服务类型失败 ({web_text})，脚本已停止: {e}")
            return wait_for_user_handle(page, f"选择服务类型失败: {e}")

        page.wait_for_timeout(500)

        if PROOF_FILE_PATH and os.path.exists(PROOF_FILE_PATH):
            log("正在上传权利证明文件...")
            try:
                file_input = page.locator(".ant-upload input[type='file']")
                file_input.set_input_files(PROOF_FILE_PATH)
                page.wait_for_timeout(3000)
                log("✅ 证明文件上传成功！")
            except Exception as e:
                log(f"⚠️ 文件上传失败: {e}")
        else:
            log("⚠️ 未检测到本地证明文件，跳过自动上传。请确保网页已保留历史文件。")

        log("正在选择权利保护期...")
        try:
            today = datetime.date.today()
            next_month = today.month % 12 + 1
            next_year = today.year if today.month < 12 else today.year + 1
            last_day = calendar.monthrange(next_year, next_month)[1]
            end_date_str = f"{next_year}年{next_month}月{last_day}日"

            page.locator("span.ant-calendar-picker-input").click()
            page.wait_for_selector(".ant-calendar-range", state="visible")
            page.locator(".ant-calendar-range-left .ant-calendar-today").click()
            page.wait_for_timeout(500)
            page.locator(f".ant-calendar-range-right td[title='{end_date_str}']").click()
            page.wait_for_timeout(500)
            log("✅ 日期选择完成！")
        except Exception as e:
            return wait_for_user_handle(page, f"日期选择失败: {e}")

        log("正在自动上传批量链接 Excel...")
        try:
            with page.expect_file_chooser() as fc_info:
                page.locator("button:has-text('从Excel导入')").click()
            file_chooser = fc_info.value
            file_chooser.set_files(os.path.abspath(temp_excel_path))
            log("✅ 文件已上传，等待迅雷解析...")
            page.wait_for_timeout(4000)
        except Exception as e:
            return wait_for_user_handle(page, f"自动上传Excel失败: {e}")

        log("正在填写侵权理由...")
        desc_text = DESC_TEMPLATE.format(name_str=first_item["name_str"], url_str=first_item["url_str"])
        page.locator("textarea[placeholder='最多800字']").fill(desc_text[:800])

        log("点击下一步，进入预览页...")
        page.locator("button:has-text('下一步')").click()
        page.wait_for_timeout(3000)

        log("点击确认提交...")
        try:
            submit_btn = page.locator("button:has-text('确认提交'):visible").first
            submit_btn.wait_for(state="visible", timeout=10000)
            submit_btn.click()
        except Exception as e:
            return wait_for_user_handle(page, f"找不到确认提交按钮: {e}")

        log("等待提交结果...")
        try:
            page.wait_for_selector("text='提交成功'", timeout=15000)
            log("🎉 迅雷投诉提交成功！本批次完成。")
        except:
            log("⚠️ 未能明确检测到成功提示，但已点击提交，请人工确认。")

        return True
    except Exception as e:
        log(f"❌ 运行遇到严重错误：{e}")
        if page and not page.is_closed():
            wait_for_user_handle(page, "发生严重的脚本运行异常")
        return False
    finally:
        if os.path.exists(temp_excel_path):
            try:
                os.remove(temp_excel_path)
            except:
                pass
        print("（迅雷任务结束，浏览器生命周期由调度器统一管理）")