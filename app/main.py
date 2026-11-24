# -*- coding: utf-8 -*-
"""飞书文档密码管理器 - FastAPI 后端。"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db, scheduler, service
from .feishu import FeishuError


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="飞书文档密码管理器", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ---------- 模型 ----------

class AuthIn(BaseModel):
    app_id: str
    app_secret: str


class EntryIn(BaseModel):
    url: str
    cron: Optional[str] = None  # 5 字段 cron 表达式，如 "0 9 * * *"，留空则不定时


class CronIn(BaseModel):
    cron: Optional[str] = None


class BatchIn(BaseModel):
    ids: list[int]


# ---------- 页面 ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ---------- 认证 ----------

@app.post("/api/auth")
def save_auth(body: AuthIn):
    db.save_auth(body.app_id.strip(), body.app_secret.strip())
    return {"ok": True, **db.auth_status()}


@app.get("/api/auth")
def auth_status():
    return db.auth_status()


# ---------- 条目 ----------

@app.get("/api/entries")
def list_entries():
    return db.list_entries()


@app.post("/api/entries")
def add_entry(body: EntryIn):
    if body.cron and not scheduler.validate_cron(body.cron):
        raise HTTPException(400, "cron 表达式不合法，应为 5 字段，如 0 9 * * *")
    try:
        entry = service.add_entry(body.url, body.cron)
    except FeishuError as e:
        raise HTTPException(400, f"{e.msg} {e.hint}".strip())
    scheduler.schedule_entry(entry)
    return entry


@app.put("/api/entries/{entry_id}/cron")
def update_cron(entry_id: int, body: CronIn):
    if not db.get_entry(entry_id):
        raise HTTPException(404, "条目不存在")
    if body.cron and not scheduler.validate_cron(body.cron):
        raise HTTPException(400, "cron 表达式不合法，应为 5 字段，如 0 9 * * *")
    db.update_entry_cron(entry_id, (body.cron or "").strip() or None)
    scheduler.schedule_entry(db.get_entry(entry_id))
    return db.get_entry(entry_id)


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int):
    if not db.get_entry(entry_id):
        raise HTTPException(404, "条目不存在")
    scheduler.remove_entry(entry_id)
    db.delete_entry(entry_id)
    return {"ok": True}


@app.post("/api/entries/{entry_id}/refresh")
def refresh_one(entry_id: int):
    if not db.get_entry(entry_id):
        raise HTTPException(404, "条目不存在")
    result = service.refresh_entry(entry_id)
    return {**result, **db.get_entry(entry_id)}


@app.post("/api/entries/refresh-all")
def refresh_all():
    """一键刷新全部条目。"""
    results = {}
    for entry in db.list_entries():
        results[entry["id"]] = service.refresh_entry(entry["id"])
    return {"results": results, "entries": db.list_entries()}


@app.post("/api/entries/batch-refresh")
def batch_refresh(body: BatchIn):
    """一键刷新选中的多个条目。"""
    results = {}
    for entry_id in body.ids:
        if db.get_entry(entry_id):
            results[entry_id] = service.refresh_entry(entry_id)
    return {"results": results, "entries": db.list_entries()}


@app.get("/api/jobs")
def list_jobs():
    """查看当前已注册的定时任务（调试用）。"""
    return [
        {"id": j.id, "next_run": str(j.next_run_time)}
        for j in scheduler.scheduler.get_jobs()
    ]


# ---------- 对外接口：按条目 id 查询最新密码 ----------

@app.get("/api/password/{entry_id}")
def get_password(entry_id: int):
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "条目不存在")
    return {
        "id": entry["id"],
        "url": entry["url"],
        "status": entry["status"],
        "password": entry["password"],
        "message": "权限不足" if entry["status"] == service.STATUS_DENIED else (entry["status_msg"] or ""),
        "last_refresh": entry["last_refresh"],
    }
