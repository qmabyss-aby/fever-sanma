"""牌の表現と牌種定義。

フィーバー三麻の使用牌は通常の麻雀と異なり、**萬子は 1m と 9m のみ**存在する。

    萬子: 1m, 9m               (2種)
    筒子: 1p 〜 9p             (9種)
    索子: 1s 〜 9s             (9種)
    字牌: 東 南 西 北 白 發 中  (7種)

合計 **27種 × 4枚 = 108枚**。

内部表現は 0〜26 の int インデックス。手牌は長さ 27 の枚数配列（counts）で持つ。
面子分解・向聴計算を素直に書けるようにするためで、表示や入出力には `Tile` を使う。

    0      : 1m
    1      : 9m
    2 〜 10: 1p 〜 9p
    11〜 19: 1s 〜 9s
    20〜 26: 東 南 西 北 白 發 中  (1z 〜 7z)
"""

from __future__ import annotations

from dataclasses import dataclass

# --- 基本定数 --------------------------------------------------------------

NUM_KINDS = 27
"""牌の種類数。通常麻雀の34種ではなく、萬子が2種しかないので27種。"""

TILES_PER_KIND = 4
TOTAL_TILES = NUM_KINDS * TILES_PER_KIND  # 108

SUITS = ("m", "p", "s", "z")

MAN_NUMBERS = (1, 9)
"""萬子に存在する数字。フィーバー三麻では 2m〜8m は使わない。"""

# --- インデックス割当 ------------------------------------------------------

M1 = 0
M9 = 1
P1 = 2  # P1 + (n - 1) で n筒
S1 = 11  # S1 + (n - 1) で n索
Z1 = 20  # Z1 + (n - 1) で n字牌

TON = Z1 + 0  # 東 (1z)
NAN = Z1 + 1  # 南 (2z)
SHA = Z1 + 2  # 西 (3z)
PEI = Z1 + 3  # 北 (4z)
HAKU = Z1 + 4  # 白 (5z)
HATSU = Z1 + 5  # 發 (6z)
CHUN = Z1 + 6  # 中 (7z)

WINDS = (TON, NAN, SHA, PEI)
DRAGONS = (HAKU, HATSU, CHUN)
HONORS = WINDS + DRAGONS


def man(number: int) -> int:
    """萬子のインデックス。1 と 9 以外は使用牌に存在しないのでエラー。"""
    if number == 1:
        return M1
    if number == 9:
        return M9
    raise ValueError(f"フィーバー三麻に {number}m は存在しない（萬子は1と9のみ）")


def pin(number: int) -> int:
    """筒子のインデックス。"""
    if not 1 <= number <= 9:
        raise ValueError(f"{number}p は存在しない")
    return P1 + number - 1


def sou(number: int) -> int:
    """索子のインデックス。"""
    if not 1 <= number <= 9:
        raise ValueError(f"{number}s は存在しない")
    return S1 + number - 1


def honor(number: int) -> int:
    """字牌のインデックス（1z=東 … 7z=中）。"""
    if not 1 <= number <= 7:
        raise ValueError(f"{number}z は存在しない")
    return Z1 + number - 1


def index_of(suit: str, number: int) -> int:
    """スートと数字からインデックスを得る。"""
    match suit:
        case "m":
            return man(number)
        case "p":
            return pin(number)
        case "s":
            return sou(number)
        case "z":
            return honor(number)
        case _:
            raise ValueError(f"不明なスート: {suit!r}")


def suit_of(index: int) -> str:
    """インデックスのスートを返す。"""
    _check_index(index)
    if index <= M9:
        return "m"
    if index < S1:
        return "p"
    if index < Z1:
        return "s"
    return "z"


def number_of(index: int) -> int:
    """インデックスの数字を返す（字牌は 1〜7）。"""
    _check_index(index)
    if index == M1:
        return 1
    if index == M9:
        return 9
    if index < S1:
        return index - P1 + 1
    if index < Z1:
        return index - S1 + 1
    return index - Z1 + 1


def _check_index(index: int) -> None:
    if not 0 <= index < NUM_KINDS:
        raise ValueError(f"牌インデックスが範囲外: {index}")


# --- 牌の集合 --------------------------------------------------------------

TERMINALS = (M1, M9, pin(1), pin(9), sou(1), sou(9))
"""老頭牌（一九牌）。萬子は1m/9mしかないので全ての萬子が老頭牌。"""

TERMINALS_AND_HONORS = frozenset(TERMINALS + HONORS)
"""么九牌。チャンタ・混老頭・国士無双・九種九牌・流し満貫の判定に使う。全13種。"""

SIMPLES = frozenset(i for i in range(NUM_KINDS) if i not in TERMINALS_AND_HONORS)
"""中張牌（タンヤオ牌）。2p〜8p と 2s〜8s の14種。"""

GREEN_TILES = frozenset({sou(2), sou(3), sou(4), sou(6), sou(8), HATSU})
"""緑一色の構成牌。鳴きOK（CLAUDE.md §4.4）。"""

DAISHARIN_TILES = frozenset(pin(n) for n in range(2, 9))
"""大車輪の構成牌（2p〜8p）。これを2枚ずつ、鳴き不可。"""

CHUREN_SUITS = ("p", "s")
"""九蓮宝燈が成立しうるスート。萬子は1と9しかないので不可。"""

PERMANENT_DORA = frozenset({M1, M9, PEI})
"""常にドラ（CLAUDE.md §4.1）。1m・9m・北はドラ表示牌に関係なく常時ドラ。"""


def is_terminal_or_honor(index: int) -> bool:
    return index in TERMINALS_AND_HONORS


def is_honor(index: int) -> bool:
    return index >= Z1


def is_simple(index: int) -> bool:
    return index in SIMPLES


def can_form_run(index: int) -> bool:
    """この牌を起点に順子（index, index+1, index+2）を作れるか。

    萬子は 1m と 9m しかないので順子を作れない。
    """
    if index < P1 or index >= Z1:
        return False
    return number_of(index) <= 7


# --- ドラ表示牌 → ドラ ----------------------------------------------------


def dora_from_indicator(indicator: int) -> int:
    """ドラ表示牌から実際のドラ牌を求める。

    - 筒子・索子: 9 の次は 1 に戻る
    - 風牌: 東→南→西→北→東
    - 三元牌: 白→發→中→白
    - 萬子: 1m と 9m しか存在しないので 1m↔9m で循環させる
      （Wiki に記載がないローカル判断。1m/9m はどのみち常時ドラなので、
        この場合は「ダブドラ」になる扱い。CLAUDE.md §4.3 の西→北と同じ考え方。）
    """
    _check_index(indicator)
    if indicator == M1:
        return M9
    if indicator == M9:
        return M1
    if indicator in WINDS:
        return WINDS[(WINDS.index(indicator) + 1) % len(WINDS)]
    if indicator in DRAGONS:
        return DRAGONS[(DRAGONS.index(indicator) + 1) % len(DRAGONS)]
    number = number_of(indicator)
    base = P1 if indicator < S1 else S1
    return base + (number % 9)


# --- Tile（表示・入出力用） -----------------------------------------------

_HONOR_NAMES = ("東", "南", "西", "北", "白", "發", "中")
_SUIT_NAMES = {"m": "萬", "p": "筒", "s": "索"}


@dataclass(frozen=True, slots=True)
class Tile:
    """表示・入出力用の牌。内部計算では int インデックスを使う。"""

    suit: str
    number: int

    def __post_init__(self) -> None:
        index_of(self.suit, self.number)  # バリデーション

    @property
    def index(self) -> int:
        return index_of(self.suit, self.number)

    @classmethod
    def from_index(cls, index: int) -> Tile:
        return cls(suit_of(index), number_of(index))

    def __str__(self) -> str:
        return f"{self.number}{self.suit}"

    @property
    def name_ja(self) -> str:
        """日本語表記（"1萬", "東" など）。"""
        if self.suit == "z":
            return _HONOR_NAMES[self.number - 1]
        return f"{self.number}{_SUIT_NAMES[self.suit]}"


def tile_name(index: int) -> str:
    """インデックスの日本語表記。"""
    return Tile.from_index(index).name_ja


def tile_str(index: int) -> str:
    """インデックスの短縮表記（"1m", "7p", "4z"）。"""
    return f"{number_of(index)}{suit_of(index)}"


# --- パース / フォーマット -------------------------------------------------


def parse_tiles(notation: str) -> list[int]:
    """麻雀の標準表記をインデックスのリストに変換する。

    数字を並べてスート文字で閉じる。空白は無視される。

        >>> parse_tiles("19m 123p 777s 11z")
        [0, 1, 2, 3, 4, 17, 17, 17, 20, 20]

    戻り値はソート済み。
    """
    tiles: list[int] = []
    pending: list[int] = []
    for char in notation:
        if char.isspace() or char == ",":
            continue
        if char.isdigit():
            pending.append(int(char))
        elif char in SUITS:
            if not pending:
                raise ValueError(f"スート {char!r} の前に数字がない: {notation!r}")
            tiles.extend(index_of(char, n) for n in pending)
            pending.clear()
        else:
            raise ValueError(f"解釈できない文字 {char!r}: {notation!r}")
    if pending:
        raise ValueError(f"末尾の数字にスートが付いていない: {notation!r}")
    return sorted(tiles)


def format_tiles(tiles: list[int]) -> str:
    """インデックスのリストを標準表記に戻す（parse_tiles の逆）。**昇順に並べ替える**。

    手牌のように順序に意味がないものに使う。河のように **捨てた順** を保ちたい
    ものには `format_ordered` を使うこと。
    """
    return format_ordered(sorted(tiles))


def format_ordered(tiles: list[int]) -> str:
    """並び順を保ったまま標準表記にする。

    河（捨てた順）やドラ表示牌（めくった順）のように、順序そのものが情報である
    ものに使う。並べ替えてしまうと「何を何番目に切ったか」が読めなくなる。
    """
    if not tiles:
        return ""
    parts: list[str] = []
    current_suit = ""
    digits: list[str] = []
    for index in tiles:
        suit = suit_of(index)
        if suit != current_suit:
            if digits:
                parts.append("".join(digits) + current_suit)
                digits = []
            current_suit = suit
        digits.append(str(number_of(index)))
    parts.append("".join(digits) + current_suit)
    return " ".join(parts)


# --- 枚数配列 --------------------------------------------------------------


def empty_counts() -> list[int]:
    """長さ27のゼロ埋め枚数配列。"""
    return [0] * NUM_KINDS


def to_counts(tiles: list[int]) -> list[int]:
    """インデックスのリストを枚数配列に変換する。"""
    counts = empty_counts()
    for index in tiles:
        _check_index(index)
        counts[index] += 1
        if counts[index] > TILES_PER_KIND:
            raise ValueError(f"{tile_str(index)} が5枚以上ある")
    return counts


def from_counts(counts: list[int]) -> list[int]:
    """枚数配列をインデックスのリストに戻す（昇順）。"""
    tiles: list[int] = []
    for index, count in enumerate(counts):
        tiles.extend([index] * count)
    return tiles


def counts_of(notation: str) -> list[int]:
    """標準表記から直接、枚数配列を作る。テストで使う近道。"""
    return to_counts(parse_tiles(notation))


def build_full_set() -> list[int]:
    """108枚の全牌を作る（未シャッフル、昇順）。"""
    tiles: list[int] = []
    for index in range(NUM_KINDS):
        tiles.extend([index] * TILES_PER_KIND)
    return tiles
