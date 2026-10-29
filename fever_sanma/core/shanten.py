"""向聴数と待ちの計算。

牌が27種しかないので素直な全探索で足りる。通常麻雀と違うのは、**萬子に順子が
作れない**（1m と 9m しかない）点。インデックス上は 1m と 9m が隣り合うので、
搭子の判定を素朴に `index+1` で書くと 1m+9m を両面搭子と誤認する。
順子・搭子の判定は必ず `_can_ryanmen` / `_can_kanchan` / `can_form_run` を通すこと。
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from .hand import Hand, is_complete, winning_tiles
from .tiles import (
    NUM_KINDS,
    P1,
    TERMINALS_AND_HONORS,
    Z1,
    can_form_run,
    number_of,
)

MAX_SETS = 4
"""1つの和了形に含まれる面子の数。面子候補（面子 + 搭子）もこの数までしか数えない。

雀頭は別枠。「面子・搭子・雀頭で合わせて5ブロック」と数えると、雀頭のない
「3面子 + 2搭子」（例: 123p 456p 789s 24s 68s）が5ブロック揃ってテンパイ扱いになるが、
実際は搭子の片方を雀頭に変える必要があるので1向聴。
"""


def _can_ryanmen(index: int) -> bool:
    """index と index+1 で搭子を作れるか（萬子・字牌は不可）。"""
    return P1 <= index < Z1 and number_of(index) <= 8


def _can_kanchan(index: int) -> bool:
    """index と index+2 で嵌張を作れるか。"""
    return P1 <= index < Z1 and number_of(index) <= 7


# --- スートごとに分けて計算する向聴数 -----------------------------------
#
# 手牌全体を一度に全探索すると、14枚の手で1回1ミリ秒ほどかかる。CPU は1手に
# 数百回呼ぶので遅すぎる。面子・搭子はスートをまたがないので、スートごとに
# 「面子数・搭子数・雀頭の有無」の組み合わせを求めてから合わせればよい。
# 同じ形のスートは何度でも出てくるので、結果をキャッシュすると非常に速くなる。

_SEGMENTS = (
    (0, 2, False),  # 萬子（1m・9m だけなので順子・搭子は作れない）
    (P1, 9, True),  # 筒子
    (P1 + 9, 9, True),  # 索子
    (Z1, 7, False),  # 字牌
)


@lru_cache(maxsize=None)
def _segment_options(counts: tuple[int, ...], runs: bool) -> frozenset[tuple[int, int, int]]:
    """1スートから取れる (面子数, 搭子数, 雀頭の有無) の組み合わせ（劣るものは除く）。"""
    index = next((i for i, c in enumerate(counts) if c), None)
    if index is None:
        return frozenset({(0, 0, 0)})

    found: set[tuple[int, int, int]] = set()

    def take(removed: dict[int, int], melds: int, partials: int, head: int) -> None:
        rest = list(counts)
        for i, n in removed.items():
            rest[i] -= n
        for m, t, h in _segment_options(tuple(rest), runs):
            if h + head <= 1:
                found.add((m + melds, t + partials, h + head))

    n = len(counts)
    if counts[index] >= 3:
        take({index: 3}, 1, 0, 0)  # 刻子
    if runs and index + 2 < n and counts[index + 1] and counts[index + 2]:
        take({index: 1, index + 1: 1, index + 2: 1}, 1, 0, 0)  # 順子
    if counts[index] >= 2:
        take({index: 2}, 0, 0, 1)  # 雀頭
        take({index: 2}, 0, 1, 0)  # 対子（搭子として）
    if runs and index + 1 < n and counts[index + 1]:
        take({index: 1, index + 1: 1}, 0, 1, 0)  # 両面・辺張
    if runs and index + 2 < n and counts[index + 2]:
        take({index: 1, index + 2: 1}, 0, 1, 0)  # 嵌張
    take({index: 1}, 0, 0, 0)  # 浮き牌
    return _pareto(found)


def _pareto(options: set[tuple[int, int, int]]) -> frozenset[tuple[int, int, int]]:
    """雀頭の有無ごとに、面子数・搭子数のどちらも上回る組み合わせがあるものを除く。

    向聴数は面子数・搭子数のどちらが増えても悪くならないので、劣る組み合わせは
    最終結果に影響しない。
    """
    return frozenset(
        option
        for option in options
        if not any(
            other != option
            and other[2] == option[2]
            and other[0] >= option[0]
            and other[1] >= option[1]
            for other in options
        )
    )


def standard_shanten(counts: Sequence[int], called_melds: int = 0) -> int:
    """通常形（4面子1雀頭）の向聴数。

    called_melds は副露・暗槓の数。counts には副露牌を含めない。
    """
    combined: frozenset[tuple[int, int, int]] = frozenset({(0, 0, 0)})
    for start, length, runs in _SEGMENTS:
        options = _segment_options(tuple(counts[start : start + length]), runs)
        merged = {
            (m1 + m2, t1 + t2, h1 + h2)
            for m1, t1, h1 in combined
            for m2, t2, h2 in options
            if h1 + h2 <= 1
        }
        combined = _pareto(merged)

    best = 8
    for melds, partials, head in combined:
        melds += called_melds
        # 面子 + 搭子は4つまで（雀頭は別枠。MAX_SETS の説明を参照）
        partials = min(partials, max(0, MAX_SETS - melds))
        best = min(best, 8 - 2 * melds - partials - head)
    return best


def _standard_shanten_bruteforce(counts: Sequence[int], called_melds: int = 0) -> int:
    """通常形（4面子1雀頭）の向聴数を、手牌全体の全探索で求める（検証用の参照実装）。

    called_melds は副露・暗槓の数。counts には副露牌を含めない。
    """
    work = list(counts)
    best = 8

    def rec(index: int, melds: int, partials: int, head: int) -> None:
        nonlocal best
        shanten = 8 - 2 * (melds + called_melds) - partials - head
        if shanten < best:
            best = shanten

        while index < NUM_KINDS and work[index] == 0:
            index += 1
        if index >= NUM_KINDS:
            return

        # 面子 + 搭子は4つまで。雀頭は別枠なので room に関係なく取れる
        room = melds + called_melds + partials < MAX_SETS

        if room and work[index] >= 3:  # 刻子
            work[index] -= 3
            rec(index, melds + 1, partials, head)
            work[index] += 3

        if room and can_form_run(index) and work[index + 1] and work[index + 2]:  # 順子
            work[index] -= 1
            work[index + 1] -= 1
            work[index + 2] -= 1
            rec(index, melds + 1, partials, head)
            work[index] += 1
            work[index + 1] += 1
            work[index + 2] += 1

        if work[index] >= 2:
            work[index] -= 2
            if not head:  # 雀頭として使う
                rec(index, melds, partials, 1)
            if room:  # 対子（シャンポンの片割れ）として使う
                rec(index, melds, partials + 1, head)
            work[index] += 2

        if room and _can_ryanmen(index) and work[index + 1]:  # 両面・辺張
            work[index] -= 1
            work[index + 1] -= 1
            rec(index, melds, partials + 1, head)
            work[index] += 1
            work[index + 1] += 1

        if room and _can_kanchan(index) and work[index + 2]:  # 嵌張
            work[index] -= 1
            work[index + 2] -= 1
            rec(index, melds, partials + 1, head)
            work[index] += 1
            work[index + 2] += 1

        work[index] -= 1  # この牌は使わない（浮き牌）
        rec(index, melds, partials, head)
        work[index] += 1

    rec(0, 0, 0, 0)
    return best


def chiitoitsu_shanten(counts: Sequence[int]) -> int:
    """七対子の向聴数。門前13枚の手にのみ意味がある。"""
    pairs = sum(1 for c in counts if c >= 2)
    kinds = sum(1 for c in counts if c >= 1)
    shanten = 6 - pairs
    if kinds < 7:
        shanten += 7 - kinds  # 種類が足りない分は追加で必要
    return shanten


def kokushi_shanten(counts: Sequence[int]) -> int:
    """国士無双の向聴数。么九牌はこの変則牌姿でもちょうど13種ある。"""
    kinds = sum(1 for i in TERMINALS_AND_HONORS if counts[i] >= 1)
    has_pair = any(counts[i] >= 2 for i in TERMINALS_AND_HONORS)
    return 13 - kinds - (1 if has_pair else 0)


def shanten(hand: Hand) -> int:
    """手牌の向聴数。0 でテンパイ、-1 で和了形。"""
    best = standard_shanten(hand.concealed, len(hand.melds))
    if hand.is_menzen and not hand.melds:
        # 七対子・国士無双は門前限定（暗槓があっても面子が固定されるので対象外）
        best = min(best, chiitoitsu_shanten(hand.concealed), kokushi_shanten(hand.concealed))
    return best


def is_tenpai(hand: Hand) -> bool:
    """テンパイか。流局時のノーテン罰符判定に使う。"""
    return shanten(hand) == 0


def waits(hand: Hand) -> list[int]:
    """待ち牌。テンパイでなければ空リスト。"""
    return winning_tiles(hand)


def ukeire(hand: Hand, visible: Sequence[int] | None = None) -> dict[int, int]:
    """有効牌と、その残り枚数。

    visible は場に見えている枚数配列（自分の手牌・河・副露・ドラ表示）。
    省略すると手の内だけを差し引く。
    """
    current = shanten(hand)
    seen = list(visible) if visible is not None else list(hand.concealed)
    result: dict[int, int] = {}
    for tile in range(NUM_KINDS):
        remaining = 4 - seen[tile]
        if remaining <= 0:
            continue
        probe = hand.copy()
        probe.add(tile)
        # 和了牌なら切らずに上がるので -1。それ以外は、どれかを切って向聴が進むかを見る。
        after = -1 if is_complete(probe) else _shanten_after_best_discard(probe)
        if after < current:
            result[tile] = remaining
    return result


def _shanten_after_best_discard(hand: Hand) -> int:
    best = 99
    for tile in range(NUM_KINDS):
        if hand.concealed[tile] == 0:
            continue
        probe = hand.copy()
        probe.remove(tile)
        best = min(best, shanten(probe))
    return best
