"""フィーバー三麻の特殊役（CLAUDE.md §4.5）。

- **ベンツ**（2翻）: 8s を槓子にする。**8p では不成立**。暗槓・大明槓・加槓いずれも可。
  和了時、ベンツ成立者のドラを **×3個** にする。
- **脊髄**（13翻）: **4副露**して裸単騎。**暗槓は副露に数えない**。
- **フィーバー立直**（2翻）: 7p または 7s が **確定暗刻**（または暗槓）でリーチ。
- **ダブルフィーバー立直**（7翻）: 7p **かつ** 7s が確定暗刻。

いちばん難しいのが「確定暗刻」。手牌に3枚あるだけでは足りず、**どの和了牌で
和了しても、どの面子分解でも暗刻になる**ことを要求する。

    東東 123456s 777s 2p3p   → 成立  （777s は必ず暗刻）
    南南 111p 12356777s      → 不成立（南で和了すると 77s が雀頭になる）
"""

from __future__ import annotations

from collections.abc import Sequence

from .hand import (
    BlockKind,
    Hand,
    MeldType,
    all_decompositions,
    winning_tiles,
)
from .tiles import NUM_KINDS, TERMINALS_AND_HONORS, TILES_PER_KIND, pin, sou
from .yaku import (
    DOUBLE_FEVER_RIICHI_NAME,
    FEVER_RIICHI_NAME,
    HandValue,
    Yaku,
)

BENZ_TILE = sou(8)
"""ベンツは 8索 の槓子。8筒では成立しない（CLAUDE.md §4.5）。"""

FEVER_TILES = (pin(7), sou(7))
"""フィーバーの対象牌。7筒 と 7索。"""

BENZ_DORA_MULTIPLIER = 3

YAKU_BENZ = Yaku("ベンツ", 2)
YAKU_SEKIZUI = Yaku("脊髄", 13)
YAKU_FEVER = Yaku(FEVER_RIICHI_NAME, 2)
YAKU_DOUBLE_FEVER = Yaku(DOUBLE_FEVER_RIICHI_NAME, 7)
"""フィーバー立直は通常の立直を **置き換える**（重ねて数えない）。
判定は `yaku._riichi_yaku` 側で、この名前を見て行っている。"""


# --- ベンツ ----------------------------------------------------------------


def has_benz(hand: Hand) -> bool:
    """8索の槓子があるか。暗槓・大明槓・加槓のいずれでもよい。"""
    return any(meld.is_kan and meld.tile == BENZ_TILE for meld in hand.melds)


def dora_multiplier(hand: Hand) -> int:
    """ベンツ成立時はドラが3倍になる。"""
    return BENZ_DORA_MULTIPLIER if has_benz(hand) else 1


# --- 脊髄 ------------------------------------------------------------------


def has_sekizui(hand: Hand) -> bool:
    """4副露して裸単騎で和了したか。

    hand は **和了牌を含んだ完成形**。裸単騎の和了なので手の内は雀頭の2枚だけになる。
    暗槓は副露に数えないので、暗槓を含む手では成立しない（CLAUDE.md §4.5）。
    """
    return hand.open_meld_count == 4 and hand.concealed_tile_count == 2


# --- フィーバー ------------------------------------------------------------


def is_confirmed_ankou(hand: Hand, tile: int) -> bool:
    """テンパイ手について、その牌が「確定暗刻」か。

    hand はリーチ宣言後の13枚相当（打牌済み）の手牌。

    1. 暗槓ならその時点で確定。
    2. そうでなければ手の内に3枚以上あることが前提。
    3. そのうえで、**すべての和了牌 × すべての面子分解**で暗刻として使われること。
    """
    if any(meld.type is MeldType.ANKAN and meld.tile == tile for meld in hand.melds):
        return True
    if hand.concealed[tile] < 3:
        return False

    wins = winning_tiles(hand)
    if not wins:
        return False

    for win in wins:
        probe = hand.copy()
        probe.add(win)
        decompositions = all_decompositions(probe)
        if not decompositions:
            return False  # 七対子など、面子分解できない和了形が混ざっている
        for blocks in decompositions:
            if not any(
                block.kind is BlockKind.TRIPLET and block.tile == tile and block.concealed
                for block in blocks
            ):
                return False
    return True


def is_junkara(hand: Hand, visible: Sequence[int]) -> bool:
    """純カラか（待ちが1枚も残っていないか）。

    visible はリーチ者から見えている枚数配列（自分の手牌・全員の河・副露・
    ドラ表示牌）。リーチ者の目線で数えるので、他家の手の内は含めない。
    """
    for tile in winning_tiles(hand):
        if visible[tile] < TILES_PER_KIND:
            return False
    return True


def fever_yaku(
    hand: Hand,
    visible: Sequence[int],
    is_menzen: bool = True,
    is_furiten: bool = False,
) -> Yaku | None:
    """フィーバー立直 / ダブルフィーバー立直が成立するか。

    成立条件（CLAUDE.md §4.5）:
      1. 門前でリーチをかけられる
      2. 7p または 7s が確定暗刻（または暗槓）
      3. リーチ者の目線から純カラでない
      4. フリテンでない
    """
    if not is_menzen or is_furiten:
        return None
    if is_junkara(hand, visible):
        return None

    confirmed = [tile for tile in FEVER_TILES if is_confirmed_ankou(hand, tile)]
    if len(confirmed) == 2:
        return YAKU_DOUBLE_FEVER
    if len(confirmed) == 1:
        return YAKU_FEVER
    return None


def visible_counts(
    own_hand: Hand,
    discards: Sequence[Sequence[int]],
    melds_tiles: Sequence[int] = (),
    dora_indicators: Sequence[int] = (),
) -> list[int]:
    """リーチ者から見えている牌の枚数配列を作る。

    自分の手牌（副露・抜いた北を含む）+ 全員の河 + 場に見えている副露牌 +
    めくれているドラ表示牌。
    """
    counts = [0] * NUM_KINDS
    for tile in own_hand.all_tiles():
        counts[tile] += 1
    from .tiles import PEI

    counts[PEI] += own_hand.kita
    for river in discards:
        for tile in river:
            counts[tile] += 1
    for tile in melds_tiles:
        counts[tile] += 1
    for tile in dora_indicators:
        counts[tile] += 1
    return [min(count, TILES_PER_KIND) for count in counts]


# --- 流し満貫 --------------------------------------------------------------

YAKU_NAGASHI = Yaku("流し満貫", 5)
NAGASHI_FU = 30
"""流し満貫は5翻役なので符は点数に影響しないが、HandValue の体裁を整えるために置く。"""


def is_nagashi_mangan(discards: Sequence[int], discards_were_called: bool) -> bool:
    """流し満貫が成立するか（CLAUDE.md §4.6）。

    捨て牌がすべて么九牌（一九字牌）で、一度もポン・チー・カンされていないこと。
    **抜いた北をポン・カンされた場合も「鳴かれた」とみなして不成立**。
    """
    if discards_were_called or not discards:
        return False
    return all(tile in TERMINALS_AND_HONORS for tile in discards)


def nagashi_dora(
    discards: Sequence[int], kita: int, dora_indicators: Sequence[int]
) -> int:
    """流し満貫に加算するドラ（CLAUDE.md §4.6）。

    **捨て牌にあるドラの枚数 + 抜いた北の枚数**。手牌ではなく河を数えるのが特徴。
    """
    from .tiles import PEI, PERMANENT_DORA, dora_from_indicator

    dora_tiles = [dora_from_indicator(indicator) for indicator in dora_indicators]
    total = 0
    for tile in discards:
        if tile in PERMANENT_DORA:
            total += 1
        total += dora_tiles.count(tile)
    # 抜いた北は1枚 = ドラ1個。ドラ表示牌が西ならダブドラになる。
    total += kita * (1 + dora_tiles.count(PEI))
    return total


def nagashi_value(
    discards: Sequence[int], kita: int, dora_indicators: Sequence[int]
) -> HandValue:
    """流し満貫の HandValue。5翻役 + 河のドラ。

    内訳は通常の和了と同じく、抜いた北の枚数を抜きドラ、それ以外をドラとして出す。
    """
    from .yaku import DoraCount

    dora = nagashi_dora(discards, kita, dora_indicators)
    yaku = [YAKU_NAGASHI, *DoraCount(dora=dora - kita, kita=kita).yaku()]
    return HandValue(yaku=yaku, fu=NAGASHI_FU, han=sum(y.han for y in yaku), dora=dora)


def extra_yaku_for_win(hand: Hand, fever: Yaku | None = None) -> tuple[Yaku, ...]:
    """和了時に足す特殊役をまとめる。

    フィーバー立直 × ベンツ、ベンツ × 脊髄 はいずれも重複可（CLAUDE.md §4.5）。
    """
    found: list[Yaku] = []
    if fever is not None:
        found.append(fever)
    if has_benz(hand):
        found.append(YAKU_BENZ)
    if has_sekizui(hand):
        found.append(YAKU_SEKIZUI)
    return tuple(found)
