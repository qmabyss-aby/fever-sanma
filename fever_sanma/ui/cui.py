"""ターミナル表示。

core は表示を知らないので、ここで整形だけを担当する。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.game import Action, ActionType, Phase, Round, RoundResult
from ..core.match import MatchResult
from ..core.tiles import PEI, format_ordered, format_tiles, tile_name
from ..core.yaku import RIICHI_EXTRA_NAMES, HandValue, is_dora_yaku

SEAT_LABELS = ("東家", "南家", "西家")

ACTION_LABELS = {
    ActionType.DISCARD: "打",
    ActionType.RIICHI: "立直",
    ActionType.OPEN_RIICHI: "オープン立直",
    ActionType.TSUMO: "ツモ",
    ActionType.RON: "ロン",
    ActionType.PON: "ポン",
    ActionType.CHI: "チー",
    ActionType.MINKAN: "大明槓",
    ActionType.KAKAN: "加槓",
    ActionType.ANKAN: "暗槓",
    ActionType.KITA: "北抜き",
    ActionType.KYUUSHU: "九種九牌",
    ActionType.PASS: "パス",
}


def seat_label(seat: int, dealer: int, wareme: int) -> str:
    marks = []
    if seat == dealer:
        marks.append("親")
    if seat == wareme:
        marks.append("割れ目")
    suffix = f"[{'/'.join(marks)}]" if marks else ""
    return f"{SEAT_LABELS[seat]}{suffix}"


def format_action(action: Action) -> str:
    label = ACTION_LABELS.get(action.type, action.type.value)
    if action.tile is None:
        return label
    if action.type is ActionType.CHI:
        run = format_tiles([action.tile, action.tile + 1, action.tile + 2])
        return f"{label} {run}"
    return f"{label} {tile_name(action.tile)}"


def format_hand(game: Round, seat: int, reveal: bool = True) -> str:
    """手牌の表示。

    reveal=False でも **副露と抜きドラは隠さない**。どちらも場に晒されている
    公開情報なので、伏せてしまうと他家の状況が読めなくなる。
    """
    player = game.players[seat]
    total = sum(player.hand.concealed)

    parts: list[str] = []
    if reveal:
        # ツモ牌は手牌から切り離して見せる（麻雀の通常の並べ方）
        counts = list(player.hand.concealed)
        if player.drawn_tile is not None and counts[player.drawn_tile]:
            counts[player.drawn_tile] -= 1
        parts.append(format_tiles(from_counts(counts)))
        if player.drawn_tile is not None:
            parts.append(f"+ ツモ {tile_name(player.drawn_tile)}")
        parts.append(f"(計{total}枚)")
    else:
        parts.append(f"（伏せ {total}枚）")

    for meld in player.hand.melds:
        parts.append(f"[{ACTION_LABELS[_meld_action(meld)]} {format_tiles(meld.tiles)}]")
    if player.hand.kita:
        parts.append(f"(北抜き{player.hand.kita})")
    return "  ".join(parts)


def _meld_action(meld) -> ActionType:
    from ..core.hand import MeldType

    return {
        MeldType.CHI: ActionType.CHI,
        MeldType.PON: ActionType.PON,
        MeldType.MINKAN: ActionType.MINKAN,
        MeldType.KAKAN: ActionType.KAKAN,
        MeldType.ANKAN: ActionType.ANKAN,
    }[meld.type]


def from_counts(counts):
    from ..core.tiles import from_counts as _from_counts

    return _from_counts(counts)


def render_table(game: Round, viewer: int | None = None) -> str:
    """卓の状況。viewer を指定すると、その席以外の手牌は伏せる。"""
    lines: list[str] = []
    lines.append(
        f"残り{game.wall.remaining}枚  "
        f"ドラ表示 {format_ordered(game.wall.dora_indicators())}  "
        f"供託 {game.riichi_sticks}"
    )
    if game.fever_seat is not None:
        lines.append(
            f"★ フィーバー中（{SEAT_LABELS[game.fever_seat]} / {game.fever_yaku.name}）"
            f" 待ち {format_tiles(sorted(game.fever_waits))}"
        )
    for seat in range(len(game.players)):
        player = game.players[seat]
        header = f"{seat_label(seat, game.dealer, game.wareme)} {player.score:>6}点"
        if player.riichi:
            header += " 立直"
        # フィーバー中はリーチ者の手牌を全公開する（CLAUDE.md §4.5）
        revealed = seat == viewer or viewer is None or seat == game.fever_seat
        lines.append(f"{header}  {format_hand(game, seat, reveal=revealed)}")
        # 河は捨てた順に意味があるので並べ替えない
        lines.append(f"    河: {format_ordered(player.discards)}")
    return "\n".join(lines)


def format_yaku(yaku) -> str:
    """役1つの表示。

    立直への上乗せぶん（ダブル立直・フィーバー立直など）は「+N翻」と出す。
    これらは通常の立直1翻を土台にした加算なので、そう書かないと
    「フィーバー立直は2翻のはずなのに1翻と出ている」と読めてしまう。
    """
    if yaku.yakuman or is_dora_yaku(yaku.name):
        return yaku.name  # ドラ系は「ドラ2」「裏ドラ1」のように枚数だけで分かる
    sign = "+" if yaku.name in RIICHI_EXTRA_NAMES else ""
    return f"{yaku.name}({sign}{yaku.han}翻)"


def format_value(value: HandValue) -> str:
    yaku = " / ".join(format_yaku(y) for y in value.yaku)
    if value.yakuman:
        return f"{yaku}  → 役満×{value.yakuman}"
    return f"{yaku}  → {value.han}翻{value.fu}符"


def render_round_result(result: RoundResult) -> str:
    lines: list[str] = []
    match result.kind:
        case "win":
            for seat in result.winners:
                lines.append(f"{SEAT_LABELS[seat]} 和了")
                # フィーバーの局は和了が何回もあるので、下の内訳一覧に任せる
                if seat in result.values and not result.fever_wins:
                    lines.append(f"  {format_value(result.values[seat])}")
            if result.fever_wins:
                lines.append(f"  フィーバー和了 {len(result.fever_wins)}回")
                for win in result.fever_wins:
                    kind = "ツモ" if win.is_tsumo else "ロン"
                    lines.append(f"    {kind} {tile_name(win.win_tile)}  {format_value(win.value)}")
        case "draw":
            tenpai = "、".join(SEAT_LABELS[s] for s in result.tenpai) or "なし"
            lines.append(f"流局（テンパイ: {tenpai}）")
        case "abort":
            lines.append(f"途中流局: {result.abort_reason}")
    if result.ura_indicators:
        lines.append(
            "  裏ドラ表示: " + " ".join(tile_name(tile) for tile in result.ura_indicators)
        )
    deltas = result.payments.deltas
    if deltas:
        moves = "  ".join(
            f"{SEAT_LABELS[s]} {deltas[s]:+,}" for s in sorted(deltas) if deltas[s]
        )
        lines.append(f"  {moves}")
    return "\n".join(lines)


def render_match_result(result: MatchResult) -> str:
    lines = [f"終局（{result.ended_by}）"]
    for rank, seat in enumerate(result.ranking, start=1):
        lines.append(
            f"  {rank}位 {SEAT_LABELS[seat]}  素点 {result.scores[seat]:>7,}  "
            f"最終 {result.final[seat]:>+8,}"
        )
    return "\n".join(lines)


DISCARD_TYPES = (ActionType.DISCARD, ActionType.RIICHI, ActionType.OPEN_RIICHI)


@dataclass(frozen=True, slots=True)
class MenuEntry:
    """メニュー1行。action が None の行は選べない（喰い替えで切れない牌など）。"""

    label: str
    action: Action | None = None
    note: str = ""
    tile: int | None = None

    @property
    def selectable(self) -> bool:
        return self.action is not None


def tile_order(game: Round, seat: int) -> list[tuple[int, bool]]:
    """手牌を1枚ずつ並べる。**ツモ牌が必ず先頭**。

    戻り値は (牌, ツモ牌か) の並び。ルールエンジン側の選択肢は「牌の種類」単位で
    重複しないが、人が選ぶときは手牌の枚数どおりに並んでいるほうが分かりやすい。
    """
    player = game.players[seat]
    counts = list(player.hand.concealed)
    order: list[tuple[int, bool]] = []
    drawn = player.drawn_tile
    if drawn is not None and counts[drawn]:
        counts[drawn] -= 1
        order.append((drawn, True))
    for tile in range(len(counts)):
        order.extend([(tile, False)] * counts[tile])
    return order


def build_menu(game: Round, seat: int, options: list[Action]) -> list[MenuEntry]:
    """選択肢を人が選びやすい形に組み直す。

    - 打牌は手牌の枚数どおり1枚ずつ並べ、0番をツモ牌にする
    - 立直は番号を占有せず、牌を選んだあとに聞く（`riichi_choices` を使う）
    - 打牌以外（ツモ・カン・北抜き・鳴きなど）は打牌のうしろに続ける
    """
    discards = {a.tile: a for a in options if a.type is ActionType.DISCARD}
    riichi_tiles = {a.tile for a in options if a.type in DISCARD_TYPES[1:]}
    kita = next((a for a in options if a.type is ActionType.KITA), None)
    others = [
        a
        for a in options
        if a.type not in DISCARD_TYPES and a.type is not ActionType.KITA
    ]

    entries: list[MenuEntry] = []
    if discards:
        for tile, is_drawn in tile_order(game, seat):
            action = discards.get(tile)
            notes = []
            if action is None:
                notes.append("喰い替えで切れない")
            if tile in riichi_tiles:
                notes.append("立直可")
            # 北抜きは独立した行にせず、北の行を選んだあとに聞く。
            # 別行にすると「北」と「北抜き 北」が離れた番号に並んで紛らわしい。
            if kita is not None and tile == PEI:
                notes.append("抜きドラ可")
            label = tile_name(tile) + ("（ツモ牌）" if is_drawn else "")
            entries.append(MenuEntry(label, action or kita, " / ".join(notes), tile))
    elif kita is not None:
        others.insert(0, kita)

    entries.extend(MenuEntry(format_action(action), action) for action in others)
    return entries


def kita_choice(options: list[Action], tile: int) -> Action | None:
    """その牌が北で、抜きドラにできる場合の北抜きアクション。"""
    if tile != PEI:
        return None
    return next((a for a in options if a.type is ActionType.KITA), None)


def riichi_choices(options: list[Action], tile: int) -> list[Action]:
    """その牌を切って立直できる場合の選択肢（通常立直・オープン立直）。"""
    return [a for a in options if a.type in DISCARD_TYPES[1:] and a.tile == tile]


def render_menu(game: Round, seat: int, entries: list[MenuEntry]) -> str:
    lines = [render_table(game, viewer=seat), ""]
    if game.phase is Phase.REACTION:
        lines.append(f"→ {tile_name(game.last_discard)} に対して:")

    width = len(str(len(entries) - 1))
    for index, entry in enumerate(entries):
        if entry.selectable:
            number = f"{index:>{width}}"
        else:
            number = "-" * width  # 選べない行は番号を出さない
        note = f"  ({entry.note})" if entry.note else ""
        lines.append(f"  {number}: {entry.label}{note}")
    return "\n".join(lines)
