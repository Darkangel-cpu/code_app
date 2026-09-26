# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code (claude.ai/code) 向けのガイドです。

## 概要

個人用のAIライティングツール（ブログ記事作成、メール返信、要約、校正、翻訳など）。Python + Streamlit + Gemini API（`google-genai` SDK）で構築している。データベースと認証は意図的に持たない。UIの文言とプロンプトは日本語。

## コマンド

```bash
source .venv/bin/activate                  # venv は作成済み（Python 3.12）
pip install -r requirements.txt
streamlit run app.py                       # http://localhost:8501
streamlit run app.py --server.headless true   # 非対話で起動する場合（Streamlit の初回起動時のメール入力プロンプトを回避する。回避しないとプロセスが止まる／終了する）
```

APIキーの探索順: 環境変数 `GEMINI_API_KEY` / `GOOGLE_API_KEY` → `.streamlit/secrets.toml`（`GEMINI_API_KEY`）→ サイドバーの入力欄。

リポジトリにテストスイートやリンターはない。変更の確認には `streamlit.testing.v1.AppTest` を使い、`AppTest.from_file("app.py")` の前に `gemini_client.stream_generate`、`gemini_client.list_text_models`、`gemini_client.make_client` をモンキーパッチして実APIを呼ばないようにする（`history.HISTORY_FILE` も一時パスに向ける）。開発環境にAPIキーがない場合、実際のAPIでの動作確認はユーザーに依頼し、報告では「モックでのみ確認済み」と明記する。

## 方針

- 個人用ツール。データベース・ログイン・ユーザー管理は追加しない。保存が必要なものはローカルファイル（`data/` 配下）に置く。
- 技術スタックは Python + Streamlit + Gemini API で固定。別のAIプロバイダ（OpenAI、Claude など）や別のフレームワーク（Flask、React など）に置き換えない。
- UIの文言・プロンプト・エラーメッセージはすべて日本語で書く。
- ライティングに役立つツールや機能は、確認なしで追加してよい。

## 実装ルール

- Python 3.12（venv）。3.9 はサポート終了済みで、依存パッケージのセキュリティ修正が入らないため使わない。既存の各ファイルは `from __future__ import annotations` と `typing.List/Dict/Optional` で書かれているので、コードはその書き方に合わせる。
- Gemini SDK は `gemini_client.py` からだけ呼ぶ。`app.py` から `google.genai` を直接使わない。
- プロンプトは `tools.py` にまとめる。`app.py` にプロンプトを書かない。
- モデル名をコードに固定しない。モデルはサイドバーで選ぶもので、`DEFAULT_MODELS` はモデル一覧を取得できなかったときの予備。
- Streamlit では、ウィジェットを描画した後にそのキーの `st.session_state` を書き換えるとエラーになる。ページ切り替え・フォームの事前入力・入力欄のクリアは `on_click` コールバックの中で行う（`queue_refine`、`restore_from_history` と同じやり方）。
- 依存パッケージを追加したら `requirements.txt` にも追記する。
- 機能を追加・変更したら `README.md` のツール一覧・機能説明も更新する。

## アーキテクチャ

- `tools.py` — ツールの登録簿。各 `Tool` は、フォーム項目 `fields`（`text`/`textarea`/`select`）、`system` プロンプト、フォームの値をユーザープロンプトに変換する `build(values) -> str`、任意のツール別 `temperature` を持つ。`COMMON_RULES` は `Tool.system_prompt()` ですべてのシステムプロンプトの末尾に付く。**ツールの追加は `TOOLS` に `Tool` を1つ足すだけ**で、サイドバー・フォーム・履歴に自動で反映される。ツールの `id` は履歴に保存されるため、変更しないこと。
- `gemini_client.py` — Gemini SDK の利用はすべてここに集約。会話は `List[Tuple[role, text]]`（role は `"user"`/`"model"`）で、`stream_generate` がそれを `types.Content` に変換してテキストの断片を yield する。`describe_error` は `google.genai.errors` を日本語メッセージに変換する。
- `app.py` — Streamlit のUI。主なセッションステートの規約:
  - `page`（サイドバーのラジオのキー）が `Tool.label` でツールを選ぶ（または履歴ページ）。
  - `convo_{tool.id}` にツールごとの会話を保持する。最後の `"model"` が表示中の出力で、それ以前のものは過去のバージョンとして表示される。
  - `in_{tool.id}_{field}` はフォームのウィジェットキー（履歴から復元するときなど、ここに値を入れるとフォームに事前入力される）。
  - 修正（「もっと短く」などのボタン／自由入力の指示）は `on_click` コールバックで `pending_refine = (tool_id, instruction)` を保存し、次の再実行でそれをユーザーターンとして追加し、会話全体で再生成する。
  - `generate()` は `st.write_stream` でストリーミング表示し、履歴に保存してから `st.rerun()` を呼び、出力欄をステートから描画し直す。
- `history.py` — `data/history.json` に JSON で保存（新しい順、最大200件）。`data/` は gitignore 済み。
