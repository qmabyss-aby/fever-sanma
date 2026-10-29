"""tkinter による GUI。

設計の要点:

- **スレッドを使わない**。局は `Round.decision()` / `Round.apply()` で1手ずつ進められるので、
  CPU の手番は `root.after()` で次の1手を予約するだけにしている。人間の手番が来たら
  何も予約せずに止まり、クリックされた手を `apply()` してから再開する。
  こうするとイベントループが止まらず、ゲーム状態を2つのスレッドから触る心配もない。
- 局と局のあいだは `Match.start_round()` / `Match.end_round()` で進める。
- 表示文言の多くは CUI（`ui/cui.py`）と共有する。
"""

from __future__ import annotations

import random
import tkinter as tk
from collections.abc import Sequence
from tkinter import font as tkfont

from ..core import hidden
from ..core.game import Action, ActionType, Phase, Round, RoundResult
from ..core.hand import MeldType
from ..core.match import Match, MatchResult
from ..core.tiles import PEI, number_of, suit_of, tile_name
from ..players import AI_LABELS, make_cpu, resolve_ai_kinds
from . import cui

CPU_DELAY_MS = 450
"""CPU が1手打つまでの間。速すぎると何が起きたか追えない。"""

BG = "#1f6b45"  # 卓の緑
PANEL_BG = "#245c3f"
TEXT_FG = "#f4f4f4"
TILE_BG = "#fbf8ef"
DRAWN_BG = "#fff1a8"
LAST_DISCARD_BG = "#ffd27a"
RIICHI_TILE_BG = "#f2b8b8"
BACK_BG = "#2f5f9e"

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

# 手牌の下に並べるボタン。打牌と立直の宣言牌は牌のクリックで扱うので含めない。
# 北抜きは加槓などと同じくボタンにする（牌のクリックにすると、押せることに気づきにくい）。
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


def tile_face(tile: int) -> tuple[str, str]:
    """牌の表面に書く文字と色。"""
    suit = suit_of(tile)
    if suit == "z":
        char = HONOR_CHARS[number_of(tile) - 1]
        return char, HONOR_COLORS.get(char, "#222222")
    return f"{number_of(tile)}\n{SUIT_CHARS[suit]}", SUIT_COLORS[suit]


def pick_font_family(root: tk.Misc) -> str:
    families = set(tkfont.families(root))
    for name in ("Yu Gothic UI", "Meiryo UI", "Meiryo", "MS Gothic", "Noto Sans CJK JP"):
        if name in families:
            return name
    return "TkDefaultFont"


class FeverSanmaApp:
    """フィーバー三麻の GUI。人間1人 vs CPU2人。"""

    def __init__(
        self,
        root: tk.Tk,
        human_seat: int = 0,
        rng: random.Random | None = None,
        cpu_delay: int = CPU_DELAY_MS,
        ai: str | Sequence[str] = "strong",
    ) -> None:
        self.root = root
        self.human = human_seat
        self.rng = rng or random.Random()
        self.cpu_delay = cpu_delay
        self.ai_spec = [ai] if isinstance(ai, str) else list(ai)
        """CPU の指定。"any" を含むなら、東風戦を始めるたびに選び直す。"""
        self.cpu_kinds: dict[int, str] = {}
        self.agents: list = []

        self.match: Match | None = None
        self.game: Round | None = None
        self.pending = None
        """人間の選択待ちの Decision。None なら人間は何も選べない。"""
        self.riichi_mode: ActionType | None = None
        """立直／オープン立直ボタンを押して、宣言牌を選んでいる最中か。"""
        self.dialog: tk.Toplevel | None = None
        self.state = "idle"
        self._current = None
        """"playing" / "fever_win"（フィーバー中の和了を表示中）/ "round_end"（局の結果表示中）/
        "match_end"（終局表示中）。"""
        self._fever_shown = 0
        """この局で、ポップアップを出し終えたフィーバー和了の件数。"""
        self._after_id: str | None = None
        """予約している「次の1手」。常に1本だけにする（_schedule を参照）。"""

        family = pick_font_family(root)
        self.font_tile = tkfont.Font(root, family=family, size=15, weight="bold")
        self.font_small_tile = tkfont.Font(root, family=family, size=10, weight="bold")
        self.font_text = tkfont.Font(root, family=family, size=11)
        self.font_header = tkfont.Font(root, family=family, size=12, weight="bold")
        self.font_banner = tkfont.Font(root, family=family, size=13, weight="bold")

        root.title("フィーバー三麻")
        root.configure(bg=BG)
        root.minsize(1000, 720)
        self._typed = ""
        """隠しコマンドの判定用に、直近に打たれた文字をためておく。"""
        root.bind_all("<Key>", self._on_key, add="+")
        self._build_layout()
        self.new_match()

    # --- 画面の骨組み ------------------------------------------------------

    def _build_layout(self) -> None:
        self.info = tk.Frame(self.root, bg=BG)
        self.info.pack(fill="x", padx=10, pady=(8, 2))

        self.banner = tk.Label(
            self.root, text="", bg=BG, fg="#ffe066", font=self.font_banner
        )
        self.banner.pack(fill="x", padx=10)

        self.opponents = tk.Frame(self.root, bg=BG)
        self.opponents.pack(fill="x", padx=10, pady=4)
        others = [(self.human + offset) % 3 for offset in (1, 2)]
        self.panels: dict[int, tk.Frame] = {}
        for seat in others:
            panel = tk.Frame(self.opponents, bg=PANEL_BG, bd=1, relief="ridge")
            panel.pack(side="left", fill="both", expand=True, padx=4)
            self.panels[seat] = panel

        middle = tk.Frame(self.root, bg=BG)
        middle.pack(fill="both", expand=True, padx=10, pady=4)
        self.log_text = tk.Text(
            middle, height=7, bg="#163f2a", fg=TEXT_FG, font=self.font_text,
            relief="flat", state="disabled", wrap="word",
        )
        scroll = tk.Scrollbar(middle, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.self_panel = tk.Frame(self.root, bg=PANEL_BG, bd=1, relief="ridge")
        self.self_panel.pack(fill="x", padx=10, pady=(4, 4))
        self.panels[self.human] = self.self_panel

        self.prompt = tk.Label(self.root, text="", bg=BG, fg=TEXT_FG, font=self.font_header)
        self.prompt.pack(fill="x", padx=10)
        self.actions = tk.Frame(self.root, bg=BG)
        self.actions.pack(fill="x", padx=10, pady=(2, 10))

    # --- 進行 --------------------------------------------------------------

    def new_match(self) -> None:
        self._close_dialog()
        self._assign_cpus()
        self.match = Match(self.agents, rng=self.rng)
        opponents = "、".join(
            f"{cui.SEAT_LABELS[seat]}={AI_LABELS[kind]}" for seat, kind in self.cpu_kinds.items()
        )
        self.log(f"=== 東風戦 開始（対戦相手: {opponents}） ===")
        self.start_round()

    def _assign_cpus(self) -> None:
        """人間の下家から順に CPU を割り当てる。"any" の席はランダムに選ぶ。"""
        seats = [(self.human + offset) % 3 for offset in (1, 2)]
        kinds = resolve_ai_kinds(self.ai_spec, len(seats), self.rng)
        self.cpu_kinds = dict(zip(seats, kinds))
        self.agents = [
            make_cpu(self.cpu_kinds.get(seat, "strong"), self.rng) for seat in range(3)
        ]

    def start_round(self) -> None:
        self.game = self.match.start_round()
        self.riichi_mode = None
        self.state = "playing"
        self._fever_shown = 0
        self.log(
            f"--- 東{self.match.round_number}局  親: {cui.SEAT_LABELS[self.game.dealer]}"
            f"  割れ目: {cui.SEAT_LABELS[self.game.wareme]} ---"
        )
        self.render()
        self._schedule(self.cpu_delay, self.step)

    def _schedule(self, delay: int, callback) -> None:
        """次の処理を予約する。**予約は常に1本だけ**にし、古い予約は取り消す。

        予約が2本走ると、片方が古い局面に対して手を打って壊れる（局を作り直したときや、
        同じ局面で step が二重に呼ばれたとき）。
        """
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)

        def run() -> None:
            self._after_id = None
            callback()

        self._after_id = self.root.after(delay, run)

    def step(self) -> None:
        """次の1手を進める。人間の番なら止まってクリックを待つ。"""
        if self.state != "playing":
            return
        # フィーバー中に和了が出ていたら、まずその1回ぶんの点数を見せて止まる。
        # 山の最後の牌で和了して同時に終局した場合も、こちらを先に出す。
        if len(self.game.fever_wins) > self._fever_shown:
            self.show_fever_win(self._fever_shown)
            return
        decision = self.game.decision()
        if decision is None:
            self.finish_round()
            return

        if decision.seat == self.human:
            if len(decision.actions) == 1:
                # 選択の余地が無い（フィーバー中の強制ツモ切りなど）ときは自動で進める
                self.pending = None
                self.render()
                self._schedule(self.cpu_delay, lambda: self.apply(decision.actions[0]))
                return
            self.pending = decision
            self.render()
            return

        self.pending = None
        action = self.agents[decision.seat].choose(self.game, decision.seat, decision.actions)
        self.game.apply(action)
        self.note(decision.seat, action)
        self.render()
        delay = 0 if action.type is ActionType.PASS else self.cpu_delay
        self._schedule(delay, self.step)

    def apply(self, action: Action) -> None:
        """人間の選んだ手を反映する。"""
        if self.state != "playing":
            return
        self.pending = None
        self.riichi_mode = None
        self.game.apply(action)
        self.note(self.human, action)
        self.render()
        self._schedule(0, self.step)

    def show_fever_win(self, index: int) -> None:
        """フィーバー中の和了1回ぶんの点数をポップアップで見せる。「続ける」で再開する。"""
        self.state = "fever_win"
        self.pending = None
        self._fever_shown = index + 1
        self.render()
        text = self._fever_win_text(index)
        self.log(text)
        self._show_dialog("フィーバー和了", text, [("続ける", self.continue_fever)])

    def continue_fever(self) -> None:
        if self.state != "fever_win":
            return
        self._close_dialog()
        self.state = "playing"
        self._schedule(self.cpu_delay, self.step)

    def _fever_win_text(self, index: int) -> str:
        game = self.game
        win = game.fever_wins[index]
        seat = game.fever_seat
        how = "ツモ" if win.is_tsumo else f"ロン（{cui.SEAT_LABELS[win.discarder]}の放銃）"
        lines = [
            f"★ フィーバー和了 {index + 1}回目",
            f"{cui.SEAT_LABELS[seat]}  {how}  {tile_name(win.win_tile)}",
            f"  {cui.format_value(win.value)}",
        ]
        deltas = win.payments.deltas
        moves = "  ".join(
            f"{cui.SEAT_LABELS[s]} {deltas[s]:+,}" for s in sorted(deltas) if deltas[s]
        )
        lines.append(f"  {moves}")
        lines.append("")
        lines.append("現在の点数（山が尽きるまでツモ切りが続きます）")
        for other, player in enumerate(game.players):
            lines.append(f"  {cui.SEAT_LABELS[other]}  {player.score:,}点")
        return "\n".join(lines)

    def finish_round(self) -> None:
        self.state = "round_end"
        self.pending = None
        result = self.game.result
        self.render(reveal_all=True)
        self.log(cui.render_round_result(result))
        self._show_dialog("局の結果", self._round_text(result), [("次へ", self.next_round)])

    def next_round(self) -> None:
        """局の結果を閉じて次へ進む。"""
        if self.state != "round_end":
            return
        self._close_dialog()
        finished = self.match.end_round(self.game, self.game.result)
        if finished is not None:
            self.finish_match(finished)
        else:
            self.start_round()

    def finish_match(self, result: MatchResult) -> None:
        self.state = "match_end"
        self.log(cui.render_match_result(result))
        self._show_dialog(
            "終局",
            cui.render_match_result(result),
            [("もう一度", self.new_match), ("終了", self.root.destroy)],
        )

    # --- 人間の操作 --------------------------------------------------------

    def on_tile(self, tile: int) -> None:
        """手牌の牌がクリックされた。"""
        if self.pending is None:
            return
        options = self.pending.actions
        if self.riichi_mode is not None:
            action = next(
                (a for a in options if a.type is self.riichi_mode and a.tile == tile), None
            )
            if action is not None:
                self.apply(action)
            return

        # 北も他の牌と同じく、クリックしたら河に捨てる。抜きドラは「北抜き」ボタンで。
        discard = next(
            (a for a in options if a.type is ActionType.DISCARD and a.tile == tile), None
        )
        if discard is not None:
            self.apply(discard)

    def _on_key(self, event: tk.Event) -> None:
        """キー入力。合言葉（fever / benz）が打たれたら隠しコマンドを受け付ける。"""
        if not event.char or not event.char.isprintable():
            return
        self._typed = (self._typed + event.char.lower())[-16:]
        for command in hidden.COMMANDS:
            if self._typed.endswith(command):
                self._typed = ""
                self.enter_hidden(command)
                return

    def enter_hidden(self, command: str) -> None:
        """隠しコマンドを次の配牌に予約する。"""
        if self.match is not None and self.match.request_hidden(self.human, command):
            self.log(f"（隠しコマンド: 次の配牌で{hidden.DESCRIPTIONS[command]}）")

    def toggle_riichi(self, kind: ActionType) -> None:
        """立直／オープン立直ボタン。押してから宣言牌を選ぶ。もう一度押すと取り消し。"""
        self.riichi_mode = None if self.riichi_mode is kind else kind
        self.render()

    # --- 描画 --------------------------------------------------------------

    def render(self, reveal_all: bool = False) -> None:
        game = self.game
        # decision() は合法手の列挙を伴って重いので、1回の描画で1度だけ計算する
        self._current = game.decision()
        self._render_info()
        if game.fever_seat is not None:
            self.banner.configure(
                text=f"★ フィーバー中  {cui.SEAT_LABELS[game.fever_seat]} / "
                f"{game.fever_yaku.name}  待ち: "
                + " ".join(tile_name(t) for t in sorted(game.fever_waits))
            )
        else:
            self.banner.configure(text="")
        for seat, panel in self.panels.items():
            self._render_player(panel, seat, reveal=reveal_all)
        self._render_actions()

    def _render_info(self) -> None:
        for child in self.info.winfo_children():
            child.destroy()
        game = self.game
        text = (
            f"東{self.match.round_number}局   残り {game.wall.remaining}枚   "
            f"供託 {game.riichi_sticks}本   ドラ表示:"
        )
        tk.Label(self.info, text=text, bg=BG, fg=TEXT_FG, font=self.font_header).pack(side="left")
        for tile in game.wall.dora_indicators():
            self._small_tile(self.info, tile).pack(side="left", padx=1)
        # 局が終わって立直者が上がっていたら、裏ドラ表示牌もめくって見せる
        ura = game.result.ura_indicators if game.result is not None else []
        if ura:
            tk.Label(
                self.info, text="   裏ドラ表示:", bg=BG, fg=TEXT_FG, font=self.font_header
            ).pack(side="left")
            for tile in ura:
                self._small_tile(self.info, tile).pack(side="left", padx=1)

    def _render_player(self, panel: tk.Frame, seat: int, reveal: bool) -> None:
        for child in panel.winfo_children():
            child.destroy()
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
        if is_human:
            marks.append("あなた")
        else:
            marks.append(AI_LABELS[self.cpu_kinds[seat]])
        header = f"{cui.SEAT_LABELS[seat]}  {player.score:,}点"
        if marks:
            header += "  [" + " / ".join(marks) + "]"
        if self._turn_seat() == seat:
            header = "▶ " + header
        tk.Label(panel, text=header, bg=PANEL_BG, fg=TEXT_FG, font=self.font_header,
                 anchor="w").pack(fill="x", padx=6, pady=(4, 2))

        self._render_river(panel, seat)

        row = tk.Frame(panel, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(2, 6))
        # 自分・終局時・フィーバー中のリーチ者（全公開 / CLAUDE.md §4.5）・オープン立直は手牌を見せる
        show = is_human or reveal or seat == game.fever_seat or player.open_riichi
        if is_human:
            self._render_own_hand(row, seat)
        elif show:
            for tile in self._hand_tiles(seat):
                self._small_tile(row, tile).pack(side="left", padx=1)
        else:
            for _ in range(sum(player.hand.concealed)):
                tk.Label(row, text=" ", bg=BACK_BG, width=2, height=2, relief="raised",
                         font=self.font_small_tile).pack(side="left", padx=1)
        self._render_melds(row, seat)

    def _turn_seat(self) -> int | None:
        decision = self._current
        return decision.seat if decision is not None else None

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

    def _render_river(self, panel: tk.Frame, seat: int) -> None:
        """河。捨てた順に6枚ずつ並べる。"""
        game = self.game
        player = game.players[seat]
        river = tk.Frame(panel, bg=PANEL_BG)
        river.pack(fill="x", padx=6)
        tk.Label(river, text="河", bg=PANEL_BG, fg=TEXT_FG, font=self.font_text).grid(
            row=0, column=0, sticky="nw", padx=(0, 4)
        )
        last = len(player.discards) - 1
        is_last_discarder = game.last_discarder == seat and game.phase is Phase.REACTION
        for index, tile in enumerate(player.discards):
            bg = TILE_BG
            if index == player.riichi_discard_index:
                bg = RIICHI_TILE_BG  # 立直宣言牌
            if index == last and is_last_discarder:
                bg = LAST_DISCARD_BG  # 鳴き・ロンの確認中の牌
            self._small_tile(river, tile, bg=bg).grid(
                row=index // 12, column=1 + index % 12, padx=1, pady=1
            )
        if not player.discards:
            tk.Label(river, text="", bg=PANEL_BG, height=2).grid(row=0, column=1)

    def _render_melds(self, row: tk.Frame, seat: int) -> None:
        player = self.game.players[seat]
        for meld in reversed(player.hand.melds):
            group = tk.Frame(row, bg=PANEL_BG)
            group.pack(side="right", padx=6)
            tk.Label(group, text=MELD_LABELS[meld.type], bg=PANEL_BG, fg=TEXT_FG,
                     font=self.font_text).pack(side="top")
            tiles = tk.Frame(group, bg=PANEL_BG)
            tiles.pack(side="top")
            for tile in meld.tiles:
                self._small_tile(tiles, tile).pack(side="left", padx=1)
        if player.hand.kita:
            group = tk.Frame(row, bg=PANEL_BG)
            group.pack(side="right", padx=6)
            tk.Label(group, text=f"抜きドラ ×{player.hand.kita}", bg=PANEL_BG, fg=TEXT_FG,
                     font=self.font_text).pack(side="top")
            tiles = tk.Frame(group, bg=PANEL_BG)
            tiles.pack(side="top")
            for _ in range(player.hand.kita):
                self._small_tile(tiles, PEI).pack(side="left", padx=1)

    def _render_own_hand(self, row: tk.Frame, seat: int) -> None:
        """自分の手牌。押せる牌だけ有効にする。ツモ牌は少し離して右端に置く。"""
        player = self.game.players[seat]
        playable = self._playable_tiles()
        tiles = self._hand_tiles(seat)
        for index, tile in enumerate(tiles):
            is_drawn = player.drawn_tile is not None and index == len(tiles) - 1
            text, color = tile_face(tile)
            button = tk.Button(
                row,
                text=text,
                fg=color,
                bg=DRAWN_BG if is_drawn else TILE_BG,
                activebackground="#ffe9a0",
                # 自分の番でないときは色を変えない（押せないだけ）。灰色にするのは
                # 自分の番なのに切れない牌（喰い替え禁止・立直の宣言牌選び）だけ。
                disabledforeground=color if self.pending is None else "#b8b3a6",
                font=self.font_tile,
                width=2,
                height=2,
                relief="raised",
                bd=2,
                state="normal" if tile in playable else "disabled",
                command=lambda t=tile: self.on_tile(t),
            )
            button.pack(side="left", padx=(14 if is_drawn else 1, 1))

    def _playable_tiles(self) -> set[int]:
        if self.pending is None:
            return set()
        options = self.pending.actions
        if self.riichi_mode is not None:
            return {a.tile for a in options if a.type is self.riichi_mode}
        return {a.tile for a in options if a.type is ActionType.DISCARD}

    def _render_actions(self) -> None:
        for child in self.actions.winfo_children():
            child.destroy()
        if self.pending is None:
            seat = self._turn_seat()
            if self.state == "playing" and seat is not None and seat != self.human:
                self.prompt.configure(text=f"{cui.SEAT_LABELS[seat]} の番です…")
            else:
                self.prompt.configure(text="")
            return

        game = self.game
        options = self.pending.actions
        if game.phase is Phase.REACTION:
            self.prompt.configure(
                text=f"{cui.SEAT_LABELS[game.last_discarder]} の "
                f"{tile_name(game.last_discard)} に対して"
            )
        elif self.riichi_mode is ActionType.RIICHI:
            self.prompt.configure(text="立直の宣言牌を選んでください")
        elif self.riichi_mode is ActionType.OPEN_RIICHI:
            self.prompt.configure(text="オープン立直の宣言牌を選んでください")
        else:
            self.prompt.configure(text="あなたの番です。切る牌をクリックしてください")

        for kind in (ActionType.RIICHI, ActionType.OPEN_RIICHI):
            if any(a.type is kind for a in options):
                active = self.riichi_mode is kind
                label = cui.ACTION_LABELS[kind] + ("（取消）" if active else "")
                self._action_button(
                    label, lambda k=kind: self.toggle_riichi(k), active=active
                )

        for kind in BUTTON_ORDER:
            for action in options:
                if action.type is kind:
                    label = "北抜き" if kind is ActionType.KITA else cui.format_action(action)
                    self._action_button(label, lambda a=action: self.apply(a))

    def _action_button(self, label: str, command, active: bool = False) -> None:
        tk.Button(
            self.actions,
            text=label,
            command=command,
            font=self.font_header,
            bg="#f6c453" if active else "#e8e2d0",
            relief="sunken" if active else "raised",
            padx=10,
        ).pack(side="left", padx=4)

    def _small_tile(self, parent: tk.Misc, tile: int, bg: str = TILE_BG) -> tk.Label:
        text, color = tile_face(tile)
        return tk.Label(
            parent, text=text, fg=color, bg=bg, font=self.font_small_tile,
            width=2, height=2, relief="raised", bd=1,
        )

    # --- ログ・ダイアログ --------------------------------------------------

    def note(self, seat: int, action: Action) -> None:
        if action.type is ActionType.PASS:
            return
        self.log(f"{cui.SEAT_LABELS[seat]}: {cui.format_action(action)}")

    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _round_text(self, result: RoundResult) -> str:
        lines = [cui.render_round_result(result), ""]
        for seat, player in enumerate(self.game.players):
            lines.append(f"{cui.SEAT_LABELS[seat]}  {player.score:,}点")
        return "\n".join(lines)

    def _show_dialog(self, title: str, text: str, buttons) -> None:
        self._close_dialog()
        dialog = tk.Toplevel(self.root, bg=PANEL_BG)
        dialog.title(title)
        dialog.transient(self.root)
        tk.Label(
            dialog, text=text, bg=PANEL_BG, fg=TEXT_FG, font=self.font_text,
            justify="left", padx=16, pady=12,
        ).pack()
        row = tk.Frame(dialog, bg=PANEL_BG)
        row.pack(pady=(0, 12))
        for label, command in buttons:
            tk.Button(row, text=label, command=command, font=self.font_header,
                      padx=12).pack(side="left", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", buttons[0][1])
        # 卓の中央に出す（既定だと画面の隅に出て卓に重なる）
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.lift()
        self.dialog = dialog

    def _close_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.destroy()
            self.dialog = None


def run(
    human_seat: int = 0,
    rng: random.Random | None = None,
    cpu_delay: int = CPU_DELAY_MS,
    ai: str | Sequence[str] = "strong",
) -> None:
    root = tk.Tk()
    FeverSanmaApp(root, human_seat=human_seat, rng=rng, cpu_delay=cpu_delay, ai=ai)
    root.mainloop()
