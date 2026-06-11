"""실제 LLM 호출 없이 번들 로딩과 파이프라인 오케스트레이션을 검증한다."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mtpe import bundle, pipeline  # noqa: E402

CONFIG = ROOT / "config.yaml"


def test_extract_tag():
    text = "잡담 <o>{\"a\": 1}</o> 뒤"
    assert pipeline.extract_output(text, "tag:o") == '{"a": 1}'
    assert pipeline.extract_output("그대로", None) == "그대로"


def test_load_bundle_latest():
    b = bundle.load_bundle(ROOT / "prompts", "장저견", "zh-ko", None)
    assert b.version == "v1"
    assert [s.id for s in b.steps] == [1, 2, 3, 4, 5]
    # 마지막 단계가 최종 산출물로 표시
    assert b.steps[-1].is_final
    # STEP1 은 <o> 추출 규칙
    assert b.steps[0].extract == "tag:o"


def test_build_prompt_auto_append():
    step = bundle.Step(id=3, name="초벌", file="step3.txt", inputs=["source", "step2"])
    artifacts = {"source": "原文", "step2": "분석결과", "glossary": "TB"}
    labels = {"source": "원문", "step2": "STEP 2 분석"}
    out = pipeline.build_prompt("지시문", step, artifacts, labels)
    assert "지시문" in out
    assert "### 원문" in out and "原文" in out
    assert "### STEP 2 분석" in out and "분석결과" in out
    # inputs 에 없는 glossary 는 첨부되지 않음
    assert "TB" not in out


def test_chain_uses_named_artifacts(monkeypatch):
    calls = []

    def fake_call(model, system_prompt, user_prompt, temperature, max_tokens):
        calls.append({"model": model, "user": user_prompt})
        n = len(calls)
        # STEP1 은 <o> 로 감싸 추출 동작 확인
        return f"<o>OUT{n}</o>" if n == 1 else f"OUT{n}"

    monkeypatch.setattr(pipeline, "call_llm", fake_call)

    pipe = pipeline.Pipeline.from_config(CONFIG, work="장저견", lang="zh-ko")
    results = pipe.run(source="SRC", glossary="GLOS")

    assert len(results) == 5
    # STEP1 출력은 <o> 안만 추출되어 OUT1 으로 저장
    assert results[0].output == "OUT1"
    assert results[0].raw == "<o>OUT1</o>"

    # STEP3 (calls[2]) 는 source + step2 를 받음 (step1 은 안 받음)
    s3 = calls[2]["user"]
    assert "SRC" in s3 and "OUT2" in s3 and "OUT1" not in s3

    # STEP5 (calls[4]) 는 source + step2 + step4 + step3 를 받음
    s5 = calls[4]["user"]
    assert "OUT2" in s5 and "OUT4" in s5 and "OUT3" in s5

    # 최종 산출물 = STEP5 출력
    assert pipe.final_output == "OUT5"


def test_model_override(monkeypatch):
    monkeypatch.setattr(pipeline, "call_llm", lambda **kw: "X")
    pipe = pipeline.Pipeline.from_config(CONFIG, work="장저견", lang="zh-ko")
    results = pipe.run(source="s", glossary="", model_override="gpt-4o")
    assert all(r.model == "gpt-4o" for r in results)
