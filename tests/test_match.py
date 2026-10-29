"""東風戦（局をまたぐ処理）のテスト。

オーラスの終局判定（CLAUDE.md §4.10）と飛び・順位点（§4.8）が中心。
"""

import random

from fever_sanma.core.game import RoundResult
from fever_sanma.core.match import LAST_ROUND, Match
from fever_sanma.core.score import START_SCORE
from fever_sanma.players import RandomAgent

DEALER = 0
CHILD1 = 1
CHILD2 = 2


def match_with(scores):
    match = Match([RandomAgent() for _ in range(3)], rng=random.Random(0))
    match.scores = list(scores)
    return match


def win_by(seat):
    return RoundResult(kind="win", winners=[seat])


def draw_with(tenpai):
    return RoundResult(kind="draw", tenpai=list(tenpai))


class TestDealerContinuation:
    def test_dealer_win_keeps_dealer_mid_game(self):
        match = match_with([25000, 25000, 25000])
        assert match._dealer_keeps(win_by(DEALER), DEALER, is_last=False)

    def test_child_win_moves_dealer(self):
        match = match_with([25000, 25000, 25000])
        assert not match._dealer_keeps(win_by(CHILD1), DEALER, is_last=False)

    def test_draw_with_dealer_tenpai_keeps_dealer(self):
        match = match_with([25000, 25000, 25000])
        assert match._dealer_keeps(draw_with([DEALER]), DEALER, is_last=False)

    def test_draw_with_dealer_noten_moves_dealer(self):
        match = match_with([25000, 25000, 25000])
        assert not match._dealer_keeps(draw_with([CHILD1]), DEALER, is_last=False)

    def test_abort_keeps_dealer(self):
        # 途中流局（四槓散了）は親継続
        match = match_with([25000, 25000, 25000])
        assert match._dealer_keeps(
            RoundResult(kind="abort", abort_reason="四槓散了"), DEALER, is_last=False
        )


class TestLastRoundEnding:
    """CLAUDE.md §4.10 のオーラス終局判定。"""

    def test_child_win_ends_the_game(self):
        match = match_with([25000, 25000, 25000])
        assert not match._dealer_keeps(win_by(CHILD1), DEALER, is_last=True)

    def test_dealer_win_while_top_ends_the_game(self):
        match = match_with([40000, 20000, 15000])
        assert not match._dealer_keeps(win_by(DEALER), DEALER, is_last=True)

    def test_dealer_win_while_not_top_continues(self):
        # 子がトップなら連荘（上がり止めなし）
        match = match_with([20000, 40000, 15000])
        assert match._dealer_keeps(win_by(DEALER), DEALER, is_last=True)

    def test_draw_with_dealer_tenpai_continues_regardless_of_rank(self):
        # 親テンパイなら順位にかかわらず連荘
        match = match_with([10000, 40000, 25000])
        assert match._dealer_keeps(draw_with([DEALER]), DEALER, is_last=True)
        match = match_with([40000, 20000, 15000])
        assert match._dealer_keeps(draw_with([DEALER]), DEALER, is_last=True)

    def test_draw_with_dealer_noten_ends_the_game(self):
        match = match_with([10000, 40000, 25000])
        assert not match._dealer_keeps(draw_with([CHILD1]), DEALER, is_last=True)

    def test_tie_for_top_is_broken_by_seat(self):
        # 同点は起家に近い方が上位
        match = match_with([30000, 30000, 15000])
        assert match._is_top(DEALER)
        assert not match._is_top(CHILD1)


class TestTobi:
    def test_win_that_busts_pays_the_bonus(self):
        match = match_with([-500, 40000, 35500])
        match._apply_tobi([DEALER], win_by(CHILD1))
        assert match.scores[DEALER] == -500 - 10000
        assert match.scores[CHILD1] == 40000 + 10000

    def test_double_ron_splits_the_bonus(self):
        match = match_with([-500, 40000, 35500])
        match._apply_tobi([DEALER], RoundResult(kind="win", winners=[CHILD1, CHILD2]))
        assert match.scores[CHILD1] == 40000 + 5000
        assert match.scores[CHILD2] == 35500 + 5000

    def test_noten_bust_has_no_bonus(self):
        # ノーテン罰符で飛んだ場合は賞もペナルティもなく終局するだけ（CLAUDE.md §4.8）
        match = match_with([-500, 40000, 35500])
        before = list(match.scores)
        match._apply_tobi([DEALER], draw_with([CHILD1, CHILD2]))
        assert match.scores == before


class TestFullMatch:
    def test_plays_three_rounds_minimum(self):
        result = Match([RandomAgent(random.Random(i)) for i in range(3)], rng=random.Random(7)).play()
        assert len(result.rounds) >= LAST_ROUND

    def test_final_scores_are_zero_sum(self):
        for seed in range(30):
            agents = [RandomAgent(random.Random(seed)) for _ in range(3)]
            result = Match(agents, rng=random.Random(seed)).play()
            assert sum(result.final) == 0, f"seed={seed}"

    def test_raw_scores_are_conserved(self):
        # 飛び賞は場外からの持ち出しではなくプレイヤー間の移動なので合計は変わらない
        for seed in range(30):
            agents = [RandomAgent(random.Random(seed)) for _ in range(3)]
            result = Match(agents, rng=random.Random(seed)).play()
            assert sum(result.scores) == START_SCORE * 3, f"seed={seed}"

    def test_ended_by_is_recorded(self):
        endings = set()
        for seed in range(60):
            agents = [RandomAgent(random.Random(seed)) for _ in range(3)]
            endings.add(Match(agents, rng=random.Random(seed)).play().ended_by)
        assert endings <= {"east3", "tobi", "limit"}
        assert "east3" in endings

    def test_ranking_is_consistent_with_final(self):
        agents = [RandomAgent(random.Random(3)) for _ in range(3)]
        result = Match(agents, rng=random.Random(3)).play()
        ranked = [result.final[seat] for seat in result.ranking]
        assert ranked == sorted(ranked, reverse=True)

    def test_on_round_end_callback_fires(self):
        seen = []
        agents = [RandomAgent(random.Random(5)) for _ in range(3)]
        result = Match(
            agents, rng=random.Random(5), on_round_end=lambda g, r: seen.append(r)
        ).play()
        assert len(seen) == len(result.rounds)
