"""脊髄狙いの CPU（鳴き特化）。

`StrongAgent` を土台に、鳴きと打牌の方針だけを差し替えている。和了の取り方、
押し引き（危険度）、北抜きの判断などは共通。

脊髄は「4副露して裸単騎」（13翻 / CLAUDE.md §4.5）。普通の手作りとは考え方が逆になる:

- 手の内で完成した面子（暗刻・順子）は**鳴けないので役に立たない**。
  欲しいのは「鳴ける形」＝ 対子（ポン）・刻子（大明槓）・両面／嵌張（上家からチー）。
- 対子でも、残りの牌が全部見えていたらもう鳴けない（死に対子）。
- **暗槓は副露に数えない**ので脊髄が消える。暗槓はしない（8索でも）。
  加槓・大明槓は副露のままなのでする（8索ならベンツも乗る）。
- 4副露したら、残り枚数の多い牌を単騎待ちに残す。
- 立直を受けて、脊髄まであと2回以上鳴く必要があるならオリる（間に合わない）。
- 門前で1向聴以内なら、脊髄を目指すより立直のほうが速いので `StrongAgent` に任せる。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.game import Action, ActionType, Round
from ..core.hand import Hand
from ..core.shanten import shanten
from ..core.tiles import NUM_KINDS, P1, PEI, Z1, number_of
from .strong_ai import StrongAgent, _after_call, _first, visible_counts

SEKIZUI_MELDS = 4
FOLD_NEED = 2
"""立直者がいるとき、脊髄まであとこの回数以上鳴く必要があればオリる。"""

MENZEN_HANDOFF_SHANTEN = 1
"""門前でこの向聴数以下なら、鳴かずに立直を目指す（StrongAgent に任せる）。"""


class SekizuiAgent(StrongAgent):
    """積極的に鳴いて脊髄（4副露の裸単騎で13翻）を狙う CPU。"""

    # --- 手番 --------------------------------------------------------------

    def _turn(self, game: Round, seat: int, options: list[Action]) -> Action:
        hand = game.players[seat].hand
        if self._menzen_and_close(hand):
            return super()._turn(game, seat, options)

        # 加槓は副露のままカンになる（嶺上牌・カンドラ。8索ならベンツ）。暗槓は脊髄が消えるのでしない。
        kakan = _first(options, ActionType.KAKAN)
        if kakan is not None:
            return kakan

        kita = _first(options, ActionType.KITA)
        if kita is not None and hand.concealed[PEI] == 1:
            return kita  # 孤立した北は抜く（対子ならポンの種なので残す）

        discards = [a for a in options if a.type is ActionType.DISCARD]
        if not discards:
            return options[0]

        visible = visible_counts(game, seat)
        threats = self._threats(game, seat)
        need = SEKIZUI_MELDS - hand.open_meld_count
        # 立直を受けて、脊髄まであと2回以上鳴く必要があるならオリる（間に合わない）
        folding = bool(threats) and need >= FOLD_NEED

        def key(action: Action) -> tuple:
            after = hand.copy()
            after.remove(action.tile)
            if need == 0:
                # 4副露済み → 残すのは単騎の1枚。残り枚数の多い牌で待つ。
                kept = next(t for t in range(NUM_KINDS) if after.concealed[t])
                return (-(4 - visible[kept]), self._danger(game, seat, action.tile, threats, visible))
            covered, pons, live = sekizui_potential(after.concealed, need, visible)
            danger = self._danger(game, seat, action.tile, threats, visible)
            if folding:
                return (danger, -covered, -pons, -live)
            return (
                -covered,
                -pons,
                -live,
                self._danger(game, seat, action.tile, threats, visible),
                shanten(after),
                self._keep_value(game, seat, action.tile),
            )

        return min(discards, key=key)

    # --- 鳴き --------------------------------------------------------------

    def _react(self, game: Round, seat: int, options: list[Action]) -> Action:
        player = game.players[seat]
        if player.riichi or self._menzen_and_close(player.hand):
            return super()._react(game, seat, options)
        pass_action = _first(options, ActionType.PASS) or options[0]
        tile = game.last_discard
        if player.hand.open_meld_count >= SEKIZUI_MELDS:
            return pass_action  # もう4副露。あとは単騎で待つだけ

        visible = visible_counts(game, seat)
        need = SEKIZUI_MELDS - player.hand.open_meld_count
        if self._threats(game, seat) and need >= FOLD_NEED:
            return pass_action  # 立直を受けて脊髄が遠いなら、鳴いて前に出ない
        best: tuple[tuple, Action] | None = None
        for action in options:
            if action.type not in (ActionType.PON, ActionType.CHI, ActionType.MINKAN):
                continue
            after = _after_call(player.hand, action, tile)
            remaining_need = need - 1
            if remaining_need == 0:
                score = (1, 0, 0)  # 4副露目。どれを鳴いても裸単騎になる
            elif action.type is ActionType.MINKAN:
                # 大明槓のあとは嶺上牌を引いてから切るので、今の形で比べる
                score = sekizui_potential(after.concealed, remaining_need, visible)
            else:
                # ポン・チーのあとは1枚切るので、残す形が一番よくなる切り方で比べる
                score = max(
                    _potential_without(after, discard, remaining_need, visible)
                    for discard in range(NUM_KINDS)
                    if after.concealed[discard] and discard != tile  # 喰い替えの現物は切れない
                )
            # 同じ見込みならポン・カン（誰からでも鳴ける）をチーより優先する
            rank = (score, action.type is not ActionType.CHI)
            if best is None or rank > best[0]:
                best = (rank, action)
        return best[1] if best is not None else pass_action

    # --- 補助 --------------------------------------------------------------

    def _menzen_and_close(self, hand: Hand) -> bool:
        """門前で立直が近いか。それなら脊髄より立直のほうが速い。"""
        return hand.is_menzen and shanten(hand) <= MENZEN_HANDOFF_SHANTEN


def _potential_without(
    hand: Hand, tile: int, need: int, visible: Sequence[int]
) -> tuple[int, int, int]:
    """tile を1枚切った後の sekizui_potential。"""
    hand.remove(tile)
    try:
        return sekizui_potential(hand.concealed, need, visible)
    finally:
        hand.add(tile)


def sekizui_potential(
    counts: Sequence[int], need: int, visible: Sequence[int]
) -> tuple[int, int, int]:
    """手の内の「鳴ける形」の見込み。(足りる鳴きの数, ポンの種の数, 鳴ける牌の残り枚数)。

    - 対子・刻子はポン（刻子なら大明槓も）の種。残りが見えていなければ生きている。
      4枚そろった牌は5枚目が無いので鳴けない（暗槓は脊髄にならない）。
    - 残りの牌から、筒子・索子の両面／嵌張をチーの種として数える。
    - 面子は need 個あれば足りるので、それ以上は数えない。
    """
    rest = list(counts)
    pons = 0
    live = 0
    for tile in range(NUM_KINDS):
        if rest[tile] == 4:
            rest[tile] = 0  # 鳴けない
            continue
        if rest[tile] >= 2:
            # visible には自分の手も入っているので、4 - visible が山や他家の手にある枚数
            outside = 4 - visible[tile]
            if outside > 0:
                pons += 1
                live += outside
            rest[tile] -= min(rest[tile], 3)

    chis = 0
    for tile in range(P1, Z1):
        number = number_of(tile)
        for gap in (1, 2):
            other = tile + gap
            if number + gap > 9 or other >= Z1 or not rest[tile] or not rest[other]:
                continue
            waits = _chi_waits(tile, other)
            outside = sum(4 - visible[w] for w in waits)
            if outside > 0:
                chis += 1
                live += outside
                rest[tile] -= 1
                rest[other] -= 1
                break

    covered = min(pons + chis, need)
    return covered, min(pons, need), live


def _chi_waits(low: int, high: int) -> list[int]:
    """low と high の搭子を完成させる牌。"""
    if high - low == 2:
        return [low + 1]  # 嵌張
    waits = []
    if number_of(low) > 1:
        waits.append(low - 1)
    if number_of(high) < 9:
        waits.append(high + 1)
    return waits

