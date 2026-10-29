"""山・王牌のテスト。

北抜きで王牌が減り、カンでは減らない、という点がこのルール特有で最も壊れやすい。
"""

import random

import pytest

from fever_sanma.core import tiles as t
from fever_sanma.core.wall import (
    DEAD_WALL_SIZE,
    INDICATOR_PAIRS,
    Wall,
    roll_dice,
    wareme_seat,
)


@pytest.fixture
def wall():
    return Wall(rng=random.Random(12345))


class TestSetup:
    def test_initial_sizes(self, wall):
        assert wall.dead_wall_size == DEAD_WALL_SIZE == 18
        # 108枚 - 王牌18枚 = 山牌90枚
        assert wall.remaining == 90

    def test_deal_leaves_51(self, wall):
        hands = wall.deal()
        assert len(hands) == 3
        assert all(len(h) == 13 for h in hands)
        assert wall.remaining == 90 - 39 == 51

    def test_all_108_tiles_present(self, wall):
        hands = wall.deal()
        seen = [tile for hand in hands for tile in hand]
        while wall.remaining:
            seen.append(wall.draw())
        seen.extend(wall._rinshan)
        seen.extend(wall._indicators)
        assert len(seen) == 108
        assert all(c == 4 for c in t.to_counts(seen))

    def test_rejects_wrong_tile_count(self):
        with pytest.raises(ValueError):
            Wall(tiles=[0] * 107)


class TestDora:
    def test_one_pair_revealed_initially(self, wall):
        assert wall.revealed_pairs == 1
        assert len(wall.dora_indicators()) == 1
        assert len(wall.ura_indicators()) == 1

    def test_reveal_new_dora_adds_both_omote_and_ura(self, wall):
        # カンがある場合は裏ドラも増える（ユーザー確定事項）
        wall.reveal_new_dora()
        assert wall.revealed_pairs == 2
        assert len(wall.dora_indicators()) == 2
        assert len(wall.ura_indicators()) == 2

    def test_omote_and_ura_use_separate_slots(self, wall):
        for _ in range(INDICATOR_PAIRS - 1):
            wall.reveal_new_dora()
        omote = wall.dora_indicators()
        ura = wall.ura_indicators()
        assert len(omote) == 5
        assert len(ura) == 5
        # 表5枚と裏5枚で王牌のドラ表示10枚をちょうど使い切る（同じ牌の使い回しがない）
        assert sorted(omote + ura) == sorted(wall._indicators)

    def test_cannot_reveal_more_than_five_pairs(self, wall):
        for _ in range(INDICATOR_PAIRS - 1):
            wall.reveal_new_dora()
        with pytest.raises(RuntimeError):
            wall.reveal_new_dora()


class TestKan:
    def test_kan_keeps_dead_wall_at_18(self, wall):
        before_live = wall.remaining
        wall.draw_rinshan_for_kan()
        assert wall.dead_wall_size == 18  # 山尾から補充されるので減らない
        assert wall.remaining == before_live - 1  # 補充のぶん山牌が1枚減る

    def test_four_kans_keep_dead_wall_at_18(self, wall):
        for _ in range(4):
            wall.draw_rinshan_for_kan()
        assert wall.dead_wall_size == 18
        assert wall.kita_drawn == 0

    def test_cannot_kan_when_live_wall_empty(self, wall):
        while wall.remaining:
            wall.draw()
        assert not wall.can_kan()
        with pytest.raises(RuntimeError):
            wall.draw_rinshan_for_kan()


class TestKitaNuki:
    def test_kita_shrinks_dead_wall(self, wall):
        before_live = wall.remaining
        wall.draw_rinshan_for_kita()
        # 補充しないので王牌が1枚減り、山牌は減らない（CLAUDE.md §4.1）
        assert wall.dead_wall_size == 17
        assert wall.remaining == before_live

    def test_four_kita_shrink_dead_wall_to_14(self, wall):
        # 北は全部で4枚しかないので、王牌は最小14枚
        for _ in range(4):
            wall.draw_rinshan_for_kita()
        assert wall.dead_wall_size == 14
        assert wall.kita_drawn == 4

    def test_kita_does_not_reveal_new_dora(self, wall):
        wall.draw_rinshan_for_kita()
        assert wall.revealed_pairs == 1

    def test_max_kan_and_kita_never_exhaust_rinshan(self, wall):
        # 1局で起こりうる最大: カン4回 + 北抜き4回。
        # カンは補充されるので嶺上牌は減らず、減るのは北抜きのぶんだけ。
        for _ in range(4):
            wall.draw_rinshan_for_kan()
        for _ in range(4):
            wall.draw_rinshan_for_kita()
        assert wall.dead_wall_size == 14
        assert wall.can_draw_kita()  # まだ余裕がある

    def test_rinshan_can_be_exhausted_by_kita_only(self, wall):
        # 北抜きは補充しないので、理屈のうえでは嶺上牌8枚を使い切れる
        for _ in range(8):
            wall.draw_rinshan_for_kita()
        assert not wall.can_draw_kita()
        with pytest.raises(RuntimeError):
            wall.draw_rinshan_for_kita()


class TestWareme:
    def test_dice_range(self):
        rng = random.Random(0)
        for _ in range(200):
            assert 2 <= roll_dice(rng) <= 12

    @pytest.mark.parametrize(
        "dice, dealer, expected",
        [
            (3, 0, 2),  # 親から3つ目 = 席2
            (4, 0, 0),  # 一周して親自身
            (5, 0, 1),
            (3, 1, 0),
            (7, 2, 2),  # 親(席2)から7つ目 = 一周半して席2に戻る
        ],
    )
    def test_wareme_seat(self, dice, dealer, expected):
        assert wareme_seat(dice, dealer) == expected

    def test_wareme_always_valid_seat(self):
        for dice in range(2, 13):
            for dealer in range(3):
                assert wareme_seat(dice, dealer) in (0, 1, 2)

    def test_invalid_dice(self):
        with pytest.raises(ValueError):
            wareme_seat(13, 0)
