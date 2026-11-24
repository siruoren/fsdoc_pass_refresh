# -*- coding: utf-8 -*-
"""飞书 OpenAPI 客户端：tenant_token、链接分享检查、密码启用/刷新。

参考官方文档：
- 启用密码: POST /drive/v1/permissions/:token/public/password （服务端随机生成）
- 刷新密码: PUT  /drive/v1/permissions/:token/public/password
- 前置条件: 链接分享须为「互联网上获得链接的人可阅读/可编辑」
- 1063002: 调用身份对文档权限不足
"""
import re
import urllib.parse

import requests

BASE = "https://open.feishu.cn/open-apis"
TIMEOUT = 30

TYPE_MAP = {
    "wiki": "wiki",
    "docx": "docx",
    "doc": "doc",
    "sheet": "sheet",
    "file": "file",
    "base": "bitable",
    "bitable": "bitable",
}


class FeishuError(Exception):
    """业务错误，code 为飞书错误码或 -1。"""

    def __init__(self, code, msg, hint=None):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.hint = hint or ""


def parse_doc_url(doc_url: str):
    """从 URL 或裸 token 解析 (token, type)。"""
    doc_url = doc_url.strip()
    m = re.search(r"/(wiki|docx|doc|sheet|file|base|bitable)/([A-Za-z0-9]+)", doc_url)
    if m:
        return m.group(2), TYPE_MAP[m.group(1)]
    if "token=" in doc_url and "type=" in doc_url:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(doc_url).query)
        return qs["token"][0], TYPE_MAP[qs["type"][0]]
    return doc_url, None


def _handle(resp):
    """统一处理飞书响应 {"code", "msg", "data"...}。"""
    result = resp.json()
    code = result.get("code")
    msg = result.get("msg", "")
    if code not in (0, None):
        hint = ""
        if code == 1063002:
            hint = "应用不是该文档的协作者/权限不足，请在文档页面「...」->「...更多」->「添加文档应用」中为应用授权"
        raise FeishuError(code, msg, hint)
    return result


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    try:
        resp = requests.post(
            f"{BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=TIMEOUT,
        )
        result = resp.json()
    except Exception as e:
        raise FeishuError(-1, f"请求飞书认证接口失败: {e}")
    if result.get("code") != 0:
        raise FeishuError(result.get("code"), result.get("msg"), "请检查 App ID / App Secret 是否正确")
    return result["tenant_access_token"]


def get_link_share(token, doc_type, access_token):
    result = _handle(
        requests.get(
            f"{BASE}/drive/v2/permissions/{token}/public",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"type": doc_type},
            timeout=TIMEOUT,
        )
    )
    return (result.get("data", {}).get("permission") or {}).get("link_share_entity", "")


def set_link_share_readable(token, doc_type, access_token):
    _handle(
        requests.patch(
            f"{BASE}/drive/v2/permissions/{token}/public",
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json; charset=utf-8"},
            params={"type": doc_type},
            json={"link_share_entity": "anyone_readable"},
            timeout=TIMEOUT,
        )
    )


def enable_password(token, doc_type, access_token):
    result = _handle(
        requests.post(
            f"{BASE}/drive/v1/permissions/{token}/public/password",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"type": doc_type},
            timeout=TIMEOUT,
        )
    )
    return result.get("data", {}).get("password")


def refresh_password(token, doc_type, access_token):
    result = _handle(
        requests.put(
            f"{BASE}/drive/v1/permissions/{token}/public/password",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"type": doc_type},
            timeout=TIMEOUT,
        )
    )
    return result.get("data", {}).get("password")


def rotate_password(token, doc_type, access_token) -> str:
    """启用（POST）或刷新（PUT）密码，返回新密码。"""
    try:
        return enable_password(token, doc_type, access_token)
    except FeishuError as e:
        # 已有密码时 POST 可能失败，改用 PUT 刷新
        return refresh_password(token, doc_type, access_token)


def check_or_fix_link_share(token, doc_type, access_token):
    """检查链接分享设置，未对互联网开放则自动设置为可阅读。返回提示信息或 None。"""
    link_share = get_link_share(token, doc_type, access_token)
    if link_share.startswith("anyone"):
        return None
    set_link_share_readable(token, doc_type, access_token)
    return f"链接分享原为「{link_share or '未开启'}」，已自动设置为互联网可阅读"
