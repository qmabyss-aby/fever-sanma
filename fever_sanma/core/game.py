"""局進行の状態機械。

旧実装（`fever_mahjong`）のフリーズバグは、状態遷移が暗黙で「次に何が起きるか」が
コードから読めないことに起因していた。ここでは

- 局面を `Phase` の列挙で明示する
- 「今どの席の、どの選択を待っているか」を `Decision` として1つだけ持つ
- 選べる手は必ず `legal_actions` が返した集合の中から選ばせる

という形にして、待ち状態が宙に浮かないようにしている。

フィーバーモード（CLAUDE.md §4.5）は通常の手番進行とは別のループになるので、
`Phase.FEVER` として分けてある（実装はフェーズ6）。
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto

from . import score as scoring
from . import yaku_special
from .hand import Hand, Meld, MeldType, is_complete
from .shanten import is_tenpai, waits
from .tiles import (
    NUM_KINDS,
    PEI,
    SHA,
    TON,
    NAN,
    can_form_run,
    number_of,
    suit_of,
)
from .wall import NUM_PLAYERS, Wall, roll_dice, wareme_seat
from .yaku import HandValue, WinContext, evaluate

SEAT_WINDS = (TON, NAN, SHA)
RIICHI_COST = 1000
MAX_KANS = 4


class Phase(StrEnum):
    """局の進行状態。"""

    DRAW = auto()  # 手番の席がツモ牌を持っていて、何をするか選ぶ
    DISCARD = auto()  # 鳴いた直後など、ツモなしで打牌を選ぶ
    REACTION = auto()  # 他家の鳴き・ロンの確認
    FEVER = auto()  # フィーバーモード（全員強制ツモ切り / フェーズ6）
    FINISHED = auto()


class ActionType(StrEnum):
    DISCARD = auto()
    RIICHI = auto()  # 立直宣言 + 打牌
    OPEN_RIICHI = auto()  # オープン立直宣言 + 打牌（CLAUDE.md §4.2）
    TSUMO = auto()
    RON = auto()
    PON = auto()
    CHI = auto()
    MINKAN = auto()  # 大明槓
    KAKAN = auto()  # 加槓
    ANKAN = auto()  # 暗槓
    KITA = auto()  # 北抜き
    PASS = auto()


@dataclass(frozen=True, slots=True)
class Action:
    """打ち手が選ぶ1手。

    tile の意味は種類による:
      DISCARD/RIICHI → 切る牌 / PON・MINKAN・ANKAN → 対象の牌
      CHI → 順子の最小牌 / KAKAN → 加える牌
    """

    type: ActionType
    tile: int | None = None
    from_seat: int | None = None

    def __str__(self) -> str:
        from .tiles import tile_name

        label = self.type.value
        return f"{label}({tile_name(self.tile)})" if self.tile is not None else label


@dataclass
class PlayerState:
    """1人分の局中の状態。"""

    seat: int
    hand: Hand = field(default_factory=Hand)
    discards: list[int] = field(default_factory=list)
    score: int = scoring.START_SCORE
    riichi: bool = False
    double_riichi: bool = False
    open_riichi: bool = False
    ippatsu: bool = False
    riichi_discard_index: int | None = None
    furiten: bool = False
    """永続フリテン。自分の河に待ち牌があるか、リーチ後に見逃した。"""
    temporary_furiten: bool = False
    """同巡内フリテン。次の自分のツモで解消する。"""
    discards_were_called: bool = False
    """自分の捨て牌（抜いた北を含む）が一度でも鳴かれたか。流し満貫の判定に使う。"""
    drawn_tile: int | None = None
    """今ツモってきた牌。打牌するとクリアされる。"""

    @property
    def seat_wind(self) -> int:
        return SEAT_WINDS[self.seat]

    @property
    def is_menzen(self) -> bool:
        return self.hand.is_menzen


@dataclass
class Decision:
    """いま誰のどんな選択を待っているか。"""

    seat: int
    actions: list[Action]
    phase: Phase


@dataclass(frozen=True, slots=True)
class WinningHand:
    """和了したときの手牌（結果の表示用）。

    concealed は **和了牌を除いた** 手の内（昇順）。ツモでもロンでも同じ形にそろえるので、
    「この手にこの牌で上がった」と読める。点数の妥当性を人が確かめられるようにするためのもの。
    """

    concealed: list[int]
    win_tile: int
    is_tsumo: bool
    melds: list[Meld] = field(default_factory=list)
    kita: int = 0


@dataclass(frozen=True, slots=True)
class FeverWin:
    """フィーバー中に成立した和了1件。

    フィーバーリーチ中は和了牌が出るたびに和了が成立し、**すべて有効**になる
    （CLAUDE.md §4.5）。そのため1局に複数回の和了が積み上がる。

    和了が起きた時点でその1回ぶんを精算し、payments に持つ（画面で和了ごとの点数を
    出すため）。局の結果の payments は、これらを全部足したものになる。
    """

    win_tile: int
    is_tsumo: bool
    discarder: int | None
    value: HandValue
    payments: scoring.Payments = field(default_factory=scoring.Payments)
    hand: WinningHand | None = None


@dataclass
class RoundResult:
    """1局の結果。"""

    kind: str  # "win" / "draw" / "abort"
    payments: scoring.Payments = field(default_factory=scoring.Payments)
    winners: list[int] = field(default_factory=list)
    values: dict[int, HandValue] = field(default_factory=dict)
    tenpai: list[int] = field(default_factory=list)
    abort_reason: str | None = None
    dealer_kept: bool = False
    """親が連荘するか。"""
    fever_wins: list[FeverWin] = field(default_factory=list)
    """フィーバー中に積み上がった和了の内訳。"""
    ura_indicators: list[int] = field(default_factory=list)
    """裏ドラ表示牌（カン裏を含む）。立直者が和了したときだけ入る。"""
    hands: dict[int, WinningHand] = field(default_factory=dict)
    """和了者ごとの和了形。フィーバーの局では最後の和了のときの手（和了牌は fever_wins に）。"""


class Round:
    """1局を進める状態機械。

    使い方は `decision()` で待っている選択を取り、`apply()` で1手進める。
    `result` が埋まったら終局。
    """

    def __init__(
        self,
        dealer: int,
        scores: Sequence[int] | None = None,
        wall: Wall | None = None,
        rng: random.Random | None = None,
        riichi_sticks: int = 0,
        wareme: int | None = None,
    ) -> None:
        self.rng = rng or random.Random()
        self.dealer = dealer
        self.wall = wall or Wall(rng=self.rng)
        self.riichi_sticks = riichi_sticks

        dice = roll_dice(self.rng)
        self.wareme = wareme if wareme is not None else wareme_seat(dice, dealer)

        hands = self.wall.deal()
        start = list(scores) if scores else [scoring.START_SCORE] * NUM_PLAYERS
        self.players = [
            PlayerState(seat=seat, hand=Hand.from_counts(_to_counts(hands[seat])), score=start[seat])
            for seat in range(NUM_PLAYERS)
        ]

        self.turn = dealer
        self.phase = Phase.DRAW
        self.result: RoundResult | None = None
        self.last_discard: int | None = None
        self.last_discarder: int | None = None
        self.kan_count = 0
        self.minkan_responsible: int | None = None
        """大明槓の責任払い。嶺上開花で和了されたら全額払う席（CLAUDE.md §4.1）。"""
        self.is_rinshan = False
        self.is_chankan = False
        self._pending_kan_dora = 0
        """明槓（大明槓・加槓）で、まだめくっていないカンドラの数。打牌したらめくる。"""
        self.first_go_around = True
        self.any_call_made = False
        self._reaction_queue: list[int] = []
        self._reactions: dict[int, Action] = {}
        self._reaction_kita = False
        self._pending_kakan: int | None = None

        # --- フィーバーモード（CLAUDE.md §4.5）---
        self.fever_seat: int | None = None
        self.fever_yaku = None
        self.fever_waits: frozenset[int] = frozenset()
        self.fever_wins: list[FeverWin] = []
        self._pending_fever: int | None = None
        """立直宣言牌がロンされなかったらフィーバーに入る席。"""

        self._draw_for_turn()

    # --- 進行 --------------------------------------------------------------

    def decision(self) -> Decision | None:
        """いま待っている選択。None なら終局。"""
        if self.result is not None:
            return None
        if self.phase is Phase.REACTION:
            seat = self._reaction_queue[0]
            return Decision(seat, self._reaction_actions(seat), self.phase)
        return Decision(self.turn, self.legal_actions(self.turn), self.phase)

    def apply(self, action: Action) -> None:
        """1手進める。"""
        decision = self.decision()
        if decision is None:
            raise RuntimeError("局は既に終わっている")
        if action not in decision.actions:
            raise ValueError(f"選べない手: {action}（候補: {[str(a) for a in decision.actions]}）")

        if decision.phase is Phase.REACTION:
            self._apply_reaction(decision.seat, action)
        else:
            self._apply_turn(action)

    # --- 手番の選択肢 ------------------------------------------------------

    def legal_actions(self, seat: int) -> list[Action]:
        """手番の席が選べる手。"""
        actions: list[Action] = []

        if self.phase is Phase.FEVER:
            return self._fever_actions(seat)

        if self.phase is Phase.DRAW:
            if self._can_tsumo(seat):
                actions.append(Action(ActionType.TSUMO))
            actions.extend(self._kan_actions(seat))
            if self._can_draw_kita(seat):
                actions.append(Action(ActionType.KITA, PEI))

        actions.extend(self._discard_actions(seat))
        return actions

    def _discard_actions(self, seat: int) -> list[Action]:
        player = self.players[seat]
        forbidden = self._kuikae_forbidden(seat)

        if player.riichi:
            # 立直後はツモ切りのみ（暗槓は別途 legal_actions で扱う）
            tile = player.drawn_tile
            return [Action(ActionType.DISCARD, tile)] if tile is not None else []

        discardable = [
            tile
            for tile in range(NUM_KINDS)
            if player.hand.concealed[tile] and tile not in forbidden
        ]
        actions = [Action(ActionType.DISCARD, tile) for tile in discardable]

        if self._can_declare_riichi(seat):
            for tile in discardable:
                probe = player.hand.copy()
                probe.remove(tile)
                # 向聴数でテンパイでも、待ちが手の内で4枚使い切った牌だけなら和了牌がない
                if is_tenpai(probe) and waits(probe):
                    actions.append(Action(ActionType.RIICHI, tile))
                    actions.append(Action(ActionType.OPEN_RIICHI, tile))
        return actions

    def _can_draw_kita(self, seat: int) -> bool:
        """北抜きできるか。

        北は手牌に残して役牌として使ってもよいし、抜きドラにしてもよいし、
        普通に河へ捨ててもよい（打牌候補には常に入っている）。

        ただし **立直後は手牌を変えられない** ので、抜けるのは「今ツモってきた北」
        だけ。手の内に組み込んだ北を後から抜くと待ちが変わってしまう。
        """
        player = self.players[seat]
        if not player.hand.concealed[PEI] or not self.wall.can_draw_kita():
            return False
        if player.riichi and player.drawn_tile != PEI:
            return False
        return True

    def _can_declare_riichi(self, seat: int) -> bool:
        player = self.players[seat]
        return (
            not player.riichi
            and player.is_menzen
            and player.score >= RIICHI_COST
            and self.wall.remaining > 0
        )

    def _kuikae_forbidden(self, seat: int) -> set[int]:
        """喰い替えで切れない牌（ユーザー確定事項で禁止）。

        鳴いた直後のみ適用。現物と、チーの場合は筋も禁止する。
        """
        if self.phase is not Phase.DISCARD or not self.players[seat].hand.melds:
            return set()
        meld = self.players[seat].hand.melds[-1]
        if meld.called_tile is None:
            return set()
        return _kuikae_set(meld.type, meld.tile, meld.called_tile)

    def _call_leaves_a_discard(self, seat: int, action: Action) -> bool:
        """その鳴きをしたあとに切れる牌が残るか。

        喰い替えを禁止しているので、鳴くと打牌できなくなる形がありうる
        （例: 手牌 99s で 6s をチー → 現物の6sも筋の9sも切れない）。
        通常の麻雀と同じく、そうなる鳴きは認めない。
        """
        tile = self.last_discard
        remaining = list(self.players[seat].hand.concealed)
        if action.type is ActionType.PON:
            remaining[tile] -= 2
            meld_type, meld_tile = MeldType.PON, tile
        elif action.type is ActionType.CHI:
            for offset in range(3):
                used = action.tile + offset
                if used != tile:
                    remaining[used] -= 1
            meld_type, meld_tile = MeldType.CHI, action.tile
        else:
            return True  # 大明槓の後は嶺上牌をツモるので喰い替えの制限が無い
        forbidden = _kuikae_set(meld_type, meld_tile, tile)
        return any(
            count and index not in forbidden for index, count in enumerate(remaining)
        )

    def _kan_actions(self, seat: int) -> list[Action]:
        player = self.players[seat]
        if not self.wall.can_kan() or self.kan_count >= MAX_KANS:
            return []
        actions: list[Action] = []
        for tile in range(NUM_KINDS):
            if player.hand.concealed[tile] == 4:
                if player.riichi and not self._ankan_keeps_waits(seat, tile):
                    continue  # 立直後の暗槓は待ちが変わらない場合のみ
                actions.append(Action(ActionType.ANKAN, tile))
        if not player.riichi:
            for meld in player.hand.melds:
                if meld.type is MeldType.PON and player.hand.concealed[meld.tile]:
                    actions.append(Action(ActionType.KAKAN, meld.tile))
        return actions

    def _ankan_keeps_waits(self, seat: int, tile: int) -> bool:
        player = self.players[seat]
        before = set(waits(_hand_without_drawn(player)))
        probe = player.hand.copy()
        for _ in range(4):
            probe.remove(tile)
        probe.melds = [*probe.melds, Meld(MeldType.ANKAN, tile)]
        return set(waits(probe)) == before

    def _can_tsumo(self, seat: int) -> bool:
        player = self.players[seat]
        if not is_complete(player.hand):
            return False
        return self._build_value(seat, player.drawn_tile, is_tsumo=True).satisfies_binding

    # --- 手番の実行 --------------------------------------------------------

    def _apply_turn(self, action: Action) -> None:
        seat = self.turn

        match action.type:
            case ActionType.TSUMO:
                self._finish_win([seat], is_tsumo=True)
            case ActionType.ANKAN:
                self._do_ankan(seat, action.tile)
            case ActionType.KAKAN:
                self._do_kakan(seat, action.tile)
            case ActionType.KITA:
                self._do_kita(seat)
            case ActionType.DISCARD | ActionType.RIICHI | ActionType.OPEN_RIICHI:
                self._do_discard(seat, action)
            case _:
                raise ValueError(f"手番で選べない手: {action}")

    def _do_discard(self, seat: int, action: Action) -> None:
        player = self.players[seat]
        tile = action.tile
        declaring_riichi = action.type in (ActionType.RIICHI, ActionType.OPEN_RIICHI)

        player.hand.remove(tile)
        player.discards.append(tile)
        player.drawn_tile = None
        self.last_discard = tile
        self.last_discarder = seat
        # 明槓のカンドラは打牌後にめくる（ユーザー確定事項）
        self._reveal_pending_kan_dora()

        if declaring_riichi:
            player.riichi = True
            player.open_riichi = action.type is ActionType.OPEN_RIICHI
            player.double_riichi = self.first_go_around and not self.any_call_made
            player.ippatsu = True
            player.riichi_discard_index = len(player.discards) - 1
            player.score -= RIICHI_COST
            self.riichi_sticks += 1
            self._pending_fever = seat
        else:
            player.ippatsu = False

        self._refresh_furiten(seat)
        self.is_rinshan = False
        # 全員が1度打牌したら第1巡は終わり（ダブルリーチの条件）
        if all(p.discards for p in self.players):
            self.first_go_around = False

        if self.fever_seat is not None:
            # フィーバー中は鳴き・ロンの確認をしない。和了牌が出たら自動で和了。
            if seat != self.fever_seat and tile in self.fever_waits:
                self._record_fever_win(tile, is_tsumo=False, discarder=seat)
            self._fever_advance()
            return

        self._start_reactions(seat)

    def _do_ankan(self, seat: int, tile: int) -> None:
        player = self.players[seat]
        for _ in range(4):
            player.hand.remove(tile)
        player.hand.melds.append(Meld(MeldType.ANKAN, tile))
        self.kan_count += 1
        self._clear_ippatsu()
        if self._check_suukaikan():
            return
        # 先に明槓をしていて、まだめくっていないカンドラがあればそちらが先
        self._reveal_pending_kan_dora()
        # 暗槓は即めくり（ユーザー確定事項）
        self.wall.reveal_new_dora()
        self._draw_rinshan(seat)

    def _do_kakan(self, seat: int, tile: int) -> None:
        player = self.players[seat]
        player.hand.remove(tile)
        for index, meld in enumerate(player.hand.melds):
            if meld.type is MeldType.PON and meld.tile == tile:
                player.hand.melds[index] = Meld(
                    MeldType.KAKAN, tile, meld.called_from, meld.called_tile
                )
                break
        self.kan_count += 1
        self._clear_ippatsu()
        if self._check_suukaikan():
            return
        self._reveal_pending_kan_dora()  # 連続でカンした場合、前のカンのぶんを先にめくる
        # 加槓は槍槓の確認が先。ドラは打牌後にめくる（ユーザー確定事項）。
        self.is_chankan = True
        self._pending_kakan = seat
        self.last_discard = tile
        self.last_discarder = seat
        self._start_reactions(seat, chankan=True)

    def _do_kita(self, seat: int) -> None:
        player = self.players[seat]
        player.hand.remove(PEI)
        player.hand.kita += 1
        # 抜いた北は河に置かない。北を抜いてもフリテンにならない（CLAUDE.md §4.3）。
        self.last_discard = PEI
        self.last_discarder = seat
        if self.fever_seat is not None:
            self._after_kita_not_called()  # フィーバー中は他家が鳴けない
            return
        self._start_reactions(seat, from_kita=True)

    def _draw_rinshan(self, seat: int) -> None:
        player = self.players[seat]
        tile = self.wall.draw_rinshan_for_kan()
        player.hand.add(tile)
        player.drawn_tile = tile
        self.is_rinshan = True
        self.turn = seat
        if self.fever_seat is not None:
            if seat == self.fever_seat and tile in self.fever_waits:
                self._record_fever_win(tile, is_tsumo=True, discarder=None)
            self.phase = Phase.FEVER
            return
        self.phase = Phase.DRAW

    def _fever_advance(self) -> None:
        """フィーバー中の1手ぶんの進行。

        山が尽きるか和了牌が出尽くすまで、全員ツモ切りを続ける（CLAUDE.md §4.5）。
        """
        if self.wall.remaining == 0 or self._fever_tiles_exhausted():
            self._finish_fever()
            return
        self.turn = (self.last_discarder + 1) % NUM_PLAYERS
        player = self.players[self.turn]
        tile = self.wall.draw()
        player.hand.add(tile)
        player.drawn_tile = tile
        if self.turn == self.fever_seat and tile in self.fever_waits:
            self._record_fever_win(tile, is_tsumo=True, discarder=None)
        self.phase = Phase.FEVER

    def _draw_for_turn(self) -> None:
        if self.wall.remaining == 0:
            self._finish_draw()
            return
        player = self.players[self.turn]
        tile = self.wall.draw()
        player.hand.add(tile)
        player.drawn_tile = tile
        player.temporary_furiten = False  # 次の自摸で同巡内フリテンは解消
        self.phase = Phase.DRAW

    # --- 鳴き・ロンの確認 --------------------------------------------------

    def _start_reactions(self, from_seat: int, chankan: bool = False, from_kita: bool = False) -> None:
        self._reactions = {}
        self._reaction_queue = [
            (from_seat + offset) % NUM_PLAYERS for offset in range(1, NUM_PLAYERS)
        ]
        self._reaction_kita = from_kita
        self.phase = Phase.REACTION
        self._skip_empty_reactions()

    def _skip_empty_reactions(self) -> None:
        while self._reaction_queue:
            seat = self._reaction_queue[0]
            actions = self._reaction_actions(seat)
            if len(actions) > 1:
                return
            self._reactions[seat] = Action(ActionType.PASS)
            self._reaction_queue.pop(0)
        self._resolve_reactions()

    def _reaction_actions(self, seat: int) -> list[Action]:
        actions = [Action(ActionType.PASS)]
        tile = self.last_discard
        if tile is None:
            return actions

        if self._can_ron(seat, tile):
            actions.append(Action(ActionType.RON, tile, self.last_discarder))

        if self.is_chankan:
            return actions  # 槍槓はロンのみ

        player = self.players[seat]
        if player.riichi:
            return actions  # 立直後は鳴けない

        # 北抜きに対してはポン・カン・ロンが可能（CLAUDE.md §4.3）
        calls: list[Action] = []
        count = player.hand.concealed[tile]
        if count >= 2:
            calls.append(Action(ActionType.PON, tile, self.last_discarder))
        if count == 3 and self.wall.can_kan() and self.kan_count < MAX_KANS:
            calls.append(Action(ActionType.MINKAN, tile, self.last_discarder))
        if not self._reaction_kita and seat == (self.last_discarder + 1) % NUM_PLAYERS:
            calls.extend(self._chi_actions(seat, tile))

        # 鳴いた結果、喰い替え禁止で打牌できなくなる鳴きは認めない
        actions.extend(call for call in calls if self._call_leaves_a_discard(seat, call))
        return actions

    def _chi_actions(self, seat: int, tile: int) -> list[Action]:
        """チーの候補。三人打ちだがフィーバー三麻ではチー可能（CLAUDE.md §4.1）。"""
        player = self.players[seat]
        found: list[Action] = []
        for start in (tile - 2, tile - 1, tile):
            if not can_form_run(start):
                continue
            run = (start, start + 1, start + 2)
            if tile not in run or suit_of(start) != suit_of(tile):
                continue
            if all(player.hand.concealed[t] for t in run if t != tile):
                found.append(Action(ActionType.CHI, start, self.last_discarder))
        return found

    def _can_ron(self, seat: int, tile: int) -> bool:
        player = self.players[seat]
        if player.furiten or player.temporary_furiten:
            return False
        probe = player.hand.copy()
        probe.add(tile)
        if not is_complete(probe):
            return False
        return self._build_value(seat, tile, is_tsumo=False, extra_tile=tile).satisfies_binding

    def _apply_reaction(self, seat: int, action: Action) -> None:
        self._reactions[seat] = action
        self._reaction_queue.pop(0)
        if action.type is ActionType.PASS and self._can_ron(seat, self.last_discard):
            # 見逃しは同巡内フリテン。立直中は永続フリテンになる。
            player = self.players[seat]
            player.temporary_furiten = True
            if player.riichi:
                player.furiten = True
        self._skip_empty_reactions()

    def _resolve_reactions(self) -> None:
        rons = [seat for seat, act in self._reactions.items() if act.type is ActionType.RON]
        if rons:
            self._finish_win(rons, is_tsumo=False)
            return

        if self.is_chankan:
            # 槍槓されなかったので加槓が成立。ドラは打牌後にめくる。
            self.is_chankan = False
            seat = self._pending_kakan
            self._pending_kakan = None
            self._pending_kan_dora += 1
            self._draw_rinshan(seat)
            return

        calls = [
            (seat, act)
            for seat, act in self._reactions.items()
            if act.type in (ActionType.MINKAN, ActionType.PON, ActionType.CHI)
        ]
        if calls:
            priority = {ActionType.MINKAN: 0, ActionType.PON: 0, ActionType.CHI: 1}
            seat, action = min(calls, key=lambda pair: priority[pair[1].type])
            self._do_call(seat, action)
            return

        # 北抜きはポン・カンの確認を済ませてから、鳴かれなかった場合だけ嶺上牌をツモる
        if self._reaction_kita:
            self._after_kita_not_called()
            return

        if self._pending_fever is not None:
            seat = self._pending_fever
            self._pending_fever = None
            if self._try_enter_fever(seat):
                self._fever_advance()
                return

        self._advance_turn()

    def _after_kita_not_called(self) -> None:
        """北抜きが鳴かれなかった場合、抜いた本人が嶺上牌をツモる。"""
        seat = self.last_discarder
        tile = self.wall.draw_rinshan_for_kita()
        player = self.players[seat]
        player.hand.add(tile)
        player.drawn_tile = tile
        # 抜きドラで引いた嶺上牌では嶺上開花にならない（CLAUDE.md §4.3）
        self.is_rinshan = False
        self.turn = seat
        if self.fever_seat is not None:
            if seat == self.fever_seat and tile in self.fever_waits:
                self._record_fever_win(tile, is_tsumo=True, discarder=None)
            self.phase = Phase.FEVER
            return
        self.phase = Phase.DRAW

    def _do_call(self, seat: int, action: Action) -> None:
        player = self.players[seat]
        discarder = self.last_discarder
        tile = self.last_discard
        self.players[discarder].discards_were_called = True
        self.any_call_made = True
        self._clear_ippatsu()

        if self._reaction_kita:
            # 鳴かれた北は抜きドラでなくなるので、抜いた本人の枚数から戻す
            self.players[discarder].hand.kita -= 1
        elif self.players[discarder].discards and self.players[discarder].discards[-1] == tile:
            self.players[discarder].discards.pop()

        match action.type:
            case ActionType.PON:
                for _ in range(2):
                    player.hand.remove(tile)
                player.hand.melds.append(Meld(MeldType.PON, tile, discarder, tile))
            case ActionType.CHI:
                for offset in range(3):
                    if action.tile + offset != tile:
                        player.hand.remove(action.tile + offset)
                player.hand.melds.append(Meld(MeldType.CHI, action.tile, discarder, tile))
            case ActionType.MINKAN:
                for _ in range(3):
                    player.hand.remove(tile)
                player.hand.melds.append(Meld(MeldType.MINKAN, tile, discarder, tile))
                self.kan_count += 1
                self.minkan_responsible = discarder
                if self._check_suukaikan():
                    return
                self._reveal_pending_kan_dora()
                # 大明槓のカンドラは打牌後にめくる（ユーザー確定事項）
                self._pending_kan_dora += 1
                self._draw_rinshan(seat)
                return

        self.turn = seat
        self.phase = Phase.DISCARD
        self.first_go_around = False

    def _revealed_ura(self, winners: list[int]) -> list[int]:
        """和了者に立直者がいれば裏ドラ表示牌を返す（いなければめくらないので空）。"""
        if any(self.players[seat].riichi for seat in winners):
            return list(self.wall.ura_indicators())
        return []

    def _reveal_pending_kan_dora(self) -> None:
        """めくり待ちのカンドラをすべてめくる。"""
        while self._pending_kan_dora:
            self.wall.reveal_new_dora()
            self._pending_kan_dora -= 1

    def _advance_turn(self) -> None:
        if self.wall.remaining == 0:
            self._finish_draw()
            return
        self.turn = (self.last_discarder + 1) % NUM_PLAYERS
        self.minkan_responsible = None
        self._draw_for_turn()

    # --- フィーバーモード --------------------------------------------------

    def _try_enter_fever(self, seat: int) -> bool:
        """立直がフィーバー立直だったらフィーバーモードに入る（CLAUDE.md §4.5）。"""
        player = self.players[seat]
        hand = _hand_without_drawn(player)
        yaku = yaku_special.fever_yaku(
            hand,
            self._visible_counts(seat),
            is_menzen=player.is_menzen,
            is_furiten=player.furiten,
        )
        if yaku is None:
            return False
        self.fever_seat = seat
        self.fever_yaku = yaku
        self.fever_waits = frozenset(waits(hand))
        self.phase = Phase.FEVER
        return True

    def _visible_counts(self, seat: int) -> list[int]:
        """その席から見えている枚数配列。純カラ判定に使う。"""
        meld_tiles: list[int] = []
        for other, player in enumerate(self.players):
            if other == seat:
                continue
            for meld in player.hand.melds:
                meld_tiles.extend(meld.tiles)
        return yaku_special.visible_counts(
            self.players[seat].hand,
            discards=[p.discards for p in self.players],
            melds_tiles=meld_tiles,
            dora_indicators=self.wall.dora_indicators(),
        )

    def _fever_actions(self, seat: int) -> list[Action]:
        """フィーバー中に選べる手。

        リーチ者以外は **強制ツモ切り**（鳴き・和了は一切不可）。
        リーチ者はカン（和了牌が変わらない場合のみ）と北抜きができる。
        """
        player = self.players[seat]
        if player.drawn_tile is None:
            return []
        actions: list[Action] = []
        if seat == self.fever_seat:
            actions.extend(self._kan_actions(seat))
            if self._can_draw_kita(seat):
                actions.append(Action(ActionType.KITA, PEI))
        actions.append(Action(ActionType.DISCARD, player.drawn_tile))
        return actions

    def _fever_seen(self) -> list[int]:
        counts = [0] * NUM_KINDS
        for player in self.players:
            for tile in player.hand.all_tiles():
                counts[tile] += 1
            counts[PEI] += player.hand.kita
            for tile in player.discards:
                counts[tile] += 1
        for tile in self.wall.dora_indicators():
            counts[tile] += 1
        return counts

    def _fever_tiles_exhausted(self) -> bool:
        """和了牌が全て出尽くしたか。

        出尽くすか山が尽きるまでツモ切りを続ける（CLAUDE.md §4.5）。
        """
        seen = self._fever_seen()
        return all(seen[tile] >= 4 for tile in self.fever_waits)

    def _record_fever_win(self, win_tile: int, is_tsumo: bool, discarder: int | None) -> None:
        """フィーバー中の和了を1件積み、その場で精算する。和了牌が残る限り局は続く。

        供託は最初の和了で受け取る。
        """
        seat = self.fever_seat
        value = self._build_value(
            seat,
            win_tile,
            is_tsumo=is_tsumo,
            extra_tile=None if is_tsumo else win_tile,
        )
        payments = scoring.settle_win(
            value,
            winner=seat,
            dealer=self.dealer,
            is_tsumo=is_tsumo,
            discarder=discarder,
            wareme=self.wareme,
            riichi_sticks=self.riichi_sticks,
        ).merge(scoring.yakuman_bonus(value, seat, is_tsumo, discarder))
        self.riichi_sticks = 0
        self._apply_payments(payments)
        hand = self._winning_hand(seat, win_tile, is_tsumo)
        self.fever_wins.append(FeverWin(win_tile, is_tsumo, discarder, value, payments, hand))

    def _finish_fever(self) -> None:
        """フィーバー終了。積み上がった和了の合計を局の結果にする。"""
        seat = self.fever_seat
        if not self.fever_wins:
            # 一度も和了せず流局 → フィーバー者はテンパイ、他家は強制ノーテン
            payments = scoring.settle_noten([seat])
            self._apply_payments(payments)
            self.result = RoundResult(
                kind="draw",
                payments=payments,
                tenpai=[seat],
                dealer_kept=self.dealer == seat,
            )
            self.phase = Phase.FINISHED
            return

        # 和了ごとの精算は _record_fever_win で済んでいる。ここでは合計をまとめるだけ。
        payments = scoring.Payments()
        for win in self.fever_wins:
            payments = payments.merge(win.payments)
        self.result = RoundResult(
            kind="win",
            payments=payments,
            winners=[seat],
            values={seat: self.fever_wins[-1].value},
            dealer_kept=self.dealer == seat,
            fever_wins=list(self.fever_wins),
            ura_indicators=self._revealed_ura([seat]),
            hands={seat: self.fever_wins[-1].hand},
        )
        self.phase = Phase.FINISHED

    # --- 終局 --------------------------------------------------------------

    def _check_suukaikan(self) -> bool:
        """四槓散了。1人で4槓なら四槓子なので流さない。"""
        if self.kan_count < MAX_KANS:
            return False
        kan_owners = {
            seat for seat, p in enumerate(self.players) if p.hand.kan_count > 0
        }
        if len(kan_owners) <= 1:
            return False
        self._finish_abort("四槓散了")
        return True

    def _build_value(
        self, seat: int, win_tile: int | None, is_tsumo: bool, extra_tile: int | None = None
    ) -> HandValue:
        player = self.players[seat]
        hand = player.hand.copy()
        if extra_tile is not None:
            hand.add(extra_tile)
        if win_tile is None:
            return HandValue()
        extra = yaku_special.extra_yaku_for_win(
            hand, fever=self.fever_yaku if seat == self.fever_seat else None
        )
        ctx = WinContext(
            hand=hand,
            win_tile=win_tile,
            is_tsumo=is_tsumo,
            seat_wind=player.seat_wind,
            is_riichi=player.riichi,
            is_double_riichi=player.double_riichi,
            is_open_riichi=player.open_riichi,
            discarder_was_riichi=(
                not is_tsumo
                and self.last_discarder is not None
                and self.players[self.last_discarder].riichi
            ),
            is_ippatsu=player.ippatsu,
            is_rinshan=self.is_rinshan and is_tsumo,
            is_chankan=self.is_chankan and not is_tsumo,
            is_haitei=is_tsumo and self.wall.remaining == 0,
            is_houtei=not is_tsumo and self.wall.remaining == 0,
            dora_indicators=tuple(self.wall.dora_indicators()),
            ura_indicators=tuple(self.wall.ura_indicators()),
            extra_yaku=extra,
            dora_multiplier=yaku_special.dora_multiplier(hand),
        )
        return evaluate(ctx)

    def _winning_hand(self, seat: int, win_tile: int, is_tsumo: bool) -> WinningHand:
        """和了形を表示用に写し取る。ツモなら手の内から和了牌を1枚抜いておく。"""
        hand = self.players[seat].hand
        counts = list(hand.concealed)
        if is_tsumo and counts[win_tile]:
            counts[win_tile] -= 1
        concealed = [tile for tile in range(NUM_KINDS) for _ in range(counts[tile])]
        return WinningHand(concealed, win_tile, is_tsumo, list(hand.melds), hand.kita)

    def _finish_win(self, winners: list[int], is_tsumo: bool) -> None:
        payments = scoring.Payments()
        values: dict[int, HandValue] = {}
        hands: dict[int, WinningHand] = {}
        sticks = self.riichi_sticks

        for index, seat in enumerate(sorted(winners, key=lambda s: (s - (self.last_discarder or 0)) % NUM_PLAYERS)):
            win_tile = self.players[seat].drawn_tile if is_tsumo else self.last_discard
            value = self._build_value(
                seat,
                win_tile,
                is_tsumo=is_tsumo,
                extra_tile=None if is_tsumo else self.last_discard,
            )
            values[seat] = value
            hands[seat] = self._winning_hand(seat, win_tile, is_tsumo)
            discarder = None if is_tsumo else self.last_discarder
            # 大明槓の責任払い: 嶺上開花で和了されたらカン牌を出した者が全額払う
            if is_tsumo and self.is_rinshan and self.minkan_responsible is not None:
                discarder = self.minkan_responsible
                settled = scoring.settle_win(
                    value,
                    winner=seat,
                    dealer=self.dealer,
                    is_tsumo=False,
                    discarder=discarder,
                    wareme=self.wareme,
                    riichi_sticks=sticks if index == 0 else 0,
                )
            else:
                settled = scoring.settle_win(
                    value,
                    winner=seat,
                    dealer=self.dealer,
                    is_tsumo=is_tsumo,
                    discarder=discarder,
                    wareme=self.wareme,
                    riichi_sticks=sticks if index == 0 else 0,
                )
            payments = payments.merge(settled)
            payments = payments.merge(
                scoring.yakuman_bonus(value, seat, is_tsumo, discarder)
            )

        self.riichi_sticks = 0
        self._apply_payments(payments)
        self.result = RoundResult(
            kind="win",
            payments=payments,
            winners=list(winners),
            values=values,
            dealer_kept=self.dealer in winners,
            ura_indicators=self._revealed_ura(winners),
            hands=hands,
        )
        self.phase = Phase.FINISHED

    def _nagashi_seats(self) -> list[int]:
        """流し満貫が成立している席（CLAUDE.md §4.6）。"""
        return [
            seat
            for seat, player in enumerate(self.players)
            if yaku_special.is_nagashi_mangan(player.discards, player.discards_were_called)
        ]

    def _finish_nagashi(self, seats: list[int]) -> None:
        """流し満貫での終局。5翻役として**ツモ和了**が成立する。"""
        payments = scoring.Payments()
        values: dict[int, HandValue] = {}
        for index, seat in enumerate(seats):
            player = self.players[seat]
            value = yaku_special.nagashi_value(
                player.discards, player.hand.kita, self.wall.dora_indicators()
            )
            values[seat] = value
            payments = payments.merge(
                scoring.settle_win(
                    value,
                    winner=seat,
                    dealer=self.dealer,
                    is_tsumo=True,
                    wareme=self.wareme,
                    riichi_sticks=self.riichi_sticks if index == 0 else 0,
                )
            )
        self.riichi_sticks = 0
        self._apply_payments(payments)
        self.result = RoundResult(
            kind="win",
            payments=payments,
            winners=list(seats),
            values=values,
            dealer_kept=self.dealer in seats,
        )
        self.phase = Phase.FINISHED

    def _finish_draw(self) -> None:
        nagashi = self._nagashi_seats()
        if nagashi:
            self._finish_nagashi(nagashi)
            return
        tenpai = [seat for seat, p in enumerate(self.players) if is_tenpai(p.hand)]
        payments = scoring.settle_noten(tenpai)
        self._apply_payments(payments)
        self.result = RoundResult(
            kind="draw",
            payments=payments,
            tenpai=tenpai,
            dealer_kept=self.dealer in tenpai,  # 親テンパイなら連荘（CLAUDE.md §4.10）
        )
        self.phase = Phase.FINISHED

    def _finish_abort(self, reason: str) -> None:
        self.result = RoundResult(kind="abort", abort_reason=reason, dealer_kept=True)
        self.phase = Phase.FINISHED

    def _apply_payments(self, payments: scoring.Payments) -> None:
        for seat, delta in payments.deltas.items():
            self.players[seat].score += delta

    # --- 補助 --------------------------------------------------------------

    def _clear_ippatsu(self) -> None:
        for player in self.players:
            player.ippatsu = False

    def _refresh_furiten(self, seat: int) -> None:
        player = self.players[seat]
        player.temporary_furiten = False
        own_waits = set(waits(_hand_without_drawn(player)))
        if own_waits & set(player.discards):
            player.furiten = True

    @property
    def scores(self) -> list[int]:
        return [player.score for player in self.players]


def _kuikae_set(meld_type: MeldType, meld_tile: int, called_tile: int) -> set[int]:
    """鳴いた直後に切れなくなる牌。

    現物（鳴いた牌そのもの）は常に禁止。チーは筋も禁止する
    （123 を 1 で鳴いたら 4 も切れない）。
    """
    forbidden = {called_tile}
    if meld_type is MeldType.CHI:
        low, high = meld_tile, meld_tile + 2
        if called_tile == low and number_of(high) < 9:
            forbidden.add(high + 1)
        elif called_tile == high and number_of(low) > 1:
            forbidden.add(low - 1)
    return forbidden


def _hand_without_drawn(player: PlayerState) -> Hand:
    """ツモ牌を除いた13枚相当の手牌。待ちの計算に使う。"""
    hand = player.hand.copy()
    if player.drawn_tile is not None and hand.concealed[player.drawn_tile]:
        hand.remove(player.drawn_tile)
    return hand


def _to_counts(tiles: Sequence[int]) -> list[int]:
    counts = [0] * NUM_KINDS
    for tile in tiles:
        counts[tile] += 1
    return counts
