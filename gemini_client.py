"""Gemini API の薄いラッパー。"""

from __future__ import annotations

from typing import Iterator, List, Tuple

from google import genai
from google.genai import errors, types

DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"]

# (role, text) のリスト。role は "user" または "model"
Conversation = List[Tuple[str, str]]


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def list_text_models(client: genai.Client) -> List[str]:
    """テキスト生成に使える Gemini モデル名の一覧を返す。取得できなければ既定リスト。"""
    try:
        names = []
        for m in client.models.list():
            actions = m.supported_actions or []
            name = (m.name or "").removeprefix("models/")
            if "generateContent" in actions and name.startswith("gemini") and not any(
                x in name for x in ("embedding", "tts", "image", "audio", "live")
            ):
                names.append(name)
        return sorted(set(names), reverse=True) or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def stream_generate(
    client: genai.Client,
    model: str,
    system_prompt: str,
    conversation: Conversation,
    temperature: float,
) -> Iterator[str]:
    """会話履歴を渡して、生成テキストを少しずつ yield する。"""
    contents = [types.Content(role=role, parts=[types.Part(text=text)]) for role, text in conversation]
    config = types.GenerateContentConfig(system_instruction=system_prompt, temperature=temperature)
    for chunk in client.models.generate_content_stream(model=model, contents=contents, config=config):
        if chunk.text:
            yield chunk.text


def describe_error(e: Exception) -> str:
    """API エラーを日本語の分かりやすいメッセージにする。"""
    if isinstance(e, errors.ClientError):
        if e.code in (400, 401, 403) and "API key" in (e.message or ""):
            return "APIキーが無効です。サイドバーのAPIキーを確認してください。"
        if e.code == 429:
            return "利用上限（レート制限・無料枠）に達しました。少し待ってから再実行するか、別のモデルを選んでください。"
        if e.code == 404:
            return "指定したモデルが見つかりません。サイドバーで別のモデルを選んでください。"
        return f"リクエストエラー（{e.code}）: {e.message}"
    if isinstance(e, errors.ServerError):
        return f"Gemini 側でエラーが発生しました（{e.code}）。時間をおいて再実行してください。"
    return f"予期しないエラー: {e}"
