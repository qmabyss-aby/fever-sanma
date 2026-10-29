"""面子分解・向聴数・待ちのテスト。

萬子に順子が作れないこと、そして「全パターン分解」が本当に全部出ることを重点的に固定する。
後者はフィーバーリーチの確定暗刻判定（フェーズ6）の土台になる。
"""

import random

import pytest

from fever_sanma.core import tiles as t
from fever_sanma.core.hand import (
    BlockKind,
    Hand,
    Meld,
    MeldType,
    all_decompositions,
    decompose_standard,
    is_chiitoitsu,
    is_complete,
    is_kokushi,
    winning_tiles,
)
from fever_sanma.core.shanten import (
    _standard_shanten_bruteforce,
    chiitoitsu_shanten,
    is_tenpai,
    kokushi_shanten,
    shanten,
    standard_shanten,
    ukeire,
    waits,
)


def hand_of(notation: str, melds=(), kita: int = 0) -> Hand:
    return Hand.from_counts(t.counts_of(notation), melds, kita)


def near_complete(rng: random.Random) -> list[int]:
    """完成形（4面子1雀頭）から1枚抜き、半分の確率でさらに1枚を別の牌に替えた13枚。

    ランダムな13枚ではテンパイがほとんど出ないので、テンパイ前後の形を作って試す。
    """
    while True:
        counts = [0] * t.NUM_KINDS
        for _ in range(4):
            if rng.random() < 0.5:
                start = rng.choice([s for s in range(t.NUM_KINDS) if t.can_form_run(s)])
                for tile in (start, start + 1, start + 2):
                    counts[tile] += 1
            else:
                counts[rng.randrange(t.NUM_KINDS)] += 3
        counts[rng.randrange(t.NUM_KINDS)] += 2
        if max(counts) > 4:
            continue
        held = [tile for tile in range(t.NUM_KINDS) for _ in range(counts[tile])]
        counts[rng.choice(held)] -= 1
        if rng.random() < 0.5:
            held = [tile for tile in range(t.NUM_KINDS) for _ in range(counts[tile])]
            counts[rng.choice(held)] -= 1
            extra = rng.randrange(t.NUM_KINDS)
            if counts[extra] == 4:
                continue
            counts[extra] += 1
        return counts


class TestDecomposition:
    def test_simple_hand_has_one_decomposition(self):
        blocks = decompose_standard(t.counts_of("123456789p 11z 456s"))
        assert len(blocks) == 1
        kinds = sorted(b.kind for b in blocks[0])
        assert kinds == [BlockKind.PAIR, BlockKind.RUN, BlockKind.RUN, BlockKind.RUN, BlockKind.RUN]

    def test_multiple_decompositions_are_all_returned(self):
        # 111222333p は「刻子3つ」とも「順子3つ」とも取れる
        results = decompose_standard(t.counts_of("111222333p 99p"))
        shapes = {tuple(sorted((b.kind, b.tile) for b in blocks)) for blocks in results}
        assert len(shapes) == 2

    def test_manzu_1_and_9_are_not_a_run(self):
        # 1m 9m は隣接インデックスだが順子ではない
        assert decompose_standard(t.counts_of("19m 1p 11z")) == []
        results = decompose_standard(t.counts_of("111m 999m 111p 222p 33p"))
        assert len(results) == 1
        assert all(b.kind != BlockKind.RUN for b in results[0])

    def test_wrong_length_returns_empty(self):
        assert decompose_standard(t.counts_of("123p")) == []

class TestWikiFeverHands:
    """CLAUDE.md §4.5 のフィーバーリーチ成立/不成立例。

    フェーズ6の「確定暗刻」判定の土台になるので、分解の段階で違いが出ることを固定する。
    """

    def test_confirmed_ankou_hand(self):
        """東東 123456s 777s 2p3p → 7s は必ず暗刻。"""
        hand = hand_of("23p 123456777s 11z")
        assert sum(hand.concealed) == 13
        assert set(winning_tiles(hand)) == {t.pin(1), t.pin(4)}
        # どの和了牌で和了しても 777s は暗刻のまま
        for win in winning_tiles(hand):
            probe = hand.copy()
            probe.add(win)
            for blocks in all_decompositions(probe):
                assert any(
                    b.kind == BlockKind.TRIPLET and b.tile == t.sou(7) for b in blocks
                ), f"{win} で和了したとき 7s が暗刻でない分解がある"

    def test_unconfirmed_ankou_hand(self):
        """南南 111p 12356777s → 南で和了すると 7s は暗刻にならない。"""
        hand = hand_of("111p 12356777s 22z")
        assert sum(hand.concealed) == 13
        # 4s でも和了できる（123s + 456s + 777s）。南は7sとのシャンポン。
        assert set(winning_tiles(hand)) == {t.sou(4), t.sou(7), t.NAN}
        # 南で和了すると 南南南 + 77s雀頭 になり、7s が暗刻にならない分解が存在する
        probe = hand.copy()
        probe.add(t.NAN)
        assert any(
            not any(b.kind == BlockKind.TRIPLET and b.tile == t.sou(7) for b in blocks)
            for blocks in all_decompositions(probe)
        )

    def test_double_fever_hand(self):
        """東東 23s 777s 123p 777p → 7p と 7s の両方が確定暗刻。"""
        hand = hand_of("123777p 23777s 11z")
        assert sum(hand.concealed) == 13
        assert set(winning_tiles(hand)) == {t.sou(1), t.sou(4)}
        for win in winning_tiles(hand):
            probe = hand.copy()
            probe.add(win)
            for blocks in all_decompositions(probe):
                triplets = {b.tile for b in blocks if b.kind == BlockKind.TRIPLET}
                assert {t.pin(7), t.sou(7)} <= triplets


class TestCompleteShapes:
    def test_chiitoitsu(self):
        assert is_chiitoitsu(t.counts_of("11p 33p 55p 77p 99p 11s 33s"))
        # 4枚使いは七対子にしない
        assert not is_chiitoitsu(t.counts_of("1111p 33p 55p 77p 99p 11s"))

    def test_kokushi_uses_13_kinds(self):
        # 么九牌13種すべて + 東の重複
        assert is_kokushi(t.counts_of("19m 19p 19s 11234567z"))
        assert not is_kokushi(t.counts_of("19m 19p 19s 1234567z 5p"))

    def test_is_complete_with_melds(self):
        hand = hand_of("77p 123s", melds=[Meld(MeldType.PON, t.TON, called_from=1)] * 1)
        # 3面子1雀頭に足りないので未完成
        assert not is_complete(hand)

    def test_is_complete_full_hand(self):
        melds = [
            Meld(MeldType.PON, t.TON, called_from=1),
            Meld(MeldType.CHI, t.pin(1), called_from=2),
            Meld(MeldType.PON, t.HAKU, called_from=1),
        ]
        assert is_complete(hand_of("123s 77p", melds=melds))


class TestWinningTiles:
    def test_tanki(self):
        melds = [
            Meld(MeldType.PON, t.TON, called_from=1),
            Meld(MeldType.PON, t.HAKU, called_from=1),
            Meld(MeldType.PON, t.HATSU, called_from=1),
            Meld(MeldType.PON, t.CHUN, called_from=1),
        ]
        hand = hand_of("7p", melds=melds)
        assert winning_tiles(hand) == [t.pin(7)]

    def test_ryanmen(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        assert winning_tiles(hand) == [t.sou(3), t.sou(6)]

    def test_shanpon(self):
        hand = hand_of("11z 123p 456p 789p 55s")
        assert set(winning_tiles(hand)) == {t.TON, t.sou(5)}

    def test_kokushi_13_wait(self):
        hand = hand_of("19m 19p 19s 1234567z")
        assert set(winning_tiles(hand)) == t.TERMINALS_AND_HONORS

    def test_no_wait_when_all_four_in_hand(self):
        # 手の内に4枚ある牌は5枚目が存在しないので待ちにならない
        hand = hand_of("1111p 123s 456s 789s 9p")
        assert t.pin(1) not in winning_tiles(hand)


class TestStandardShanten:
    @pytest.mark.parametrize(
        "notation, expected",
        [
            ("11z 123p 456p 789p 456s", -1),  # 和了形（14枚）
            ("11z 123p 456p 789p 45s", 0),  # テンパイ
            ("123p 456p 789p 123s 4s", 0),  # 単騎テンパイ（13枚）
            ("11z 123p 456p 78p 45s", 1),
        ],
    )
    def test_known_shanten(self, notation, expected):
        assert standard_shanten(t.counts_of(notation)) == expected

    def test_called_melds_counted(self):
        # 副露3つ + 手の内4枚（1面子 + 単騎待ち）でテンパイ
        assert standard_shanten(t.counts_of("123p 7s"), called_melds=3) == 0

    def test_worst_hand(self):
        # 孤立牌ばかりの13枚は8向聴
        assert standard_shanten(t.counts_of("19m 147p 258s 1234z")) == 8

    @pytest.mark.parametrize(
        "notation, called, expected",
        [
            # 3面子 + 2搭子で雀頭なし → 搭子の片方を雀頭に変える必要があるので1向聴
            ("123p 456p 789s 24s 68s", 0, 1),
            ("123p 456p 789s 23s 67s", 0, 1),
            # 実際に GUI で立直ボタンが出てしまった手（暗槓8索 + 2468p 4567s 77s）
            ("2468p 456777s", 1, 1),
            # 雀頭があれば同じ数の搭子でもテンパイ
            ("123p 456p 789s 24s 66s", 0, 0),
        ],
    )
    def test_no_head_with_too_many_partials(self, notation, called, expected):
        counts = t.counts_of(notation)
        assert standard_shanten(counts, called) == expected
        assert _standard_shanten_bruteforce(counts, called) == expected

    def test_fast_matches_bruteforce(self):
        rng = random.Random(7)
        for _ in range(300):
            counts = near_complete(rng)
            assert standard_shanten(counts) == _standard_shanten_bruteforce(counts)

    def test_manzu_pair_is_not_a_ryanmen(self):
        # 1m9m は搭子にならない。字牌だらけの手と同じ扱いになること
        with_manzu = standard_shanten(t.counts_of("19m 147p 258s 1234z"))
        with_honors = standard_shanten(t.counts_of("11z 147p 258s 2345z"))
        assert with_manzu >= with_honors


class TestSpecialShanten:
    def test_chiitoitsu(self):
        assert chiitoitsu_shanten(t.counts_of("11p 33p 55p 77p 99p 11s 3s")) == 0
        assert chiitoitsu_shanten(t.counts_of("11p 33p 55p 77p 99p 13s 5s")) == 1

    def test_chiitoitsu_needs_seven_kinds(self):
        # 4枚使いは対子2つとして数えない
        assert chiitoitsu_shanten(t.counts_of("1111p 3333p 5555p 7p")) > 0

    def test_kokushi(self):
        assert kokushi_shanten(t.counts_of("19m 19p 19s 1234567z")) == 0
        assert kokushi_shanten(t.counts_of("19m 19p 19s 112345z")) == 1


class TestHandShanten:
    def test_menzen_uses_chiitoitsu(self):
        hand = hand_of("11p 33p 55p 77p 99p 11s 3s")
        assert shanten(hand) == 0
        assert is_tenpai(hand)

    def test_open_hand_ignores_chiitoitsu(self):
        melds = [Meld(MeldType.PON, t.TON, called_from=1)]
        hand = hand_of("11p 33p 55p 77p 3s", melds=melds)
        assert shanten(hand) > 0

    def test_ankan_keeps_menzen_but_blocks_chiitoitsu(self):
        hand = hand_of("11p 33p 55p 77p 3s", melds=[Meld(MeldType.ANKAN, t.pin(9))])
        assert hand.is_menzen
        assert shanten(hand) == standard_shanten(hand.concealed, 1)

    def test_waits_matches_winning_tiles(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        assert waits(hand) == winning_tiles(hand)

    def test_tenpai_iff_some_tile_completes(self):
        """テンパイ判定（向聴数）と待ち判定（和了形の分解）は別の実装なので、互いに検算になる。

        例外は「待ちが手の内で4枚使い切っている牌だけ」の形。向聴数ではテンパイだが、
        5枚目がないので和了牌はない。
        """
        rng = random.Random(11)
        seen_tenpai = 0
        for _ in range(3000):
            hand = Hand.from_counts(near_complete(rng))
            tenpai = is_tenpai(hand)
            seen_tenpai += tenpai
            if tenpai and not winning_tiles(hand):
                assert any(c == 4 for c in hand.concealed), hand.concealed
            else:
                assert tenpai == bool(winning_tiles(hand)), hand.concealed
        assert seen_tenpai


class TestUkeire:
    """有効牌の計算。強い CPU を書くときの土台になる。"""

    def test_tenpai_ukeire_matches_waits(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        assert set(ukeire(hand)) == set(waits(hand))

    def test_counts_remaining_copies(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        # 手の内に無い 3s・6s は4枚とも残っている
        assert ukeire(hand)[t.sou(3)] == 4
        assert ukeire(hand)[t.sou(6)] == 4

    def test_visible_tiles_reduce_the_count(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        visible = list(hand.concealed)
        visible[t.sou(3)] = 3  # 河などで3枚見えている
        assert ukeire(hand, visible)[t.sou(3)] == 1

    def test_fully_visible_tile_is_dropped(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        visible = list(hand.concealed)
        visible[t.sou(3)] = 4
        assert t.sou(3) not in ukeire(hand, visible)

    def test_one_shanten_hand_has_ukeire(self):
        hand = hand_of("11z 123p 456p 78p 455s")
        assert sum(hand.concealed) == 13
        assert shanten(hand) == 1
        # 78p を埋める 6p・9p が有効牌に入る
        assert {t.pin(6), t.pin(9)} <= set(ukeire(hand))


class TestHandProperties:
    def test_ankan_is_not_an_open_meld(self):
        # 脊髄は「4副露で裸単騎」。暗槓は副露に数えない（CLAUDE.md §4.5）
        hand = hand_of("7p", melds=[Meld(MeldType.ANKAN, t.pin(9))] * 4)
        assert hand.open_meld_count == 0
        assert hand.is_menzen
        assert hand.is_tanki_only

    def test_open_melds_counted(self):
        melds = [Meld(MeldType.PON, t.TON, called_from=1)] * 3 + [Meld(MeldType.ANKAN, t.pin(9))]
        hand = hand_of("7p", melds=melds)
        assert hand.open_meld_count == 3
        assert not hand.is_menzen
        assert hand.kan_count == 1
