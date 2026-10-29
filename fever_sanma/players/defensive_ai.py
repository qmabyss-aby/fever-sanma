"""守備型の CPU。

`StrongAgent` を土台に、押し引きを「放銃しないこと」優先に差し替えている。

- **立直を受けたら、テンパイしていなければ必ずオリる**（強い CPU は1向聴なら押す）。
- 警戒する相手を広げる: 立直者に加えて **2副露以上の相手**（鳴きが進むと脊髄＝13翻が近い）。
  さらに **局の終盤（山が残り20枚以下）は全員を警戒** し、テンパイでなければ安全な牌を切る。
- **立直を受けたら、テンパイでも危険な牌は切らない**。テンパイを崩しても安全な牌を選ぶ。
- テンパイでも、危ない相手がいれば **立直せずダマ**にする。立直すると手が固定されて
  オリられなくなる。ダマで上がれなくても、流局時のノーテン罰符は避けられる。
- 同じ向聴数なら、有効牌より **安全さを優先** して切る牌を選ぶ。
- 鳴くのは、その鳴きでテンパイになるときだけ（手牌が減ると守りにくい）。
- カンはしない（他家にカンドラが乗る）。危ない相手がいるときは北抜きも控える
  （抜いた北はロンされうる）。8索のカン（ベンツ）だけは、危ない相手がいなければする。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.game import Action, ActionType, Round
from ..core.tiles import PEI
from .strong_ai import (
    BENZ_TILE,
    StrongAgent,
    _after_call,
    _best_discard_shanten,
    _first,
    visible_counts,
)

WATCH_MELDS = 2
"""この数以上鳴いている相手は、立直していなくても警戒する。"""

LATE_REMAINING = 20
"""山がこれ以下になったら、全員を警戒する。"""

DANGER_WEIGHT = 8
"""危険度1と比べた、有効牌1枚の重み。同じ向聴数なら安全な牌を選ぶ。"""

DANGEROUS = 4
"""立直者に対してこの危険度以上の牌は、テンパイを崩してでも切らない。"""

DANGEROUS_PENALTY = 2
"""危険な牌を切る打牌に足す向聴数。テンパイ維持（0）より、安全に崩す（1）を選ばせる。"""


class DefensiveAgent(StrongAgent):
    """放銃しないことを最優先にする CPU。"""

    # --- 警戒・押し引き ----------------------------------------------------

    def _threats(self, game: Round, seat: int) -> list[int]:
        late = game.wall.remaining <= LATE_REMAINING
        return [
            other
            for other, player in enumerate(game.players)
            if other != seat
            and (player.riichi or late or player.hand.open_meld_count >= WATCH_MELDS)
        ]

    def _should_fold(
        self, game: Round, seat: int, threats: list[int], best_shanten: int
    ) -> bool:
        # 危ない相手がいるなら、テンパイしていない限りオリる
        return bool(threats) and best_shanten >= 1

    def _discard_score(
        self, game: Round, seat: int, tile: int, visible: Sequence[int]
    ) -> tuple[int, int, int]:
        """同じ向聴数なら安全な牌を選べるよう、有効牌から危険度を差し引く。"""
        current, ukeire, keep = super()._discard_score(game, seat, tile, visible)
        danger = self._danger(game, seat, tile, self._threats(game, seat), visible)
        riichi = [o for o, p in enumerate(game.players) if o != seat and p.riichi]
        if riichi and self._danger(game, seat, tile, riichi, visible) >= DANGEROUS:
            current += DANGEROUS_PENALTY  # 立直者への危険牌は、テンパイでも切らない
        return current, ukeire - DANGER_WEIGHT * danger, keep

    def _riichi_action(
        self, game: Round, seat: int, options: list[Action], tile: int
    ) -> Action | None:
        if self._threats(game, seat):
            return None  # 立直すると手が固定されてオリられない。ダマで構える
        return super()._riichi_action(game, seat, options, tile)

    # --- 手番 --------------------------------------------------------------

    def _turn(self, game: Round, seat: int, options: list[Action]) -> Action:
        threats = self._threats(game, seat)
        visible = visible_counts(game, seat)
        filtered = []
        for action in options:
            if action.type in (ActionType.ANKAN, ActionType.KAKAN):
                if action.tile != BENZ_TILE or threats:
                    continue  # カンは他家にカンドラを乗せる。ベンツだけは安全なときにする
            if action.type is ActionType.KITA and threats:
                if self._danger(game, seat, PEI, threats, visible) > 0:
                    continue  # 抜いた北はロンされうる
            filtered.append(action)
        return super()._turn(game, seat, filtered or options)

    # --- 鳴き --------------------------------------------------------------

    def _react(self, game: Round, seat: int, options: list[Action]) -> Action:
        pass_action = _first(options, ActionType.PASS) or options[0]
        for action in options:
            if action.type is ActionType.RON:
                return action
        player = game.players[seat]
        if player.riichi or self._threats(game, seat):
            return pass_action
        tile = game.last_discard
        for action in options:
            if action.type not in (ActionType.PON, ActionType.CHI):
                continue
            after = _after_call(player.hand, action, tile)
            # 鳴くのはテンパイになるときだけ。役が無ければエンジンが和了を出さないので、
            # 役牌のポンか、すでに鳴いている手（脊髄・役牌）に限る。
            if _best_discard_shanten(after, forbidden={tile}) != 0:
                continue
            if player.hand.open_meld_count or self._worth_opening(
                game, seat, action, tile, before=0
            ):
                return action
        return pass_action
