"""本机持久会话。浏览器凭随机 Cookie 访问自己的会话，聊天不写入知识图谱。"""
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from answer_presentation import present_answer


DB_PATH = Path(os.getenv("CHAT_DB_PATH", Path(__file__).parent / "data" / "chats.sqlite3"))
COOKIE_NAME = "kg_chat_owner"


class ChatNotFound(Exception):
    pass


class ChatBusy(Exception):
    pass


def owner_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            course_id TEXT, node_id TEXT, context_source TEXT NOT NULL DEFAULT 'knowledge_graph',
            busy_token TEXT, busy_until REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS chats_by_owner ON conversations(owner, updated_at);
        CREATE TABLE IF NOT EXISTS exchanges (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            request_id TEXT NOT NULL, question TEXT NOT NULL, response TEXT NOT NULL,
            created_at REAL NOT NULL, UNIQUE(conversation_id, request_id)
        );
    """)
    if "context_source" not in {row[1] for row in connection.execute("PRAGMA table_info(conversations)")}:
        try:
            connection.execute("ALTER TABLE conversations ADD COLUMN context_source TEXT NOT NULL DEFAULT 'knowledge_graph'")
            connection.commit()
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                connection.close()
                raise
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def require_chat(db, owner, chat_id):
    row = db.execute("SELECT * FROM conversations WHERE id=? AND owner=?", (chat_id, owner)).fetchone()
    if row is None:
        raise ChatNotFound()
    return row


def public_chat(row):
    return {key: row[key] for key in ("id", "title", "created_at", "updated_at", "course_id", "node_id", "context_source")}


def create_chat(owner):
    chat_id, now = secrets.token_urlsafe(24), time.time()
    with database() as db:
        db.execute("INSERT INTO conversations(id,owner,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                   (chat_id, owner, "新对话", now, now))
        return public_chat(require_chat(db, owner, chat_id))


def list_chats(owner):
    with database() as db:
        return [public_chat(row) for row in db.execute(
            "SELECT * FROM conversations WHERE owner=? ORDER BY updated_at DESC", (owner,))]


def get_chat(owner, chat_id):
    with database() as db:
        chat = public_chat(require_chat(db, owner, chat_id))
        chat["messages"] = []
        for row in db.execute("SELECT * FROM exchanges WHERE conversation_id=? ORDER BY seq", (chat_id,)):
            response = json.loads(row["response"])
            response["answer"] = present_answer(response["answer"], row["question"])
            chat["messages"].extend([
                dict(role="user", content=row["question"], created_at=row["created_at"]),
                dict(role="assistant", content=response["answer"],
                     result=response, created_at=row["created_at"]),
            ])
        return chat


def change_chat(owner, chat_id, title=None, delete=False):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        chat = require_chat(db, owner, chat_id)
        if chat["busy_until"] > time.time():
            raise ChatBusy()
        if delete:
            db.execute("DELETE FROM conversations WHERE id=?", (chat_id,))
        else:
            db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, time.time(), chat_id))


def begin_turn(owner, chat_id, request_id):
    """原子锁定会话，拒绝并发打乱轮次，并允许已完成请求安全重试。"""
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        chat = require_chat(db, owner, chat_id)
        cached = db.execute("SELECT question,response FROM exchanges WHERE conversation_id=? AND request_id=?",
                            (chat_id, request_id)).fetchone()
        if cached:
            response = json.loads(cached["response"])
            response["answer"] = present_answer(response["answer"], cached["question"])
            return None, [], response
        if chat["busy_until"] > time.time():
            raise ChatBusy()
        token = secrets.token_urlsafe(24)
        db.execute("UPDATE conversations SET busy_token=?, busy_until=? WHERE id=?",
                   (token, time.time() + 600, chat_id))
        rows = list(db.execute("SELECT question,response FROM exchanges WHERE conversation_id=? ORDER BY seq DESC LIMIT 10", (chat_id,)))
        # 保存完整历史，模型采用最近十轮、最多约 16000 字的完整问答对。
        history, size = [], 0
        for row in rows:
            question, answer = row["question"], json.loads(row["response"])["answer"]
            answer = present_answer(answer, question)
            pair_size = len(question) + len(answer)
            if history and size + pair_size > 16000:
                break
            history[0:0] = [dict(role="user", content=question), dict(role="assistant", content=answer[:15000])]
            size += pair_size
        return token, history, None


def finish_turn(owner, chat_id, token, request_id, question, result, course_id, node_id, context_source="knowledge_graph"):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        chat = require_chat(db, owner, chat_id)
        if chat["busy_token"] != token:
            raise ChatBusy()
        now = time.time()
        first = not db.execute("SELECT 1 FROM exchanges WHERE conversation_id=? LIMIT 1", (chat_id,)).fetchone()
        db.execute("INSERT INTO exchanges(conversation_id,request_id,question,response,created_at) VALUES(?,?,?,?,?)",
                   (chat_id, request_id, question, json.dumps(result, ensure_ascii=False), now))
        title = question[:32] if first and chat["title"] == "新对话" else chat["title"]
        db.execute("UPDATE conversations SET title=?,updated_at=?,course_id=?,node_id=?,context_source=?,busy_token=NULL,busy_until=0 WHERE id=?",
                   (title, now, course_id, node_id, context_source if node_id else "knowledge_graph", chat_id))


def release_turn(owner, chat_id, token):
    if token:
        with database() as db:
            db.execute("UPDATE conversations SET busy_token=NULL,busy_until=0 WHERE id=? AND owner=? AND busy_token=?",
                       (chat_id, owner, token))
