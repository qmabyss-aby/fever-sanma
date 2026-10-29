"""ランダム打ちの CPU（ベースライン）。

ユーザー確定事項として、まずはこれで局進行とルールを検証する。強くする場合は
`choose` を差し替えるだけでよいので、ここには戦略を書かない。

ただし完全な一様選択だと和了できる場面で和了しないためテストの意味が薄れるので、
**和了だけは必ず取る**。それ以外（鳴くか、リーチするか、何を切るか）は一様乱数。
"""

from __future__ import annotations

import random

from ..core.game import Action, ActionType, Round

ALWAYS_TAKE = (ActionType.TSUMO, ActionType.RON)


class RandomAgent:
    """合法手から一様に選ぶ打ち手。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def choose(self, game: Round, seat: int, options: list[Action]) -> Action:
        for action in options:
            if action.type in ALWAYS_TAKE:
                return action
        return self.rng.choice(options)
