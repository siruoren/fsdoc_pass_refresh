# -*- coding: utf-8 -*-
"""业务逻辑：刷新条目密码。"""
from datetime import datetime

from . import db, feishu
from .feishu import FeishuError

# 状态常量
STATUS_OK = "正常"
STATUS_DENIED = "权限不足"
STATUS_FAILED = "刷新失败"
STATUS_NO_AUTH = "未配置认证"


def refresh_entry(entry_id: int) -> dict:
    """刷新单个条目的密码，并落库。返回 {status, password, msg}。"""
    entry = db.get_entry(entry_id)
    if not entry:
        raise KeyError(entry_id)

    auth = db.get_auth()
    if not auth:
        db.save_refresh_result(entry_id, None, STATUS_NO_AUTH,
                               "尚未配置应用认证信息，请先点击「认证」保存 App ID / App Secret")
        return {"status": STATUS_NO_AUTH, "password": None,
                "msg": "未配置认证信息"}

    try:
        access_token = feishu.get_tenant_access_token(auth["app_id"], auth["app_secret"])
        # 顺带更新文档名称（失败不影响主流程）
        title = feishu.get_doc_title(entry["doc_token"], entry["doc_type"], access_token)
        if title:
            db.update_entry_title(entry_id, title)
        notice = feishu.check_or_fix_link_share(entry["doc_token"], entry["doc_type"], access_token)
        password = feishu.rotate_password(entry["doc_token"], entry["doc_type"], access_token)
        db.save_refresh_result(entry_id, password, STATUS_OK, notice or "")
        return {"status": STATUS_OK, "password": password, "msg": notice or ""}
    except FeishuError as e:
        if e.code == 1063002:
            # 权限不足：不更新/不显示密码，保留旧密码字段由前端隐藏
            db.save_refresh_result(entry_id, None, STATUS_DENIED,
                                   f"{e.msg}。{e.hint}")
            return {"status": STATUS_DENIED, "password": None,
                    "msg": f"{e.msg}。{e.hint}"}
        db.save_refresh_result(entry_id, None, STATUS_FAILED, f"{e.msg} {e.hint}".strip())
        return {"status": STATUS_FAILED, "password": None,
                "msg": f"{e.msg} {e.hint}".strip()}
    except Exception as e:  # 网络等异常
        db.save_refresh_result(entry_id, None, STATUS_FAILED, str(e))
        return {"status": STATUS_FAILED, "password": None, "msg": str(e)}


def add_entry(url: str, cron: str = None, entry_id: int = None) -> dict:
    doc_token, doc_type = feishu.parse_doc_url(url)
    if not doc_type:
        raise FeishuError(-1, "无法识别文档类型", "请使用完整的文档链接（/wiki/、/docx/、/sheet/ 等）")
    title = doc_token
    auth = db.get_auth()
    if auth:
        try:
            access_token = feishu.get_tenant_access_token(auth["app_id"], auth["app_secret"])
            fetched = feishu.get_doc_title(doc_token, doc_type, access_token)
            if fetched:
                title = fetched
        except Exception:
            pass  # 获取标题失败时先以 token 占位，刷新成功后会再次尝试
    entry_id = db.add_entry(url.strip(), doc_token, doc_type, title,
                            (cron or "").strip() or None, entry_id)
    return db.get_entry(entry_id)
