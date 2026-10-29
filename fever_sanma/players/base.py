"""打ち手のインターフェース。

ルールエンジンは「今この席が選べる手」を必ず列挙してから渡すので、打ち手は
その中から1つ選ぶだけでよい。非合法手を考えなくて済むので、CPU も人間 UI も
同じ形で書ける。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.game import Action, Round


@runtime_checkable
class Agent(Protocol):
    """1つの席を担当する打ち手。"""

    def choose(self, game: Round, seat: int, options: list[Action]) -> Action:
        """options の中から1手選ぶ。"""
        ...
