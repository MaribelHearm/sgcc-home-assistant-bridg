from __future__ import annotations

import io
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol
from urllib.parse import urlsplit

import requests

from .notify import UrlLoginQrCodeNotify
from .redact import redact_text


_SMS_CODE_RE = re.compile(r"^\d{4,8}$")
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_SMS_WAIT_SECONDS = 180


class LoginInteraction(Protocol):
    def send_qr_code(self, qrcode: bytes, reason: str) -> bool:
        ...

    def request_sms_code(self, reason: str) -> Optional[str]:
        ...

    def notify_result(self, method: str, success: bool, detail: str = "") -> bool:
        ...


class NoopLoginInteraction:
    def send_qr_code(self, qrcode: bytes, reason: str) -> bool:
        return False

    def request_sms_code(self, reason: str) -> Optional[str]:
        return None

    def notify_result(self, method: str, success: bool, detail: str = "") -> bool:
        return False


class UrlLoginInteraction(NoopLoginInteraction):
    def send_qr_code(self, qrcode: bytes, reason: str) -> bool:
        return UrlLoginQrCodeNotify()(qrcode, _safe_reason(reason))


class CompositeLoginInteraction:
    def __init__(self, interactions: list[LoginInteraction]):
        self.interactions = interactions

    def send_qr_code(self, qrcode: bytes, reason: str) -> bool:
        results = [_safe_call(item.send_qr_code, qrcode, reason) for item in self.interactions]
        return any(results)

    def request_sms_code(self, reason: str) -> Optional[str]:
        for interaction in self.interactions:
            code = _safe_call(interaction.request_sms_code, reason)
            if code:
                return code
        return None

    def notify_result(self, method: str, success: bool, detail: str = "") -> bool:
        results = [_safe_call(item.notify_result, method, success, detail) for item in self.interactions]
        return any(results)


@dataclass
class TelegramLoginInteraction:
    token: str
    chat_id: str
    api_base_url: str = "https://api.telegram.org"
    request_timeout: float = _DEFAULT_TIMEOUT
    sms_wait_seconds: int = _DEFAULT_SMS_WAIT_SECONDS
    _next_update_offset: Optional[int] = field(default=None, init=False, repr=False)

    @classmethod
    def from_env(cls) -> Optional["TelegramLoginInteraction"]:
        token = _first_env("SGCC_TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN")
        chat_id = _first_env("SGCC_TELEGRAM_CHAT_ID", "TG_CHAT_ID")
        if not token or not chat_id:
            return None
        api_base_url = _first_env(
            "SGCC_TELEGRAM_API_BASE_URL",
            "TG_API_BASE_URL",
        ) or "https://api.telegram.org"
        if "://" not in api_base_url:
            api_base_url = f"https://{api_base_url}"
        api_base_url = api_base_url.rstrip("/")
        parsed = urlsplit(api_base_url)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            logging.warning(
                "Telegram API Base URL 必须是无凭证、无查询参数的 HTTPS 地址，"
                "登录交互已禁用。"
            )
            return None
        return cls(
            token=token,
            chat_id=chat_id,
            api_base_url=api_base_url,
            request_timeout=_env_float("PUSH_TIMEOUT", _DEFAULT_TIMEOUT, minimum=1.0),
            sms_wait_seconds=_env_int(
                "SGCC_SMS_CODE_TIMEOUT_SECONDS",
                _DEFAULT_SMS_WAIT_SECONDS,
                minimum=30,
                maximum=600,
            ),
        )

    @property
    def bot_url(self) -> str:
        return f"{self.api_base_url}/bot{self.token}"

    def send_qr_code(self, qrcode: bytes, reason: str) -> bool:
        result = self._post(
            "sendPhoto",
            data={
                "chat_id": self.chat_id,
                "caption": "国家电网登录需要扫码。二维码仅用于本次登录，请尽快使用网上国网 App 扫描。"
                f"\n原因：{_safe_reason(reason)}",
            },
            files={"photo": ("qrcode.png", io.BytesIO(qrcode), "image/png")},
        )
        return bool(result)

    def request_sms_code(self, reason: str) -> Optional[str]:
        next_update_id = self._next_update_id()
        if next_update_id is None:
            return None
        prompt = self._post(
            "sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": "国家电网登录需要短信验证码。请直接回复本消息，发送 4～8 位纯数字验证码。"
                "验证码只用于本次登录，不会写入日志。"
                f"\n原因：{_safe_reason(reason)}",
                "reply_markup": {"force_reply": True, "selective": True},
            },
        )
        if not prompt:
            return None
        prompt_message_id = prompt.get("message_id")
        if prompt_message_id is None:
            return None

        deadline = time.monotonic() + self.sms_wait_seconds
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            poll_timeout = min(20, remaining)
            result = self._post(
                "getUpdates",
                json={
                    "offset": next_update_id,
                    "timeout": poll_timeout,
                    "allowed_updates": ["message"],
                },
                timeout=poll_timeout + self.request_timeout,
            )
            if result is None:
                return None
            for update in result:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    next_update_id = max(next_update_id, update_id + 1)
                    self._next_update_offset = next_update_id
                message = update.get("message") or {}
                if str((message.get("chat") or {}).get("id")) != str(self.chat_id):
                    continue
                reply_to = message.get("reply_to_message") or {}
                if reply_to.get("message_id") != prompt_message_id:
                    continue
                code = str(message.get("text") or "").strip()
                if _SMS_CODE_RE.fullmatch(code):
                    logging.info("已从 Telegram 收到本次登录的短信验证码回复。")
                    return code
                self._post(
                    "sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": "验证码格式无效，请继续回复原提示消息并发送 4～8 位纯数字。",
                    },
                )

        self._post(
            "sendMessage",
            json={"chat_id": self.chat_id, "text": "本次国家电网短信验证码等待已超时，登录已安全取消。"},
        )
        return None

    def notify_result(self, method: str, success: bool, detail: str = "") -> bool:
        method_name = "短信验证码" if method == "phone-code" else "二维码" if method == "qrcode" else method
        status = "成功" if success else "未成功"
        text = f"国家电网{method_name}登录{status}。"
        if detail:
            text += f"\n{_safe_reason(detail)}"
        result = self._post("sendMessage", json={"chat_id": self.chat_id, "text": text})
        return bool(result)

    def _next_update_id(self) -> Optional[int]:
        if self._next_update_offset is not None:
            return self._next_update_offset
        result = self._post(
            "getUpdates",
            json={"offset": -1, "timeout": 0, "allowed_updates": ["message"]},
        )
        if result is None:
            return None
        latest = max(
            (item.get("update_id", -1) for item in result if isinstance(item.get("update_id"), int)),
            default=-1,
        )
        self._next_update_offset = latest + 1
        return self._next_update_offset

    def _post(self, method: str, *, timeout: Optional[float] = None, **kwargs):
        try:
            response = requests.post(
                f"{self.bot_url}/{method}",
                timeout=timeout or self.request_timeout,
                **kwargs,
            )
            if response.status_code == 409 and method == "getUpdates":
                logging.warning(
                    "Telegram Bot getUpdates 冲突：请关闭该 Bot 的 webhook 或其他长轮询消费者，"
                    "本次短信验证码交互已取消。"
                )
                return None
            if response.status_code != 200:
                logging.warning(f"Telegram Bot {method} 请求失败，HTTP {response.status_code}。")
                return None
            payload = response.json()
            if not payload.get("ok"):
                logging.warning(f"Telegram Bot {method} 返回失败。")
                return None
            return payload.get("result")
        except Exception as error:
            safe_error = str(error).replace(self.token, "<redacted>")
            logging.warning(
                f"Telegram Bot {method} 请求异常[{type(error).__name__}]: {redact_text(safe_error)}"
            )
            return None


def build_login_interaction() -> LoginInteraction:
    provider = os.getenv("SGCC_LOGIN_INTERACTION_PROVIDER", "auto").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return NoopLoginInteraction()

    interactions: list[LoginInteraction] = []
    telegram = TelegramLoginInteraction.from_env()
    if provider in {"auto", "telegram", "both"}:
        if telegram is not None:
            interactions.append(telegram)
        elif provider in {"telegram", "both"}:
            logging.warning("已启用 Telegram 登录交互，但 Bot Token 或 Chat ID 未完整配置。")
    if provider in {"auto", "url", "both"} and os.getenv("PUSH_QRCODE_URL", "").strip():
        interactions.append(UrlLoginInteraction())

    if not interactions:
        return NoopLoginInteraction()
    if len(interactions) == 1:
        return interactions[0]
    return CompositeLoginInteraction(interactions)


def read_sms_code(interaction: LoginInteraction, reason: str) -> Optional[str]:
    code = interaction.request_sms_code(reason)
    if code:
        return code
    if sys.stdin is not None and sys.stdin.isatty():
        code = input("请输入手机验证码: ").strip()
        if _SMS_CODE_RE.fullmatch(code):
            return code
        logging.warning("输入的手机验证码格式无效。")
    return None


def _safe_call(func, *args):
    try:
        return func(*args)
    except Exception as error:
        logging.warning(f"登录交互通知失败，已隔离: {redact_text(error)}")
        return None


def _safe_reason(reason: str) -> str:
    return redact_text(reason or "登录态失效")[:160]


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))
