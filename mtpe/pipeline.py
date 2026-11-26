"""번들 기반 단계 체인 오케스트레이션.

각 단계는 meta.yaml 의 inputs 에 명시된 산출물(source/glossary/step1..N)을
프롬프트 뒤에 '[입력 자료]'로 자동 첨부받는다. 프롬프트에 {{TOKEN}} 자리표시자가
있으면 자동 첨부 대신 토큰 치환 방식을 사용한다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from .bundle import Bundle, Step, load_bundle
from .llm import EmptyResponseError, TruncatedResponseError, call_llm

_SEP = "─" * 28


@dataclass
class StageResult:
    id: int
    name: str
    model: str
    output: str        # extract 규칙 적용 후 (다음 단계로 전달되는 값)
    raw: str           # LLM 원응답
    user_prompt: str = ""  # 실제로 보낸 프롬프트(튜닝 화면에서 확인용)
    skipped: bool = False  # 프롬프트가 비어 LLM 호출 없이 건너뛴 단계
    error: str = ""        # 모델 빈 응답 등으로 실패(직전 결과로 대체됨)
    seconds: float = 0.0   # 이 단계 소요 시간(초)
    in_tokens: int = 0     # 입력 토큰(추정)
    out_tokens: int = 0    # 출력 토큰(추정)
    cost: float = 0.0      # 예상 비용(USD)


def _pick_translation_field(data):
    """dict 에서 '번역문' 필드를 고른다(없으면 None). 분석용 JSON 은 건드리지 않도록 보수적."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("final_translation"), str):
        return data["final_translation"]
    for k, v in data.items():
        if isinstance(v, str) and str(k).lower().endswith("translation"):
            return v
    if isinstance(data.get("translation"), str):
        return data["translation"]
    for k in ("translated_text", "translated", "target_text", "target", "output", "result", "text", "final"):
        if isinstance(data.get(k), str) and data[k].strip():
            return data[k]
    return None


def _lenient_json(text: str):
    """모델이 틀을 조금 어겨도 JSON 객체를 찾아 파싱한다. 실패 시 None.
    - 앞뒤 설명 문장 / ```json 펜스 / 끝 쉼표 / 중괄호 바깥 잡문 허용.
    - 닫는 중괄호가 없거나 값이 중간에서 잘려도(모델이 </o>·}·닫는 따옴표를 빠뜨림) 복구 시도."""
    if not text:
        return None
    t = text.strip()
    # 코드펜스 제거
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t).strip()
    t = re.sub(r"\s*```$", "", t).strip()
    i = t.find("{")
    if i < 0:
        return None
    j = t.rfind("}")
    cands = []
    if j > i:                                   # 정상: 첫 { ~ 마지막 } 범위
        cand = t[i:j + 1]
        cands += [cand, re.sub(r",\s*([}\]])", r"\1", cand)]  # 끝 쉼표 제거 재시도
    # 잘린 객체 복구: 닫는 } 또는 "} 를 붙여본다(값이 중간에서 끊긴 경우 포함).
    tail = t[i:].rstrip()
    cands += [tail + "}", tail + '"}', tail.rstrip(",") + "}"]
    for base in cands:
        # 그대로, 그리고 문자열 안 생줄바꿈을 이스케이프한 버전 둘 다 시도
        for attempt in (base, re.sub(r'(?<!\\)\n', r'\\n', base)):
            try:
                return json.loads(attempt)
            except Exception:  # noqa: BLE001
                continue
    return None


def _salvage_translation_field(text: str):
    """닫히지 않은/깨진 JSON 에서도 '번역문' 필드 값만 직접 건져낸다(최후 수단).
    JSON 파싱이 끝내 실패할 때, "...translation": "..." 모양을 정규식으로 찾아
    따옴표 안 내용을 이스케이프 해제해 돌려준다. 못 찾으면 None."""
    m = re.search(
        r'"(?:[a-z_]*translation|translated_text|translated|target_text|target|final|output|result|text)"\s*:\s*"',
        text, re.I)
    if not m:
        return None
    rest = text[m.end():]
    buf, k = [], 0
    while k < len(rest):                         # 이스케이프를 존중하며 닫는 따옴표까지 읽는다
        c = rest[k]
        if c == "\\" and k + 1 < len(rest):
            buf.append(rest[k:k + 2]); k += 2; continue
        if c == '"':
            break
        buf.append(c); k += 1
    raw = "".join(buf)
    try:
        val = json.loads('"' + raw + '"')       # 표준 JSON 이스케이프 해제
    except Exception:  # noqa: BLE001
        val = (raw.replace('\\n', '\n').replace('\\t', '\t')
                  .replace('\\"', '"').replace('\\\\', '\\'))
    return val.strip() if val and val.strip() else None


class ExtractError(RuntimeError):
    """출력 형식 불일치로 번역문을 꺼내지 못함."""


def _auto_clean(text: str) -> str:
    """출력 추출 규칙이 없을 때의 안전망.
    모델이 번역문을 ```json / <o></o> / 그 둘을 겹쳐서 / 닫는 태그 없이 등 '어떤 껍데기'로 감싸도,
    그 안에 번역문 필드를 가진 JSON 이 있으면 값만 깔끔히 꺼낸다(이스케이프 \n → 실제 줄바꿈).
    JSON 이 아니면 <o> 래퍼·코드펜스만 벗겨 통과하고, 그조차 없으면 원문 그대로 둔다.
    → 번들에 추출 규칙이 없어도 JSON 껍데기가 새는 '서식 오류'를 어떤 언어·어떤 포장에서든 막는다.
      (모델이 회차마다 포장 방식을 바꿔도 안쪽 JSON 만 보고 처리하므로 복불복이 사라진다.)"""
    if not text or not text.strip():
        return text
    # 1) 껍데기가 무엇이든 우선 안쪽 JSON 의 번역문 필드를 꺼낸다.
    #    _lenient_json 이 { ~ } 범위를 스스로 찾으므로 ```json·<o>·둘 다·끝쉼표·여는태그만 등에 영향받지 않는다.
    data = _lenient_json(text)
    if isinstance(data, dict):
        val = _pick_translation_field(data)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # 1-b) JSON 복구조차 실패(심하게 잘림)해도, 번역문 필드만 정규식으로 직접 건져본다.
    if "{" in text and re.search(r'"[a-z_]*(?:translation|target|output|result|text|final)"\s*:', text, re.I):
        sv = _salvage_translation_field(text)
        if sv:
            return sv
    # 2) JSON 이 아니면 래퍼/코드펜스만 제거해 통과(평문 번역이 <o> 안에 든 경우 등).
    m = re.search(r"<\s*o\s*>(.*?)<\s*/\s*o\s*>", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    stripped = re.sub(r"<\s*/?\s*o\s*>", "", text, flags=re.I)          # <o> / </o> 어디에 있든 제거
    stripped = re.sub(r"^\s*```[a-zA-Z]*\s*", "", stripped)             # 여는 ```json 펜스
    stripped = re.sub(r"\s*```\s*$", "", stripped).strip()             # 닫는 ``` 펜스
    return stripped if stripped and stripped != text.strip() else text


_ESC_MAP = {"n": "\n", "r": "", "t": "\t", '"': '"', "'": "'", "\\": "\\", "/": "/"}


def _undo_double_escape(text: str) -> str:
    """모델이 번역문을 한 번 더 이스케이프해 보낸 경우를 풀어 준다.
    (예: JSON 값 안에 '\\n' 을 넣어, 파싱 후에도 줄바꿈이 '\\n' 글자로 남고 대사 따옴표가 '\\"' 로 남는 경우
     → Word 로 저장하면 전체가 한 문단이 됨.)
    실제 줄바꿈보다 '\\n' 글자가 더 많을 때만(3개 이상) 손대므로, 정상 번역문은 그대로 둔다."""
    if not text or "\\" not in text:
        return text
    lit = text.count("\\n")
    if lit < 3 or lit <= text.count("\n"):
        return text
    out = re.sub(r'\\(["\'\\/nrt])', lambda m: _ESC_MAP[m.group(1)], text)
    return out.strip()


def extract_output(text: str, rule: str | None) -> str:
    """extract 규칙을 적용하고, 번역문 추출(json/자동)일 때는 이중 이스케이프도 풀어 준다.
    분석용 tag: 추출(1단계 JSON 등)은 건드리지 않는다."""
    out = _extract_output_raw(text, rule)
    if rule and rule.startswith("tag:"):
        return out
    return _undo_double_escape(out)


def _extract_output_raw(text: str, rule: str | None) -> str:
    """extract 규칙 적용.

    'tag:NAME'  → <NAME>...</NAME> 안의 내용만 반환.
    'json:FIELD'→ <o> 안(없으면 전체)에서 JSON 을 파싱해 FIELD 값만 반환
                  (프롬프트가 <o>{JSON}</o> 로 답할 때 특정 필드[번역문]만 깔끔히 추출).
    파싱 실패 시엔 원본을 그대로 반환(모의 모드 등에서도 흐름 유지).
    규칙이 없으면 _auto_clean 안전망을 거쳐, JSON 껍데기가 새는 서식오류를 자동 방지.
    """
    if not rule:
        return _auto_clean(text)
    if rule.startswith("tag:"):
        tag = rule.split(":", 1)[1].strip()
        m = re.search(rf"<\s*{tag}\s*>(.*?)<\s*/\s*{tag}\s*>", text, re.S | re.I)
        return m.group(1).strip() if m else text.strip()
    if rule.startswith("json:"):
        field = rule.split(":", 1)[1].strip()
        m = re.search(r"<o>(.*?)</o>", text, re.S | re.I)
        inner = (m.group(1) if m else text).strip()
        data = _lenient_json(inner)
        if data is None and m is None:
            data = _lenient_json(text)
        if isinstance(data, dict):
            val = data.get(field)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if val is not None and not isinstance(val, (dict, list)):
                return str(val)
            alt = _pick_translation_field(data)   # 필드 이름이 다를 때
            if isinstance(alt, str) and alt.strip():
                return alt.strip()
        # JSON 이 아니고 <o> 안에 평문 번역이 들어 있으면 그걸 사용
        if m and inner and not inner.lstrip().startswith("{"):
            return inner
        # 심하게 잘린 JSON 이면 번역문 필드만 직접 건져 마지막으로 구제
        sv = _salvage_translation_field(text)
        if sv:
            return sv
        raise ExtractError(f"출력 형식 불일치: '{field}' 필드를 찾지 못함 (응답 앞부분: {text.strip()[:80]!r})")
    return text


def _count_tok(model: str, text: str) -> int:
    """토큰 수 추정. litellm 우선, 실패하거나 0 이면 문자 기반 폴백(대략 1토큰≈2자).
    → 어떤 모델이든 0 이 아닌 합리적인 값을 돌려줘 예상이 0 으로 뜨는 사고를 막는다."""
    if not text:
        return 0
    try:
        import litellm
        n = int(litellm.token_counter(model=model, text=text) or 0)
        if n > 0:
            return n
    except Exception:
        pass
    return max(1, len(text) // 2)


def estimate_usage(model: str, in_text: str, out_text: str):
    """입력/출력 토큰과 예상 비용(USD)을 추정. 토큰은 폴백까지 있어 0 이 안 나온다.
    비용은 모델 단가를 모르면 0(무료/미상)."""
    it = _count_tok(model, in_text or "")
    ot = _count_tok(model, out_text or "")
    cost = 0.0
    try:
        import litellm
        pc, cc = litellm.cost_per_token(model=model, prompt_tokens=it, completion_tokens=ot)
        cost = float(pc or 0) + float(cc or 0)
    except Exception:
        cost = 0.0
    return it, ot, cost


def estimate_pipeline_usage(pipe, source: str, glossary: str, model: str):
    """실행 전 예상. 실제 단계 구성(시스템프롬프트 + 단계지시문 + 원문 + 설정집(TB)
    + 누적 단계출력)을 그대로 모사해 입력/출력 토큰과 실제 호출 수를 계산한다.
    LLM 은 호출하지 않는다. 반환: (입력토큰, 출력토큰, 호출수)."""
    sys_t = _count_tok(model, getattr(pipe, "system_prompt", "") or "")
    src_t = _count_tok(model, source or "")
    glo_t = _count_tok(model, glossary or "(설정집 없음)")
    hs = (getattr(pipe.bundle, "house_style", "") or "")
    hs_t = _count_tok(model, hs)
    art = {
        "source": src_t,
        "glossary": glo_t,
        "source_lang": _count_tok(model, getattr(pipe.bundle, "source_lang", "") or ""),
        "target_lang": _count_tok(model, getattr(pipe.bundle, "target_lang", "") or ""),
    }
    in_total = out_total = calls = 0
    for step in pipe.bundle.steps:
        instr = pipe.bundle.step_text(step)
        if not (instr or "").strip():
            # 빈 단계는 LLM 호출 없이 직전 결과를 통과 → 토큰/호출 없음
            art[f"step{step.id}"] = art.get(f"step{step.id}", src_t)
            continue
        calls += 1
        step_in = sys_t + _count_tok(model, instr)
        if hs.strip() and pipe.bundle.house_style_applies(step):
            step_in += hs_t
        for key in step.inputs:
            step_in += art.get(key, 0)
        # 각 단계 출력 ≈ 원문의 0.7배 (QA 실측 2026-09: 5단계 합산 출력이 원문×5의 약 35~40% —
        # 분석 단계는 짧고, 번역 단계도 원문보다 약간 짧게 나옴)
        step_out = int(src_t * 0.7)
        in_total += step_in
        out_total += step_out
        art[f"step{step.id}"] = step_out
    return in_total, out_total, calls


_HS_HEADER = "[공통 규칙(HOUSE STYLE) — 아래 규칙을 반드시 준수]"


def build_prompt(
    instruction: str,
    step: Step,
    artifacts: dict,
    labels: dict,
    inject_house_style: bool = False,
) -> str:
    """단계 프롬프트를 완성한다.

    - 프롬프트에 {{KEY}} 토큰이 있으면 치환 모드 (artifacts 키를 대문자로 매칭).
      · {{HOUSE_STYLE}} 토큰이 있으면 그 자리에 공통 규칙이 치환된다.
    - 없으면 자동 첨부 모드: (공통 규칙 →) step.inputs 순서대로 블록을 덧붙인다.
    - inject_house_style=True 이고 공통 규칙이 있으면 지시문 바로 뒤에 규칙 블록을 넣는다.
    """
    house_style = (artifacts.get("house_style") or "") if inject_house_style else ""

    if "{{" in instruction:
        out = instruction
        for key, val in artifacts.items():
            out = out.replace("{{" + key.upper() + "}}", str(val))
        return out

    parts = [instruction.rstrip(), ""]
    if house_style.strip():
        parts += [_SEP, _HS_HEADER, "", str(house_style), ""]
    parts += [_SEP, "[입력 자료]", ""]
    for key in step.inputs:
        val = artifacts.get(key)
        if val is None or val == "":
            continue
        label = labels.get(key, key)
        parts += [f"### {label}", str(val), ""]
    return "\n".join(parts)


class Pipeline:
    def __init__(self, config: dict, base_dir: Path, bundle: Bundle):
        self.config = config
        self.base_dir = base_dir
        self.bundle = bundle
        self.system_prompt = config.get("system_prompt", "")
        self.temperature = float(config.get("temperature", 0.3))
        self.max_tokens = int(config.get("max_tokens", 8192))
        self.default_model = config["default_model"]
        self.input_labels = config.get("input_labels", {})
        self.final_output: str = ""

    @classmethod
    def from_config(
        cls,
        config_path: str | Path,
        *,
        work: str | None = None,
        lang: str | None = None,
        version: str | None = None,
    ) -> "Pipeline":
        config_path = Path(config_path)
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        base_dir = config_path.resolve().parent

        work = work or config.get("default_work")
        lang = lang or config.get("default_lang")
        version = version if version is not None else config.get("default_version")
        if not work or not lang:
            raise ValueError("작품(work)과 언어(lang)를 지정해야 합니다.")

        # 쓰기 가능한 데이터 루트(서버 영구디스크/패키징 사용자폴더/개발 프로젝트루트)의 prompts
        from .paths import data_root

        prompts_root = data_root() / config.get("prompts_root", "prompts")
        bundle = load_bundle(prompts_root, work, lang, version)
        return cls(config, base_dir, bundle)

    def run_iter(
        self,
        source: str,
        glossary: str = "",
        *,
        model_override: str | None = None,
        llm=None,
        prompt_overrides: dict | None = None,
        seed_artifacts: dict | None = None,
        start_from: int = 0,
    ):
        """각 단계를 실행하며 StageResult 를 하나씩 yield 한다(스트리밍용).

        llm                call_llm 대신 쓸 함수(모의 모드 등)
        prompt_overrides   {단계id: 프롬프트텍스트} — 저장 안 한 편집본으로 시험
        seed_artifacts     {"step1": "...", ...} — 이전에 만든 단계 출력 재사용
        start_from         이 단계 번호부터 실행(앞 단계는 seed 로 채워 건너뜀)
        """
        llm_fn = llm or call_llm
        overrides = {int(k): v for k, v in (prompt_overrides or {}).items()}
        artifacts: dict[str, str] = {
            "source": source,
            "glossary": glossary or "(설정집 없음)",
            "source_lang": self.bundle.source_lang,
            "target_lang": self.bundle.target_lang,
            # 작품별 공통 규칙(없으면 빈 문자열 → 주입되지 않음)
            "house_style": self.bundle.house_style,
        }
        # 이번 회차 원문에 나온 TB 항목만 모아 설정집 맨 앞에 '필수 용어' 블록으로 붙인다(전체 TB 는 그대로 유지).
        self.tb_digest_count = 0
        if glossary and glossary.strip():
            try:
                from .io_utils import tb_episode_digest
                digest, n = tb_episode_digest(glossary, source, self.bundle.source_lang,
                                              self.bundle.target_lang)
                if n:
                    artifacts["glossary"] = digest + "\n\n" + glossary
                    self.tb_digest_count = n
                    from .logbuf import log as _log
                    _log(f"TB 필수 용어 {n}개 추출(이번 회차 원문 대조)")
            except Exception:  # noqa: BLE001 — 실패해도 전체 TB 로 그대로 진행
                pass
        if seed_artifacts:
            artifacts.update({k: v for k, v in seed_artifacts.items() if v is not None})
        self.final_output = ""
        last_output = ""
        last_nonempty = ""  # 빈 응답/빈 단계 시 최종을 직전 정상 결과로 대체하기 위함
        truncated_ids: list[int] = []  # 길이 제한으로 끝에서 잘린 단계들(경고 배너용)

        for step in self.bundle.steps:
            if start_from and step.id < start_from:
                continue  # 앞 단계는 seed_artifacts 로 이미 채워둠
            instruction = overrides.get(step.id)
            if instruction is None:
                instruction = self.bundle.step_text(step)
            model = model_override or step.model or self.default_model

            # 프롬프트가 비어 있으면 LLM 호출 없이 직전 결과를 그대로 통과(이 작품은 이 단계 안 씀).
            # → 빈 단계가 0자로 최종 결과를 덮어쓰는 사고를 막는다.
            if not (instruction or "").strip():
                output = last_nonempty
                artifacts[f"step{step.id}"] = output
                last_output = output
                if step.is_final:
                    self.final_output = output
                yield StageResult(
                    id=step.id, name=step.name, model=model, output=output, raw="",
                    user_prompt="(프롬프트가 비어 있어 건너뜀 — 직전 단계 결과를 그대로 유지)",
                    skipped=True,
                )
                continue

            user_prompt = build_prompt(
                instruction, step, artifacts, self.input_labels,
                inject_house_style=self.bundle.house_style_applies(step),
            )
            # 모델이 빈 응답(토큰한도/안전필터)을 주면 회차를 죽이지 않고 직전 결과로 대체 + 경고 표시.
            _t0 = time.time()
            try:
                raw = llm_fn(
                    model=model,
                    system_prompt=self.system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                try:
                    output = extract_output(raw, step.extract)
                    err = ""
                except ExtractError as _xe:
                    from .logbuf import log as _log
                    _log(f"⚠ 추출 실패  {model} · STEP{step.id} · {str(_xe)[:160]}")
                    output = last_nonempty
                    err = (f"이 단계 출력이 정해진 형식과 달라 번역문을 꺼내지 못했습니다. 직전 단계 결과를 사용합니다. "
                           f"('이 단계부터 다시'로 재시도) — {str(_xe)[:120]}")
                # 마지막 단계가 번역문 대신 '분석/검사 결과'를 내놓은 경우 → 직전 정상 결과로 대체
                if step.is_final and last_nonempty and _looks_like_analysis(output):
                    err = ("마지막 단계가 번역문 대신 분석 결과를 반환해, 직전 단계 번역문을 최종본으로 사용했습니다. "
                           "(이 단계부터 다시 실행하면 재시도)")
                    output = last_nonempty
            except TruncatedResponseError as exc:
                # 끝에서 잘렸지만 받은 데까지(부분 번역)는 살린다. 껍데기는 벗겨 본문만.
                raw = exc.partial or ""
                try:
                    output = extract_output(raw, step.extract)
                except ExtractError:
                    output = _auto_clean(raw)
                if not (output or "").strip():
                    output = last_nonempty
                truncated_ids.append(step.id)
                err = (f"이 회차는 너무 길어 모델 출력이 끝에서 잘렸습니다(STEP{step.id}). "
                       "번역 끝부분이 빠졌을 수 있어요. max_tokens 를 늘리거나 회차를 나눠 다시 실행하세요.")
            except EmptyResponseError as exc:
                raw, output, err = "", last_nonempty, str(exc)
            _sec = time.time() - _t0
            _in, _out, _cost = estimate_usage(
                model, (self.system_prompt or "") + "\n" + user_prompt, raw)

            artifacts[f"step{step.id}"] = output
            last_output = output
            if output.strip():
                last_nonempty = output
            if step.is_final:
                self.final_output = output

            yield StageResult(
                id=step.id, name=step.name, model=model, output=output, raw=raw,
                user_prompt=user_prompt, error=err,
                seconds=_sec, in_tokens=_in, out_tokens=_out, cost=_cost,
            )

        # 최종이 비었으면(마지막 단계가 빈 응답·빈 프롬프트였던 경우) 직전 정상 결과로 대체
        if not self.final_output.strip():
            self.final_output = last_nonempty or last_output
        # 어느 단계든 길이 제한으로 잘렸으면, 저장 파일(final.txt·docx)에서도 놓치지 않도록
        # 최종 결과 맨 위에 눈에 띄는 경고 한 줄을 붙인다.
        if truncated_ids and self.final_output.strip():
            tag = ", ".join(f"STEP{i}" for i in sorted(set(truncated_ids)))
            self.final_output = (
                f"⚠️ [자동경고] 이 회차는 분량이 많아 모델 출력이 끝에서 잘렸습니다({tag}). "
                "번역 끝부분이 빠졌을 수 있으니 max_tokens 를 늘리거나 회차를 나눠 다시 실행해 확인하세요. "
                "— 확인 후 이 줄은 지워도 됩니다.\n\n"
                + self.final_output
            )

    def run(
        self,
        source: str,
        glossary: str = "",
        *,
        model_override: str | None = None,
        on_stage=None,
    ) -> list[StageResult]:
        results: list[StageResult] = []
        for result in self.run_iter(
            source, glossary, model_override=model_override
        ):
            results.append(result)
            if on_stage:
                on_stage(result)
        return results


_ANALYSIS_MARKERS = ("원문 대조", "대조 검사", "| 판정 |", "|---|", "## 1.", "검사 결과", "문제 지점", "## 수정 목록", "### 검토")

def _looks_like_analysis(text: str) -> bool:
    """번역문이 아니라 마크다운 표/제목 위주의 분석 결과처럼 보이면 True."""
    t = (text or "").strip()
    if not t:
        return False
    head = t[:600]
    hits = sum(1 for m in _ANALYSIS_MARKERS if m in head)
    table_lines = sum(1 for l in t.splitlines()[:40] if l.strip().startswith("|"))
    return hits >= 2 or table_lines >= 5
