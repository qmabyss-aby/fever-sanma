"""コマンドライン（`python -m fever_sanma`）のテスト。重い比較は半荘数を最小にして形だけ見る。"""

import random

import pytest

from fever_sanma.__main__ import _pad, cpu_seating, main
from fever_sanma.players import PICKABLE_KINDS, RANDOM_PICK, parse_ai_kinds, resolve_ai_kinds


def test_league_covers_every_table(capsys):
    assert main(["--league", "1", "--seed", "0"]) == 0
    out = capsys.readouterr().out
    assert "4卓 × 1半荘 = 4半荘" in out  # 4種類から3人を選ぶ組み合わせは4通り
    for label in ("強いCPU", "脊髄狙い", "高打点狙い", "守備型"):
        assert label in out
    assert "直接対決" in out
    assert "1半荘の最高得点" in out


def test_league_needs_three_kinds():
    with pytest.raises(SystemExit):
        main(["--league", "1", "--ai", "strong,value"])


def test_compare_reports_best_score(capsys):
    assert main(["--compare", "3", "--seed", "0"]) == 0
    assert "1半荘の最高得点" in capsys.readouterr().out


def test_unknown_ai_is_rejected():
    with pytest.raises(SystemExit):
        main(["--compare", "1", "--ai", "strong,nope,random"])


def test_cpu_seating_starts_from_the_humans_right():
    # 人間の下家から順に割り当てる
    assert cpu_seating(0, ["value", "defense"])[1:] == ["value", "defense"]
    assert cpu_seating(2, ["value", "defense"])[:2] == ["value", "defense"]


def test_pad_counts_full_width_as_two():
    assert _pad("守備型", 8) == "守備型  "
    assert _pad("CPU", 6, right=True) == "   CPU"


# --- ランダムに選ぶ（--ai any） ---------------------------------------------


def test_any_picks_two_different_real_ais():
    for seed in range(50):
        kinds = resolve_ai_kinds([RANDOM_PICK], 2, random.Random(seed))
        assert len(set(kinds)) == 2  # 同じAIを2人にしない
        assert set(kinds) <= set(PICKABLE_KINDS)  # ランダム打ちは選ばない


def test_any_covers_every_ai():
    seen = set()
    for seed in range(100):
        seen.update(resolve_ai_kinds([RANDOM_PICK], 2, random.Random(seed)))
    assert seen == set(PICKABLE_KINDS)


def test_any_mixed_with_a_fixed_ai():
    for seed in range(30):
        kinds = resolve_ai_kinds(["strong", RANDOM_PICK], 2, random.Random(seed))
        assert kinds[0] == "strong"
        assert kinds[1] in PICKABLE_KINDS and kinds[1] != "strong"


def test_fixed_kinds_pass_through():
    assert resolve_ai_kinds(["value", "defense"], 2, random.Random(0)) == ["value", "defense"]
    assert resolve_ai_kinds(["value"], 2, random.Random(0)) == ["value", "value"]


def test_parse_accepts_any():
    assert parse_ai_kinds("any") == [RANDOM_PICK]


def test_league_rejects_any():
    with pytest.raises(SystemExit):
        main(["--league", "1", "--ai", "any"])


def test_cui_announces_the_opponents(monkeypatch, capsys):
    def fake_input(prompt=""):
        raise EOFError  # 最初の入力で止める。表示だけ確かめる

    monkeypatch.setattr("builtins.input", fake_input)
    with pytest.raises(EOFError):
        main(["--cui", "--ai", "any", "--seed", "3"])
    assert "対戦相手:" in capsys.readouterr().out
