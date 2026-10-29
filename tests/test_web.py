"""ブラウザ版の進行役（ui/web.py）のテスト。JavaScript と同じ呼び方だけで試す。"""

import json
import random

from fever_sanma.core.game import ActionType
from fever_sanma.ui.web import WebSession, faces_json

MAX_CALLS = 200_000


def play(session: WebSession, rng: random.Random, until: str = "match_end") -> list[dict]:
    """JavaScript の動きをまねて進める。人間は押せるボタンか切れる牌をランダムに選ぶ。"""
    views = []
    for _ in range(MAX_CALLS):
        delay = session.tick()
        view = json.loads(session.view_json())  # 毎回 JSON にできること
        views.append(view)
        if view["state"] == until and view["dialog"] is not None:
            return views
        if delay is not None:
            continue
        if view["dialog"] is not None:
            session.dialog_button(0)
            continue
        own = view["players"][view["human"]]["hand"]
        playable = [t["tile"] for t in own if t["playable"]]
        buttons = [b for b in view["buttons"] if not b["active"]]
        if buttons and (not playable or rng.random() < 0.5):
            session.press(rng.choice(buttons)["id"])
        else:
            assert playable, "操作待ちなのに押せるものが無い"
            assert session.click_tile(rng.choice(playable))
    raise AssertionError("終わらなかった")


class TestWholeMatch:
    def test_plays_to_the_end(self):
        for seed in range(3):
            rng = random.Random(seed)
            session = WebSession(ai="any", rng=rng)
            views = play(session, random.Random(seed + 100))
            result = views[-1]["result"]
            assert result is not None
            assert result["rank"] in (1, 2, 3)
            assert len(result["opponents"]) == 2

    def test_play_again_starts_a_new_match(self):
        session = WebSession(ai="random", rng=random.Random(1))
        play(session, random.Random(2))
        session.dialog_button(0)  # もう一度
        view = session.view()
        assert view["state"] == "playing"
        assert view["result"] is None


class TestView:
    def test_cpu_hands_are_hidden(self):
        session = WebSession(ai="random", rng=random.Random(0))
        view = session.view()
        for player in view["players"]:
            if player["seat"] == view["human"]:
                assert player["hand"] is not None
            else:
                assert player["hand"] is None
                assert player["hidden"] >= 13

    def test_log_is_returned_once(self):
        session = WebSession(ai="random", rng=random.Random(0))
        assert session.view()["log"]  # 開始のあいさつ
        assert session.view()["log"] == []

    def test_faces_cover_all_tiles(self):
        faces = json.loads(faces_json())
        assert len(faces) == 27
        assert faces[0]["top"] == "1" and faces[0]["bottom"] == "萬"
        assert faces[23]["top"] == "北"


class TestControls:
    def test_click_outside_turn_is_ignored(self):
        session = WebSession(ai="random", rng=random.Random(0), human_seat=1)
        assert session.pending is None
        assert not session.click_tile(0)

    def reach_riichi_chance(self, session) -> bool:
        """立直を選べる場面まで進める。人間は立直以外ではツモ切りかパスをする。"""
        for _ in range(10_000):
            if session.state == "match_end":
                return False
            if session.state != "playing":
                session.dialog_button(0)
                continue
            if session.tick() is not None or session.pending is None:
                continue
            options = session.pending.actions
            if any(a.type is ActionType.RIICHI for a in options):
                return True
            discards = [a.tile for a in options if a.type is ActionType.DISCARD]
            if discards:
                drawn = session.game.players[session.human].drawn_tile
                session.click_tile(drawn if drawn in discards else discards[0])
                continue
            view = session.view()
            passing = [b for b in view["buttons"] if b["label"] == "パス"]
            session.press((passing or view["buttons"])[0]["id"])
        return False

    def test_riichi_button_switches_to_declaration_tiles(self):
        for seed in range(50):
            session = WebSession(ai="random", rng=random.Random(seed))
            if not self.reach_riichi_chance(session):
                continue
            view = session.view()
            riichi = next(b for b in view["buttons"] if b["label"] == "立直")
            session.press(riichi["id"])
            view = session.view()
            own = view["players"][view["human"]]["hand"]
            playable = {t["tile"] for t in own if t["playable"]}
            expected = {a.tile for a in session.pending.actions if a.type is ActionType.RIICHI}
            assert playable == expected
            assert any(b["label"] == "立直（取消）" for b in view["buttons"])
            assert session.click_tile(next(iter(playable)))
            assert session.game.players[session.human].riichi
            return
        raise AssertionError("立直できる場面が出なかった")

    def test_hidden_command(self):
        session = WebSession(ai="random", rng=random.Random(0))
        results = [session.key(c) for c in "benz"]
        assert results[-1] == "benz"
        assert any("隠しコマンド" in line for line in session.view()["log"])

    def test_hidden_command_by_tap(self):
        # スマホ向け: 画面の連続タップから直接呼ぶ。次の配牌に仕込まれる
        session = WebSession(ai="random", rng=random.Random(0))
        assert session.hidden_command("fever") == "fever"
        assert session.hidden_command("nope") is None
        assert session.match.hidden_requests[session.human] == ["fever"]
        assert any("フィーバーモード" in line for line in session.view()["log"])


class TestWinningHandInDialog:
    def test_round_result_dialog_shows_winning_hand(self):
        found = 0
        for seed in range(5):
            session = WebSession(ai="strong", rng=random.Random(seed))
            for view in play(session, random.Random(seed + 50)):
                dialog = view["dialog"]
                if not dialog or dialog["title"] != "局の結果" or "和了" not in dialog["text"]:
                    continue
                assert dialog["hands"], dialog["text"]
                for hand in dialog["hands"]:
                    tiles = len(hand["concealed"]) + 1 + 3 * len(hand["melds"])
                    assert tiles == 14, hand
                    assert hand["how"] in ("ツモ", "ロン")
                assert "手牌:" in dialog["text"]
                found += 1
        assert found
