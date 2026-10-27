# auto_complaint_baidu.py
import time
import os
from PySide6.QtCore import QObject, Signal

from app_paths import get_user_dir, DIR_TEMP, TEMP_EXCEL_TPL
from db_config import get_current_user
from browser_manager import BrowserManager
from complaint_excel_utils import generate_platform_excel
from complaint_common import DESC_TEMPLATE, take_error_screenshot

# ★ 模块代号常量
from app_data import MODULE_NETDISK, MODULE_OTHER, PLATFORM_BAIDU


class AutoComplaintSignals(QObject):
    progress = Signal(str)


def run_auto_complaint_baidu(complaints_data, signals=None, is_all=False, stop_event=None, login_event=None,
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
    book_name = first_item.get("book", "未知作品")
    baidu_id = first_item.get("baidu_id", "")
    clean_book_name = book_name.strip("《》")

    def wait_for_user_handle(page, error_msg=""):
        log(f"❌ 运行中断: {error_msg}")
        log("🛑 脚本已暂停，未关闭浏览器。请在弹出的窗口中查看当前状态。")
        log("👉 您可以手动接管完成后续操作，或者直接点击小窗右上角的 X，程序会自动结束。")
        shot_path = take_error_screenshot(page, user_dir, "baidu")
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
    temp_excel_path = os.path.join(user_dir, DIR_TEMP, TEMP_EXCEL_TPL.format(platform=PLATFORM_BAIDU))
    if os.path.exists(temp_excel_path):
        try:
            os.remove(temp_excel_path)
        except:
            pass

    try:
        if not generate_platform_excel(complaints_data, PLATFORM_BAIDU, temp_excel_path):
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

        log("正在打开百度版权投诉页...")
        page.goto("https://newcopyright.baidu.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        log("⏳ 正在检查账号状态...")
        page.wait_for_timeout(3000)

        log("正在点击“发起投诉”...")
        try:
            start_btn = page.locator("button:has-text('发起投诉'):visible").first
            start_btn.wait_for(state="visible", timeout=10000)
            start_btn.click()
        except Exception as e:
            return wait_for_user_handle(page, f"找不到【发起投诉】按钮，页面可能未加载完成: {e}")

        time.sleep(3)
        if "subject" in page.url:
            log("✅ 已自动进入【账号主体信息】页。")
        else:
            log("👉 【需要人工干预】检测到账号未登录或掉线！")
            log("请在浏览器中完成扫码/密码登录。登录完成后，无需任何操作，脚本会自动接管！")
            max_login_wait = 300
            waited_login = 0
            logged_in = False
            while waited_login < max_login_wait:
                if stop_event and stop_event.is_set():
                    return False
                time.sleep(3)
                waited_login += 3
                if waited_login > 0 and waited_login % 10 == 0:
                    log(f"⏳ 等待登录中...（已等待 {waited_login} 秒）")
                try:
                    if "subject" in page.url:
                        log("✅ 登录成功！页面已自动跳转。")
                        logged_in = True
                        break
                    is_login_box_visible = False
                    if page.locator("input[placeholder='手机号/用户名/邮箱']").count() > 0:
                        is_login_box_visible = page.locator(
                            "input[placeholder='手机号/用户名/邮箱']").first.is_visible()
                    elif page.locator("text=扫码登录").count() > 0:
                        is_login_box_visible = page.locator("text=扫码登录").first.is_visible()

                    if not is_login_box_visible:
                        new_start_btn = page.locator("button:has-text('发起投诉'):visible").first
                        if new_start_btn.count() > 0:
                            log("检测到可能已登录，正在重新点击“发起投诉”...")
                            new_start_btn.click()
                            time.sleep(3)
                            if "subject" in page.url:
                                log("✅ 登录成功！脚本已自动接管。")
                                logged_in = True
                                break
                except Exception:
                    pass
            if not logged_in:
                return wait_for_user_handle(page, "等待登录超时（5分钟）或页面发生异常")

        log("正在确认账号主体信息，点击“下一步”...")
        try:
            next_btn = page.locator("button.el-button--primary:has-text('下一步'):visible").first
            next_btn.wait_for(state="visible", timeout=10000)
            next_btn.click()
            log("正在等待跳转到【权属登记】...")
            page.wait_for_url("**/hasownership**", timeout=15000)
            time.sleep(2)
        except Exception as e:
            return wait_for_user_handle(page, f"进入权属登记页(/hasownership)失败: {e}")

        try:
            if baidu_id:
                log(f"✅ 检测到百度CP号，正在通过 百度CP号 搜索: {baidu_id}")
                id_input = page.locator("input[placeholder*='ID'], input[placeholder*='id']").first
                if id_input.count() > 0:
                    id_input.fill(baidu_id)
                else:
                    page.locator("input").nth(1).fill(baidu_id)
            else:
                log(f"⚠️ 未检测到百度CP号，正在通过 作品名 搜索: {clean_book_name}")
                name_input = page.locator("input[placeholder='请输入作品名称']").first
                name_input.wait_for(state="visible", timeout=10000)
                name_input.fill(clean_book_name[:4])

            page.locator("button:has-text('搜索')").first.click()
            time.sleep(3)
            target_text = baidu_id if baidu_id else clean_book_name[:4]
            row = page.locator("div.el-table__row, tr").filter(has_text=target_text).first
            select_btn = row.locator("p.selectpop:has-text('选择')").first
            select_btn.click()
            log("正在等待跳转到【填写投诉链接】...")
            page.wait_for_url("**/complaint**", timeout=15000)
            time.sleep(2)
        except Exception as e:
            return wait_for_user_handle(page, f"选择作品失败（可能未登记或网络慢）: {e}")

        log("正在填写投诉表单...")
        log("正在选择投诉产品...")
        try:
            select_input = page.locator(".el-select input[placeholder='请选择']").first
            select_input.click(force=True)
            time.sleep(1)

            # ★ 核心修复：用 module_code 精准选择，用网页文字点击
            module_code = first_item.get("module_code", MODULE_OTHER)
            web_text = first_item.get("web_text", "")

            try:
                # 尝试直接点击下拉框里的选项
                option = page.locator("li:visible").filter(has_text=web_text).first
                option.click(timeout=3000)
                log(f"-> 已选择: {web_text}")
            except Exception:
                # 如果直接点不到（可能被遮挡），才用键盘，但必须严格根据 code 判断
                log(f"⚠️ 点击选项失败，降级使用键盘盲按: {web_text}")
                if module_code == MODULE_NETDISK:
                    page.keyboard.press("ArrowDown")
                else:
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("ArrowDown")
                time.sleep(0.5)
                page.keyboard.press("Enter")

            time.sleep(1)
            log("✅ 产品选择完成")
        except Exception as e:
            return wait_for_user_handle(page, f"选择投诉产品失败: {e}")

        log("正在填写投诉描述...")
        try:
            desc_text = DESC_TEMPLATE.format(name_str=first_item["name_str"], url_str=first_item["url_str"])
            desc_box = page.locator("textarea[placeholder*='请详细描述您遇到的问题']").first
            desc_box.click(force=True)
            desc_box.fill(desc_text[:200])
            log("✅ 描述填写完成")
        except Exception as e:
            return wait_for_user_handle(page, f"填写描述失败: {e}")

        log("正在填写原版链接...")
        try:
            page.locator("input[placeholder='请输入链接标题']").first.click(force=True)
            page.locator("input[placeholder='请输入链接标题']").first.fill("原版主页链接，点击目录则是正文内容")
            time.sleep(0.5)
            page.locator("input[placeholder='请输入链接地址']").first.click(force=True)
            page.locator("input[placeholder='请输入链接地址']").first.fill(first_item["url_str"])
            log("✅ 原版链接填写完成")
        except Exception as e:
            return wait_for_user_handle(page, f"填写原版链接失败: {e}")

        log("正在自动上传批量链接 Excel...")
        try:
            with page.expect_file_chooser() as fc_info:
                page.locator("span:has-text('选择文件')").first.click(force=True)
            file_chooser = fc_info.value
            file_chooser.set_files(os.path.abspath(temp_excel_path))
            log("✅ 文件已上传，等待百度解析...")
            time.sleep(5)
        except Exception as e:
            return wait_for_user_handle(page, f"自动上传文件失败: {e}")

        if page.locator("text=该链接已投诉").count() > 0:
            log("❌ 检测到本批次有链接【已被投诉】（存在历史记录）。")
            return wait_for_user_handle(page, "存在已投诉记录")
        else:
            log("✅ 链接检查通过，未发现已投诉记录。")

        log("正在进入下一步（身份真实性验证）...")
        try:
            next_btn_2 = page.locator("button.el-button--primary:has-text('下一步'):visible").last
            next_btn_2.wait_for(state="visible", timeout=10000)
            next_btn_2.click(force=True)
            log("正在等待跳转到【扫码验证页】...")
            page.wait_for_url("**/verification**", timeout=15000)
            time.sleep(2)
        except Exception as e:
            return wait_for_user_handle(page, f"进入扫码页(/verification)失败: {e}")

        log("👉 【需要人工干预】请在弹出的页面中扫码进行身份验证！")
        log("扫码成功后，脚本将自动继续并提交...")

        max_wait = 600
        waited = 0
        scan_success = False
        while waited < max_wait:
            if stop_event and stop_event.is_set():
                return False
            try:
                for p_tab in page.context.pages:
                    if p_tab.is_closed():
                        continue
                    if "confirm" in p_tab.url or p_tab.locator("button:has-text('提交投诉'):visible").count() > 0:
                        page = p_tab
                        scan_success = True
                        break
                if scan_success:
                    break
            except Exception:
                pass
            if waited > 0 and waited % 5 == 0:
                log(f"⏳ 正在等待扫码验证...（已等待 {waited} 秒）")
            time.sleep(1)
            waited += 1

        if not scan_success:
            return wait_for_user_handle(page, "等待扫码超时（10分钟）或发生页面异常")

        log("✅ 扫码成功，已进入确认页面。")
        time.sleep(3)

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            try:
                checkbox = page.locator("span.el-checkbox__inner:visible").first
                if checkbox.count() > 0 and checkbox.is_visible():
                    checkbox.click(force=True)
                    time.sleep(0.5)
            except:
                pass

            submit_btn = page.locator("button:has-text('提交投诉'):visible").first
            submit_btn.wait_for(state="visible", timeout=10000)
            submit_btn.click(force=True)
            log("🎉 已点击提交！正在等待百度响应...")

            success_found = False
            for _ in range(15):
                if "complete" in page.url or page.locator("text=反馈完成").count() > 0 or page.locator(
                        "text=提交成功").count() > 0:
                    success_found = True
                    break
                time.sleep(1)

            if success_found:
                log("✅ 页面提示提交成功！本批次完成。")
            else:
                log("⚠️ 未能明确检测到成功提示，但已点击提交。")
        except Exception as e:
            return wait_for_user_handle(page, f"提交或验证成功提示失败: {e}")

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
        print("（百度任务结束，浏览器生命周期由调度器统一管理）")