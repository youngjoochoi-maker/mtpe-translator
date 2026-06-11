"""프롬프트 번들 해석/로딩.

번들 구조:  <prompts_root>/<작품>/<언어쌍>/<버전>/  (step*.txt + meta.yaml)
버전 미지정 시 최신(숫자가 가장 큰) 버전을 자동 선택한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_VER_NUM = re.compile(r"(\d+)")


@dataclass
class Step:
    id: int
    name: str
    file: str
    inputs: list[str] = field(default_factory=list)
    model: str | None = None
    extract: str | None = None
    is_final: bool = False


@dataclass
class Bundle:
    work: str
    lang: str
    version: str
    path: Path
    source_lang: str
    target_lang: str
    steps: list[Step]

    def step_text(self, step: Step) -> str:
        return (self.path / step.file).read_text(encoding="utf-8")


def _version_key(name: str) -> tuple[int, str]:
    m = _VER_NUM.search(name)
    return (int(m.group(1)) if m else -1, name)


def resolve_version(lang_dir: Path, version: str | None) -> Path:
    if not lang_dir.is_dir():
        raise FileNotFoundError(f"언어 번들 경로가 없습니다: {lang_dir}")
    if version:
        vpath = lang_dir / version
        if not vpath.is_dir():
            available = ", ".join(sorted(p.name for p in lang_dir.iterdir() if p.is_dir()))
            raise FileNotFoundError(
                f"버전 '{version}' 이 없습니다: {lang_dir} (가능: {available or '없음'})"
            )
        return vpath
    versions = [p for p in lang_dir.iterdir() if p.is_dir()]
    if not versions:
        raise FileNotFoundError(f"버전 폴더가 없습니다: {lang_dir}")
    return max(versions, key=lambda p: _version_key(p.name))


def list_bundles(prompts_root: str | Path) -> list[dict]:
    """prompts_root 를 스캔해 작품→언어→버전 목록을 반환한다(UI 드롭다운용)."""
    root = Path(prompts_root)
    works: list[dict] = []
    if not root.is_dir():
        return works
    for work_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        langs = []
        for lang_dir in sorted(p for p in work_dir.iterdir() if p.is_dir()):
            versions = sorted(
                (p.name for p in lang_dir.iterdir()
                 if p.is_dir() and (p / "meta.yaml").exists()),
                key=_version_key,
                reverse=True,
            )
            if versions:
                langs.append({"lang": lang_dir.name, "versions": versions})
        if langs:
            works.append({"work": work_dir.name, "langs": langs})
    return works


def load_bundle(
    prompts_root: str | Path,
    work: str,
    lang: str,
    version: str | None = None,
) -> Bundle:
    lang_dir = Path(prompts_root) / work / lang
    vpath = resolve_version(lang_dir, version)

    meta_path = vpath / "meta.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"meta.yaml 이 없습니다: {meta_path}")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

    steps: list[Step] = []
    for s in meta.get("steps", []):
        steps.append(
            Step(
                id=int(s["id"]),
                name=s.get("name", f"STEP {s['id']}"),
                file=s["file"],
                inputs=list(s.get("inputs", [])),
                model=s.get("model"),
                extract=s.get("extract"),
                is_final=(s.get("output") == "final"),
            )
        )
    if not steps:
        raise ValueError(f"번들에 정의된 단계가 없습니다: {meta_path}")
    if not any(st.is_final for st in steps):
        steps[-1].is_final = True

    return Bundle(
        work=meta.get("work", work),
        lang=meta.get("lang", lang),
        version=vpath.name,
        path=vpath,
        source_lang=meta.get("source_lang", "auto"),
        target_lang=meta.get("target_lang", "한국어"),
        steps=steps,
    )
