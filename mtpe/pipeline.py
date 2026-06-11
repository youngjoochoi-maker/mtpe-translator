"""번들 기반 단계 체인 오케스트레이션.

각 단계는 meta.yaml 의 inputs 에 명시된 산출물(source/glossary/step1..N)을
프롬프트 뒤에 '[입력 자료]'로 자동 첨부받는다. 프롬프트에 {{TOKEN}} 자리표시자가
있으면 자동 첨부 대신 토큰 치환 방식을 사용한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .bundle import Bundle, Step, load_bundle
from .llm import call_llm

_SEP = "─" * 28


@dataclass
class StageResult:
    id: int
    name: str
    model: str
    output: str        # extract 규칙 적용 후 (다음 단계로 전달되는 값)
    raw: str           # LLM 원응답
    user_prompt: str = ""  # 실제로 보낸 프롬프트(튜닝 화면에서 확인용)


def extract_output(text: str, rule: str | None) -> str:
    """extract 규칙 적용. 'tag:NAME' → <NAME>...</NAME> 안의 내용만 반환."""
    if not rule:
        return text
    if rule.startswith("tag:"):
        tag = rule.split(":", 1)[1].strip()
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
        return m.group(1).strip() if m else text.strip()
    return text


def build_prompt(instruction: str, step: Step, artifacts: dict, labels: dict) -> str:
    """단계 프롬프트를 완성한다.

    - 프롬프트에 {{KEY}} 토큰이 있으면 치환 모드 (artifacts 키를 대문자로 매칭).
    - 없으면 자동 첨부 모드: step.inputs 순서대로 '[입력 자료]' 블록을 덧붙인다.
    """
    if "{{" in instruction:
        out = instruction
        for key, val in artifacts.items():
            out = out.replace("{{" + key.upper() + "}}", str(val))
        return out

    parts = [instruction.rstrip(), "", _SEP, "[입력 자료]", ""]
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
        }
        if seed_artifacts:
            artifacts.update({k: v for k, v in seed_artifacts.items() if v is not None})
        self.final_output = ""
        last_output = ""

        for step in self.bundle.steps:
            if start_from and step.id < start_from:
                continue  # 앞 단계는 seed_artifacts 로 이미 채워둠
            instruction = overrides.get(step.id)
            if instruction is None:
                instruction = self.bundle.step_text(step)
            user_prompt = build_prompt(instruction, step, artifacts, self.input_labels)
            model = model_override or step.model or self.default_model

            raw = llm_fn(
                model=model,
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            output = extract_output(raw, step.extract)
            artifacts[f"step{step.id}"] = output
            last_output = output
            if step.is_final:
                self.final_output = output

            yield StageResult(
                id=step.id, name=step.name, model=model, output=output, raw=raw,
                user_prompt=user_prompt,
            )

        if not self.final_output:
            self.final_output = last_output

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
