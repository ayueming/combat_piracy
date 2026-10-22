# auto_complaint_baidu.py
import time
import os
import openpyxl
from openpyxl import Workbook
from PySide6.QtCore import QObject, Signal

# ★ 引入路径管理和统一浏览器
from app_paths import get_user_dir
from db_config import get_current_user
from browser_manager import BrowserManager


class AutoComplaintSignals(QObject):
    progress = Signal(str)


def run_auto_complaint_baidu(complaints_data, signals: AutoComplaintSignals = None, is_all=False):
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
        log("👉 您可以手动接管完成后续操作，或者直接点击浏览器该标签页右上角的 X 关闭它，程序会自动结束。")

        try:
            screenshot_dir = os.path.join(user_dir, "error_screenshots")
            if not os.path.exists(screenshot_dir):
                os.makedirs(screenshot_dir)

            ts = time.strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(screenshot_dir, f"error_baidu_{ts}.png")

            page.screenshot(path=screenshot_path, full_page=True)
            log(f"📸 已保存当前画面截图至: {screenshot_path}")
        except Exception as e:
            log(f"⚠️ 截图保存失败: {e}")

        while True:
            try:
                # ★ 改造：因为统一了浏览器，只需检查当前 page 是否被关闭
                if page.is_closed():
                    log("✅ 检测到当前标签页已关闭，任务结束。")
                    return False
            except:
                return False
            time.sleep(2)

    log("正在生成本次投诉的 Excel 文件...")
    temp_excel_path = os.path.join(user_dir, "temp", "temp_baidu_import.xlsx")

    if os.path.exists(temp_excel_path):
        try:
            os.remove(temp_excel_path)
        except:
            pass

    try:
        wb = Workbook()
        ws = wb.active
        ws.append(["序号", "链接名称", "链接地址"])
        for idx, item in enumerate(complaints_data, start=1):
            ws.append([idx, "盗版链接", item["url"]])
        wb.save(temp_excel_path)
    except Exception as e:
        log(f"❌ 生成 Excel 失败: {e}")
        return False

    page = None

    try:
        log("正在唤醒统一浏览器...")

        # ★ 核心改造：使用 BrowserManager 启动/连接浏览器
        try:
            bm = BrowserManager.instance()
            page = bm.new_page()
        except Exception as launch_err:
            log(f"❌ 浏览器启动失败: {launch_err}")
            log("👉 请检查是否有残留的 Chrome 进程，或任务管理器强制结束后重试。")
            return False

        log("正在打开百度版权投诉页...")
        page.goto("https://newcopyright.baidu.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        log("⏳ 正在检查账号状态...")
        page.wait_for_timeout(2000)

        is_offline = False
        try:
            if page.locator("input[placeholder='手机号/用户名/邮箱']").count() > 0 and \
                    page.locator("input[placeholder='手机号/用户名/邮箱']").first.is_visible():
                is_offline = True
            elif page.locator("text=扫码登录").count() > 0 and \
                    page.locator("text=扫码登录").first.is_visible():
                is_offline = True
        except:
            pass

        if is_offline:
            log("👉 【需要人工干预】检测到账号未登录或掉线！")
            log("请在浏览器中完成扫码/密码登录。登录完成后，无需任何操作，脚本会自动接管！")

            max_login_wait = 300
            waited_login = 0
            logged_in = False

            while waited_login < max_login_wait:
                time.sleep(3)
                waited_login += 3
                if waited_login > 0 and waited_login % 10 == 0:
                    log(f"⏳ 等待登录中...（已等待 {waited_login} 秒）")

                try:
                    page.goto("https://newcopyright.baidu.com/", timeout=10000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    if page.locator("button:has-text('发起投诉'):visible").count() > 0 and \
                            page.locator("input[placeholder='手机号/用户名/邮箱']").count() == 0:
                        log("✅ 登录成功！脚本已自动接管。")
                        logged_in = True
                        break
                except:
                    pass

            if not logged_in:
                return wait_for_user_handle(page, "等待登录超时（5分钟）")

        log("正在点击“发起投诉”...")
        try:
            start_btn = page.locator("button:has-text('发起投诉'):visible").first
            start_btn.wait_for(state="visible", timeout=10000)
            start_btn.click()

            log("正在等待跳转到【账号主体信息】...")
            page.wait_for_url("**/subject**", timeout=15000)
            time.sleep(1)
        except Exception as e:
            return wait_for_user_handle(page, f"进入主体信息页(/subject)失败: {e}")

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
                log(f"✅ 检测到百度CP号，正在通过 ID 搜索: {baidu_id}")
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

            cat = first_item.get("cat", "")
            if "网盘" in cat:
                log("-> 选择: 百度网盘")
                page.keyboard.press("ArrowDown")
                time.sleep(0.5)
                page.keyboard.press("Enter")
            else:
                log("-> 选择: 百度搜索")
                page.keyboard.press("ArrowDown")
                time.sleep(0.5)
                page.keyboard.press("Enter")
            time.sleep(1)
            log("✅ 产品选择完成")
        except Exception as e:
            return wait_for_user_handle(page, f"选择投诉产品失败: {e}")

        log("正在填写投诉描述...")
        try:
            p_id = first_item.get("platform_id", "")
            aliases = first_item.get("aliases", "")
            url_str = f"https://www.jjwxc.net/onebook.php?novelid={p_id}" if p_id else ""

            name_str = f"《{book_name}（原名：{aliases}）》" if aliases else f"《{book_name}》"

            desc_text = (
                f"晋江文学城授权作品{name_str}，首发网址：{url_str}，"
                f"被盗文网站非法获取，贵站出现大量盗文txt分享，持续侵犯作者的个人利益。"
                f"作者已经按照规则提交了作者的作品授权书，首发平台截图和后台截图，"
                f"希望贵站能够严肃处理这一问题，删除原帖和txt分享链接。"
            )
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
            page.locator("input[placeholder='请输入链接地址']").first.fill(url_str)
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
            log("👉 存在已投诉链接，请手动删除后完成后续投诉，关闭当前标签页，标记为已投诉，或者直接关闭标签页。")
            log("⏳ 脚本已暂停，请手动在网页中操作。")
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
            try:
                # ★ 改造：由于统一了浏览器，扫码后可能会在当前标签页跳转，也可能新开一个标签页
                # 我们获取当前浏览器里所有的标签页来找
                current_pages = bm._context.pages
                for p_tab in current_pages:
                    if p_tab.is_closed():
                        continue
                    if "confirm" in p_tab.url:
                        page = p_tab
                        scan_success = True
                        break
                    if p_tab.locator("button:has-text('提交投诉'):visible").count() > 0:
                        scan_success = True
                        break
                if scan_success:
                    break
            except Exception:
                pass

            if waited > 0 and waited % 5 == 0:
                log(f"⏳ 正在等待扫码验证...（已等待 {waited} 秒，最多等待 10 分钟）")

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
                if "complete" in page.url:
                    success_found = True
                    break
                if page.locator("text=反馈完成").count() > 0 or page.locator("text=提交成功").count() > 0:
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

        # ★ 改造：不再强杀浏览器进程，而是优雅地关闭当前标签页
        try:
            if is_all and page and not page.is_closed():
                time.sleep(3)
                page.close()
                print("（当前百度标签页已关闭，浏览器保留在后台）")
            else:
                print("（浏览器已保留，未自动关闭）")
        except:
            pass