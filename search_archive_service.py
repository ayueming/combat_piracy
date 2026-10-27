# search_archive_service.py
"""
检索控制台归档动作收集。

只服务检索页的三张表（明确资源 / 未知网站 / 暂不处理），
负责把“用户对每行的操作”翻译成 keep / drop / black 三类动作。

★ 本模块只收集动作，不执行落库。
  执行仍走 link_ingest_service.archive_batch_by_ids(keep_items, drop_ids, blacklist_ids)。

规则（优先级从高到低）：
  1. black_checked = True  → 进 blacklist_ids（永久删除，写 ignored_links）
  2. action_data 以 keep: 开头 → 进 keep_items（入库，分类为冒号后的值）
  3. 其他（含 action_data = "drop" 或空）→ 进 drop_ids（暂不处理，物理删除当前草稿）
"""


def collect_archive_actions(rows):
    """
    参数 rows: 普通行数据列表，每行是一个 dict：
        {
            "db_id": <int/str>,          必填
            "black_checked": <bool>,     必填，是否勾选拉黑
            "action_data": <str>,        必填，入库下拉的 currentData()，
                                         取值 "drop" 或 "keep:分类名"
        }

    返回 (keep_items, drop_ids, blacklist_ids)：
        keep_items: [(db_id, category), ...]
        drop_ids: [db_id, ...]
        blacklist_ids: [db_id, ...]
    """
    keep_items = []
    drop_ids = []
    blacklist_ids = []

    for row in rows or []:
        db_id = row.get("db_id")
        if db_id is None:
            continue

        # 拉黑优先于一切
        if row.get("black_checked"):
            blacklist_ids.append(db_id)
            continue

        action_data = row.get("action_data") or ""
        if action_data.startswith("keep:"):
            category = action_data.split(":", 1)[1]
            keep_items.append((db_id, category))
        else:
            drop_ids.append(db_id)

    return keep_items, drop_ids, blacklist_ids