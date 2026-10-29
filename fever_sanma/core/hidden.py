"""隠しコマンド（配牌の仕込み）。

対局中に合言葉を入力すると、**次の配牌**で指定の牌が手牌に入るようにする。

    fever  7筒 か 7索 のどちらかを3枚以上（フィーバー立直を狙える）
    benz   8索 を4枚（暗槓すればベンツ）

ルールそのものは変えない。山を配る前に牌を入れ替えるだけなので、山の108枚の
構成は崩れない。合言葉の受け付け（キー入力など）は UI 側の責務で、ここは
「何を何枚仕込むか」と「山にどう仕込むか」だけを持つ。
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable

from .tiles import pin, sou
from .wall import DEAD_WALL_SIZE, HAND_SIZE

FEVER = "fever"
BENZ = "benz"
COMMANDS = (FEVER, BENZ)

DESCRIPTIONS = {
    FEVER: "フィーバーモード（7筒か7索を3枚以上）",
    BENZ: "ベンツモード（8索を4枚）",
}


def guaranteed_tiles(commands: Iterable[str], rng: random.Random) -> list[int]:
    """有効になっている隠しコマンドから、配牌に必ず入れる牌を決める。"""
    tiles: list[int] = []
    for command in commands:
        if command == FEVER:
            tiles += [rng.choice((pin(7), sou(7)))] * 3
        elif command == BENZ:
            tiles += [sou(8)] * 4
        else:
            raise ValueError(f"不明な隠しコマンド: {command!r}")
    return tiles


def rig_deal(tiles: list[int], seat: int, guaranteed: list[int]) -> list[int]:
    """シャッフル済みの山を、seat の配牌に guaranteed が入るよう入れ替えた山にする。

    `Wall` は先頭18枚を王牌、続く13枚ずつを各席の配牌にするので、その席の配牌の
    範囲へ、範囲外にある牌を入れ替えで持ってくる。入れ替えるだけなので108枚の
    構成は変わらない。もともと配牌に入っていた枚数も数えるので「3枚以上」になる。
    """
    result = list(tiles)
    start = DEAD_WALL_SIZE + HAND_SIZE * seat
    region = range(start, start + HAND_SIZE)
    wanted = Counter(guaranteed)
    if sum(wanted.values()) > HAND_SIZE:
        raise ValueError("配牌に入りきらない")

    for tile, need in wanted.items():
        have = sum(1 for i in region if result[i] == tile)
        while have < need:
            outside = next(
                i for i in range(len(result)) if i not in region and result[i] == tile
            )
            # 配牌の中で、仕込む対象でない牌（または必要数を超えたぶん）と入れ替える
            inside = next(
                i
                for i in region
                if result[i] not in wanted
                or sum(1 for j in region if result[j] == result[i]) > wanted[result[i]]
            )
            result[outside], result[inside] = result[inside], result[outside]
            have += 1
    return result
