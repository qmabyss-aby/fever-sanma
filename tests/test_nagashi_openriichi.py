"""流し満貫（CLAUDE.md §4.6）とオープン立直（§4.2）のテスト。"""

import random

import pytest

from fever_sanma.core import tiles as t
from fever_sanma.core.game import ActionType, Round
from fever_sanma.core.hand import Hand
from fever_sanma.core.score import counted_yakuman_multiplier, win_transfers
from fever_sanma.core.yaku import WinContext, evaluate
from fever_sanma.core.yaku_special import (
    is_nagashi_mangan,
    nagashi_dora,
    nagashi_value,
)

YAOCHU = t.parse_tiles("19m 19p 19s 1234567z")


def names(value):
    return {y.name for y in value.yaku}


class TestNagashiDetection:
    def test_all_terminals_and_honors(self):
        assert is_nagashi_mangan(YAOCHU, discards_were_called=False)

    def test_one_simple_tile_breaks_it(self):
        assert not is_nagashi_mangan([*YAOCHU, t.pin(5)], discards_were_called=False)

    def test_being_called_breaks_it(self):
        # 抜いた北をポン・カンされた場合も鳴かれたとみなす（CLAUDE.md §4.6）
        assert not is_nagashi_mangan(YAOCHU, discards_were_called=True)

    def test_empty_discards_is_not_nagashi(self):
        assert not is_nagashi_mangan([], discards_were_called=False)

    @pytest.mark.parametrize("tile", [t.pin(2), t.sou(8), t.pin(5)])
    def test_simple_tiles_are_not_yaochu(self, tile):
        assert not is_nagashi_mangan([tile], discards_were_called=False)

    @pytest.mark.parametrize("tile", [t.man(1), t.man(9), t.PEI, t.CHUN, t.pin(9)])
    def test_yaochu_tiles_accepted(self, tile):
        assert is_nagashi_mangan([tile], discards_were_called=False)


class TestNagashiDora:
    def test_permanent_dora_in_discards(self):
        # 捨て牌にある 1m・9m・北 は常時ドラ
        assert nagashi_dora([t.man(1), t.man(9), t.PEI], kita=0, dora_indicators=()) == 3

    def test_kita_nuki_counts(self):
        # 抜いた北の枚数もドラとして加算（CLAUDE.md §4.6）
        assert nagashi_dora([t.pin(1)], kita=2, dora_indicators=()) == 2

    def test_indicator_dora_in_discards(self):
        # ドラ表示牌が 9p ならドラは 1p
        assert nagashi_dora([t.pin(1), t.pin(1)], kita=0, dora_indicators=(t.pin(9),)) == 2

    def test_sha_indicator_doubles_kita(self):
        # ドラ表示牌が西なら北はダブドラ
        assert nagashi_dora([], kita=2, dora_indicators=(t.SHA,)) == 4

    def test_hand_tiles_are_not_counted(self):
        # 手牌ではなく河を数えるのが流し満貫の特徴
        assert nagashi_dora([], kita=0, dora_indicators=(t.pin(9),)) == 0


class TestNagashiValue:
    def test_five_han(self):
        value = nagashi_value([t.pin(1)], kita=0, dora_indicators=())
        assert "流し満貫" in names(value)
        assert value.han == 5

    def test_dora_added_on_top(self):
        value = nagashi_value([t.man(1), t.man(9)], kita=1, dora_indicators=())
        assert value.dora == 3
        assert value.han == 8  # 5翻 + ドラ3 → 倍満

    def test_child_mangan_payout(self):
        value = nagashi_value([t.pin(1)], kita=0, dora_indicators=())
        payments = win_transfers(value, winner=1, dealer=0, is_tsumo=True)
        # 満貫ツモ: 親4,000 + 子2,000
        assert payments.get(1) == 6000

    def test_satisfies_binding(self):
        # 5翻役なので常に二翻縛りを満たす
        assert nagashi_value([t.pin(1)], kita=0, dora_indicators=()).satisfies_binding


class TestNagashiInRound:
    def test_ryuukyoku_becomes_a_win(self):
        game = Round(dealer=0, rng=random.Random(1))
        game.players[1].discards = list(YAOCHU)
        game.players[0].discards = [t.pin(5)]
        game.players[2].discards = [t.pin(5)]
        game._finish_draw()

        result = game.result
        assert result.kind == "win"
        assert result.winners == [1]
        assert "流し満貫" in names(result.values[1])
        # ツモ和了なので他家2人から取る
        assert result.payments.get(1) > 0
        assert result.payments.get(0) < 0
        assert result.payments.get(2) < 0

    def test_called_discards_fall_back_to_noten(self):
        game = Round(dealer=0, rng=random.Random(1))
        game.players[1].discards = list(YAOCHU)
        game.players[1].discards_were_called = True
        game._finish_draw()
        assert game.result.kind == "draw"

    def test_dealer_keeps_on_own_nagashi(self):
        game = Round(dealer=0, rng=random.Random(1))
        game.players[0].discards = list(YAOCHU)
        game.players[1].discards = [t.pin(5)]
        game.players[2].discards = [t.pin(5)]
        game._finish_draw()
        assert game.result.dealer_kept


# --- オープン立直 -----------------------------------------------------------

PINFU_HAND = "234p 567p 234s 678s 55s"
WIN_TILE = t.sou(8)


def open_riichi_ctx(**kwargs):
    hand = Hand.from_counts(t.counts_of(PINFU_HAND))
    base = dict(
        hand=hand,
        win_tile=WIN_TILE,
        seat_wind=t.NAN,
        is_riichi=True,
        is_open_riichi=True,
    )
    base.update(kwargs)
    base.setdefault("is_tsumo", False)
    return WinContext(**base)


RIICHI_NAMES = {"立直", "ダブル立直", "オープン立直", "フィーバー立直", "ダブルフィーバー立直"}


def riichi_total(value):
    """立直系だけの合計翻数。

    立直系は「通常の立直1翻 + 種類ごとの上乗せ」で数えるので、
    個々の Yaku の翻数ではなく合計を見る（CLAUDE.md §4.5）。
    """
    return sum(y.han for y in value.yaku if y.name in RIICHI_NAMES)


class TestOpenRiichi:
    def test_tsumo_is_two_han(self):
        value = evaluate(open_riichi_ctx(is_tsumo=True))
        assert "オープン立直" in names(value)
        assert riichi_total(value) == 2

    def test_ron_from_non_riichi_is_thirteen_han(self):
        value = evaluate(open_riichi_ctx(is_tsumo=False, discarder_was_riichi=False))
        assert riichi_total(value) == 13

    def test_ron_from_riichi_player_is_two_han(self):
        # リーチ済みの者が放銃した場合は2翻役扱い（CLAUDE.md §4.2）
        value = evaluate(open_riichi_ctx(is_tsumo=False, discarder_was_riichi=True))
        assert riichi_total(value) == 2

    def test_is_built_on_top_of_plain_riichi(self):
        # オープン立直は「通常の立直 +1翻」。合わせて2翻で、3翻にはならない。
        value = evaluate(open_riichi_ctx(is_tsumo=True))
        assert {"立直", "オープン立直"} <= names(value)
        assert riichi_total(value) == 2
        assert "ダブル立直" not in names(value)

    def test_ron_reaches_yakuman_territory(self):
        # 13翻 + 平和1翻 = 14翻 → 数え役満
        value = evaluate(open_riichi_ctx(is_tsumo=False))
        assert value.han >= 13
        assert counted_yakuman_multiplier(value.han) >= 1

    def test_double_yakuman_with_seven_more_han(self):
        # 「他に7翻以上の役があればダブル役満放銃もありうる」（CLAUDE.md §4.2）
        hand = Hand.from_counts(t.counts_of("123456789p 234p 55p"))
        ctx = WinContext(
            hand=hand,
            win_tile=t.pin(5),
            is_tsumo=False,
            seat_wind=t.NAN,
            is_riichi=True,
            is_open_riichi=True,
        )
        value = evaluate(ctx)
        # オープン立直13 + 清一色6 + 一気通貫2 = 21翻
        assert value.han >= 20
        assert counted_yakuman_multiplier(value.han) == 2

    def test_normal_riichi_unaffected(self):
        hand = Hand.from_counts(t.counts_of(PINFU_HAND))
        ctx = WinContext(
            hand=hand, win_tile=WIN_TILE, is_tsumo=False, seat_wind=t.NAN, is_riichi=True
        )
        value = evaluate(ctx)
        assert "立直" in names(value)
        assert "オープン立直" not in names(value)
        assert riichi_total(value) == 1


class TestOpenRiichiAction:
    def test_offered_alongside_normal_riichi(self):
        for seed in range(60):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            for _ in range(400):
                decision = game.decision()
                if decision is None:
                    break
                riichi = [a for a in decision.actions if a.type is ActionType.RIICHI]
                if riichi:
                    opens = [
                        a for a in decision.actions if a.type is ActionType.OPEN_RIICHI
                    ]
                    assert {a.tile for a in opens} == {a.tile for a in riichi}
                    return
                game.apply(decision.actions[0])
        pytest.skip("この範囲のシードでは立直の機会が無かった")

    def test_declaring_open_riichi_sets_the_flag(self):
        for seed in range(60):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            for _ in range(400):
                decision = game.decision()
                if decision is None:
                    break
                opens = [a for a in decision.actions if a.type is ActionType.OPEN_RIICHI]
                if opens:
                    seat = decision.seat
                    game.apply(opens[0])
                    assert game.players[seat].riichi
                    assert game.players[seat].open_riichi
                    return
                game.apply(decision.actions[0])
        pytest.skip("この範囲のシードでは立直の機会が無かった")
