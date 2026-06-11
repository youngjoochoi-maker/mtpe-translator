"""MTPE CLI 진입점.

사용 예:
  # 기본 작품/언어 + 최신 버전
  python -m mtpe.cli -s 원문.txt -g 설정집.txt --out out/

  # 작품/언어/버전 지정 + 단계별 모델 강제 + 중간결과 저장
  python -m mtpe.cli -s 원문.txt -g tb.txt -w 장저견 -l zh-ko -V v1 -m gpt-4o --save-stages
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .io_utils import read_text, write_text
from .pipeline import Pipeline, build_prompt


def load_dotenv(path: Path) -> None:
    """.env 파일이 있으면 KEY=VALUE 를 환경변수로 로드한다(기존 값은 보존)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mtpe",
        description="작품·언어·버전별 프롬프트 번들로 MT(기계번역)를 추출하는 MTPE 도구",
    )
    p.add_argument("--source", "-s", default=None, help="원문 파일 (txt/md/docx)")
    p.add_argument("--glossary", "-g", default=None, help="설정집/TB 파일 (txt/md/docx)")
    p.add_argument("--out", "-o", default="out", help="결과 출력 디렉터리 (기본: out)")
    p.add_argument("--config", "-c", default=None, help="config.yaml 경로")
    p.add_argument("--work", "-w", default=None, help="작품 (미지정 시 config default_work)")
    p.add_argument("--lang", "-l", default=None, help="언어쌍 예: zh-ko (미지정 시 default_lang)")
    p.add_argument("--version", "-V", default=None, help="프롬프트 버전 (미지정 시 최신)")
    p.add_argument("--model", "-m", default=None, help="모든 단계 모델 강제 지정(override)")
    p.add_argument("--save-stages", action="store_true", help="단계별 중간 결과도 모두 저장")
    p.add_argument("--check", action="store_true",
                   help="LLM 호출 없이 번들 로드/모델/API키 설정 상태만 점검(프리플라이트)")
    p.add_argument("--dry-run", action="store_true",
                   help="LLM 호출 없이 각 단계 조립 프롬프트를 out/ 에 저장(원문·TB 주입 확인용)")
    return p


def _run_dry(pipeline, source, glossary, out_dir) -> int:
    """LLM 없이 각 단계 프롬프트를 실제 원문·TB로 조립해 저장한다.

    이후 단계 출력은 자리표시자로 채워 흐름만 보여준다.
    """
    artifacts = {
        "source": source,
        "glossary": glossary or "(설정집 없음)",
        "source_lang": pipeline.bundle.source_lang,
        "target_lang": pipeline.bundle.target_lang,
    }
    print(f"▶ DRY-RUN (LLM 호출 없음) — 원문 {len(source)}자 / TB {len(glossary)}자",
          file=sys.stderr)
    for step in pipeline.bundle.steps:
        instruction = pipeline.bundle.step_text(step)
        prompt = build_prompt(instruction, step, artifacts, pipeline.input_labels)
        path = out_dir / f"_dryrun_step{step.id}_prompt.txt"
        write_text(path, prompt)
        print(f"  STEP{step.id} {step.name}: 프롬프트 {len(prompt)}자 → {path}",
              file=sys.stderr)
        # 다음 단계가 참조할 수 있도록 자리표시자 출력 채움
        artifacts[f"step{step.id}"] = f"(STEP{step.id} 출력 자리 — 실제 실행 시 채워짐)"
    print("✅ DRY-RUN 완료. out/_dryrun_step*_prompt.txt 확인", file=sys.stderr)
    return 0


# (provider 표시용) LiteLLM 모델 문자열 → 필요한 환경변수 키
_PROVIDER_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "o1": "OPENAI_API_KEY",
    "o3": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _required_key_for(model: str) -> str | None:
    m = model.lower()
    for prefix, env in _PROVIDER_KEYS.items():
        if m.startswith(prefix) or m.startswith(f"{prefix}/"):
            return env
    return None


def _run_check(pipeline, args) -> int:
    import os

    b = pipeline.bundle
    print(f"■ 번들: 작품={b.work} 언어={b.lang} 버전={b.version} "
          f"({b.source_lang}→{b.target_lang})")
    print(f"■ 단계 {len(b.steps)}개:")
    needed: set[str] = set()
    for s in b.steps:
        model = args.model or s.model or pipeline.default_model
        env = _required_key_for(model)
        if env:
            needed.add(env)
        print(f"   STEP{s.id} {s.name}: model={model} inputs={s.inputs}"
              + (f" extract={s.extract}" if s.extract else "")
              + (" [최종]" if s.is_final else ""))
    print("■ API 키 상태:")
    if not needed:
        print("   (모델 문자열에서 provider 를 식별 못 함 — 수동 확인 필요)")
    for env in sorted(needed):
        ok = "설정됨 ✅" if os.environ.get(env) else "없음 ❌  ← export 필요"
        print(f"   {env}: {ok}")
    return 0


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 프로젝트 루트의 .env 로드 (있으면)
    load_dotenv(_default_config_path().parent / ".env")

    config_path = Path(args.config) if args.config else _default_config_path()
    if not config_path.exists():
        print(f"[오류] 설정 파일이 없습니다: {config_path}", file=sys.stderr)
        return 2

    try:
        pipeline = Pipeline.from_config(
            config_path, work=args.work, lang=args.lang, version=args.version
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[오류] 프롬프트 번들 로드 실패: {exc}", file=sys.stderr)
        return 2

    if args.check:
        return _run_check(pipeline, args)

    if not args.source:
        print("[오류] --source 가 필요합니다. (점검만 하려면 --check)", file=sys.stderr)
        return 2

    source = read_text(args.source)
    glossary = read_text(args.glossary) if args.glossary else ""
    out_dir = Path(args.out)

    if args.dry_run:
        return _run_dry(pipeline, source, glossary, out_dir)

    b = pipeline.bundle
    print(
        f"▶ 작품={b.work} 언어={b.lang} 버전={b.version} "
        f"({b.source_lang}→{b.target_lang}) | 단계={len(b.steps)}",
        file=sys.stderr,
    )

    def on_stage(result):
        print(f"✓ [{result.id}] {result.name} ({result.model}) — {len(result.output)}자",
              file=sys.stderr)
        if args.save_stages:
            write_text(out_dir / f"step{result.id}_{result.name}.txt", result.raw)

    try:
        results = pipeline.run(
            source, glossary, model_override=args.model, on_stage=on_stage
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[오류] 파이프라인 실패: {exc}", file=sys.stderr)
        return 1

    final_path = out_dir / "final.txt"
    write_text(final_path, pipeline.final_output)
    print(f"✅ 완료 → {final_path}", file=sys.stderr)

    print(pipeline.final_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
