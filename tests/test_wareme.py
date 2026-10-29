"""割れ目・ご祝儀・飛び・順位点のテスト。

CLAUDE.md §4.9 の検算表をそのままテストにする。この5ケースが通れば、
「割れ目の人が関わる点数移動をすべて3倍にする」という一般則が Wiki の点数表と
一致していることになる。
"""

import pytest

from fever_sanma.core.score import (
    Payments,
    apply_wareme,
    counted_yakuman_multiplier,
    final_scores,
    is_bust,
    settle_noten,
    settle_win,
    tobi_bonus,
    win_transfers,
    yakuman_bonus,
)
from fever_sanma.core.yaku import HandValue, Yaku

DEALER = 0
CHILD1 = 1
CHILD2 = 2

MANGAN = HandValue(han=5, fu=30)
"""満貫（基本点2,000）。§4.9 の検算表はすべて満貫で書かれている。"""


def deltas(payments: Payments) -> dict[int, int]:
    return {seat: payments.get(seat) for seat in range(3)}


class TestWaremeTableFromWiki:
    """CLAUDE.md §4.9 の検算表。親が割れ目、満貫。"""

    def test_dealer_tsumo(self):
        # 親がツモ: 親 +24,000 / 子1 −12,000 / 子2 −12,000
        p = settle_win(MANGAN, winner=DEALER, dealer=DEALER, is_tsumo=True, wareme=DEALER)
        assert deltas(p) == {DEALER: 24000, CHILD1: -12000, CHILD2: -12000}

    def test_dealer_ron_from_child1(self):
        # 親がロン（子1放銃）: 親 +36,000 / 子1 −36,000 / 子2 0
        p = settle_win(
            MANGAN, winner=DEALER, dealer=DEALER, is_tsumo=False, discarder=CHILD1, wareme=DEALER
        )
        assert deltas(p) == {DEALER: 36000, CHILD1: -36000, CHILD2: 0}

    def test_child1_tsumo(self):
        # 子1がツモ: 親 −12,000 / 子1 +14,000 / 子2 −2,000
        # 親への支払いだけが3倍。子2との移動（2,000）はそのまま。
        p = settle_win(MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=True, wareme=DEALER)
        assert deltas(p) == {DEALER: -12000, CHILD1: 14000, CHILD2: -2000}

    def test_child1_ron_from_dealer(self):
        # 子1が親からロン: 親 −24,000 / 子1 +24,000 / 子2 0
        p = settle_win(
            MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=DEALER, wareme=DEALER
        )
        assert deltas(p) == {DEALER: -24000, CHILD1: 24000, CHILD2: 0}

    def test_child1_ron_from_child2(self):
        # 子1が子2からロン: 親 0 / 子1 +8,000 / 子2 −8,000（割れ目は無関係）
        p = settle_win(
            MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2, wareme=DEALER
        )
        assert deltas(p) == {DEALER: 0, CHILD1: 8000, CHILD2: -8000}


class TestWaremeGeneral:
    def test_no_wareme_is_plain(self):
        p = settle_win(MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=True)
        assert deltas(p) == {DEALER: -4000, CHILD1: 6000, CHILD2: -2000}

    def test_child_wareme_on_own_tsumo(self):
        # 割れ目の子がツモ: 自分が関わる移動なので両方3倍
        p = settle_win(MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=True, wareme=CHILD1)
        assert deltas(p) == {DEALER: -12000, CHILD1: 18000, CHILD2: -6000}

    def test_uninvolved_wareme_changes_nothing(self):
        # 割れ目が関わらない放銃は素の点数のまま
        plain = settle_win(
            MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2
        )
        with_wareme = settle_win(
            MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2, wareme=DEALER
        )
        assert deltas(plain) == deltas(with_wareme)

    def test_zero_sum(self):
        for wareme in (None, DEALER, CHILD1, CHILD2):
            p = settle_win(MANGAN, winner=CHILD2, dealer=DEALER, is_tsumo=True, wareme=wareme)
            assert p.total() == 0

    def test_riichi_sticks_are_not_tripled(self):
        # 供託は割れ目の対象外
        p = settle_win(
            MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=True, wareme=DEALER, riichi_sticks=2
        )
        assert p.get(CHILD1) == 14000 + 2000

    def test_apply_wareme_is_idempotent_on_empty(self):
        assert apply_wareme(Payments(), DEALER).total() == 0


class TestCountedYakuman:
    @pytest.mark.parametrize(
        "han, expected",
        [
            (12, 0),
            (13, 1),
            (19, 1),
            (20, 2),
            (29, 2),
            (30, 3),
            (35, 3),  # ベンツ例（CLAUDE.md §4.5）がトリプル役満になること
            (40, 4),
            (50, 5),
        ],
    )
    def test_multiplier(self, han, expected):
        assert counted_yakuman_multiplier(han) == expected


class TestYakumanBonus:
    def test_ron_bonus(self):
        value = HandValue(yaku=[Yaku("大三元", yakuman=1)], yakuman=1)
        p = yakuman_bonus(value, winner=CHILD1, is_tsumo=False, discarder=DEALER)
        assert deltas(p) == {DEALER: -40000, CHILD1: 40000, CHILD2: 0}

    def test_tsumo_bonus_split(self):
        value = HandValue(yaku=[Yaku("大三元", yakuman=1)], yakuman=1)
        p = yakuman_bonus(value, winner=CHILD1, is_tsumo=True)
        assert deltas(p) == {DEALER: -20000, CHILD1: 40000, CHILD2: -20000}

    def test_double_yakuman_doubles_bonus(self):
        value = HandValue(yaku=[Yaku("字一色", yakuman=1), Yaku("大三元", yakuman=1)], yakuman=2)
        p = yakuman_bonus(value, winner=CHILD1, is_tsumo=False, discarder=DEALER)
        assert p.get(CHILD1) == 80000

    def test_counted_yakuman_gets_no_bonus(self):
        # 数え役満ではご祝儀は発生しない（CLAUDE.md §4.8）
        value = HandValue(han=13, fu=30)
        assert yakuman_bonus(value, winner=CHILD1, is_tsumo=False, discarder=DEALER).total() == 0

    def test_bonus_is_not_affected_by_wareme(self):
        value = HandValue(yaku=[Yaku("大三元", yakuman=1)], yakuman=1)
        p = yakuman_bonus(value, winner=CHILD1, is_tsumo=False, discarder=DEALER)
        assert deltas(apply_wareme(p, DEALER)) == deltas(p)


class TestNoten:
    def test_one_tenpai(self):
        # 1人テンパイ → ノーテン2人が3,000点ずつ
        p = settle_noten([CHILD1])
        assert deltas(p) == {DEALER: -3000, CHILD1: 6000, CHILD2: -3000}

    def test_two_tenpai(self):
        # 2人テンパイ → ノーテン1人が3,000点ずつ支払う（−6,000）
        p = settle_noten([DEALER, CHILD1])
        assert deltas(p) == {DEALER: 3000, CHILD1: 3000, CHILD2: -6000}

    def test_all_tenpai_no_movement(self):
        assert settle_noten([0, 1, 2]).total() == 0
        assert settle_noten([0, 1, 2]).deltas == {}

    def test_all_noten_no_movement(self):
        assert settle_noten([]).deltas == {}

    def test_wareme_not_applied_by_default(self):
        # Wiki に罰符の割れ目扱いの記載がないため既定では倍率をかけない
        assert deltas(settle_noten([CHILD1])) == {DEALER: -3000, CHILD1: 6000, CHILD2: -3000}

    def test_wareme_can_be_opted_in(self):
        # 必要になったら呼び出し側で有効にできる、という切り替えの存在を固定しておく
        assert deltas(settle_noten([CHILD1], wareme=DEALER)) == {
            DEALER: -9000,
            CHILD1: 12000,
            CHILD2: -3000,
        }


class TestTobi:
    def test_bust_below_zero_only(self):
        # 0点ちょうどは続行、0点未満で終局（CLAUDE.md §4.8）
        assert not is_bust(0)
        assert is_bust(-100)
        assert not is_bust(100)

    def test_single_winner(self):
        p = tobi_bonus(busted=[CHILD2], winners=[CHILD1])
        assert deltas(p) == {DEALER: 0, CHILD1: 10000, CHILD2: -10000}

    def test_double_ron_splits_bonus(self):
        # ダブロンで飛んだ場合は 5,000 ずつ折半
        p = tobi_bonus(busted=[CHILD2], winners=[DEALER, CHILD1])
        assert deltas(p) == {DEALER: 5000, CHILD1: 5000, CHILD2: -10000}

    def test_no_winner_no_bonus(self):
        # ノーテン罰符で飛んだ場合はこの関数を呼ばない、が念のため
        assert tobi_bonus(busted=[CHILD2], winners=[]).total() == 0


class TestFinalScores:
    def test_rank_points_with_oka(self):
        # 25,000持ちの30,000返し、順位点 +15,000 / −5,000 / −10,000。
        # オカ 15,000 はトップに加算（ユーザー確定事項）
        result = final_scores([40000, 20000, 15000])
        assert result == [40000 - 30000 + 15000 + 15000, 20000 - 30000 - 5000, 15000 - 30000 - 10000]
        assert result == [40000, -15000, -25000]

    def test_zero_sum(self):
        assert sum(final_scores([40000, 20000, 15000])) == 0
        assert sum(final_scores([25000, 25000, 25000])) == 0

    def test_ties_broken_by_seat(self):
        result = final_scores([25000, 25000, 25000])
        assert result[0] > result[1] > result[2]


class TestBasePoints:
    def test_child_mangan_ron(self):
        p = win_transfers(MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2)
        assert p.get(CHILD1) == 8000

    def test_dealer_mangan_ron(self):
        p = win_transfers(MANGAN, winner=DEALER, dealer=DEALER, is_tsumo=False, discarder=CHILD1)
        assert p.get(DEALER) == 12000

    def test_kiriage_mangan(self):
        # 30符4翻は切り上げ満貫（ユーザー確定事項）
        value = HandValue(han=4, fu=30)
        p = win_transfers(value, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2)
        assert p.get(CHILD1) == 8000

    def test_no_kiriage_when_disabled(self):
        value = HandValue(han=4, fu=30)
        p = win_transfers(
            value, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2, kiriage=False
        )
        assert p.get(CHILD1) == 7700

    @pytest.mark.parametrize(
        "han, expected",
        [(6, 12000), (8, 16000), (11, 24000), (13, 32000)],
    )
    def test_child_limit_hands(self, han, expected):
        value = HandValue(han=han, fu=30)
        p = win_transfers(value, winner=CHILD1, dealer=DEALER, is_tsumo=False, discarder=CHILD2)
        assert p.get(CHILD1) == expected

    def test_sanma_child_tsumo_is_dealer2_child1(self):
        # 三人打ちなので子ツモは 親2 + 子1 = 6,000（満貫）。ツモ損あり。
        p = win_transfers(MANGAN, winner=CHILD1, dealer=DEALER, is_tsumo=True)
        assert deltas(p) == {DEALER: -4000, CHILD1: 6000, CHILD2: -2000}

    def test_dealer_tsumo_is_all_2x(self):
        p = win_transfers(MANGAN, winner=DEALER, dealer=DEALER, is_tsumo=True)
        assert deltas(p) == {DEALER: 8000, CHILD1: -4000, CHILD2: -4000}
