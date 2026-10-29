"""ブラウザ版（Pyodide）の進行役。

ブラウザの中で Python を動かし、画面は JavaScript（`web/app.js`）が描く。
このモジュールは **ブラウザにも JavaScript にも依存しない**。やり取りは2種類だけ:

- `view_json()` … 今の画面に出すものを JSON で返す。JavaScript はこれをそのまま描く
- `tick()` / `click_tile()` / `press()` / `key()` … 進行と人間の操作

進め方は tkinter 版（`ui/gui.py`）と同じで、スレッドを使わない。JavaScript が
`tick()` を呼ぶと1手だけ進み、次に呼ぶまでの待ち時間（ミリ秒）を返す。
人間の選択やポップアップを待つときは None を返すので、JavaScript は何もせずに
クリックを待つ。こうしておけば pytest からも、JavaScript なしで1局を最後まで試せる。
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence

from ..core import hidden
from ..core.game import Action, ActionType, Phase, Round
from ..core.hand import MeldType
from ..core.match import Match, MatchResult
from ..core.tiles import NUM_KINDS, PEI, number_of, suit_of, tile_name
from ..players import AI_LABELS, make_cpu, resolve_ai_kinds
from . import cui

SUIT_CHARS = {"m": "萬", "p": "筒", "s": "索"}
SUIT_COLORS = {"m": "#b3261e", "p": "#1d4f9c", "s": "#16733a"}
HONOR_CHARS = "東南西北白發中"
HONOR_COLORS = {"白": "#7a7a7a", "發": "#16733a", "中": "#b3261e"}

MELD_LABELS = {
    MeldType.CHI: "チー",
    MeldType.PON: "ポン",
    MeldType.MINKAN: "明槓",
    MeldType.KAKAN: "加槓",
    MeldType.ANKAN: "暗槓",
}

# 手牌の下に並べるボタン（tkinter 版と同じ並び）。打牌と立直の宣言牌は牌のクリックで扱う。
BUTTON_ORDER = (
    ActionType.TSUMO,
    ActionType.RON,
    ActionType.PON,
    ActionType.CHI,
    ActionType.MINKAN,
    ActionType.ANKAN,
    ActionType.KAKAN,
    ActionType.KITA,
    ActionType.KYUUSHU,
    ActionType.PASS,
)

STEP = 1
"""tick() が返す「普通の1手ぶん」の待ち時間の単位。実際の長さは JavaScript 側の速度設定で決める。"""


def tile_faces() -> list[dict]:
    """牌の表面（文字と色）の一覧。牌番号で引く。"""
    faces = []
    for tile in range(NUM_KINDS):
        suit = suit_of(tile)
        if suit == "z":
            char = HONOR_CHARS[number_of(tile) - 1]
            faces.append({"top": char, "bottom": "", "color": HONOR_COLORS.get(char, "#222222")})
        else:
            faces.append(
                {"top": str(number_of(tile)), "bottom": SUIT_CHARS[suit], "color": SUIT_COLORS[suit]}
            )
    return faces


class WebSession:
    """人間1人 vs CPU2人の東風戦を、ブラウザから1手ずつ進める。"""

    def __init__(
        self,
        ai: str | Sequence[str] = "any",
        rng: random.Random | None = None,
        human_seat: int = 0,
    ) -> None:
        self.human = human_seat
        self.rng = rng or random.Random()
        self.ai_spec = [ai] if isinstance(ai, str) else list(ai)
        self.cpu_kinds: dict[int, str] = {}
        self.agents: list = []
        self.match: Match | None = None
        self.game: Round | None = None
        self.result: MatchResult | None = None
        self.pending = None
        """人間の選択待ちの Decision。"""
        self.riichi_mode: ActionType | None = None
        self.state = "idle"
        """"playing" / "fever_win" / "round_end" / "match_end"。"""
        self._fever_shown = 0
        self._typed = ""
        self._buttons: list[Callable[[], None]] = []
        self._dialog: dict | None = None
        self._dialog_actions: list[Callable[[], None]] = []
        self._log: list[str] = []
        self.new_match()

    # --- 進行 --------------------------------------------------------------

    def new_match(self) -> None:
        seats = [(self.human + offset) % 3 for offset in (1, 2)]
        kinds = resolve_ai_kinds(self.ai_spec, len(seats), self.rng)
        self.cpu_kinds = dict(zip(seats, kinds))
        self.agents = [make_cpu(self.cpu_kinds.get(s, "strong"), self.rng) for s in range(3)]
        self.match = Match(self.agents, rng=self.rng)
        self.result = None
        self._close_dialog()
        opponents = "、".join(
            f"{cui.SEAT_LABELS[seat]}={AI_LABELS[kind]}" for seat, kind in self.cpu_kinds.items()
        )
        self.log(f"=== 東風戦 開始（対戦相手: {opponents}） ===")
        self._start_round()

    def _start_round(self) -> None:
        self.game = self.match.start_round()
        self.riichi_mode = None
        self.pending = None
        self.state = "playing"
        self._fever_shown = 0
        self.log(
            f"--- 東{self.match.round_number}局  親: {cui.SEAT_LABELS[self.game.dealer]}"
            f"  割れ目: {cui.SEAT_LABELS[self.game.wareme]} ---"
        )

    def tick(self) -> int | None:
        """1手進める。戻り値は次の tick までの待ち時間（STEP 単位）。None なら操作待ち。"""
        if self.state != "playing" or self.pending is not None:
            return None
        if len(self.game.fever_wins) > self._fever_shown:
            self._show_fever_win(self._fever_shown)
            return None
        decision = self.game.decision()
        if decision is None:
            self._finish_round()
            return None
        if decision.seat == self.human:
            if len(decision.actions) == 1:
                # 選択の余地が無い（フィーバー中の強制ツモ切りなど）ときは自動で進める
                self._apply(self.human, decision.actions[0])
                return STEP
            self.pending = decision
            return None
        action = self.agents[decision.seat].choose(self.game, decision.seat, decision.actions)
        self._apply(decision.seat, action)
        return 0 if action.type is ActionType.PASS else STEP

    def _apply(self, seat: int, action: Action) -> None:
        self.game.apply(action)
        if action.type is not ActionType.PASS:
            self.log(f"{cui.SEAT_LABELS[seat]}: {cui.format_action(action)}")

    def _choose(self, action: Action) -> None:
        """人間の選んだ手を反映する。"""
        self.pending = None
        self.riichi_mode = None
        self._apply(self.human, action)

    def _show_fever_win(self, index: int) -> None:
        self.state = "fever_win"
        self._fever_shown = index + 1
        text = self._fever_win_text(index)
        self.log(text)
        self._open_dialog("フィーバー和了", text, [("続ける", self._continue_fever)])

    def _continue_fever(self) -> None:
        self._close_dialog()
        self.state = "playing"

    def _fever_win_text(self, index: int) -> str:
        game = self.game
        win = game.fever_wins[index]
        how = "ツモ" if win.is_tsumo else f"ロン（{cui.SEAT_LABELS[win.discarder]}の放銃）"
        lines = [
            f"★ フィーバー和了 {index + 1}回目",
            f"{cui.SEAT_LABELS[game.fever_seat]}  {how}  {tile_name(win.win_tile)}",
            f"  {cui.format_value(win.value)}",
        ]
        deltas = win.payments.deltas
        lines.append("  " + "  ".join(
            f"{cui.SEAT_LABELS[s]} {deltas[s]:+,}" for s in sorted(deltas) if deltas[s]
        ))
        lines.append("")
        lines.append("現在の点数（山が尽きるまでツモ切りが続きます）")
        for seat, player in enumerate(game.players):
            lines.append(f"  {cui.SEAT_LABELS[seat]}  {player.score:,}点")
        return "\n".join(lines)

    def _finish_round(self) -> None:
        self.state = "round_end"
        result = self.game.result
        self.log(cui.render_round_result(result))
        lines = [cui.render_round_result(result), ""]
        for seat, player in enumerate(self.game.players):
            lines.append(f"{cui.SEAT_LABELS[seat]}  {player.score:,}点")
        self._open_dialog("局の結果", "\n".join(lines), [("次へ", self._next_round)])

    def _next_round(self) -> None:
        self._close_dialog()
        finished = self.match.end_round(self.game, self.game.result)
        if finished is None:
            self._start_round()
            return
        self.state = "match_end"
        self.result = finished
        text = cui.render_match_result(finished)
        self.log(text)
        self._open_dialog("終局", text, [("もう一度", self.new_match)])

    # --- 人間の操作 --------------------------------------------------------

    def click_tile(self, tile: int) -> bool:
        """手牌の牌がクリックされた。手として受け付けたら True。"""
        if self.pending is None:
            return False
        kind = self.riichi_mode or ActionType.DISCARD
        action = next(
            (a for a in self.pending.actions if a.type is kind and a.tile == tile), None
        )
        if action is None:
            return False
        self._choose(action)
        return True

    def press(self, index: int) -> None:
        """手牌の下のボタン（view の buttons の番号）。"""
        if 0 <= index < len(self._buttons):
            self._buttons[index]()

    def dialog_button(self, index: int) -> None:
        """ポップアップのボタン（view の dialog.buttons の番号）。"""
        if 0 <= index < len(self._dialog_actions):
            self._dialog_actions[index]()

    def key(self, char: str) -> str | None:
        """キー入力。合言葉（fever / benz）が打たれたら次の配牌に仕込む。"""
        if len(char) != 1 or not char.isprintable():
            return None
        self._typed = (self._typed + char.lower())[-16:]
        for command in hidden.COMMANDS:
            if self._typed.endswith(command):
                self._typed = ""
                if self.match.request_hidden(self.human, command):
                    self.log(f"（隠しコマンド: 次の配牌で{hidden.DESCRIPTIONS[command]}）")
                    return command
        return None

    def _toggle_riichi(self, kind: ActionType) -> None:
        self.riichi_mode = None if self.riichi_mode is kind else kind

    # --- 表示 --------------------------------------------------------------

    def log(self, text: str) -> None:
        self._log.extend(text.split("\n"))

    def _open_dialog(self, title: str, text: str, buttons) -> None:
        self._dialog = {"title": title, "text": text, "buttons": [label for label, _ in buttons]}
        self._dialog_actions = [command for _, command in buttons]

    def _close_dialog(self) -> None:
        self._dialog = None
        self._dialog_actions = []

    def view_json(self) -> str:
        return json.dumps(self.view(), ensure_ascii=False)

    def view(self) -> dict:
        """画面に出すもの一式。ログは前回の view() 以降に増えた行だけを返す。"""
        game = self.game
        decision = game.decision()
        turn = decision.seat if decision is not None else None
        reveal_all = self.state in ("round_end", "match_end")
        log, self._log = self._log, []
        prompt, buttons = self._actions_view(turn)
        return {
            "state": self.state,
            "info": {
                "round": self.match.round_number,
                "remaining": game.wall.remaining,
                "sticks": game.riichi_sticks,
                "dora": list(game.wall.dora_indicators()),
                "ura": list(game.result.ura_indicators) if game.result is not None else [],
            },
            "banner": self._banner(),
            "human": self.human,
            "players": [self._player_view(seat, turn, reveal_all) for seat in range(3)],
            "prompt": prompt,
            "buttons": buttons,
            "dialog": self._dialog,
            "log": log,
            "result": self._result_view(),
        }

    def _banner(self) -> str:
        game = self.game
        if game.fever_seat is None:
            return ""
        waits = " ".join(tile_name(t) for t in sorted(game.fever_waits))
        return (
            f"★ フィーバー中  {cui.SEAT_LABELS[game.fever_seat]} / "
            f"{game.fever_yaku.name}  待ち: {waits}"
        )

    def _player_view(self, seat: int, turn: int | None, reveal_all: bool) -> dict:
        game = self.game
        player = game.players[seat]
        is_human = seat == self.human
        marks = []
        if seat == game.dealer:
            marks.append("親")
        if seat == game.wareme:
            marks.append("割れ目")
        if player.riichi:
            marks.append("オープン立直" if player.open_riichi else "立直")
        marks.append("あなた" if is_human else AI_LABELS[self.cpu_kinds[seat]])

        last = len(player.discards) - 1
        is_last_discarder = game.last_discarder == seat and game.phase is Phase.REACTION
        river = []
        for index, tile in enumerate(player.discards):
            mark = ""
            if index == player.riichi_discard_index:
                mark = "riichi"
            if index == last and is_last_discarder:
                mark = "last"
            river.append({"tile": tile, "mark": mark})

        # 自分・局の終わり・フィーバー中のリーチ者（全公開 / CLAUDE.md §4.5）・オープン立直は手牌を見せる
        show = is_human or reveal_all or seat == game.fever_seat or player.open_riichi
        tiles = self._hand_tiles(seat)
        playable = self._playable_tiles() if is_human else set()
        hand = None
        if show:
            hand = [
                {
                    "tile": tile,
                    "drawn": player.drawn_tile is not None and index == len(tiles) - 1,
                    "playable": tile in playable,
                }
                for index, tile in enumerate(tiles)
            ]
        return {
            "seat": seat,
            "label": cui.SEAT_LABELS[seat],
            "score": player.score,
            "marks": marks,
            "turn": turn == seat,
            "river": river,
            "hand": hand,
            "hidden": sum(player.hand.concealed),
            "melds": [
                {"label": MELD_LABELS[meld.type], "tiles": list(meld.tiles)}
                for meld in player.hand.melds
            ],
            "kita": player.hand.kita,
        }

    def _hand_tiles(self, seat: int) -> list[int]:
        """手の内の牌（ツモ牌を除いて昇順）とツモ牌。"""
        player = self.game.players[seat]
        counts = list(player.hand.concealed)
        if player.drawn_tile is not None and counts[player.drawn_tile]:
            counts[player.drawn_tile] -= 1
        tiles = [tile for tile, count in enumerate(counts) for _ in range(count)]
        if player.drawn_tile is not None:
            tiles.append(player.drawn_tile)
        return tiles

    def _playable_tiles(self) -> set[int]:
        if self.pending is None:
            return set()
        kind = self.riichi_mode or ActionType.DISCARD
        return {a.tile for a in self.pending.actions if a.type is kind}

    def _actions_view(self, turn: int | None) -> tuple[str, list[dict]]:
        self._buttons = []
        if self.pending is None:
            if self.state == "playing" and turn is not None and turn != self.human:
                return f"{cui.SEAT_LABELS[turn]} の番です…", []
            return "", []

        game = self.game
        options = self.pending.actions
        if game.phase is Phase.REACTION:
            prompt = (
                f"{cui.SEAT_LABELS[game.last_discarder]} の {tile_name(game.last_discard)} に対して"
            )
        elif self.riichi_mode is ActionType.RIICHI:
            prompt = "立直の宣言牌を選んでください"
        elif self.riichi_mode is ActionType.OPEN_RIICHI:
            prompt = "オープン立直の宣言牌を選んでください"
        else:
            prompt = "あなたの番です。切る牌をクリックしてください"

        buttons: list[dict] = []

        def add(label: str, command: Callable[[], None], active: bool = False) -> None:
            buttons.append({"id": len(self._buttons), "label": label, "active": active})
            self._buttons.append(command)

        for kind in (ActionType.RIICHI, ActionType.OPEN_RIICHI):
            if any(a.type is kind for a in options):
                active = self.riichi_mode is kind
                add(
                    cui.ACTION_LABELS[kind] + ("（取消）" if active else ""),
                    lambda k=kind: self._toggle_riichi(k),
                    active,
                )
        for kind in BUTTON_ORDER:
            for action in options:
                if action.type is kind:
                    label = "北抜き" if kind is ActionType.KITA else cui.format_action(action)
                    add(label, lambda a=action: self._choose(a))
        return prompt, buttons

    def _result_view(self) -> dict | None:
        """終局したときの成績（ランキング登録用）。"""
        result = self.result
        if result is None:
            return None
        return {
            "raw": result.scores[self.human],
            "final": result.final[self.human],
            "rank": result.ranking.index(self.human) + 1,
            "opponents": [AI_LABELS[kind] for kind in self.cpu_kinds.values()],
        }


def faces_json() -> str:
    return json.dumps(tile_faces(), ensure_ascii=False)
