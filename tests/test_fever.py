"""フィーバー立直 / ダブルフィーバー立直のテスト。

Wiki（CLAUDE.md §4.5）の成立例・不成立例をそのまま固定する。「確定暗刻」の判定が
この実装のいちばん難しいところなので、手厚く書く。
"""

import random

import pytest

from fever_sanma.core import tiles as t
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.yaku_special import (
    FEVER_TILES,
    fever_yaku,
    is_confirmed_ankou,
    is_junkara,
    visible_counts,
)

# Wiki の例（いずれもリーチ宣言後の13枚）
FEVER_OK = "23p 123456777s 11z"  # 東東 123456s 777s 2p3p
FEVER_NG = "111p 12356777s 22z"  # 南南 111p 12356777s
DOUBLE_FEVER = "123777p 23777s 11z"  # 東東 23s 777s 123p 777p


def hand_of(notation, melds=(), kita=0):
    return Hand.from_counts(t.counts_of(notation), melds, kita)


def open_view(hand):
    """自分の手牌しか見えていない状態（純カラでない）。"""
    return visible_counts(hand, discards=[[], [], []])


class TestConfirmedAnkou:
    def test_wiki_success_example(self):
        # 東東 123456s 777s 2p3p → 7s は必ず暗刻
        hand = hand_of(FEVER_OK)
        assert is_confirmed_ankou(hand, t.sou(7))

    def test_wiki_failure_example(self):
        # 南南 111p 12356777s → 南で和了すると 77s が雀頭になる
        hand = hand_of(FEVER_NG)
        assert not is_confirmed_ankou(hand, t.sou(7))

    def test_double_fever_example(self):
        hand = hand_of(DOUBLE_FEVER)
        assert is_confirmed_ankou(hand, t.pin(7))
        assert is_confirmed_ankou(hand, t.sou(7))

    def test_ankan_is_always_confirmed(self):
        hand = hand_of("11z 123p 456p 78p", melds=[Meld(MeldType.ANKAN, t.sou(7))])
        assert is_confirmed_ankou(hand, t.sou(7))

    def test_needs_three_in_hand(self):
        # 2枚しかないシャンポン待ちは「確定暗刻」ではない
        hand = hand_of("11z 123p 456p 789p 77s")
        assert hand.concealed[t.sou(7)] == 2
        assert not is_confirmed_ankou(hand, t.sou(7))

    def test_not_confirmed_when_no_such_tile(self):
        hand = hand_of("11z 123p 456p 789p 45s")
        assert not is_confirmed_ankou(hand, t.sou(7))
        assert not is_confirmed_ankou(hand, t.pin(7))

    def test_not_tenpai_is_not_confirmed(self):
        hand = hand_of("777s 19m 19p 258p 3z")
        assert not is_confirmed_ankou(hand, t.sou(7))


class TestJunkara:
    def test_not_junkara_when_tiles_remain(self):
        hand = hand_of(FEVER_OK)
        assert not is_junkara(hand, open_view(hand))

    def test_junkara_when_all_waits_visible(self):
        hand = hand_of(FEVER_OK)
        visible = open_view(hand)
        # 待ちは 1p と 4p。両方4枚とも見えている状態にする
        for tile in (t.pin(1), t.pin(4)):
            visible[tile] = 4
        assert is_junkara(hand, visible)

    def test_partial_visibility_is_not_junkara(self):
        hand = hand_of(FEVER_OK)
        visible = open_view(hand)
        visible[t.pin(1)] = 4
        visible[t.pin(4)] = 3
        assert not is_junkara(hand, visible)


class TestFeverYaku:
    def test_fever_riichi(self):
        hand = hand_of(FEVER_OK)
        yaku = fever_yaku(hand, open_view(hand))
        assert yaku is not None
        assert yaku.name == "フィーバー立直"
        assert yaku.han == 2

    def test_double_fever_riichi(self):
        hand = hand_of(DOUBLE_FEVER)
        yaku = fever_yaku(hand, open_view(hand))
        assert yaku is not None
        assert yaku.name == "ダブルフィーバー立直"
        assert yaku.han == 7

    def test_failure_example_gives_nothing(self):
        hand = hand_of(FEVER_NG)
        assert fever_yaku(hand, open_view(hand)) is None

    def test_furiten_blocks_fever(self):
        hand = hand_of(FEVER_OK)
        assert fever_yaku(hand, open_view(hand), is_furiten=True) is None

    def test_open_hand_blocks_fever(self):
        hand = hand_of(FEVER_OK)
        assert fever_yaku(hand, open_view(hand), is_menzen=False) is None

    def test_junkara_blocks_fever(self):
        hand = hand_of(FEVER_OK)
        visible = open_view(hand)
        for tile in (t.pin(1), t.pin(4)):
            visible[tile] = 4
        assert fever_yaku(hand, visible) is None

    def test_ankan_of_7s_qualifies(self):
        hand = hand_of("11z 123p 456p 78p", melds=[Meld(MeldType.ANKAN, t.sou(7))])
        yaku = fever_yaku(hand, open_view(hand))
        assert yaku is not None
        assert yaku.name == "フィーバー立直"


class TestRiichiPrecedence:
    """立直系は「通常の立直1翻 + 種類ごとの上乗せ」で数える。

    ダブル立直もフィーバー立直も「通常の立直 +1翻」なので、両方成立すれば +2翻。
    ただしフィーバー立直とオープン立直は重複せず、フィーバーが優先する。
    """

    RIICHI_NAMES = {
        "立直",
        "ダブル立直",
        "オープン立直",
        "フィーバー立直",
        "ダブルフィーバー立直",
    }

    def riichi_total(self, value):
        """立直系だけの合計翻数。ルールが規定しているのはこの数字。"""
        return sum(y.han for y in value.yaku if y.name in self.RIICHI_NAMES)

    def value_with(self, fever, **kwargs):
        from fever_sanma.core.hand import Hand
        from fever_sanma.core.yaku import WinContext, evaluate

        hand = Hand.from_counts(t.counts_of("234p 567p 234s 678s 55s"))
        base = dict(
            hand=hand,
            win_tile=t.sou(8),
            is_tsumo=False,
            seat_wind=t.NAN,
            is_riichi=True,
            extra_yaku=(fever,) if fever else (),
        )
        base.update(kwargs)
        return evaluate(WinContext(**base))

    def names(self, value):
        return {y.name for y in value.yaku}

    def test_plain_riichi_is_one_han(self):
        assert self.riichi_total(self.value_with(None)) == 1

    def test_double_riichi_alone_is_two_han(self):
        assert self.riichi_total(self.value_with(None, is_double_riichi=True)) == 2

    def test_fever_alone_is_two_han(self):
        from fever_sanma.core.yaku_special import YAKU_FEVER

        assert self.riichi_total(self.value_with(YAKU_FEVER)) == 2

    def test_double_fever_alone_is_seven_han(self):
        from fever_sanma.core.yaku_special import YAKU_DOUBLE_FEVER

        assert self.riichi_total(self.value_with(YAKU_DOUBLE_FEVER)) == 7

    def test_open_riichi_tsumo_is_two_han(self):
        assert self.riichi_total(self.value_with(None, is_open_riichi=True, is_tsumo=True)) == 2

    def test_open_riichi_ron_is_thirteen_han(self):
        assert self.riichi_total(self.value_with(None, is_open_riichi=True)) == 13

    def test_double_riichi_times_fever_is_three_han(self):
        # ダブル立直も フィーバー立直も「通常の立直 +1翻」なので 1 + 1 + 1 = 3翻
        from fever_sanma.core.yaku_special import YAKU_FEVER

        assert self.riichi_total(self.value_with(YAKU_FEVER, is_double_riichi=True)) == 3

    def test_double_riichi_times_double_fever_is_eight_han(self):
        from fever_sanma.core.yaku_special import YAKU_DOUBLE_FEVER

        assert (
            self.riichi_total(self.value_with(YAKU_DOUBLE_FEVER, is_double_riichi=True)) == 8
        )

    def test_double_riichi_times_open_riichi_is_three_han(self):
        value = self.value_with(
            None, is_double_riichi=True, is_open_riichi=True, is_tsumo=True
        )
        assert self.riichi_total(value) == 3

    def test_fever_beats_open_riichi(self):
        # フィーバーが優先し、オープン立直の上乗せは付かない（確定事項）
        from fever_sanma.core.yaku_special import YAKU_FEVER

        value = self.value_with(YAKU_FEVER, is_open_riichi=True)
        assert "オープン立直" not in self.names(value)
        assert self.riichi_total(value) == 2

    def test_open_riichi_ron_is_not_13_han_when_fever_applies(self):
        # オープン立直の放銃は本来13翻だが、フィーバーが優先するので乗らない
        from fever_sanma.core.yaku_special import YAKU_FEVER

        value = self.value_with(YAKU_FEVER, is_open_riichi=True, is_tsumo=False)
        assert self.riichi_total(value) == 2
        assert value.han < 13  # 数え役満にはならない

    def test_double_fever_beats_open_riichi(self):
        from fever_sanma.core.yaku_special import YAKU_DOUBLE_FEVER

        value = self.value_with(YAKU_DOUBLE_FEVER, is_open_riichi=True)
        assert "オープン立直" not in self.names(value)
        assert self.riichi_total(value) == 7

    def test_fever_and_double_fever_never_coexist(self):
        # fever_yaku は片方しか返さない
        for notation in (FEVER_OK, DOUBLE_FEVER):
            hand = hand_of(notation)
            yaku = fever_yaku(hand, open_view(hand))
            assert yaku is not None
            assert yaku.name in ("フィーバー立直", "ダブルフィーバー立直")

    def test_han_is_not_doubled_up(self):
        from fever_sanma.core.yaku_special import YAKU_FEVER

        plain = self.value_with(None)  # 立直1 + 平和1 + 断幺九1
        fever = self.value_with(YAKU_FEVER)  # 立直1 + フィーバー+1 + 平和1 + 断幺九1
        assert plain.han == 3
        # フィーバー立直は「立直 +1翻」なので、差はちょうど1翻。
        # 立直1翻とフィーバー立直2翻を別々に足していたら 3 + 2 = 5翻 になってしまう。
        assert fever.han == 4

    def test_ippatsu_still_applies(self):
        # 置き換わるのは立直そのものだけ。一発は別の役なので残る。
        from fever_sanma.core.yaku_special import YAKU_FEVER

        names = self.names(self.value_with(YAKU_FEVER, is_ippatsu=True))
        assert "一発" in names

    def test_ura_dora_still_applies(self):
        # フィーバー立直も立直なので裏ドラは乗る
        from fever_sanma.core.yaku_special import YAKU_FEVER

        # 裏ドラ表示が4索 → 裏ドラは5索。この手は 55s を持っているので2枚ぶん乗る。
        value = self.value_with(YAKU_FEVER, ura_indicators=(t.sou(4),))
        assert value.dora == 2


class TestVisibleCounts:
    def test_counts_own_hand_and_rivers(self):
        hand = hand_of("123p")
        visible = visible_counts(hand, discards=[[t.pin(1)], [t.pin(1)], []])
        assert visible[t.pin(1)] == 3

    def test_counts_kita(self):
        hand = hand_of("123p", kita=2)
        visible = visible_counts(hand, discards=[[], [], []])
        assert visible[t.PEI] == 2

    def test_never_exceeds_four(self):
        hand = hand_of("1111p")
        visible = visible_counts(hand, discards=[[t.pin(1)], [], []])
        assert visible[t.pin(1)] == 4


# --- フィーバーモード（局進行との結合）------------------------------------


def rigged_wall(
    hand0: str, hand1: str, hand2: str, draws: str = "", buried: str = "", shuffle: int | None = None
):
    """指定の配牌になる山を作る。shuffle を渡すと、残りの牌をそのシードで混ぜる。

    Wall は先頭18枚を王牌、続く13枚ずつを配牌として取るので、その順に並べる。

    buried に指定した牌は王牌の **ドラ表示牌の領域**（嶺上牌の後ろ）に埋める。
    嶺上牌に置くとカンや北抜きで出てきてしまうので、局中に絶対出したくない牌は
    こちらに入れる。
    """
    from fever_sanma.core.wall import RINSHAN_COUNT, Wall

    pool = t.build_full_set()

    def take(notation: str) -> list[int]:
        tiles = t.parse_tiles(notation) if notation else []
        for tile in tiles:
            pool.remove(tile)
        return tiles

    if shuffle is not None:
        # 残りの牌を混ぜる。混ぜないと昇順のまま積まれ、1筒・4筒などが王牌に偏る
        random.Random(shuffle).shuffle(pool)
    hidden = take(buried)
    assert len(hidden) <= 18 - RINSHAN_COUNT, "ドラ表示牌の領域に収まらない"
    hands = [take(hand0), take(hand1), take(hand2)]
    drawn = take(draws)

    filler = 18 - RINSHAN_COUNT - len(hidden)
    dead = pool[:RINSHAN_COUNT] + hidden + pool[RINSHAN_COUNT : RINSHAN_COUNT + filler]
    del pool[: RINSHAN_COUNT + filler]
    tiles = dead + hands[0] + hands[1] + hands[2] + drawn + pool
    assert len(tiles) == 108
    return Wall(tiles=tiles)


def run_to_fever(wall, dealer=0):
    """親が立直してフィーバーに入るところまで進める。"""
    from fever_sanma.core.game import ActionType, Phase, Round

    game = Round(dealer=dealer, wall=wall, wareme=dealer)
    decision = game.decision()
    riichi = [a for a in decision.actions if a.type is ActionType.RIICHI]
    assert riichi, f"立直できない: {[str(a) for a in decision.actions]}"
    # 引いてきた牌を切って立直する（手牌はフィーバー形のまま残る）
    drawn = game.players[dealer].drawn_tile
    game.apply(next(a for a in riichi if a.tile == drawn))
    # 立直宣言牌への鳴き・ロンの確認を全員パスさせる。ここを抜けてフィーバーに入る。
    while game.decision() is not None and game.phase is Phase.REACTION:
        current = game.decision()
        game.apply(next(a for a in current.actions if a.type is ActionType.PASS))
    return game


# テンパイせず、フィーバー対象牌（7p・7s）と待ち牌（1p・4p・1s・4s）も使わない13枚
JUNK_1 = "19m 5688p 5689s 123z"
JUNK_2 = "19m 2299p 2299s 456z"


class TestFeverMode:
    def test_entering_fever(self):
        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m")
        game = run_to_fever(wall)
        assert game.fever_seat == 0
        assert game.fever_yaku.name == "フィーバー立直"
        assert game.fever_waits == frozenset({t.pin(1), t.pin(4)})

    def test_others_are_forced_to_tsumogiri(self):
        from fever_sanma.core.game import ActionType, Phase

        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m")
        game = run_to_fever(wall)
        for _ in range(30):
            decision = game.decision()
            if decision is None:
                break
            if decision.seat != game.fever_seat:
                assert decision.phase is Phase.FEVER
                assert len(decision.actions) == 1
                action = decision.actions[0]
                assert action.type is ActionType.DISCARD
                assert action.tile == game.players[decision.seat].drawn_tile
            game.apply(decision.actions[0])

    def test_no_calls_or_ron_during_fever(self):
        from fever_sanma.core.game import ActionType

        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m")
        game = run_to_fever(wall)
        forbidden = {ActionType.RON, ActionType.PON, ActionType.CHI, ActionType.MINKAN}
        for _ in range(60):
            decision = game.decision()
            if decision is None:
                break
            assert not forbidden & {a.type for a in decision.actions}
            game.apply(decision.actions[0])

    def test_wins_accumulate(self):
        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m")
        game = run_to_fever(wall)
        for _ in range(300):
            decision = game.decision()
            if decision is None:
                break
            game.apply(decision.actions[0])
        assert game.result is not None
        if game.result.kind == "win":
            # 和了牌が出るたびに和了が積み上がる（CLAUDE.md §4.5）
            assert len(game.result.fever_wins) >= 1
            assert game.result.winners == [0]
            for win in game.result.fever_wins:
                assert win.win_tile in game.fever_waits
                assert "フィーバー立直" in {y.name for y in win.value.yaku}

    def test_no_win_gives_fever_player_tenpai_and_others_noten(self):
        from fever_sanma.core.game import ActionType

        # 和了牌（1p・4p）を全て王牌の奥に埋めて、一度も和了できない局にする
        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m", buried="1111p 4444p")
        game = run_to_fever(wall)
        for _ in range(300):
            decision = game.decision()
            if decision is None:
                break
            # カン・北抜きはせず、ツモ切りだけで進める
            game.apply(next(a for a in decision.actions if a.type is ActionType.DISCARD))
        result = game.result
        assert result.kind == "draw"
        # フィーバー者はテンパイ、他家は強制ノーテン（CLAUDE.md §4.5）
        assert result.tenpai == [0]
        assert result.payments.get(0) == 6000
        assert result.payments.get(1) == -3000
        assert result.payments.get(2) == -3000

    def test_double_fever_is_seven_han(self):
        wall = rigged_wall(DOUBLE_FEVER, JUNK_1, JUNK_2, draws="9m")
        game = run_to_fever(wall)
        assert game.fever_yaku.name == "ダブルフィーバー立直"
        assert game.fever_yaku.han == 7

    def test_fever_player_keeps_kan_and_kita_options(self):
        from fever_sanma.core.game import ActionType, Phase

        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m")
        game = run_to_fever(wall)
        seen_own_turn = False
        for _ in range(120):
            decision = game.decision()
            if decision is None:
                break
            if decision.seat == game.fever_seat and decision.phase is Phase.FEVER:
                seen_own_turn = True
                # リーチ者は最低でもツモ切りができ、カン・北抜きが混ざりうる
                assert any(a.type is ActionType.DISCARD for a in decision.actions)
            game.apply(decision.actions[-1])
        assert seen_own_turn


class TestFeverTiles:
    def test_only_7p_and_7s(self):
        assert FEVER_TILES == (t.pin(7), t.sou(7))

    @pytest.mark.parametrize("tile", [t.pin(8), t.sou(8), t.pin(6), t.sou(6)])
    def test_other_tiles_do_not_trigger(self, tile):
        # 888s の暗刻ではフィーバーにならない（ベンツとは別の役）
        hand = hand_of("11z 123p 456p 78p", melds=[Meld(MeldType.ANKAN, tile)])
        assert fever_yaku(hand, open_view(hand)) is None


MIXED_WINS = 2
"""この山の混ぜ方だと、フィーバー中にツモ・ロン合わせて6回和了する。"""


class TestFeverWinsAreSettledOneByOne:
    """フィーバー中の和了は、起きた時点でその1回ぶんを精算する（画面で和了ごとに出すため）。"""

    def play_out(self, game):
        for _ in range(300):
            decision = game.decision()
            if decision is None:
                break
            game.apply(next(a for a in decision.actions if a.type.name == "DISCARD"))

    def test_scores_move_at_each_win(self):
        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m", shuffle=MIXED_WINS)
        game = run_to_fever(wall)
        start = list(game.scores)
        seen = 0
        for _ in range(300):
            if len(game.fever_wins) > seen:
                # 和了した直後に、その和了のぶんだけ点数が動いている
                moved = [game.scores[s] - start[s] for s in range(3)]
                expected = [0, 0, 0]
                for win in game.fever_wins:
                    for seat, delta in win.payments.deltas.items():
                        expected[seat] += delta
                assert moved == expected
                seen = len(game.fever_wins)
            decision = game.decision()
            if decision is None:
                break
            game.apply(next(a for a in decision.actions if a.type.name == "DISCARD"))
        assert game.result.kind == "win"

    def test_round_total_is_the_sum_of_each_win(self):
        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m", shuffle=MIXED_WINS)
        game = run_to_fever(wall)
        self.play_out(game)
        result = game.result
        assert result.kind == "win"
        total = {}
        for win in result.fever_wins:
            for seat, delta in win.payments.deltas.items():
                total[seat] = total.get(seat, 0) + delta
        assert {s: d for s, d in total.items() if d} == {
            s: d for s, d in result.payments.deltas.items() if d
        }

    def test_riichi_sticks_go_to_the_first_win_only(self):
        wall = rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m", shuffle=MIXED_WINS)
        game = run_to_fever(wall)
        assert game.riichi_sticks == 1  # 自分の立直棒
        self.play_out(game)
        assert len(game.result.fever_wins) >= 2
        first = game.result.fever_wins[0]
        assert first.payments.pot.get(game.fever_seat) == 1000
        assert all(not w.payments.pot.get(game.fever_seat) for w in game.result.fever_wins[1:])
        assert game.riichi_sticks == 0
