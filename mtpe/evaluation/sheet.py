"""MT 추출본 → v2 평가표(.xlsx) 자동 기입 엔진.

템플릿의 데이터 영역(번호·원문·MT·장면 등)만 채우고,
카테고리 드롭다운·집계 수식·조건부서식은 그대로 보존한다(openpyxl 로드→수정→저장).

언어쌍별 컬럼/시트 위치는 TEMPLATES 설정으로 관리한다.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# 언어쌍별 템플릿 구조 (실제 v2 파일 분석 기준)
TEMPLATES: dict[str, dict] = {
    "ko-en": {
        "file": "한영_v2.xlsx",
        # ③ 평가 입력
        "input_sheet": "③ 평가 입력",
        "input_start_row": 3,
        "input_last_row": 349,          # 데이터 용량(수식이 깔린 마지막 행)
        "col_num": "A",                 # 작품·문장 번호
        "col_source": "B",              # 원문
        "col_mt": "C",                  # MT본
        "col_human": None,              # 한영 템플릿엔 사람 번역본 컬럼 없음
        # D=검수본 / E~R=14개 카테고리(드롭다운) / S~X=집계(수식) / Y=비고 → 건드리지 않음
        # ④ 정성 평가
        "qual_sheet": "④ 정성 평가",
        "qual_start_row": 3,
        "qual_last_row": 33,
        "col_scene_id": "A",
        "col_scene_desc": "B",
        # ⑤ 결과 대시보드
        "dash_sheet": "⑤ 결과 대시보드",
        "cell_version": "B4",
        "cell_date": "D4",
        # ⑥ 버전 비교
        "cmp_sheet": "⑥ 버전 비교",
        "cell_cmp_header": "C4",
        # ⑧ 평가자 일치율 — 장면별 대표 샘플(원문 B / MT본 C)만 채움
        "qcheck_sheet": "⑧ 평가자 일치율",
        "qcheck_start_row": 8,
        "qcheck_last_row": 57,           # 샘플 50칸(8~57)
        "qcheck_col_source": "B",
        "qcheck_col_mt": "C",
        "qcheck_clear_cols": ["D", "E", "F", "G"],  # 평가자 입력칸(H/I/J=일치는 보존)
    },
    "ko-ja": {
        "file": "한일_v2.xlsx",
        # ③ 평가 입력 (한일: 사람번역 C, MT D, 검수 E, 카테고리 F~R 13개)
        "input_sheet": "③ 평가 입력",
        "input_start_row": 3,
        "input_last_row": 203,          # 한일 용량(201문장)
        "col_num": "A",
        "col_source": "B",
        "col_human": "C",               # 한일은 사람 번역본 컬럼 있음
        "col_mt": "D",                  # MT본이 D열
        # E=검수본 / F~R=13 카테고리(드롭다운) / S~X=집계 / Y=비고 → 건드리지 않음
        "qual_sheet": "④ 정성 평가",
        "qual_start_row": 3,
        "qual_last_row": 33,
        "col_scene_id": "A",
        "col_scene_desc": "B",
        "dash_sheet": "⑤ 결과 대시보드",
        "cell_version": "B4",
        "cell_date": "D4",
        "cmp_sheet": "⑥ 버전 비교",
        "cell_cmp_header": "C4",
        # ⑧ 평가자 일치율 — 샘플 50칸(17~66), 평가자 3명(D~I), 일치 J/K/L=수식 보존
        "qcheck_sheet": "⑧ 평가자 일치율",
        "qcheck_start_row": 17,
        "qcheck_last_row": 66,
        "qcheck_col_source": "B",
        "qcheck_col_mt": "C",
        "qcheck_clear_cols": ["D", "E", "F", "G", "H", "I"],  # 예시 평점 제거(J~L 수식 보존)
    },
}


def select_scene_samples(scenes: list, n_sentences: int, per_scene: int = 3) -> list[int]:
    """장면(scene)마다 균등 간격으로 몇 문장씩 뽑아 대표 샘플 인덱스를 만든다.

    ⑧ 평가자 일치율(보정)용 — 전체를 다 넣지 않고 각 장면을 고르게 대표하도록 추출.
    장면 정보가 없으면 전체를 한 장면으로 보고 균등 추출한다.
    """
    if n_sentences <= 0:
        return []
    if not scenes:
        scenes = [{"start_sentence_index": 0, "end_sentence_index": n_sentences - 1}]

    picked: list[int] = []
    for sc in scenes:
        s = sc.get("start_sentence_index")
        e = sc.get("end_sentence_index")
        if s is None or e is None:
            continue
        s = max(0, int(s))
        e = min(n_sentences - 1, int(e))
        if e < s:
            continue
        length = e - s + 1
        k = max(1, min(per_scene, length))
        if k >= length:
            idxs = list(range(s, e + 1))
        elif k == 1:
            idxs = [s + length // 2]                       # 1문장이면 장면 가운데
        else:
            idxs = [s + round(i * (length - 1) / (k - 1)) for i in range(k)]  # 양끝 포함 균등
        picked.extend(idxs)

    seen: set[int] = set()
    out: list[int] = []
    for i in picked:
        if 0 <= i < n_sentences and i not in seen:
            seen.add(i)
            out.append(i)
    return out


@dataclass
class EvalResult:
    files: list[tuple[str, bytes]] = field(default_factory=list)  # (filename, xlsx bytes)
    warnings: list[str] = field(default_factory=list)


def _sanitize_filename(s: str) -> str:
    """파일명에서 위험 문자 제거(한글 등은 유지)."""
    s = re.sub(r'[\\/:*?"<>|]', "", str(s)).strip()
    return s or "untitled"


def _validate(data: dict) -> list[str]:
    """필수/형식 검증. 치명적이면 ValueError, 경미하면 경고 리스트 반환."""
    warnings: list[str] = []

    lp = data.get("language_pair")
    if lp not in TEMPLATES:
        raise ValueError(f"지원하지 않는 언어쌍: {lp} (가능: {', '.join(TEMPLATES)})")

    src = data.get("source_sentences") or []
    mt = data.get("mt_sentences") or []
    if not src or not mt:
        raise ValueError("원문/MT본 문장이 비어 있습니다.")
    if len(src) != len(mt):
        raise ValueError(f"원문과 MT본 문장 수 불일치 (원문 {len(src)} / MT {len(mt)})")

    cfg = TEMPLATES[lp]
    capacity = cfg["input_last_row"] - cfg["input_start_row"] + 1
    if len(src) > capacity:
        raise ValueError(f"문장 수({len(src)})가 템플릿 용량({capacity})을 초과합니다.")

    ver = str(data.get("prompt_version") or "")
    if not re.fullmatch(r"v\d+(\.\d+)?", ver):
        warnings.append(f"prompt_version 형식이 'v1' 또는 'v1.2'와 다릅니다: '{ver}'")

    scenes = data.get("scene_breakdown") or []
    if not scenes:
        warnings.append("scene_breakdown 이 비어 있어 ④ 정성 평가 시트는 빈 상태로 출력됩니다.")
    for sc in scenes:
        s_i = sc.get("start_sentence_index")
        e_i = sc.get("end_sentence_index")
        if s_i is None or e_i is None:
            continue
        if not (0 <= s_i <= e_i < len(src)):
            raise ValueError(f"장면 인덱스가 문장 범위를 벗어남: {sc.get('scene_id')} ({s_i}~{e_i})")
    return warnings


def fill_workbook(data: dict):
    """템플릿을 로드해 데이터 영역만 채운 openpyxl Workbook 반환."""
    cfg = TEMPLATES[data["language_pair"]]
    path = TEMPLATE_DIR / cfg["file"]
    if not path.exists():
        raise FileNotFoundError(f"템플릿이 없습니다: {path}")

    wb = openpyxl.load_workbook(str(path))  # data_only=False → 수식 보존

    # ③ 평가 입력 — A(번호)·B(원문)·C(MT) 만 입력
    ws = wb[cfg["input_sheet"]]
    src = data["source_sentences"]
    mt = data["mt_sentences"]
    human = data.get("human_translation") or []
    wid = data.get("work_id", "WORK")
    for i in range(len(src)):
        r = cfg["input_start_row"] + i
        ws[f"{cfg['col_num']}{r}"] = f"{wid}-{i + 1:03d}"
        ws[f"{cfg['col_source']}{r}"] = src[i]
        ws[f"{cfg['col_mt']}{r}"] = mt[i]
        if cfg["col_human"] and i < len(human):
            ws[f"{cfg['col_human']}{r}"] = human[i]

    # ④ 정성 평가 — A(장면ID)·B(장면설명)
    qws = wb[cfg["qual_sheet"]]
    for i, sc in enumerate(data.get("scene_breakdown") or []):
        r = cfg["qual_start_row"] + i
        if r > cfg["qual_last_row"]:
            break
        qws[f"{cfg['col_scene_id']}{r}"] = sc.get("scene_id", "")
        qws[f"{cfg['col_scene_desc']}{r}"] = sc.get("scene_description", "")

    # ⑤ 결과 대시보드 — 프롬프트 버전 / 평가 일자
    dws = wb[cfg["dash_sheet"]]
    dws[cfg["cell_version"]] = data.get("prompt_version", "")
    dws[cfg["cell_date"]] = _as_date(data.get("extraction_date"))

    # ⑥ 버전 비교 — 현재 버전 헤더
    cws = wb[cfg["cmp_sheet"]]
    cws[cfg["cell_cmp_header"]] = f"{data.get('prompt_version', '')} (현재)"

    # ⑧ 평가자 일치율 — 장면별 대표 샘플(원문/MT본)만 채움. 평가자 채점칸은 비우고 수식은 보존.
    if cfg.get("qcheck_sheet"):
        qws = wb[cfg["qcheck_sheet"]]
        per_scene = int(data.get("samples_per_scene", 3) or 3)
        picked = select_scene_samples(
            data.get("scene_breakdown") or [], len(src), per_scene
        )
        cap = cfg["qcheck_last_row"] - cfg["qcheck_start_row"] + 1
        picked = picked[:cap]
        for slot in range(cap):
            r = cfg["qcheck_start_row"] + slot
            if slot < len(picked):
                idx = picked[slot]
                qws[f"{cfg['qcheck_col_source']}{r}"] = src[idx]
                qws[f"{cfg['qcheck_col_mt']}{r}"] = mt[idx]
            else:
                # 미사용 샘플 행: 템플릿 예시 문장 잔재 제거
                qws[f"{cfg['qcheck_col_source']}{r}"] = None
                qws[f"{cfg['qcheck_col_mt']}{r}"] = None
            # 평가자 입력칸(예시 평점 포함) 비우기 — 일치 수식 칸은 절대 건드리지 않음
            for col in cfg.get("qcheck_clear_cols", []):
                qws[f"{col}{r}"] = None

    return wb


def _as_date(v):
    if isinstance(v, (datetime, date)):
        return v
    return v  # 문자열 등은 그대로 기입


def _to_bytes(wb) -> bytes:
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def generate_files(data: dict) -> EvalResult:
    """평가표(.xlsx) 단일 파일을 생성해 반환.

    2명 이상 평가는 운영측에서 이 파일을 복제·파일명 수정해 배포한다(평가자별 분할 안 함).
    """
    warnings = _validate(data)
    wb = fill_workbook(data)
    payload = _to_bytes(wb)

    wid = _sanitize_filename(data.get("work_id", "WORK"))
    ver = _sanitize_filename(data.get("prompt_version", "v1"))
    base = f"{wid}_{ver}_평가표"

    result = EvalResult(warnings=warnings)
    result.files.append((f"{base}.xlsx", payload))
    return result
