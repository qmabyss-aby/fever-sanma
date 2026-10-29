"""役判定と符計算のテスト。

通常麻雀との差異（混一色2翻・三色同順なし・東と北は全員の風牌・親のみ連風牌）を
重点的に固定する。
"""

import pytest

from fever_sanma.core import tiles as t
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.yaku import WinContext, count_dora, evaluate, yakuhai_han


def ctx(notation, win, *, melds=(), tsumo=False, seat=t.TON, kita=0, **kwargs):
    hand = Hand.from_counts(t.counts_of(notation), melds, kita)
    return WinContext(
        hand=hand, win_tile=win, is_tsumo=tsumo, seat_wind=seat, **kwargs
    )


def names(value):
    return {y.name for y in value.yaku}


def han_of(value):
    return value.han


class TestYakuhai:
    def test_east_is_two_han_for_dealer_only(self):
        # 東は常に全員の風牌。東風戦なので親だけ場風+自風で2翻（ユーザー確定事項）
        assert yakuhai_han(t.TON, seat_wind=t.TON) == 2
        assert yakuhai_han(t.TON, seat_wind=t.NAN) == 1
        assert yakuhai_han(t.TON, seat_wind=t.SHA) == 1

    def test_kita_is_one_han_for_everyone(self):
        for seat in (t.TON, t.NAN, t.SHA):
            assert yakuhai_han(t.PEI, seat_wind=seat) == 1

    def test_nan_and_sha_are_seat_winds_only(self):
        # 南家の南・西家の西は自風として認める（ユーザー確定事項）
        assert yakuhai_han(t.NAN, seat_wind=t.NAN) == 1
        assert yakuhai_han(t.NAN, seat_wind=t.SHA) == 0
        assert yakuhai_han(t.SHA, seat_wind=t.SHA) == 1
        assert yakuhai_han(t.SHA, seat_wind=t.TON) == 0

    def test_dragons_always_one_han(self):
        for tile in t.DRAGONS:
            assert yakuhai_han(tile, seat_wind=t.NAN) == 1

    def test_dealer_east_triplet_scores_two(self):
        value = evaluate(ctx("111z 123p 456p 234s 55s", t.sou(5), seat=t.TON))
        assert "役牌 東" in names(value)
        assert han_of(value) == 2

    def test_child_east_triplet_scores_one(self):
        value = evaluate(ctx("111z 123p 456p 234s 55s", t.sou(5), seat=t.NAN))
        assert han_of(value) == 1

    def test_kita_triplet_is_yakuhai_plus_dora(self):
        # 北は役牌1翻 + 常時ドラ3枚
        value = evaluate(ctx("444z 123p 456p 234s 55s", t.sou(5), seat=t.NAN))
        assert "役牌 北" in names(value)
        assert value.dora == 3
        assert han_of(value) == 4


class TestHonitsuIsTwoHan:
    def test_menzen_honitsu(self):
        # 通常麻雀では3翻だが、フィーバー三麻では2翻（CLAUDE.md §4.4）
        value = evaluate(ctx("123456789p 111z 22z", t.pin(9), seat=t.NAN))
        assert "混一色" in names(value)
        assert next(y.han for y in value.yaku if y.name == "混一色") == 2

    def test_open_honitsu_is_one_han(self):
        melds = [Meld(MeldType.PON, t.TON, called_from=1)]
        value = evaluate(ctx("123456789p 22z", t.pin(9), melds=melds, seat=t.NAN))
        assert next(y.han for y in value.yaku if y.name == "混一色") == 1

    def test_chinitsu_six_han(self):
        value = evaluate(ctx("123456789p 234p 55p", t.pin(5), seat=t.NAN))
        assert "清一色" in names(value)
        assert next(y.han for y in value.yaku if y.name == "清一色") == 6

    def test_open_chinitsu_five_han(self):
        melds = [Meld(MeldType.CHI, t.pin(1), called_from=2)]
        value = evaluate(ctx("456789p 234p 55p", t.pin(5), melds=melds, seat=t.NAN))
        assert next(y.han for y in value.yaku if y.name == "清一色") == 5


class TestNoSanshokuDoujun:
    def test_sanshoku_doujun_is_not_a_yaku(self):
        # 役一覧に三色同順は無い。萬子が1と9しかないので原理的にも作れない。
        value = evaluate(ctx("123456789p 123s 55s", t.sou(5), seat=t.NAN))
        assert "三色同順" not in names(value)

    def test_sanshoku_doukou_exists(self):
        # 三色同刻はある。萬子は1と9しかないので 111 か 999 のみ。
        value = evaluate(ctx("111m 111p 111s 123p 99p", t.pin(9), seat=t.NAN))
        assert "三色同刻" in names(value)


class TestCommonYaku:
    def test_pinfu(self):
        value = evaluate(ctx("234p 567p 234s 678s 55s", t.sou(8), seat=t.NAN))
        assert "平和" in names(value)
        assert value.fu == 30  # 平和ロンは30符

    def test_pinfu_tsumo_is_20_fu(self):
        value = evaluate(ctx("234p 567p 234s 678s 55s", t.sou(8), tsumo=True, seat=t.NAN))
        assert "平和" in names(value)
        assert value.fu == 20

    def test_kita_pair_blocks_pinfu(self):
        # 北は全員の風牌なので雀頭にすると平和にならない
        value = evaluate(ctx("234p 567p 234s 678s 44z", t.sou(8), seat=t.NAN))
        assert "平和" not in names(value)

    def test_tanyao_allows_open_hand(self):
        # 役一覧に門前限定・喰い下がりの注記がないので喰いタンあり
        melds = [Meld(MeldType.CHI, t.pin(2), called_from=2)]
        value = evaluate(ctx("567p 234s 678s 55s", t.sou(8), melds=melds, seat=t.NAN))
        assert "断幺九" in names(value)

    def test_iipeiko(self):
        value = evaluate(ctx("223344p 567p 234s 55s", t.sou(4), seat=t.NAN))
        assert "一盃口" in names(value)

    def test_ryanpeiko(self):
        value = evaluate(ctx("223344p 556677p 99p", t.pin(9), seat=t.NAN))
        assert "二盃口" in names(value)
        assert "一盃口" not in names(value)

    def test_ittsu_in_pinzu(self):
        value = evaluate(ctx("123456789p 111z 11s", t.sou(1), seat=t.NAN))
        assert "一気通貫" in names(value)

    def test_toitoi_and_sanankou(self):
        # ロンで完成した 888s は明刻になるので四暗刻ではなく三暗刻
        value = evaluate(ctx("222p 444p 666p 888s 55s", t.sou(8), seat=t.NAN))
        assert "対々和" in names(value)
        assert "三暗刻" in names(value)
        assert value.yakuman == 0

    def test_chanta(self):
        value = evaluate(ctx("123p 789p 123s 111z 99s", t.sou(9), seat=t.NAN))
        assert "混全帯幺九" in names(value)

    def test_junchan(self):
        value = evaluate(ctx("123p 789p 123s 789s 11p", t.pin(1), seat=t.NAN))
        assert "純全帯幺九" in names(value)

    def test_honroutou(self):
        # ポンを入れて四暗刻にならないようにする
        melds = [Meld(MeldType.PON, t.TON, called_from=1)]
        value = evaluate(ctx("111m 999m 222z 33z", t.SHA, melds=melds, seat=t.NAN))
        assert "混老頭" in names(value)
        assert "対々和" in names(value)

    def test_shousangen(self):
        value = evaluate(ctx("555z 666z 77z 123p 456p", t.pin(6), seat=t.NAN))
        assert "小三元" in names(value)

    def test_chiitoitsu(self):
        value = evaluate(ctx("11p 33p 55p 77p 99p 11s 33s", t.sou(3), seat=t.NAN))
        assert "七対子" in names(value)
        assert value.fu == 25


class TestYakuman:
    def test_daisangen(self):
        value = evaluate(ctx("555z 666z 777z 123p 11s", t.sou(1), seat=t.NAN))
        assert value.yakuman == 1
        assert "大三元" in names(value)

    def test_yakuman_compose(self):
        # 複数役満の複合はダブル以上になる（CLAUDE.md §4.4）。
        # 東南西北の暗刻 + 白の単騎待ちなので 大四喜 + 字一色 + 四暗刻 の3つ。
        value = evaluate(ctx("111z 222z 333z 444z 55z", t.HAKU, seat=t.NAN))
        assert {"字一色", "大四喜", "四暗刻"} == names(value)
        assert value.yakuman == 3

    def test_single_yaku_never_doubles(self):
        # 1つの役でダブル役満は採用しない。四暗刻単騎もシングル（CLAUDE.md §4.4）
        value = evaluate(ctx("111p 333p 555p 777p 99p", t.pin(9), tsumo=True, seat=t.NAN))
        assert names(value) == {"四暗刻"}
        assert value.yakuman == 1

    def test_kokushi_is_single_even_13_wait(self):
        value = evaluate(ctx("19m 19p 19s 11234567z", t.TON, seat=t.NAN))
        assert "国士無双" in names(value)
        assert value.yakuman == 1

    def test_daisharin(self):
        # 2p〜8pを2枚ずつ。鳴き不可。
        value = evaluate(ctx("22334455667788p", t.pin(8), seat=t.NAN))
        assert "大車輪" in names(value)
        assert value.yakuman == 1

    def test_daisharin_needs_pinzu(self):
        # 索子の同じ形では成立しない
        value = evaluate(ctx("22334455667788s", t.sou(8), seat=t.NAN))
        assert "大車輪" not in names(value)

    def test_ryuuiisou_allows_melds(self):
        melds = [Meld(MeldType.PON, t.sou(6), called_from=1)]
        value = evaluate(ctx("234234s 888s 66z", t.HATSU, melds=melds, seat=t.NAN))
        assert "緑一色" in names(value)

    def test_chinroutou(self):
        value = evaluate(ctx("111m 999m 111p 999p 11s", t.sou(1), seat=t.NAN))
        assert "清老頭" in names(value)

    def test_churen_in_pinzu(self):
        value = evaluate(ctx("11123455678999p", t.pin(5), seat=t.NAN))
        assert "九蓮宝燈" in names(value)
        assert value.yakuman == 1

    def test_suukantsu(self):
        melds = [
            Meld(MeldType.ANKAN, t.pin(1)),
            Meld(MeldType.ANKAN, t.pin(2)),
            Meld(MeldType.ANKAN, t.pin(3)),
            Meld(MeldType.ANKAN, t.pin(4)),
        ]
        value = evaluate(ctx("99p", t.pin(9), melds=melds, seat=t.NAN))
        assert "四槓子" in names(value)


class TestDora:
    def test_permanent_dora(self):
        # 1m・9m・北は常にドラ（CLAUDE.md §4.1）
        c = ctx("111m 999m 123p 456p 99p", t.pin(9), seat=t.NAN)
        assert count_dora(c) == 6

    def test_indicator_dora(self):
        c = ctx(
            "123456789p 123s 55s",
            t.sou(5),
            seat=t.NAN,
            dora_indicators=(t.pin(4),),  # ドラは5p
        )
        assert count_dora(c) == 1

    def test_kita_counts_as_dora_whether_in_hand_or_nuki(self):
        # 手牌で使っても抜きドラでも 1枚 = ドラ1個（CLAUDE.md §4.3）
        in_hand = ctx("444z 123456789p 11s", t.sou(1), seat=t.NAN)
        nuki = ctx("123456789p 11s 11p", t.pin(1), seat=t.NAN, kita=3)
        assert count_dora(in_hand) == 3
        assert count_dora(nuki) == 3

    def test_sha_indicator_makes_kita_double_dora(self):
        # ドラ表示牌が西なら北はダブドラ（CLAUDE.md §4.3）
        c = ctx(
            "444z 123456789p 11s",
            t.sou(1),
            seat=t.NAN,
            dora_indicators=(t.SHA,),
        )
        assert count_dora(c) == 6  # 常時3 + 表3

    def test_ura_dora_only_with_riichi(self):
        without = ctx(
            "123456789p 123s 55s", t.sou(5), seat=t.NAN, ura_indicators=(t.pin(4),)
        )
        with_riichi = ctx(
            "123456789p 123s 55s",
            t.sou(5),
            seat=t.NAN,
            is_riichi=True,
            ura_indicators=(t.pin(4),),
        )
        assert count_dora(without) == 0
        assert count_dora(with_riichi) == 1


class TestSituational:
    def test_riichi_ippatsu_tsumo(self):
        value = evaluate(
            ctx(
                "234p 567p 234s 678s 55s",
                t.sou(8),
                tsumo=True,
                seat=t.NAN,
                is_riichi=True,
                is_ippatsu=True,
            )
        )
        assert {"立直", "一発", "門前清自摸和", "平和"} <= names(value)

    def test_double_riichi_is_riichi_plus_one(self):
        # ダブル立直は「通常の立直 +1翻」なので、立直1 + ダブル立直1 = 2翻
        value = evaluate(
            ctx(
                "234p 567p 234s 678s 55s",
                t.sou(8),
                seat=t.NAN,
                is_riichi=True,
                is_double_riichi=True,
            )
        )
        assert {"立直", "ダブル立直"} <= names(value)
        riichi_han = sum(y.han for y in value.yaku if y.name in ("立直", "ダブル立直"))
        assert riichi_han == 2

    def test_haitei(self):
        value = evaluate(
            ctx("123456789p 111z 11s", t.sou(1), tsumo=True, seat=t.NAN, is_haitei=True)
        )
        assert "海底摸月" in names(value)

    def test_tenhou_is_yakuman(self):
        value = evaluate(
            ctx("123456789p 111z 11s", t.sou(1), tsumo=True, seat=t.TON, is_tenhou=True)
        )
        assert value.yakuman >= 1
        assert "天和" in names(value)


class TestFu:
    def test_menzen_ron_base(self):
        # 副底20 + 門前ロン10 + 単騎2 = 32 → 40符
        value = evaluate(ctx("123456789p 123s 55s", t.sou(5), seat=t.NAN))
        assert value.fu == 40

    def test_ankou_of_terminals(self):
        # 副底20 + 門前ロン10 + 么九暗刻8 ...
        value = evaluate(ctx("111p 234p 567p 234s 55s", t.sou(5), seat=t.NAN))
        assert value.fu == 40

    def test_chiitoitsu_is_25(self):
        value = evaluate(ctx("11p 33p 55p 77p 99p 11s 33s", t.sou(3), seat=t.NAN))
        assert value.fu == 25

    def test_ron_completed_triplet_is_open(self):
        # ロンで完成した刻子は明刻扱いなので四暗刻にならない
        ron = evaluate(ctx("111p 333p 555p 777p 99p", t.pin(7), seat=t.NAN))
        tsumo = evaluate(ctx("111p 333p 555p 777p 99p", t.pin(7), tsumo=True, seat=t.NAN))
        assert ron.yakuman == 0
        assert tsumo.yakuman == 1


class TestYakuHanExcludesDora:
    def test_yaku_han_excludes_dora(self):
        # 二翻縛りの判定はドラを含めない（CLAUDE.md §4.1）
        value = evaluate(ctx("444z 123p 456p 234s 55s", t.sou(5), seat=t.NAN))
        assert value.dora == 3
        assert value.yaku_han == 1  # 役牌 北 のみ。これだけでは二翻縛りを満たさない
        assert value.han == 4
