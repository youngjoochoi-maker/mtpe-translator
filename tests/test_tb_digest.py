"""회차별 필수 용어(TB 다이제스트): 원문에 나온 TB 항목만, 긴 용어 안에 들어간 짧은 용어는 빼고, 인물명은 남긴다."""
from mtpe.io_utils import tb_episode_digest

GLOSSARY = """## [인물] (= Characters)
NO | 중문명 | 국문명 | 성별 | 첫 등장시기
1 | 秦莞 | 진완 | 여 | 1화
2 | 晋王 | 진왕 | 남 | 3화
3 | 不在 | 없는사람 | 남 | 9화
## [용어] (= Term Localizations)
No. | 범주 | 등장회차 | 중문명 | 국문명
1 | 기관 | 4 | 大理寺 | 대리시
2 | 관직 | 5 | 大理寺卿 | 대리시경(大理寺卿)
3 | 명칭 | 3 | 夫人 | 부인
4 | 명칭 | 7 | 人和 | 인화
5 | 사건 | 8 | 晋王的案子 | 진왕(晉王) 사건
6 | 명칭 | 9 | 院子 | 뜰->정원
## [호칭]
NO | F=존대/I=반말 | 진완
1 | 진완 | I(~해)
"""

SRC = "秦莞看着大理寺卿。赵夫人和胡氏进了院子。晋王的案子还没结。"


def test_digest_picks_terms_in_source_order():
    d, n = tb_episode_digest(GLOSSARY, SRC)
    lines = [l for l in d.splitlines() if l.startswith("- ")]
    assert n == len(lines)
    terms = [l[2:].split(" →")[0] for l in lines]
    assert terms[:2] == ["秦莞", "大理寺卿"]          # 원문 등장 순
    assert "大理寺" not in terms                       # 大理寺卿 안에 완전히 들어간 짧은 용어는 제외
    assert "晋王" in terms and "晋王的案子" in terms    # 인물명은 긴 용어 안에 있어도 남김
    assert "不在" not in terms                         # 원문에 없는 항목 제외
    assert any("院子 → 뜰->정원" in l for l in lines)
    assert "첫 등장 1화" in lines[0] and "(인물" in lines[0]


def test_crossing_overlap_is_flagged():
    d, _ = tb_episode_digest(GLOSSARY, SRC)
    line = next(l for l in d.splitlines() if l.startswith("- 人和"))
    assert "문맥 확인" in line                         # 夫人和: 夫人/人和 가 걸쳐 겹침


def test_no_match_or_no_columns_returns_empty():
    assert tb_episode_digest(GLOSSARY, "没有任何术语") == ("", 0)
    assert tb_episode_digest("## [기타]\nA | B\nx | y", SRC) == ("", 0)
    assert tb_episode_digest("", SRC) == ("", 0)


def test_slash_bundled_terms_are_split_and_paired():
    g = "## [인물] (= Characters)\nNO | 중문명 | 국문명 | 첫 등장시기\n1 | 王氏/王燕如 | 왕씨/왕연여 | 3화\n2 | 李叔/李大贵 | 이 아저씨 | 1화\n"
    d, n = tb_episode_digest(g, "王燕如来了，李大贵也来了。")
    assert "- 王燕如 → 왕연여" in d                    # 개수가 같으면 짝지어
    assert "- 李大贵 → 이 아저씨" in d                 # 개수가 다르면 국문 전체
    assert "王氏 →" not in d and n == 2
