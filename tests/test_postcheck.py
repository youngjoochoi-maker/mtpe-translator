"""배치 자동 점검·정리·재추출 (2026-11-26 권총 EP352·361 중국어 줄 섞임, 대소저타 빈 줄 대량, 권총 EP357 잘림 경고 사례)."""
from types import SimpleNamespace

from mtpe import postcheck as pc
from mtpe import server

HEAD = "§§§第352章心有所属\n#제352화"
GOOD = HEAD + "\n진완은 잠시 생각했다.\n\"큰어머니, 정말 맹요가 좋으세요?\"\n호 씨가 말했다."


def test_normal_output_untouched():
    iss = pc.inspect(GOOD)
    assert not iss.needs_retry and iss.header_gap == 0
    assert pc.clean(GOOD) == GOOD  # 원문 챕터 줄(§§§…)은 남김


def test_interleaved_source_lines_removed():
    mixed = (HEAD + "\n秦莞想了想孟瑶，强自笑笑道，“大伯母，您当真觉的孟瑶好？”\n"
             "진완은 잠시 생각했다.\n“郡主——”\n\"큰어머니, 정말 맹요가 좋으세요?\"\n호 씨가 말했다.")
    iss = pc.inspect(mixed)
    assert iss.untranslated == 2 and iss.needs_retry
    assert pc.clean(mixed) == GOOD


def test_hanja_annotation_line_kept():
    line = "팽번금(彭繁錦)이 더욱 마음에 들었다."
    assert pc.inspect(HEAD + "\n" + line).untranslated == 0
    assert line in pc.clean(HEAD + "\n" + line)


def test_blank_lines_body_vs_header_gap():
    gap_only = HEAD + "\n\n진완은 잠시 생각했다.\n호 씨가 말했다.\n"
    iss = pc.inspect(gap_only)
    assert iss.header_gap == 1 and iss.blank == 0 and not iss.needs_retry  # 제목 아래 1칸은 재추출 사유 아님
    assert "\n\n" not in pc.clean(gap_only)
    mass = HEAD + "\n\n진완은 잠시 생각했다.\n\n\"큰어머니?\"\n\n호 씨가 말했다."
    iss = pc.inspect(mass)
    assert iss.blank == 2 and iss.needs_retry
    assert pc.clean(mass).count("\n") == 4


def test_warning_line_detected_and_removed():
    warned = ("⚠️ [자동경고] 이 회차는 분량이 많아 모델 출력이 끝에서 잘렸습니다(STEP1). — 확인 후 이 줄은 지워도 됩니다.\n\n"
              + GOOD)
    iss = pc.inspect(warned, [1])
    assert iss.warning_line and iss.truncated == [1] and iss.needs_retry
    assert pc.clean(warned) == GOOD
    assert pc.inspect(GOOD, [1]).rank() > pc.inspect(GOOD).rank()


# ── 배치 실행 흐름: 문제 있으면 같은 회차를 다시 추출하고 더 나은 결과 + 정리본 저장 ──

def _fake_pipeline(outputs):
    calls = {"n": 0}

    class FakePipe:
        bundle = SimpleNamespace(version="v1", steps=[SimpleNamespace(id=5, name="각색")])

        @classmethod
        def from_config(cls, *a, **k):
            return cls()

        def run_iter(self, source, tb_text, **k):
            final, trunc = outputs[min(calls["n"], len(outputs) - 1)]
            calls["n"] += 1
            self.final_output, self.truncated_steps = final, trunc
            yield SimpleNamespace(id=5, name="각색", model="fake", output=final, seconds=1.0,
                                  in_tokens=10, out_tokens=10, cost=0.5, skipped=False, error="")
    return FakePipe, calls


def _run_batch(tmp_path, monkeypatch, outputs, retries=1):
    monkeypatch.setattr(server, "WORKS_ROOT", tmp_path)
    monkeypatch.setattr(server, "postcheck_settings",
                        lambda lang: {"max_retries": retries} if lang == "zh-ko" else None)
    fake, calls = _fake_pipeline(outputs)
    monkeypatch.setattr(server, "Pipeline", fake)
    epd = server._batch_ep_dir("작품", "배치")
    epd.mkdir(parents=True)
    (epd / "작품_EP1.txt").write_text("§§§第1章\n原文", encoding="utf-8")
    st = {"batch_id": "btest", "work": "작품", "lang": "zh-ko", "batch": "배치", "version": "v1",
          "model": "fake", "model_override": "fake", "concurrency": 1, "status": "queued", "error": None,
          "totals": {"seconds": 0.0, "in_tokens": 0, "out_tokens": 0, "cost": 0.0},
          "episodes": [{"name": "작품_EP1.txt", "status": "queued", "error": None}], "_cancel": False}
    server._batch_runner(st, "")
    outd = server._batch_out_dir("작품", "배치") / "작품_EP1"
    return st, calls, outd


def test_batch_retries_bad_episode_and_uses_clean_result(tmp_path, monkeypatch):
    bad = HEAD + "\n秦莞想了想孟瑶，强自笑笑道\n\n진완은 잠시 생각했다."
    st, calls, outd = _run_batch(tmp_path, monkeypatch, [(bad, []), (GOOD, [])])
    ep = st["episodes"][0]
    assert calls["n"] == 2 and ep["status"] == "done" and st["status"] == "done"
    assert ep["postcheck"]["tries"] == 2 and ep["postcheck"]["used"] == 2
    assert (outd / "final.txt").read_text(encoding="utf-8") == GOOD
    assert (outd / "steps_try1.json").exists()          # 쓰지 않은 첫 결과 보관
    assert ep["cost"] == 1.0 and st["totals"]["cost"] == 1.0   # 재추출 비용 포함
    assert not st.get("error") and "note" not in ep
    hist = (tmp_path / "작품" / "자동점검_기록.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(hist) == 2 and "n8n 배치" in hist[1] and "작품_EP1" in hist[1] and "2번째" in hist[1]


def test_batch_cleans_when_retry_still_bad_and_reports_truncation(tmp_path, monkeypatch):
    warned = "⚠️ [자동경고] 잘렸습니다(STEP1).\n\n" + HEAD + "\n\n진완은 잠시 생각했다.\n\n호 씨가 말했다."
    st, calls, outd = _run_batch(tmp_path, monkeypatch, [(warned, [1]), (warned, [1])])
    ep = st["episodes"][0]
    assert calls["n"] == 2 and ep["status"] == "done"        # 재추출은 1번까지만
    final = (outd / "final.txt").read_text(encoding="utf-8")
    assert final == HEAD + "\n진완은 잠시 생각했다.\n호 씨가 말했다."
    assert (outd / "final_raw.txt").read_text(encoding="utf-8") == warned
    assert "출력 잘림(STEP1)" in ep["note"] and "확인 필요" in st["error"]   # 시트 오류메시지·슬랙으로 전달


def test_batch_no_retry_for_clean_or_header_gap(tmp_path, monkeypatch):
    gap = HEAD + "\n\n진완은 잠시 생각했다."
    st, calls, outd = _run_batch(tmp_path, monkeypatch, [(gap, [])])
    assert calls["n"] == 1 and st["episodes"][0]["postcheck"]["tries"] == 1
    assert (outd / "final.txt").read_text(encoding="utf-8") == HEAD + "\n진완은 잠시 생각했다."
    assert not (tmp_path / "작품" / "자동점검_기록.csv").exists()   # 제목 아래 빈 줄만 정리 → 기록 안 함


# ── 앱(번역 탭 '회차 실행', /api/run): 같은 점검·재추출, 화면 알림 없이 기록만 ──

def _run_app(tmp_path, monkeypatch, outputs, lang="zh-ko"):
    import json
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "WORKS_ROOT", tmp_path)
    monkeypatch.setattr(server, "postcheck_settings",
                        lambda l: {"max_retries": 1} if l == "zh-ko" else None)
    monkeypatch.setattr(server, "_app_model", lambda m, p: ("fake", ["fake"], "fake"))
    monkeypatch.setattr(server, "_missing_keys", lambda used: [])
    fake, calls = _fake_pipeline(outputs)
    monkeypatch.setattr(server, "Pipeline", fake)
    epd = tmp_path / "작품" / "episodes"
    epd.mkdir(parents=True)
    (epd / "작품_EP1.txt").write_text("§§§第1章\n原文", encoding="utf-8")
    r = TestClient(server.app).post("/api/run", json={"work": "작품", "lang": lang, "model": "fake",
                                                       "episodes": ["작품_EP1.txt"]})
    evs = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    return evs, calls


def test_app_run_retries_and_shows_clean_final(tmp_path, monkeypatch):
    bad = HEAD + "\n秦莞想了想孟瑶，强自笑笑道\n\n진완은 잠시 생각했다."
    evs, calls = _run_app(tmp_path, monkeypatch, [(bad, []), (GOOD, [])])
    fin = next(e for e in evs if e["type"] == "episode_final")
    done = next(e for e in evs if e["type"] == "all_done")
    assert calls["n"] == 2 and fin["output"] == GOOD
    assert fin["cost"] == 1.0 and done["cost"] == 1.0 and done["done"] == 1
    assert [e["output"] for e in evs if e["type"] == "step"][-1] == GOOD   # 화면 단계 칸 = 쓴 결과
    assert not any("재추출" in json_str for json_str in map(str, evs))      # 화면 알림 없음
    hist = (tmp_path / "작품" / "자동점검_기록.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(hist) == 2 and ",앱," in hist[1]


def test_app_run_keeps_better_first_try_and_restores_step_panels(tmp_path, monkeypatch):
    first = HEAD + "\n\n진완은 잠시 생각했다.\n\n호 씨가 말했다."        # 빈 줄만
    worse = "⚠️ [자동경고] 잘렸습니다(STEP2).\n\n" + HEAD + "\n진완은"   # 잘림
    evs, calls = _run_app(tmp_path, monkeypatch, [(first, []), (worse, [2])])
    fin = next(e for e in evs if e["type"] == "episode_final")
    assert calls["n"] == 2 and fin["output"] == HEAD + "\n진완은 잠시 생각했다.\n호 씨가 말했다."
    assert [e["output"] for e in evs if e["type"] == "step"][-1] == first   # 앞 시도로 되돌림


def test_app_run_other_lang_unchanged(tmp_path, monkeypatch):
    raw = "제목\n\n本文 그대로"
    evs, calls = _run_app(tmp_path, monkeypatch, [(raw, [])], lang="ko-ja")
    fin = next(e for e in evs if e["type"] == "episode_final")
    assert calls["n"] == 1 and fin["output"] == raw


def test_batch_other_lang_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKS_ROOT", tmp_path)
    assert server.postcheck_settings("ko-ja") is None
    assert server.postcheck_settings("zh-ko") == {"max_retries": 1}
