"""牌の表現のテスト。通常麻雀との差異（萬子が1と9のみ）を中心に固定する。"""

import pytest

from fever_sanma.core import tiles as t


class TestTileSet:
    def test_27_kinds_108_tiles(self):
        assert t.NUM_KINDS == 27
        assert t.TOTAL_TILES == 108
        full = t.build_full_set()
        assert len(full) == 108
        counts = t.to_counts(full)
        assert all(c == 4 for c in counts)

    @pytest.mark.parametrize("number", [2, 3, 4, 5, 6, 7, 8])
    def test_manzu_2_to_8_do_not_exist(self, number):
        with pytest.raises(ValueError):
            t.man(number)
        with pytest.raises(ValueError):
            t.index_of("m", number)

    def test_manzu_only_1_and_9(self):
        assert t.man(1) == 0
        assert t.man(9) == 1

    def test_index_layout(self):
        assert t.pin(1) == 2 and t.pin(9) == 10
        assert t.sou(1) == 11 and t.sou(9) == 19
        assert t.honor(1) == t.TON == 20
        assert t.honor(7) == t.CHUN == 26

    @pytest.mark.parametrize("index", range(27))
    def test_suit_number_roundtrip(self, index):
        assert t.index_of(t.suit_of(index), t.number_of(index)) == index


class TestTileSets:
    def test_terminals_and_honors_has_13_kinds(self):
        # 么九牌: 1m 9m 1p 9p 1s 9s + 字牌7種 = 13種。国士無双もこの13種で成立する。
        assert len(t.TERMINALS_AND_HONORS) == 13

    def test_simples_are_2to8_of_pin_and_sou(self):
        assert len(t.SIMPLES) == 14
        assert t.pin(5) in t.SIMPLES
        assert t.man(1) not in t.SIMPLES
        assert t.man(9) not in t.SIMPLES

    def test_permanent_dora(self):
        # 1m・9m・北は常にドラ（CLAUDE.md §4.1）
        assert t.PERMANENT_DORA == {t.man(1), t.man(9), t.PEI}

    def test_green_tiles(self):
        assert t.GREEN_TILES == {t.sou(2), t.sou(3), t.sou(4), t.sou(6), t.sou(8), t.HATSU}

    def test_daisharin_tiles(self):
        assert t.DAISHARIN_TILES == {t.pin(n) for n in range(2, 9)}


class TestRuns:
    def test_manzu_cannot_form_runs(self):
        # 2m〜8m が存在しないので萬子に順子はない
        assert not t.can_form_run(t.man(1))
        assert not t.can_form_run(t.man(9))

    def test_honors_cannot_form_runs(self):
        for index in t.HONORS:
            assert not t.can_form_run(index)

    def test_pin_sou_runs(self):
        assert t.can_form_run(t.pin(1))
        assert t.can_form_run(t.pin(7))
        assert not t.can_form_run(t.pin(8))
        assert t.can_form_run(t.sou(7))
        assert not t.can_form_run(t.sou(9))


class TestDoraIndicator:
    @pytest.mark.parametrize(
        "indicator, dora",
        [
            ("1p", "2p"),
            ("8p", "9p"),
            ("9p", "1p"),
            ("9s", "1s"),
            ("1z", "2z"),  # 東 → 南
            ("3z", "4z"),  # 西 → 北  (CLAUDE.md §4.3 のベンツ例に対応)
            ("4z", "1z"),  # 北 → 東
            ("5z", "6z"),  # 白 → 發
            ("7z", "5z"),  # 中 → 白
        ],
    )
    def test_standard_cycles(self, indicator, dora):
        (ind,) = t.parse_tiles(indicator)
        (expected,) = t.parse_tiles(dora)
        assert t.dora_from_indicator(ind) == expected

    def test_manzu_cycles_between_1_and_9(self):
        # 2m〜8m が無いので 1m↔9m で循環させる（ローカル判断）
        assert t.dora_from_indicator(t.man(1)) == t.man(9)
        assert t.dora_from_indicator(t.man(9)) == t.man(1)


class TestNotation:
    def test_parse_tiles(self):
        assert t.parse_tiles("19m") == [t.man(1), t.man(9)]
        assert t.parse_tiles("777p") == [t.pin(7)] * 3
        assert t.parse_tiles("123p 4z") == [t.pin(1), t.pin(2), t.pin(3), t.PEI]

    def test_parse_is_sorted(self):
        assert t.parse_tiles("4z 123p 9m") == sorted(t.parse_tiles("4z 123p 9m"))

    def test_parse_rejects_nonexistent_manzu(self):
        with pytest.raises(ValueError):
            t.parse_tiles("5m")

    def test_parse_rejects_trailing_digits(self):
        with pytest.raises(ValueError):
            t.parse_tiles("123")

    def test_format_roundtrip(self):
        notation = "19m 123456789p 777s 1234567z"
        assert t.format_tiles(t.parse_tiles(notation)) == notation

    def test_format_tiles_sorts(self):
        # 手牌用。順序に意味がないので並べ替える
        assert t.format_tiles([t.sou(9), t.pin(1), t.sou(1)]) == "1p 19s"

    def test_format_ordered_keeps_the_order(self):
        # 河用。捨てた順を保つ
        river = [t.sou(9), t.pin(1), t.sou(1), t.TON]
        assert t.format_ordered(river) == "9s 1p 1s 1z"

    def test_format_ordered_groups_consecutive_same_suit(self):
        assert t.format_ordered([t.pin(9), t.pin(1), t.sou(5)]) == "91p 5s"

    def test_format_ordered_empty(self):
        assert t.format_ordered([]) == ""

    def test_tile_names(self):
        assert t.tile_name(t.man(1)) == "1萬"
        assert t.tile_name(t.pin(7)) == "7筒"
        assert t.tile_name(t.PEI) == "北"
        assert t.tile_str(t.PEI) == "4z"


class TestCounts:
    def test_counts_of(self):
        counts = t.counts_of("777p 4z4z")
        assert counts[t.pin(7)] == 3
        assert counts[t.PEI] == 2
        assert sum(counts) == 5

    def test_five_of_a_kind_rejected(self):
        with pytest.raises(ValueError):
            t.counts_of("77777p")

    def test_from_counts_roundtrip(self):
        tiles = t.parse_tiles("19m 111p 777s 4z")
        assert t.from_counts(t.to_counts(tiles)) == tiles


class TestTileDataclass:
    def test_from_index(self):
        tile = t.Tile.from_index(t.pin(7))
        assert (tile.suit, tile.number) == ("p", 7)
        assert str(tile) == "7p"
        assert tile.name_ja == "7筒"

    def test_validation(self):
        with pytest.raises(ValueError):
            t.Tile("m", 5)
