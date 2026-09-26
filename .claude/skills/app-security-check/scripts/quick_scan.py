#!/usr/bin/env python3
"""Streamlit + LLM API アプリ向けの機械的なセキュリティスキャン。

使い方: python quick_scan.py [プロジェクトのルート]

見つけたものを Markdown で標準出力に出す。ここに出るのは「要確認の候補」であり、
誤検知も見逃しも含む。最終判断は SKILL.md の手順に従って人（Claude）が行う。
標準ライブラリのみ・Python 3.9 対応。
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SKIP_DIRS = {
    ".venv", "venv", "env", "node_modules", ".git", "__pycache__", ".agents", ".claude",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", "dist", "build",
}
TEXT_SUFFIXES = {
    ".py", ".ipynb", ".toml", ".json", ".md", ".txt", ".env", ".cfg", ".ini",
    ".yaml", ".yml", ".sh", ".js", ".ts", ".html", "",
}
MAX_FILE_BYTES = 2_000_000

SECRET_PATTERNS = [
    ("Google API キー", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Anthropic API キー", re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}")),
    ("OpenAI API キー", re.compile(r"sk-(?:proj-|svcacct-|admin-)?[0-9A-Za-z_\-]{20,}")),
    ("AWS アクセスキー", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("Hugging Face トークン", re.compile(r"hf_[0-9A-Za-z]{30,}")),
    ("Groq API キー", re.compile(r"gsk_[0-9A-Za-z]{40,}")),
    ("xAI API キー", re.compile(r"xai-[0-9A-Za-z]{40,}")),
    ("GitHub トークン", re.compile(r"gh[pousr]_[0-9A-Za-z]{36,}|github_pat_[0-9A-Za-z_]{50,}")),
    ("Slack トークン", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("キー・パスワードの直書きらしき代入", re.compile(
        r"""(?i)(api[_-]?key|secret|token|password|passwd|cookie_secret)\s*[=:]\s*["'][^"'\s]{12,}["']""")),
]
# 秘密情報を置くことが想定された場所（gitignore されていれば正常）
EXPECTED_SECRET_FILES = {".streamlit/secrets.toml", ".env", ".env.local"}

LLM_SDKS = [
    ("Google Gemini (google-genai)", re.compile(r"^\s*(from|import)\s+google\.genai\b|^\s*from\s+google\s+import\s+genai\b")),
    ("Google Gemini (旧 google-generativeai)", re.compile(r"^\s*(from|import)\s+google\.generativeai\b")),
    ("Vertex AI", re.compile(r"^\s*(from|import)\s+vertexai\b")),
    ("OpenAI / Azure OpenAI", re.compile(r"^\s*(from|import)\s+openai\b")),
    ("Anthropic", re.compile(r"^\s*(from|import)\s+anthropic\b")),
    ("AWS (boto3 / Bedrock)", re.compile(r"^\s*(from|import)\s+boto3\b")),
    ("LangChain", re.compile(r"^\s*(from|import)\s+langchain\w*")),
    ("LangGraph", re.compile(r"^\s*(from|import)\s+langgraph\b")),
    ("LlamaIndex", re.compile(r"^\s*(from|import)\s+llama_index\b")),
    ("LiteLLM", re.compile(r"^\s*(from|import)\s+litellm\b")),
    ("Ollama", re.compile(r"^\s*(from|import)\s+ollama\b")),
    ("Mistral", re.compile(r"^\s*(from|import)\s+mistralai\b")),
    ("Cohere", re.compile(r"^\s*(from|import)\s+cohere\b")),
    ("Groq", re.compile(r"^\s*(from|import)\s+groq\b")),
    ("Hugging Face", re.compile(r"^\s*(from|import)\s+(huggingface_hub|transformers)\b")),
    ("MCP", re.compile(r"^\s*(from|import)\s+mcp\b")),
]

RISKY_CODE = [
    ("unsafe_allow_html=True（HTMLをそのまま描画）", re.compile(r"unsafe_allow_html\s*=\s*True")),
    ("st.html（HTMLをそのまま描画）", re.compile(r"\bst\.html\(")),
    ("components.html / iframe", re.compile(r"components\.(v1\.)?(html|iframe)\(")),
    ("eval / exec", re.compile(r"(?<![\w.])(eval|exec)\(")),
    ("シェル実行", re.compile(r"os\.system\(|os\.popen\(|shell\s*=\s*True|subprocess\.")),
    ("pickle / joblib の読み込み", re.compile(r"pickle\.loads?\(|joblib\.load\(")),
    ("yaml.load（safe_load でない）", re.compile(r"yaml\.load\(")),
    ("SSL 検証の無効化", re.compile(r"verify\s*=\s*False")),
    ("LangChain の危険フラグ", re.compile(r"allow_dangerous_(code|requests|deserialization)\s*=\s*True")),
    ("コード実行ツール（PythonREPL 等）", re.compile(r"PythonREPL|PythonAstREPLTool|create_pandas_dataframe_agent|create_csv_agent")),
    ("LLM 生成 SQL の実行", re.compile(r"SQLDatabaseChain|create_sql_agent|SQLDatabaseToolkit")),
    ("pandas の query/eval", re.compile(r"\.(query|eval)\(\s*[a-zA-Z_]")),
]

# 危険とは限らないが、手で確認すべき箇所
REVIEW_POINTS = [
    ("st.cache_data / st.cache_resource（全ユーザーで共有される）", re.compile(r"st\.cache_(data|resource)|st\.experimental_(memo|singleton)|@st\.cache\b")),
    ("st.file_uploader（アップロード）", re.compile(r"st\.file_uploader\(")),
    ("st.query_params（URL から入る値）", re.compile(r"st\.(experimental_get_)?query_params")),
    ("認証（st.login / st.user / streamlit_authenticator）", re.compile(r"st\.login\(|st\.user\b|st\.experimental_user|streamlit_authenticator")),
    ("st.secrets の利用", re.compile(r"st\.secrets\b")),
    ("パスワード入力欄", re.compile(r"type\s*=\s*[\"']password[\"']")),
    ("st.image（URL を渡していれば外部読み込み）", re.compile(r"st\.image\(")),
    ("サーバーからの外部 HTTP 取得（SSRF の経路になりうる）", re.compile(r"requests\.(get|post)\(|httpx\.(get|post|Client|AsyncClient)|urllib\.request\.urlopen|WebBaseLoader|aiohttp\.ClientSession")),
    ("ツール呼び出し・エージェント", re.compile(r"\btools\s*=|bind_tools\(|function_call|tool_choice|AgentExecutor|create_\w*agent\(|create_react_agent")),
    ("出力トークン上限の指定", re.compile(r"max_(output_)?tokens|max_completion_tokens")),
    ("例外メッセージの表示", re.compile(r"st\.(error|exception|warning)\([^)]*\b(e|err|exc|error)\b")),
    ("ファイルへの書き込み", re.compile(r"open\([^)]*[\"'][wa]b?\+?[\"']|\.write_text\(|\.write_bytes\(|json\.dump\(")),
]

REQUIRED_IGNORES = [".streamlit/secrets.toml", ".env", ".venv/"]
PYTHON_EOL = {(3, 7): "2023-06", (3, 8): "2024-10", (3, 9): "2025-10", (3, 10): "2026-10", (3, 11): "2027-10", (3, 12): "2028-10"}
DATA_SUFFIXES = {".json", ".jsonl", ".db", ".sqlite", ".sqlite3", ".csv", ".log", ".pkl", ".parquet"}
DATA_DIR_NAMES = {"data", "history", "logs", "uploads", "storage", "chroma", "chroma_db", "faiss_index", "vectorstore"}
DEPLOY_FILES = [
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", ".dockerignore",
    "Procfile", "fly.toml", "app.yaml", "render.yaml", "railway.json", "vercel.json", "packages.txt",
]
DEP_FILES = ["requirements.txt", "pyproject.toml", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "requirements.lock"]
EXEC_CONFIG = [".claude/settings.json", ".claude/settings.local.json", ".mcp.json", ".pre-commit-config.yaml", "skills-lock.json"]


def walk(root: Path, suffixes: Optional[set] = None) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            allowed = suffixes if suffixes is not None else TEXT_SUFFIXES
            if p.suffix in allowed or (suffixes is None and name.startswith(".env")):
                try:
                    if p.stat().st_size <= MAX_FILE_BYTES:
                        yield p
                except OSError:
                    continue


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def mask(s: str) -> str:
    return s[:6] + "…" + s[-2:] if len(s) > 10 else "…"


def run(cmd: List[str], cwd: Path, timeout: int = 180) -> Tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def section(title: str) -> None:
    print(f"\n## {title}\n")


def scan_secrets(root: Path) -> None:
    section("1. 秘密情報のパターン（作業ツリー）")
    hits = 0
    for p in walk(root):
        r = rel(p, root)
        note = "（想定された保存場所。gitignore と権限を確認）" if r in EXPECTED_SECRET_FILES else ""
        for lineno, line in enumerate(read(p).splitlines(), 1):
            seen = set()
            for label, pat in SECRET_PATTERNS:
                m = pat.search(line)
                if not m or m.group(0) in seen:
                    continue
                if label == "OpenAI API キー" and m.group(0).startswith("sk-ant-"):
                    continue
                seen.add(m.group(0))
                hits += 1
                print(f"- {label}: `{r}:{lineno}` → `{mask(m.group(0))}`{note}")
    if not hits:
        print("- 検出なし")


def scan_gitignore_and_git(root: Path) -> None:
    section("2. .gitignore と git")
    gi = read(root / ".gitignore")
    if not gi:
        print("- .gitignore が**ない**")
    for entry in REQUIRED_IGNORES:
        ok = entry in gi or entry.rstrip("/") in gi
        print(f"- `{entry}` が .gitignore に{'ある' if ok else '**ない**'}")
    if not (root / ".git").exists():
        print("- git リポジトリではない（履歴への混入チェックは不要）")
        return
    code, out = run(["git", "ls-files"], root)
    tracked = out.splitlines() if code == 0 else []
    bad = [f for f in tracked if f.endswith("secrets.toml") or Path(f).name.startswith(".env")
           or Path(f).suffix in {".db", ".sqlite", ".sqlite3", ".pem", ".key"}]
    print(f"- 追跡中の要注意ファイル: {', '.join(bad) if bad else 'なし'}")
    key_re = r"AIza[0-9A-Za-z_\-]{35}|sk-ant-|sk-proj-|sk-[0-9A-Za-z]{40,}|AKIA[0-9A-Z]{16}|hf_[0-9A-Za-z]{30,}|gsk_|xai-[0-9A-Za-z]{40,}"
    code, out = run(["git", "log", "-p", "--all", "-G", key_re, "--format=%h %s"], root)
    commits = [l for l in out.splitlines() if re.match(r"^[0-9a-f]{7,} ", l)]
    print(f"- 履歴中にキーらしき文字列を含むコミット: {', '.join(commits[:10]) if commits else 'なし'}")
    code, out = run(["git", "remote", "-v"], root)
    remotes = sorted({l.split()[1] for l in out.splitlines() if len(l.split()) >= 2})
    print(f"- リモート: {', '.join(remotes) if remotes else 'なし'}（公開リポジトリかどうかはユーザーに確認）")


def toml_value(text: str, section_name: str, key: str) -> Optional[str]:
    current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            current = m.group(1).strip()
            continue
        m = re.match(rf"^{re.escape(key)}\s*=\s*(.+)$", line)
        if m and current == section_name:
            return m.group(1).strip().strip('"\'')
    return None


def scan_streamlit(root: Path) -> None:
    section("3. Streamlit の設定と待ち受け")
    configs = [root / ".streamlit" / "config.toml", Path.home() / ".streamlit" / "config.toml"]
    settings = {
        ("server", "address"): "未設定 → 全インターフェースで待ち受け（LANから到達可能）",
        ("server", "enableXsrfProtection"): "既定 true",
        ("server", "enableCORS"): "既定 true",
        ("server", "enableStaticServing"): "既定 false",
        ("server", "maxUploadSize"): "既定 200（MB）",
        ("client", "showErrorDetails"): "既定（トレースバックをブラウザに表示）",
        ("browser", "gatherUsageStats"): "既定 true（利用統計の送信）",
    }
    for (sec, key), default in settings.items():
        value, source = None, None
        for cfg in configs:  # プロジェクトの設定が優先
            v = toml_value(read(cfg), sec, key)
            if v is not None:
                value, source = v, rel(cfg, root)
                break
        shown = f"`{value}`（{source}）" if value is not None else default
        print(f"- {sec}.{key}: {shown}")

    secrets = root / ".streamlit" / "secrets.toml"
    if secrets.exists():
        mode = stat.S_IMODE(secrets.stat().st_mode)
        print(f"- .streamlit/secrets.toml あり（権限 {oct(mode)}）")
        if "[auth]" in read(secrets):
            print("- secrets.toml に [auth]（st.login の設定）あり → cookie_secret と redirect_uri を確認")

    # 起動コマンド・デプロイ設定中のサーバー引数
    for p in walk(root, {".sh", ".toml", ".yml", ".yaml", ".json", ".md", ""}):
        for lineno, line in enumerate(read(p).splitlines(), 1):
            if re.search(r"--server\.(address|port|enableCORS|enableXsrfProtection)", line):
                print(f"- 起動引数: `{rel(p, root)}:{lineno}` `{line.strip()[:120]}`")

    if shutil.which("lsof"):
        code, out = run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], root)
        lines = [l for l in out.splitlines() if re.search(r"[:.]85\d\d \(LISTEN\)", l)]
        for l in lines:
            addr = l.split()[-2]
            exposed = addr.startswith("*:") or addr.startswith("0.0.0.0") or addr.startswith("[::]")
            print(f"- 起動中: `{l.split()[0]}` `{addr}` → {'**全インターフェースに公開**' if exposed else 'ローカルのみ'}")
        if not lines:
            print("- ポート 85xx で待ち受け中のプロセスなし")
    else:
        print("- lsof が無いため待ち受けの確認は未実施")


def grep_py(root: Path, patterns: List[Tuple[str, "re.Pattern[str]"]], limit_per_label: int = 20) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for p in walk(root, {".py"}):
        for lineno, line in enumerate(read(p).splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for label, pat in patterns:
                if pat.search(line):
                    items = found.setdefault(label, [])
                    if len(items) < limit_per_label:
                        items.append(f"`{rel(p, root)}:{lineno}` `{line.strip()[:100]}`")
                    elif len(items) == limit_per_label:
                        items.append("…（以下省略）")
    return found


def scan_llm_sdks(root: Path) -> None:
    section("4. 使われている LLM SDK・フレームワーク")
    found = grep_py(root, LLM_SDKS, limit_per_label=5)
    if not found:
        print("- 検出なし（HTTP で直接呼んでいる可能性。requests / httpx の箇所を確認）")
    for label, items in found.items():
        print(f"- **{label}**: " + ", ".join(i.split(" ")[0] for i in items))


def scan_code(root: Path) -> None:
    section("5. 危険になりうるコードパターン")
    found = grep_py(root, RISKY_CODE)
    if not found:
        print("- 検出なし")
    for label, items in found.items():
        print(f"- **{label}**")
        for i in items:
            print(f"  - {i}")


def scan_review_points(root: Path) -> None:
    section("6. 手で確認すべき箇所（Streamlit / LLM 固有）")
    found = grep_py(root, REVIEW_POINTS)
    for label, _ in REVIEW_POINTS:
        items = found.get(label)
        if not items:
            print(f"- {label}: なし")
            continue
        print(f"- **{label}**")
        for i in items:
            print(f"  - {i}")
    pages = root / "pages"
    if pages.is_dir():
        names = sorted(p.name for p in pages.glob("*.py"))
        print(f"- マルチページ `pages/`: {', '.join(names)}（認証チェックがページごとにあるか確認）")


def scan_deploy(root: Path) -> None:
    section("7. デプロイ・公開に関するファイル")
    any_found = False
    for name in DEPLOY_FILES:
        p = root / name
        if not p.exists():
            continue
        any_found = True
        text = read(p)
        notes = []
        if name == "Dockerfile":
            notes.append("USER 指定あり" if re.search(r"^\s*USER\s+", text, re.M) else "**USER 指定なし（root で実行）**")
            if re.search(r"^\s*COPY\s+\.\s", text, re.M) and not (root / ".dockerignore").exists():
                notes.append("**`COPY .` があるのに .dockerignore が無い（secrets や .env がイメージに入りうる）**")
            m = re.findall(r"^\s*EXPOSE\s+(.+)$", text, re.M)
            if m:
                notes.append("EXPOSE " + ", ".join(x.strip() for x in m))
        if name == ".dockerignore":
            missing = [e for e in (".env", "secrets.toml", ".git") if e not in text]
            notes.append("除外に無いもの: " + ", ".join(missing) if missing else "主要な秘密ファイルは除外済み")
        if "compose" in name:
            ports = re.findall(r"[\"']?(\d+(?:\.\d+){3}:)?\d+:\d+[\"']?", text)
            if ports:
                notes.append("ports の公開あり（ホストのアドレス指定が無ければ全インターフェース）")
        print(f"- `{name}`" + (f": {'; '.join(notes)}" if notes else ""))
    tunnels = grep_py(root, [("トンネル（ngrok / cloudflared / localtunnel）", re.compile(r"ngrok|cloudflared|localtunnel|pyngrok"))])
    for label, items in tunnels.items():
        any_found = True
        print(f"- **{label}**: " + ", ".join(i.split(" ")[0] for i in items))
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        any_found = True
        for p in sorted(wf.glob("*.y*ml")):
            t = read(p)
            flag = "（**pull_request_target あり**）" if "pull_request_target" in t else ""
            print(f"- GitHub Actions: `{rel(p, root)}`{flag}")
    if not any_found:
        print("- なし（ローカル実行のみの可能性。README の起動方法と合わせて判断）")


def scan_exec_config(root: Path) -> None:
    section("8. リポジトリ内の実行されうる設定・スキル")
    any_found = False
    for name in EXEC_CONFIG:
        p = root / name
        if p.exists():
            any_found = True
            t = read(p)
            flag = "（hooks あり）" if '"hooks"' in t else ""
            print(f"- `{name}` あり{flag}")
    for d in (root / ".claude" / "skills", root / ".agents" / "skills"):
        if d.is_dir():
            any_found = True
            skills = sorted(x.name for x in d.iterdir() if x.is_dir())
            print(f"- `{rel(d, root)}`: {', '.join(skills) if skills else '空'}")
    if not any_found:
        print("- なし")


def scan_data(root: Path) -> None:
    section("9. ローカルに保存されたデータ")
    candidates: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".streamlit"]
        in_data_dir = any(part in DATA_DIR_NAMES for part in Path(dirpath).relative_to(root).parts)
        for name in filenames:
            p = Path(dirpath) / name
            if in_data_dir or p.suffix in {".db", ".sqlite", ".sqlite3", ".log", ".pkl", ".jsonl"}:
                if p.suffix in DATA_SUFFIXES or in_data_dir:
                    candidates.append(p)
    if not candidates:
        print("- 検出なし")
        return
    home = str(Path.home())
    synced = any(str(root).startswith(os.path.join(home, d)) for d in ("Desktop", "Documents", "Library/Mobile Documents", "Dropbox", "OneDrive", "Google Drive"))
    if synced:
        print("- プロジェクトがクラウド同期されうる場所（Desktop / Documents / Dropbox 等）にある。同期設定をユーザーに確認")
    for p in sorted(candidates)[:50]:
        mode = stat.S_IMODE(p.stat().st_mode)
        others = "**他ユーザーも読める**" if mode & 0o044 else "本人のみ"
        print(f"- `{rel(p, root)}`: {p.stat().st_size:,} バイト, 権限 {oct(mode)}（{others}）")


def scan_deps(root: Path) -> None:
    section("10. 依存関係と実行環境")
    py = next((root / d / "bin" / "python" for d in (".venv", "venv", "env") if (root / d / "bin" / "python").exists()), None)
    python = str(py) if py else sys.executable
    code, out = run([python, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"], root)
    ver = out.strip()
    note = ""
    try:
        major, minor = (int(x) for x in ver.split(".")[:2])
        eol = PYTHON_EOL.get((major, minor))
        if eol:
            today = datetime.date.today().strftime("%Y-%m")
            if eol <= today:
                note = f"（**{eol} にサポート終了済み**）"
            else:
                y, m = (int(x) for x in eol.split("-"))
                months_left = (y - datetime.date.today().year) * 12 + m - datetime.date.today().month
                note = f"（{eol} にサポート終了予定" + ("。**まもなく終了**" if months_left <= 6 else "") + "）"
    except ValueError:
        pass
    print(f"- Python {ver}（{'プロジェクトの venv' if py else 'スクリプトを実行した Python'}）{note}")
    present = [f for f in DEP_FILES if (root / f).exists()]
    print(f"- 依存関係ファイル: {', '.join(present) if present else '**なし**'}")
    reqs = read(root / "requirements.txt")
    if reqs:
        lines = [l.strip() for l in reqs.splitlines() if l.strip() and not l.strip().startswith("#")]
        unpinned = [l for l in lines if "==" not in l and not l.startswith("-")]
        print("- requirements.txt: " + ", ".join(lines))
        if unpinned:
            print(f"- `==` で固定されていないもの: {', '.join(unpinned)}")
    if py:
        code, out = run([python, "-m", "pip", "list", "--format=freeze"], root, timeout=60)
        if code == 0:
            key = [l for l in out.splitlines() if re.match(r"(?i)^(streamlit|openai|anthropic|google-genai|google-generativeai|langchain[\w-]*|llama-index[\w-]*|litellm)==", l)]
            if key:
                print("- 主要パッケージの導入済みバージョン: " + ", ".join(key))
    auditor = shutil.which("pip-audit")
    if auditor:
        cmd = [auditor, "--progress-spinner", "off", "-r", "requirements.txt"] if reqs else [auditor, "--progress-spinner", "off"]
        code, out = run(cmd, root, timeout=300)
        print("- pip-audit の結果:\n\n```\n" + out.strip()[-3000:] + "\n```")
    else:
        print("- pip-audit が見つからない（既知の脆弱性チェックは未実施。導入するかユーザーに確認すること）")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(f"# クイックスキャン結果: {root}")
    print(f"\n実行日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}。以下は候補であり、誤検知・見逃しを含む。")
    for fn in (scan_secrets, scan_gitignore_and_git, scan_streamlit, scan_llm_sdks, scan_code,
               scan_review_points, scan_deploy, scan_exec_config, scan_data, scan_deps):
        try:
            fn(root)
        except Exception as e:  # 1つの失敗で全体を止めない
            print(f"- （このセクションの実行中にエラー: {type(e).__name__}: {e}）")


if __name__ == "__main__":
    main()
