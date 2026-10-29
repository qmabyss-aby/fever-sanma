"""強い CPU。

ランダム打ちと同じ `choose(game, seat, options)` を実装しているので差し替えるだけで使える。
**見えている情報しか使わない**（自分の手牌・全員の河・副露・抜きドラ・ドラ表示牌、
それに公開されている手牌＝オープン立直者とフィーバー者の手）。山や他家の伏せた手は覗かない。

方針（このルールならではの点を含む）:

- 牌効率: 向聴数を最優先し、次に有効牌の残り枚数が多い牌を残す。
- 二翻縛り: 通常の立直は「立直＋ロン」だけだと1翻で上がれないことが多い。
  ロンで上がれない待ちなら **オープン立直**（他家のロンなら13翻）を選ぶ。
  ツモなら立直＋門前清自摸和で2翻になるので、立直そのものは常に上がりがある。
- 鳴き: 一度鳴いたら **脊髄**（4副露の裸単騎で13翻）を目指して鳴き進める。
  門前のうちは、手が遠い・役牌のポン・混一色／対々和寄り、のときだけ最初に鳴く。
- 守備: 立直者がいて自分の手が遠ければベタオリ（現物 → 筋 → 見えている字牌）。
  自分か立直者が割れ目なら失点が3倍になるので、1向聴でもオリる。
  オープン立直者の待ちは見えているので、その牌は絶対に切らない（放銃は13翻）。
- このルール特有の価値: 8索のカン（ベンツ）は必ずする。7筒・7索の対子（フィーバーの種）と
  常時ドラ（1萬・9萬・北）は残しやすくする。北は手を崩さないなら抜く。
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from ..core import yaku_special
from ..core.game import Action, ActionType, Phase, Round
from ..core.hand import Hand, Meld, MeldType
from ..core.shanten import shanten, waits
from ..core.tiles import (
    NUM_KINDS,
    PEI,
    PERMANENT_DORA,
    TERMINALS_AND_HONORS,
    dora_from_indicator,
    is_honor,
    number_of,
    pin,
    sou,
    suit_of,
)
from ..core.yaku import WinContext, evaluate, yakuhai_han

FOLD_SHANTEN = 2
"""立直者がいるとき、この向聴数以上ならベタオリする。"""

LATE_FOLD_REMAINING = 15
"""山がこれ以下なら、1向聴でもベタオリする。"""

MIN_RIICHI_REMAINING = 4
"""山がこれより少ないと立直しない（ツモ番がほぼ無いので1,000点を払う意味が薄い）。"""

FAR_SHANTEN = 3
"""門前でこれ以上遠ければ、最初の鳴きを入れて脊髄を狙う。"""

KOKUSHI_KINDS = 11
"""么九牌がこれ以上あれば九種九牌で流さず国士無双を狙う。"""

NEVER = 10_000
"""オープン立直者の待ち牌など、絶対に切らない牌の危険度。"""

BENZ_TILE = sou(8)
FEVER_TILES = (pin(7), sou(7))


class StrongAgent:
    """牌効率・押し引き・このルール特有の役を考えて打つ CPU。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    # --- 入口 --------------------------------------------------------------

    def choose(self, game: Round, seat: int, options: list[Action]) -> Action:
        for action in options:
            if action.type in (ActionType.TSUMO, ActionType.RON):
                return action  # エンジンは二翻縛りを満たすときしか和了を出さない
        if len(options) == 1:
            return options[0]
        if game.phase is Phase.REACTION:
            return self._react(game, seat, options)
        return self._turn(game, seat, options)

    # --- 手番 --------------------------------------------------------------

    def _turn(self, game: Round, seat: int, options: list[Action]) -> Action:
        player = game.players[seat]
        visible = visible_counts(game, seat)
        threats = self._threats(game, seat)

        kyuushu = _first(options, ActionType.KYUUSHU)
        if kyuushu is not None:
            kinds = sum(1 for t in TERMINALS_AND_HONORS if player.hand.concealed[t])
            if kinds < KOKUSHI_KINDS:
                return kyuushu

        discards = [a for a in options if a.type is ActionType.DISCARD]
        scored = {a.tile: self._discard_score(game, seat, a.tile, visible) for a in discards}
        best_shanten = min((s[0] for s in scored.values()), default=99)
        folding = self._should_fold(game, seat, threats, best_shanten)

        # 8索のカンはベンツ（2翻＋ドラ×3）。待ちを崩しても見返りが大きい。
        for kind in (ActionType.ANKAN, ActionType.KAKAN):
            for action in options:
                if action.type is kind and action.tile == BENZ_TILE:
                    return action
        if not folding:
            for action in options:
                if action.type in (ActionType.ANKAN, ActionType.KAKAN):
                    if _after_kan_shanten(player.hand, action) <= best_shanten:
                        return action

        kita = _first(options, ActionType.KITA)
        if kita is not None:
            probe = player.hand.copy()
            probe.remove(PEI)
            # 北を抜いても手が進まなくならないなら抜く（ドラ1枚＋嶺上牌が増える）
            if shanten(probe) <= best_shanten:
                return kita

        if not discards:
            return options[0]

        danger = {tile: self._danger(game, seat, tile, threats, visible) for tile in scored}
        if folding:
            tile = min(scored, key=lambda t: (danger[t], scored[t][0], -scored[t][1]))
        else:
            # 押すときも、オープン立直者の待ち（放銃すると13翻）だけは最後まで切らない
            tile = min(
                scored,
                key=lambda t: (
                    danger[t] >= NEVER,
                    scored[t][0],
                    -scored[t][1],
                    scored[t][2],
                    danger[t],
                ),
            )

        if not folding and scored[tile][0] == 0:
            riichi = self._riichi_action(game, seat, options, tile)
            if riichi is not None:
                return riichi
        return next(a for a in discards if a.tile == tile)

    def _discard_score(
        self, game: Round, seat: int, tile: int, visible: Sequence[int]
    ) -> tuple[int, int, int]:
        """(切った後の向聴数, 有効牌の残り枚数, 残す価値)。"""
        hand = game.players[seat].hand.copy()
        hand.remove(tile)
        current = shanten(hand)
        return current, ukeire_count(hand, current, visible), self._keep_value(game, seat, tile)

    def _keep_value(self, game: Round, seat: int, tile: int) -> int:
        """手に残しておきたい度合い。大きいほど切りたくない。"""
        hand = game.players[seat].hand
        count = hand.concealed[tile]
        value = 0
        dora = [dora_from_indicator(i) for i in game.wall.dora_indicators()]
        if tile in PERMANENT_DORA:
            value += 2
        value += 2 * dora.count(tile)
        if tile in FEVER_TILES and count >= 2:
            value += 3  # 3枚そろえば確定暗刻でフィーバー立直の種
        if tile == BENZ_TILE and count >= 3:
            value += 3  # 4枚目を引けばベンツ
        if count >= 2 and yakuhai_han(tile, game.players[seat].seat_wind):
            value += 2
        if is_honor(tile) and count == 1 and not yakuhai_han(tile, game.players[seat].seat_wind):
            value -= 1  # 役にならない孤立字牌は真っ先に切る
        return value

    def _riichi_action(
        self, game: Round, seat: int, options: list[Action], tile: int
    ) -> Action | None:
        if game.wall.remaining < MIN_RIICHI_REMAINING:
            return None
        plain = next((a for a in options if a.type is ActionType.RIICHI and a.tile == tile), None)
        open_ = next(
            (a for a in options if a.type is ActionType.OPEN_RIICHI and a.tile == tile), None
        )
        if plain is None:
            return open_
        if open_ is not None and not self._plain_riichi_can_ron(game, seat, tile):
            # 普通の立直では二翻縛りでロンできない待ち → オープン立直ならロンで13翻
            return open_
        return plain

    def _plain_riichi_can_ron(self, game: Round, seat: int, discard: int) -> bool:
        player = game.players[seat]
        hand = player.hand.copy()
        hand.remove(discard)
        for wait in waits(hand):
            probe = hand.copy()
            probe.add(wait)
            ctx = WinContext(
                hand=probe,
                win_tile=wait,
                is_tsumo=False,
                seat_wind=player.seat_wind,
                is_riichi=True,
                dora_indicators=tuple(game.wall.dora_indicators()),
                extra_yaku=yaku_special.extra_yaku_for_win(probe),
                dora_multiplier=yaku_special.dora_multiplier(probe),
            )
            if evaluate(ctx).satisfies_binding:
                return True
        return False

    # --- 鳴き --------------------------------------------------------------

    def _react(self, game: Round, seat: int, options: list[Action]) -> Action:
        pass_action = _first(options, ActionType.PASS) or options[0]
        player = game.players[seat]
        tile = game.last_discard
        if player.riichi:
            return pass_action
        before = shanten(player.hand)
        if self._threats(game, seat) and before >= 1:
            return pass_action  # 立直者がいるのに手が遠ければ鳴いて前に出ない

        best: tuple[tuple[int, int], Action] | None = None
        for action in options:
            if action.type not in (ActionType.PON, ActionType.CHI, ActionType.MINKAN):
                continue
            after = _after_call(player.hand, action, tile)
            if action.type is ActionType.MINKAN:
                # 大明槓のあとは嶺上牌を引くので、その時点の手の形で比べる
                if tile == BENZ_TILE:
                    return action  # ベンツ
                if player.hand.open_meld_count and shanten(after) <= before:
                    candidate = (shanten(after), 1)
                else:
                    continue
            else:
                after_shanten = _best_discard_shanten(after, forbidden={tile})
                if after_shanten >= before:
                    continue
                if not self._worth_opening(game, seat, action, tile, before):
                    continue
                candidate = (after_shanten, 0)
            if best is None or candidate < best[0]:
                best = (candidate, action)
        return best[1] if best is not None else pass_action

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

    # --- 押し引き ----------------------------------------------------------

    def _threats(self, game: Round, seat: int) -> list[int]:
        return [
            other
            for other, player in enumerate(game.players)
            if other != seat and player.riichi
        ]

    def _should_fold(
        self, game: Round, seat: int, threats: list[int], best_shanten: int
    ) -> bool:
        if not threats:
            return False
        if best_shanten >= FOLD_SHANTEN:
            return True
        if best_shanten != 1:
            return False
        # 自分か立直者が割れ目なら、放銃したときの失点が3倍になる（CLAUDE.md §4.9）
        wareme_involved = seat == game.wareme or game.wareme in threats
        return wareme_involved or game.wall.remaining <= LATE_FOLD_REMAINING

    def _danger(
        self, game: Round, seat: int, tile: int, threats: list[int], visible: Sequence[int]
    ) -> int:
        """その牌を切ったときの放銃しやすさ。0 が安全。"""
        total = 0
        for other in threats:
            player = game.players[other]
            if player.open_riichi or other == game.fever_seat:
                # 手牌が公開されている → 待ちが正確に分かる
                if tile in waits(player.hand):
                    total += NEVER
                continue
            if tile in player.discards:
                continue  # 現物（フリテンなのでロンされない）
            total += _base_danger(tile, player.discards, visible)
        return total


# --- 補助 ------------------------------------------------------------------


def visible_counts(game: Round, seat: int) -> list[int]:
    """seat から見えている牌の枚数。山や他家の伏せた手は含めない。"""
    counts = [0] * NUM_KINDS
    for tile in game.players[seat].hand.all_tiles():
        counts[tile] += 1
    for other, player in enumerate(game.players):
        for tile in player.discards:
            counts[tile] += 1
        counts[PEI] += player.hand.kita
        if other != seat:
            for meld in player.hand.melds:
                for tile in meld.tiles:
                    counts[tile] += 1
    for tile in game.wall.dora_indicators():
        counts[tile] += 1
    return [min(count, 4) for count in counts]


def ukeire_count(hand: Hand, current: int, visible: Sequence[int]) -> int:
    """有効牌の残り枚数（見えている枚数を差し引く）。

    14枚の向聴数は「1枚切った後の最良の向聴数」と同じになるので、
    引いた後に何を切るかを全部試さなくてよい。
    """
    total = 0
    for tile in range(NUM_KINDS):
        remaining = 4 - visible[tile]
        if remaining <= 0:
            continue
        hand.add(tile)
        improved = shanten(hand) < current
        hand.remove(tile)
        if improved:
            total += remaining
    return total


def _base_danger(tile: int, discards: Sequence[int], visible: Sequence[int]) -> int:
    if is_honor(tile):
        unseen = 4 - visible[tile]
        return (0, 1, 3, 4, 4)[unseen]
    number = number_of(tile)
    if suit_of(tile) == "m":
        return 3  # 1萬・9萬は順子にならないので単騎・シャンポンしかない
    danger = 4 if number in (1, 9) else 6 if number in (2, 8) else 8
    low_suji = tile - 3 if number >= 4 else None
    high_suji = tile + 3 if number <= 6 else None
    sides = [s for s in (low_suji, high_suji) if s is not None]
    if sides and all(s in discards for s in sides):
        danger //= 2  # 筋
    return danger


def _first(options: list[Action], kind: ActionType) -> Action | None:
    return next((a for a in options if a.type is kind), None)


def _after_call(hand: Hand, action: Action, tile: int) -> Hand:
    after = hand.copy()
    if action.type is ActionType.PON:
        for _ in range(2):
            after.remove(tile)
        after.melds.append(Meld(MeldType.PON, tile, action.from_seat, tile))
    elif action.type is ActionType.CHI:
        for offset in range(3):
            if action.tile + offset != tile:
                after.remove(action.tile + offset)
        after.melds.append(Meld(MeldType.CHI, action.tile, action.from_seat, tile))
    elif action.type is ActionType.MINKAN:
        for _ in range(3):
            after.remove(tile)
        after.melds.append(Meld(MeldType.MINKAN, tile, action.from_seat, tile))
    return after


def _best_discard_shanten(hand: Hand, forbidden: set[int]) -> int:
    best = 99
    for tile in range(NUM_KINDS):
        if hand.concealed[tile] and tile not in forbidden:
            hand.remove(tile)
            best = min(best, shanten(hand))
            hand.add(tile)
    return best


def _after_kan_shanten(hand: Hand, action: Action) -> int:
    after = hand.copy()
    if action.type is ActionType.ANKAN:
        for _ in range(4):
            after.remove(action.tile)
        after.melds.append(Meld(MeldType.ANKAN, action.tile))
    else:
        after.remove(action.tile)
        after.melds = [
            Meld(MeldType.KAKAN, m.tile, m.called_from, m.called_tile)
            if m.type is MeldType.PON and m.tile == action.tile
            else m
            for m in after.melds
        ]
    return shanten(after)

