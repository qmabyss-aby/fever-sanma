"""表示層のスモークテスト。

見た目そのものは固定しないが、あらゆる局面で例外を出さないこと、そして
「伏せるべき手牌が漏れていないか」だけは押さえる。
"""

import random

import pytest

from fever_sanma.core.game import Action, ActionType, Phase, Round
from fever_sanma.core.match import Match
from fever_sanma.core import tiles as t
from fever_sanma.players import RandomAgent
from fever_sanma.ui import cui


class TestRendering:
    def test_table_renders(self):
        game = Round(dealer=0, rng=random.Random(1))
        text = cui.render_table(game)
        assert "東家" in text and "南家" in text and "西家" in text
        assert "親" in text and "割れ目" in text

    def test_every_decision_renders(self):
        rng = random.Random(2)
        game = Round(dealer=0, rng=rng)
        agent = RandomAgent(rng)
        for _ in range(400):
            decision = game.decision()
            if decision is None:
                break
            entries = cui.build_menu(game, decision.seat, decision.actions)
            assert cui.render_menu(game, decision.seat, entries)
            for action in decision.actions:
                assert cui.format_action(action)
            game.apply(agent.choose(game, decision.seat, decision.actions))

    def test_other_hands_are_hidden_from_viewer(self):
        game = Round(dealer=0, rng=random.Random(1))
        text = cui.render_table(game, viewer=0)
        assert text.count("（伏せ") == 2

    def test_river_keeps_discard_order(self):
        # 河は捨てた順に並ぶ。並べ替えると何を何番目に切ったか読めなくなる。
        game = Round(dealer=0, rng=random.Random(1))
        game.players[0].discards = [t.sou(9), t.pin(1), t.sou(1), t.TON]
        text = cui.render_table(game, viewer=0)
        assert "河: 9s 1p 1s 1z" in text

    def test_hidden_hands_still_show_their_size(self):
        game = Round(dealer=0, rng=random.Random(1))
        text = cui.render_table(game, viewer=0)
        assert "（伏せ 13枚）" in text

    def test_melds_are_visible_even_when_hand_is_hidden(self):
        # 副露は場に晒された公開情報なので伏せない
        from fever_sanma.core.hand import Meld, MeldType

        game = Round(dealer=0, rng=random.Random(1))
        game.players[1].hand.melds.append(Meld(MeldType.PON, t.PEI, called_from=0))
        text = cui.render_table(game, viewer=0)
        assert "ポン" in text

    def test_kita_count_is_visible_even_when_hand_is_hidden(self):
        game = Round(dealer=0, rng=random.Random(1))
        game.players[1].hand.kita = 2
        text = cui.render_table(game, viewer=0)
        assert "北抜き2" in text

    def test_fever_player_hand_is_revealed(self):
        # フィーバー中はリーチ者の手牌を全公開する（CLAUDE.md §4.5）
        game = Round(dealer=0, rng=random.Random(1))
        game.fever_seat = 1
        game.fever_yaku = type("Y", (), {"name": "フィーバー立直"})()
        game.fever_waits = frozenset({t.pin(1)})
        text = cui.render_table(game, viewer=0)
        assert text.count("（伏せ") == 1  # 西家だけ伏せられる
        assert "フィーバー中" in text

    def test_round_and_match_results_render(self):
        agents = [RandomAgent(random.Random(4)) for _ in range(3)]
        rendered: list[str] = []
        result = Match(
            agents,
            rng=random.Random(4),
            on_round_end=lambda g, r: rendered.append(cui.render_round_result(r)),
        ).play()
        assert all(rendered)
        assert cui.render_match_result(result)
        assert "終局" in cui.render_match_result(result)


class TestDiscardMenu:
    """打牌メニューは手牌の枚数どおりに並び、0番がツモ牌になる。

    ルールエンジンの選択肢は「牌の種類」単位で重複しないので、そのまま出すと
    手牌14枚に対して候補が11個などになって紛らわしい。ここで展開している。
    """

    def menu_for_turn(self, seed=0):
        game = Round(dealer=0, rng=random.Random(seed))
        decision = game.decision()
        return game, decision, cui.build_menu(game, decision.seat, decision.actions)

    def test_one_entry_per_tile_in_hand(self):
        game, _, entries = self.menu_for_turn()
        tiles = [e for e in entries if e.tile is not None]
        assert len(tiles) == sum(game.players[0].hand.concealed) == 14

    def test_index_zero_is_the_drawn_tile(self):
        game, _, entries = self.menu_for_turn()
        assert entries[0].tile == game.players[0].drawn_tile
        assert "ツモ牌" in entries[0].label

    def test_duplicates_appear_separately(self):
        game, _, entries = self.menu_for_turn()
        counts = game.players[0].hand.concealed
        duplicated = [tile for tile in range(27) if counts[tile] >= 2]
        assert duplicated, "このシードでは重複牌がない"
        for tile in duplicated:
            assert sum(1 for e in entries if e.tile == tile) == counts[tile]

    def test_tiles_come_before_other_actions(self):
        _, _, entries = self.menu_for_turn()
        tile_indexes = [i for i, e in enumerate(entries) if e.tile is not None]
        other_indexes = [i for i, e in enumerate(entries) if e.tile is None]
        assert not other_indexes or max(tile_indexes) < min(other_indexes)

    def test_every_entry_is_selectable_when_nothing_is_forbidden(self):
        _, _, entries = self.menu_for_turn()
        assert all(e.selectable for e in entries)

    def test_riichi_does_not_take_a_number(self):
        # 立直は牌を選んだあとに聞くので、メニューには立直の行を作らない
        for seed in range(60):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(400):
                decision = game.decision()
                if decision is None:
                    break
                riichi = [
                    a for a in decision.actions if a.type is ActionType.RIICHI
                ]
                if riichi:
                    entries = cui.build_menu(game, decision.seat, decision.actions)
                    assert all(
                        e.action is None or e.action.type is not ActionType.RIICHI
                        for e in entries
                    )
                    marked = [e for e in entries if e.note == "立直可"]
                    assert {e.tile for e in marked} == {a.tile for a in riichi}
                    assert cui.riichi_choices(decision.actions, riichi[0].tile)
                    return
                game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この範囲のシードでは立直の機会が無かった")

    def test_reaction_menu_has_no_tile_entries(self):
        rng = random.Random(2)
        game = Round(dealer=0, rng=rng)
        agent = RandomAgent(rng)
        for _ in range(400):
            decision = game.decision()
            if decision is None:
                break
            if decision.phase is Phase.REACTION:
                entries = cui.build_menu(game, decision.seat, decision.actions)
                assert all(e.tile is None for e in entries)
                assert len(entries) == len(decision.actions)
                return
            game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この局では鳴きの確認が発生しなかった")

    def test_unselectable_entries_are_marked(self):
        # 喰い替えで切れない牌は行としては出すが選ばせない
        entry = cui.MenuEntry("1筒", None, "喰い替えで切れない", tile=2)
        assert not entry.selectable
        text = cui.render_menu(
            Round(dealer=0, rng=random.Random(0)), 0, [entry]
        )
        assert "喰い替えで切れない" in text


class TestKitaMenu:
    """北は「河に捨てる / 抜きドラにする」を牌の行から選ばせる。

    別々の行にすると「北」と「北抜き 北」が離れた番号に並んで紛らわしいため。
    """

    def find_kita_turn(self):
        for seed in range(80):
            rng = random.Random(seed)
            game = Round(dealer=0, rng=rng)
            agent = RandomAgent(rng)
            for _ in range(400):
                decision = game.decision()
                if decision is None:
                    break
                player = game.players[decision.seat]
                has_kita_action = any(
                    a.type is ActionType.KITA for a in decision.actions
                )
                if has_kita_action and player.hand.concealed[t.PEI]:
                    return game, decision
                game.apply(agent.choose(game, decision.seat, decision.actions))
        pytest.skip("この範囲のシードでは北抜きの機会が無かった")

    def test_kita_is_not_a_separate_row(self):
        game, decision = self.find_kita_turn()
        entries = cui.build_menu(game, decision.seat, decision.actions)
        assert not any(
            e.action is not None and e.action.type is ActionType.KITA and e.tile is None
            for e in entries
        )

    def test_kita_tile_row_is_marked(self):
        game, decision = self.find_kita_turn()
        entries = cui.build_menu(game, decision.seat, decision.actions)
        rows = [e for e in entries if e.tile == t.PEI]
        assert rows
        assert all("抜きドラ可" in e.note for e in rows)

    def test_kita_tile_row_still_discards_to_the_river(self):
        # 行の既定の動作はあくまで「河に捨てる」
        game, decision = self.find_kita_turn()
        entries = cui.build_menu(game, decision.seat, decision.actions)
        row = next(e for e in entries if e.tile == t.PEI)
        assert row.action.type is ActionType.DISCARD

    def test_kita_choice_only_for_kita_tile(self):
        game, decision = self.find_kita_turn()
        assert cui.kita_choice(decision.actions, t.PEI) is not None
        assert cui.kita_choice(decision.actions, t.pin(1)) is None

    def test_kita_choice_absent_when_not_offered(self):
        game = Round(dealer=0, rng=random.Random(1))
        decision = game.decision()
        actions = [a for a in decision.actions if a.type is not ActionType.KITA]
        assert cui.kita_choice(actions, t.PEI) is None


class TestActionLabels:
    def test_every_action_type_has_a_label(self):
        for action_type in ActionType:
            assert action_type in cui.ACTION_LABELS

    def test_chi_shows_the_full_run(self):
        text = cui.format_action(Action(ActionType.CHI, t.pin(1), from_seat=2))
        assert "123p" in text

    def test_tileless_action(self):
        assert cui.format_action(Action(ActionType.PASS)) == "パス"
