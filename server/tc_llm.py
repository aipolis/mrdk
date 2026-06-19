# -*- coding: utf-8 -*-
"""TradeCheck LLM 客户端 —— DeepSeek / 智谱 通用解析层"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)


def _provider() -> str:
    """返回当前配置的 LLM 提供商,优先级:DeepSeek > 智谱 > 未配置"""
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return "deepseek"
    if os.environ.get("ZHIPU_API_KEY", "").strip():
        return "zhipu"
    return ""


def _config() -> dict:
    p = _provider()
    if p == "deepseek":
        return {
            "provider": "deepseek",
            "api_key": os.environ["DEEPSEEK_API_KEY"].strip(),
            "base": os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/"),
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        }
    if p == "zhipu":
        return {
            "provider": "zhipu",
            "api_key": os.environ["ZHIPU_API_KEY"].strip(),
            "base": os.environ.get("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
            "model": os.environ.get("ZHIPU_MODEL", "glm-4-flash"),
        }
    return {"provider": "", "api_key": "", "base": "", "model": ""}


def available() -> dict:
    c = _config()
    return {"ok": bool(c["api_key"]), "provider": c["provider"], "model": c["model"]}


def chat(messages: list[dict],
         system: Optional[str] = None,
         max_tokens: int = 4096,
         temperature: float = 0.1,
         json_mode: bool = False) -> str:
    """OpenAI 兼容协议(DeepSeek 与智谱新版均支持),用 urllib 即可。

    messages 是 [{"role":"user","content":"..."}, ...] 列表;
    system 单独传入,自动加在前面;
    json_mode=True 时要求模型输出严格 JSON(由 response_format 控制)。
    """
    c = _config()
    if not c["api_key"]:
        raise RuntimeError("LLM 未配置:请在环境变量设置 DEEPSEEK_API_KEY 或 ZHIPU_API_KEY")

    payload_messages: list[dict] = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    payload = {
        "model": c["model"],
        "messages": payload_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        c["base"] + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + c["api_key"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"]["content"] or ""
    # 去掉常见的 ```csv ... ``` 包裹
    text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text.strip(), flags=re.M).strip()
    return text
