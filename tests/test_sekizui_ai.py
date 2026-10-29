"""脊髄狙いの CPU のテスト。

強い CPU とは逆の判断（鳴ける形を残す・暗槓しない・単騎の選び方）を中心に確かめる。
局面の作り方は test_strong_ai と同じ。
"""

import random

from fever_sanma.core import tiles as t
from fever_sanma.core.game import ActionType, Phase, Round
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.match import Match
from fever_sanma.players import RandomAgent, SekizuiAgent, StrongAgent, make_cpu
from fever_sanma.players.sekizui_ai import sekizui_potential

ME = 0
OPP = 1


def new_game(seed=0):
    return Round(dealer=0, rng=random.Random(seed), wareme=2)


def pon(tile, frm=2):
    return Meld(MeldType.PON, tile, called_from=frm, called_tile=tile)


def set_turn(game, seat, notation, drawn, melds=()):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation), list(melds))
    player.drawn_tile = drawn
    player.riichi = False
    game.turn = seat
    game.phase = Phase.DRAW
    return game.legal_actions(seat)


def react(game, seat, notation, tile, discarder=0, melds=()):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation), list(melds))
    player.riichi = False
    game.last_discard = tile
    game.last_discarder = discarder
    game.phase = Phase.REACTION
    game._reaction_queue = [seat]
    game._reaction_kita = False
    game.is_chankan = False
    return game._reaction_actions(seat)


def set_riichi(game, seat, notation, discards=()):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation))
    player.drawn_tile = None
    player.riichi = True
    player.discards = list(discards)


def sekizui(game, seat, options):
    return SekizuiAgent(random.Random(0)).choose(game, seat, options)


NOTHING_VISIBLE = [0] * 27


class TestPotential:
    def visible_with(self, counts, extra=()):
        visible = list(counts)
        for tile in extra:
            visible[tile] += 1
        return visible

    def test_pairs_are_pon_seeds(self):
        counts = t.counts_of("22p 88s 11z")
        covered, pons, _ = sekizui_potential(counts, 4, self.visible_with(counts))
        assert (covered, pons) == (3, 3)

    def test_dead_pair_is_not_counted(self):
        # 2筒の残り2枚が河で見えている → もうポンできない
        counts = t.counts_of("22p 88s")
        visible = self.visible_with(counts, extra=[t.pin(2), t.pin(2)])
        covered, pons, _ = sekizui_potential(counts, 4, visible)
        assert (covered, pons) == (1, 1)

    def test_four_of_a_kind_cannot_be_called(self):
        # 5枚目は無いし、暗槓は副露に数えないので脊髄の役に立たない
        counts = t.counts_of("5555p")
        assert sekizui_potential(counts, 4, self.visible_with(counts))[0] == 0

    def test_partials_are_chi_seeds(self):
        counts = t.counts_of("46p 78s")
        covered, pons, _ = sekizui_potential(counts, 4, self.visible_with(counts))
        assert (covered, pons) == (2, 0)

    def test_manzu_and_honors_make_no_chi(self):
        counts = t.counts_of("19m 12z")
        assert sekizui_potential(counts, 4, self.visible_with(counts))[0] == 0

    def test_capped_by_need(self):
        counts = t.counts_of("22p 44p 66s 88s 11z")
        covered, _, _ = sekizui_potential(counts, 2, self.visible_with(counts))
        assert covered == 2


class TestCalls:
    def test_pons_a_plain_pair_when_far(self):
        # 門前2向聴。役牌でなくてもポンして脊髄に向かう（強いCPUはここでは門前を守る）
        game = new_game()
        options = react(game, OPP, "22p 456p 789s 46s 19m 3z", t.pin(2))
        assert sekizui(game, OPP, options).type is ActionType.PON
        assert StrongAgent(random.Random(0)).choose(game, OPP, options).type is ActionType.PASS

    def test_chis_once_open(self):
        game = new_game()
        options = react(game, OPP, "46s 22p 88p 19m 3z", t.sou(5), melds=[pon(t.HAKU)])
        assert sekizui(game, OPP, options).type is ActionType.CHI

    def test_fourth_call_is_taken(self):
        # 3副露から4副露目。鳴けば裸単騎になる
        game = new_game()
        melds = [pon(t.HAKU), pon(t.HATSU), pon(t.CHUN)]
        options = react(game, OPP, "22p 9s", t.pin(2), melds=melds)
        assert sekizui(game, OPP, options).type is ActionType.PON

    def test_hands_off_to_strong_when_menzen_and_close(self):
        # 門前1向聴なら脊髄より立直が速い → 強いCPUと同じく鳴かない
        game = new_game()
        options = react(game, OPP, "123p 456p 22s 46s 89s 3z", t.sou(2))
        assert sekizui(game, OPP, options).type is ActionType.PASS

    def test_stops_calling_against_riichi_when_far(self):
        game = new_game()
        set_riichi(game, 2, "123p 456p 789p 11s 23s")
        options = react(game, OPP, "22p 46p 88s 13s 19m 34z 7z", t.pin(2))
        assert sekizui(game, OPP, options).type is ActionType.PASS


class TestTurn:
    def test_never_ankans(self):
        # 暗槓は副露に数えないので脊髄が消える
        game = new_game()
        options = set_turn(game, ME, "5555p 22s 46s 9m 3z", drawn=t.pin(5), melds=[pon(t.HAKU)])
        assert any(a.type is ActionType.ANKAN for a in options)
        assert sekizui(game, ME, options).type is not ActionType.ANKAN

    def test_kakans(self):
        # 加槓は副露のまま。嶺上牌とカンドラが付く
        game = new_game()
        options = set_turn(game, ME, "5z 22s 46s 88p 19m", drawn=t.HAKU, melds=[pon(t.HAKU)])
        assert sekizui(game, ME, options).type is ActionType.KAKAN

    def test_keeps_callable_shapes(self):
        # 完成した順子（123p）は鳴けないので崩してよい。対子・搭子は残す
        game = new_game()
        options = set_turn(game, ME, "123p 22s 46s 88p 9m", drawn=t.man(9), melds=[pon(t.HAKU)])
        tile = sekizui(game, ME, options).tile
        assert tile not in (t.sou(2), t.sou(4), t.sou(6), t.pin(8))

    def test_tanki_on_the_tile_with_more_left(self):
        # 4副露済み。1筒は河に2枚見えていて残り1枚、9索は残り3枚 → 9索で待つ
        game = new_game()
        game.players[OPP].discards = [t.pin(1), t.pin(1)]
        melds = [pon(t.HAKU), pon(t.HATSU), pon(t.CHUN), pon(t.TON)]
        options = set_turn(game, ME, "1p 9s", drawn=t.sou(9), melds=melds)
        assert sekizui(game, ME, options).tile == t.pin(1)

    def test_folds_against_riichi_when_far(self):
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.sou(9)])
        options = set_turn(game, ME, "22p 46p 88s 13s 9s 3z", drawn=t.sou(9), melds=[pon(t.HAKU)])
        assert sekizui(game, ME, options).tile == t.sou(9)  # 現物


class TestFullGames:
    def test_matches_complete(self):
        for seed in range(5):
            rng = random.Random(seed)
            agents = [make_cpu("sekizui", rng) for _ in range(3)]
            assert sum(Match(agents, rng=rng).play().final) == 0

    def test_actually_wins_by_sekizui(self):
        sekizui_wins = 0
        for seed in range(30):
            rng = random.Random(seed)
            agents = [SekizuiAgent(rng), RandomAgent(rng), RandomAgent(rng)]
            for round_result in Match(agents, rng=rng).play().rounds:
                if 0 in round_result.winners:
                    sekizui_wins += "脊髄" in {y.name for y in round_result.values[0].yaku}
        assert sekizui_wins >= 3

    def test_beats_random(self):
        total = 0
        for index in range(24):
            rng = random.Random(index)
            seat = index % 3
            agents = [RandomAgent(rng) for _ in range(3)]
            agents[seat] = SekizuiAgent(rng)
            total += Match(agents, rng=rng).play().final[seat]
        assert total / 24 > 30_000
