"""エントリポイント。

    python -m fever_sanma                 人間1人 vs CPU2人でGUI対局
    python -m fever_sanma --cui           同じ対局をターミナルで
    python -m fever_sanma --simulate 1000 全CPUで1000半荘まわす（検証用）
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from .core.match import Match, MatchResult
from .core.yaku import is_dora_yaku
from .players import (
    AI_KINDS,
    AI_LABELS,
    RANDOM_PICK,
    make_cpu,
    parse_ai_kinds,
    resolve_ai_kinds,
)
from .ui import cui


def _configure_console() -> None:
    """出力を UTF-8 に揃える。

    Windows の既定コンソール／パイプは cp932 なので、表現できない文字が1つでも
    混ざると `UnicodeEncodeError` でプログラムごと落ちる。日本語を大量に出す
    プログラムなので、encoding を固定し、それでも駄目な文字は置換して落とさない。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(prog="fever_sanma", description="フィーバー三麻")
    parser.add_argument(
        "--simulate",
        type=int,
        metavar="N",
        help="全CPUで N 半荘まわして統計を出す（対局はしない）",
    )
    parser.add_argument("--seed", type=int, default=None, help="乱数シード")
    parser.add_argument(
        "--seat", type=int, default=0, choices=(0, 1, 2), help="人間が座る席（既定は起家）"
    )
    parser.add_argument("--cui", action="store_true", help="GUIではなくターミナルで対局する")
    parser.add_argument(
        "--ai",
        default=None,
        metavar="KIND[,KIND...]",
        help=(
            f"CPU の種類（{', '.join(AI_KINDS)}）。カンマ区切りで席ごとに混ぜられる。"
            f"{RANDOM_PICK} にするとその席はランダムに選ぶ（例: --ai {RANDOM_PICK} で2人ともランダム）。"
            "既定は対局なら strong、--compare なら strong,random,random"
        ),
    )
    parser.add_argument(
        "--compare",
        type=int,
        metavar="N",
        help="--ai の3人を N 半荘（席を入れ替えながら）対戦させて比べる",
    )
    parser.add_argument(
        "--league",
        type=int,
        metavar="N",
        help="--ai の CPU（既定は strong,sekizui,value,defense）から3人を選ぶ全組み合わせを、"
        "それぞれ N 半荘ずつ総当たりで対戦させる",
    )
    parser.add_argument(
        "--delay", type=int, default=None, metavar="MS", help="GUIでCPUが1手打つまでの間（ミリ秒）"
    )
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    try:
        if args.league:
            default = "strong,sekizui,value,defense"
        elif args.compare:
            default = "strong,random,random"
        else:
            default = "strong"
        kinds = parse_ai_kinds(args.ai or default)
    except ValueError as error:
        parser.error(str(error))
    if args.league:
        if RANDOM_PICK in kinds:
            parser.error(f"--league では {RANDOM_PICK} は使えません（全組み合わせを回すため）")
        return league(args.league, rng, kinds)
    if args.simulate:
        return simulate(args.simulate, rng, resolve_ai_kinds(kinds, 3, rng))
    if args.compare:
        return compare(args.compare, rng, resolve_ai_kinds(kinds, 3, rng))
    if not args.cui:
        from .ui import gui

        delay = gui.CPU_DELAY_MS if args.delay is None else args.delay
        gui.run(human_seat=args.seat, rng=rng, cpu_delay=delay, ai=kinds)
        return 0
    return play_interactive(args.seat, rng, kinds)


def simulate(count: int, rng: random.Random, kinds: list[str]) -> int:
    """全CPUでまわして、破綻していないことを確かめる。"""
    endings: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    yaku_seen: Counter[str] = Counter()
    fever_rounds = 0
    fever_wins = 0
    total_rounds = 0
    draws = 0
    tenpai_players = 0

    for index in range(count):
        agents = [make_cpu(kinds[seat % len(kinds)], rng) for seat in range(3)]
        result = Match(agents, rng=rng).play()
        endings[result.ended_by] += 1
        _check_invariants(result, index)
        for round_result in result.rounds:
            total_rounds += 1
            kinds[round_result.kind] += 1
            if round_result.kind == "draw":
                draws += 1
                tenpai_players += len(round_result.tenpai)
            for value in round_result.values.values():
                yaku_seen.update(
                    y.name for y in value.yaku if not is_dora_yaku(y.name)
                )
            if round_result.fever_wins:
                fever_rounds += 1
                fever_wins += len(round_result.fever_wins)

    print(f"{count}半荘 / {total_rounds}局 完走")
    print(f"  終局理由: {dict(endings)}")
    print(f"  局の結果: {dict(kinds)}")
    if draws:
        print(f"  流局時の平均テンパイ人数: {tenpai_players / draws:.2f} / 3人")
    print(f"  フィーバー和了が出た局: {fever_rounds}（和了 {fever_wins}回）")
    print(f"  出た役: {dict(yaku_seen.most_common(15))}")
    return 0


def compare(count: int, rng: random.Random, kinds: list[str]) -> int:
    """指定した3種類の CPU を対戦させて比べる。

    席の有利不利（親番・割れ目）を均すため、半荘ごとに座る席を1つずつずらす。
    """
    if len(kinds) != 3:
        raise SystemExit("--compare では --ai に3人ぶん指定してください（例: strong,sekizui,random）")
    stats: dict[str, Counter[str]] = {kind: Counter() for kind in kinds}
    best_raw: tuple[int, str, int] | None = None  # (素点, CPU, 何半荘目)
    best_final: tuple[int, str, int] | None = None  # (最終得点, CPU, 何半荘目)
    for index in range(count):
        seating = [kinds[(seat + index) % 3] for seat in range(3)]
        agents = [make_cpu(kind, rng) for kind in seating]
        result = Match(agents, rng=rng).play()
        _check_invariants(result, index)
        for seat, kind in enumerate(seating):
            if best_raw is None or result.scores[seat] > best_raw[0]:
                best_raw = (result.scores[seat], kind, index + 1)
            if best_final is None or result.final[seat] > best_final[0]:
                best_final = (result.final[seat], kind, index + 1)
            stat = stats[kind]
            stat["seats"] += 1
            stat["final"] += result.final[seat]
            stat["top"] += result.ranking[0] == seat
            for round_result in result.rounds:
                stat["wins"] += seat in round_result.winners
                stat["deal_ins"] += _dealt_in(round_result, seat)
                if seat in round_result.winners:
                    names = {y.name for y in round_result.values[seat].yaku}
                    stat["sekizui"] += "脊髄" in names
    print(f"{count}半荘（{' / '.join(AI_LABELS[k] for k in kinds)}、席は毎回ずらす）")
    for kind, stat in stats.items():
        n = stat["seats"]
        print(
            f"  {AI_LABELS[kind]}: 平均最終得点 {stat['final'] / n:+9,.0f}  "
            f"トップ率 {stat['top'] / n:4.0%}  和了 {stat['wins'] / n:.2f}回/半荘"
            f"（うち脊髄 {stat['sekizui'] / n:.2f}）  放銃 {stat['deal_ins'] / n:.2f}回/半荘"
        )
    print(
        f"  1半荘の最高得点: 素点 {best_raw[0]:,}点（{AI_LABELS[best_raw[1]]}、{best_raw[2]}半荘目）"
        f" / 最終得点 {best_final[0]:+,}点（{AI_LABELS[best_final[1]]}、{best_final[2]}半荘目）"
    )
    return 0


def league(count: int, rng: random.Random, kinds: list[str]) -> int:
    """総当たり。kinds から3人を選ぶ全組み合わせを、それぞれ count 半荘ずつ対戦させる。

    席の有利不利を均すため、半荘ごとに座る席を1つずつずらす。
    直接対決は「同じ半荘に座った2人のうち、上の順位だったほう」の勝ちとして数える。
    """
    from itertools import combinations

    if len(set(kinds)) < 3:
        raise SystemExit("--league には3種類以上の CPU を指定してください")
    kinds = list(dict.fromkeys(kinds))
    stats: dict[str, Counter[str]] = {kind: Counter() for kind in kinds}
    duel: Counter[tuple[str, str]] = Counter()  # (勝った方, 負けた方)
    best: tuple[int, str, tuple[str, ...], int] | None = None
    tables = list(combinations(kinds, 3))

    for table in tables:
        for index in range(count):
            seating = [table[(seat + index) % 3] for seat in range(3)]
            result = Match([make_cpu(kind, rng) for kind in seating], rng=rng).play()
            _check_invariants(result, index)
            rank = {seat: position for position, seat in enumerate(result.ranking)}
            for seat, kind in enumerate(seating):
                stat = stats[kind]
                stat["seats"] += 1
                stat["final"] += result.final[seat]
                stat["top"] += rank[seat] == 0
                stat["last"] += rank[seat] == 2
                stat["busted"] += result.scores[seat] < 0
                for round_result in result.rounds:
                    stat["wins"] += seat in round_result.winners
                    stat["deal_ins"] += _dealt_in(round_result, seat)
                if best is None or result.scores[seat] > best[0]:
                    best = (result.scores[seat], kind, table, index + 1)
            for a in range(3):
                for b in range(3):
                    if a != b and rank[a] < rank[b]:
                        duel[(seating[a], seating[b])] += 1

    print(f"総当たり: {len(tables)}卓 × {count}半荘 = {len(tables) * count}半荘（席は毎回ずらす）")
    print()
    print("■ 通算成績（平均最終得点の順）")
    order = sorted(kinds, key=lambda k: -stats[k]["final"] / stats[k]["seats"])
    for place, kind in enumerate(order, start=1):
        stat = stats[kind]
        n = stat["seats"]
        print(
            f"  {place}位 {_pad(AI_LABELS[kind], 10)} 平均最終得点 {stat['final'] / n:+9,.0f}  "
            f"トップ {stat['top'] / n:4.0%}  ラス {stat['last'] / n:4.0%}  飛び {stat['busted'] / n:4.0%}  "
            f"和了 {stat['wins'] / n:.2f}  放銃 {stat['deal_ins'] / n:.2f}（回/半荘）"
        )
    print()
    print("■ 直接対決（同じ半荘で上の順位だった割合。行のAIから見た勝率）")
    width = 12
    print("  " + " " * width + "".join(_pad(AI_LABELS[k], width, right=True) for k in order))
    for a in order:
        cells = []
        for b in order:
            if a == b:
                cells.append(_pad("-", width, right=True))
                continue
            games = duel[(a, b)] + duel[(b, a)]
            cells.append(_pad(f"{duel[(a, b)] / games:.0%}" if games else "", width, right=True))
        print("  " + _pad(AI_LABELS[a], width) + "".join(cells))
    print()
    raw, kind, table, number = best
    print(
        f"■ 1半荘の最高得点: 素点 {raw:,}点（{AI_LABELS[kind]}。"
        f"卓: {' / '.join(AI_LABELS[k] for k in table)} の{number}半荘目）"
    )
    return 0


def _pad(text: str, width: int, right: bool = False) -> str:
    """全角文字を2桁として数えて幅をそろえる（日本語の表を崩さないため）。"""
    import unicodedata

    size = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    space = " " * max(0, width - size)
    return space + text if right else text + space


def _dealt_in(round_result, seat: int) -> bool:
    """その局で seat が放銃したか（ロンで失点したのが seat だけ）。"""
    if round_result.kind != "win" or seat in round_result.winners:
        return False
    losers = [s for s, d in round_result.payments.deltas.items() if d < 0]
    return losers == [seat]


def _check_invariants(result: MatchResult, index: int) -> None:
    """全CPU実行中に不変条件が壊れていないか確かめる。"""
    if sum(result.final) != 0:
        raise AssertionError(f"{index}半荘目: 最終得点がゼロサムでない {result.final}")
    if len(result.scores) != 3:
        raise AssertionError(f"{index}半荘目: 席数が壊れている")


def play_interactive(seat: int, rng: random.Random, kinds: list[str]) -> int:
    from .players import HumanCuiAgent

    seating = cpu_seating(seat, resolve_ai_kinds(kinds, 2, rng))
    agents = [make_cpu(kind, rng) for kind in seating]
    match_ref: list[Match] = []
    agents[seat] = HumanCuiAgent(on_command=lambda c: match_ref[0].request_hidden(seat, c))

    print(f"フィーバー三麻（東風戦）: あなたは {cui.SEAT_LABELS[seat]} です")
    opponents = "、".join(
        f"{cui.SEAT_LABELS[other]}={AI_LABELS[seating[other]]}"
        for other in ((seat + 1) % 3, (seat + 2) % 3)
    )
    print(f"対戦相手: {opponents}")

    counter = [0]

    def show(game, round_result) -> None:
        counter[0] += 1
        print()
        print(f"--- {counter[0]}局目 終了 ---")
        print(cui.render_table(game))
        print(cui.render_round_result(round_result))

    match = Match(agents, rng=rng, on_round_end=show)
    match_ref.append(match)
    result = match.play()
    print()
    print(cui.render_match_result(result))
    return 0


def cpu_seating(human_seat: int, kinds: list[str]) -> list[str]:
    """各席の CPU の種類。人間の席以外に、人間の下家から順に kinds を割り当てる。

    人間の席の値は使われない（人間の打ち手で置き換える）。
    """
    seating = ["strong"] * 3
    for order, offset in enumerate((1, 2)):
        seating[(human_seat + offset) % 3] = kinds[order % len(kinds)]
    return seating


if __name__ == "__main__":
    sys.exit(main())
