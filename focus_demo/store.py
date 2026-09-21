"""SQLite 审计存储；采集、补丁、提示词和模型结果分开保存。"""
import json  # 导入运行所需模块。
import sqlite3  # 导入运行所需模块。
import threading  # 导入运行所需模块。
import time  # 导入运行所需模块。
from pathlib import Path  # 导入本模块需要的接口。
from .common import dumps, digest  # 导入本模块需要的接口。


class Store:  # 封装当前组件的状态与接口。
    """提供少量存取接口；不开放修改原始样本的 API。"""
    def __init__(self, path):  # 定义当前功能的处理入口。
        self.path = Path(path)  # 保存文件路径。
        self.path.parent.mkdir(parents=True, exist_ok=True)  # 保存文件路径。
        self.lock = threading.RLock()  # 保存下一步骤使用的计算结果。
        self.db = sqlite3.connect(self.path, check_same_thread=False)  # 保存下一步骤使用的计算结果。
        self.db.row_factory = sqlite3.Row  # 保存下一步骤使用的计算结果。
        self.db.execute("PRAGMA synchronous=FULL")  # 提高已确认契约在异常退出后的持久性。
        self.db.execute("PRAGMA busy_timeout=5000")  # 有界等待写锁。
        self.db.execute("PRAGMA journal_mode=WAL")  # 执行参数化的数据库操作。
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS samples(
                id INTEGER PRIMARY KEY, task_id TEXT NOT NULL,
                ts REAL NOT NULL, mono REAL NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents(
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(kind, id)
            );
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY, ts REAL NOT NULL,
                event TEXT NOT NULL, body TEXT NOT NULL
            );
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS samples_task_id ON samples(task_id,id)")  # 避免按任务检索扫描全部历史。
        self.db.commit()  # 执行当前步骤并保留既定边界。

    def add_sample(self, task_id, sample):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            cursor = self.db.execute("INSERT INTO samples(task_id,ts,mono,body,sha256) VALUES(?,?,?,?,?)", (task_id, sample["ts"], sample["mono"], dumps(sample), digest(sample)))  # 执行参数化的数据库操作。
            self.db.commit()  # 执行当前步骤并保留既定边界。
            return cursor.lastrowid  # 返回本步骤的结果。

    def samples(self, task_id, after=0):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            rows = self.db.execute("SELECT * FROM samples WHERE task_id=? AND id>=? ORDER BY id", (task_id, after)).fetchall()  # 执行参数化的数据库操作。
            return [{"sample_id": row["id"], "sha256": row["sha256"], **json.loads(row["body"])} for row in rows]  # 返回本步骤的结果。

    def save(self, kind, value):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            self.db.execute("INSERT OR REPLACE INTO documents(kind,id,body) VALUES(?,?,?)", (kind, value["id"], dumps(value)))  # 执行参数化的数据库操作。
            self.db.commit()  # 执行当前步骤并保留既定边界。

    def get(self, kind, identifier):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            row = self.db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, identifier)).fetchone()  # 执行参数化的数据库操作。
            return json.loads(row["body"]) if row else None  # 返回本步骤的结果。

    def all(self, kind):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            rows = self.db.execute("SELECT body FROM documents WHERE kind=? ORDER BY rowid", (kind,)).fetchall()  # 执行参数化的数据库操作。
            return [json.loads(row["body"]) for row in rows]  # 返回本步骤的结果。

    def log(self, event, body):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            self.db.execute("INSERT INTO audit(ts,event,body) VALUES(?,?,?)", (time.time(), event, dumps(body)))  # 执行参数化的数据库操作。
            self.db.commit()  # 执行当前步骤并保留既定边界。

    def logs(self, limit=40):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            rows = self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()  # 执行参数化的数据库操作。
            return [{**dict(row), "body": json.loads(row["body"])} for row in rows]  # 返回本步骤的结果。

    def close(self):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            self.db.close()  # 执行当前步骤并保留既定边界。
