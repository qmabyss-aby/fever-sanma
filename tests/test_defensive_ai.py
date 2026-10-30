"""守備型の CPU のテスト。

強い CPU なら押す局面で引く、という性格の違いを中心に確かめる。
"""

import random

from fever_sanma.core import tiles as t
from fever_sanma.core.game import ActionType, Phase, Round
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.match import Match
from fever_sanma.players import DefensiveAgent, StrongAgent, make_cpu

ME = 0
OPP = 1
OTHER = 2


def new_game(seed=0):
    game = Round(dealer=0, rng=random.Random(seed), wareme=OTHER)
    game.wall._indicators[0] = t.man(9)  # ドラを1萬に固定
    return game


def set_turn(game, seat, notation, drawn, melds=()):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation), list(melds))
    player.drawn_tile = drawn
    player.riichi = False
    game.turn = seat
    game.phase = Phase.DRAW
    return game.legal_actions(seat)


def set_riichi(game, seat, notation, discards=()):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation))
    player.drawn_tile = None
    player.riichi = True
    player.discards = list(discards)


def give_melds(game, seat, count):
    tiles = (t.HAKU, t.HATSU, t.CHUN, t.TON)[:count]
    game.players[seat].hand = Hand.from_counts(
        t.counts_of("5p"),
        [Meld(MeldType.PON, tile, called_from=ME, called_tile=tile) for tile in tiles],
    )


def react(game, seat, notation, tile, discarder=0):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation))
    player.riichi = False
    game.last_discard = tile
    game.last_discarder = discarder
    game.phase = Phase.REACTION
    game._reaction_queue = [seat]
    game._reaction_kita = False
    game.is_chankan = False
    return game._reaction_actions(seat)


def defensive(game, seat, options):
    return DefensiveAgent(random.Random(0)).choose(game, seat, options)


def strong(game, seat, options):
    return StrongAgent(random.Random(0)).choose(game, seat, options)


TENPAI = "234p 567p 345s 67s 88s"  # 5s・8s 待ちのテンパイ（13枚）


class TestThreats:
    def test_two_meld_opponent_is_a_threat(self):
        game = new_game()
        give_melds(game, OPP, 2)
        assert OPP in DefensiveAgent()._threats(game, ME)
        assert OPP not in StrongAgent()._threats(game, ME)

    def test_one_meld_opponent_is_not(self):
        game = new_game()
        give_melds(game, OPP, 1)
        assert OPP not in DefensiveAgent()._threats(game, ME)

    def test_everyone_is_a_threat_late(self):
        game = new_game()
        while game.wall.remaining > 20:
            game.wall.draw()
        assert set(DefensiveAgent()._threats(game, ME)) == {OPP, OTHER}


class TestFolding:
    def test_folds_one_shanten_that_strong_pushes(self):
        # 1向聴・中盤・割れ目なし → 強いCPUは押すが、守備型は現物を切ってオリる。
        # 現物は面子を崩す4筒にする（押すなら絶対に切らない牌）
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.pin(4)])
        options = set_turn(game, ME, "234p 567p 345s 6s 88s 1z 9s", drawn=t.sou(9))
        assert strong(game, ME, options).tile != t.pin(4)
        assert defensive(game, ME, options).tile == t.pin(4)

    def test_breaks_tenpai_rather_than_throw_a_dangerous_tile(self):
        # テンパイを保つには無筋の9筒を切るしかない → 立直者がいるので現物の8索で崩す
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.sou(8)])
        options = set_turn(game, ME, TENPAI + " 9p", drawn=t.pin(9))
        assert strong(game, ME, options).tile == t.pin(9)
        action = defensive(game, ME, options)
        assert action.type is ActionType.DISCARD
        assert action.tile == t.sou(8)

    def test_damas_instead_of_riichi_when_threatened(self):
        # 2副露の相手がいる → テンパイでも立直せずダマ（オリられるように）
        game = new_game()
        give_melds(game, OPP, 2)
        options = set_turn(game, ME, TENPAI + " 3z", drawn=t.SHA)
        assert any(a.type is ActionType.RIICHI for a in options)
        action = defensive(game, ME, options)
        assert action.type is ActionType.DISCARD
        assert action.tile == t.SHA

    def test_riichis_when_safe(self):
        game = new_game()
        options = set_turn(game, ME, TENPAI + " 3z", drawn=t.SHA)
        assert defensive(game, ME, options).type in (ActionType.RIICHI, ActionType.OPEN_RIICHI)


class TestCallsAndKans:
    def test_no_call_unless_it_makes_tenpai(self):
        # 2翻の当てがある役牌のポンでも、テンパイにならないなら鳴かない（強いCPUは鳴く）
        game = new_game()
        options = react(game, OPP, "55z 77z 123p 46p 19m 8s 3z", t.HAKU)
        assert strong(game, OPP, options).type is ActionType.PON
        assert defensive(game, OPP, options).type is ActionType.PASS

    def test_calls_when_it_makes_tenpai(self):
        game = new_game()
        # 白をポンして 中と8索のシャンポン待ち（中で上がれば白・中の2翻）
        options = react(game, OPP, "55z 77z 123p 456p 88s 1m", t.HAKU)
        assert defensive(game, OPP, options).type is ActionType.PON

    def test_no_kan(self):
        game = new_game()
        options = set_turn(game, ME, "5555p 123s 456s 19m 2z", drawn=t.pin(5))
        assert any(a.type is ActionType.ANKAN for a in options)
        assert defensive(game, ME, options).type is not ActionType.ANKAN

    def test_benz_only_when_safe(self):
        game = new_game()
        options = set_turn(game, ME, "8888s 123p 456p 19m 23z", drawn=t.sou(8))
        assert defensive(game, ME, options).type is ActionType.ANKAN
        give_melds(game, OPP, 2)  # 危ない相手がいるなら、ベンツでもカンしない
        options = set_turn(game, ME, "8888s 123p 456p 19m 23z", drawn=t.sou(8))
        assert defensive(game, ME, options).type is not ActionType.ANKAN


class TestFullGames:
    def test_matches_complete(self):
        for seed in range(5):
            rng = random.Random(seed)
            agents = [make_cpu("defense", rng) for _ in range(3)]
            assert sum(Match(agents, rng=rng).play().final) == 0
