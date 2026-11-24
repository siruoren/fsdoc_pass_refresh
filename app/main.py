# -*- coding: utf-8 -*-
"""飞书文档密码管理器 - FastAPI 后端。"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import db, pageauth, scheduler, service
from .feishu import FeishuError


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="飞书文档密码管理器", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# 无需页面认证的路径（favicon、登录/会话查询接口）
PUBLIC_PATHS = {"/api/login", "/api/session", "/favicon.ico", "/favicon.svg"}

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<path d="M12 2 4 5v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V5l-8-3z" fill="#3370ff"/>
<path d="M10.9 15.3 7.6 12l1.4-1.4 1.9 1.9 4.1-4.1 1.4 1.4-5.5 5.5z" fill="#fff"/>
</svg>"""


@app.middleware("http")
async def page_auth_middleware(request: Request, call_next):
    """页面访问密码认证：未认证时 API 返回 401，由前端展示登录界面。

    API 支持两种认证方式：
    - Cookie（浏览器登录后自动携带）
    - Authorization: Bearer <访问密码或登录token> 请求头，供外部程序调用
    """
    path = request.url.path
    if path not in PUBLIC_PATHS and path != "/":
        if not _authorized(request):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "未认证，请先登录"}, status_code=401)
            return PlainTextResponse("Not Found", status_code=404)
    return await call_next(request)


def _authorized(request: Request) -> bool:
    token = request.cookies.get(pageauth.SESSION_COOKIE)
    if pageauth.verify_token(token):
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        value = auth[7:].strip()
        if not value:
            return False
        # API 认证密码（已设置时优先且独立生效）
        if pageauth.api_password_configured():
            return pageauth.verify_api_password(value)
        # 未设置 API 密码时回退到访问密码，再兼容登录 token
        return pageauth.verify_page_password(value) or pageauth.verify_token(value)
    return False


# ---------- 模型 ----------

class AuthIn(BaseModel):
    app_id: str
    app_secret: str


class EntryIn(BaseModel):
    url: str
    cron: Optional[str] = None  # 5 字段 cron 表达式，如 "0 9 * * *"，留空则不定时
    id: Optional[int] = None    # 手动指定条目 ID，留空自增；已存在则报错不保存


class CronIn(BaseModel):
    cron: Optional[str] = None


class MessageIn(BaseModel):
    message: Optional[str] = None  # 用户手动输入的备注，随密码接口返回


class ApiPwdIn(BaseModel):
    password: Optional[str] = None  # API 认证密码，空表示清除（回退用访问密码认证）


class BatchIn(BaseModel):
    ids: list[int]


# ---------- 页面 ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/favicon.svg")
def favicon():
    return Response(FAVICON_SVG, media_type="image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico():
    return Response(FAVICON_SVG, media_type="image/svg+xml")


# ---------- 页面访问认证 ----------

class LoginIn(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginIn):
    if not pageauth.verify_page_password(body.password):
        raise HTTPException(401, "访问密码错误")
    token = pageauth.make_token()
    resp = JSONResponse({"ok": True, "token": token})
    resp.set_cookie(
        pageauth.SESSION_COOKIE, token,
        max_age=pageauth.SESSION_TTL, httponly=True, samesite="lax", path="/",
    )
    return resp


class ChangePwdIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/change-password")
def change_password(body: ChangePwdIn):
    """修改页面访问密码：需验证原密码；改密后旧会话失效，当前设备重签发会话保持登录。"""
    if not pageauth.verify_page_password(body.old_password):
        raise HTTPException(400, "原密码错误")
    new_pwd = body.new_password.strip()
    if len(new_pwd) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    pageauth.set_page_password(new_pwd)
    token = pageauth.make_token()
    resp = JSONResponse({"ok": True, "token": token})
    resp.set_cookie(
        pageauth.SESSION_COOKIE, token,
        max_age=pageauth.SESSION_TTL, httponly=True, samesite="lax", path="/",
    )
    return resp


@app.post("/api/logout")
def logout():
    """注销会话：清除认证 Cookie。"""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(pageauth.SESSION_COOKIE, path="/")
    return resp


@app.get("/api/session")
def session_status(request: Request):
    token = request.cookies.get(pageauth.SESSION_COOKIE)
    return {"authenticated": pageauth.verify_token(token)}


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
    if body.id is not None and db.get_entry(body.id):
        raise HTTPException(400, f"ID {body.id} 已存在，请更换条目 ID")
    try:
        entry = service.add_entry(body.url, body.cron, body.id)
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


@app.put("/api/entries/{entry_id}/message")
def update_message(entry_id: int, body: MessageIn):
    """编辑条目备注（message），随对外密码接口返回。"""
    if not db.get_entry(entry_id):
        raise HTTPException(404, "条目不存在")
    db.update_entry_message(entry_id, (body.message or "").strip() or None)
    return db.get_entry(entry_id)


@app.get("/api/api-password")
def api_password_status():
    return {"configured": pageauth.api_password_configured()}


@app.put("/api/api-password")
def set_api_password(body: ApiPwdIn):
    """设置/清除 API 认证密码（独立于页面访问密码，存库）。"""
    pwd = (body.password or "").strip()
    if not pwd:
        pageauth.clear_api_password()
        return {"ok": True, "configured": False}
    if len(pwd) < 6:
        raise HTTPException(400, "API 认证密码至少 6 位")
    pageauth.set_api_password(pwd)
    return {"ok": True, "configured": True}


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
        "message": entry["message"]
                   or ("权限不足" if entry["status"] == service.STATUS_DENIED else (entry["status_msg"] or "")),
        "last_refresh": entry["last_refresh"],
    }
