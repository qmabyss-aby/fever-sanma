"""ドラの内訳（ドラ / 裏ドラ / 抜きドラ）と、裏ドラ表示牌の表示のテスト。"""

import random

from fever_sanma.core import tiles as t
from fever_sanma.core.game import Round
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.yaku import WinContext, count_dora, dora_breakdown, evaluate, is_dora_yaku
from fever_sanma.players import RandomAgent
from fever_sanma.ui import cui

PINFU = "234p 567p 234s 678s 55s"  # 8索ロンで平和（ドラなし）


def ctx(notation=PINFU, win=t.sou(8), melds=(), kita=0, **kwargs):
    hand = Hand.from_counts(t.counts_of(notation), list(melds), kita)
    kwargs.setdefault("is_tsumo", False)
    return WinContext(hand=hand, win_tile=win, seat_wind=t.NAN, **kwargs)


def names(value):
    return [y.name for y in value.yaku]


class TestBreakdown:
    def test_each_source_is_counted_separately(self):
        c = ctx(
            "99m 234p 567p 234s 55s",
            win=t.sou(5),
            kita=1,
            is_riichi=True,
            dora_indicators=(t.pin(1),),  # 表ドラは2筒
            ura_indicators=(t.sou(4),),  # 裏ドラは5索
        )
        counts = dora_breakdown(c)
        assert counts.dora == 2 + 1  # 9萬の常時ドラ2 + 表ドラ(2筒)1
        assert counts.ura == 2  # 5索2枚
        assert counts.kita == 1  # 抜いた北1枚
        assert counts.total == count_dora(c) == 6

    def test_no_ura_without_riichi(self):
        c = ctx(ura_indicators=(t.sou(4),))
        assert dora_breakdown(c).ura == 0

    def test_omote_hit_on_nuki_kita_is_dora(self):
        # ドラ表示が西なら北はダブドラ。抜いた北の「常時ドラ」は抜きドラ、表ドラに当たったぶんはドラ
        counts = dora_breakdown(ctx(kita=2, dora_indicators=(t.SHA,)))
        assert counts.kita == 2
        assert counts.dora == 2

    def test_ura_hit_on_nuki_kita_is_ura(self):
        counts = dora_breakdown(ctx(kita=1, is_riichi=True, ura_indicators=(t.SHA,)))
        assert (counts.kita, counts.ura) == (1, 1)

    def test_benz_triples_each(self):
        c = ctx(
            "99m 123p 456p 11z",
            win=t.TON,
            melds=[Meld(MeldType.ANKAN, t.sou(8))],
            kita=1,
            dora_multiplier=3,
        )
        counts = dora_breakdown(c)
        assert (counts.dora, counts.kita) == (2 * 3, 1 * 3)


class TestYakuList:
    def test_listed_separately(self):
        value = evaluate(
            ctx(kita=1, is_riichi=True, ura_indicators=(t.sou(4),), dora_indicators=(t.pin(1),))
        )
        assert "ドラ1" in names(value)  # 2筒
        assert "裏ドラ2" in names(value)  # 5索2枚
        assert "抜きドラ1" in names(value)
        assert value.dora == 4

    def test_zero_counts_are_not_listed(self):
        value = evaluate(ctx())
        assert not [n for n in names(value) if is_dora_yaku(n)]

    def test_ura_and_kita_do_not_count_for_the_binding(self):
        # 嵌張の8索で上がるので平和は付かない。立直1翻 + 裏ドラ・抜きドラ
        # → 二翻縛りを満たさない（ドラは縛りに含めない）
        value = evaluate(
            ctx(
                "234p 567p 234s 789s 55s",
                win=t.sou(8),
                kita=1,
                is_riichi=True,
                ura_indicators=(t.sou(4),),
            )
        )
        assert value.dora >= 3
        assert value.binding_han == 1
        assert not value.satisfies_binding


class TestDisplay:
    def test_dora_yaku_show_count_only(self):
        value = evaluate(ctx(kita=1, is_riichi=True, ura_indicators=(t.sou(4),)))
        text = cui.format_value(value)
        assert "裏ドラ2" in text and "裏ドラ2(" not in text
        assert "抜きドラ1" in text

    def test_ura_indicators_only_for_riichi_winners(self):
        seen_riichi = seen_dama = False
        for seed in range(400):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            while game.decision() is not None:
                decision = game.decision()
                game.apply(agent.choose(game, decision.seat, decision.actions))
            result = game.result
            if result.kind != "win":
                continue
            riichi = any(game.players[s].riichi for s in result.winners)
            if riichi:
                assert result.ura_indicators == game.wall.ura_indicators()
                assert "裏ドラ表示" in cui.render_round_result(result)
                seen_riichi = True
            else:
                assert result.ura_indicators == []
                assert "裏ドラ表示" not in cui.render_round_result(result)
                seen_dama = True
            if seen_riichi and seen_dama:
                return
        assert seen_riichi and seen_dama, "立直の和了・ダマの和了の両方が出なかった"
