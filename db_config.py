# db_config.py
import sqlite3
import os
import time
import re
from app_paths import get_user_dir

# 平台ID / 百度ID 的合法字符检查
_ALNUM_CHECK_SQL = "NOT GLOB '*[^A-Za-z0-9]*'"

# ★ 全局变量，记住当前是谁在登录
_current_user_id = None


def set_current_user(user_id):
    """登录成功后，必须调用此函数，告诉数据库现在是谁在使用"""
    global _current_user_id
    _current_user_id = str(user_id)
    # 确保该用户的文件夹存在
    get_user_dir(_current_user_id)


def get_current_user():
    return _current_user_id


def get_db_path():
    """动态获取当前用户的数据库完整路径"""
    if not _current_user_id:
        raise Exception("系统异常：未设置当前登录用户，无法连接数据库。")
    return os.path.join(get_user_dir(_current_user_id), 'piracy_records.db')


def get_conn():
    """获取当前用户的数据库连接"""
    return sqlite3.connect(get_db_path())


# ================= 1. DB 层格式约束：检测 / 清洗 / 迁移 =================
def _books_has_alnum_check(cursor):
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='books'"
    ).fetchone()
    if not row or not row[0]:
        return False
    return "[^A-Za-z0-9]" in row[0]


def _clean_invalid_book_ids(cursor):
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
    if not records:
        return
    log_dir = os.path.join(get_user_dir(_current_user_id), "logs")
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
    bad_records = _clean_invalid_book_ids(cursor)
    conn.commit()
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
                       SELECT id,
                              platform_id,
                              name,
                              pen_name,
                              aliases,
                              evidence_path,
                              rights_holder,
                              baidu_id
                       FROM books
                       ''')
        cursor.execute("DROP TABLE books")
        cursor.execute("ALTER TABLE books_new RENAME TO books")
        conn.commit()
        print("[DB迁移] books 表已重建，platform_id / baidu_id 已加 CHECK 约束")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    _log_migration(bad_records)


# ================= 2. 关键词字典自动生成 =================
def _sync_book_keywords(conn, cursor):
    """扫描 books 表，自动拆分曾用名，将词条同步到 book_keywords 字典表"""
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS book_keywords
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       book_id
                       INTEGER
                       NOT
                       NULL,
                       keyword
                       TEXT
                       NOT
                       NULL,
                       keyword_type
                       TEXT
                       NOT
                       NULL, -- 'name', 'pen_name', 'alias'
                       UNIQUE
                   (
                       book_id,
                       keyword,
                       keyword_type
                   ),
                       FOREIGN KEY
                   (
                       book_id
                   ) REFERENCES books
                   (
                       id
                   ) ON DELETE CASCADE
                       )
                   ''')

    books = cursor.execute("SELECT id, name, pen_name, aliases FROM books").fetchall()
    for b_id, name, pen_name, aliases in books:
        if name:
            cursor.execute("INSERT OR IGNORE INTO book_keywords (book_id, keyword, keyword_type) VALUES (?, ?, 'name')",
                           (b_id, name.strip()))

        if pen_name:
            cursor.execute(
                "INSERT OR IGNORE INTO book_keywords (book_id, keyword, keyword_type) VALUES (?, ?, 'pen_name')",
                (b_id, pen_name.strip()))

        if aliases:
            # 正则拆分中英文逗号、斜杠、反斜杠、竖线、顿号、空格
            split_aliases = re.split(r'[,，/\\|、\s]+', aliases)
            for a in split_aliases:
                a = a.strip()
                if a:
                    cursor.execute(
                        "INSERT OR IGNORE INTO book_keywords (book_id, keyword, keyword_type) VALUES (?, ?, 'alias')",
                        (b_id, a))
    conn.commit()


# ================= 3. 网站处理规则初始化 =================
def _init_site_rules(conn, cursor):
    """初始化网站规则表，并写入默认白名单"""
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS site_rules
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       domain
                       TEXT
                       UNIQUE
                       NOT
                       NULL,
                       category
                       TEXT,
                       strategy
                       TEXT,
                       description
                       TEXT
                   )
                   ''')

    # 检查是否为空，如果为空，写入出厂默认规则
    count = cursor.execute("SELECT COUNT(*) FROM site_rules").fetchone()[0]
    if count == 0:
        default_rules = [
            # 策略代码: ignore(跳过), netdisk(提取网盘), deep_crawl(深挖)
            ("jjwxc", "白名单", "ignore", "晋江正版，直接跳过"),
            ("qidian.com", "白名单", "ignore", "起点正版，直接跳过"),
            ("zongheng.com", "白名单", "ignore", "纵横正版，直接跳过"),
            ("pan.baidu.com", "网盘", "netdisk", "百度网盘直链"),
            ("pan.quark.cn", "网盘", "netdisk", "夸克网盘直链"),
            ("aliyundrive.com", "网盘", "netdisk", "阿里云盘直链"),
            ("alipan.com", "网盘", "netdisk", "阿里云盘直链")
        ]
        cursor.executemany(
            "INSERT INTO site_rules (domain, category, strategy, description) VALUES (?, ?, ?, ?)",
            default_rules
        )
        print("[DB初始化] 已写入默认网站规则。")
    conn.commit()


# ================= 4. 业务接口：供 UI 和 爬虫 层调用 =================
def record_search_log(book_id, keyword, keyword_type):
    """前端点击检索时调用，记录搜索行为"""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO search_logs (book_id, search_keyword, keyword_type) VALUES (?, ?, ?)",
            (book_id, keyword, keyword_type)
        )
        conn.commit()
    except Exception as e:
        print(f"记录搜索日志失败: {e}")
    finally:
        conn.close()


def get_recent_book_frequencies(days=7):
    """获取近 N 天内，每本书被搜索的频次"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT book_id, COUNT(*) as freq 
        FROM search_logs 
        WHERE search_time >= datetime('now', '-{days} days') 
        GROUP BY book_id
    ''')
    results = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}


def get_site_rules_dict():
    """获取爬虫调度所需的规则字典 {域名: 策略}"""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT domain, strategy FROM site_rules")
        rules = {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        rules = {}
    finally:
        conn.close()
    return rules


# ================= 5. 初始化主入口 =================
def init_db():
    """初始化当前用户的数据库"""
    if not _current_user_id:
        raise Exception("系统异常：未设置当前用户，无法初始化数据库。")

    conn = get_conn()
    # 开启外键约束
    conn.execute("PRAGMA foreign_keys=ON")
    cursor = conn.cursor()

    # 1. 初始化 books 表
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

    book_columns_to_add = [("evidence_path", "TEXT"), ("rights_holder", "TEXT"), ("baidu_id", "TEXT")]
    for col_name, col_type in book_columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE books ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    if not _books_has_alnum_check(cursor):
        _migrate_books_add_check(conn, cursor)

    # 2. 初始化 sites 表
    cursor.execute('''CREATE TABLE IF NOT EXISTS sites
                      (
                          id
                          INTEGER
                          PRIMARY
                          KEY
                          AUTOINCREMENT,
                          category
                          TEXT,
                          site_url
                          TEXT
                          UNIQUE,
                          name
                          TEXT,
                          attr
                          TEXT,
                          feature_code
                          TEXT,
                          complaint_time
                          TEXT,
                          resource_status
                          TEXT,
                          book_id
                          INTEGER,
                          book_name
                          TEXT,
                          crawl_status
                          TEXT
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

    # 3. 初始化 records 表
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS records
           (
               id
               INTEGER
               PRIMARY
               KEY
               AUTOINCREMENT,
               date
               TEXT,
               attr
               TEXT,
               platform_id
               TEXT,
               book_name
               TEXT,
               url
               TEXT
               UNIQUE
           )''')

    # 4. 初始化 evidences 表
    ev_exists = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='evidences'"
    ).fetchone()

    if ev_exists:
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(evidences)").fetchall()]
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
        id
        INTEGER
        PRIMARY
        KEY
        AUTOINCREMENT,
        owner_type
        TEXT
        NOT
        NULL,
        owner_key
        TEXT
        NOT
        NULL,
        ev_type
        TEXT,
        file_path
        TEXT,
        UNIQUE
                      (
        owner_type,
        owner_key,
        ev_type
                      )
        )''')

    # 5. 初始化 search_logs 表（记录搜索频率）
    cursor.execute('''CREATE TABLE IF NOT EXISTS search_logs
                      (
                          id
                          INTEGER
                          PRIMARY
                          KEY
                          AUTOINCREMENT,
                          book_id
                          INTEGER,
                          search_keyword
                          TEXT,
                          keyword_type
                          TEXT,
                          search_time
                          TIMESTAMP
                          DEFAULT
                          CURRENT_TIMESTAMP
                      )''')

    # 6. 自动构建专属关键词字典表
    _sync_book_keywords(conn, cursor)

    # 7. 初始化网站处理规则表
    _init_site_rules(conn, cursor)

    conn.commit()
    conn.close()