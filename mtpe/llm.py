"""LiteLLM 래퍼 — 모델 문자열 하나로 모든 LLM(provider) 호출."""

from __future__ import annotations


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

    response = completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()
