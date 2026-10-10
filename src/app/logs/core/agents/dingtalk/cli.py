"""钉钉 DWS CLI 的安全封装层。

把「语义化动作」映射到钉钉官方 ``dingtalk-workspace-cli`` 的子命令，
通过「白名单 + 参数列表」方式执行，全程不使用 shell=True，避免命令注入。

命令与参数 flag 已按 ``dws --help`` 校准，优先使用面向 Agent 的「+shortcut」语义化命令（自动解析姓名/群名/userId）。
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from app.logs.core.config import settings


class DingTalkError(RuntimeError):
    """钉钉 CLI 相关错误的基类，接口层据此映射成可读的 HTTP 响应。"""


class DingTalkNotInstalledError(DingTalkError):
    """dws 未安装，或不在 PATH 中。"""


class DingTalkWriteDisabledError(DingTalkError):
    """写操作总开关 ``DINGTALK_ENABLE_WRITE`` 未打开。"""


class DingTalkCommandError(DingTalkError):
    """dws 已执行但失败：退出码非零、执行超时，或输出无法解析。"""


@dataclass(frozen=True)
class _Action:
    """一个受白名单保护的 dws 子命令定义。

    Attributes:
        command: dws 子命令片段，如 ``("contact", "user", "search")``。
        params: 语义参数名到 CLI flag 的映射，如 ``{"query": "--query"}``。
        write: 是否为写操作；写操作受 ``DINGTALK_ENABLE_WRITE`` 开关控制。
    """

    command: tuple[str, ...]
    params: dict[str, str] = field(default_factory=dict)
    write: bool = False


# 语义动作名 -> dws 子命令；params 的键是语义参数名，值是 CLI flag。
# 命令已按 dws --help 校准：优先使用面向 Agent 的「+shortcut」语义化命令（自动解析姓名/群名/userId）。
_ACTIONS: dict[str, _Action] = {
    # ---- 通讯录 ----
    "contact_search": _Action(("contact", "+search-user"), {"query": "--query"}),
    # ---- 日历 ----
    "calendar_list": _Action(("calendar", "+today")),  # 查询今天的日程
    "calendar_create": _Action(
        ("calendar", "+book"),
        {"title": "--title", "start": "--start", "end": "--end", "attendees": "--with"},
        write=True,
    ),
    # ---- 待办 ----
    "todo_list": _Action(("todo", "+get-my-tasks"), {"status": "--status", "priority": "--priority"}),
    "todo_remind": _Action(("todo", "+remind"), {"task": "--task", "at": "--at"}, write=True),  # 给自己建待办
    "todo_assign": _Action(("todo", "+assign"), {"task": "--task", "to": "--to", "due": "--due"}, write=True),
    # ---- 消息 / 机器人 ----
    # 单聊：--to 只认姓名，同名多人时 CLI 会停下不发；改用 --user-query / --open-dingtalk-id 二选一。
    "message_send": _Action(
        ("chat", "+messages-send"),
        {
            "identity": "--as",
            "to_query": "--user-query",
            "open_dingtalk_id": "--open-dingtalk-id",
            "content": "--markdown",
        },
        write=True,
    ),
    "group_message_send": _Action(
        ("chat", "+send-to-group"), {"group": "--group", "content": "--content"}, write=True
    ),  # 群聊
    "robot_send": _Action(
        ("chat", "+messages-send"),
        {"identity": "--as", "webhook_token": "--webhook-token", "text": "--text"},
        write=True,
    ),
    # ---- 群搜索 / 群公告 ----
    "group_search": _Action(("chat", "+chat-search"), {"query": "--query"}),
    "notice_create": _Action(
        ("chat", "group", "notice", "create"),
        {
            "conversation_id": "--conversation-id",
            "content": "--content",
            "sticky": "--sticky",
            "send_ding": "--send-ding",
            "run_at": "--run-at",
        },
        write=True,
    ),
    # ---- DING 消息 ----
    "ding_send": _Action(
        ("ding", "+send-personal"), {"users": "--users", "content": "--content", "method": "--type"}, write=True
    ),
    # ---- 在线表格 ----
    "sheet_create": _Action(
        ("sheet", "create"), {"name": "--name", "folder": "--folder", "workspace": "--workspace"}, write=True
    ),
    # ---- 日志（日报） ----
    "log_list": _Action(("report", "+inbox-list")),  # 我收到的日志
    "log_create": _Action(
        ("report", "entry", "submit"),
        {"template_id": "--template-id", "contents": "--contents", "to_user_ids": "--to-user-ids"},
        write=True,
    ),
    # ---- 考勤 ----
    "attendance_get": _Action(("attendance", "+my-attendance")),  # 今日打卡流水
}


def is_available() -> bool:
    """检查 dws CLI 是否已安装并可执行。"""
    try:
        result = subprocess.run(
            [_resolve_binary(), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _resolve_binary() -> str:
    """解析 dws 可执行文件路径。

    npm 全局安装的 ``dws`` 在 Windows 上是 ``.cmd`` shim。直接拿裸名字 ``dws``
    交给 subprocess，Windows 只会去找 ``dws.exe``，找不到就报「未找到命令」，
    所以这里统一解析成 ``shutil.which`` 给出的完整路径；若 npm 包内带有原生
    ``dws.exe``（postinstall 下载的），则优先用它。

    配置了绝对路径时直接使用。
    """
    configured = settings.DINGTALK_DWS_BIN
    if Path(configured).is_absolute():
        return configured

    resolved = shutil.which(configured)

    if resolved and os.name == "nt":
        npm_bin = Path(resolved).parent
        candidate = npm_bin / "node_modules" / "dingtalk-workspace-cli" / "vendor" / "dws.exe"
        if candidate.is_file():
            return str(candidate)

    return resolved or configured


def _pick(payload: Any, *paths: str) -> Any:
    """按 ``a.b.c`` 路径逐层取值，返回第一个非空值。"""
    for path in paths:
        node: Any = payload
        for part in path.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        if node:
            return node
    return None


def _format_candidates(candidates: Any) -> str:
    """把 dws 的目标候选列表压成「姓名（openDingTalkId）」多行文本。"""
    if not isinstance(candidates, list):
        return ""
    lines = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("userName") or item.get("nickname") or ""
        ident = item.get("openDingTalkId") or item.get("open_dingtalk_id") or item.get("id") or ""
        if name or ident:
            lines.append(f"  · {name}（{ident}）" if name and ident else f"  · {name or ident}")
    return "\n".join(lines)


def _describe_failure(output: str, returncode: int) -> str:
    """把 dws 的结构化失败输出翻译成中文说明；解析不出来就原样返回。

    dws 失败时把 JSON 写到 stderr，外层结构是 ``{"error": {...}}``，目标解析失败
    还会带上候选列表。直接把这坨 JSON 甩给用户等于没说，这里抽出原因和候选。
    """
    prefix = f"钉钉 CLI 执行失败（exit {returncode}）"
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return f"{prefix}：{output}"

    reason = _pick(payload, "error.reason", "reason", "error.message", "message", "error.hint", "hint")
    candidates = _pick(
        payload,
        "error.details.resolution.candidates",
        "error.details.candidates",
        "details.resolution.candidates",
        "details.candidates",
        "resolution.candidates",
        "candidates",
    )
    if not reason and not candidates:
        return f"{prefix}：{output}"

    lines = [f"{prefix}：{reason or '目标解析失败'}"]
    block = _format_candidates(candidates)
    if block:
        lines.append("候选：")
        lines.append(block)
        lines.append("同名多人时请改用 openDingTalkId 指定收件人。")
    return "\n".join(lines)


def run_dws(action: str, *, confirm: bool = False, **params: Any) -> str:
    """执行一个白名单内的 dws 子命令并返回文本输出。

    Args:
        action: 动作名，必须是 ``_ACTIONS`` 的键。
        confirm: 写操作是否已获用户确认；确认后追加 ``--yes`` 跳过 dws 的交互确认。
        **params: 语义参数，键必须是该动作允许的参数名；None / False 会被跳过。

    Raises:
        ValueError: 动作名或参数名不在白名单内。
        RuntimeError: dws 未安装、执行超时或退出码非零。
    """
    spec = _ACTIONS.get(action)
    if spec is None:
        raise ValueError(f"未注册的钉钉操作：{action}")

    if spec.write and not settings.DINGTALK_ENABLE_WRITE:
        raise DingTalkWriteDisabledError("钉钉写操作未开启，请在 src/.env 中设置 DINGTALK_ENABLE_WRITE=true")

    args: list[str] = [_resolve_binary(), *spec.command]
    for name, value in params.items():
        flag = spec.params.get(name)
        if flag is None:
            raise ValueError(f"操作 {action} 不支持参数 {name}")
        if value is None or value is False:
            continue
        if value is True:
            args.append(flag)
        else:
            args.extend([flag, str(value)])

    if confirm:
        args.append("--yes")

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.DINGTALK_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise DingTalkNotInstalledError(
            f"未找到 dws 命令（{_resolve_binary()}），请先执行 npm install -g dingtalk-workspace-cli 并 dws auth login"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DingTalkCommandError(
            f"钉钉 CLI 执行超时（{settings.DINGTALK_TIMEOUT_SECONDS}s）：{' '.join(args)}"
        ) from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    # dws 的成功输出走 stdout、错误走 stderr；失败时优先用 stderr，避免丢掉真正的原因。
    output = (stderr or stdout) if result.returncode != 0 else (stdout or stderr)
    if result.returncode != 0:
        raise DingTalkCommandError(_describe_failure(output, result.returncode))

    max_chars = settings.DINGTALK_OUTPUT_MAX_CHARS
    if len(output) > max_chars:
        output = output[:max_chars] + "\n…（输出过长，已截断）"
    return output


def auth_status() -> dict[str, Any]:
    """查询钉钉登录状态，返回解析后的 JSON（含 authenticated、user_name 等）。"""
    try:
        result = subprocess.run(
            [_resolve_binary(), "auth", "status", "-f", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise DingTalkNotInstalledError(
            f"未找到 dws 命令（{_resolve_binary()}），请先执行 npm install -g dingtalk-workspace-cli"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DingTalkCommandError("查询钉钉登录状态超时（15s）") from exc

    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        raise DingTalkCommandError(f"查询登录状态失败：{output}")
    try:
        return cast(dict[str, Any], json.loads(output))
    except json.JSONDecodeError as exc:
        raise DingTalkCommandError(f"解析登录状态失败：{output}") from exc


def auth_login() -> None:
    """后台触发钉钉扫码登录（Loopback 流，会在本机打开浏览器授权）。

    不等待授权完成，登录进度通过 :func:`auth_status` 轮询。
    """
    try:
        subprocess.Popen(
            [_resolve_binary(), "auth", "login"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise DingTalkNotInstalledError(
            f"未找到 dws 命令（{_resolve_binary()}），请先执行 npm install -g dingtalk-workspace-cli"
        ) from exc
