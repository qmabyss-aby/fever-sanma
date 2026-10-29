"""通常役の判定と符計算。

通常麻雀との差異（CLAUDE.md §4.4）:

- **混一色は2翻**（通常は3翻）。喰い下がり1翻。
- **三色同順は役に無い**。三色同刻はある（萬子が1と9しかないので 111 か 999 のみ）。
- **東と北は常に全員の風牌**。東風戦なので親だけ東が場風+自風で2翻（連風牌）。
  北は常に1翻で、かつ常時ドラ。
- **南家の南・西家の西も自風**として役牌になる（Wiki 未記載・ユーザー確定事項）。
- 一気通貫・清一色・九蓮宝燈は筒子か索子でしか成立しない（萬子は1と9のみ）。
- **大車輪**（2p〜8pを2枚ずつ、鳴き不可）が役満にある。
- **1つの役でダブル役満は採用しない**。四暗刻単騎・国士13面・九蓮9面・大四喜も
  すべてシングル役満。複数役満の複合によるダブル以上はあり。

符は標準的な日本麻雀通り（ユーザー確定事項）。連風牌の雀頭は2符とする。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .hand import (
    Block,
    BlockKind,
    Hand,
    all_decompositions,
    is_chiitoitsu,
    is_kokushi,
)
from .tiles import (
    CHUREN_SUITS,
    DAISHARIN_TILES,
    DRAGONS,
    GREEN_TILES,
    NUM_KINDS,
    PEI,
    PERMANENT_DORA,
    TERMINALS_AND_HONORS,
    TON,
    WINDS,
    dora_from_indicator,
    is_honor,
    is_terminal_or_honor,
    number_of,
    suit_of,
)


@dataclass(frozen=True, slots=True)
class Yaku:
    """成立した役。yakuman が 1 以上なら役満（数値は重複数）。"""

    name: str
    han: int = 0
    yakuman: int = 0


@dataclass
class WinContext:
    """和了時の状況。

    hand は **和了牌を含んだ完成形**（手の内 + 副露で14枚相当）を渡す。
    """

    hand: Hand
    win_tile: int
    is_tsumo: bool
    seat_wind: int = TON
    round_wind: int = TON  # 東風戦なので常に東
    is_riichi: bool = False
    is_double_riichi: bool = False
    is_open_riichi: bool = False
    discarder_was_riichi: bool = False
    """オープン立直の翻数を決めるのに使う（CLAUDE.md §4.2）。"""
    is_ippatsu: bool = False
    is_rinshan: bool = False
    is_chankan: bool = False
    is_haitei: bool = False
    is_houtei: bool = False
    is_tenhou: bool = False
    is_chiihou: bool = False
    dora_indicators: tuple[int, ...] = ()
    ura_indicators: tuple[int, ...] = ()
    extra_yaku: tuple[Yaku, ...] = ()
    """フェーズ6以降で足す特殊役（フィーバー立直・ベンツ・脊髄など）。"""

    dora_multiplier: int = 1
    """ベンツ成立時に 3 になる（和了者のドラを×3個にする / CLAUDE.md §4.5）。"""

    @property
    def is_dealer(self) -> bool:
        return self.seat_wind == TON


@dataclass
class HandValue:
    """役判定の結果。"""

    yaku: list[Yaku] = field(default_factory=list)
    fu: int = 0
    han: int = 0
    """ドラを含めた総翻数。"""
    dora: int = 0
    yakuman: int = 0
    """役満の重複数。0 なら通常役。"""

    @property
    def yaku_han(self) -> int:
        """ドラを除いた、役だけの翻数。"""
        return sum(y.han for y in self.yaku if not is_dora_yaku(y.name))

    @property
    def binding_han(self) -> int:
        """二翻縛りの判定に使う翻数。**ドラと一発を除く**（CLAUDE.md §4.1）。"""
        return sum(
            y.han
            for y in self.yaku
            if not is_dora_yaku(y.name) and y.name != "一発"
        )

    @property
    def satisfies_binding(self) -> bool:
        """常に二翻縛り。役満なら無条件で成立。"""
        return bool(self.yakuman) or self.binding_han >= 2


# --- 役牌 ------------------------------------------------------------------


def yakuhai_han(tile: int, seat_wind: int) -> int:
    """その牌の刻子が何翻の役牌になるか。

    東は常に全員の風牌（CLAUDE.md §4.3）。東風戦なので親だけ場風と自風が重なり2翻。
    北も常に全員の風牌で1翻。南・西は自風のときだけ1翻。
    """
    if tile in DRAGONS:
        return 1
    if tile == TON:
        return 2 if seat_wind == TON else 1  # 親のみ連風牌
    if tile == PEI:
        return 1
    if tile == seat_wind:
        return 1  # 南家の南 / 西家の西
    return 0


# --- ドラ ------------------------------------------------------------------


DORA_YAKU_PREFIXES = ("ドラ", "裏ドラ", "抜きドラ")
"""ドラ系の役名の頭。二翻縛りの翻数に含めない（CLAUDE.md §4.1）。"""


def is_dora_yaku(name: str) -> bool:
    """ドラ・裏ドラ・抜きドラか。"""
    return name.startswith(DORA_YAKU_PREFIXES)


@dataclass(frozen=True, slots=True)
class DoraCount:
    """ドラの内訳。足すと従来のドラの総数になる。

    - dora: 手牌の常時ドラ（1萬・9萬・北）＋ 表ドラ表示牌に当たったもの
            （抜いた北に当たったぶんも含む）
    - ura:  裏ドラ表示牌に当たったもの（手牌・抜いた北とも。立直時のみ）
    - kita: 抜いた北の枚数（1枚 = ドラ1個）

    ベンツ成立時はそれぞれ3倍になっている。
    """

    dora: int = 0
    ura: int = 0
    kita: int = 0

    @property
    def total(self) -> int:
        return self.dora + self.ura + self.kita

    def yaku(self) -> list[Yaku]:
        """結果表示用の役。0 のものは出さない。"""
        return [
            Yaku(f"{label}{count}", count)
            for label, count in (("ドラ", self.dora), ("裏ドラ", self.ura), ("抜きドラ", self.kita))
            if count
        ]


def dora_breakdown(ctx: WinContext) -> DoraCount:
    """ドラを、どの表示牌・どこから来たかで分けて数える。

    抜いた北も手牌の北も 1枚 = ドラ1個（CLAUDE.md §4.3）。抜いた北のぶんは抜きドラに、
    手牌の北のぶんはドラに入れる。ドラ表示牌が西なら北はダブドラになる。
    """
    omote = [dora_from_indicator(i) for i in ctx.dora_indicators]
    ura = [dora_from_indicator(i) for i in ctx.ura_indicators] if ctx.is_riichi else []
    in_hand = ctx.hand.all_tiles()
    nuki = [PEI] * ctx.hand.kita
    dora = sum(1 for t in in_hand if t in PERMANENT_DORA)
    dora += sum(omote.count(t) for t in in_hand + nuki)
    ura_count = sum(ura.count(t) for t in in_hand + nuki)
    times = ctx.dora_multiplier
    return DoraCount(dora * times, ura_count * times, ctx.hand.kita * times)


def count_dora(ctx: WinContext) -> int:
    """ドラの総数（ドラ＋裏ドラ＋抜きドラ）。"""
    return dora_breakdown(ctx).total


# --- ブロック集合に対する判定 ---------------------------------------------


def _block_tiles(blocks: list[Block]) -> list[int]:
    tiles: list[int] = []
    for block in blocks:
        tiles.extend(block.tiles)
    return tiles


def _suits_used(tiles: list[int]) -> set[str]:
    return {suit_of(tile) for tile in tiles}


def _sets(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.is_set]


def _runs(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.kind == BlockKind.RUN]


def _pair(blocks: list[Block]) -> Block:
    return next(b for b in blocks if b.kind == BlockKind.PAIR)


# --- 役満 ------------------------------------------------------------------


def _yakuman(ctx: WinContext, blocks: list[Block], absorbed: int | None) -> list[Yaku]:
    """通常形から成立する役満。Wiki の通り1役でダブルにはしない。"""
    found: list[Yaku] = []
    tiles = _block_tiles(blocks)
    sets = _sets(blocks)
    pair = _pair(blocks)

    concealed_sets = [
        b
        for index, b in enumerate(blocks)
        if b.is_set and b.concealed and not (index == absorbed and not ctx.is_tsumo)
    ]
    if len(concealed_sets) == 4:
        found.append(Yaku("四暗刻", yakuman=1))  # 単騎もシングル

    dragon_sets = [b for b in sets if b.tile in DRAGONS]
    if len(dragon_sets) == 3:
        found.append(Yaku("大三元", yakuman=1))

    wind_sets = [b for b in sets if b.tile in WINDS]
    if len(wind_sets) == 4:
        found.append(Yaku("大四喜", yakuman=1))  # シングル
    elif len(wind_sets) == 3 and pair.tile in WINDS:
        found.append(Yaku("小四喜", yakuman=1))

    if all(is_honor(tile) for tile in tiles):
        found.append(Yaku("字一色", yakuman=1))

    if all(is_terminal_or_honor(tile) and not is_honor(tile) for tile in tiles):
        found.append(Yaku("清老頭", yakuman=1))

    if all(tile in GREEN_TILES for tile in tiles):
        found.append(Yaku("緑一色", yakuman=1))  # 鳴きOK

    if len([b for b in blocks if b.kind == BlockKind.KAN]) == 4:
        found.append(Yaku("四槓子", yakuman=1))

    if _is_churen(ctx, tiles):
        found.append(Yaku("九蓮宝燈", yakuman=1))  # 9面もシングル

    return found


def _is_churen(ctx: WinContext, tiles: list[int]) -> bool:
    """九蓮宝燈。門前限定で、筒子か索子のみ（萬子は1と9しかないので不可）。"""
    if not ctx.hand.is_menzen or ctx.hand.melds:
        return False
    suits = _suits_used(tiles)
    if len(suits) != 1:
        return False
    suit = next(iter(suits))
    if suit not in CHUREN_SUITS:
        return False
    counts = [0] * 10
    for tile in tiles:
        counts[number_of(tile)] += 1
    required = [0, 3, 1, 1, 1, 1, 1, 1, 1, 3]
    extra = 0
    for number in range(1, 10):
        if counts[number] < required[number]:
            return False
        extra += counts[number] - required[number]
    return extra == 1


# --- 通常役 ----------------------------------------------------------------


def _standard_yaku(ctx: WinContext, blocks: list[Block], absorbed: int | None) -> list[Yaku]:
    found: list[Yaku] = []
    hand = ctx.hand
    menzen = hand.is_menzen
    tiles = _block_tiles(blocks)
    sets = _sets(blocks)
    runs = _runs(blocks)
    pair = _pair(blocks)

    # --- 状況役 ---
    found.extend(_riichi_yaku(ctx))
    if ctx.is_ippatsu:
        found.append(Yaku("一発", 1))
    if ctx.is_tsumo and menzen:
        found.append(Yaku("門前清自摸和", 1))
    if ctx.is_rinshan:
        found.append(Yaku("嶺上開花", 1))
    if ctx.is_chankan:
        found.append(Yaku("槍槓", 1))
    if ctx.is_haitei:
        found.append(Yaku("海底摸月", 1))
    if ctx.is_houtei:
        found.append(Yaku("河底撈魚", 1))

    # --- 役牌 ---
    for block in sets:
        han = yakuhai_han(block.tile, ctx.seat_wind)
        if han:
            found.append(Yaku(f"役牌 {_tile_label(block.tile)}", han))

    # --- 平和 ---
    if (
        menzen
        and len(runs) == 4
        and yakuhai_han(pair.tile, ctx.seat_wind) == 0
        and _is_ryanmen_wait(blocks, absorbed, ctx.win_tile)
    ):
        found.append(Yaku("平和", 1))

    # --- タンヤオ（喰いタンあり。役一覧に門前限定・喰い下がりの注記がない）---
    if all(not is_terminal_or_honor(tile) for tile in tiles):
        found.append(Yaku("断幺九", 1))

    # --- 一盃口 / 二盃口 ---
    if menzen:
        run_tiles = [b.tile for b in runs]
        # 同じ順子が2組そろうごとに1つ。4順子が2種類ずつなら二盃口。
        identical_pairs = sum(run_tiles.count(tile) // 2 for tile in set(run_tiles))
        if identical_pairs >= 2:
            found.append(Yaku("二盃口", 3))
        elif identical_pairs == 1:
            found.append(Yaku("一盃口", 1))

    # --- 対々和 / 三暗刻 / 三槓子 ---
    if len(sets) == 4:
        found.append(Yaku("対々和", 2))
    concealed_sets = [
        b
        for index, b in enumerate(blocks)
        if b.is_set and b.concealed and not (index == absorbed and not ctx.is_tsumo)
    ]
    if len(concealed_sets) == 3:
        found.append(Yaku("三暗刻", 2))
    kans = [b for b in blocks if b.kind == BlockKind.KAN]
    if len(kans) == 3:
        found.append(Yaku("三槓子", 2))

    # --- 一気通貫（筒子・索子のみ）---
    for suit in CHUREN_SUITS:
        starts = {number_of(b.tile) for b in runs if suit_of(b.tile) == suit}
        if {1, 4, 7} <= starts:
            found.append(Yaku("一気通貫", 2 if menzen else 1))
            break

    # --- 三色同刻（萬子は1と9しかないので実質 111 か 999）---
    for number in (1, 9):
        matching = {suit_of(b.tile) for b in sets if number_of(b.tile) == number}
        if {"m", "p", "s"} <= matching:
            found.append(Yaku("三色同刻", 2))
            break

    # --- 小三元 ---
    dragon_sets = [b for b in sets if b.tile in DRAGONS]
    if len(dragon_sets) == 2 and pair.tile in DRAGONS:
        found.append(Yaku("小三元", 2))

    # --- チャンタ / 純チャンタ / 混老頭 ---
    all_blocks_have_yaochu = all(
        any(is_terminal_or_honor(tile) for tile in block.tiles) for block in blocks
    )
    has_honor = any(is_honor(tile) for tile in tiles)
    if all(is_terminal_or_honor(tile) for tile in tiles):
        if has_honor:
            found.append(Yaku("混老頭", 2))
        # 清老頭は役満側で処理
    elif all_blocks_have_yaochu:
        if has_honor:
            found.append(Yaku("混全帯幺九", 2 if menzen else 1))
        else:
            found.append(Yaku("純全帯幺九", 3 if menzen else 2))

    # --- 混一色 / 清一色 ---
    suits = _suits_used(tiles)
    number_suits = suits - {"z"}
    if len(number_suits) == 1:
        if "z" in suits:
            # 通常麻雀と異なり2翻（CLAUDE.md §4.4）
            found.append(Yaku("混一色", 2 if menzen else 1))
        else:
            found.append(Yaku("清一色", 6 if menzen else 5))

    return found


FEVER_RIICHI_NAME = "フィーバー立直"
DOUBLE_FEVER_RIICHI_NAME = "ダブルフィーバー立直"
FEVER_RIICHI_NAMES = frozenset({FEVER_RIICHI_NAME, DOUBLE_FEVER_RIICHI_NAME})

# 立直系は「通常の立直1翻 + 上乗せ」で数える（CLAUDE.md §4.5）。
# 単独で成立したときの翻数が、役一覧に載っている翻数になる:
#   ダブル立直       = 1 + 1 = 2翻
#   フィーバー立直   = 1 + 1 = 2翻
#   ダブルフィーバー = 1 + 6 = 7翻
#   オープン立直     = 1 + 1 = 2翻（ツモ） / 1 + 12 = 13翻（放銃）
RIICHI_BASE_HAN = 1
DOUBLE_RIICHI_EXTRA_HAN = 1
FEVER_EXTRA_HAN = 1
DOUBLE_FEVER_EXTRA_HAN = 6
OPEN_RIICHI_TSUMO_EXTRA_HAN = 1
OPEN_RIICHI_RON_EXTRA_HAN = 12

RIICHI_EXTRA_NAMES = frozenset(
    {"ダブル立直", "オープン立直", FEVER_RIICHI_NAME, DOUBLE_FEVER_RIICHI_NAME}
)
"""立直への上乗せぶんの役名。表示側で「+N翻」と出すために使う。"""


def _riichi_yaku(ctx: WinContext) -> list[Yaku]:
    """立直系の役（CLAUDE.md §4.2, §4.5）。

    **通常の立直1翻を土台に、種類ごとの上乗せを足す**という数え方をする。
    ダブル立直もフィーバー立直も「通常の立直 +1翻」なので、両方成立すれば +2翻。

        立直                             = 1翻
        ダブル立直                       = 1 + 1 = 2翻
        フィーバー立直                   = 1 + 1 = 2翻
        ダブルフィーバー立直             = 1 + 6 = 7翻
        オープン立直（ツモ）             = 1 + 1 = 2翻
        オープン立直（放銃）             = 1 + 12 = 13翻
        ダブル立直 × フィーバー立直      = 1 + 1 + 1 = 3翻
        ダブル立直 × ダブルフィーバー    = 1 + 1 + 6 = 8翻
        ダブル立直 × オープン立直（ツモ）= 1 + 1 + 1 = 3翻

    ただし **フィーバー立直とオープン立直は重複しない**。フィーバーが優先し、
    オープン立直の上乗せは付かない（放銃されても13翻にはならない）。
    フィーバー立直かダブルフィーバー立直かは `ctx.extra_yaku` に入ってくる。

    オープン立直の上乗せは、**放銃者が立直済みならツモ扱い**（+1翻）になる。
    """
    if not ctx.is_riichi:
        return []

    found = [Yaku("立直", RIICHI_BASE_HAN)]
    if ctx.is_double_riichi:
        found.append(Yaku("ダブル立直", DOUBLE_RIICHI_EXTRA_HAN))

    fever = next((y for y in ctx.extra_yaku if y.name in FEVER_RIICHI_NAMES), None)
    if fever is not None:
        extra = (
            DOUBLE_FEVER_EXTRA_HAN
            if fever.name == DOUBLE_FEVER_RIICHI_NAME
            else FEVER_EXTRA_HAN
        )
        found.append(Yaku(fever.name, extra))
    elif ctx.is_open_riichi:
        found.append(
            Yaku(
                "オープン立直",
                OPEN_RIICHI_TSUMO_EXTRA_HAN
                if ctx.is_tsumo or ctx.discarder_was_riichi
                else OPEN_RIICHI_RON_EXTRA_HAN,
            )
        )
    return found


def _tile_label(tile: int) -> str:
    from .tiles import tile_name

    return tile_name(tile)


def _is_ryanmen_wait(blocks: list[Block], absorbed: int | None, win_tile: int) -> bool:
    """和了牌が両面待ちで順子に入ったか（平和の条件）。"""
    if absorbed is None:
        return False
    block = blocks[absorbed]
    if block.kind != BlockKind.RUN:
        return False
    position = win_tile - block.tile  # 0=下端, 1=中央, 2=上端
    if position == 1:
        return False  # 嵌張
    low, high = number_of(block.tile), number_of(block.tile) + 2
    if position == 0 and high == 9:
        return False  # 789 の 7 待ち = 辺張
    if position == 2 and low == 1:
        return False  # 123 の 3 待ち = 辺張
    return True


# --- 符計算 ----------------------------------------------------------------

BASE_FU = 20
MENZEN_RON_FU = 10
TSUMO_FU = 2
CHIITOITSU_FU = 25
OPEN_PINFU_FU = 30


def calculate_fu(ctx: WinContext, blocks: list[Block], absorbed: int | None, has_pinfu: bool) -> int:
    """符を計算する（標準的な日本麻雀通り）。"""
    menzen = ctx.hand.is_menzen
    if has_pinfu:
        # 平和ツモは20符固定、平和ロンは門前ロンの10符を足して30符
        return BASE_FU if ctx.is_tsumo else BASE_FU + MENZEN_RON_FU

    fu = BASE_FU
    if menzen and not ctx.is_tsumo:
        fu += MENZEN_RON_FU
    if ctx.is_tsumo:
        fu += TSUMO_FU

    for index, block in enumerate(blocks):
        if block.kind == BlockKind.PAIR:
            # 連風牌の雀頭も2符（天鳳などの標準に合わせる）
            if yakuhai_han(block.tile, ctx.seat_wind) > 0:
                fu += 2
            continue
        if block.kind == BlockKind.RUN:
            continue

        terminal = is_terminal_or_honor(block.tile)
        # ロンで完成した刻子は明刻扱い
        concealed = block.concealed and not (index == absorbed and not ctx.is_tsumo)
        if block.kind == BlockKind.TRIPLET:
            base = 4 if concealed else 2
        else:  # 槓子
            base = 16 if concealed else 8
        fu += base * 2 if terminal else base

    fu += _wait_fu(blocks, absorbed, ctx.win_tile)

    if not menzen and fu == BASE_FU:
        return OPEN_PINFU_FU  # 喰い平和形は30符

    return -(-fu // 10) * 10  # 10符単位に切り上げ


def _wait_fu(blocks: list[Block], absorbed: int | None, win_tile: int) -> int:
    """待ちの形による符。単騎・嵌張・辺張が2符。"""
    if absorbed is None:
        return 0
    block = blocks[absorbed]
    if block.kind == BlockKind.PAIR:
        return 2  # 単騎
    if block.kind != BlockKind.RUN:
        return 0  # シャンポン
    position = win_tile - block.tile
    if position == 1:
        return 2  # 嵌張
    low, high = number_of(block.tile), number_of(block.tile) + 2
    if (position == 0 and high == 9) or (position == 2 and low == 1):
        return 2  # 辺張
    return 0


# --- 評価 ------------------------------------------------------------------


def evaluate(ctx: WinContext) -> HandValue:
    """和了手を評価して、最も点数の高い解釈を返す。"""
    candidates: list[HandValue] = []

    special = _evaluate_special_shapes(ctx)
    if special is not None:
        candidates.append(special)

    for blocks in all_decompositions(ctx.hand):
        for absorbed in _absorb_candidates(blocks, ctx.win_tile):
            candidates.append(_evaluate_blocks(ctx, blocks, absorbed))

    if not candidates:
        return HandValue()

    return max(candidates, key=_ranking_key)


def _ranking_key(value: HandValue) -> tuple[int, int, int]:
    return (value.yakuman, value.han, value.fu)


def _non_riichi_extras(ctx: WinContext) -> list[Yaku]:
    """特殊役のうち、立直系でないもの（ベンツ・脊髄など）。

    フィーバー立直は立直への上乗せとして `_riichi_yaku` が翻数を決めるので、
    ここで二重に足さないよう取り除く。
    """
    return [y for y in ctx.extra_yaku if y.name not in FEVER_RIICHI_NAMES]


def _absorb_candidates(blocks: list[Block], win_tile: int) -> list[int | None]:
    """和了牌がどのブロックに入ったかの候補。

    複数のブロックに入りうる場合は全て試し、最も高くなる解釈を採る。
    """
    found: list[int | None] = [
        index for index, block in enumerate(blocks) if block.contains(win_tile)
    ]
    return found or [None]


def _evaluate_blocks(ctx: WinContext, blocks: list[Block], absorbed: int | None) -> HandValue:
    yakuman = _yakuman(ctx, blocks, absorbed) + _situational_yakuman(ctx)
    if yakuman:
        return HandValue(yaku=yakuman, yakuman=sum(y.yakuman for y in yakuman))

    yaku = _standard_yaku(ctx, blocks, absorbed) + _non_riichi_extras(ctx)
    has_pinfu = any(y.name == "平和" for y in yaku)
    fu = calculate_fu(ctx, blocks, absorbed, has_pinfu)
    breakdown = dora_breakdown(ctx)
    dora = breakdown.total
    yaku += breakdown.yaku()
    han = sum(y.han for y in yaku)
    return HandValue(yaku=yaku, fu=fu, han=han, dora=dora)


def _situational_yakuman(ctx: WinContext) -> list[Yaku]:
    found: list[Yaku] = []
    if ctx.is_tenhou:
        found.append(Yaku("天和", yakuman=1))
    if ctx.is_chiihou:
        found.append(Yaku("地和", yakuman=1))
    return found


def _evaluate_special_shapes(ctx: WinContext) -> HandValue | None:
    """七対子・国士無双・大車輪。面子分解できない形。"""
    counts = ctx.hand.concealed
    if ctx.hand.melds or not ctx.hand.is_menzen:
        return None

    if is_kokushi(counts):
        yaku = [Yaku("国士無双", yakuman=1)] + _situational_yakuman(ctx)  # 13面もシングル
        return HandValue(yaku=yaku, yakuman=sum(y.yakuman for y in yaku))

    if not is_chiitoitsu(counts):
        return None

    if all(counts[tile] == 2 for tile in DAISHARIN_TILES):
        yaku = [Yaku("大車輪", yakuman=1)] + _situational_yakuman(ctx)
        return HandValue(yaku=yaku, yakuman=sum(y.yakuman for y in yaku))

    situational = _situational_yakuman(ctx)
    if situational:
        return HandValue(yaku=situational, yakuman=sum(y.yakuman for y in situational))

    yaku: list[Yaku] = [Yaku("七対子", 2)]
    yaku += _chiitoitsu_extra_yaku(ctx, counts)
    yaku += _non_riichi_extras(ctx)
    breakdown = dora_breakdown(ctx)
    dora = breakdown.total
    yaku += breakdown.yaku()
    han = sum(y.han for y in yaku)
    return HandValue(yaku=yaku, fu=CHIITOITSU_FU, han=han, dora=dora)


def _chiitoitsu_extra_yaku(ctx: WinContext, counts: list[int]) -> list[Yaku]:
    """七対子と複合しうる役。"""
    found: list[Yaku] = []
    tiles = [tile for tile in range(NUM_KINDS) if counts[tile]]

    found.extend(_riichi_yaku(ctx))
    if ctx.is_ippatsu:
        found.append(Yaku("一発", 1))
    if ctx.is_tsumo:
        found.append(Yaku("門前清自摸和", 1))
    if ctx.is_haitei:
        found.append(Yaku("海底摸月", 1))
    if ctx.is_houtei:
        found.append(Yaku("河底撈魚", 1))
    if ctx.is_chankan:
        found.append(Yaku("槍槓", 1))

    if all(not is_terminal_or_honor(tile) for tile in tiles):
        found.append(Yaku("断幺九", 1))
    if all(is_terminal_or_honor(tile) for tile in tiles):
        found.append(Yaku("混老頭", 2))

    suits = {suit_of(tile) for tile in tiles}
    number_suits = suits - {"z"}
    if len(number_suits) == 1:
        if "z" in suits:
            found.append(Yaku("混一色", 2))
        else:
            found.append(Yaku("清一色", 6))

    return found
