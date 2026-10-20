from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time

url = "https://www.qianmixs.com/info/6609732.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # 先用有头模式

    # ★ 核心修复：创建 context 并忽略证书错误
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()

    print("正在加载网页...")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # 点击展开
    try:
        more_btn = page.locator("text='查看更多章节'").first
        if more_btn.is_visible():
            more_btn.click()
            print("点击了查看更多章节")
            page.wait_for_timeout(2000)
    except Exception:
        print("没找到查看更多章节按钮")

    # 滚动到底部
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    count = 0
    # 只打印前10个看看结构
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if "第" in text and "章" in text:
            href = a.get("href")
            onclick = a.get("onclick")
            print(f"标题: {text} | 链接: {href} | onclick: {onclick}")
            count += 1
            if count >= 10:
                break

    print(f"总计找到包含'第'和'章'的a标签: {count} 个")

    print("按回车键关闭浏览器...")
    input()
    browser.close()