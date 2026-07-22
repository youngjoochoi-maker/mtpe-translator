"""
platform_fetcher.py
-------------------
연재 플랫폼(네이버 시리즈 등)의 '공개 회차 목록'(회차 번호 + 제목)을 가져온다.

목적: 우리가 분권한 결과의 회차 수·제목을 플랫폼 연재분과 대조하기 위함.
- 본문(유료/DRM)은 다루지 않고, 공개 페이지의 회차 목록 메타데이터만 사용한다.
- 표준 라이브러리 urllib 만 사용(추가 의존성 없음).

지원 현황
- 네이버 시리즈: 지원 (회차 목록이 공개 JSON 으로 제공됨)
- 카카오페이지 : 현재 단순 HTTP 요청이 차단(403)되어 미지원(실제 브라우저 세션 필요)

주의: 공개 페이지라도 자동 수집은 각 플랫폼 약관상 제한될 수 있으며,
      사용 책임은 사용자에게 있다. 본 모듈은 사용자가 URL 을 직접 입력해
      실행하는 경우에만 동작한다.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_TIMEOUT = 15


@dataclass
class Episode:
    """플랫폼 회차 1개."""

    no: int          # 회차 순번(1부터)
    title: str       # 회차 제목(예: '1화' 또는 '1화 제목')


@dataclass
class PlatformResult:
    """플랫폼에서 수집한 작품 회차 정보."""

    platform: str                       # 'naver' 등
    work_title: str = ""                # 작품 제목
    total_count: int = 0                # 플랫폼이 알려주는 총 회차 수
    episodes: List[Episode] = field(default_factory=list)
    source_url: str = ""


class PlatformError(Exception):
    """플랫폼 수집 중 발생하는 사용자 안내용 오류."""


# ---------------------------------------------------------------------------- #
# 우리 분권 결과 ↔ 플랫폼 회차 목록 대조
# ---------------------------------------------------------------------------- #
@dataclass
class ComparisonRow:
    """대조 표의 한 줄."""

    no: int
    our_title: str        # 우리 분권 제목(첫 줄) - 없으면 ''
    platform_title: str   # 플랫폼 회차 제목 - 없으면 ''
    title_match: bool     # 제목이 대응되는지(느슨한 비교)


@dataclass
class Comparison:
    """분권 결과와 플랫폼 회차 목록의 대조 결과."""

    our_count: int
    platform_count: int
    rows: List[ComparisonRow] = field(default_factory=list)

    @property
    def count_match(self) -> bool:
        """회차 수가 일치하는가."""
        return self.our_count == self.platform_count


def _normalize(text: str) -> str:
    """제목 비교용 정규화: 공백 제거."""
    return re.sub(r"\s+", "", text or "")


def compare_titles(our_titles: List[str], platform: PlatformResult) -> Comparison:
    """
    우리 분권 제목 목록과 플랫폼 회차 목록을 순번 기준으로 나란히 대조한다.

    제목 일치는 느슨하게 판정한다(공백 제거 후 완전일치 또는 한쪽이 다른 쪽을
    포함). 플랫폼 회차가 '1화'처럼 번호만 있는 경우가 많아, 제목 불일치가
    곧 오류를 의미하지는 않는다(회차 '수' 일치가 1차 지표).
    """
    plat_titles = [ep.title for ep in platform.episodes]
    n = max(len(our_titles), len(plat_titles))
    rows: List[ComparisonRow] = []
    for i in range(n):
        ours = our_titles[i] if i < len(our_titles) else ""
        plat = plat_titles[i] if i < len(plat_titles) else ""
        no = _normalize(ours)
        np = _normalize(plat)
        match = bool(no and np and (no == np or no in np or np in no))
        rows.append(
            ComparisonRow(no=i + 1, our_title=ours, platform_title=plat, title_match=match)
        )
    return Comparison(
        our_count=len(our_titles),
        platform_count=platform.total_count or len(plat_titles),
        rows=rows,
    )


class PlatformFetcher:
    """URL 을 받아 해당 플랫폼의 회차 목록을 가져온다."""

    def fetch(self, url: str) -> PlatformResult:
        """URL 의 플랫폼을 판별해 회차 목록을 수집한다."""
        url = (url or "").strip()
        if not url:
            raise PlatformError("URL 을 입력하세요.")

        if "series.naver.com" in url:
            return self._fetch_naver(url)
        if "page.kakao.com" in url or "kakao" in url:
            raise PlatformError(
                "카카오페이지는 현재 자동 수집이 차단(403)되어 지원되지 않습니다.\n"
                "네이버 시리즈 URL 을 사용하시거나, 회차 목록을 직접 붙여넣는 방식을 "
                "요청해 주세요."
            )
        raise PlatformError(
            "지원하지 않는 URL 입니다.\n"
            "현재는 네이버 시리즈(series.naver.com) 작품 URL 을 지원합니다."
        )

    # ------------------------------------------------------------------ #
    # 네이버 시리즈
    # ------------------------------------------------------------------ #
    def _fetch_naver(self, url: str) -> PlatformResult:
        """
        네이버 시리즈 작품의 전체 회차 목록을 수집한다.

        회차 목록은 volumeList.series 엔드포인트가 페이지당 30개씩 JSON 형태로
        제공하며, totalVolumeCount 로 총 회차 수를 알 수 있다.
        """
        m = re.search(r"productNo=(\d+)", url)
        if not m:
            raise PlatformError(
                "네이버 시리즈 URL 에서 productNo 를 찾을 수 없습니다.\n"
                "작품 상세 페이지 URL(예: .../novel/detail.series?productNo=123)을 "
                "입력하세요."
            )
        product_no = m.group(1)

        work_title = self._fetch_naver_title(product_no)

        episodes: List[Episode] = []
        total: Optional[int] = None
        page = 1
        while True:
            html = self._get(
                f"https://series.naver.com/novel/volumeList.series"
                f"?productNo={product_no}&page={page}&sortOrder=ASC",
                referer=f"https://series.naver.com/novel/detail.series?productNo={product_no}",
            )
            if total is None:
                tm = re.search(r'"totalVolumeCount":(\d+)', html)
                total = int(tm.group(1)) if tm else 0

            names = re.findall(r'"volumnNameText":"([^"]*)"', html)
            if not names:
                break
            for name in names:
                episodes.append(Episode(no=len(episodes) + 1, title=name))

            if total and len(episodes) >= total:
                break
            if page >= 200:  # 안전장치(무한 루프 방지)
                break
            page += 1

        return PlatformResult(
            platform="naver",
            work_title=work_title,
            total_count=total or len(episodes),
            episodes=episodes,
            source_url=url,
        )

    def _fetch_naver_title(self, product_no: str) -> str:
        """작품 상세 페이지 <title> 에서 작품명을 추출한다."""
        try:
            html = self._get(
                f"https://series.naver.com/novel/detail.series?productNo={product_no}"
            )
            m = re.search(r"<title>([^<]+)</title>", html)
            if m:
                # '작품명 : 네이버 시리즈' 형태면 앞부분만 취함
                return m.group(1).split(":")[0].strip()
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------ #
    # 공통 HTTP
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get(url: str, referer: str = "") -> str:
        """GET 요청 후 본문 텍스트를 반환한다."""
        headers = {"User-Agent": _UA}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read()
        except Exception as exc:  # noqa: BLE001
            raise PlatformError(f"페이지를 가져오지 못했습니다: {exc}") from exc
        return raw.decode("utf-8", errors="replace")
