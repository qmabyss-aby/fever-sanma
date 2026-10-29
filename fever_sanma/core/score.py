"""符翻から点数へ、そして点数移動へ。

CLAUDE.md §6 の通り **割れ目なしの精算を土台にし、その上に割れ目倍率を掛ける**
二層構造にしている。

要点は点数移動を「誰から誰へいくら」（`Transfer`）で保持すること。割れ目の
一般則「割れ目の人が関わる点数移動をすべて3倍にする」（CLAUDE.md §4.9）は、
この形なら該当する Transfer を3倍するだけで書ける。増減の合計値だけを持っていると、
第三者どうしの移動と割れ目相手との移動を区別できず、正しく3倍にできない。

三人打ちなので子のツモは「親2 + 子1」の支払いになる（ツモ損あり）。これは
CLAUDE.md §4.9 の検算表と一致する:

    子1が満貫ツモ・親が割れ目 → 親 4,000×3 = 12,000 / 子2 2,000 / 和了者 +14,000
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .yaku import HandValue

NUM_PLAYERS = 3

MANGAN_BASE = 2000
KIRIAGE_THRESHOLD = 1920
"""切り上げ満貫の閾値（30符4翻・60符3翻がちょうど1,920）。ユーザー確定事項で採用。"""

COUNTED_YAKUMAN_HAN = 13
YAKUMAN_BASE = 8000

NOTEN_PENALTY = 3000
"""ノーテン罰符（CLAUDE.md §4.1）。"""

YAKUMAN_BONUS = 40000
"""役満ご祝儀（CLAUDE.md §4.8）。割れ目の対象外。数え役満では発生しない。"""

TOBI_BONUS = 10000
"""飛び賞。飛ばした和了者が受け取り、飛んだ人が支払う。"""

START_SCORE = 25000
RETURN_SCORE = 30000
RANK_POINTS = (15000, -5000, -10000)
"""順位点。25,000点持ちの30,000点返し（CLAUDE.md §4.8）。"""


# --- 点数移動の表現 --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transfer:
    """プレイヤー間の点数移動1件。"""

    payer: int
    receiver: int
    amount: int

    def involves(self, seat: int) -> bool:
        return seat in (self.payer, self.receiver)

    def scaled(self, factor: int) -> Transfer:
        return Transfer(self.payer, self.receiver, self.amount * factor)


@dataclass
class Payments:
    """1回の精算。

    transfers はプレイヤー間の移動（割れ目倍率の対象）。
    pot は供託・ご祝儀など、プレイヤー間の移動として扱わない増減。
    """

    transfers: list[Transfer] = field(default_factory=list)
    pot: dict[int, int] = field(default_factory=dict)

    def add_transfer(self, payer: int, receiver: int, amount: int) -> None:
        if amount:
            self.transfers.append(Transfer(payer, receiver, amount))

    def add_pot(self, seat: int, amount: int) -> None:
        if amount:
            self.pot[seat] = self.pot.get(seat, 0) + amount

    @property
    def deltas(self) -> dict[int, int]:
        """席番号 → 増減。"""
        result: dict[int, int] = dict(self.pot)
        for transfer in self.transfers:
            result[transfer.payer] = result.get(transfer.payer, 0) - transfer.amount
            result[transfer.receiver] = result.get(transfer.receiver, 0) + transfer.amount
        return result

    def get(self, seat: int) -> int:
        return self.deltas.get(seat, 0)

    def total(self) -> int:
        """ゼロサムなら0になる。供託の受け渡しがある場合はその分ずれる。"""
        return sum(self.deltas.values())

    def merge(self, other: Payments) -> Payments:
        merged = Payments(list(self.transfers), dict(self.pot))
        merged.transfers.extend(other.transfers)
        for seat, amount in other.pot.items():
            merged.add_pot(seat, amount)
        return merged


# --- 基本点 ----------------------------------------------------------------


DOUBLE_YAKUMAN_HAN = 20


def counted_yakuman_multiplier(han: int) -> int:
    """数え役満の重複数。

    13〜19翻で役満、20〜29翻でダブル、30〜39翻でトリプル、以降10翻ごと
    （CLAUDE.md §4.7 の表 / Wiki「13翻で数え役満、20翻でダブル役満、
    30翻でトリプル役満、40翻でクアドラプル役満、以降10翻ごと」）。

    注意: CLAUDE.md §4.7 に併記されている式 `1 + max(0, (han - 13) // 10)` は
    同じ節の表と一致しない（20翻でも1のまま、30翻でも2にしかならない）。
    表と Wiki の記述が正なので、そちらに合わせている。
    """
    if han < COUNTED_YAKUMAN_HAN:
        return 0
    if han < DOUBLE_YAKUMAN_HAN:
        return 1
    return 2 + (han - DOUBLE_YAKUMAN_HAN) // 10


def base_points(value: HandValue, kiriage: bool = True) -> int:
    """符と翻から基本点を求める。基本点 = 符 × 2^(2+翻)、満貫で頭打ち。"""
    if value.yakuman:
        return YAKUMAN_BASE * value.yakuman

    counted = counted_yakuman_multiplier(value.han)
    if counted:
        return YAKUMAN_BASE * counted

    han = value.han
    if han >= 11:
        return 6000  # 三倍満
    if han >= 8:
        return 4000  # 倍満
    if han >= 6:
        return 3000  # 跳満
    if han >= 5:
        return MANGAN_BASE

    raw = value.fu * (2 ** (2 + han))
    if kiriage and raw >= KIRIAGE_THRESHOLD:
        return MANGAN_BASE  # 切り上げ満貫（30符4翻・60符3翻）
    return min(raw, MANGAN_BASE)


def _round_up_100(points: int) -> int:
    return -(-points // 100) * 100


# --- 和了の精算 ------------------------------------------------------------


def win_transfers(
    value: HandValue,
    winner: int,
    dealer: int,
    is_tsumo: bool,
    discarder: int | None = None,
    num_players: int = NUM_PLAYERS,
    kiriage: bool = True,
) -> Payments:
    """割れ目を考えない素の点数移動。"""
    base = base_points(value, kiriage)
    winner_is_dealer = winner == dealer
    payments = Payments()

    if is_tsumo:
        for seat in range(num_players):
            if seat == winner:
                continue
            if winner_is_dealer:
                amount = _round_up_100(base * 2)
            else:
                # 三人打ちなので親2・子1。子1人ぶん少ないまま（ツモ損あり）
                amount = _round_up_100(base * (2 if seat == dealer else 1))
            payments.add_transfer(seat, winner, amount)
    else:
        if discarder is None:
            raise ValueError("ロンには放銃者が必要")
        payments.add_transfer(
            discarder, winner, _round_up_100(base * (6 if winner_is_dealer else 4))
        )
    return payments


def apply_wareme(payments: Payments, wareme: int | None) -> Payments:
    """割れ目倍率を適用する（CLAUDE.md §4.9）。

    一般則「割れ目の人が関わる点数移動をすべて3倍にする」。Wiki の点数表は
    「親が割れている場合」しか載っていないが、この一般則で §4.9 の検算表5ケース
    すべてに一致する。供託・ご祝儀（pot）は対象外。
    """
    if wareme is None:
        return payments
    return Payments(
        [t.scaled(3) if t.involves(wareme) else t for t in payments.transfers],
        dict(payments.pot),
    )


def settle_win(
    value: HandValue,
    winner: int,
    dealer: int,
    is_tsumo: bool,
    discarder: int | None = None,
    wareme: int | None = None,
    riichi_sticks: int = 0,
    num_players: int = NUM_PLAYERS,
    kiriage: bool = True,
) -> Payments:
    """和了による点数移動（割れ目・供託込み。ご祝儀は含まない）。"""
    payments = win_transfers(
        value,
        winner=winner,
        dealer=dealer,
        is_tsumo=is_tsumo,
        discarder=discarder,
        num_players=num_players,
        kiriage=kiriage,
    )
    result = apply_wareme(payments, wareme)
    result.add_pot(winner, riichi_sticks * 1000)  # 供託は割れ目の対象外
    return result


def yakuman_bonus(
    value: HandValue,
    winner: int,
    is_tsumo: bool,
    discarder: int | None = None,
    num_players: int = NUM_PLAYERS,
) -> Payments:
    """役満ご祝儀（CLAUDE.md §4.8）。

    ロンなら放銃者が40,000点、ツモなら和了者以外が20,000点ずつ。ダブル役満は2倍。
    **数え役満では発生しない**し、**割れ目の対象外**なので pot として扱う。
    """
    payments = Payments()
    if not value.yakuman:
        return payments

    total = YAKUMAN_BONUS * value.yakuman
    if is_tsumo:
        share = total // (num_players - 1)
        for seat in range(num_players):
            if seat == winner:
                continue
            payments.add_pot(seat, -share)
            payments.add_pot(winner, share)
    else:
        if discarder is None:
            raise ValueError("ロンには放銃者が必要")
        payments.add_pot(discarder, -total)
        payments.add_pot(winner, total)
    return payments


# --- 流局 ------------------------------------------------------------------


def settle_noten(
    tenpai_seats: list[int],
    num_players: int = NUM_PLAYERS,
    wareme: int | None = None,
) -> Payments:
    """流局時のノーテン罰符（CLAUDE.md §4.1）。

    1人テンパイ → ノーテン2人が3,000点ずつ払う（テンパイ者 +6,000）
    2人テンパイ → ノーテン1人が3,000点ずつ払う（−6,000）
    全員テンパイ・全員ノーテンなら移動なし。

    wareme を渡した場合のみ罰符にも割れ目倍率をかける。Wiki の割れ目の点数表は
    和了しか載っておらず罰符の扱いが不明なため、既定では **かけない**。
    """
    payments = Payments()
    noten = [seat for seat in range(num_players) if seat not in tenpai_seats]
    if not tenpai_seats or not noten:
        return payments

    # ノーテン1人あたりの支払総額は 3,000 × テンパイ人数。それをテンパイ者で分ける。
    per_payer = NOTEN_PENALTY * len(tenpai_seats)
    for payer in noten:
        for receiver in tenpai_seats:
            payments.add_transfer(payer, receiver, per_payer // len(tenpai_seats))
    return apply_wareme(payments, wareme)


# --- 飛び ------------------------------------------------------------------


def is_bust(score: int) -> bool:
    """飛んだか。**0点ちょうどは続行**、0点を下回った時点で終局（CLAUDE.md §4.8）。"""
    return score < 0


def tobi_bonus(busted: list[int], winners: list[int]) -> Payments:
    """飛び賞（CLAUDE.md §4.8）。

    飛ばした和了者に +10,000、飛んだ人に −10,000。ダブロンで飛んだ場合は
    和了者で 5,000 ずつ折半する。**ノーテン罰符で飛んだ場合は呼ばないこと**
    （賞もペナルティもなく、その時点で終局するだけ）。
    """
    payments = Payments()
    if not busted or not winners:
        return payments
    total = TOBI_BONUS * len(busted)
    for seat in busted:
        payments.add_pot(seat, -TOBI_BONUS)
    share = total // len(winners)
    for seat in winners:
        payments.add_pot(seat, share)
    return payments


# --- 順位点 ----------------------------------------------------------------


def final_scores(scores: list[int], num_players: int = NUM_PLAYERS) -> list[int]:
    """終局時の最終得点（順位点・オカ込み）。

    25,000点持ちの30,000点返し。順位点は 1位 +15,000 / 2位 −5,000 / 3位 −10,000
    （CLAUDE.md §4.8 / Wiki）。

    返し点で引くと (30,000 − 25,000) × 3人 = 15,000点 が浮くが、Wiki にオカの
    記載がない。ユーザー確定事項として **オカはトップに加算** し、全体をゼロサムに
    する（実質 1位 +30,000 / 2位 −5,000 / 3位 −10,000）。
    同点の場合は席順（起家に近い順）で上位とする。
    """
    oka = (RETURN_SCORE - START_SCORE) * num_players
    order = sorted(range(len(scores)), key=lambda s: (-scores[s], s))
    result = [0] * len(scores)
    for rank, seat in enumerate(order):
        result[seat] = scores[seat] - RETURN_SCORE + RANK_POINTS[rank]
        if rank == 0:
            result[seat] += oka
    return result
