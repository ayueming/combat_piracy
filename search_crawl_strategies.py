# search_crawl_strategies.py
"""
搜索抓取策略配置。

每个搜索平台一份策略，search_crawl_service 按策略执行抓取。
当前百度系列的自动扫描函数是 link_picker_injector 里的 window.__aptAutoScan。

以后新增 UC/夸克专用扫描时：
  1. 在 link_picker_injector.py 里加对应 JS 函数，例如 window.__aptAutoScan_uc；
  2. 在 SEARCH_CRAWL_STRATEGIES 里加一条平台专属策略，
     把 auto_scan_func 改成 "__aptAutoScan_uc"，必要时替换 next_page_selectors。
"""

from app_data.crawl_consts import (
    CRAWL_FIRST_WAIT_MS,
    CRAWL_PAGING_WAIT_MS_RANGE,
)

# 默认策略：找不到平台专属策略时回退到这里。
# ★ 只读配置，不要修改这个 dict 本身；需要定制请复制一份放到 SEARCH_CRAWL_STRATEGIES 里。
DEFAULT_STRATEGY = {
    # 页面内执行的自动扫描 JS 函数名（不含 window. 前缀）
    "auto_scan_func": "__aptAutoScan",

    # 翻页模式：
    # "click"  -> 找下一页按钮并点击（百度等）
    # "scroll" -> 向下滚动触发瀑布流加载（夸克等）
    "paging_mode": "click",

    # 翻页按钮候选选择器，按顺序尝试（仅当 paging_mode == "click" 时生效）
    "next_page_selectors": [
        "a.n:has-text('下一页')",
        "a.sb_pagN",
        "a[title='下一页']",
        "a[aria-label='下一页']",
        ".next",
        "a.next",
        ".page-next",
        "a:has-text('下一页')",
    ],

    # 首次页面等待时间（毫秒）
    "first_wait_ms": CRAWL_FIRST_WAIT_MS,

    # 翻页后等待时间区间（毫秒），随机取值防封（仅当 paging_mode == "click" 时生效）
    "paging_wait_ms_range": CRAWL_PAGING_WAIT_MS_RANGE,

    # 是否模拟人类滚动（通用防封滚动）
    "simulate_scroll": True,

    # 瀑布流模式下，每轮向下滚动的“小步数”（仅当 paging_mode == "scroll" 时生效）
    "scroll_steps_per_page": 6,
}

# 平台专属策略覆盖。
SEARCH_CRAWL_STRATEGIES = {
    # ★ 夸克搜索专属策略：无限瀑布流模式
    "夸克搜索": {
        **DEFAULT_STRATEGY,
        "auto_scan_func": "__aptAutoScan_quark",  # 使用专属扫描 JS
        "paging_mode": "scroll",  # 声明使用滚动模式
        "scroll_steps_per_page": 6,  # 每轮向下滚 6 步（约 1.5 屏）
        "simulate_scroll": False,  # 关闭通用随机滚动，避免与瀑布流逻辑冲突
    },

    # ★ 百度知道专属策略
    "百度知道": {
        **DEFAULT_STRATEGY,
        "auto_scan_func": "__aptAutoScan_zhidao",
        "next_page_selectors": [
            "a.pager-next",  # 精准匹配百度知道底部的下一页按钮
        ],
    },

    # ★ 百度贴吧专属策略
    "百度贴吧": {
        **DEFAULT_STRATEGY,
        "auto_scan_func": "__aptAutoScan_tieba",
        "paging_mode": "scroll",      # ★ 贴吧新版是 virtual-list-item，无"下一页"按钮
        "simulate_scroll": False,     # 关闭通用随机滚动，避免与瀑布流逻辑冲突
        # scroll_steps_per_page 走 DEFAULT_STRATEGY 的 6 步
    },


    # 预留：以后写 UC 搜索专用扫描时，在这里加条目，例如：
    # "uc搜索": {
    #     **DEFAULT_STRATEGY,
    #     "auto_scan_func": "__aptAutoScan_uc",
    # },
}


def get_crawl_strategy(platform):
    """获取平台抓取策略，找不到则回退到默认策略。"""
    return SEARCH_CRAWL_STRATEGIES.get(platform, DEFAULT_STRATEGY)