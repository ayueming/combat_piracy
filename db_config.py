import sqlite3
import os
import time
from app_paths import DATA_DIR

# 把相对路径改成绝对路径，固定在 data 文件夹里
DB_NAME = os.path.join(DATA_DIR, 'piracy_records.db')

# ★ 平台ID / 百度ID 的合法字符：英文字母 + 数字
# GLOB '*[^A-Za-z0-9]*' 表示"包含任意非字母数字字符"，NOT GLOB 即"不含非法字符"
_ALNUM_CHECK_SQL = "NOT GLOB '*[^A-Za-z0-9]*'"


def get_conn():
    return sqlite3.connect(DB_NAME)


# ================= DB 层格式约束：检测 / 清洗 / 迁移 =================

def _books_has_alnum_check(cursor):
    """检测 books 表是否已有字母数字 CHECK 约束"""
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='books'"
    ).fetchone()
    if not row or not row[0]:
        return False
    # 用特征串判断，避免误伤未来其他 GLOB 用法
    return "[^A-Za-z0-9]" in row[0]


def _clean_invalid_book_ids(cursor):
    """
    把 books 表中含非法字符的 platform_id / baidu_id 清洗为 NULL。
    返回被清洗掉的记录，供写日志（用户可据此手工补录）。
    """
    bad = []
    for col in ("platform_id", "baidu_id"):
        rows = cursor.execute(
            f"SELECT id, name, {col} FROM books "
            f"WHERE {col} IS NOT NULL AND {col} != '' "
            f"AND {col} GLOB '*[^A-Za-z0-9]*'"
        ).fetchall()
        for r in rows:
            bad.append({"id": r[0], "name": r[1], "field": col, "value": r[2]})
        if rows:
            cursor.execute(
                f"UPDATE books SET {col}=NULL "
                f"WHERE {col} IS NOT NULL AND {col} != '' "
                f"AND {col} GLOB '*[^A-Za-z0-9]*'"
            )
    return bad


def _log_migration(records):
    """把迁移中清洗掉的脏数据写日志，方便用户事后找回"""
    if not records:
        return
    log_dir = os.path.join(DATA_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"db_migrate_{ts}.log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("以下记录因【平台ID / 百度ID】包含非字母数字字符，已被置为 NULL：\n")
            f.write("如需保留，请手工修正后重新填写。\n\n")
            for r in records:
                f.write(f"  id={r['id']}  作品={r['name']}  字段={r['field']}  原值={r['value']!r}\n")
        print(f"[DB迁移] 已清洗 {len(records)} 条非法ID记录，日志：{log_path}")
    except Exception as e:
        print(f"[DB迁移] 写日志失败: {e}")


def _migrate_books_add_check(conn, cursor):
    """
    重建 books 表，加入 platform_id / baidu_id 的字母数字 CHECK 约束。
    SQLite 不支持 ADD CONSTRAINT，只能：建新表 → 搬数据 → 删旧表 → 改名。
    """
    # 1. 先清洗历史脏数据（否则 INSERT SELECT 会违反 CHECK）
    bad_records = _clean_invalid_book_ids(cursor)
    conn.commit()

    # 2. 关外键（DROP TABLE 时如果 sites.book_id 有 FK 引用会失败）
    #    PRAGMA 在事务中切换无效，所以前面先 commit 了
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        cursor.execute(f'''
            CREATE TABLE books_new
            (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id   TEXT CHECK (platform_id IS NULL OR platform_id {_ALNUM_CHECK_SQL}),
                name          TEXT UNIQUE NOT NULL,
                pen_name      TEXT,
                aliases       TEXT,
                evidence_path TEXT,
                rights_holder TEXT,
                baidu_id      TEXT CHECK (baidu_id IS NULL OR baidu_id {_ALNUM_CHECK_SQL})
            )
        ''')
        cursor.execute('''
            INSERT INTO books_new
                (id, platform_id, name, pen_name, aliases, evidence_path, rights_holder, baidu_id)
            SELECT id, platform_id, name, pen_name, aliases, evidence_path, rights_holder, baidu_id
            FROM books
        ''')
        cursor.execute("DROP TABLE books")
        cursor.execute("ALTER TABLE books_new RENAME TO books")
        conn.commit()
        print("[DB迁移] books 表已重建，platform_id / baidu_id 已加 CHECK 约束")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")

    _log_migration(bad_records)


# ================= 初始化 =================

def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    # ================= 1. 初始化 books 表 =================
    # 新库直接一步到位建带 CHECK 的表；老库 IF NOT EXISTS 不执行，后面走迁移
    cursor.execute(f'''CREATE TABLE IF NOT EXISTS books
                       (
                           id            INTEGER PRIMARY KEY AUTOINCREMENT,
                           platform_id   TEXT CHECK (platform_id IS NULL OR platform_id {_ALNUM_CHECK_SQL}),
                           name          TEXT UNIQUE NOT NULL,
                           pen_name      TEXT,
                           aliases       TEXT,
                           evidence_path TEXT,
                           rights_holder TEXT,
                           baidu_id      TEXT CHECK (baidu_id IS NULL OR baidu_id {_ALNUM_CHECK_SQL})
                       )''')

    # 自动升级 books 表（老库补齐后续新增字段；已存在则忽略）
    book_columns_to_add = [
        ("evidence_path", "TEXT"),
        ("rights_holder", "TEXT"),
        ("baidu_id", "TEXT"),
    ]
    for col_name, col_type in book_columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE books ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    conn.commit()

    # ★ 关键：老库补齐字段后，若还没有 CHECK 约束，就重建表
    if not _books_has_alnum_check(cursor):
        _migrate_books_add_check(conn, cursor)

    # ================= 2. 初始化 sites 表 =================
    cursor.execute('''CREATE TABLE IF NOT EXISTS sites
                      (
                          id              INTEGER PRIMARY KEY AUTOINCREMENT,
                          category        TEXT,
                          site_url        TEXT UNIQUE,
                          name            TEXT,
                          attr            TEXT,
                          feature_code    TEXT,
                          complaint_time  TEXT,
                          resource_status TEXT,
                          book_id         INTEGER,
                          book_name       TEXT,
                          crawl_status    TEXT
                      )''')

    site_columns_to_add = [
        ("name", "TEXT"), ("attr", "TEXT"), ("feature_code", "TEXT"),
        ("complaint_time", "TEXT"), ("resource_status", "TEXT"),
        ("book_id", "INTEGER"), ("book_name", "TEXT"), ("crawl_status", "TEXT"),
    ]
    for col_name, col_type in site_columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE sites ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    # ================= 3. 初始化 records 表 =================
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS records
           (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               date        TEXT,
               attr        TEXT,
               platform_id TEXT,
               book_name   TEXT,
               url         TEXT UNIQUE
           )''')

    # ================= 4. 初始化 evidences 表（分权利人/书籍） =================
    ev_exists = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='evidences'"
    ).fetchone()

    if ev_exists:
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(evidences)").fetchall()]
        # 旧版结构迁移
        if "book_id" in cols and "owner_type" not in cols:
            cursor.execute("ALTER TABLE evidences RENAME TO evidences_old")
            cursor.execute('''CREATE TABLE evidences
                              (
                                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                                  owner_type TEXT NOT NULL,
                                  owner_key  TEXT NOT NULL,
                                  ev_type    TEXT,
                                  file_path  TEXT,
                                  UNIQUE (owner_type, owner_key, ev_type)
                              )''')
            for b_id, ev_type, f_path in cursor.execute(
                    "SELECT book_id, ev_type, file_path FROM evidences_old"
            ).fetchall():
                if b_id == 0:
                    cursor.execute(
                        "INSERT OR IGNORE INTO evidences (owner_type, owner_key, ev_type, file_path) "
                        "VALUES ('holder', '__default__', ?, ?)", (ev_type, f_path))
                else:
                    cursor.execute(
                        "INSERT OR IGNORE INTO evidences (owner_type, owner_key, ev_type, file_path) "
                        "VALUES ('book', ?, ?, ?)", (str(b_id), ev_type, f_path))
            cursor.execute("DROP TABLE evidences_old")

    cursor.execute('''CREATE TABLE IF NOT EXISTS evidences
                      (
                          id         INTEGER PRIMARY KEY AUTOINCREMENT,
                          owner_type TEXT NOT NULL,
                          owner_key  TEXT NOT NULL,
                          ev_type    TEXT,
                          file_path  TEXT,
                          UNIQUE (owner_type, owner_key, ev_type)
                      )''')

    conn.commit()
    conn.close()