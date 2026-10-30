"""普通の CPU（2026-10 の改良より前の「強いCPU」）。

`StrongAgent` と違うのは最初の鳴きの基準だけ。手が遠ければ鳴き始めて脊髄
（4副露の裸単騎で13翻）を狙い、役牌なら1つでもポンする。二翻縛りのせいで鳴いた手は
上がれないことが多く、総当たりでは最強CPU（`StrongAgent`）に大きく負け越す。
"""

from __future__ import annotations

from ..core.game import Action, ActionType, Round
from ..core.tiles import NUM_KINDS, is_honor, suit_of
from ..core.yaku import yakuhai_han
from .strong_ai import StrongAgent

FAR_SHANTEN = 3
"""門前でこれ以上遠ければ、最初の鳴きを入れて脊髄を狙う。"""


class NormalAgent(StrongAgent):
    """鳴きの基準がゆるい `StrongAgent`。"""

    def _worth_opening(
        self, game: Round, seat: int, action: Action, tile: int, before: int
    ) -> bool:
        """鳴いても上がりの見込み（役）が残るか。"""
        player = game.players[seat]
        hand = player.hand
        if hand.open_meld_count:
            return True  # すでに鳴いている → 脊髄（4副露の裸単騎で13翻）まで鳴き進める
        if action.type is ActionType.PON and yakuhai_han(tile, player.seat_wind):
            return True
        if before >= FAR_SHANTEN:
            return True  # 門前では遠すぎる。鳴いて脊髄を狙うほうが速い
        tiles = [t for t in range(NUM_KINDS) for _ in range(hand.concealed[t])]
        honors = sum(1 for t in tiles if is_honor(t))
        by_suit: dict[str, int] = {}
        for t in tiles:
            if not is_honor(t):
                by_suit[suit_of(t)] = by_suit.get(suit_of(t), 0) + 1
        if honors + max(by_suit.values(), default=0) >= 10:
            return True  # 混一色・清一色に寄っている
        if action.type is ActionType.PON:
            groups = sum(1 for t in range(NUM_KINDS) if hand.concealed[t] >= 2)
            if groups >= 4:
                return True  # 対々和に寄っている
        return False
