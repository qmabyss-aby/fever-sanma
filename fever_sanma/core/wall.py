"""山・王牌・ドラ表示牌。

CLAUDE.md §4.1 の通り、王牌は **18枚**。内訳は次のように割り当てる:

    嶺上牌   8枚  = カン最大4回 + 北抜き最大4回（北は全部で4枚しかない）
    ドラ表示 10枚 = (表・裏) の5組 = 開局時1組 + カン最大4回

- **槓**: 嶺上牌を1枚ツモり、山牌の末尾（山尾）から1枚を王牌に補充する。
  → 王牌は18枚のまま。
- **北抜き**: 嶺上牌を1枚ツモるが **補充しない**。
  → 王牌が1枚ずつ減る。北は4枚なので王牌は最小14枚まで痩せる。

ドラは開局時に表・裏を1組めくる。カン1回につき表・裏を1組ずつ追加でめくる
（Wiki 未記載。「場にカンがある場合は裏ドラも増える」というユーザー確定事項による）。
めくる **タイミング**（暗槓は即時、明槓は打牌後）は局進行の責務なので game.py 側で
`reveal_new_dora()` を呼ぶ時点を制御する。
"""

from __future__ import annotations

import random

from .tiles import TOTAL_TILES, build_full_set

DEAD_WALL_SIZE = 18
"""開局時の王牌の枚数（CLAUDE.md §4.1）。"""

RINSHAN_COUNT = 8
"""王牌のうち嶺上牌に充てる枚数。カン4回 + 北抜き4回の上限に一致する。"""

INDICATOR_PAIRS = 5
"""ドラ表示牌の組数（表・裏で1組）。開局時1組 + カン4回分。"""

HAND_SIZE = 13
NUM_PLAYERS = 3


class Wall:
    """1局分の山。

    シャッフル済みの牌列を受け取ることもできる（テストで牌姿を固定するため）。
    """

    def __init__(
        self,
        tiles: list[int] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        if tiles is None:
            tiles = build_full_set()
            (rng or random).shuffle(tiles)
        elif len(tiles) != TOTAL_TILES:
            raise ValueError(f"山は{TOTAL_TILES}枚でなければならない（受け取った枚数: {len(tiles)}）")
        else:
            tiles = list(tiles)

        # 先頭から王牌を切り出し、残りが山牌。
        dead = tiles[:DEAD_WALL_SIZE]
        self._rinshan: list[int] = dead[:RINSHAN_COUNT]
        self._indicators: list[int] = dead[RINSHAN_COUNT:]
        self._live: list[int] = tiles[DEAD_WALL_SIZE:]
        self._revealed_pairs = 1  # 開局時に表・裏を1組めくる

    # --- 状態の参照 --------------------------------------------------------

    @property
    def remaining(self) -> int:
        """山牌の残り枚数。0 になったら流局。"""
        return len(self._live)

    @property
    def dead_wall_size(self) -> int:
        """王牌の残り枚数。北抜きの回数だけ18枚から減る。"""
        return len(self._rinshan) + len(self._indicators)

    @property
    def kita_drawn(self) -> int:
        """北抜きによって王牌が痩せた枚数。"""
        return DEAD_WALL_SIZE - self.dead_wall_size

    def dora_indicators(self) -> list[int]:
        """めくれている表ドラ表示牌。"""
        return [self._indicators[i * 2] for i in range(self._revealed_pairs)]

    def ura_indicators(self) -> list[int]:
        """めくれている裏ドラ表示牌。立直していない者には適用しない。"""
        return [self._indicators[i * 2 + 1] for i in range(self._revealed_pairs)]

    @property
    def revealed_pairs(self) -> int:
        return self._revealed_pairs

    # --- 配牌・ツモ --------------------------------------------------------

    def deal(self, num_players: int = NUM_PLAYERS) -> list[list[int]]:
        """配牌。各家13枚を山牌の先頭から配る。"""
        hands: list[list[int]] = []
        for _ in range(num_players):
            hands.append(sorted(self._live[:HAND_SIZE]))
            del self._live[:HAND_SIZE]
        return hands

    def draw(self) -> int:
        """通常のツモ。山牌の先頭から1枚。"""
        if not self._live:
            raise IndexError("山牌が尽きている")
        return self._live.pop(0)

    # --- 嶺上牌 ------------------------------------------------------------

    def can_kan(self) -> bool:
        """カンできるか。

        嶺上牌が残っていて、かつ山尾からの補充ができる（山牌が残っている）こと。
        海底牌でのカンは認めない。
        """
        return bool(self._rinshan) and bool(self._live)

    def draw_rinshan_for_kan(self) -> int:
        """カンの嶺上牌をツモり、山尾から王牌を補充する（王牌は18枚のまま）。"""
        if not self.can_kan():
            raise RuntimeError("カンできる状態ではない")
        tile = self._rinshan.pop(0)
        self._rinshan.append(self._live.pop())  # 山尾から補充
        return tile

    def can_draw_kita(self) -> bool:
        """北抜きできるか。嶺上牌が残っていればよい（補充しないので山牌は不要）。"""
        return bool(self._rinshan)

    def draw_rinshan_for_kita(self) -> int:
        """北抜きの嶺上牌をツモる。**補充しない**ので王牌が1枚減る。"""
        if not self.can_draw_kita():
            raise RuntimeError("嶺上牌が尽きている")
        return self._rinshan.pop(0)

    # --- ドラ --------------------------------------------------------------

    def reveal_new_dora(self) -> int:
        """カンドラを1組めくり、新しい表ドラ表示牌を返す。

        タイミング（暗槓は即時 / 明槓は打牌後）の制御は呼び出し側の責務。
        """
        if self._revealed_pairs >= INDICATOR_PAIRS:
            raise RuntimeError("これ以上ドラ表示牌をめくれない")
        self._revealed_pairs += 1
        return self._indicators[(self._revealed_pairs - 1) * 2]


# --- 割れ目 ----------------------------------------------------------------


def roll_dice(rng: random.Random | None = None) -> int:
    """サイコロ2個の出目の合計（2〜12）。"""
    r = rng or random
    return r.randint(1, 6) + r.randint(1, 6)


def wareme_seat(dice_total: int, dealer_seat: int, num_players: int = NUM_PLAYERS) -> int:
    """割れ目になる席を決める（CLAUDE.md §4.9）。

    「ドラ表示された山の前に座っている人」が割れ目。出目を親から反時計回りに
    数えた席の山が割られるので、その席が割れ目になる。三人打ちなので3で巡回する。
    """
    if not 2 <= dice_total <= 12:
        raise ValueError(f"サイコロの出目が範囲外: {dice_total}")
    return (dealer_seat + dice_total - 1) % num_players
