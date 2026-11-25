"""모델이 번역문을 이중 이스케이프해 보내도 줄바꿈·따옴표가 복원되는지 (2026-11-25 권총지오작의비 EP343 사례)."""
import json

from mtpe.pipeline import _undo_double_escape, extract_output

NORMAL = '§§§第343章乡村治病\n#제343화\n\n이곳은 허름한 농가였다.\n"군주께서 원하시는 것입니다."\n그는 고개를 끄덕였다.'


def _double(text: str) -> str:
    """모델이 값을 한 번 더 이스케이프한 상태(파싱 후에도 '\\n' 글자가 남는 상태)."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def test_json_rule_restores_double_escaped_value():
    raw = '<o>' + json.dumps({"final_translation": "\\n" + _double(NORMAL) + "\\n"}, ensure_ascii=False) + '</o>'
    # json.dumps 가 '\\n' 을 다시 이스케이프 → 모델이 보낸 '이중 이스케이프' 응답과 같은 모양
    out = extract_output(raw, "json:final_translation")
    assert out == NORMAL
    assert "\\n" not in out and '\\"' not in out


def test_auto_clean_restores_double_escaped_value():
    raw = json.dumps({"translation": _double(NORMAL)}, ensure_ascii=False)
    assert extract_output(raw, None) == NORMAL


def test_normal_output_untouched():
    raw = '<o>' + json.dumps({"final_translation": NORMAL}, ensure_ascii=False) + '</o>'
    assert extract_output(raw, "json:final_translation") == NORMAL


def test_few_literal_backslash_n_untouched():
    text = NORMAL + '\n코드 예시는 "\\n" 처럼 쓴다.'
    assert _undo_double_escape(text) == text


def test_tag_rule_untouched():
    analysis = '{"a": "x\\ny\\nz\\nw"}'
    assert extract_output("<o>" + analysis + "</o>", "tag:o") == analysis
