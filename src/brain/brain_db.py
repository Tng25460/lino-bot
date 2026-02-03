#!/usr/bin/env python3
import os, sqlite3, time, json

DB_PATH = os.getenv("BRAIN_DB", "state/brain.sqlite")

def connect():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init_db():
    from pathlib import Path
    schema = Path("src/brain/schema.sql").read_text(encoding="utf-8")
    con = connect()
    con.executescript(schema)
    con.commit()
    con.close()

def kv_set(k: str, v: str):
    con = connect()
    con.execute("INSERT OR REPLACE INTO brain_kv(k,v) VALUES(?,?)", (k, v))
    con.commit()
    con.close()

def kv_get(k: str, default=None):
    con = connect()
    cur = con.execute("SELECT v FROM brain_kv WHERE k=?", (k,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else default

if __name__ == "__main__":
    init_db()
    print("[OK] brain db init ->", DB_PATH)
