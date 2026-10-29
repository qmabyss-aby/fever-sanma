"""GUI のテスト。

ウィンドウを隠したまま tkinter のイベントループを手で回し、人間の手番では
クリックと同じ処理（`on_tile` やボタンの処理）を呼んで、東風戦を最後まで通す。
画面が出せない環境ではまとめてスキップする。
"""

import random
import tkinter as tk

import pytest

from fever_sanma.core.game import ActionType, Phase
from fever_sanma.core import tiles as t
from fever_sanma.ui.gui import FeverSanmaApp

MAX_PUMPS = 20000


@pytest.fixture
def root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("画面が使えない環境")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def make_app(root, seed=0):
    return FeverSanmaApp(root, rng=random.Random(seed), cpu_delay=0)


def pump_until(root, app, condition):
    for _ in range(MAX_PUMPS):
        root.update()
        if condition():
            return True
    return False


def play_like_a_human(root, app, rng):
    """人間の番が来たら、画面上で押せるもののどれかを押す。"""
    for _ in range(MAX_PUMPS):
        root.update()
        if app.state == "fever_win":
            app.continue_fever()
            continue
        if app.state == "round_end":
            app.next_round()
            continue
        if app.state == "match_end":
            return
        if app.pending is None:
            continue
        options = app.pending.actions
        win = [a for a in options if a.type in (ActionType.TSUMO, ActionType.RON)]
        if win:
            app.apply(win[0])
            continue
        tiles = sorted(app._playable_tiles())
        if tiles and rng.random() < 0.85:
            app.on_tile(rng.choice(tiles))  # 牌をクリック
        else:
            app.apply(rng.choice(options))  # ボタンを押す
    raise AssertionError("東風戦が終わらなかった")


class TestFullMatch:
    @pytest.mark.parametrize("seed", [0, 1])
    def test_plays_to_the_end(self, root, seed):
        app = make_app(root, seed)
        play_like_a_human(root, app, random.Random(seed))
        assert app.state == "match_end"
        assert app.match.result is not None
        assert sum(app.match.result.final) == 0


class TestHumanTurn:
    def test_waits_for_the_human(self, root):
        app = make_app(root)
        assert pump_until(root, app, lambda: app.pending is not None)
        assert app.pending.seat == app.human
        # 待っている間は勝手に進まない
        before = app.game.wall.remaining
        for _ in range(50):
            root.update()
        assert app.game.wall.remaining == before

    def test_clicking_a_tile_discards_it(self, root):
        app = make_app(root)
        assert pump_until(root, app, lambda: app.pending is not None)
        player = app.game.players[app.human]
        tile = next(
            a.tile for a in app.pending.actions
            if a.type is ActionType.DISCARD and a.tile != t.PEI
        )
        app.on_tile(tile)
        assert player.discards[-1] == tile

    def test_tiles_without_a_legal_discard_are_disabled(self, root):
        app = make_app(root)
        assert pump_until(root, app, lambda: app.pending is not None)
        legal = {a.tile for a in app.pending.actions if a.type is ActionType.DISCARD}
        assert app._playable_tiles() >= legal

    def test_clicks_are_ignored_on_cpu_turns(self, root):
        app = make_app(root)
        app.pending = None
        before = list(app.game.players[app.human].discards)
        app.on_tile(t.pin(1))
        assert app.game.players[app.human].discards == before


class TestRiichiAndKita:
    def find(self, root, app, predicate):
        rng = random.Random(1)
        for _ in range(MAX_PUMPS):
            root.update()
            if app.state == "fever_win":
                app.continue_fever()
                continue
            if app.state == "round_end":
                app.next_round()
                continue
            if app.state == "match_end":
                break
            if app.pending is None:
                continue
            if predicate(app.pending.actions):
                return True
            discards = [a for a in app.pending.actions if a.type is ActionType.DISCARD]
            app.apply(rng.choice(discards or app.pending.actions))
        return False

    def test_riichi_button_then_tile(self, root):
        # 人間はツモ切りしかしないので立直の機会は少ない。seed 44 で初めて来る
        # （向聴数の修正前は、雀頭のない形も立直できたので早く来ていた）
        for seed in range(44, 60):
            app = make_app(root, seed)
            if self.find(root, app, lambda o: any(a.type is ActionType.RIICHI for a in o)):
                riichi_tiles = {a.tile for a in app.pending.actions if a.type is ActionType.RIICHI}
                app.toggle_riichi(ActionType.RIICHI)
                # 立直モード中は宣言できる牌だけが押せる
                assert app._playable_tiles() == riichi_tiles
                app.on_tile(next(iter(riichi_tiles)))
                assert app.game.players[app.human].riichi
                return
        pytest.skip("立直の機会が無かった")

    def test_riichi_toggle_can_be_cancelled(self, root):
        app = make_app(root)
        assert pump_until(root, app, lambda: app.pending is not None)
        app.toggle_riichi(ActionType.RIICHI)
        app.toggle_riichi(ActionType.RIICHI)
        assert app.riichi_mode is None

    def find_kita(self, root):
        for seed in range(15):
            app = make_app(root, seed)
            if self.find(root, app, lambda o: any(a.type is ActionType.KITA for a in o)):
                return app
        pytest.skip("北抜きの機会が無かった")

    def action_buttons(self, app):
        return {w.cget("text"): w for w in app.actions.winfo_children()}

    def test_kita_is_a_button_like_kakan(self, root):
        # 北抜きは加槓などと同じく、手牌の下のボタンに出る
        app = self.find_kita(root)
        buttons = self.action_buttons(app)
        assert "北抜き" in buttons
        before = app.game.players[app.human].hand.kita
        buttons["北抜き"].invoke()
        assert app.game.players[app.human].hand.kita == before + 1

    def test_clicking_kita_tile_discards_it(self, root):
        # 北の牌をクリックしたら、他の牌と同じくそのまま河に捨てる
        app = self.find_kita(root)
        player = app.game.players[app.human]
        before = player.hand.kita
        app.on_tile(t.PEI)
        assert player.discards[-1] == t.PEI
        assert player.hand.kita == before

    def test_no_kita_button_when_not_allowed(self, root):
        app = make_app(root)
        assert pump_until(root, app, lambda: app.pending is not None)
        if any(a.type is ActionType.KITA for a in app.pending.actions):
            pytest.skip("この局面では北抜きできる")
        assert "北抜き" not in self.action_buttons(app)


class TestRendering:
    def test_opponent_hands_are_hidden(self, root):
        app = make_app(root)
        assert pump_until(root, app, lambda: app.pending is not None)
        for seat, panel in app.panels.items():
            if seat == app.human:
                continue
            buttons = [w for w in panel.winfo_children() if isinstance(w, tk.Button)]
            assert not buttons

    def test_round_end_shows_dialog_and_advances(self, root):
        app = make_app(root)
        rng = random.Random(0)
        for _ in range(MAX_PUMPS):
            root.update()
            if app.state == "fever_win":
                app.continue_fever()
                continue
            if app.state == "round_end":
                break
            if app.pending is not None:
                discards = [a for a in app.pending.actions if a.type is ActionType.DISCARD]
                app.apply(rng.choice(discards or app.pending.actions))
        assert app.state == "round_end"
        assert app.dialog is not None
        rounds = len(app.match.results)
        app.next_round()
        assert len(app.match.results) == rounds + 1
        assert app.state in ("playing", "match_end")

    def test_reaction_prompt_names_the_tile(self, root):
        app = make_app(root)
        rng = random.Random(0)
        for _ in range(MAX_PUMPS):
            root.update()
            if app.state != "playing":
                break
            if app.pending is None:
                continue
            if app.game.phase is Phase.REACTION:
                assert "に対して" in app.prompt.cget("text")
                return
            discards = [a for a in app.pending.actions if a.type is ActionType.DISCARD]
            app.apply(rng.choice(discards or app.pending.actions))
        pytest.skip("鳴きの確認が来なかった")


class TestRandomOpponents:
    def test_any_picks_two_different_ais(self, root):
        app = FeverSanmaApp(root, rng=random.Random(0), cpu_delay=0, ai="any")
        kinds = list(app.cpu_kinds.values())
        assert len(set(kinds)) == 2
        assert "対戦相手" in app.log_text.get("1.0", "end")

    def test_new_match_picks_again(self, root):
        app = FeverSanmaApp(root, rng=random.Random(0), cpu_delay=0, ai="any")
        seen = {tuple(app.cpu_kinds.values())}
        for _ in range(10):
            app.new_match()
            seen.add(tuple(app.cpu_kinds.values()))
        assert len(seen) > 1  # 東風戦を始め直すたびに選び直している


class TestFeverWinPopup:
    """フィーバー中は和了ごとにポップアップで点数を出し、終局したらサマリを出す。"""

    def setup_fever(self, root):
        from fever_sanma.core.game import Round
        from test_fever import FEVER_OK, JUNK_1, JUNK_2, MIXED_WINS, rigged_wall

        app = make_app(root)
        app.state = "idle"  # 最初の局は使わない
        app.game = Round(dealer=0, wall=rigged_wall(FEVER_OK, JUNK_1, JUNK_2, draws="9m", shuffle=MIXED_WINS), wareme=0)
        app._fever_shown = 0
        app.state = "playing"
        app.step()
        riichi = next(
            a
            for a in app.pending.actions
            if a.type is ActionType.RIICHI and a.tile == app.game.players[0].drawn_tile
        )
        app.apply(riichi)
        return app

    def run(self, root, app):
        popups = []
        for _ in range(MAX_PUMPS):
            root.update()
            if app.state == "fever_win":
                popups.append(app.dialog.children)  # ダイアログが出ている
                text = app._fever_win_text(app._fever_shown - 1)
                assert "フィーバー和了" in text and "点" in text
                app.continue_fever()
                continue
            if app.state == "round_end":
                return popups
            if app.pending is not None:
                app.apply(next(a for a in app.pending.actions if a.type is ActionType.DISCARD))
        raise AssertionError("局が終わらなかった")

    def test_popup_for_each_win_then_summary(self, root):
        app = self.setup_fever(root)
        assert app.game.fever_seat == 0
        popups = self.run(root, app)
        result = app.game.result
        assert result.kind == "win"
        # 和了の回数ぶんポップアップが出て、最後に今までと同じ点数画面（サマリ）が出る
        assert len(popups) == len(result.fever_wins) >= 2
        assert app.dialog is not None
        assert f"フィーバー和了 {len(result.fever_wins)}回" in app._round_text(result)

    def test_game_pauses_while_the_popup_is_open(self, root):
        app = self.setup_fever(root)
        for _ in range(MAX_PUMPS):
            root.update()
            if app.state == "fever_win":
                break
            assert app.state != "round_end", "フィーバー中の和了が起きなかった"
            if app.pending is not None:
                app.apply(next(a for a in app.pending.actions if a.type is ActionType.DISCARD))
        remaining = app.game.wall.remaining
        for _ in range(200):
            root.update()
        assert app.state == "fever_win"  # 「続ける」を押すまで止まっている
        assert app.game.wall.remaining == remaining
        app.continue_fever()
        assert app.state == "playing"
