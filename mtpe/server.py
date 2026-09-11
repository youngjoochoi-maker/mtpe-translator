"""MTPE 로컬 웹 UI 백엔드 (FastAPI).

실행:  ./.venv/bin/python -m mtpe.server   (기본 http://127.0.0.1:8000)
키는 로컬 .env 에 저장되며, 모델은 UI 에서 선택한다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from starlette.middleware.sessions import SessionMiddleware

from .bundle import Bundle, Step, list_bundles
from .io_utils import read_text
from .paths import data_root, resource_root
from .pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = resource_root()          # 번들된 읽기전용 리소스(config/web/기본 prompts)
DATA_ROOT = data_root()                  # 쓰기 가능한 데이터(prompts 편집본/works/.env)
CONFIG_PATH = RESOURCE_ROOT / "config.yaml"
ENV_PATH = DATA_ROOT / ".env"
WEB_DIR = RESOURCE_ROOT / "mtpe" / "web"

# ── 운영 모드 (서버 배포용) ───────────────────────────────────
# MTPE_APP_PASSWORD 설정 시 로그인 게이트 활성화(사내 공유 비밀번호)
APP_PASSWORD = os.environ.get("MTPE_APP_PASSWORD", "")
# MTPE_KEY_MANAGED 설정 시 키 입력 UI 숨김(회사 공용 키를 서버 env 로 운영)
KEY_MANAGED = bool(os.environ.get("MTPE_KEY_MANAGED"))
SESSION_SECRET = os.environ.get("MTPE_SECRET") or "mtpe-dev-secret-change-me"
# MTPE_API_TOKEN 설정 시 자동화 API(/api/automate/*)를 이 토큰(헤더 X-API-Key)으로 보호(n8n 등)
API_TOKEN = os.environ.get("MTPE_API_TOKEN", "")

app = FastAPI(title="MTPE 번역 파이프라인")


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """MTPE_APP_PASSWORD 설정 시 로그인 안 된 요청을 차단."""
    if not APP_PASSWORD:
        return await call_next(request)
    path = request.url.path
    # /api/automate/* 는 세션 로그인 대신 API 토큰(X-API-Key)으로 별도 보호되므로 게이트 통과
    allow = (path in ("/login",) or path.startswith("/api/login")
             or path.startswith("/api/logout") or path.startswith("/api/automate"))
    if allow or request.session.get("authed"):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "로그인이 필요합니다."}, status_code=401)
    return RedirectResponse("/login")


# SessionMiddleware 는 auth_gate 보다 바깥에서 동작해야 하므로 뒤에 추가
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

# 모델 문자열 → 필요한 환경변수 키 (UI 안내용)
PROVIDER_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "o1": "OPENAI_API_KEY",
    "o3": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# UI 모델 프리셋 (사용자가 직접 입력도 가능)
MODEL_PRESETS = [
    {"label": "🧪 키 없이 테스트 (모의 응답)", "model": "mock"},
    {"label": "Claude Opus 4.8", "model": "claude-opus-4-8"},
    {"label": "Claude Sonnet 4.6", "model": "claude-sonnet-4-6"},
    {"label": "Claude Haiku 4.5", "model": "claude-haiku-4-5-20251001"},
    {"label": "OpenAI GPT-4o", "model": "gpt-4o"},
    {"label": "OpenAI o3", "model": "o3"},
    {"label": "Gemini 3.6 Flash", "model": "gemini/gemini-3.6-flash"},
    {"label": "Gemini 2.5 Flash", "model": "gemini/gemini-2.5-flash"},
    {"label": "Gemini 2.5 Pro", "model": "gemini/gemini-2.5-pro"},
    {"label": "Gemini 3.1 Pro", "model": "gemini/gemini-3.1-pro-preview"},
]


# 대소문자·공백 변형까지 허용: <center>, <CENTER>, < center >, </ center > 등
_CENTER_LINE_RE = re.compile(r'^\s*<\s*center\s*>(.*?)<\s*/\s*center\s*>\s*$', re.S | re.I)
_CENTER_TAG_RE = re.compile(r'<\s*/?\s*center\s*>', re.I)


_JP_BODY_PT = 10          # 가이드: 본문 10pt 통일
_JP_TITLE_PT = 10        # 가이드: 제목도 10pt 통일(볼드만). 필요 시 이 값만 조정.
_NOVEL_MARK = "−ノベル版−"  # −ノベル版− (− 는 U+2212)
_ELLIPSIS_ASCII_RE = re.compile(r'\.{3,}')
_ELLIPSIS_RUN_RE = re.compile(r'…+')
_FW_DIGITS = str.maketrans('0123456789', '０１２３４５６７８９')
_JP_EPNO_LINE_RE = re.compile(r'\d+\.?')          # 본문 맨 앞 원문 화수줄(예: 172.)
_JP_SCENE_RE = re.compile(r'[\*＊][\s\*＊]*')  # 장면전환 별표만으로 된 줄


def _is_jp(lang) -> bool:
    return str(lang or "").lower() in ("ko-jp", "ko-ja", "jp", "ja", "japanese", "일본어")


def _norm_ellipsis(s: str) -> str:
    """말줄임표를 짝수 개(최소 2)로 정규화. …… 유지, … → ……, ……… → …………(4)."""
    s = s.replace('‥', '…')                       # ‥ → …
    s = _ELLIPSIS_ASCII_RE.sub(lambda m: '…' * (len(m.group(0)) // 3), s)  # ... → …

    def _rep(m):
        n = len(m.group(0))
        n = max(2, n + (n % 2))
        return '…' * n
    return _ELLIPSIS_RUN_RE.sub(_rep, s)


_CLOSE_BRACKETS = "｣」』）\)\]］＞’”"
_JP_PERIOD_BEFORE_CLOSE_RE = re.compile(r'。(?=[' + _CLOSE_BRACKETS + r'])')
_JP_SPACE_AFTER_QE_RE = re.compile(r'([？！])[ \u3000]+')


def _jp_text_transform(line: str) -> str:
    """한일 표기 규칙 자동 교정:
    - 대사 괄호 전각「」→ 반각 ｢｣
    - 말줄임표 짝수(……) 정규화
    - 닫는 괄호(｣」』) 앞 마침표(。) 제거
    - 물음표·느낌표(？！) 뒤 공백 제거"""
    line = line.replace("「", "｢").replace("」", "｣")
    line = _norm_ellipsis(line)
    line = _JP_PERIOD_BEFORE_CLOSE_RE.sub("", line)
    line = _JP_SPACE_AFTER_QE_RE.sub(r"\1", line)
    return line


def _work_jp_title(work) -> str:
    """작품별 일본어 제목(라이브러리 설정 jp_title). 없으면 빈 문자열."""
    try:
        return (_read_lib_cfg(work) or {}).get("jp_title", "") or ""
    except Exception:
        return ""


def _ep_number(episode) -> str:
    m = re.search(r'\d+', str(episode or ""))
    return m.group(0) if m else ""


def _set_run_font(run, name: str, size_pt: float) -> None:
    """런의 글꼴을 (동아시아 문자 포함) 지정."""
    from docx.oxml.ns import qn
    from docx.shared import Pt
    run.font.name = name
    run.font.size = Pt(size_pt)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = rpr.makeelement(qn('w:rFonts'), {})
        rpr.insert(0, rfonts)
    for attr in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
        rfonts.set(qn(attr), name)


def _add_doc_paragraphs(doc, text: str, *, lang=None, work=None, episode=None) -> None:
    """번역문을 docx 문단으로 추가.
    - 공통: <center>…</center> 줄 → 태그 제거 + 가운데 정렬 + 볼드.
    - 한일(ko-jp): 가이드 서식 반영.
      · 상단 제목 블록(작품명[크게·볼드] / −ノベル版−[볼드] / 第N話[볼드, 한자릿수 전각]) 가운데.
      · 본문 양쪽정렬, 대사 ｢｣·말줄임표 …… 변환.
      · 끝에 본문 2줄 띄우고 「つづく」 우측정렬 + 1줄.
      · 폰트 Yu Gothic, 본문 10pt, 줄간격 1.15, 단락 뒤 공백 0."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    jp = _is_jp(lang)

    # ── 한일 제목 블록 ──
    if jp:
        jp_title = _work_jp_title(work)
        if jp_title:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = para.add_run(jp_title); r.bold = True
            _set_run_font(r, "Yu Gothic", _JP_TITLE_PT)      # 제목만 크게

            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = para.add_run(_NOVEL_MARK); r.bold = True
            _set_run_font(r, "Yu Gothic", _JP_BODY_PT)

            epno = _ep_number(episode)
            if epno:
                disp = epno.translate(_FW_DIGITS) if len(epno) == 1 else epno  # 한 자릿수 전각
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = para.add_run(f"第{disp}話"); r.bold = True
                _set_run_font(r, "Yu Gothic", _JP_BODY_PT)
            doc.add_paragraph()  # 제목 블록과 본문 사이 빈 줄

    # ── 본문 ──
    lines = (text or "").split("\n")
    if jp:
        # 본문 맨 앞에 남은 원문 화수줄(예: "172.")·빈줄 제거 — 第N話가 제목블록에 있음
        k = 0
        while k < len(lines) and (not lines[k].strip()
                                  or _JP_EPNO_LINE_RE.fullmatch(lines[k].strip())):
            k += 1
        lines = lines[k:]
    for line in lines:
        m = _CENTER_LINE_RE.match(line)
        if m:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.add_run(m.group(1).strip()).bold = True
        else:
            content = _CENTER_TAG_RE.sub("", line)
            stripped = content.strip()
            if jp and stripped and _JP_SCENE_RE.fullmatch(stripped):
                # 장면전환 기호는 형태 불문 "* * *" 가운데정렬로 통일
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                para.add_run("* * *")
                continue
            if jp:
                content = _jp_text_transform(content)
            para = doc.add_paragraph(content)
            if jp:
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # ── 한일: 끝맺음(つづく) + 폰트/단락 서식 일괄 ──
    if jp:
        doc.add_paragraph()
        doc.add_paragraph()               # 본문에서 2줄 띄움
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        para.add_run("つづく")
        doc.add_paragraph()               # 아래 1줄
        for para in doc.paragraphs:
            pf = para.paragraph_format
            pf.line_spacing = 1.15
            pf.space_after = Pt(0)
            for run in para.runs:
                if run.font.size is None:     # 이미 지정된(제목 등) 건 유지
                    _set_run_font(run, "Yu Gothic", _JP_BODY_PT)
                elif run.font.name != "Yu Gothic":
                    _set_run_font(run, "Yu Gothic", run.font.size.pt)


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def required_key_for(model: str) -> str | None:
    m = (model or "").lower()
    if m == "mock":
        return None
    for prefix, env in PROVIDER_KEYS.items():
        if m.startswith(prefix):
            return env
    return None


def _mock_llm(model, system_prompt, user_prompt, temperature, max_tokens):
    """키 없이 흐름을 확인하기 위한 가짜 LLM 응답(실제 호출 안 함)."""
    preview = " ".join(user_prompt.split())[:180]
    return (
        "■ 모의 응답입니다 (실제 LLM 호출 안 함 / 비용 0).\n"
        "상단 모델을 실제 모델로 바꾸고 API 키를 저장하면 이 자리에 진짜 결과가 나옵니다.\n\n"
        f"· 이 단계가 받은 프롬프트 앞부분: {preview} …"
    )


def load_env_into_os() -> None:
    """.env 의 KEY=VALUE 를 os.environ 에 반영(덮어쓰기 포함)."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def upsert_env(key: str, value: str) -> None:
    """.env 에 KEY=VALUE 를 추가/갱신하고 os.environ 에도 반영."""
    lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"# {key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    # 브라우저가 옛 UI 를 캐시하지 않도록(기능 업데이트 즉시 반영)
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })


@app.get("/api/bootstrap")
def bootstrap() -> JSONResponse:
    """UI 초기화 데이터: 번들 목록, 모델 프리셋, 기본값, 키 상태."""
    cfg = _load_config()
    load_env_into_os()
    key_status = {
        env: bool(os.environ.get(env))
        for env in sorted(set(PROVIDER_KEYS.values()))
    }
    return JSONResponse({
        "bundles": list_bundles(_prompts_root()),
        "models": MODEL_PRESETS,
        "defaults": {
            "work": cfg.get("default_work"),
            "lang": cfg.get("default_lang"),
            "model": cfg.get("default_model"),
        },
        "key_status": key_status,
        "key_managed": KEY_MANAGED,   # True 면 UI 에서 키 입력 숨김(회사 공용 키 운영)
        "auth_required": bool(APP_PASSWORD),
    })


LOGIN_HTML = """<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>MTPE 로그인</title>
<style>body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f1115;color:#e6e8ee;font:14px -apple-system,sans-serif}
.box{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:32px;width:320px}
h1{font-size:18px;margin:0 0 4px}.sub{color:#9aa3b2;font-size:13px;margin-bottom:20px}
input{width:100%;box-sizing:border-box;background:#0d0f14;color:#e6e8ee;border:1px solid #262b36;
border-radius:8px;padding:11px;font-size:14px;margin-bottom:12px}
button{width:100%;background:#4f8cff;color:#fff;border:0;border-radius:8px;padding:11px;font-weight:600;cursor:pointer}
.err{color:#ff5c5c;font-size:13px;min-height:18px;margin-top:8px}</style></head>
<body><div class="box"><h1>MTPE 번역 파이프라인</h1>
<div class="sub">접속 비밀번호를 입력하세요</div>
<input type="password" id="pw" placeholder="비밀번호" autofocus>
<button id="go">로그인</button><div class="err" id="err"></div></div>
<script>
async function login(){const fd=new FormData();fd.append("password",document.getElementById("pw").value);
const r=await fetch("/api/login",{method:"POST",body:fd});const d=await r.json();
if(d.ok)location.href="/";else document.getElementById("err").textContent=d.error||"실패";}
document.getElementById("go").onclick=login;
document.getElementById("pw").addEventListener("keydown",e=>{if(e.key==="Enter")login();});
</script></body></html>"""


@app.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    return HTMLResponse(LOGIN_HTML)


@app.post("/api/login")
def do_login(request: Request, password: str = Form(...)) -> JSONResponse:
    if APP_PASSWORD and password == APP_PASSWORD:
        request.session["authed"] = True
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "비밀번호가 올바르지 않습니다."}, status_code=401)


@app.post("/api/logout")
def do_logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})


@app.post("/api/save-key")
def save_key(provider_key: str = Form(...), value: str = Form(...)) -> JSONResponse:
    """API 키를 로컬 .env 에 저장. (회사 공용 키 운영 시엔 비활성)"""
    if KEY_MANAGED:
        return JSONResponse({"ok": False, "error": "서버에서 키를 관리합니다."}, status_code=403)
    if provider_key not in PROVIDER_KEYS.values():
        return JSONResponse({"ok": False, "error": "알 수 없는 키 이름"}, status_code=400)
    if not value.strip():
        return JSONResponse({"ok": False, "error": "빈 값"}, status_code=400)
    upsert_env(provider_key, value.strip())
    return JSONResponse({"ok": True, "saved": provider_key})


@app.post("/api/translate")
async def translate(
    source: UploadFile,
    work: str = Form(...),
    lang: str = Form(...),
    model: str = Form(...),
    version: str = Form(""),
    glossary: UploadFile | None = None,
) -> StreamingResponse:
    """파일을 받아 5단계 파이프라인을 실행하며 NDJSON 으로 단계별 결과를 스트리밍."""
    load_env_into_os()

    # 업로드 파일을 임시 저장 후 read_text 로 형식별 파싱(docx/xlsx 포함)
    import tempfile

    def _save_tmp(uf: UploadFile, data: bytes) -> str:
        suffix = Path(uf.filename or "").suffix or ".txt"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return tmp

    src_tmp = _save_tmp(source, await source.read())
    glo_tmp = _save_tmp(glossary, await glossary.read()) if glossary else None

    def stream():
        try:
            source_text = read_text(src_tmp)
            glossary_text = read_text(glo_tmp) if glo_tmp else ""
            pipe = Pipeline.from_config(
                CONFIG_PATH, work=work, lang=lang, version=version or None
            )
            b = pipe.bundle
            need = required_key_for(model)
            if need and not os.environ.get(need):
                yield json.dumps({"type": "error",
                    "message": f"{need} 가 설정되지 않았습니다. 상단에서 키를 저장하세요."}) + "\n"
                return

            yield json.dumps({"type": "start", "work": b.work, "lang": b.lang,
                "version": b.version, "model": model,
                "steps": [{"id": s.id, "name": s.name} for s in b.steps]},
                ensure_ascii=False) + "\n"

            for r in pipe.run_iter(source_text, glossary_text, model_override=model):
                yield json.dumps({"type": "step", "id": r.id, "name": r.name,
                    "model": r.model, "chars": len(r.output), "output": r.output},
                    ensure_ascii=False) + "\n"

            yield json.dumps({"type": "final", "output": pipe.final_output},
                ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": str(exc)},
                ensure_ascii=False) + "\n"
        finally:
            for t in (src_tmp, glo_tmp):
                if t and os.path.exists(t):
                    os.remove(t)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ── 프롬프트 번들 편집 (작품/버전 관리) ──────────────────────

def _prompts_root() -> Path:
    return DATA_ROOT / _load_config().get("prompts_root", "prompts")


def _safe_seg(s: str) -> str:
    s = (s or "").strip()
    if not s or "/" in s or "\\" in s or ".." in s:
        raise ValueError(f"잘못된 경로 요소: {s!r}")
    return s


@app.get("/api/bundle")
def get_bundle(work: str, lang: str, version: str) -> JSONResponse:
    """편집용: meta + 각 단계 프롬프트 원문을 반환."""
    try:
        path = _prompts_root() / _safe_seg(work) / _safe_seg(lang) / _safe_seg(version)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    mp = path / "meta.yaml"
    if not mp.exists():
        return JSONResponse({"error": "번들을 찾을 수 없습니다."}, status_code=404)
    meta = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
    steps = []
    for s in meta.get("steps", []):
        f = path / s.get("file", "")
        steps.append({
            "id": s["id"],
            "name": s.get("name", f"STEP {s['id']}"),
            "inputs": s.get("inputs", []),
            "model": s.get("model") or "",
            "extract": s.get("extract") or "",
            "final": s.get("output") == "final",
            "content": f.read_text(encoding="utf-8") if f.exists() else "",
        })
    hs_path = path / "house_style.md"
    house_style = hs_path.read_text(encoding="utf-8") if hs_path.exists() else ""
    return JSONResponse({
        "work": meta.get("work", work), "lang": meta.get("lang", lang),
        "version": version, "source_lang": meta.get("source_lang", "auto"),
        "target_lang": meta.get("target_lang", "한국어"),
        "notes": meta.get("notes", ""),
        "house_style": house_style, "steps": steps,
    })


@app.get("/api/bundle/next-version")
def next_version(work: str, lang: str) -> JSONResponse:
    """해당 작품/언어의 다음 버전 이름(v+1)을 제안."""
    try:
        ld = _prompts_root() / _safe_seg(work) / _safe_seg(lang)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    nums = []
    if ld.is_dir():
        for p in ld.iterdir():
            if p.is_dir():
                m = re.search(r"(\d+)", p.name)
                if m:
                    nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return JSONResponse({"version": f"v{n}"})


@app.post("/api/bundle/save")
def save_bundle(payload: dict = Body(...)) -> JSONResponse:
    """프롬프트 + meta 를 번들 경로에 저장(없으면 생성). 새 버전/새 작품도 동일 처리."""
    try:
        work = _safe_seg(payload["work"])
        # 언어쌍·버전은 소문자로 통일(ko-EN / V1 등 대소문자 혼용 방지 → 평가표·번들 매칭 안정)
        lang = _safe_seg(payload["lang"]).lower()
        version = _safe_seg(payload["version"]).lower()
    except (KeyError, ValueError) as e:
        return JSONResponse({"ok": False, "error": f"입력 오류: {e}"}, status_code=400)

    steps_in = payload.get("steps", [])
    if not steps_in:
        return JSONResponse({"ok": False, "error": "단계가 없습니다."}, status_code=400)

    path = _prompts_root() / work / lang / version
    path.mkdir(parents=True, exist_ok=True)

    meta_steps = []
    for s in steps_in:
        sid = int(s["id"])
        fname = f"step{sid}.txt"
        (path / fname).write_text(s.get("content", ""), encoding="utf-8")
        inputs = s.get("inputs", [])
        if isinstance(inputs, str):
            inputs = [x.strip() for x in inputs.split(",")]
        entry = {
            "id": sid,
            "name": s.get("name", f"STEP {sid}"),
            "file": fname,
            "inputs": [x for x in inputs if x],
        }
        if s.get("model"):
            entry["model"] = s["model"]
        if s.get("extract"):
            entry["extract"] = s["extract"]
        if s.get("final"):
            entry["output"] = "final"
        meta_steps.append(entry)

    meta = {
        "work": work, "lang": lang, "version": version,
        "source_lang": payload.get("source_lang", "auto"),
        "target_lang": payload.get("target_lang", "한국어"),
        "notes": payload.get("notes", ""),
        "steps": meta_steps,
    }
    (path / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    # 작품별 공통 규칙(HOUSE STYLE). payload 에 house_style 키가 있을 때만 반영.
    #   내용 있음 → house_style.md 저장 / 비어 있음 → 파일 삭제(=공통 규칙 끔)
    if "house_style" in payload:
        hs = (payload.get("house_style") or "").strip()
        hs_path = path / "house_style.md"
        if hs:
            hs_path.write_text(hs, encoding="utf-8")
        elif hs_path.exists():
            hs_path.unlink()

    return JSONResponse({"ok": True, "work": work, "lang": lang, "version": version,
                         "path": str(path)})


@app.delete("/api/bundle")
def delete_bundle(work: str, lang: str, version: str) -> JSONResponse:
    """저장된 프롬프트 버전을 삭제(폴더 통째로). 상위 폴더가 비면 함께 정리."""
    try:
        path = _prompts_root() / _safe_seg(work) / _safe_seg(lang) / _safe_seg(version)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    if not (path / "meta.yaml").exists():
        return JSONResponse({"ok": False, "error": "해당 버전을 찾을 수 없습니다."}, status_code=404)
    shutil.rmtree(path)
    # 언어/작품 폴더가 비면 정리
    for d in (path.parent, path.parent.parent):
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            break
    return JSONResponse({"ok": True})


# ── 자료 라이브러리 (작품별 회차 원문 + 설정집) ─────────────────
WORKS_ROOT = DATA_ROOT / "works"
SOURCE_EXTS = {".txt", ".md", ".docx", ".srt", ".vtt"}


def _work_dir(work: str) -> Path:
    return WORKS_ROOT / _safe_seg(work)


def _natkey(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _read_lib_cfg(work: str) -> dict:
    p = _work_dir(work) / "library.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _write_lib_cfg(work: str, cfg: dict) -> None:
    d = _work_dir(work)
    d.mkdir(parents=True, exist_ok=True)
    (d / "library.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _list_episodes(work: str) -> list[dict]:
    eps: dict[str, dict] = {}
    up = _work_dir(work) / "episodes"
    if up.is_dir():
        for f in up.iterdir():
            if f.is_file() and f.suffix.lower() in SOURCE_EXTS:
                eps[f.name] = {"id": f.name, "name": f.name,
                               "origin": "업로드", "size": f.stat().st_size}
    sd = _read_lib_cfg(work).get("source_dir")
    if sd and Path(sd).is_dir():
        for f in Path(sd).iterdir():
            if f.is_file() and f.suffix.lower() in SOURCE_EXTS and f.name not in eps:
                eps[f.name] = {"id": f.name, "name": f.name,
                               "origin": "폴더", "size": f.stat().st_size}
    return sorted(eps.values(), key=lambda e: _natkey(e["name"]))


def _episode_path(work: str, eid: str) -> Path | None:
    eid = _safe_seg(eid)
    up = _work_dir(work) / "episodes" / eid
    if up.exists():
        return up
    sd = _read_lib_cfg(work).get("source_dir")
    if sd:
        p = Path(sd) / eid
        if p.exists():
            return p
    return None


def _tb_path(work: str) -> Path | None:
    d = _work_dir(work) / "tb"
    if d.is_dir():
        files = sorted(f for f in d.iterdir() if f.is_file())
        if files:
            return files[0]
    return None


def _tb_sheets(tb: Path) -> list[str]:
    """엑셀 TB 의 시트 이름 목록(엑셀이 아니면 빈 리스트)."""
    if tb.suffix.lower() not in (".xlsx", ".xlsm"):
        return []
    import openpyxl

    wb = openpyxl.load_workbook(str(tb), read_only=True)
    names = list(wb.sheetnames)
    wb.close()
    return names


def _read_tb_text(work: str) -> str:
    """선택된 시트만 반영해 TB 를 텍스트로 변환(선택 없으면 전체)."""
    tb = _tb_path(work)
    if not tb:
        return ""
    if tb.suffix.lower() in (".xlsx", ".xlsm"):
        from .io_utils import _read_xlsx
        sel = _read_lib_cfg(work).get("tb_sheets")  # None → 전체
        return _read_xlsx(tb, sheets=sel)
    return read_text(str(tb))


@app.get("/api/library")
def library(work: str) -> JSONResponse:
    try:
        _safe_seg(work)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    tb = _tb_path(work)
    tb_info = None
    if tb:
        sheets = _tb_sheets(tb)
        sel = _read_lib_cfg(work).get("tb_sheets")
        tb_info = {
            "name": tb.name,
            "sheets": sheets,
            "selected": (sel if sel is not None else sheets),
        }
    return JSONResponse({
        "work": work,
        "source_dir": _read_lib_cfg(work).get("source_dir", ""),
        "jp_title": _read_lib_cfg(work).get("jp_title", ""),
        "episodes": _list_episodes(work),
        "tb": tb_info,
    })


@app.post("/api/library/tb-sheets")
def set_tb_sheets(payload: dict = Body(...)) -> JSONResponse:
    """이 작품 TB 에서 AI 에 전달할 시트 목록을 저장."""
    try:
        work = _safe_seg(payload["work"])
    except (KeyError, ValueError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    sheets = payload.get("sheets", [])
    cfg = _read_lib_cfg(work)
    cfg["tb_sheets"] = [str(s) for s in sheets]
    _write_lib_cfg(work, cfg)
    return JSONResponse({"ok": True})


@app.post("/api/library/source-dir")
def set_source_dir(work: str = Form(...), path: str = Form("")) -> JSONResponse:
    try:
        _safe_seg(work)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    path = path.strip()
    if path and not Path(path).is_dir():
        return JSONResponse({"ok": False, "error": "폴더가 존재하지 않습니다."}, status_code=400)
    cfg = _read_lib_cfg(work)
    cfg["source_dir"] = path
    _write_lib_cfg(work, cfg)
    return JSONResponse({"ok": True, "episodes": _list_episodes(work)})


@app.post("/api/library/jp-title")
def set_jp_title(work: str = Form(...), title: str = Form("")) -> JSONResponse:
    """한일(ko-jp) 제목 블록에 쓸 '일본어 작품 제목'을 작품별로 저장."""
    try:
        _safe_seg(work)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    cfg = _read_lib_cfg(work)
    cfg["jp_title"] = title.strip()
    _write_lib_cfg(work, cfg)
    return JSONResponse({"ok": True})


@app.post("/api/library/episode")
async def add_episode(work: str = Form(...), file: UploadFile = File(...)) -> JSONResponse:
    try:
        _safe_seg(work)
        name = _safe_seg(Path(file.filename or "").name)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    d = _work_dir(work) / "episodes"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(await file.read())
    return JSONResponse({"ok": True, "episodes": _list_episodes(work)})


@app.delete("/api/library/episode")
def delete_episode(work: str, episode: str) -> JSONResponse:
    """업로드한 회차만 삭제(폴더 경로의 원문은 앱에서 삭제하지 않음)."""
    try:
        _safe_seg(work)
        name = _safe_seg(episode)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    f = _work_dir(work) / "episodes" / name
    if not f.exists():
        return JSONResponse({"ok": False,
            "error": "업로드된 회차가 아닙니다. (폴더 경로 원문은 앱에서 삭제하지 않습니다)"},
            status_code=400)
    f.unlink()
    return JSONResponse({"ok": True, "episodes": _list_episodes(work)})


@app.delete("/api/library/tb")
def delete_tb(work: str) -> JSONResponse:
    """현재 설정집을 삭제(없음 상태로)."""
    try:
        _safe_seg(work)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    d = _work_dir(work) / "tb"
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
    return JSONResponse({"ok": True, "tb": None})


@app.get("/api/tb-template")
def tb_template() -> StreamingResponse:
    """설정집(TB) 표준 양식 템플릿(.xlsx)을 생성해 다운로드.

    모든 시트가 텍스트로 변환되어 프롬프트에 주입되므로, 시트/헤더 구조를
    이 양식에 맞춰 채우면 일관되게 활용된다.
    """
    import io

    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()

    sheets = {
        "안내": [
            ["이 파일은 설정집(TB) 양식입니다. 각 시트를 채워 업로드하세요."],
            ["· 모든 시트가 번역 AI에게 참고 자료로 전달됩니다(빈 행은 무시)."],
            ["· 시트/열은 자유롭게 추가·수정 가능합니다. 아래는 권장 구조입니다."],
            ["· 첫 줄(머리글)은 그대로 두고, 둘째 줄부터 내용을 채우세요(예시 행은 지우거나 덮어쓰기)."],
        ],
        "인물": [
            ["중문명", "국문명", "성별", "첫 등장", "메모", "말버릇"],
            ["唐清晨", "당청천", "여", "1화", "회귀한 주인공", "단호한 말투"],
        ],
        "용어": [
            ["범주", "중문명", "국문명", "메모"],
            ["지명", "南河村", "남하촌", "주인공이 사는 마을"],
            ["설정", "末世", "말세", "주인공의 전생 배경"],
        ],
        "호칭": [
            ["화자", "청자", "존대/반말", "자기지칭", "청자호칭", "어미", "비고"],
            ["당청천", "동생들", "반말", "나/누나", "너희", "~야/~자", "다정한 보호자 말투"],
        ],
        "인물관계": [
            ["인물 A", "인물 B", "관계", "비고"],
            ["당청천", "이란화", "손녀-할머니", "정서적으로 적대 관계"],
        ],
        "제목": [
            ["권", "장", "장제목(원문)", "장제목(번역)"],
            ["1", "1", "她回来了", "그녀가 돌아왔다"],
        ],
        "서식 규칙": [
            ["항목", "규칙", "예시"],
            ["대사/지문", "한 문단에 붙이지 말고 행갈음", "그가 말했다.\\n\"예.\""],
            ["생략부호", "……로 통일", "……"],
        ],
    }

    first = True
    bold = Font(bold=True)
    for title, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        first = False
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                cell = ws.cell(row=r + 1, column=c + 1, value=val)
                if r == 0 and title != "안내":
                    cell.font = bold

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="TB_template.xlsx"'},
    )


@app.post("/api/library/tb")
async def set_tb(work: str = Form(...), file: UploadFile = File(...)) -> JSONResponse:
    """설정집을 교체(최신 1개만 유지)."""
    try:
        _safe_seg(work)
        name = _safe_seg(Path(file.filename or "").name)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    d = _work_dir(work) / "tb"
    if d.exists():
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(await file.read())
    # 새 파일은 시트 구성이 다를 수 있으므로 이전 시트 선택을 초기화(=전체)
    cfg = _read_lib_cfg(work)
    if "tb_sheets" in cfg:
        cfg.pop("tb_sheets")
        _write_lib_cfg(work, cfg)
    return JSONResponse({"ok": True, "tb": {"name": name}})


@app.post("/api/run")
def run_episodes(payload: dict = Body(...)) -> StreamingResponse:
    """선택한 회차들을 순차 번역하며 NDJSON 으로 진행을 스트리밍."""
    load_env_into_os()
    work = payload.get("work")
    lang = payload.get("lang")
    version = payload.get("version") or None
    model = payload.get("model")
    eids = payload.get("episodes", [])

    def emit(obj):
        return json.dumps(obj, ensure_ascii=False) + "\n"

    def stream():
        try:
            if not eids:
                yield emit({"type": "error", "message": "선택된 회차가 없습니다."})
                return
            need = required_key_for(model)
            if need and not os.environ.get(need):
                yield emit({"type": "error",
                            "message": f"{need} 가 설정되지 않았습니다. 상단에서 키를 저장하세요."})
                return
            tb = _tb_path(work)
            tb_text = _read_tb_text(work)
            total = len(eids)
            yield emit({"type": "run_start", "total": total,
                        "tb": (tb.name if tb else None)})
            g_sec = 0.0; g_in = 0; g_out = 0; g_cost = 0.0
            import re as _re_zip
            safe_work = _re_zip.sub(r'[\\/:*?"<>|]', "", str(work)).strip() or "WORK"
            out_root = _work_dir(work) / "output"
            saved_docs = []  # [(stem, fname, path)] — 완료 시 자동 저장된 Word 파일들

            for idx, eid in enumerate(eids):
                p = _episode_path(work, eid)
                if not p:
                    yield emit({"type": "episode_error", "episode": eid,
                                "message": "원문 파일을 찾을 수 없습니다."})
                    continue
                source = read_text(str(p))
                pipe = Pipeline.from_config(CONFIG_PATH, work=work, lang=lang, version=version)
                b = pipe.bundle
                yield emit({"type": "episode_start", "episode": eid,
                            "index": idx, "total": total, "version": b.version,
                            "steps": [{"id": s.id, "name": s.name} for s in b.steps]})
                llm = _mock_llm if (model == "mock") else None
                ep_sec = 0.0; ep_in = 0; ep_out = 0; ep_cost = 0.0
                for r in pipe.run_iter(source, tb_text, model_override=model, llm=llm):
                    ep_sec += r.seconds; ep_in += r.in_tokens
                    ep_out += r.out_tokens; ep_cost += r.cost
                    yield emit({"type": "step", "episode": eid, "id": r.id,
                                "name": r.name, "model": r.model,
                                "chars": len(r.output), "output": r.output,
                                "skipped": r.skipped, "error": r.error,
                                "seconds": round(r.seconds, 2), "in_tokens": r.in_tokens,
                                "out_tokens": r.out_tokens, "cost": r.cost})
                outd = _work_dir(work) / "output" / Path(eid).stem
                outd.mkdir(parents=True, exist_ok=True)
                (outd / "final.txt").write_text(pipe.final_output, encoding="utf-8")
                # 완료 즉시 Word(.docx) 자동 저장 — 창을 닫아도 결과가 남도록
                doc_name = f"{safe_work}_{Path(eid).stem}.docx"
                try:
                    import docx as _docx
                    _d = _docx.Document()
                    _add_doc_paragraphs(_d, pipe.final_output, lang=lang, work=work, episode=eid)
                    _d.save(str(outd / doc_name))
                    saved_docs.append((Path(eid).stem, doc_name, str(outd / doc_name)))
                except Exception:
                    doc_name = None
                g_sec += ep_sec; g_in += ep_in; g_out += ep_out; g_cost += ep_cost
                yield emit({"type": "episode_final", "episode": eid,
                            "output": pipe.final_output,
                            "saved": str(outd / "final.txt"),
                            "seconds": round(ep_sec, 2), "in_tokens": ep_in,
                            "out_tokens": ep_out, "cost": ep_cost})
            # 자동 전달 정보: 저장 폴더 + 회차별 Word 링크 (+2회차 이상이면 ZIP 묶음)
            auto = {"dir": str(out_root), "files": [], "zip": None}
            for _stem, _fname, _ in saved_docs:
                auto["files"].append({"name": _fname,
                    "url": f"/api/export-docx-download?work={quote(work)}&episode={quote(_stem)}&name={quote(_fname)}"})
            if len(saved_docs) >= 2:
                try:
                    import zipfile as _zip
                    from datetime import datetime as _dt
                    zip_name = f"{safe_work}_batch_{_dt.now():%Y%m%d_%H%M}.zip"
                    with _zip.ZipFile(str(out_root / zip_name), "w", _zip.ZIP_DEFLATED) as zf:
                        for _stem, _fname, _fpath in saved_docs:
                            if Path(_fpath).exists():
                                zf.write(_fpath, arcname=_fname)
                    auto["zip"] = {"name": zip_name,
                        "url": f"/api/export-zip-download?work={quote(work)}&name={quote(zip_name)}"}
                except Exception:
                    auto["zip"] = None
            yield emit({"type": "all_done", "count": total,
                        "seconds": round(g_sec, 2), "in_tokens": g_in,
                        "out_tokens": g_out, "cost": g_cost, "auto": auto})
        except Exception as exc:  # noqa: BLE001
            yield emit({"type": "error", "message": str(exc)})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/estimate")
def estimate_run(payload: dict = Body(...)) -> JSONResponse:
    """실행 전 예상: 실제 단계 구성(시스템+지시문+원문+설정집(TB)+누적출력)을 모사해
    회차·모델 기준 예상 토큰·비용·시간을 계산한다(러프하지만 실제와 근접)."""
    from .pipeline import estimate_pipeline_usage
    work = payload.get("work"); lang = payload.get("lang")
    version = payload.get("version") or None
    model = payload.get("model") or ""
    eids = payload.get("episodes", [])
    if not eids:
        return JSONResponse({"ok": False, "error": "회차를 선택하세요."}, status_code=400)
    try:
        pipe = Pipeline.from_config(CONFIG_PATH, work=work, lang=lang, version=version)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"설정 로드 실패: {e}"}, status_code=400)
    nsteps = max(1, len(pipe.bundle.steps))
    glossary = _read_tb_text(work)  # 설정집(TB) — 실제 실행처럼 단계마다 재전송됨
    est_in = est_out = calls = 0
    read_ok = 0
    for eid in eids:
        pp = _episode_path(work, eid)
        src = ""
        if pp:
            try:
                src = read_text(str(pp)); read_ok += 1
            except Exception:
                src = ""
        i, o, c = estimate_pipeline_usage(pipe, src, glossary, model)
        est_in += i; est_out += o; calls += c
    cost = 0.0
    try:
        import litellm
        pc, cc = litellm.cost_per_token(model=model, prompt_tokens=est_in, completion_tokens=est_out)
        cost = float(pc or 0) + float(cc or 0)
    except Exception:
        cost = 0.0
    # 시간: 호출당 지연(~2.5s) + 출력 토큰 처리량(~45토큰/s). 모델 속도에 따라 편차 큼.
    est_seconds = int(calls * 2.5 + est_out / 45.0)
    return JSONResponse({"ok": True, "episodes": len(eids), "steps": nsteps,
                         "calls": calls, "read_ok": read_ok, "tb_used": bool(glossary),
                         "est_in": est_in, "est_out": est_out,
                         "est_cost": cost, "est_seconds": est_seconds})


# ── 자동화(n8n 등) API — 요청 1번 → JSON 1번(비스트리밍) ──────────
def _check_api_token(request: Request) -> JSONResponse | None:
    """자동화 API 인증. 토큰 설정 시 헤더 X-API-Key 로 검사. 배포(비번)인데 토큰 미설정이면 차단."""
    if API_TOKEN:
        supplied = ""
        if request is not None:
            supplied = request.headers.get("x-api-key", "") or request.query_params.get("api_key", "")
        if supplied != API_TOKEN:
            return JSONResponse({"ok": False, "error": "유효한 API 키가 필요합니다 (헤더 X-API-Key)."},
                                status_code=401)
        return None
    if APP_PASSWORD:  # 배포 서버인데 자동화 토큰 미설정 → 보안상 자동화 비활성
        return JSONResponse({"ok": False,
            "error": "자동화 API 가 비활성입니다. 서버에 MTPE_API_TOKEN 을 설정하세요."}, status_code=403)
    return None  # 로컬(비번·토큰 모두 없음)은 개방


@app.get("/api/automate/works")
def automate_works(request: Request) -> JSONResponse:
    """자동화용 — 작품/언어/버전/회차 목록(n8n 이 무엇을 번역할지 조회)."""
    err = _check_api_token(request)
    if err:
        return err
    works = []
    for b in list_bundles(_prompts_root()):
        works.append({
            "work": b["work"],
            "langs": b.get("langs", []),
            "episodes": [e.get("name") for e in _list_episodes(b["work"])],
        })
    return JSONResponse({"ok": True, "works": works})


@app.post("/api/automate/translate")
def automate_translate(request: Request, payload: dict = Body(...)) -> JSONResponse:
    """자동화용 — 회차 1개(또는 원문 텍스트)를 번역해 최종 결과를 단일 JSON 으로 반환.

    body:
      work, lang            (필수)  예: "장저견", "zh-ko"
      version               (선택)  미지정 시 최신
      model                 (선택)  기본 "mock". 실제 모델은 서버 env 에 키 필요
      episode               (원문 소스 ①) 라이브러리 회차 파일명. 주면 그 원문을 읽음
      source                (원문 소스 ②) 원문 텍스트 직접 전달(episode 없을 때)
      glossary              (선택)  설정집 텍스트 직접 전달(없으면 작품 TB 사용)
      save                  (선택, 기본 true) episode 일 때 output/<회차>/final.txt 저장
      include_steps         (선택, 기본 true) 단계별 결과 포함 여부
    """
    err = _check_api_token(request)
    if err:
        return err
    load_env_into_os()

    work = payload.get("work")
    lang = (payload.get("lang") or "").lower()
    version = payload.get("version") or None
    model = payload.get("model") or "mock"
    episode = payload.get("episode")
    source = payload.get("source")
    glossary = payload.get("glossary")
    if not work or not lang:
        return JSONResponse({"ok": False, "error": "work, lang 이 필요합니다."}, status_code=400)

    # 원문 확보: episode 우선 → 없으면 source 텍스트
    if episode:
        p = _episode_path(work, episode)
        if not p:
            return JSONResponse({"ok": False, "error": "회차 원문을 찾을 수 없습니다."}, status_code=400)
        src_text = read_text(str(p))
    elif source:
        src_text = source
    else:
        return JSONResponse({"ok": False, "error": "episode 또는 source 중 하나가 필요합니다."},
                            status_code=400)

    # 설정집: 직접 전달 우선 → 없으면 작품 TB(회차 기반일 때)
    tb_text = glossary if glossary is not None else (_read_tb_text(work) if episode else "")

    need = required_key_for(model)
    if need and not os.environ.get(need):
        return JSONResponse({"ok": False,
            "error": f"{need} 가 서버에 설정되지 않았습니다(서버 .env 에 저장하세요)."}, status_code=400)

    try:
        pipe = Pipeline.from_config(CONFIG_PATH, work=work, lang=lang, version=version)
        llm = _mock_llm if model == "mock" else None
        steps = []
        for r in pipe.run_iter(src_text, tb_text, model_override=model, llm=llm):
            steps.append({"id": r.id, "name": r.name, "chars": len(r.output),
                          "skipped": r.skipped, "error": r.error, "output": r.output})
        final = pipe.final_output
        bver = pipe.bundle.version
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    saved = None
    if episode and payload.get("save", True):
        outd = _work_dir(work) / "output" / Path(episode).stem
        outd.mkdir(parents=True, exist_ok=True)
        (outd / "final.txt").write_text(final, encoding="utf-8")
        saved = str(outd / "final.txt")

    result = {"ok": True, "work": work, "lang": lang, "version": bver,
              "episode": episode, "model": model, "final": final, "saved": saved}
    if payload.get("include_steps", True):
        result["steps"] = steps
    return JSONResponse(result)


# ── 프롬프트 튜닝 (단계별 결과 보며 프롬프트 개선) ───────────────

def _build_tune_pipeline(payload: dict):
    """화면의 편집 중인 단계 구성으로 인메모리 파이프라인을 만든다.

    반환: (Pipeline, {단계id: 프롬프트텍스트})
    """
    cfg = _load_config()
    steps: list[Step] = []
    overrides: dict[int, str] = {}
    for s in payload.get("steps", []):
        sid = int(s["id"])
        steps.append(Step(
            id=sid,
            name=s.get("name", f"STEP {sid}"),
            file=f"step{sid}.txt",
            inputs=list(s.get("inputs", [])),
            model=(s.get("model") or None),
            extract=(s.get("extract") or None),
            is_final=bool(s.get("final")),
        ))
        overrides[sid] = s.get("content", "")
    if steps and not any(st.is_final for st in steps):
        steps[-1].is_final = True
    bundle = Bundle(
        work=payload.get("work", "?"), lang=payload.get("lang", "?"),
        version=payload.get("version", "?"), path=ROOT,
        source_lang=payload.get("source_lang", "auto"),
        target_lang=payload.get("target_lang", "한국어"),
        steps=steps,
    )
    return Pipeline(cfg, ROOT, bundle), overrides


@app.post("/api/tune")
def tune(payload: dict = Body(...)) -> StreamingResponse:
    """샘플 회차에 대해 편집 중인 프롬프트로 시험 실행. 단계별 출력+보낸 프롬프트 스트리밍."""
    load_env_into_os()
    model = payload.get("model") or "mock"

    def emit(obj):
        return json.dumps(obj, ensure_ascii=False) + "\n"

    def stream():
        try:
            if not payload.get("steps"):
                yield emit({"type": "error", "message": "단계가 없습니다."})
                return
            need = required_key_for(model)
            if need and not os.environ.get(need):
                yield emit({"type": "error",
                            "message": f"{need} 가 설정되지 않았습니다. 번역 탭에서 키를 저장하세요."})
                return

            raw_source = (payload.get("source") or "").strip()
            if raw_source:
                source = raw_source
            else:
                ep = payload.get("episode")
                p = _episode_path(payload.get("work"), ep) if ep else None
                if not p:
                    yield emit({"type": "error", "message": "시험할 회차(원문)를 선택하세요."})
                    return
                source = read_text(str(p))

            tb_text = _read_tb_text(payload.get("work"))
            pipe, overrides = _build_tune_pipeline(payload)
            llm = _mock_llm if model == "mock" else None
            from_step = int(payload.get("from_step") or 0)
            seed = payload.get("seed") or {}

            yield emit({"type": "start", "from_step": from_step, "model": model})
            for r in pipe.run_iter(source, tb_text, model_override=model, llm=llm,
                                   prompt_overrides=overrides, seed_artifacts=seed,
                                   start_from=from_step):
                yield emit({"type": "step", "id": r.id, "name": r.name, "model": r.model,
                            "chars": len(r.output), "output": r.output,
                            "prompt": r.user_prompt})
            yield emit({"type": "done", "final": pipe.final_output})
        except Exception as exc:  # noqa: BLE001
            yield emit({"type": "error", "message": str(exc)})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ── MT 추출본 평가 시트 자동 기입 ────────────────────────────

@app.post("/api/eval-sheet")
def eval_sheet(payload: dict = Body(...)) -> JSONResponse:
    """번역 완료된 회차를 v2 평가표(.xlsx)로 생성. 원문+MT 정렬 후 템플릿 기입."""
    load_env_into_os()
    from .evaluation.align import align, naive_align
    from .evaluation.sheet import TEMPLATES, generate_files

    work = payload.get("work")
    lang = (payload.get("lang") or "").lower()   # ko-EN 등 들어와도 ko-en 으로 매칭
    version = (payload.get("version") or "v1").lower()
    episode = payload.get("episode")
    mode = payload.get("output_mode", "single")
    model = payload.get("model") or "mock"

    if not work or not episode:
        return JSONResponse({"ok": False, "error": "작품/회차가 필요합니다."}, status_code=400)
    if lang not in TEMPLATES:
        return JSONResponse({"ok": False,
            "error": f"'{lang}' 언어쌍은 평가표 템플릿이 없습니다. (한일 ko-ja / 한영 ko-en 만 지원)"},
            status_code=400)

    ep_path = _episode_path(work, episode)
    if not ep_path:
        return JSONResponse({"ok": False, "error": "회차 원문을 찾을 수 없습니다."}, status_code=400)
    source = read_text(str(ep_path))

    final_path = _work_dir(work) / "output" / Path(episode).stem / "final.txt"
    if not final_path.exists():
        return JSONResponse({"ok": False,
            "error": "이 회차의 번역 결과(final.txt)가 없습니다. 먼저 번역하세요."}, status_code=400)
    mt = final_path.read_text(encoding="utf-8")

    need = required_key_for(model)
    if model != "mock" and need and not os.environ.get(need):
        return JSONResponse({"ok": False,
            "error": f"{need} 가 설정되지 않았습니다."}, status_code=400)

    try:
        aligned = naive_align(source, mt) if model == "mock" else align(source, mt, model=model)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"정렬 실패: {exc}"}, status_code=400)

    data = {
        "work_id": work,
        "work_title": payload.get("work_title", work),
        "language_pair": lang,
        "prompt_version": payload.get("prompt_version", version),
        "model_name": model,
        "chapter_range": payload.get("chapter_range", Path(episode).stem),
        "extraction_date": payload.get("extraction_date") or date.today().isoformat(),
        "source_sentences": aligned["source_sentences"],
        "mt_sentences": aligned["mt_sentences"],
        "scene_breakdown": aligned.get("scene_breakdown", []),
        "output_mode": mode,
        "samples_per_scene": int(payload.get("samples_per_scene", 3) or 3),
    }
    try:
        res = generate_files(data)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"평가표 생성 실패: {exc}"}, status_code=400)

    out_dir = _work_dir(work) / "eval" / Path(episode).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    stem = Path(episode).stem
    for fname, blob in res.files:
        (out_dir / fname).write_bytes(blob)
        files.append({
            "filename": fname,
            "size_kb": round(len(blob) / 1024),
            "url": f"/api/eval-download?work={quote(work)}&episode={quote(stem)}&name={quote(fname)}",
        })
    return JSONResponse({"ok": True, "files": files, "warnings": res.warnings,
                         "dir": str(out_dir)})


@app.get("/api/eval-download")
def eval_download(work: str, episode: str, name: str):
    """생성된 평가표 파일 다운로드."""
    try:
        fp = _work_dir(work) / "eval" / _safe_seg(episode) / _safe_seg(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not fp.exists():
        return JSONResponse({"error": "파일을 찾을 수 없습니다."}, status_code=404)
    return FileResponse(
        str(fp), filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/export-docx")
def export_docx(payload: dict = Body(...)) -> JSONResponse:
    """최종 번역 결과를 Word(.docx) 로 저장하고 다운로드 URL 을 반환."""
    import re as _re

    import docx  # python-docx

    work = payload.get("work")
    episode = payload.get("episode")
    text = payload.get("text") or ""
    if not work or not episode:
        return JSONResponse({"ok": False, "error": "작품/회차가 필요합니다."}, status_code=400)
    stem = Path(episode).stem
    safe_work = _re.sub(r'[\\/:*?"<>|]', "", str(work)).strip() or "WORK"
    fname = f"{safe_work}_{stem}.docx"
    try:
        out_dir = _work_dir(work) / "output" / _safe_seg(stem)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = docx.Document()
    _add_doc_paragraphs(doc, text, lang=payload.get("lang"), work=work, episode=stem)
    doc.save(str(out_dir / fname))
    return JSONResponse({"ok": True, "filename": fname, "dir": str(out_dir),
        "url": f"/api/export-docx-download?work={quote(work)}&episode={quote(stem)}&name={quote(fname)}"})


@app.get("/api/export-docx-download")
def export_docx_download(work: str, episode: str, name: str):
    """생성된 최종 결과 Word 파일 다운로드."""
    try:
        fp = _work_dir(work) / "output" / _safe_seg(episode) / _safe_seg(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not fp.exists():
        return JSONResponse({"error": "파일을 찾을 수 없습니다."}, status_code=404)
    return FileResponse(
        str(fp), filename=name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/api/export-zip")
def export_zip(payload: dict = Body(...)) -> JSONResponse:
    """한 번에 뽑은 여러 회차의 최종 결과를 ZIP(회차별 .docx 또는 .txt)으로 묶어 저장."""
    import io as _io
    import re as _re
    import zipfile
    from datetime import datetime

    import docx  # python-docx

    work = payload.get("work")
    items = payload.get("items") or []   # [{episode, text}, ...]
    fmt = (payload.get("format") or "docx").lower()
    if not work or not items:
        return JSONResponse({"ok": False, "error": "작품과 회차 결과가 필요합니다."}, status_code=400)
    safe_work = _re.sub(r'[\\/:*?"<>|]', "", str(work)).strip() or "WORK"
    try:
        out_dir = _work_dir(work) / "output"
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    out_dir.mkdir(parents=True, exist_ok=True)
    zipname = f"{safe_work}_batch_{datetime.now():%Y%m%d_%H%M}.zip"
    zpath = out_dir / zipname
    n = 0
    with zipfile.ZipFile(str(zpath), "w", zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            stem = Path(str(it.get("episode", ""))).stem or f"회차{n+1}"
            text = it.get("text") or ""
            safe_stem = _re.sub(r'[\\/:*?"<>|]', "", stem).strip() or f"회차{n+1}"
            member = f"{safe_work}_{safe_stem}"
            if fmt == "txt":
                zf.writestr(member + ".txt", text)
            else:
                doc = docx.Document()
                _add_doc_paragraphs(doc, text, lang=payload.get("lang"), work=work, episode=it.get("episode"))
                bio = _io.BytesIO()
                doc.save(bio)
                zf.writestr(member + ".docx", bio.getvalue())
            n += 1
    return JSONResponse({"ok": True, "filename": zipname, "count": n, "dir": str(out_dir),
        "url": f"/api/export-zip-download?work={quote(work)}&name={quote(zipname)}"})


@app.get("/api/export-zip-download")
def export_zip_download(work: str, name: str):
    """생성된 배치 ZIP 파일 다운로드."""
    try:
        fp = _work_dir(work) / "output" / _safe_seg(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not fp.exists() or fp.suffix.lower() != ".zip":
        return JSONResponse({"error": "파일을 찾을 수 없습니다."}, status_code=404)
    return FileResponse(str(fp), filename=name, media_type="application/zip")


@app.on_event("startup")
def _seed_data_dir() -> None:
    """데이터 폴더가 리소스와 다르면(서버 배포·패키징) 비어있을 때 기본 프롬프트를 시드."""
    if DATA_ROOT == RESOURCE_ROOT:
        return
    src = RESOURCE_ROOT / "prompts"
    dst = DATA_ROOT / "prompts"
    try:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst)
        (DATA_ROOT / "works").mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    import uvicorn

    host = os.environ.get("MTPE_HOST", "127.0.0.1")
    port = int(os.environ.get("MTPE_PORT", "8001"))
    print(f"▶ MTPE 웹 UI: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
