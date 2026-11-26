"""최종본 자동 점검·정리(배치 자동화용). AI 호출 없음 — 같은 입력이면 늘 같은 결과.

점검(재추출 여부 판단)과 정리(파일로 내보내기 전 마무리) 두 가지만 한다.
  ① 번역 안 된 원문 줄: 한글이 하나도 없고 한자가 2자 이상인 줄(맨 위 원문 챕터 줄 §§§… 은 제외).
     예) 번역 사이에 중국어 원문 줄이 그대로 끼어 나온 경우.
  ② 빈 줄: 본문 사이의 빈 줄. 단 맨 위 제목 줄(§§§…·#제N화) 바로 아래 빈 줄은 모델 습관이라
     정리만 하고 재추출 사유로는 세지 않는다(header_gap).
  ③ 잘림 경고: 파이프라인이 길이 제한으로 잘린 회차 맨 위에 붙이는 '⚠️ [자동경고] …' 줄.
번역 문장 자체(용어·한자·문체)는 건드리지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

WARN_PREFIX = "⚠️ [자동경고]"
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
_HEADER = re.compile(r"^(?:§§§|#\s*제\s*\d+\s*화)")


@dataclass
class Issues:
    untranslated: int = 0        # ① 번역 안 된 원문 줄 수
    blank: int = 0               # ② 본문 사이 빈 줄 수(제목 아래 1칸 제외)
    header_gap: int = 0          #    제목 줄 바로 아래 빈 줄(정리만, 재추출 사유 아님)
    truncated: list[int] = field(default_factory=list)  # ③ 잘린 단계 번호
    warning_line: bool = False   #    본문 맨 위 경고 줄 유무

    @property
    def needs_retry(self) -> bool:
        return bool(self.untranslated or self.blank or self.truncated or self.warning_line)

    def rank(self) -> tuple:
        """두 결과 중 고를 때 작을수록 좋음: 잘림 > 원문 줄 > 빈 줄 순으로 나쁨."""
        return (1 if (self.truncated or self.warning_line) else 0, self.untranslated, self.blank)

    def summary(self) -> str:
        parts = []
        if self.untranslated:
            parts.append(f"번역 안 된 원문 줄 {self.untranslated}")
        if self.blank:
            parts.append(f"빈 줄 {self.blank}")
        if self.truncated or self.warning_line:
            tag = ", ".join(f"STEP{i}" for i in self.truncated) or "단계 미상"
            parts.append(f"출력 잘림({tag})")
        return " · ".join(parts)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _is_untranslated(line: str) -> bool:
    t = line.strip()
    if not t or t.startswith("§§§"):
        return False
    return len(_HAN.findall(t)) >= 2 and not _HANGUL.search(t)


def _split(text: str) -> tuple[list[str], list[str]]:
    """(경고 줄들, 나머지 줄들). 끝의 빈 줄은 버린다."""
    lines = _norm(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    warn = [l for l in lines if l.strip().startswith(WARN_PREFIX)]
    rest = [l for l in lines if not l.strip().startswith(WARN_PREFIX)]
    while rest and not rest[0].strip():
        rest.pop(0)
    while rest and not rest[-1].strip():
        rest.pop()
    return warn, rest


def _blank_counts(lines: list[str]) -> tuple[int, int]:
    """(본문 빈 줄, 제목 아래 빈 줄). lines 는 앞뒤 빈 줄이 없는 상태."""
    i = 0
    while i < len(lines) and lines[i].strip() and _HEADER.match(lines[i].strip()):
        i += 1
    gap = 0
    if i:  # 제목 줄이 있으면 그 바로 아래 연속 빈 줄
        while i < len(lines) and not lines[i].strip():
            gap += 1
            i += 1
    body = sum(1 for l in lines[i:] if not l.strip())
    return body, gap


def inspect(text: str, truncated_steps: list[int] | None = None) -> Issues:
    warn, rest = _split(text)
    body, gap = _blank_counts(rest)
    return Issues(
        untranslated=sum(1 for l in rest if _is_untranslated(l)),
        blank=body,
        header_gap=gap,
        truncated=sorted(set(truncated_steps or [])),
        warning_line=bool(warn),
    )


def clean(text: str) -> str:
    """경고 줄·번역 안 된 원문 줄·빈 줄을 지운 최종본. 나머지 줄은 글자 하나 바꾸지 않는다."""
    _, rest = _split(text)
    out = [l.rstrip() for l in rest if l.strip() and not _is_untranslated(l)]
    return "\n".join(out)


def has_target_text(text: str) -> bool:
    """정리 뒤에 한글 번역이 남아 있는지(원문을 통째로 되돌려준 경우 등을 거르기 위함)."""
    return bool(_HANGUL.search(text or ""))
