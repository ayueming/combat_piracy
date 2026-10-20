import csv
import os
import sqlite3
from db_config import get_conn
from feature_extractor import extract_pure_feature, get_platform_category


def import_sites_from_file(file_path):
    """
    核心导入逻辑，解析 Excel/CSV 并写入数据库。
    返回 (成功数量, 重复数量)
    """
    ext = os.path.splitext(file_path)[1].lower()
    rows = []

    # 1. 读取文件
    if ext == '.csv':
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            rows = list(csv.reader(f))
    elif ext == '.xlsx':
        try:
            import openpyxl
        except ImportError:
            raise ImportError(
                "读取 Excel 需要 openpyxl 模块。\n请在终端运行：pip install openpyxl\n或者将文件另存为 CSV 格式。")

        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            if any(row):
                rows.append([str(cell) if cell is not None else "" for cell in row])
    else:
        raise ValueError("不支持的文件格式，仅支持 .csv 或 .xlsx")

    if not rows or len(rows) <= 1:
        raise ValueError("文件里没有有效数据（必须包含表头且至少有一行数据）！")

    # 2. 智能识别表头索引（默认顺序）
    header = rows[0]
    col_idx = {"book": 0, "cat": 1, "url": 2, "name": 3, "attr": 4, "time": 5, "status": 6}

    for i, h in enumerate(header):
        h_str = str(h).strip().lower()
        if "作品" in h_str or "中文" in h_str or "书名" in h_str:
            col_idx["book"] = i
        elif "分类" in h_str or "平台" in h_str:
            col_idx["cat"] = i
        elif "链接" in h_str or "网址" in h_str or "url" in h_str:
            col_idx["url"] = i
        elif "名称" in h_str or "描述" in h_str:
            col_idx["name"] = i
        elif "属性" in h_str:
            col_idx["attr"] = i
        elif "投诉" in h_str or "日期" in h_str or "时间" in h_str:
            col_idx["time"] = i
        elif "状态" in h_str:
            col_idx["status"] = i

    # 3. 准备数据库数据
    conn = get_conn()
    cursor = conn.cursor()

    # 获取作品库字典供匹配
    books_dict = {name: b_id for b_id, name in conn.execute("SELECT id, name FROM books").fetchall()}
    platform_dict = {str(pid): b_id for b_id, pid in
                     conn.execute("SELECT id, platform_id FROM books WHERE platform_id IS NOT NULL").fetchall()}

    success_count = 0
    duplicate_count = 0

    # 4. 遍历数据行
    for row in rows[1:]:
        # 确保这行有链接的数据
        if len(row) <= col_idx["url"]: continue

        url = str(row[col_idx["url"]]).strip()
        if not url: continue

        # 提取特征码并自动识别分类
        pure_code = extract_pure_feature(url)
        cat = str(row[col_idx["cat"]]).strip() if len(row) > col_idx["cat"] else ""
        if not cat:
            cat = get_platform_category(url)

        name = str(row[col_idx["name"]]).strip() if len(row) > col_idx["name"] else ""
        attr = str(row[col_idx["attr"]]).strip() if len(row) > col_idx["attr"] else ""
        comp_time = str(row[col_idx["time"]]).strip() if len(row) > col_idx["time"] else ""
        status = str(row[col_idx["status"]]).strip() if len(row) > col_idx["status"] else ""

        # 解析关联作品
        book_id = None
        book_name = ""
        if len(row) > col_idx["book"]:
            b_val = str(row[col_idx["book"]]).strip()
            if b_val and b_val != "暂不关联":
                if b_val in books_dict:
                    book_id = books_dict[b_val]
                elif b_val in platform_dict:
                    book_id = platform_dict[b_val]
                else:
                    book_name = b_val  # 数据库没有这本，直接存文字

        # 查重
        cursor.execute("SELECT id FROM sites WHERE feature_code = ?", (pure_code,))
        if cursor.fetchone():
            duplicate_count += 1
            continue

        # 插入
        try:
            cursor.execute('''INSERT INTO sites
                              (category, site_url, name, attr, feature_code, complaint_time, resource_status, book_id,
                               book_name)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                           (cat, url, name, attr, pure_code, comp_time, status, book_id, book_name))
            success_count += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()
    return success_count, duplicate_count