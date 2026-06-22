"""LiteLLM 래퍼 — 모델 문자열 하나로 모든 LLM(provider) 호출."""

from __future__ import annotations


class EmptyResponseError(RuntimeError):
    """모델이 빈 응답을 반환(토큰 한도 초과·안전필터 차단 등). 파이프라인이 직전 결과로 대체."""


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

    response = completion(**kwargs)
    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        # 빈 응답이면 이유를 알려준다(토큰 한도 초과 / 안전필터 차단 등). 호출측(파이프라인)이 처리.
        fr = getattr(choice, "finish_reason", None) or "unknown"
        raise EmptyResponseError(
            f"모델이 빈 응답을 반환했습니다 (finish_reason={fr}). "
            "출력 토큰 한도 초과거나 안전필터 차단일 수 있어요. "
            "max_tokens 를 늘리거나 회차를 나눠 다시 시도해 보세요."
        )
    return content
