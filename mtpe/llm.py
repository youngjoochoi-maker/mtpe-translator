"""LiteLLM 래퍼 — 모델 문자열 하나로 모든 LLM(provider) 호출."""

from __future__ import annotations


class EmptyResponseError(RuntimeError):
    """모델이 빈 응답을 반환(토큰 한도 초과·안전필터 차단 등). 파이프라인이 직전 결과로 대체."""


class ModelRefusalError(RuntimeError):
    """모델이 요청 자체를 거부(안전 필터). 거부 문장을 결과로 흘려보내지 않고 회차를 중단한다."""


import re as _re
_REFUSAL_RE = _re.compile(
    r"^\s*(I'm sorry|I am sorry|Sorry)[,.]?\s*(but\s+)?I (can't|cannot|can not|won't|am unable to)\s+(assist|help|comply|provide|fulfill|do that)"
    r"|^\s*I (can't|cannot) (assist|help) with (that|this)"
    r"|^\s*(죄송하지만|죄송합니다)[,.]?\s*(이|해당|그)?\s*요청(은|을)?\s*(도와드릴 수 없|처리할 수 없|수행할 수 없)"
    r"|^\s*申し訳ありません(が)?[、,]?\s*(この|その)?リクエスト(に|は)(お応え|対応)(でき|いたしかね)",
    _re.I,
)


def looks_like_refusal(text: str) -> bool:
    """짧은 응답이 정형화된 거부 문구로 시작하면 True."""
    t = (text or "").strip()
    return bool(t) and len(t) < 400 and bool(_REFUSAL_RE.search(t))


def call_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> str:
    """주어진 모델로 1회 호출하고 응답 텍스트를 반환한다.

    API 키는 환경변수에서 읽는다:
      ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY ...
    """
    try:
        from litellm import completion
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "litellm 이 필요합니다: pip install litellm"
        ) from exc

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    kwargs = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    # gemini 는 기본 안전필터가 소설(폭력·욕설 등)을 빈 응답으로 차단할 수 있어 해제(전문 번역 용도).
    if "gemini" in model.lower():
        kwargs["safety_settings"] = [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ]

    from .logbuf import log as _log
    import time as _time
    _n_in = len(system_prompt or "") + len(user_prompt or "")
    _log(f"▶ 요청  {model} · 입력 약 {_n_in:,}자 · max_tokens {kwargs.get('max_tokens')}"
         + (f" · temp {kwargs['temperature']}" if 'temperature' in kwargs else ""))
    _t0 = _time.time()
    try:
        response = _completion_with_fallback(kwargs)
    except Exception as exc:  # noqa: BLE001
        _log(f"✖ 오류  {model} · {_time.time()-_t0:.1f}초 · {str(exc)[:200]}")
        raise
    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    _fr = getattr(choice, "finish_reason", None) or "?"
    _log(f"◀ 응답  {model} · {_time.time()-_t0:.1f}초 · 출력 {len(content):,}자 · finish={_fr}")
    if looks_like_refusal(content):
        _log(f"✖ 거부  {model} · 모델이 요청을 거부(안전 필터)")
        raise ModelRefusalError(
            f"모델({model})이 요청을 거부했습니다(안전 필터): “{content[:80]}”\n"
            "웹소설의 폭력·선정 묘사 등에 반응한 것으로, 이 모델로는 이 회차를 번역하기 어렵습니다. "
            "다른 모델(Gemini 3.1 Pro / Claude / GPT-4.1·GPT-5 등)로 바꿔 다시 실행해 주세요."
        )
    if not content:
        # 빈 응답이면 이유를 알려준다(토큰 한도 초과 / 안전필터 차단 등). 호출측(파이프라인)이 처리.
        fr = getattr(choice, "finish_reason", None) or "unknown"
        raise EmptyResponseError(
            f"모델이 빈 응답을 반환했습니다 (finish_reason={fr}). "
            "출력 토큰 한도 초과거나 안전필터 차단일 수 있어요. "
            "max_tokens 를 늘리거나 회차를 나눠 다시 시도해 보세요."
        )
    return content


def _model_max_output(model: str) -> int | None:
    """LiteLLM 모델 정보에서 출력 토큰 상한을 조회(모르면 None)."""
    try:
        import litellm
        info = litellm.get_model_info(model)
        v = info.get("max_output_tokens") or info.get("max_tokens")
        return int(v) if v else None
    except Exception:  # noqa: BLE001
        return None


def _completion_with_fallback(kwargs: dict):
    """모델별 파라미터 제약을 자동 흡수하며 호출한다.

    - 모델이 지원하지 않는 파라미터(예: Claude Opus 4.8 의 temperature≠1)는 버림(drop_params).
    - max_tokens 가 모델 상한보다 크면 상한으로 낮춤. 그래도 거부되면 오류 메시지의 상한값으로 1회 재시도.
    """
    import re
    import litellm
    from litellm import completion

    litellm.drop_params = True  # 지원하지 않는 파라미터는 조용히 제거

    cap = _model_max_output(kwargs["model"])
    if cap and kwargs.get("max_tokens") and kwargs["max_tokens"] > cap:
        kwargs["max_tokens"] = cap

    try:
        return completion(**kwargs)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        # 1) temperature 등 파라미터 거부 → 해당 파라미터 빼고 재시도
        if "temperature" in msg and ("does not support" in msg or "Only temperature" in msg):
            from .logbuf import log as _log
            _log(f"⚠ 재시도  {kwargs['model']} · temperature 미지원 → 제거 후 재요청")
            kwargs.pop("temperature", None)
            return completion(**kwargs)
        # 2) max_tokens 상한 초과 → 메시지의 상한값으로 재시도
        m = re.search(r"supports at most (\d+) (?:completion|output) tokens", msg) \
            or re.search(r"max_tokens.*?(\d{4,6})", msg)
        if m and "max_tokens" in kwargs:
            limit = int(m.group(1))
            if limit < kwargs["max_tokens"]:
                from .logbuf import log as _log
                _log(f"⚠ 재시도  {kwargs['model']} · max_tokens 상한 초과 → {limit}로 낮춰 재요청")
                kwargs["max_tokens"] = limit
                return completion(**kwargs)
        raise
