"""普通の CPU（改良前の強いCPU）のテスト。最強CPUと違う鳴きの判断だけを確かめる。

局面の作り方は test_strong_ai と同じ。
"""

import random

from fever_sanma.core import tiles as t
from fever_sanma.core.game import ActionType
from fever_sanma.core.match import Match
from fever_sanma.players import NormalAgent, make_cpu

from test_strong_ai import OPP, new_game, react


def normal(game, seat, options):
    return NormalAgent(random.Random(0)).choose(game, seat, options)


class TestCalls:
    def test_pons_a_lone_yakuhai(self):
        # 役牌1つだけでもポンする（最強CPUは門前を守る）
        game = new_game()
        _, options = react(game, OPP, "55z 123p 456p 78s 19m 3z", t.HAKU)
        assert normal(game, OPP, options).type is ActionType.PON

    def test_calls_when_the_hand_is_far(self):
        # 門前で遠い手なら、役牌でなくてもポンして脊髄を狙う（最強CPUは鳴かない）
        game = new_game()
        _, options = react(game, OPP, "22s 66s 9s 258p 369p 3z 4z", t.sou(2))
        assert normal(game, OPP, options).type is ActionType.PON


def test_make_cpu():
    assert isinstance(make_cpu("normal"), NormalAgent)


def test_matches_complete():
    for seed in range(3):
        rng = random.Random(seed)
        result = Match([make_cpu("normal", rng) for _ in range(3)], rng=rng).play()
        assert sum(result.final) == 0
