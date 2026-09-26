"""ライティングツールの定義。

各ツールは「入力フォームの項目」「システムプロンプト」「ユーザープロンプトの組み立て方」を持つ。
新しいツールを追加するときは TOOLS に Tool を1つ足すだけでよい。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

COMMON_RULES = """
# 共通ルール
- 出力は日本語（翻訳ツールで別言語を指定された場合を除く）。
- 前置き（「承知しました」「以下が〜です」など）や締めの挨拶は書かず、成果物だけを出力する。
- 見出し・箇条書きが役立つ場合は Markdown を使う。
- 事実が不明な箇所は捏造せず、[要確認: 〜] のように明示する。
""".strip()


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # "text" | "textarea" | "select"
    options: List[str] = field(default_factory=list)
    placeholder: str = ""
    required: bool = False
    height: int = 200


@dataclass
class Tool:
    id: str
    name: str
    icon: str
    description: str
    system: str
    fields: List[Field]
    build: Callable[[Dict[str, str]], str]
    temperature: Optional[float] = None  # None のときはサイドバーの設定値を使う

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}"

    def system_prompt(self) -> str:
        return f"{self.system.strip()}\n\n{COMMON_RULES}"


def _opt(v: Dict[str, str], key: str, label: str) -> str:
    """値が入力されていれば「label: 値」の行を返す。"""
    value = (v.get(key) or "").strip()
    return f"{label}: {value}\n" if value else ""


# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------

TOOLS: List[Tool] = [
    Tool(
        id="blog",
        name="ブログ記事作成",
        icon="✍️",
        description="テーマとキーワードから、構成の整ったブログ記事を書きます。",
        system="""
あなたは経験豊富なWebライター兼編集者です。読者の検索意図を満たし、最後まで読まれるブログ記事を書きます。
- 冒頭で読者の悩みや関心に共感し、記事を読むメリットを示す。
- H2/H3 の見出しで論理的に構成し、具体例・手順・数字を盛り込む。
- 指定キーワードは自然な形で本文や見出しに含める（詰め込みすぎない）。
- 最後に「まとめ」を置く。
- 1行目に `# 記事タイトル` を書く。
""",
        fields=[
            Field("topic", "テーマ・タイトル案", placeholder="例: 在宅勤務で集中力を保つコツ", required=True),
            Field("audience", "想定読者", placeholder="例: リモートワークを始めたばかりの会社員"),
            Field("keywords", "含めたいキーワード（カンマ区切り）", placeholder="例: 在宅勤務, 集中力, ポモドーロ"),
            Field("length", "文字数の目安", "select", ["約1,000字", "約2,000字", "約3,000字", "約5,000字"]),
            Field("style", "文体", "select", ["です・ます調（親しみやすい）", "です・ます調（専門的）", "だ・である調", "カジュアル・会話調"]),
            Field("notes", "盛り込みたい内容・メモ（任意）", "textarea", placeholder="自分の体験談、伝えたいポイントなど", height=150),
        ],
        build=lambda v: (
            f"次の条件でブログ記事を書いてください。\n\n"
            f"テーマ: {v['topic']}\n"
            + _opt(v, "audience", "想定読者")
            + _opt(v, "keywords", "キーワード")
            + _opt(v, "length", "文字数の目安")
            + _opt(v, "style", "文体")
            + (f"\n# 盛り込みたい内容\n{v['notes']}\n" if v.get("notes") else "")
        ),
        temperature=0.8,
    ),
    Tool(
        id="email_reply",
        name="メール返信",
        icon="📧",
        description="受け取ったメールと返信の要点から、返信文を作ります。",
        system="""
あなたはビジネスコミュニケーションの専門家です。受信メールの内容と相手との関係を踏まえ、そのまま送れる返信メールを作成します。
- 1行目に「件名: Re: 〜」を書き、続けて本文を書く。
- 相手の質問・依頼にはすべて漏れなく答える。答えが要点に含まれていない場合は [要確認: 〜] とする。
- 相手との関係とトーンに合った敬語レベルにする。
- 簡潔で読みやすく、段落の間は空行を入れる。
""",
        fields=[
            Field("received", "受信したメール", "textarea", placeholder="返信したいメールを貼り付け", required=True, height=220),
            Field("points", "返信で伝えたいこと", "textarea", placeholder="例: 日程は来週水曜で了承。資料は金曜までに送る。", height=120),
            Field("relation", "相手との関係", "select", ["社外（取引先・顧客）", "上司・目上", "同僚", "友人・知人"]),
            Field("tone", "トーン", "select", ["丁寧", "とても丁寧（謝罪・お願い）", "簡潔", "フレンドリー"]),
            Field("signature", "署名・名前（任意）", placeholder="例: 山田太郎"),
        ],
        build=lambda v: (
            f"# 受信メール\n{v['received']}\n\n"
            + (f"# 返信で伝えたいこと\n{v['points']}\n\n" if v.get("points") else "# 返信で伝えたいこと\n（特になし。内容に合わせて適切に返信）\n\n")
            + _opt(v, "relation", "相手との関係")
            + _opt(v, "tone", "トーン")
            + _opt(v, "signature", "署名")
        ),
    ),
    Tool(
        id="email_new",
        name="メール作成",
        icon="✉️",
        description="用件を伝えるだけで、新規メールを一から作ります。",
        system="""
あなたはビジネスコミュニケーションの専門家です。用件から、そのまま送れるメールを作成します。
- 1行目に「件名: 〜」を書き、続けて宛名・本文・結びを書く。
- 用件を冒頭で明確に伝え、相手に求める行動や期限をはっきり書く。
""",
        fields=[
            Field("purpose", "メールの用件", "textarea", placeholder="例: 来月の定例会議の日程調整をお願いしたい。候補は3日と10日。", required=True, height=150),
            Field("to", "宛先（相手）", placeholder="例: 取引先の佐藤様"),
            Field("relation", "相手との関係", "select", ["社外（取引先・顧客）", "上司・目上", "同僚", "友人・知人"]),
            Field("tone", "トーン", "select", ["丁寧", "とても丁寧（謝罪・お願い）", "簡潔", "フレンドリー"]),
            Field("signature", "署名・名前（任意）", placeholder="例: 山田太郎"),
        ],
        build=lambda v: (
            f"次の用件でメールを作成してください。\n\n# 用件\n{v['purpose']}\n\n"
            + _opt(v, "to", "宛先")
            + _opt(v, "relation", "相手との関係")
            + _opt(v, "tone", "トーン")
            + _opt(v, "signature", "署名")
        ),
    ),
    Tool(
        id="summarize",
        name="要約",
        icon="📝",
        description="長い文章・記事・議事録などを、指定の形式で要約します。",
        system="""
あなたは要約の専門家です。原文の主旨を正確に捉え、重要な情報を落とさずに簡潔にまとめます。
- 原文にない情報や自分の意見を加えない。
- 数字・固有名詞・結論・決定事項は優先して残す。
""",
        fields=[
            Field("text", "要約したい文章", "textarea", placeholder="ここに文章を貼り付け", required=True, height=300),
            Field("format", "形式", "select", ["3行要約", "箇条書き（要点）", "段落（文章）", "一言で（TL;DR）", "議事録形式（決定事項・TODO）"]),
            Field("length", "長さ", "select", ["標準", "短め", "詳しめ"]),
            Field("focus", "特に注目してほしい観点（任意）", placeholder="例: 費用面、リスク"),
        ],
        build=lambda v: (
            f"次の文章を「{v.get('format') or '箇条書き'}」で要約してください。長さ: {v.get('length') or '標準'}\n"
            + _opt(v, "focus", "注目する観点")
            + f"\n# 原文\n{v['text']}"
        ),
        temperature=0.3,
    ),
    Tool(
        id="proofread",
        name="校正・推敲",
        icon="🔍",
        description="誤字脱字・文法・表現をチェックし、修正版と変更点を示します。",
        system="""
あなたはプロの校正者・編集者です。文章の誤字脱字、文法の誤り、表記ゆれ、分かりにくい表現を直します。
原文の意図と文体はできる限り保ちます。

出力形式:
## 修正版
（修正後の全文）

## 主な修正点
| 修正前 | 修正後 | 理由 |
|---|---|---|
（重要なものから最大15件）

## 全体へのアドバイス
（1〜3点、簡潔に）
""",
        fields=[
            Field("text", "チェックしたい文章", "textarea", placeholder="ここに文章を貼り付け", required=True, height=300),
            Field("level", "修正の強さ", "select", ["誤字脱字・文法のみ（最小限）", "読みやすさも改善（標準）", "しっかり推敲（大幅に書き換えてOK）"]),
        ],
        build=lambda v: f"修正の強さ: {v.get('level') or '標準'}\n\n# 原文\n{v['text']}",
        temperature=0.2,
    ),
    Tool(
        id="rewrite",
        name="リライト・トーン変換",
        icon="🔄",
        description="内容はそのままに、文体やトーンを変えて書き直します。",
        system="""
あなたは文章表現の専門家です。原文の内容・情報を保ったまま、指定された文体やトーンに書き直します。
書き直した文章だけを出力します。
""",
        fields=[
            Field("text", "書き直したい文章", "textarea", placeholder="ここに文章を貼り付け", required=True, height=250),
            Field("tone", "変換先のスタイル", "select", [
                "ビジネス向けに丁寧に", "カジュアル・親しみやすく", "簡潔に短く", "小学生にも分かるように",
                "説得力を高める", "もっと詳しく膨らませる", "SNS向けにキャッチーに", "文学的・情緒的に",
            ]),
            Field("extra", "その他の要望（任意）", placeholder="例: 300字以内、「私」を「僕」に"),
        ],
        build=lambda v: (
            f"次の文章を「{v.get('tone')}」に書き直してください。\n" + _opt(v, "extra", "その他の要望") + f"\n# 原文\n{v['text']}"
        ),
    ),
    Tool(
        id="translate",
        name="翻訳",
        icon="🌐",
        description="自然な表現で他の言語に翻訳します。",
        system="""
あなたはプロの翻訳者です。直訳ではなく、翻訳先の言語のネイティブが自然に感じる表現で翻訳します。
専門用語や固有名詞は正確に扱い、原文の意味とニュアンスを保ちます。
翻訳文のみを出力します（「翻訳のポイント」を求められた場合のみ末尾に追記）。
""",
        fields=[
            Field("text", "翻訳したい文章", "textarea", placeholder="ここに文章を貼り付け", required=True, height=250),
            Field("target", "翻訳先の言語", "select", ["英語", "日本語", "中国語（簡体字）", "中国語（繁体字）", "韓国語", "スペイン語", "フランス語", "ドイツ語"]),
            Field("style", "スタイル", "select", ["自然・標準", "ビジネス・フォーマル", "カジュアル", "技術文書"]),
            Field("explain", "翻訳のポイントも説明する", "select", ["いいえ", "はい"]),
        ],
        build=lambda v: (
            f"次の文章を{v.get('target')}に翻訳してください。スタイル: {v.get('style')}\n"
            + ("翻訳文の後に「## 翻訳のポイント」として、訳し方の工夫や注意点を日本語で簡潔に説明してください。\n" if v.get("explain") == "はい" else "")
            + f"\n# 原文\n{v['text']}"
        ),
        temperature=0.3,
    ),
    Tool(
        id="sns",
        name="SNS投稿作成",
        icon="📱",
        description="各SNSの特徴に合わせた投稿文を複数案作ります。",
        system="""
あなたはSNSマーケティングの専門家です。プラットフォームの特性（文字数、文化、ハッシュタグの使い方）に合わせ、
反応が得られやすい投稿文を作ります。各案は切り口を変え、「### 案1」のように見出しを付けて出力します。
X（旧Twitter）は1投稿140字以内（全角換算）を守ります。
""",
        fields=[
            Field("topic", "投稿の内容・伝えたいこと", "textarea", placeholder="例: ブログで在宅勤務のコツ記事を公開した", required=True, height=150),
            Field("platform", "プラットフォーム", "select", ["X（旧Twitter）", "Instagram", "Threads", "LinkedIn", "Facebook", "note（紹介文）"]),
            Field("count", "案の数", "select", ["3", "5", "1"]),
            Field("tone", "トーン", "select", ["親しみやすい", "専門的・信頼感", "ユーモア", "エモーショナル"]),
            Field("hashtags", "ハッシュタグ", "select", ["付ける", "付けない"]),
        ],
        build=lambda v: (
            f"{v.get('platform')}向けの投稿文を{v.get('count')}案作成してください。\n"
            f"トーン: {v.get('tone')}\nハッシュタグ: {v.get('hashtags')}\n\n# 内容\n{v['topic']}"
        ),
        temperature=0.9,
    ),
    Tool(
        id="titles",
        name="タイトル・見出し案",
        icon="💡",
        description="記事・資料・動画などのタイトル案をたくさん出します。",
        system="""
あなたは編集者兼コピーライターです。思わずクリックしたくなる、かつ内容を正確に表すタイトルを考えます。
数字・ベネフィット・疑問形・意外性など、さまざまな型を使い分けます。
番号付きリストで出力し、各案の後に（型: 〜）と使った型を短く添えます。最後に「おすすめ」を1つ理由付きで挙げます。
""",
        fields=[
            Field("content", "内容・本文・概要", "textarea", placeholder="記事の概要や本文を貼り付け", required=True, height=200),
            Field("kind", "用途", "select", ["ブログ記事", "YouTube動画", "プレゼン資料", "メールの件名", "キャッチコピー", "書籍・電子書籍"]),
            Field("count", "案の数", "select", ["10", "5", "20"]),
        ],
        build=lambda v: f"{v.get('kind')}のタイトル案を{v.get('count')}個考えてください。\n\n# 内容\n{v['content']}",
        temperature=1.0,
    ),
    Tool(
        id="expand",
        name="メモ→文章化",
        icon="📄",
        description="箇条書きや走り書きのメモを、読みやすい文章に仕上げます。",
        system="""
あなたは優秀なライターです。断片的なメモや箇条書きから、論理的で読みやすい文章を書き起こします。
メモにない事実は付け加えず、つなぎの表現や論理の流れを補うことで文章にします。
""",
        fields=[
            Field("memo", "メモ・箇条書き", "textarea", placeholder="・今期の売上は前年比120%\n・新規顧客が増えた\n・課題は人手不足", required=True, height=250),
            Field("kind", "仕上げる文章の種類", "select", ["報告書・レポート", "日報・週報", "エッセイ・コラム", "スピーチ原稿", "自己紹介・プロフィール", "企画書の説明文"]),
            Field("style", "文体", "select", ["です・ます調", "だ・である調"]),
        ],
        build=lambda v: f"次のメモを「{v.get('kind')}」として、{v.get('style')}の文章にしてください。\n\n# メモ\n{v['memo']}",
    ),
    Tool(
        id="free",
        name="自由指示",
        icon="💬",
        description="上のどれにも当てはまらない文章作成を、自由な指示で行います。",
        system="""
あなたは万能なライティングアシスタントです。ユーザーの指示を正確に理解し、目的に合った質の高い文章を作成します。
""",
        fields=[
            Field("instruction", "指示", "textarea", placeholder="例: 退職する同僚への寄せ書きメッセージを3パターン", required=True, height=150),
            Field("material", "参考資料・素材（任意）", "textarea", placeholder="必要なら元になる文章などを貼り付け", height=200),
        ],
        build=lambda v: v["instruction"] + (f"\n\n# 参考資料\n{v['material']}" if v.get("material") else ""),
    ),
]

TOOLS_BY_ID: Dict[str, Tool] = {t.id: t for t in TOOLS}
