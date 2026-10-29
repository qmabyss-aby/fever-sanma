"""強い CPU のテスト。

局面を作り込んで、狙った判断（牌効率・押し引き・オープン立直・ベンツ・鳴き）が
できているかを1つずつ確かめる。最後に、ランダム打ちに大差で勝つことも確かめる。
"""

import random

from fever_sanma.core import tiles as t
from fever_sanma.core.game import Action, ActionType, Phase, Round
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.match import Match
from fever_sanma.players import RandomAgent, StrongAgent, make_cpu

ME = 0
OPP = 1


def new_game(seed=0):
    return Round(dealer=0, rng=random.Random(seed), wareme=2)


def set_turn(game, seat, notation, drawn):
    """seat の手番にして、手牌（ツモ牌込み14枚）を差し替える。"""
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation))
    player.drawn_tile = drawn
    player.riichi = False
    game.turn = seat
    game.phase = Phase.DRAW
    return game.legal_actions(seat)


def set_riichi(game, seat, notation, discards=(), open_riichi=False):
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation))
    player.drawn_tile = None
    player.riichi = True
    player.open_riichi = open_riichi
    player.discards = list(discards)


def choose(game, seat, options):
    return StrongAgent(random.Random(0)).choose(game, seat, options)


class TestEfficiency:
    def test_throws_the_isolated_useless_honor(self):
        game = new_game()
        options = set_turn(game, ME, "234p 567p 2345s 778s 2z", drawn=t.NAN)
        action = choose(game, ME, options)
        # 南を切るとテンパイなので立直を伴ってもよい。切る牌が南であることが大事。
        assert action.type in (ActionType.DISCARD, ActionType.RIICHI, ActionType.OPEN_RIICHI)
        assert action.tile == t.NAN  # 東家にとって南は役にならない孤立字牌

    def test_always_takes_a_win(self):
        game = new_game()
        options = [Action(ActionType.DISCARD, t.pin(1)), Action(ActionType.TSUMO)]
        assert choose(game, ME, options).type is ActionType.TSUMO


class TestRiichi:
    def test_open_riichi_when_plain_riichi_cannot_ron(self):
        # 234p 567p 345s 79s 99m: 8s 待ちの嵌張。立直＋ロンだと1翻しかなく二翻縛りで上がれない。
        # オープン立直なら他家のロンで13翻になる。
        game = new_game()
        options = set_turn(game, ME, "234p 567p 345s 79s 99m 3z", drawn=t.SHA)
        action = choose(game, ME, options)
        assert action.type is ActionType.OPEN_RIICHI
        assert action.tile == t.SHA

    def test_plain_riichi_when_ron_already_has_enough_han(self):
        # 平和・断幺九が付くので、普通の立直でもロンで上がれる → 待ちを隠す
        game = new_game()
        options = set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        action = choose(game, ME, options)
        assert action.type is ActionType.RIICHI
        assert action.tile == t.SHA

    def test_no_riichi_at_the_very_end(self):
        game = new_game()
        while game.wall.remaining > 2:
            game.wall.draw()
        options = set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        assert choose(game, ME, options).type is ActionType.DISCARD


class TestDefense:
    def test_folds_with_genbutsu_against_riichi(self):
        # 立直者がいて自分の手が遠い → 立直者の河にある牌（現物）を切る
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.pin(5)])
        options = set_turn(game, ME, "19m 135p 79s 1234567z", drawn=t.pin(5))
        assert choose(game, ME, options).tile == t.pin(5)

    def test_never_deals_into_open_riichi(self):
        # オープン立直者の待ち（南・1索）は見えている。効率では南を切りたいが、切らない。
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 22z", open_riichi=True)
        options = set_turn(game, ME, "234p 567p 2345s 778s 2z", drawn=t.NAN)
        action = choose(game, ME, options)
        assert action.tile not in (t.NAN, t.sou(1))

    def test_pushes_when_tenpai_against_riichi(self):
        # 自分もテンパイなら押す（立直をかける）
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.pin(5)])
        options = set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        assert choose(game, ME, options).type in (ActionType.RIICHI, ActionType.OPEN_RIICHI)


class TestSpecialYaku:
    def test_always_makes_benz(self):
        # 8索の暗槓はベンツ（2翻 + ドラ×3）
        game = new_game()
        options = set_turn(game, ME, "8888s 123p 456p 19m 23z", drawn=t.sou(8))
        action = choose(game, ME, options)
        assert action.type is ActionType.ANKAN
        assert action.tile == t.sou(8)

    def test_nukis_an_isolated_kita(self):
        game = new_game()
        options = set_turn(game, ME, "234p 567p 2345s 778s 4z", drawn=t.PEI)
        assert choose(game, ME, options).type is ActionType.KITA

    def test_keeps_a_fever_pair(self):
        # 7筒の対子はフィーバー立直の種なので、効率が同じなら残す
        game = new_game()
        options = set_turn(game, ME, "77p 19m 1s 9s 135z 246s 8p", drawn=t.pin(8))
        action = choose(game, ME, options)
        assert action.tile != t.pin(7)


def react(game, seat, notation, tile, discarder=0, melds=()):
    """discarder が tile を切った直後の、seat の鳴き判断。"""
    player = game.players[seat]
    player.hand = Hand.from_counts(t.counts_of(notation), list(melds))
    player.riichi = False
    game.last_discard = tile
    game.last_discarder = discarder
    game.phase = Phase.REACTION
    game._reaction_queue = [seat]
    game._reaction_kita = False
    game.is_chankan = False
    options = game._reaction_actions(seat)
    return choose(game, seat, options), options


class TestCalls:
    def test_pons_yakuhai(self):
        game = new_game()
        action, _ = react(game, OPP, "55z 123p 456p 78s 19m 3z", t.HAKU)
        assert action.type is ActionType.PON

    def test_stays_menzen_when_close(self):
        # 1向聴の門前手は役牌以外を鳴かず、立直を目指す
        game = new_game()
        action, options = react(game, OPP, "123p 456p 22s 46s 89s 3z", t.sou(2))
        assert any(a.type is ActionType.PON for a in options)
        assert action.type is ActionType.PASS

    def test_keeps_calling_once_open(self):
        # 一度鳴いたら脊髄（4副露の裸単騎で13翻）を目指して鳴き進める
        game = new_game()
        melds = [Meld(MeldType.PON, t.HAKU, called_from=2, called_tile=t.HAKU)]
        action, _ = react(game, OPP, "123p 46s 89s 19m 3z 4z", t.sou(5), melds=melds)
        assert action.type is ActionType.CHI

    def test_does_not_call_into_a_riichi_when_far(self):
        game = new_game()
        set_riichi(game, 2, "123p 456p 789p 11s 23s")
        action, _ = react(game, OPP, "55z 123p 456p 78s 19m 3z", t.HAKU)
        assert action.type is ActionType.PASS


class TestFullGames:
    def test_strong_matches_complete(self):
        for seed in range(5):
            rng = random.Random(seed)
            result = Match([make_cpu("strong", rng) for _ in range(3)], rng=rng).play()
            assert sum(result.final) == 0

    def test_beats_random_by_a_wide_margin(self):
        strong_total = 0
        random_total = 0
        for index in range(24):
            rng = random.Random(index)
            seat = index % 3
            agents = [RandomAgent(rng) for _ in range(3)]
            agents[seat] = StrongAgent(rng)
            result = Match(agents, rng=rng).play()
            strong_total += result.final[seat]
            random_total += sum(result.final) - result.final[seat]
        assert strong_total / 24 > 50_000
        assert random_total / 48 < 0

    def test_make_cpu(self):
        assert isinstance(make_cpu("strong"), StrongAgent)
        assert isinstance(make_cpu("random"), RandomAgent)
