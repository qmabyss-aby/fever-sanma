"""手牌・副露・面子分解。

面子分解は **全パターンを列挙する** のが要点。フィーバーリーチの「確定暗刻」判定
（CLAUDE.md §4.5）は「どう分解しても 7p が暗刻になる」ことを要求するので、
分解を1つ見つけて打ち切る実装では判定できない。

    東東 123456 777s ②③   → 成立   （7sは必ず暗刻）
    南南 123 567 777s ①①① → 不成立 （南と7sのシャンポンにも取れる）
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .tiles import (
    NUM_KINDS,
    TERMINALS_AND_HONORS,
    can_form_run,
    empty_counts,
)


class BlockKind(StrEnum):
    """面子・雀頭の種類。"""

    RUN = "run"  # 順子
    TRIPLET = "triplet"  # 刻子
    KAN = "kan"  # 槓子
    PAIR = "pair"  # 雀頭


@dataclass(frozen=True, slots=True)
class Block:
    """分解後の1ブロック。

    tile は順子なら最小の牌、それ以外はその牌そのもの。
    concealed は暗（門前で作った）かどうか。
    """

    kind: BlockKind
    tile: int
    concealed: bool = True

    @property
    def tiles(self) -> list[int]:
        match self.kind:
            case BlockKind.RUN:
                return [self.tile, self.tile + 1, self.tile + 2]
            case BlockKind.TRIPLET:
                return [self.tile] * 3
            case BlockKind.KAN:
                return [self.tile] * 4
            case BlockKind.PAIR:
                return [self.tile] * 2

    @property
    def is_set(self) -> bool:
        """刻子・槓子か（順子でない面子）。"""
        return self.kind in (BlockKind.TRIPLET, BlockKind.KAN)

    @property
    def is_meld(self) -> bool:
        """面子か（雀頭でない）。"""
        return self.kind != BlockKind.PAIR

    def contains(self, tile: int) -> bool:
        return tile in self.tiles


class MeldType(StrEnum):
    """副露の種類。"""

    CHI = "chi"  # チー（三麻だがフィーバー三麻では可 / CLAUDE.md §4.1）
    PON = "pon"
    MINKAN = "minkan"  # 大明槓
    KAKAN = "kakan"  # 加槓
    ANKAN = "ankan"  # 暗槓


@dataclass(frozen=True, slots=True)
class Meld:
    """晒した面子。

    tile はチーなら順子の最小牌、それ以外はその牌。
    called_from は鳴いた相手の席（暗槓は None）。
    """

    type: MeldType
    tile: int
    called_from: int | None = None
    called_tile: int | None = None

    @property
    def is_concealed(self) -> bool:
        """門前を崩さないか。暗槓のみ True。"""
        return self.type is MeldType.ANKAN

    @property
    def is_open_meld(self) -> bool:
        """副露に数えるか。**暗槓は副露に数えない**（脊髄の判定 / CLAUDE.md §4.5）。"""
        return not self.is_concealed

    @property
    def is_kan(self) -> bool:
        return self.type in (MeldType.MINKAN, MeldType.KAKAN, MeldType.ANKAN)

    @property
    def tiles(self) -> list[int]:
        if self.type is MeldType.CHI:
            return [self.tile, self.tile + 1, self.tile + 2]
        if self.is_kan:
            return [self.tile] * 4
        return [self.tile] * 3

    def to_block(self) -> Block:
        match self.type:
            case MeldType.CHI:
                return Block(BlockKind.RUN, self.tile, concealed=False)
            case MeldType.PON:
                return Block(BlockKind.TRIPLET, self.tile, concealed=False)
            case MeldType.ANKAN:
                return Block(BlockKind.KAN, self.tile, concealed=True)
            case _:  # MINKAN / KAKAN
                return Block(BlockKind.KAN, self.tile, concealed=False)


@dataclass
class Hand:
    """1人分の手牌。

    concealed は長さ27の枚数配列（手の内）。副露牌は含まない。
    kita は抜いた北の枚数（抜きドラ / CLAUDE.md §4.3）。
    """

    concealed: list[int] = field(default_factory=empty_counts)
    melds: list[Meld] = field(default_factory=list)
    kita: int = 0

    @classmethod
    def from_counts(cls, counts: Sequence[int], melds: Sequence[Meld] = (), kita: int = 0) -> Hand:
        return cls(list(counts), list(melds), kita)

    @property
    def is_menzen(self) -> bool:
        """門前か。暗槓は門前を崩さない。"""
        return all(meld.is_concealed for meld in self.melds)

    @property
    def open_meld_count(self) -> int:
        """副露の数。暗槓は数えない（脊髄は4副露で成立 / CLAUDE.md §4.5）。"""
        return sum(1 for meld in self.melds if meld.is_open_meld)

    @property
    def kan_count(self) -> int:
        return sum(1 for meld in self.melds if meld.is_kan)

    @property
    def concealed_tile_count(self) -> int:
        return sum(self.concealed)

    @property
    def is_tanki_only(self) -> bool:
        """裸単騎か。手の内が1枚だけの状態。"""
        return self.concealed_tile_count == 1

    def add(self, tile: int) -> None:
        self.concealed[tile] += 1

    def remove(self, tile: int) -> None:
        if self.concealed[tile] <= 0:
            raise ValueError(f"手牌に無い牌を切ろうとした: {tile}")
        self.concealed[tile] -= 1

    def copy(self) -> Hand:
        return Hand(list(self.concealed), list(self.melds), self.kita)

    def all_tiles(self) -> list[int]:
        """手の内と副露を合わせた全ての牌（槓子は4枚として数える）。"""
        tiles: list[int] = []
        for index, count in enumerate(self.concealed):
            tiles.extend([index] * count)
        for meld in self.melds:
            tiles.extend(meld.tiles)
        return tiles

    def meld_blocks(self) -> list[Block]:
        return [meld.to_block() for meld in self.melds]


# --- 面子分解 --------------------------------------------------------------


def decompose_standard(counts: Sequence[int]) -> list[list[Block]]:
    """門前部分を「面子いくつ + 雀頭1つ」に分解する全パターンを返す。

    counts の合計が 3n+2 でなければ空リスト。戻り値の各要素は Block のリストで、
    必ず雀頭を1つ含む。同じ分解が重複して現れることはない。
    """
    total = sum(counts)
    if total % 3 != 2:
        return []

    results: list[list[Block]] = []
    for pair_tile in range(NUM_KINDS):
        if counts[pair_tile] < 2:
            continue
        work = list(counts)
        work[pair_tile] -= 2
        pair = Block(BlockKind.PAIR, pair_tile)
        for melds in _melds_from(work, 0):
            results.append([pair, *melds])
    return results


def _melds_from(work: list[int], start: int) -> list[list[Block]]:
    """work を面子だけに分解する全パターン。

    「残っている最小の牌から順に必ず使い切る」ことで、同じ組み合わせを
    順序違いで二重に数えるのを防いでいる。
    """
    index = start
    while index < NUM_KINDS and work[index] == 0:
        index += 1
    if index == NUM_KINDS:
        return [[]]

    patterns: list[list[Block]] = []

    if work[index] >= 3:
        work[index] -= 3
        for rest in _melds_from(work, index):
            patterns.append([Block(BlockKind.TRIPLET, index), *rest])
        work[index] += 3

    if can_form_run(index) and work[index + 1] > 0 and work[index + 2] > 0:
        work[index] -= 1
        work[index + 1] -= 1
        work[index + 2] -= 1
        for rest in _melds_from(work, index):
            patterns.append([Block(BlockKind.RUN, index), *rest])
        work[index] += 1
        work[index + 1] += 1
        work[index + 2] += 1

    return patterns


def is_chiitoitsu(counts: Sequence[int]) -> bool:
    """七対子の形か。4枚使いは認めない（7種類ちょうど必要）。"""
    if sum(counts) != 14:
        return False
    return sum(1 for c in counts if c == 2) == 7


def is_kokushi(counts: Sequence[int]) -> bool:
    """国士無双の形か。

    この変則牌姿でも么九牌はちょうど13種（1m 9m 1p 9p 1s 9s + 字牌7種）なので、
    通常麻雀と同じく「13種すべて + どれか1枚重複」で成立する。
    """
    if sum(counts) != 14:
        return False
    if any(counts[i] for i in range(NUM_KINDS) if i not in TERMINALS_AND_HONORS):
        return False
    kinds = [counts[i] for i in TERMINALS_AND_HONORS]
    return all(c >= 1 for c in kinds) and max(kinds) == 2


TOTAL_MELDS = 4
"""通常形の面子の数（4面子1雀頭）。"""


def is_complete(hand: Hand) -> bool:
    """和了形か（役の有無は見ない）。"""
    if is_chiitoitsu(hand.concealed) or is_kokushi(hand.concealed):
        # 七対子・国士無双は門前限定
        return hand.is_menzen and not hand.melds
    return bool(all_decompositions(hand))


def winning_tiles(hand: Hand) -> list[int]:
    """この手牌の待ち（和了牌）を列挙する。

    手の内が 3n+1 枚（ツモ前・ロン待ち）の状態で呼ぶ。牌が4枚使い切られている
    ものも待ちとしては返す（純カラかどうかの判定は呼び出し側の責務）。
    """
    waits: list[int] = []
    for tile in range(NUM_KINDS):
        if hand.concealed[tile] >= 4:
            # 手の内に4枚あるなら5枚目は存在しないので和了牌になりえない
            continue
        probe = hand.copy()
        probe.add(tile)
        if is_complete(probe):
            waits.append(tile)
    return waits


def all_decompositions(hand: Hand) -> list[list[Block]]:
    """副露も含めた完成形（4面子1雀頭）の全分解パターン。

    面子数が4に満たない分解は和了形ではないので除く。
    七対子・国士無双は面子分解できないので空リストを返す。
    """
    needed = TOTAL_MELDS - len(hand.melds)
    if needed < 0:
        return []
    meld_blocks = hand.meld_blocks()
    return [
        blocks + meld_blocks
        for blocks in decompose_standard(hand.concealed)
        if len(blocks) - 1 == needed  # 雀頭1つを差し引いた数が面子数
    ]
