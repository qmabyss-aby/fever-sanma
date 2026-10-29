"""局進行の状態機械のテスト。

旧実装で問題になった「状態が宙に浮いて進まなくなる」ことを構造的に防げているか
を確かめるのが主目的。ランダム打ちで大量に回して、例外・デッドロック・収支の
ずれが出ないことを見る。
"""

import random

import pytest

from fever_sanma.core import score as scoring
from fever_sanma.core import tiles as t
from fever_sanma.core.game import Action, ActionType, Phase, Round
from fever_sanma.players import RandomAgent

MAX_STEPS = 400
"""1局で必要な手数の上限。無限ループになっていないことの検出に使う。"""


def play_round(seed: int, dealer: int = 0, scores=None) -> Round:
    rng = random.Random(seed)
    game = Round(dealer=dealer, scores=scores, rng=rng)
    agent = RandomAgent(random.Random(seed + 1))
    for _ in range(MAX_STEPS):
        decision = game.decision()
        if decision is None:
            return game
        assert decision.actions, f"選べる手が無い状態で止まった: {decision.phase}"
        game.apply(agent.choose(game, decision.seat, decision.actions))
    raise AssertionError("局が終わらなかった（デッドロックの疑い）")


class TestSetup:
    def test_initial_state(self):
        game = Round(dealer=0, rng=random.Random(1))
        assert game.phase is Phase.DRAW
        assert game.turn == 0
        # 親はツモ済みで14枚、子は13枚
        assert sum(game.players[0].hand.concealed) == 14
        assert sum(game.players[1].hand.concealed) == 13
        assert sum(game.players[2].hand.concealed) == 13

    def test_wareme_is_a_valid_seat(self):
        for seed in range(20):
            game = Round(dealer=seed % 3, rng=random.Random(seed))
            assert game.wareme in (0, 1, 2)

    def test_scores_start_at_25000(self):
        game = Round(dealer=0, rng=random.Random(1))
        assert game.scores == [25000, 25000, 25000]


class TestDecisionAlwaysAvailable:
    def test_never_stuck(self):
        # 状態機械が必ず「次に誰が何を選ぶか」を返し続けること
        for seed in range(30):
            game = play_round(seed)
            assert game.result is not None
            assert game.phase is Phase.FINISHED

    def test_decision_is_none_after_finish(self):
        game = play_round(0)
        assert game.decision() is None

    def test_rejects_illegal_action(self):
        game = Round(dealer=0, rng=random.Random(1))
        with pytest.raises(ValueError):
            game.apply(Action(ActionType.RON, t.pin(1), 1))


class TestRoundResults:
    def test_all_outcomes_reachable(self):
        kinds = {play_round(seed).result.kind for seed in range(60)}
        assert "win" in kinds
        assert "draw" in kinds

    def test_scores_are_zero_sum_within_round(self):
        # 供託が出入りするので、リーチ棒の増減を足し戻すとゼロサムになる
        for seed in range(40):
            game = play_round(seed)
            total = sum(game.scores) + game.riichi_sticks * 1000
            assert total == 75000, f"seed={seed} で点数が保存されていない"

    def test_dealer_kept_on_dealer_win(self):
        for seed in range(60):
            game = play_round(seed)
            result = game.result
            if result.kind == "win":
                assert result.dealer_kept == (game.dealer in result.winners)


class TestRyuukyoku:
    def test_noten_penalty_applied(self):
        for seed in range(60):
            game = play_round(seed)
            result = game.result
            if result.kind != "draw":
                continue
            tenpai = result.tenpai
            if 0 < len(tenpai) < 3:
                assert result.payments.total() == 0
                for seat in tenpai:
                    assert result.payments.get(seat) > 0
                return
        pytest.skip("この範囲のシードでは1〜2人テンパイの流局が出なかった")

    def test_dealer_kept_when_dealer_tenpai(self):
        # 親テンパイなら順位にかかわらず連荘（CLAUDE.md §4.10）
        for seed in range(60):
            game = play_round(seed)
            result = game.result
            if result.kind == "draw":
                assert result.dealer_kept == (game.dealer in result.tenpai)


class TestRiichi:
    def test_riichi_costs_1000_and_locks_discards(self):
        rng = random.Random(0)
        game = Round(dealer=0, rng=rng)
        for _ in range(MAX_STEPS):
            decision = game.decision()
            if decision is None:
                break
            riichi = [a for a in decision.actions if a.type is ActionType.RIICHI]
            if riichi:
                seat = decision.seat
                before = game.players[seat].score
                game.apply(riichi[0])
                assert game.players[seat].score == before - 1000
                assert game.players[seat].riichi
                assert game.riichi_sticks >= 1
                return
            game.apply(RandomAgent(rng).choose(game, decision.seat, decision.actions))
        pytest.skip("この局では立直の機会が無かった")

    def test_riichi_player_can_only_tsumogiri(self):
        rng = random.Random(3)
        game = Round(dealer=0, rng=rng)
        agent = RandomAgent(rng)
        declared: int | None = None
        for _ in range(MAX_STEPS):
            decision = game.decision()
            if decision is None:
                break
            if declared is not None and decision.seat == declared:
                if decision.phase is Phase.DRAW:
                    discards = [a for a in decision.actions if a.type is ActionType.DISCARD]
                    drawn = game.players[declared].drawn_tile
                    assert all(a.tile == drawn for a in discards)
                    return
            riichi = [a for a in decision.actions if a.type is ActionType.RIICHI]
            if riichi and declared is None:
                declared = decision.seat
                game.apply(riichi[0])
                continue
            game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この局では立直後のツモ番が来なかった")


class TestKita:
    def test_kita_is_always_discardable_to_the_river(self):
        # 北は抜きドラにするだけでなく、普通に河へ捨てられる
        for seed in range(40):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(MAX_STEPS):
                decision = game.decision()
                if decision is None:
                    break
                player = game.players[decision.seat]
                if (
                    decision.phase in (Phase.DRAW, Phase.DISCARD)
                    and player.hand.concealed[t.PEI]
                    and not player.riichi
                ):
                    assert any(
                        a.type is ActionType.DISCARD and a.tile == t.PEI
                        for a in decision.actions
                    )
                game.apply(agent.choose(game, decision.seat, decision.actions))

    def test_riichi_blocks_kita_from_the_concealed_hand(self):
        # 立直後は手牌を変えられないので、抜けるのは今ツモってきた北だけ
        game = Round(dealer=0, rng=random.Random(1))
        player = game.players[0]
        player.riichi = True
        player.hand.concealed[t.PEI] = 1

        player.drawn_tile = t.pin(5)
        assert not game._can_draw_kita(0)

        player.drawn_tile = t.PEI
        assert game._can_draw_kita(0)

    def test_kita_allowed_from_hand_before_riichi(self):
        game = Round(dealer=0, rng=random.Random(1))
        player = game.players[0]
        player.hand.concealed[t.PEI] = 1
        player.drawn_tile = t.pin(5)
        assert game._can_draw_kita(0)

    def test_kita_does_not_go_to_discards(self):
        # 北を抜いてもフリテンにならない（CLAUDE.md §4.3）ので河に置かない
        for seed in range(40):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(MAX_STEPS):
                decision = game.decision()
                if decision is None:
                    break
                kita = [a for a in decision.actions if a.type is ActionType.KITA]
                if kita:
                    seat = decision.seat
                    before_discards = len(game.players[seat].discards)
                    game.apply(kita[0])
                    assert game.players[seat].hand.kita >= 1
                    assert len(game.players[seat].discards) == before_discards
                    return
                game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この範囲のシードでは北抜きが起きなかった")

    def test_kita_shrinks_dead_wall(self):
        for seed in range(40):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(MAX_STEPS):
                decision = game.decision()
                if decision is None:
                    break
                kita = [a for a in decision.actions if a.type is ActionType.KITA]
                if kita:
                    before = game.wall.dead_wall_size
                    game.apply(kita[0])
                    if game.decision() is not None:
                        assert game.wall.dead_wall_size == before - 1
                    return
                game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この範囲のシードでは北抜きが起きなかった")


class TestKan:
    def test_ankan_reveals_dora_immediately(self):
        # 暗槓は即めくり（ユーザー確定事項）
        for seed in range(60):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(MAX_STEPS):
                decision = game.decision()
                if decision is None:
                    break
                ankan = [a for a in decision.actions if a.type is ActionType.ANKAN]
                if ankan:
                    before = game.wall.revealed_pairs
                    game.apply(ankan[0])
                    assert game.wall.revealed_pairs == before + 1
                    return
                game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この範囲のシードでは暗槓が起きなかった")

    def _open_kan_reveals_after_discard(self, kind):
        """明槓は、カンした直後ではなく、カンした人が打牌したときにドラが増える。"""
        for seed in range(300):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(MAX_STEPS):
                decision = game.decision()
                if decision is None:
                    break
                kans = [a for a in decision.actions if a.type is kind]
                if not kans:
                    game.apply(agent.choose(game, decision.seat, decision.actions))
                    continue
                seat = decision.seat
                before = game.wall.revealed_pairs
                game.apply(kans[0])
                # 加槓は槍槓の確認を挟むので、全員パスさせてから嶺上牌に進める
                while game.decision() is not None and game.phase is Phase.REACTION:
                    game.apply(Action(ActionType.PASS))
                after_kan = game.decision()
                if after_kan is None or after_kan.seat != seat:
                    break  # 四槓散了・槍槓など。別のシードで試す
                assert game.wall.revealed_pairs == before, "カン直後にめくってしまっている"
                discards = [a for a in after_kan.actions if a.type is ActionType.DISCARD]
                if not discards:
                    break
                game.apply(discards[0])
                assert game.wall.revealed_pairs == before + 1, "打牌してもめくられていない"
                return
        pytest.skip(f"この範囲のシードでは{kind}が起きなかった")

    def test_minkan_reveals_dora_after_discard(self):
        # 大明槓は打牌後めくり（ユーザー確定事項）
        self._open_kan_reveals_after_discard(ActionType.MINKAN)

    def test_kakan_reveals_dora_after_discard(self):
        # 加槓も打牌後めくり（ユーザー確定事項）
        self._open_kan_reveals_after_discard(ActionType.KAKAN)

    def test_pending_kan_dora_flushes_before_next_kan(self):
        # 明槓のあと打牌せずに続けてカンしたら、前のカンのぶんを先にめくる
        game = Round(dealer=0, rng=random.Random(1))
        game._pending_kan_dora = 1
        before = game.wall.revealed_pairs
        game._reveal_pending_kan_dora()
        assert game.wall.revealed_pairs == before + 1
        assert game._pending_kan_dora == 0


class TestTwoHanBinding:
    def test_wins_always_satisfy_the_binding(self):
        # 常に二翻縛り。ドラと一発は縛りの翻数に含めない（CLAUDE.md §4.1）
        for seed in range(80):
            game = play_round(seed)
            result = game.result
            if result.kind != "win":
                continue
            for seat in result.winners:
                assert result.values[seat].satisfies_binding


class TestScoreConservation:
    def test_many_rounds(self):
        for seed in range(120):
            game = play_round(seed, dealer=seed % 3)
            assert sum(game.scores) + game.riichi_sticks * 1000 == 75000
            assert all(isinstance(s, int) for s in game.scores)


class TestYakumanBonusIsSeparate:
    def test_no_bonus_without_yakuman(self):
        for seed in range(60):
            game = play_round(seed)
            result = game.result
            if result.kind != "win":
                continue
            if all(v.yakuman == 0 for v in result.values.values()):
                # ご祝儀が混ざっていないこと（供託を除けばゼロサム）
                assert abs(result.payments.total()) <= game.riichi_sticks * 1000 + 4000


class TestRiichiNeedsRealTenpai:
    """3面子 + 2搭子で雀頭がない形を、テンパイと誤認して立直を出していた不具合。"""

    def _round_with(self, notation, drawn, melds=()):
        from fever_sanma.core.hand import Hand

        game = Round(dealer=0, rng=random.Random(0))  # 配牌直後は親の打牌番
        player = game.players[0]
        player.hand = Hand.from_counts(t.counts_of(notation), list(melds), player.hand.kita)
        player.drawn_tile = drawn
        return game

    def riichi_tiles(self, game):
        return {
            a.tile
            for a in game.decision().actions
            if a.type in (ActionType.RIICHI, ActionType.OPEN_RIICHI)
        }

    def test_reported_hand_cannot_riichi(self):
        from fever_sanma.core.hand import Meld, MeldType

        # 画面の手: 2468p 2457776s + 暗槓8索。どれを切っても1向聴
        game = self._round_with("2468p 2456777s", t.sou(6), [Meld(MeldType.ANKAN, t.sou(8))])
        assert self.riichi_tiles(game) == set()

    def test_real_tenpai_still_offers_riichi(self):
        # 9p を切れば 123p 456p 789s 24s 66s のテンパイ（3索待ち）
        game = self._round_with("123p 456p 9p 789s 24s 66s", t.pin(9))
        assert self.riichi_tiles(game) == {t.pin(9)}


class TestWinningHandIsRecorded:
    """局の結果に和了形が残り、それが本当に和了形になっていること（表示して点数を確かめるため）。"""

    def test_hand_plus_win_tile_is_complete(self):
        from fever_sanma.core.hand import Hand, is_complete
        from fever_sanma.ui import cui

        seen = {"tsumo": 0, "ron": 0, "fever": 0}
        for seed in range(400):
            game = play_round(seed)
            result = game.result
            if result.kind != "win" or not result.hands:
                continue
            for seat in result.winners:
                hand = result.hands[seat]
                counts = t.counts_of("")
                for tile in hand.concealed:
                    counts[tile] += 1
                counts[hand.win_tile] += 1
                assert is_complete(Hand.from_counts(counts, list(hand.melds), hand.kita))
                seen["tsumo" if hand.is_tsumo else "ron"] += 1
            for win in result.fever_wins:
                seen["fever"] += 1
                assert win.hand.win_tile == win.win_tile
            assert "手牌:" in cui.render_round_result(result)
        assert seen["tsumo"] and seen["ron"], seen


class TestCallOnKita:
    """他家が抜いた北はポン・カンできる（CLAUDE.md §4.3）。鳴いたら抜きドラから外れて副露になる。"""

    def _round(self):
        from fever_sanma.core.hand import Hand

        game = Round(dealer=0, rng=random.Random(0))  # 配牌直後は親の打牌番
        game.players[0].hand = Hand.from_counts(t.counts_of("123p 456p 789p 23s 55s 4z"))
        game.players[0].drawn_tile = t.PEI
        game.players[1].hand = Hand.from_counts(t.counts_of("19m 2468p 1357s 444z"))
        game.players[2].hand = Hand.from_counts(t.counts_of("19m 2468p 1357s 123z"))
        game.apply(Action(ActionType.KITA, t.PEI))
        return game

    def _call(self, game, kind):
        decision = game.decision()
        assert decision.seat == 1
        call = next(a for a in decision.actions if a.type is kind)
        game.apply(call)
        while (decision := game.decision()) is not None and decision.seat != 1:
            game.apply(next(a for a in decision.actions if a.type is ActionType.PASS))
        return game

    def test_pon_takes_the_kita(self):
        game = self._call(self._round(), ActionType.PON)
        assert game.players[0].hand.kita == 0
        caller = game.players[1].hand
        assert caller.concealed[t.PEI] == 1
        assert [(m.type.name, m.tile) for m in caller.melds] == [("PON", t.PEI)]
        assert game.turn == 1 and game.phase is Phase.DISCARD

    def test_minkan_takes_the_kita(self):
        game = self._call(self._round(), ActionType.MINKAN)
        assert game.players[0].hand.kita == 0
        caller = game.players[1].hand
        assert caller.concealed[t.PEI] == 0
        assert [(m.type.name, m.tile) for m in caller.melds] == [("MINKAN", t.PEI)]
        assert game.turn == 1

    def test_pass_lets_the_kita_player_draw(self):
        game = self._round()
        while (decision := game.decision()) is not None and decision.phase is Phase.REACTION:
            game.apply(next(a for a in decision.actions if a.type is ActionType.PASS))
        assert game.players[0].hand.kita == 1
        assert game.turn == 0


class TestNoKyuushu:
    """フィーバー三麻に九種九牌はない（Wiki に記載なし。ユーザー確認済み）。么九牌だらけでも流せない。"""

    def test_terminal_heavy_first_draw_cannot_abort(self):
        from fever_sanma.core.hand import Hand

        game = Round(dealer=0, rng=random.Random(0))
        game.players[0].hand = Hand.from_counts(t.counts_of("19m 19p 19s 1234567z 55p"))
        game.players[0].drawn_tile = t.pin(5)
        assert game.first_go_around and game.phase is Phase.DRAW
        kinds = {a.type for a in game.decision().actions}
        assert kinds <= {ActionType.DISCARD, ActionType.KITA, ActionType.RIICHI, ActionType.OPEN_RIICHI}
        assert not hasattr(ActionType, "KYUUSHU")
