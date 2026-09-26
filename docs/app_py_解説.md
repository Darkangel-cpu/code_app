# app.py を読み解く：AIライティングツールの仕組み

## はじめに

この記事では、今回作ったAIライティングツールの画面を担当するファイル `app.py` を順番に解説します。約250行のコードですが、**Streamlit の「ひとつのクセ」**さえ押さえれば、ぐっと読みやすくなります。

---

## 1. 全体像：だれが何をしているか

アプリは4つのファイルに分かれていて、`app.py` は**画面と流れ**だけを担当します。

| ファイル | 役割 | たとえると |
|---|---|---|
| `app.py` | 画面を描き、クリックに応える | 受付 |
| `tools.py` | 各ツールのプロンプトと入力項目 | レシピ本 |
| `gemini_client.py` | Gemini API とのやりとり | 厨房への電話 |
| `history.py` | 履歴を JSON ファイルに保存 | ノート |

そのため、`app.py` の冒頭ではほかの3つを読み込んでいます。

```python
import history
from gemini_client import Conversation, describe_error, ...
from tools import TOOLS, TOOLS_BY_ID, Tool
```

---

## 2. 最重要ポイント：Streamlit はクリックのたびにスクリプト全体をやり直す

この記事でいちばん大事なところです。

Streamlit のアプリは、ユーザーが何か操作するたびに（ボタンを押す、メニューを選ぶなど）**スクリプトを上から下まで丸ごと実行し直します**。画面は毎回イチから描き直されます。

すると困ったことが起きます。**ふつうの変数は実行のたびに消えてしまう**のです。生成した文章を変数に入れておいても、次にクリックしたときにはなくなっています。

そこで使うのが `st.session_state` です。これは**実行をまたいで中身が残る箱**です。このアプリでは次のものを入れています。

| キー | 中身 |
|---|---|
| `page` | いま選んでいるツール |
| `convo_blog` など | ツールごとの会話（プロンプトとAIの返答） |
| `in_blog_topic` など | 入力欄の値 |
| `pending_refine` | 実行待ちの修正依頼 |

「毎回やり直す」と「残る箱」の2つを頭に入れておけば、この先のコードは自然に読めます。

---

## 3. 設定とAPIクライアント

### APIキーを探す

```python
def secret_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""
```

まず環境変数を見て、次に `.streamlit/secrets.toml` を見ます。どちらにもキーがなければ空文字を返し、その場合はサイドバーにAPIキーの入力欄が表示されます。

### キャッシュ：時間のかかる処理を繰り返さない

```python
@st.cache_resource(show_spinner=False)
def get_client(api_key: str):
    return make_client(api_key)

@st.cache_data(ttl=3600, show_spinner=False)
def get_models(api_key: str) -> List[str]:
    return list_text_models(get_client(api_key))
```

クリックのたびにスクリプトがやり直されるので、APIクライアントの作成やモデル一覧の取得を毎回していたら無駄です。`@st.cache_...` デコレーターは「最初の結果を覚えておいて、次からはそれを使い回す」という指示です。

- `cache_resource`：接続のように使い回す**オブジェクト**向け
- `cache_data`：一覧のような**データ**向け。`ttl=3600` は「1時間たったら取り直す」という意味

---

## 4. サイドバー：設定をひとつの辞書にまとめて返す

```python
page = st.radio("ツール", [t.label for t in TOOLS] + [HISTORY_PAGE], key="page", ...)
```

ツールのメニューは、`tools.py` の `TOOLS` リストから自動で作られます。**だから `tools.py` にツールを足すだけでメニューに出てくる**のです。

`key="page"` を付けているので、選んだ項目は `st.session_state["page"]` にも保存されます。これは後で、履歴ページからツールを切り替えるときに効いてきます。

最後に、`render_sidebar()` は設定を辞書にまとめて返します。

```python
return {"page": page, "api_key": api_key, "model": model, "temperature": temperature}
```

この後の関数は `settings` を受け取るだけで済みます。設定を1か所にまとめておくと、コードがすっきりします。

---

## 5. 「生成する」を押すと何が起きるか

### 入力フォーム

```python
with st.form(f"form_{tool.id}"):
    values = {f.key: render_field(tool, f) for f in tool.fields}
    submitted = st.form_submit_button("✨ 生成する", ...)
```

ふつう Streamlit は、**1文字入力するたびに**スクリプトをやり直します。入力欄を `st.form` で囲むと、**ボタンを押すまで何も送信されない**ので、長いメールを打っている途中で画面が何度も再読み込みされることがありません。

`render_field` は、`tools.py` の定義に合わせて入力欄を描き分けます。`textarea` なら複数行の欄、`select` ならプルダウン、それ以外は1行の欄です。

### 生成する：generate() 関数

ここがアプリの心臓部です。

```python
def generate(tool, conversation, settings, inputs):
    # ① temperature を決める（手動設定がオンならその値、なければツールの推奨値）
    ...
    try:
        with st.spinner("生成中..."):
            text = st.write_stream(stream_generate(...))   # ② 届いた文字から順に表示
    except Exception as e:
        st.error(describe_error(e))                        # ③ エラーは日本語で表示
        return

    conversation = conversation + [("model", text)]
    st.session_state[convo_key(tool)] = conversation       # ④ 箱に保存
    history.add(tool.id, inputs, text, settings["model"])  # ⑤ 履歴に記録
    st.rerun()                                              # ⑥ 画面を描き直す
```

ポイントをいくつか補足します。

- **② `st.write_stream`**：Gemini から届いた文字を順に表示します。出力が ChatGPT のように少しずつ現れるのはこのためです。終わると全文を返します。
- **会話の形式**：`[("user", "プロンプト"), ("model", "返答")]` のような組のリストです。リストで持っておくことで、次に説明する修正機能が実現できます。
- **⑥ `st.rerun()`**：保存が終わったら、スクリプトを上からもう一度実行します。次の実行では `session_state` から出力を読み出して、きれいに表示します。

---

## 6. 修正機能：なぜコールバックを経由するのか

結果は「もっと短く」などのボタンや、自由な指示で修正できます。ここは少しトリッキーです。

```python
col.button(label, on_click=queue_refine, args=(tool, label))
```

`on_click` には、**ボタンが押されたらすぐ、スクリプトの再実行より前に呼ばれる関数**を指定します。これをコールバックと呼びます。

```python
def queue_refine(tool, instruction):
    st.session_state["pending_refine"] = (tool.id, instruction)
```

コールバックは自分では何も生成しません。「修正依頼があるよ」という**メモを残すだけ**です。そして再実行のときに、

```python
pending = st.session_state.pop("pending_refine", None)   # メモを受け取る（そして消す）
...
elif pending and pending[0] == tool.id and ...:
    conversation = st.session_state[convo_key(tool)] + [("user", pending[1])]
    generate(tool, conversation, settings, ...)
```

メモを受け取り、**これまでの会話の末尾に「もっと短く」を付け足して** Gemini に送ります。AIは前の会話を見ているので、何を短くすればいいのか分かるわけです。

**なぜこんな回り道をするのでしょうか。** Streamlit には「**ウィジェットを描いた後に、そのウィジェットの値は変更できない**」というルールがあります。たとえば、ボタンを押した後に指示の入力欄を空にする処理を通常の流れで書くと、エラーになります。コールバックの中なら何も描かれる前に変更されるので安全です。

```python
def queue_refine_from_input(tool):
    key = f"refine_text_{tool.id}"
    queue_refine(tool, st.session_state.get(key, ""))
    st.session_state[key] = ""   # 指示の入力欄を空にする（コールバック内なのでOK）
```

---

## 7. 出力の表示

```python
outputs = [text for role, text in conversation if role == "model"]
latest = outputs[-1]
```

会話からAIの返答だけを取り出し、**最新のもの**を表示します。

- **「プレビュー」タブ**：`st.markdown` で見出しや箇条書きを整形して表示します。
- **「テキスト（コピー用）」タブ**：`st.code` でプレーンテキストを表示します。右上にコピーボタンが付きます。
- **これまでのバージョン**：修正すると、以前の結果が折りたたみ欄に並びます。コードは古いバージョンと、その後に出した指示を組にして「バージョン1 → 指示：もっと短く」のように表示します。

---

## 8. 履歴ページ

`history.load()` で保存済みの項目を読み込み、ツールやキーワードで絞り込んで一覧表示します。

おもしろいのは「ツールで開く」ボタンです。

```python
def restore_from_history(item):
    tool = TOOLS_BY_ID[item["tool_id"]]
    for f in tool.fields:
        ...
        st.session_state[input_key(tool, f.key)] = value   # 以前の入力をフォームに戻す
    st.session_state[convo_key(tool)] = [...]              # 出力を戻す
    st.session_state["page"] = tool.label                  # サイドバーの選択を切り替える
```

以前の入力・出力・ページの選択を `session_state` に直接書き込みます。再実行されると、そのツールの画面がすべて復元された状態で表示されます。これもセクション6と同じ理由で、コールバックとして実行されます。

---

## 9. main()：出発点

```python
def main():
    settings = render_sidebar()
    if settings["page"] == HISTORY_PAGE:
        render_history_page()
        return
    tool = next(t for t in TOOLS if t.label == settings["page"])
    render_tool_page(tool, settings)
```

シンプルです。サイドバーを描き、選ばれているものに応じて履歴ページかツールのページを描きます。これが再実行のたびに走ります。

---

## まとめ：「生成する」を1回押したときの流れ

1. フォームに入力して **「生成する」** を押す。
2. Streamlit が**スクリプトを上から再実行**し、今回は `submitted` が `True` になる。
3. `tool.build()` が入力をプロンプトに変え、`generate()` が Gemini に送る。
4. `st.write_stream` が届いた返答を順に表示する。
5. 結果を **`session_state`** と**履歴**に保存する。
6. `st.rerun()` で画面を描き直し、`session_state` から結果を読み出して表示する。
7. 「もっと短く」を押すと、**コールバックがメモを残し**、次の実行で会話を続ける形で結果を修正する。

ファイル全体を支えているのは次の3つの考え方です。

- **Streamlit はクリックのたびにスクリプトをやり直す**
- **残しておきたいものは `st.session_state` に入れる**
- **ウィジェットの値はコールバックの中で変更する**

これさえ分かれば、`app.py` 全体を追えるはずです。次のステップとして、`tools.py` に自分でツールを1つ追加して、アプリにどう現れるか試してみるのがおすすめです。
