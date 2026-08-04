"""
api.py
------
소설 분권 기능을 HTTP API 로 노출한다(n8n 등 자동화 연동용).

GUI 없이 processor.py 를 그대로 재사용하며, 파일을 받아 분권/집계하고
결과(회차별 글자수 + 분권 파일 zip)를 JSON 으로 돌려준다.

엔드포인트
- GET  /health              : 상태 확인(인증 불필요) - 터널/연결 테스트용
- POST /count               : 파일 전체 글자수/단어수(Word 방식)
- POST /split               : 파일 분권 + 회차별 집계 + 분권 zip(base64)
- POST /platform/episodes   : 네이버 시리즈 URL -> 회차 목록 JSON

인증: 모든 엔드포인트(/health 제외)는 헤더 X-API-Key 로 토큰을 확인한다.
      토큰은 환경변수 SPLITTER_API_TOKEN 로 지정하며, 없으면 파일
      splitter_api_token.txt 에 자동 생성/저장한다(재시작해도 동일 토큰).

실행: python run_api.py   (기본 0.0.0.0:8000)
"""

from __future__ import annotations

import base64
import io
import os
import secrets
import tempfile
import zipfile
from dataclasses import asdict
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from .platform_fetcher import PlatformError, PlatformFetcher
from .processor import Processor, SplitMode, SplitOptions
from .utils import is_supported_file
from .web import INDEX_HTML

app = FastAPI(title="소설 분권 API", version="1.0.0")


@app.get("/", response_class=HTMLResponse)
def index():
    """웹 UI(사람용 브라우저 페이지)를 제공한다. API 와 같은 서버가 함께 서빙."""
    return INDEX_HTML

_processor = Processor()
_MAX_BYTES = 50 * 1024 * 1024  # 업로드 파일 최대 50MB


# ---------------------------------------------------------------------------- #
# 인증
# ---------------------------------------------------------------------------- #
def _load_token() -> str:
    """API 토큰을 환경변수 또는 로컬 파일에서 읽고, 없으면 생성한다."""
    env = os.environ.get("SPLITTER_API_TOKEN")
    if env:
        return env.strip()
    token_file = os.path.join(os.getcwd(), "splitter_api_token.txt")
    if os.path.exists(token_file):
        with open(token_file, encoding="utf-8") as f:
            return f.read().strip()
    token = secrets.token_urlsafe(24)
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(token)
    return token


API_TOKEN = _load_token()


def _check_auth(x_api_key: Optional[str]) -> None:
    """X-API-Key 헤더를 검증한다. 틀리면 401."""
    if not x_api_key or not secrets.compare_digest(x_api_key, API_TOKEN):
        raise HTTPException(status_code=401, detail="인증 실패: 올바른 X-API-Key 헤더가 필요합니다.")


# ---------------------------------------------------------------------------- #
# 공통 유틸
# ---------------------------------------------------------------------------- #
def _build_options(
    mode: str,
    separator: str,
    include_separator: bool,
    remove_separator: bool,
    count_limit: int,
    char_count_with_spaces: bool,
    number_position: str,
    overwrite: bool,
    output_dir: str,
) -> SplitOptions:
    """폼 값으로 SplitOptions 를 구성한다."""
    mode_map = {
        "separator": SplitMode.SEPARATOR,
        "char_count": SplitMode.CHAR_COUNT,
        "word_count": SplitMode.WORD_COUNT,
    }
    if mode not in mode_map:
        raise HTTPException(
            status_code=400,
            detail="mode 는 separator / char_count / word_count 중 하나여야 합니다.",
        )
    return SplitOptions(
        mode=mode_map[mode],
        separator=separator,
        include_separator=include_separator,
        remove_separator=remove_separator,
        count_limit=count_limit,
        char_count_with_spaces=char_count_with_spaces,
        number_position=number_position,
        overwrite=overwrite,
        custom_output_dir=output_dir,
    )


async def _save_upload(file: UploadFile, dest_dir: str) -> str:
    """업로드 파일을 dest_dir 에 원래 이름으로 저장하고 경로를 반환한다."""
    filename = os.path.basename(file.filename or "input")
    if not is_supported_file(filename):
        raise HTTPException(status_code=400, detail="지원하지 않는 파일입니다(docx, txt 만 가능).")
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다(최대 50MB).")
    path = os.path.join(dest_dir, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _zip_dir(dir_path: str) -> bytes:
    """디렉터리 안의 파일들을 zip 바이트로 묶는다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(dir_path)):
            full = os.path.join(dir_path, name)
            if os.path.isfile(full):
                zf.write(full, arcname=name)
    return buf.getvalue()


# ---------------------------------------------------------------------------- #
# 엔드포인트
# ---------------------------------------------------------------------------- #
@app.get("/health")
def health():
    """상태 확인(인증 불필요)."""
    return {"status": "ok", "service": "novel-splitter-api"}


@app.post("/count")
async def count(
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(default=None),
):
    """파일 전체 분량(글자수/단어수/줄수)을 계산한다."""
    _check_auth(x_api_key)
    with tempfile.TemporaryDirectory() as tmp:
        path = await _save_upload(file, tmp)
        doc = _processor.analyze(path)
        counts = _processor.summarize(doc)
    return {"filename": os.path.basename(path), "counts": asdict(counts)}


@app.post("/split")
async def split(
    file: UploadFile = File(...),
    mode: str = Form("separator"),
    separator: str = Form(""),
    include_separator: bool = Form(True),
    remove_separator: bool = Form(False),
    count_limit: int = Form(5000),
    char_count_with_spaces: bool = Form(True),
    number_position: str = Form("suffix"),
    overwrite: bool = Form(True),
    include_zip: bool = Form(True),
    x_api_key: Optional[str] = Header(default=None),
):
    """
    파일을 분권하고 회차별 집계 + 분권 파일 zip(base64)을 반환한다.

    반환 JSON
    - source        : 원본 파일명
    - output_count  : 생성된 분권 수
    - total         : 전체 합계(글자수/단어수/줄수)
    - chunks[]      : 분권별 {index, filename, title, counts}
    - zip_base64    : 분권 파일들을 담은 zip (include_zip=false 면 생략)
    """
    _check_auth(x_api_key)
    with tempfile.TemporaryDirectory() as tmp:
        in_dir = os.path.join(tmp, "in")
        out_base = os.path.join(tmp, "out")
        os.makedirs(in_dir, exist_ok=True)
        os.makedirs(out_base, exist_ok=True)

        path = await _save_upload(file, in_dir)
        options = _build_options(
            mode, separator, include_separator, remove_separator,
            count_limit, char_count_with_spaces, number_position,
            overwrite, out_base,
        )
        try:
            result = _processor.process_file(path, options)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        chunks = [
            {
                "index": c.index,
                "filename": c.filename,
                "title": c.title,
                "counts": asdict(c.counts),
                "skipped": c.skipped,
            }
            for c in result.chunks
        ]
        payload = {
            "source": os.path.basename(path),
            "output_count": len(result.chunks),
            "total": asdict(result.total),
            "chunks": chunks,
        }
        if include_zip:
            payload["zip_filename"] = f"{os.path.splitext(os.path.basename(path))[0]}.zip"
            payload["zip_base64"] = base64.b64encode(_zip_dir(result.output_dir)).decode("ascii")

    return JSONResponse(payload)


@app.post("/platform/episodes")
async def platform_episodes(
    url: str = Form(...),
    x_api_key: Optional[str] = Header(default=None),
):
    """네이버 시리즈 등 URL 의 공개 회차 목록(번호/제목)을 가져온다."""
    _check_auth(x_api_key)
    try:
        result = PlatformFetcher().fetch(url)
    except PlatformError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "platform": result.platform,
        "work_title": result.work_title,
        "total_count": result.total_count,
        "episodes": [{"no": e.no, "title": e.title} for e in result.episodes],
    }
