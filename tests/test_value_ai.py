"""高打点狙いの CPU のテスト。

「高い手」＝上がれば誰かを飛ばせる手、という基準で押し引きが変わることと、
フィーバー立直・ベンツを狙いに行くことを確かめる。
"""

import random

from fever_sanma.core import tiles as t
from fever_sanma.core.game import ActionType, Phase, Round
from fever_sanma.core.hand import Hand, Meld, MeldType
from fever_sanma.core.match import Match
from fever_sanma.core.yaku_special import fever_yaku
from fever_sanma.players import StrongAgent, ValueAgent, make_cpu
from fever_sanma.players.strong_ai import visible_counts

ME = 0  # 親
OPP = 1
OTHER = 2


def new_game(seed=0, wareme=OTHER):
    game = Round(dealer=0, rng=random.Random(seed), wareme=wareme)
    # ドラ表示を 9萬 にしてドラを 1萬 に固定する（テストの手に入れない限りドラは乗らない）
    game.wall._indicators[0] = t.man(9)
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


def agent():
    return ValueAgent(random.Random(0))


class TestHandValue:
    def test_counts_permanent_dora(self):
        game = new_game()
        set_turn(game, ME, "99m 234p 567p 345s 67s 3z", drawn=t.SHA)
        assert agent().hand_value(game, ME) == 2  # 9萬2枚

    def test_fever_seed_adds_value(self):
        game = new_game()
        plain = Hand.from_counts(t.counts_of("234p 567p 345s 67s 88s"))
        fever = Hand.from_counts(t.counts_of("777p 567p 345s 67s 88s"))
        assert agent().hand_value(game, ME, fever) > agent().hand_value(game, ME, plain)

    def test_benz_triples_dora(self):
        game = new_game()
        benz = Hand.from_counts(t.counts_of("99m 123p 456p 2z"), [Meld(MeldType.ANKAN, t.sou(8))])
        # ドラ2（9萬） + ベンツ2翻 + ドラ×3 のぶん
        assert agent().hand_value(game, ME, benz) >= 2 + 2 + 4


class TestCanBust:
    def test_cheap_hand_cannot_bust_from_25000(self):
        game = new_game()
        set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        assert not agent().can_bust(game, ME)

    def test_can_bust_a_low_opponent(self):
        game = new_game()
        game.players[OPP].score = 1000
        set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        assert agent().can_bust(game, ME)

    def test_wareme_tripling_counts(self):
        # 満貫（親12,000）では 25,000 の相手は飛ばない。割れ目なら3倍で36,000になって飛ぶ。
        hand = "99m 123p 456p 345s 67s 3z"  # ドラ2 → 見込み4翻 → 切り上げ満貫
        game = new_game()
        game.wareme = None  # 割れ目なし
        set_turn(game, ME, hand, drawn=t.SHA)
        assert not agent().can_bust(game, ME)
        game = new_game(wareme=OPP)
        set_turn(game, ME, hand, drawn=t.SHA)
        assert agent().can_bust(game, ME)

    def test_zero_is_not_bust(self):
        # 0点ちょうどは飛ばない（CLAUDE.md §4.8）
        game = new_game()
        game.wareme = None
        game.players[OPP].score = 12000
        set_turn(game, ME, "99m 123p 456p 345s 67s 3z", drawn=t.SHA)  # 親満貫ロン12,000
        assert not agent().can_bust(game, ME)
        game.players[OPP].score = 11900
        assert agent().can_bust(game, ME)


class TestPushFold:
    FAR_HAND = "234p 567p 13s 9s 99m 2z 5z 7z"  # 2向聴、9萬のドラ2

    def test_pushes_when_it_can_bust(self):
        # 2向聴。強いCPUはオリる（現物の5筒を切る）が、飛ばせる手なので押す
        game = new_game()
        game.players[OPP].score = 500
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.pin(5)])
        options = set_turn(game, ME, self.FAR_HAND, drawn=t.CHUN)
        assert StrongAgent(random.Random(0)).choose(game, ME, options).tile == t.pin(5)
        assert agent().choose(game, ME, options).tile != t.pin(5)

    def test_folds_a_cheap_tenpai(self):
        # ドラも役もない安いテンパイ → 立直を受けたらテンパイでもオリる
        game = new_game()
        set_riichi(game, OPP, "123p 456p 789p 11s 23s", discards=[t.sou(8)])
        options = set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        action = agent().choose(game, ME, options)
        assert action.type is ActionType.DISCARD
        assert action.tile == t.sou(8)  # 現物

    def test_watches_three_meld_opponents_when_cheap(self):
        # 安い手のときは、3副露の相手（脊髄が近い）も警戒する
        game = new_game()
        opp = game.players[OPP]
        opp.hand = Hand.from_counts(
            t.counts_of("5p"),
            [Meld(MeldType.PON, tile, called_from=2, called_tile=tile) for tile in (20, 24, 25)],
        )
        set_turn(game, ME, "234p 567p 345s 67s 88s 3z", drawn=t.SHA)
        assert OPP in agent()._threats(game, ME)


class TestValueOverEfficiency:
    def test_keeps_dora_that_strong_would_throw(self):
        # 2向聴。強いCPUは効率で孤立した9萬（常時ドラ）を切るが、高打点狙いは残して中を切る
        game = new_game()
        options = set_turn(game, ME, "9m 34679p 3456789s 7z", drawn=t.pin(7))
        assert StrongAgent(random.Random(0)).choose(game, ME, options).tile == t.man(9)
        assert agent().choose(game, ME, options).tile == t.CHUN


class TestFeverAndBenz:
    def test_never_breaks_a_fever_triplet(self):
        game = new_game()
        options = set_turn(game, ME, "777p 19m 2z 135s 246s 9p", drawn=t.pin(9))
        assert agent().choose(game, ME, options).tile != t.pin(7)

    def test_riichi_chooses_a_fever_discard(self):
        game = new_game()
        options = set_turn(game, ME, "123p 123456777s 1z 9p", drawn=t.pin(9))
        action = agent().choose(game, ME, options)
        assert action.type in (ActionType.RIICHI, ActionType.OPEN_RIICHI)
        hand = game.players[ME].hand.copy()
        hand.remove(action.tile)
        assert fever_yaku(hand, visible_counts(game, ME)) is not None

    def test_stays_menzen_with_a_fever_seed(self):
        game = new_game()
        options = react(game, OPP, "777s 55z 13p 46p 19m 2z", t.HAKU)
        assert agent().choose(game, OPP, options).type is ActionType.PASS

    def test_pons_8s_for_benz(self):
        game = new_game()
        options = react(game, OPP, "88s 13p 46p 19m 2z 3z 4z 7z", t.sou(8))
        assert agent().choose(game, OPP, options).type is ActionType.PON

    def test_no_cheap_calls(self):
        # 強いCPUは遠い手なら脊髄狙いで鳴くが、高打点狙いは安い鳴きをしない
        game = new_game()
        options = react(game, OPP, "22p 46p 37s 13s 19m 34z 7z", t.pin(2))
        assert agent().choose(game, OPP, options).type is ActionType.PASS


class TestFullGames:
    def test_matches_complete(self):
        for seed in range(5):
            rng = random.Random(seed)
            agents = [make_cpu("value", rng) for _ in range(3)]
            assert sum(Match(agents, rng=rng).play().final) == 0

    # 強さそのものは1局で数万点動くためばらつきが大きく、少ない半荘数のテストでは
    # 結果が上下する。強さは `--compare` で数百半荘まわして確かめる。
