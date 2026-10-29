"""隠しコマンド（fever / benz）のテスト。"""

import random
import tkinter as tk

import pytest

from fever_sanma.core import hidden
from fever_sanma.core import tiles as t
from fever_sanma.core.match import Match
from fever_sanma.core.wall import Wall
from fever_sanma.players import RandomAgent


def new_match(seed=0):
    return Match([RandomAgent(random.Random(seed)) for _ in range(3)], rng=random.Random(seed))


def dealt(game, seat):
    """配牌13枚（親はツモ済みなのでツモ牌を除く）。"""
    counts = list(game.players[seat].hand.concealed)
    drawn = game.players[seat].drawn_tile
    if drawn is not None:
        counts[drawn] -= 1
    return counts


class TestRigDeal:
    @pytest.mark.parametrize("seat", [0, 1, 2])
    def test_guaranteed_tiles_are_in_the_hand(self, seat):
        rng = random.Random(seat)
        tiles = t.build_full_set()
        rng.shuffle(tiles)
        rigged = hidden.rig_deal(tiles, seat, [t.sou(8)] * 4 + [t.pin(7)] * 3)
        hands = Wall(tiles=rigged).deal()
        counts = t.to_counts(hands[seat])
        assert counts[t.sou(8)] == 4
        assert counts[t.pin(7)] >= 3

    def test_wall_composition_is_unchanged(self):
        tiles = t.build_full_set()
        random.Random(0).shuffle(tiles)
        rigged = hidden.rig_deal(tiles, 0, [t.sou(8)] * 4)
        assert sorted(rigged) == sorted(tiles)  # 入れ替えただけで108枚の構成は同じ

    def test_already_present_tiles_are_kept(self):
        # もともと配牌に入っている枚数も数える（3枚以上 = すでに4枚ならそのまま）
        tiles = t.build_full_set()
        random.Random(0).shuffle(tiles)
        rigged = hidden.rig_deal(tiles, 0, [t.sou(7)] * 3)
        again = hidden.rig_deal(rigged, 0, [t.sou(7)] * 3)
        assert again == rigged

    def test_other_seats_are_untouched_in_size(self):
        tiles = t.build_full_set()
        random.Random(3).shuffle(tiles)
        hands = Wall(tiles=hidden.rig_deal(tiles, 1, [t.sou(8)] * 4)).deal()
        assert [len(h) for h in hands] == [13, 13, 13]


class TestGuaranteedTiles:
    def test_fever_is_7p_or_7s_times_three(self):
        seen = set()
        for seed in range(30):
            tiles = hidden.guaranteed_tiles([hidden.FEVER], random.Random(seed))
            assert len(tiles) == 3 and len(set(tiles)) == 1
            seen.add(tiles[0])
        assert seen == {t.pin(7), t.sou(7)}  # どちらも出る

    def test_benz_is_8s_times_four(self):
        assert hidden.guaranteed_tiles([hidden.BENZ], random.Random(0)) == [t.sou(8)] * 4

    def test_unknown_command(self):
        with pytest.raises(ValueError):
            hidden.guaranteed_tiles(["nope"], random.Random(0))


class TestMatch:
    def test_fever_applies_to_next_deal(self):
        match = new_match()
        assert match.request_hidden(0, hidden.FEVER)
        counts = dealt(match.start_round(), 0)
        assert counts[t.pin(7)] >= 3 or counts[t.sou(7)] >= 3

    def test_benz_applies_to_next_deal(self):
        match = new_match()
        match.request_hidden(0, hidden.BENZ)
        assert dealt(match.start_round(), 0)[t.sou(8)] == 4

    def test_both_together(self):
        match = new_match()
        match.request_hidden(0, hidden.FEVER)
        match.request_hidden(0, hidden.BENZ)
        counts = dealt(match.start_round(), 0)
        assert counts[t.sou(8)] == 4
        assert counts[t.pin(7)] >= 3 or counts[t.sou(7)] >= 3

    def test_only_once(self):
        # 1回入力すると1回だけ効く
        match = new_match()
        match.request_hidden(0, hidden.BENZ)
        match.start_round()
        assert match.hidden_requests == {}

    def test_rigs_the_requesting_seat(self):
        match = new_match()
        match.request_hidden(2, hidden.BENZ)
        assert dealt(match.start_round(), 2)[t.sou(8)] == 4

    def test_unknown_command_is_rejected(self):
        match = new_match()
        assert not match.request_hidden(0, "hello")
        assert match.hidden_requests == {}

    def test_no_command_means_normal_deal(self):
        # 何も入力しなければ、仕込みのない普段どおりの山
        match = new_match()
        assert match._next_wall() is None


class TestGui:
    @pytest.fixture
    def app(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            pytest.skip("画面が使えない環境")
        root.withdraw()
        from fever_sanma.ui.gui import FeverSanmaApp

        app = FeverSanmaApp(root, rng=random.Random(0), cpu_delay=0)
        yield app
        root.destroy()

    def type_text(self, app, text):
        for char in text:
            app._on_key(type("E", (), {"char": char})())

    def test_typing_fever_reserves_it(self, app):
        self.type_text(app, "fever")
        assert app.match.hidden_requests == {app.human: [hidden.FEVER]}
        assert "隠しコマンド" in app.log_text.get("1.0", "end")

    def test_typing_benz_with_noise_before(self, app):
        self.type_text(app, "xyzBenz")  # 前に余計な文字があっても、大文字でもよい
        assert app.match.hidden_requests == {app.human: [hidden.BENZ]}

    def test_partial_word_does_nothing(self, app):
        self.type_text(app, "feve")
        assert app.match.hidden_requests == {}

    def test_next_round_is_rigged(self, app):
        self.type_text(app, "benz")
        # 次局の配牌に効くことを、Match に直接次の局を作らせて確かめる
        game = app.match.start_round()
        assert dealt(game, app.human)[t.sou(8)] == 4


class TestCui:
    def test_command_at_the_prompt(self, monkeypatch, capsys):
        from fever_sanma.players.human_cui import HumanCuiAgent
        from fever_sanma.ui import cui

        match = new_match()
        game = match.start_round()
        agent = HumanCuiAgent(on_command=lambda c: match.request_hidden(0, c))
        answers = iter(["fever", "0"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        decision = game.decision()
        agent._ask_entry(cui.build_menu(game, decision.seat, decision.actions))
        assert match.hidden_requests == {0: [hidden.FEVER]}
        assert "隠しコマンド" in capsys.readouterr().out
