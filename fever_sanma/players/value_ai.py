"""高打点狙いの CPU。

`StrongAgent` を土台に、押し引きと手作りを「打点」で決めるよう差し替えている。

- 手の価値（見込みの打点）を数える: ドラ（常時ドラ・表ドラ・抜きドラ）、
  フィーバーの種（7筒・7索の刻子）、ベンツの種（8索3枚以上）、混一色寄り、
  役牌の刻子、割れ目（上がれば3倍）。
- **「高い手」＝上がれば誰かを飛ばせる手**。見込みの翻数から点数を出し、相手ごとに
  「その人からロン（またはツモ）したら0点を下回るか」で判定する。割れ目の3倍も計算に入る。
  高い手は押す。立直を受けても1向聴なら押し、オリるのは3向聴以上だけ。
- **安くなりそうな手は早くオリる**。立直を受けたらテンパイでもオリる。さらに
  3副露以上の相手も脊髄（4副露の裸単騎で13翻）の可能性があるので警戒する。
- **フィーバー立直を狙う**: 7筒・7索の刻子は崩さない。鳴かずに門前を守り、
  立直の宣言牌はフィーバー立直が成立する切り方を優先する。
- **ベンツを狙う**: 8索の対子はポンし、8索のカンは必ずする。8索は1枚でも残しやすい。
- 安い鳴きはしない。鳴くのは役牌・8索・混一色寄りのときだけ（脊髄狙いの鳴きはしない）。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core import yaku_special
from ..core.game import Action, ActionType, Round
from ..core.hand import Hand, MeldType
from ..core.tiles import NUM_KINDS, PEI, PERMANENT_DORA, dora_from_indicator, is_honor, suit_of
from ..core.score import is_bust, settle_win
from ..core.yaku import HandValue, yakuhai_han
from .strong_ai import BENZ_TILE, FEVER_TILES, StrongAgent, _first, visible_counts

LOW_VALUE = 1
"""この見込み以下なら安い手として、立直を受けたらすぐオリる。"""

MIN_WIN_HAN = 2
"""上がるには常に二翻縛りを満たすので、見込みの翻数はこれを土台にする。"""

ESTIMATE_FU = 30
"""見込みの点数を出すときの符。満貫未満の手でしか効かないので大まかでよい。"""

HIGH_VALUE_FOLD_SHANTEN = 3
"""誰かを飛ばせる手でも、立直を受けてこれ以上遠ければオリる。"""

SEKIZUI_WATCH_MELDS = 3
"""安い手のとき、この数以上鳴いている相手も警戒する（脊髄が近い）。"""

PROTECT_PENALTY = 2
"""守りたい形（フィーバー・ベンツの種）を崩す打牌に足す向聴数の重み。実質崩さない。"""

VALUE_WEIGHT = 12
"""有効牌1枚と比べた、手の価値1点の重み。多少効率を落としても高い手を残す。"""


class ValueAgent(StrongAgent):
    """打点を重視し、安い手は早くオリる CPU。"""

    # --- 手の価値 ----------------------------------------------------------

    def hand_value(self, game: Round, seat: int, hand: Hand | None = None) -> int:
        """見込みの打点（おおよその翻数）。"""
        player = game.players[seat]
        hand = hand or player.hand
        tiles = hand.all_tiles()
        dora_tiles = [dora_from_indicator(i) for i in game.wall.dora_indicators()]

        dora = sum(1 for t in tiles if t in PERMANENT_DORA)
        dora += sum(dora_tiles.count(t) for t in tiles)
        dora += hand.kita * (1 + dora_tiles.count(PEI))
        value = dora

        if _fever_seed(hand):
            value += 2  # フィーバー立直（2翻）。さらに他家が強制ツモ切りになる
        benz = _count_with_melds(hand, BENZ_TILE)
        if yaku_special.has_benz(hand) or benz == 4:
            value += 2 + dora * 2  # ベンツ（2翻）＋ドラが3倍
        elif benz == 3:
            value += 1

        if _honitsu_leaning(hand):
            value += 2
        value += sum(
            yakuhai_han(t, player.seat_wind) for t in range(NUM_KINDS) if hand.concealed[t] >= 3
        )
        value += sum(
            yakuhai_han(m.tile, player.seat_wind) for m in hand.melds if m.type is not MeldType.CHI
        )
        return value

    def estimated_han(self, game: Round, seat: int, hand: Hand | None = None) -> int:
        """上がったときの見込みの翻数。二翻縛りがあるので最低2翻を土台に、手の価値を足す。"""
        return MIN_WIN_HAN + self.hand_value(game, seat, hand)

    def can_bust(self, game: Round, seat: int, hand: Hand | None = None) -> bool:
        """この手で上がれば、誰かを飛ばせるか（「高い手」の基準）。

        相手ごとに、その人からロンした場合と、ツモった場合の支払いを割れ目込みで計算し、
        支払った後に0点を下回る（＝飛ぶ）人がいるかを見る。0点ちょうどは飛ばない。
        """
        value = HandValue(han=self.estimated_han(game, seat, hand), fu=ESTIMATE_FU)
        scores = [player.score for player in game.players]
        others = [other for other in range(len(scores)) if other != seat]
        for other in others:
            ron = settle_win(
                value, winner=seat, dealer=game.dealer, is_tsumo=False,
                discarder=other, wareme=game.wareme,
            )
            if is_bust(scores[other] + ron.get(other)):
                return True
        tsumo = settle_win(value, winner=seat, dealer=game.dealer, is_tsumo=True, wareme=game.wareme)
        return any(is_bust(scores[other] + tsumo.get(other)) for other in others)

    # --- 手番 --------------------------------------------------------------

    def _discard_score(
        self, game: Round, seat: int, tile: int, visible: Sequence[int]
    ) -> tuple[int, int, int]:
        """(向聴数, 有効牌と手の価値を合わせた評価, 残す価値)。"""
        current, ukeire, keep = super()._discard_score(game, seat, tile, visible)
        hand = game.players[seat].hand
        if _breaks_seed(hand, tile):
            current += PROTECT_PENALTY  # フィーバー・ベンツの種は崩さない
        after = hand.copy()
        after.remove(tile)
        combined = ukeire + VALUE_WEIGHT * self.hand_value(game, seat, after)
        return current, combined, keep

    def _keep_value(self, game: Round, seat: int, tile: int) -> int:
        value = super()._keep_value(game, seat, tile)
        count = game.players[seat].hand.concealed[tile]
        if tile in FEVER_TILES and count >= 1:
            value += 1  # 7筒・7索は1枚でも刻子の種
        if tile == BENZ_TILE:
            value += 1 + count  # 8索は集めたい
        return value

    def _riichi_action(
        self, game: Round, seat: int, options: list[Action], tile: int
    ) -> Action | None:
        """フィーバー立直が成立する宣言牌があれば、それを優先する。"""
        fever_tile = self._fever_riichi_tile(game, seat, options)
        if fever_tile is not None:
            tile = fever_tile
        return super()._riichi_action(game, seat, options, tile)

    def _fever_riichi_tile(self, game: Round, seat: int, options: list[Action]) -> int | None:
        player = game.players[seat]
        visible = visible_counts(game, seat)
        best_tile: int | None = None
        best_han = 0
        for action in options:
            if action.type is not ActionType.RIICHI:
                continue
            hand = player.hand.copy()
            hand.remove(action.tile)
            yaku = yaku_special.fever_yaku(hand, visible, is_menzen=hand.is_menzen)
            if yaku is not None and yaku.han > best_han:  # ダブルフィーバーを優先
                best_tile, best_han = action.tile, yaku.han
        return best_tile

    # --- 押し引き ----------------------------------------------------------

    def _threats(self, game: Round, seat: int) -> list[int]:
        threats = super()._threats(game, seat)
        if self.hand_value(game, seat) <= LOW_VALUE:
            # 安い手で放銃するのは割に合わない。脊髄が近い相手も警戒する。
            threats += [
                other
                for other, player in enumerate(game.players)
                if other != seat
                and other not in threats
                and player.hand.open_meld_count >= SEKIZUI_WATCH_MELDS
            ]
        return threats

    def _should_fold(
        self, game: Round, seat: int, threats: list[int], best_shanten: int
    ) -> bool:
        if not threats:
            return False
        value = self.hand_value(game, seat)
        if value <= LOW_VALUE:
            return True  # 安い手はテンパイでもオリる
        if self.can_bust(game, seat):
            return best_shanten >= HIGH_VALUE_FOLD_SHANTEN  # 誰かを飛ばせる手は押す
        return super()._should_fold(game, seat, threats, best_shanten)

    # --- 鳴き --------------------------------------------------------------

    def _react(self, game: Round, seat: int, options: list[Action]) -> Action:
        player = game.players[seat]
        if not player.riichi and game.last_discard == BENZ_TILE and not _fever_seed(player.hand):
            # 8索の対子はポンして、後で加槓すればベンツ
            pon = _first(options, ActionType.PON)
            minkan = _first(options, ActionType.MINKAN)
            if minkan is not None or pon is not None:
                return minkan or pon
        return super()._react(game, seat, options)

    def _worth_opening(
        self, game: Round, seat: int, action: Action, tile: int, before: int
    ) -> bool:
        hand = game.players[seat].hand
        if _fever_seed(hand) and hand.is_menzen:
            return False  # フィーバーの種がある門前手は崩さない
        if hand.open_meld_count:
            return self.hand_value(game, seat) > LOW_VALUE  # 安いまま鳴き進めない
        if action.type is ActionType.PON and yakuhai_han(tile, game.players[seat].seat_wind):
            return True
        return _honitsu_leaning(hand)


# --- 補助 ------------------------------------------------------------------


def _fever_seed(hand: Hand) -> bool:
    """7筒か7索の刻子（または暗槓）を持っているか。"""
    return any(
        hand.concealed[t] >= 3
        or any(m.type is MeldType.ANKAN and m.tile == t for m in hand.melds)
        for t in FEVER_TILES
    )


def _breaks_seed(hand: Hand, tile: int) -> bool:
    """その牌を切ると、フィーバー・ベンツの種が崩れるか。"""
    count = hand.concealed[tile]
    if tile in FEVER_TILES:
        return count == 3  # 刻子を崩す（4枚なら1枚切っても刻子が残る）
    if tile == BENZ_TILE:
        return count >= 2  # 対子以上ならポン・カンでベンツが見える
    return False


def _count_with_melds(hand: Hand, tile: int) -> int:
    return hand.concealed[tile] + sum(m.tiles.count(tile) for m in hand.melds)


def _honitsu_leaning(hand: Hand) -> bool:
    tiles = hand.all_tiles()
    honors = sum(1 for t in tiles if is_honor(t))
    by_suit: dict[str, int] = {}
    for t in tiles:
        if not is_honor(t):
            by_suit[suit_of(t)] = by_suit.get(suit_of(t), 0) + 1
    return honors + max(by_suit.values(), default=0) >= len(tiles) - 3
