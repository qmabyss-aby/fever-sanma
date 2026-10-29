"""東風戦1回ぶんの進行（局をまたぐ処理）。

局の中身は `game.Round` が持つ。ここが受け持つのは局と局のあいだ:

- 親の移動と連荘（CLAUDE.md §4.10 のオーラス終局判定）
- 飛びによる終局と飛び賞（§4.8）
- 順位点・オカによる最終得点（§4.8）

**積み棒は増えない**（§4.1）ので本場は持たない。供託だけが次局に持ち越される。
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import hidden
from .game import Action, Round, RoundResult
from .tiles import build_full_set
from .wall import Wall
from .score import (
    NUM_PLAYERS,
    START_SCORE,
    Payments,
    final_scores,
    is_bust,
    tobi_bonus,
)

LAST_ROUND = 3
"""東風戦なので東3局がオーラス。"""

MAX_ROUNDS = 100
"""連荘が続いても止まるようにする安全弁。"""

MAX_STEPS_PER_ROUND = 1000


@dataclass
class MatchResult:
    """半荘（ここでは東風戦）1回の結果。"""

    scores: list[int]
    final: list[int]
    rounds: list[RoundResult] = field(default_factory=list)
    ended_by: str = "east3"
    """"east3"（オーラス終了）か "tobi"（飛び）か "limit"（安全弁）。"""

    @property
    def ranking(self) -> list[int]:
        """1位から順の席番号。"""
        return sorted(range(len(self.final)), key=lambda s: (-self.final[s], s))


class Agent:
    """型ヒント用のプレースホルダ。実体は players パッケージ側。"""

    def choose(self, game: Round, seat: int, options: list[Action]) -> Action:  # pragma: no cover
        raise NotImplementedError


def drive_round(game: Round, agents: Sequence[Agent]) -> RoundResult:
    """1局を最後まで進める。

    状態機械が必ず「次に誰が何を選ぶか」を返すので、それを打ち手に渡すだけでよい。
    手数の上限を設けているのは、万一状態が進まなくなったときに無限ループではなく
    例外で気づけるようにするため。
    """
    for _ in range(MAX_STEPS_PER_ROUND):
        decision = game.decision()
        if decision is None:
            return game.result
        if not decision.actions:
            raise RuntimeError(f"選べる手が無い状態で止まった: seat={decision.seat} {decision.phase}")
        game.apply(agents[decision.seat].choose(game, decision.seat, decision.actions))
    raise RuntimeError("局が終わらなかった（デッドロックの疑い）")


class Match:
    """東風戦1回。"""

    def __init__(
        self,
        agents: Sequence[Agent],
        rng: random.Random | None = None,
        start_scores: Sequence[int] | None = None,
        on_round_end: Callable[[Round, RoundResult], None] | None = None,
    ) -> None:
        self.agents = list(agents)
        self.rng = rng or random.Random()
        self.scores = list(start_scores) if start_scores else [START_SCORE] * NUM_PLAYERS
        self.riichi_sticks = 0
        self.on_round_end = on_round_end
        """局が終わるたびに呼ばれる。表示のためのフックで、core 自体は何も出力しない。"""

        self.round_number = 1
        """東何局か（1〜3）。連荘しても増えない。"""
        self.dealer = 0
        self.results: list[RoundResult] = []
        self.result: MatchResult | None = None
        """終局したら埋まる。"""
        self.hidden_requests: dict[int, list[str]] = {}
        """次の配牌で効かせる隠しコマンド（席 → コマンド名）。配ったら消える。"""

    def play(self) -> MatchResult:
        """最後まで一気に進める（CUI・全CPU検証用）。"""
        while self.result is None:
            game = self.start_round()
            self.end_round(game, drive_round(game, self.agents))
        return self.result

    # --- 1局ずつ進める API -------------------------------------------------
    # GUI はイベントループを止められないので、`play()` のように局を回し切れない。
    # `start_round()` で局を受け取り、`Round.decision()/apply()` を自分のペースで
    # 進め、局が終わったら `end_round()` を呼ぶ。

    def start_round(self) -> Round:
        """次の局を作る。隠しコマンドが入っていれば配牌に仕込む。"""
        if self.result is not None:
            raise RuntimeError("東風戦は既に終わっている")
        return Round(
            dealer=self.dealer,
            scores=self.scores,
            rng=self.rng,
            riichi_sticks=self.riichi_sticks,
            wall=self._next_wall(),
        )

    def request_hidden(self, seat: int, command: str) -> bool:
        """隠しコマンドを受け付ける。**次の配牌**で効く。知らないコマンドなら False。"""
        if command not in hidden.COMMANDS:
            return False
        requests = self.hidden_requests.setdefault(seat, [])
        if command not in requests:
            requests.append(command)
        return True

    def _next_wall(self) -> Wall | None:
        if not self.hidden_requests:
            return None  # いつもどおり Round に山を作らせる
        tiles = build_full_set()
        self.rng.shuffle(tiles)
        for seat, commands in self.hidden_requests.items():
            tiles = hidden.rig_deal(tiles, seat, hidden.guaranteed_tiles(commands, self.rng))
        self.hidden_requests = {}  # 1回入力すると1回だけ効く
        return Wall(tiles=tiles)

    def end_round(self, game: Round, result: RoundResult) -> MatchResult | None:
        """終わった局を反映し、連荘・親の移動・終局を判定する。終局なら結果を返す。"""
        self.results.append(result)
        self.scores = game.scores
        self.riichi_sticks = game.riichi_sticks
        if self.on_round_end is not None:
            self.on_round_end(game, result)

        busted = [seat for seat in range(NUM_PLAYERS) if is_bust(self.scores[seat])]
        if busted:
            self._apply_tobi(busted, result)
            return self._set_result("tobi")

        is_last = self.round_number >= LAST_ROUND
        if self._dealer_keeps(result, self.dealer, is_last):
            # 連荘。局番号も親も動かさない。
            if len(self.results) >= MAX_ROUNDS:
                return self._set_result("limit")
            return None
        if is_last:
            return self._set_result("east3")
        self.round_number += 1
        self.dealer = self.round_number - 1
        return None

    def _set_result(self, ended_by: str) -> MatchResult:
        self.result = self._finish(self.results, ended_by)
        return self.result

    # --- 局間の判定 --------------------------------------------------------

    def _dealer_keeps(self, result: RoundResult, dealer: int, is_last: bool) -> bool:
        """親が連荘するか（CLAUDE.md §4.10）。"""
        if result.kind == "abort":
            return True  # 途中流局は積み棒も増えずそのまま親継続
        if result.kind == "draw":
            # 流局は親テンパイなら順位にかかわらず連荘、ノーテンなら終局
            return dealer in result.tenpai
        if dealer not in result.winners:
            return False  # 子が和了 → 親が流れる（オーラスなら終局）
        if is_last and self._is_top(dealer):
            return False  # オーラスで親がトップなら終局（上がり止めではなく強制）
        return True

    def _is_top(self, seat: int) -> bool:
        best = max(self.scores)
        if self.scores[seat] != best:
            return False
        # 同点は席順（起家に近い順）で上位
        return all(self.scores[other] != best for other in range(seat))

    def _apply_tobi(self, busted: list[int], result: RoundResult) -> None:
        """飛び賞（CLAUDE.md §4.8）。

        ノーテン罰符で飛んだ場合は賞もペナルティもなく、終局するだけ。
        """
        if result.kind != "win" or not result.winners:
            return
        payments = tobi_bonus(busted, result.winners)
        self._apply(payments)

    def _apply(self, payments: Payments) -> None:
        for seat, delta in payments.deltas.items():
            self.scores[seat] += delta

    def _finish(self, results: list[RoundResult], ended_by: str) -> MatchResult:
        # 残った供託はトップの取り分にする
        if self.riichi_sticks:
            top = max(range(NUM_PLAYERS), key=lambda s: (self.scores[s], -s))
            self.scores[top] += self.riichi_sticks * 1000
            self.riichi_sticks = 0
        return MatchResult(
            scores=list(self.scores),
            final=final_scores(self.scores),
            rounds=results,
            ended_by=ended_by,
        )
