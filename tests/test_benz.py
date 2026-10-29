"""ベンツと脊髄のテスト。

ベンツは CLAUDE.md §4.5 の例（ドラ11 → ×3 = 33 → +ベンツ2翻 = 35翻 →
トリプル役満）をそのまま検算する。
"""

from fever_sanma.core import tiles as t
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.score import counted_yakuman_multiplier
from fever_sanma.core.yaku import WinContext, count_dora, evaluate
from fever_sanma.core.yaku_special import (
    YAKU_BENZ,
    YAKU_SEKIZUI,
    dora_multiplier,
    extra_yaku_for_win,
    has_benz,
    has_sekizui,
)


def hand_of(notation="", melds=(), kita=0):
    return Hand.from_counts(t.counts_of(notation) if notation else [0] * 27, melds, kita)


class TestBenz:
    def test_ankan_of_8s(self):
        hand = hand_of(melds=[Meld(MeldType.ANKAN, t.sou(8))])
        assert has_benz(hand)
        assert dora_multiplier(hand) == 3

    def test_minkan_and_kakan_also_count(self):
        # 暗槓・大明槓・加槓いずれも可（CLAUDE.md §4.5）
        for kind in (MeldType.MINKAN, MeldType.KAKAN):
            hand = hand_of(melds=[Meld(kind, t.sou(8), called_from=1)])
            assert has_benz(hand)

    def test_pon_of_8s_is_not_benz(self):
        hand = hand_of(melds=[Meld(MeldType.PON, t.sou(8), called_from=1)])
        assert not has_benz(hand)

    def test_8p_kan_is_not_benz(self):
        # ※⑧では不成立（CLAUDE.md §4.5）
        hand = hand_of(melds=[Meld(MeldType.ANKAN, t.pin(8))])
        assert not has_benz(hand)
        assert dora_multiplier(hand) == 1

    def test_no_kan_no_benz(self):
        assert not has_benz(hand_of("123p"))


class TestBenzWikiExample:
    """CLAUDE.md §4.5 のベンツ例。

        東東 999m 8888s(暗槓) 北北(2枚抜き) + 面子
        ドラ表示牌 7s, 西

        ドラ = 999m(3) + 8888s(4) + 北北(北はダブドラなので4) = 11
        ベンツ効果で 11×3 = 33 → +ベンツ2翻 = 35翻 → トリプル役満
    """

    def build(self):
        # 999m(3) + 8888s(暗槓) + 北抜き2枚 + 東東雀頭 + 適当な2面子
        melds = [Meld(MeldType.ANKAN, t.sou(8))]
        hand = Hand.from_counts(t.counts_of("999m 123p 456p 11z"), melds, kita=2)
        return WinContext(
            hand=hand,
            win_tile=t.pin(6),
            is_tsumo=False,
            seat_wind=t.NAN,
            dora_indicators=(t.sou(7), t.SHA),  # ドラは 8s と 北
            dora_multiplier=3,
            extra_yaku=(YAKU_BENZ,),
        )

    def test_dora_count_is_11_before_multiplier(self):
        ctx = self.build()
        ctx.dora_multiplier = 1
        # 999m=3, 8888s=4, 北2枚(常時1 + 表1 のダブドラ)=4 → 合計11
        assert count_dora(ctx) == 11

    def test_benz_triples_dora_to_33(self):
        assert count_dora(self.build()) == 33

    def test_total_is_35_han_triple_yakuman(self):
        value = evaluate(self.build())
        assert value.dora == 33
        assert "ベンツ" in {y.name for y in value.yaku}
        assert value.han == 35
        assert counted_yakuman_multiplier(value.han) == 3  # トリプル役満


class TestSekizui:
    def test_four_open_melds_with_tanki(self):
        # 4副露して裸単騎。和了形では手の内は雀頭の2枚。
        melds = [Meld(MeldType.PON, t.TON, called_from=1)] * 2 + [
            Meld(MeldType.CHI, t.pin(1), called_from=2)
        ] * 2
        assert has_sekizui(hand_of("99p", melds=melds))

    def test_ankan_does_not_count_as_open_meld(self):
        # 暗槓は副露に数えない（CLAUDE.md §4.5）
        melds = [Meld(MeldType.ANKAN, t.pin(1))] * 4
        assert not has_sekizui(hand_of("99p", melds=melds))

    def test_three_melds_is_not_sekizui(self):
        melds = [Meld(MeldType.PON, t.TON, called_from=1)] * 3
        assert not has_sekizui(hand_of("99p 123s", melds=melds))

    def test_mixed_ankan_breaks_sekizui(self):
        melds = [Meld(MeldType.PON, t.TON, called_from=1)] * 3 + [
            Meld(MeldType.ANKAN, t.pin(1))
        ]
        assert not has_sekizui(hand_of("99p", melds=melds))

    def test_sekizui_is_13_han(self):
        assert YAKU_SEKIZUI.han == 13
        assert counted_yakuman_multiplier(YAKU_SEKIZUI.han) == 1


class TestStacking:
    def test_benz_and_sekizui_stack(self):
        # ベンツ × 脊髄 は重複可（CLAUDE.md §4.5）
        melds = [Meld(MeldType.MINKAN, t.sou(8), called_from=1)] + [
            Meld(MeldType.PON, t.TON, called_from=1)
        ] * 3
        hand = hand_of("99p", melds=melds)
        found = {y.name for y in extra_yaku_for_win(hand)}
        assert found == {"ベンツ", "脊髄"}

    def test_fever_and_benz_stack(self):
        # フィーバー立直 × ベンツ は重複可（CLAUDE.md §4.5）
        from fever_sanma.core.yaku_special import YAKU_FEVER

        hand = hand_of("99p", melds=[Meld(MeldType.ANKAN, t.sou(8))])
        found = {y.name for y in extra_yaku_for_win(hand, fever=YAKU_FEVER)}
        assert found == {"フィーバー立直", "ベンツ"}
