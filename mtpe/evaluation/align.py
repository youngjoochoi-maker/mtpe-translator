"""LLM 정렬 단계 — 원문+MT 를 문장 단위로 1:1 정렬하고 장면을 분할한다.

평가표(③·④) 기입에 필요한 source_sentences / mt_sentences / scene_breakdown 을 만든다.
출력은 <o>…</o> 안의 JSON 으로 받아 파싱한다(기존 추출 메커니즘 재사용).
"""

from __future__ import annotations

import json
import re

from ..llm import call_llm
from ..pipeline import extract_output


def naive_align(source: str, mt: str) -> dict:
    """키 없이 쓰는 단순 정렬(모의 모드/폴백). 문장부호로 분리해 1:1 로 맞춘다.

    실제 품질은 LLM 정렬(align)이 담당. 이건 흐름 확인·테스트용.
    """
    def split(text):
        parts = re.split(r"(?<=[.。．!?！？\n])\s+", (text or "").strip())
        return [p.strip() for p in parts if p.strip()]

    src = split(source)
    mts = split(mt)
    n = max(len(src), len(mts), 1)
    src += [""] * (n - len(src))
    mts += [""] * (n - len(mts))
    scenes = [{
        "scene_id": "장면-01", "scene_description": "(모의) 전체 장면",
        "start_sentence_index": 0, "end_sentence_index": n - 1,
    }]
    return {"source_sentences": src, "mt_sentences": mts, "scene_breakdown": scenes}

ALIGN_SYSTEM = "당신은 번역 정렬 도우미입니다. 지시한 JSON 형식만 출력합니다."

ALIGN_PROMPT = """[원문]과 [번역(MT)]을 문장 단위로 1:1 정렬하고 장면을 분할하라.

규칙:
- 원문을 문장 단위로 나눈다(source_sentences).
- 각 원문 문장에 대응하는 번역 문장을 매칭한다(mt_sentences). 번역이 합쳐졌거나 나뉘었으면
  원문 문장 수와 같아지도록 적절히 분할/병합해 **1:1, 같은 길이**로 맞춘다.
- 장면(scene)을 의미 단위로 분할하고, 각 장면의 시작/끝 문장 인덱스(0-기준, 포함)를 부여한다.
- 아래 JSON 을 <o> 와 </o> 사이에만 출력한다. 설명·머리말 금지.

출력 형식:
<o>
{
  "source_sentences": ["원문문장1", "원문문장2"],
  "mt_sentences": ["번역문장1", "번역문장2"],
  "scene_breakdown": [
    {"scene_id": "장면-01", "scene_description": "장면 요약", "start_sentence_index": 0, "end_sentence_index": 1}
  ]
}
</o>

[원문]
{{SOURCE}}

[번역(MT)]
{{MT}}
"""


def align(source: str, mt: str, *, model: str, llm=None,
          temperature: float = 0.0, max_tokens: int = 8192) -> dict:
    """원문/MT 를 정렬해 {source_sentences, mt_sentences, scene_breakdown} 반환.

    llm 이 주어지면 call_llm 대신 그 함수로 호출한다(모의 모드/테스트).
    """
    fn = llm or call_llm
    user = ALIGN_PROMPT.replace("{{SOURCE}}", source or "").replace("{{MT}}", mt or "")
    raw = fn(
        model=model, system_prompt=ALIGN_SYSTEM, user_prompt=user,
        temperature=temperature, max_tokens=max_tokens,
    )
    text = extract_output(raw, "tag:o").strip()
    # JSON 앞뒤 군더더기(코드펜스 등) 제거
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"): text.rfind("}") + 1]
    data = json.loads(text)

    src = data.get("source_sentences") or []
    mts = data.get("mt_sentences") or []
    if len(src) != len(mts):
        raise ValueError(f"정렬 결과 길이 불일치 (원문 {len(src)} / MT {len(mts)})")
    data.setdefault("scene_breakdown", [])
    return data
