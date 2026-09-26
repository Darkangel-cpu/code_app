"""AIライティングツール（Streamlit + Gemini API）

起動: streamlit run app.py
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import streamlit as st

import history
from gemini_client import Conversation, describe_error, list_text_models, make_client, stream_generate
from tools import TOOLS, TOOLS_BY_ID, Tool

HISTORY_PAGE = "🕘 履歴"
DEFAULT_TEMPERATURE = 0.7
QUICK_REFINES = ["もっと短く", "もっと詳しく", "もっと丁寧に", "もっとカジュアルに", "別の案を出して"]

st.set_page_config(page_title="AIライティングツール", page_icon="✍️", layout="wide")


# ---------------------------------------------------------------------------
# 設定・クライアント
# ---------------------------------------------------------------------------

def secret_api_key() -> str:
    """環境変数 → .streamlit/secrets.toml の順に API キーを探す。"""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:  # secrets.toml が無い場合
        return ""


@st.cache_resource(show_spinner=False)
def get_client(api_key: str):
    return make_client(api_key)


@st.cache_data(ttl=3600, show_spinner=False)
def get_models(api_key: str) -> List[str]:
    return list_text_models(get_client(api_key))


def convo_key(tool: Tool) -> str:
    return f"convo_{tool.id}"


def input_key(tool: Tool, field_key: str) -> str:
    return f"in_{tool.id}_{field_key}"


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------

def render_sidebar() -> Dict:
    with st.sidebar:
        st.title("✍️ AIライティング")
        page = st.radio("ツール", [t.label for t in TOOLS] + [HISTORY_PAGE], key="page", label_visibility="collapsed")

        st.divider()
        st.subheader("⚙️ 設定")
        api_key = secret_api_key()
        if api_key:
            st.caption("🔑 APIキー: 設定済み")
        else:
            api_key = st.text_input(
                "Gemini APIキー", type="password", key="api_key_input",
                help="https://aistudio.google.com/apikey で取得できます。環境変数 GEMINI_API_KEY に設定すると入力不要になります。",
            )

        models = get_models(api_key) if api_key else []
        model = st.selectbox("モデル", models or ["gemini-2.5-flash"], disabled=not api_key)

        use_tool_temp = st.checkbox("ツールごとの推奨の創造性を使う", value=True)
        temperature = None
        if not use_tool_temp:
            temperature = st.slider("創造性（temperature）", 0.0, 2.0, DEFAULT_TEMPERATURE, 0.1,
                                    help="低いほど正確で安定、高いほど多様で独創的になります。")

    return {"page": page, "api_key": api_key, "model": model, "temperature": temperature}


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

def generate(tool: Tool, conversation: Conversation, settings: Dict, inputs: Dict[str, str]) -> None:
    """会話を Gemini に送ってストリーミング表示し、結果を保存して再描画する。"""
    temperature = settings["temperature"]
    if temperature is None:
        temperature = tool.temperature if tool.temperature is not None else DEFAULT_TEMPERATURE

    client = get_client(settings["api_key"])
    try:
        with st.spinner("生成中..."):
            text = st.write_stream(
                stream_generate(client, settings["model"], tool.system_prompt(), conversation, temperature)
            )
    except Exception as e:
        st.error(describe_error(e))
        return

    if not text:
        st.warning("出力が空でした。入力内容を変えるか、もう一度お試しください。")
        return

    conversation = conversation + [("model", text)]
    st.session_state[convo_key(tool)] = conversation
    st.session_state[f"inputs_{tool.id}"] = inputs
    history.add(tool.id, inputs, text, settings["model"])
    st.rerun()


def queue_refine(tool: Tool, instruction: str) -> None:
    """修正指示を受け付け、次の再実行で生成させる（ボタンの on_click から呼ばれる）。"""
    instruction = instruction.strip()
    if instruction:
        st.session_state["pending_refine"] = (tool.id, instruction)


def queue_refine_from_input(tool: Tool) -> None:
    key = f"refine_text_{tool.id}"
    queue_refine(tool, st.session_state.get(key, ""))
    st.session_state[key] = ""


def clear_output(tool: Tool) -> None:
    st.session_state.pop(convo_key(tool), None)


# ---------------------------------------------------------------------------
# 画面: ツール
# ---------------------------------------------------------------------------

def render_field(tool: Tool, f) -> str:
    label = f"{f.label} *" if f.required else f.label
    key = input_key(tool, f.key)
    if f.kind == "textarea":
        return st.text_area(label, key=key, placeholder=f.placeholder, height=f.height)
    if f.kind == "select":
        return st.selectbox(label, f.options, key=key)
    return st.text_input(label, key=key, placeholder=f.placeholder)


def render_output(tool: Tool) -> None:
    conversation: Optional[Conversation] = st.session_state.get(convo_key(tool))
    if not conversation:
        st.info("左のフォームに入力して「生成する」を押すと、ここに結果が表示されます。")
        return

    outputs = [text for role, text in conversation if role == "model"]
    latest = outputs[-1]

    preview, raw = st.tabs(["プレビュー", "テキスト（コピー用）"])
    with preview:
        st.markdown(latest)
    with raw:
        st.code(latest, language=None, wrap_lines=True)

    c1, c2, c3 = st.columns([2, 2, 1])
    c1.caption(f"{len(latest):,} 文字 ・ バージョン {len(outputs)}")
    c2.download_button("⬇️ ダウンロード (.md)", latest, file_name=f"{tool.id}.md", mime="text/markdown",
                       use_container_width=True)
    c3.button("🗑️ クリア", on_click=clear_output, args=(tool,), use_container_width=True)

    st.markdown("##### 🔧 この結果を修正する")
    cols = st.columns(len(QUICK_REFINES))
    for col, label in zip(cols, QUICK_REFINES):
        col.button(label, key=f"quick_{tool.id}_{label}", on_click=queue_refine, args=(tool, label),
                   use_container_width=True)
    st.text_area("追加の指示", key=f"refine_text_{tool.id}", height=80,
                 placeholder="例: 2段落目をもっと具体的に / 結論を最初に / 絵文字を入れて")
    st.button("↻ 指示どおりに修正", on_click=queue_refine_from_input, args=(tool,), type="primary")

    if len(outputs) > 1:
        with st.expander(f"これまでのバージョン（{len(outputs) - 1}件）"):
            requests = [text for role, text in conversation if role == "user"][1:]
            for i, text in enumerate(outputs[:-1], start=1):
                st.markdown(f"**バージョン {i}**" + (f" → 指示:「{requests[i - 1]}」" if i - 1 < len(requests) else ""))
                st.code(text, language=None, wrap_lines=True)


def render_tool_page(tool: Tool, settings: Dict) -> None:
    st.title(tool.label)
    st.caption(tool.description)

    left, right = st.columns([1, 1], gap="large")

    with left:
        with st.form(f"form_{tool.id}"):
            values = {f.key: render_field(tool, f) for f in tool.fields}
            submitted = st.form_submit_button("✨ 生成する", type="primary", use_container_width=True)

    with right:
        st.subheader("出力")
        if not settings["api_key"]:
            st.warning("サイドバーで Gemini APIキーを設定してください。")
            return

        pending = st.session_state.pop("pending_refine", None)
        if submitted:
            missing = [f.label for f in tool.fields if f.required and not (values[f.key] or "").strip()]
            if missing:
                st.warning("必須項目を入力してください: " + "、".join(missing))
            else:
                generate(tool, [("user", tool.build(values))], settings, values)
        elif pending and pending[0] == tool.id and st.session_state.get(convo_key(tool)):
            conversation = st.session_state[convo_key(tool)] + [("user", pending[1])]
            generate(tool, conversation, settings, st.session_state.get(f"inputs_{tool.id}", {}))

        render_output(tool)


# ---------------------------------------------------------------------------
# 画面: 履歴
# ---------------------------------------------------------------------------

def restore_from_history(item: Dict) -> None:
    """履歴の入力と出力をツール画面に戻す。"""
    tool = TOOLS_BY_ID[item["tool_id"]]
    for f in tool.fields:
        value = item["inputs"].get(f.key)
        if value is not None and (f.kind != "select" or value in f.options):
            st.session_state[input_key(tool, f.key)] = value
    st.session_state[convo_key(tool)] = [("user", tool.build(item["inputs"])), ("model", item["output"])]
    st.session_state[f"inputs_{tool.id}"] = item["inputs"]
    st.session_state["page"] = tool.label


def render_history_page() -> None:
    
    items = [i for i in history.load() if i["tool_id"] in TOOLS_BY_ID]
    if not items:
        st.info("まだ履歴はありません。")
        return

    tool_filter = st.multiselect("ツールで絞り込み", [t.label for t in TOOLS])
    keyword = st.text_input("キーワード検索", placeholder="出力や入力に含まれる語句")

    for item in items:
        tool = TOOLS_BY_ID[item["tool_id"]]
        if tool_filter and tool.label not in tool_filter:
            continue
        if keyword and keyword not in item["output"] and not any(keyword in str(v) for v in item["inputs"].values()):
            continue

        first_input = next((str(v) for v in item["inputs"].values() if str(v).strip()), "")
        title = f"{item['created_at']} ・ {tool.label} ・ {first_input[:40].replace(chr(10), ' ')}"
        with st.expander(title):
            st.code(item["output"], language=None, wrap_lines=True)
            c1, c2, _ = st.columns([1, 1, 3])
            c1.button("↩️ ツールで開く", key=f"open_{item['id']}", on_click=restore_from_history, args=(item,))
            c2.button("🗑️ 削除", key=f"del_{item['id']}", on_click=history.delete, args=(item["id"],))
            st.caption(f"モデル: {item.get('model', '-')}")

    st.divider()
    if st.button("すべての履歴を削除"):
        history.clear()
        st.rerun()


# ---------------------------------------------------------------------------

def main() -> None:
    settings = render_sidebar()
    if settings["page"] == HISTORY_PAGE:
        render_history_page()
        return
    tool = next(t for t in TOOLS if t.label == settings["page"])
    render_tool_page(tool, settings)


main()
