from collections import defaultdict
from PySide6.QtCore import Qt
from db_config import get_conn


def prepare_complaints_data(model, book_list):
    """
    从模型中提取勾选的数据，按【分类+书籍】分组，并分别按 200 切片。
    """
    checked_data = []
    missing_books = set()

    conn = get_conn()
    # ★ 修复核心：在 SELECT 里加上 baidu_id 字段
    book_details = {
        row[1]: {
            "aliases": row[2],
            "platform_id": row[3],
            "evidence_path": row[4],
            "rights_holder": row[5],
            "baidu_id": row[6]
        }
        for row in
        conn.execute("SELECT id, name, aliases, platform_id, evidence_path, rights_holder, baidu_id FROM books").fetchall()
    }
    conn.close()

    for row in range(model.rowCount()):
        chk_item = model.item(row, 0)
        if chk_item and chk_item.checkState() == Qt.Checked:
            db_id = chk_item.data(Qt.UserRole)
            if not db_id: continue

            book_name = model.item(row, 1).text()

            aliases = ""
            p_id = ""
            evidence_path = ""
            rights_holder = ""
            baidu_id = ""  # ★ 新增

            if book_name in book_details:
                aliases = book_details[book_name].get("aliases", "")
                p_id = book_details[book_name].get("platform_id", "")
                evidence_path = book_details[book_name].get("evidence_path", "")
                rights_holder = book_details[book_name].get("rights_holder", "")
                baidu_id = book_details[book_name].get("baidu_id", "")  # ★ 新增

            # 校验：平台ID、维权书、权利人缺一不可
            if not p_id or not evidence_path or not rights_holder:
                missing_books.add(book_name)

            checked_data.append({
                "id": db_id,
                "book": book_name,
                "aliases": aliases,
                "platform_id": p_id or "",
                "evidence_path": evidence_path or "",
                "rights_holder": rights_holder or "",
                "baidu_id": baidu_id or "",  # ★ 核心修复：把百度CP号塞进数据字典里
                # 这里的 cat 就是你说的“分类”（如：夸克网盘、夸克搜索）
                "cat": model.item(row, 2).text(),
                "url": model.item(row, 3).text().replace(" (重复资源链接)", "").strip(),
                "name": model.item(row, 4).text(),
            })

    if not checked_data:
        return [], missing_books

    # 【核心逻辑】严格按照 (分类, 书名) 进行双重分组
    grouped_data = defaultdict(list)
    for item in checked_data:
        cat = item["cat"] or "未分类"
        book = item["book"] or "未关联"
        grouped_data[(cat, book)].append(item)

    batches = []
    batch_size = 200

    # 遍历每个“分类+书名”组合，对每个组合再按 200 切分
    for (cat, book), items in grouped_data.items():
        for i in range(0, len(items), batch_size):
            batches.append(items[i:i + batch_size])

    return batches, missing_books