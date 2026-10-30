"""CPU 同士の牌譜を記録して、どこで点を得て・失っているかを集計する。

    python tools/paifu.py record 3000 --seed 1 --out paifu/league.jsonl.gz
    python tools/paifu.py analyze paifu/league.jsonl.gz [--ai strong]

record は総当たり（4種類から3人を選ぶ4卓）を卓ごとに N 半荘、並列で回し、
1局につき1行の JSON を gzip で書き出す。各行には配牌・全員の選んだ手・局の結果に加えて、
あとで押し引きを調べられるよう、選択の時点の向聴数・立直者の有無・現物があったかを入れる。

analyze はその牌譜から、AI ごとの点数の出入り（和了・放銃・被ツモ・ノーテン罰符など）、
放銃した相手の手の種類と放銃したときの自分の状態、立直・鳴きの成績を出す。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fever_sanma.core.game import ActionType, Phase, Round  # noqa: E402
from fever_sanma.core.match import Match, drive_round  # noqa: E402
from fever_sanma.core.shanten import is_tenpai, shanten  # noqa: E402
from fever_sanma.players import AI_LABELS, make_cpu  # noqa: E402

KINDS = ["strong", "value", "sekizui", "defense"]


# --- 記録 --------------------------------------------------------------------


def threats_of(game: Round, seat: int) -> list[str]:
    """seat から見た脅威。R=立直 O=オープン立直 F=フィーバー M=3副露以上（脊髄の手前）。"""
    found = []
    for other, player in enumerate(game.players):
        if other == seat:
            continue
        if other == game.fever_seat:
            found.append(f"F{other}")
        elif player.open_riichi:
            found.append(f"O{other}")
        elif player.riichi:
            found.append(f"R{other}")
        elif player.hand.open_meld_count >= 3:
            found.append(f"M{other}")
    return found


def is_genbutsu(game: Round, seat: int, tile: int) -> bool:
    """立直者全員に対して現物か（立直者がいなければ False）。"""
    riichi = [p for s, p in enumerate(game.players) if s != seat and p.riichi]
    return bool(riichi) and all(tile in p.discards for p in riichi)


class Recorder:
    """打ち手を包んで、選んだ手とその時点の状況を記録する。"""

    def __init__(self, agent, events: list) -> None:
        self.agent = agent
        self.events = events
        self.ron_from: int | None = None

    def choose(self, game: Round, seat: int, options):
        action = self.agent.choose(game, seat, options)
        event = {"s": seat, "p": game.phase.value, "a": action.type.value}
        if action.tile is not None:
            event["t"] = action.tile
        if len(options) > 1 and game.phase is not Phase.FEVER:
            player = game.players[seat]
            event["sh"] = shanten(player.hand)
            event["rem"] = game.wall.remaining
            threats = threats_of(game, seat)
            if threats:
                event["thr"] = threats
            if action.type is ActionType.DISCARD and any(t[0] == "R" or t[0] == "O" for t in threats):
                tiles = {a.tile for a in options if a.type is ActionType.DISCARD}
                event["safe"] = is_genbutsu(game, seat, action.tile)
                event["safe_avail"] = any(is_genbutsu(game, seat, t) for t in tiles)
        if action.type is ActionType.RON:
            event["from"] = game.last_discarder
        self.events.append(event)
        return action


def player_end_state(game: Round, seat: int) -> dict:
    player = game.players[seat]
    return {
        "riichi": player.riichi,
        "open_riichi": player.open_riichi,
        "double": player.double_riichi,
        "fever": seat == game.fever_seat,
        "melds": [m.type.value for m in player.hand.melds],
        "kita": player.hand.kita,
        "shanten": shanten(player.hand),
        "tenpai": is_tenpai(player.hand) if sum(player.hand.concealed) % 3 == 1 else None,
    }


def value_json(value) -> dict:
    return {
        "han": value.han,
        "fu": value.fu,
        "yakuman": value.yakuman,
        "yaku": [y.name for y in value.yaku],
    }


def play_match(seating: list[str], rng: random.Random, match_id: str) -> list[dict]:
    rows = []
    match = Match([make_cpu(kind, rng) for kind in seating], rng=rng)
    while match.result is None:
        game = match.start_round()
        events: list = []
        agents = [Recorder(agent, events) for agent in match.agents]
        start_scores = list(game.scores)
        deal = [sorted(game.players[s].hand.all_tiles()) for s in range(3)]
        result = drive_round(game, agents)
        row = {
            "match": match_id,
            "seating": seating,
            "round": match.round_number,
            "dealer": game.dealer,
            "wareme": game.wareme,
            "start": start_scores,
            "deal": deal,
            "dora": list(game.wall.dora_indicators()),
            "events": events,
            "kind": result.kind,
            "abort": result.abort_reason,
            "winners": result.winners,
            "tenpai": result.tenpai,
            "values": {str(s): value_json(v) for s, v in result.values.items()},
            "transfers": [[t.payer, t.receiver, t.amount] for t in result.payments.transfers],
            "pot": {str(s): v for s, v in result.payments.pot.items()},
            "fever_wins": [
                {
                    "tile": w.win_tile,
                    "tsumo": w.is_tsumo,
                    "from": w.discarder,
                    "value": value_json(w.value),
                    "deltas": {str(s): d for s, d in w.payments.deltas.items()},
                }
                for w in result.fever_wins
            ],
            "end": [player_end_state(game, s) for s in range(3)],
        }
        ended = match.end_round(game, result)
        if ended is not None:
            row["match_end"] = {
                "scores": ended.scores,
                "final": ended.final,
                "ranking": ended.ranking,
                "ended_by": ended.ended_by,
            }
        rows.append(row)
    return rows


def record_chunk(table: tuple[str, ...], start: int, count: int, seed: int, path: str) -> str:
    rng = random.Random(seed)
    with gzip.open(path, "wt", encoding="utf-8") as out:
        for index in range(start, start + count):
            seating = [table[(seat + index) % 3] for seat in range(3)]
            for row in play_match(seating, rng, f"{seed}-{index}"):
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def record(per_table: int, seed: int, out: Path, workers: int) -> None:
    tables = list(combinations(KINDS, 3))
    chunks = max(1, workers * 2 // len(tables))
    size = per_table // chunks
    out.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = out.parent / (out.name + ".parts")
    parts_dir.mkdir(exist_ok=True)
    jobs = [
        (table, c * size, size, seed * 100000 + t * 1000 + c, str(parts_dir / f"{t}-{c}.jsonl.gz"))
        for t, table in enumerate(tables)
        for c in range(chunks)
    ]
    began = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(record_chunk, *job) for job in jobs]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            print(f"[{done}/{len(jobs)}] {time.time() - began:.0f}s", flush=True)
    with open(out, "wb") as merged:
        for job in jobs:
            merged.write(Path(job[4]).read_bytes())  # gzip は連結してもそのまま読める
            Path(job[4]).unlink()
    parts_dir.rmdir()
    print(f"{len(tables)}卓 × {size * chunks}半荘 → {out}（{time.time() - began:.0f}秒）")


# --- 集計 --------------------------------------------------------------------


def hand_type(end: dict, value: dict | None) -> str:
    """和了者（または相手）の手の種類。"""
    yaku = set(value["yaku"]) if value else set()
    if end["fever"]:
        return "フィーバー"
    if "脊髄" in yaku:
        return "脊髄"
    if end["open_riichi"]:
        return "オープン立直"
    if end["riichi"]:
        return "立直"
    if any(m in ("pon", "chi", "minkan", "kakan") for m in end["melds"]):
        return "鳴き"
    return "ダマ"


def bucket(points: int) -> str:
    for limit, label in ((8000, "〜8千"), (24000, "〜2.4万"), (48000, "〜4.8万"), (96000, "〜9.6万")):
        if points <= limit:
            return label
    return "9.6万超"


def analyze(path: Path, focus: list[str]) -> None:
    seats = Counter()           # AI → 着席数（半荘）
    rounds = Counter()          # AI → 局数
    flow = defaultdict(Counter)  # AI → 区分 → 点数合計
    final = Counter()
    ranks = defaultdict(Counter)
    deal_in = defaultdict(Counter)        # AI → 相手の手の種類 → 回数
    deal_in_pts = defaultdict(Counter)    # AI → 相手の手の種類 → 失点
    deal_in_state = defaultdict(Counter)  # AI → 放銃時の自分の状態 → 回数
    deal_in_state_pts = defaultdict(Counter)
    deal_in_size = defaultdict(Counter)
    win_type = defaultdict(Counter)
    win_pts = defaultdict(Counter)
    win_size = defaultdict(Counter)
    route = defaultdict(Counter)          # AI → 自分の局の進め方 → 局数
    route_pts = defaultdict(Counter)      # AI → 進め方 → その局の収支
    route_win = defaultdict(Counter)
    route_dealin = defaultdict(Counter)
    push = defaultdict(Counter)           # 立直を受けたときの押し引き
    tobi = Counter()
    draw_tenpai = defaultdict(Counter)

    with gzip.open(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            row = json.loads(line)
            seating = row["seating"]
            values = row["values"]
            ends = row["end"]
            if "match_end" in row:
                me = row["match_end"]
                for seat, kind in enumerate(seating):
                    seats[kind] += 1
                    final[kind] += me["final"][seat]
                    ranks[kind][me["ranking"].index(seat)] += 1
                    tobi[kind] += me["scores"][seat] < 0

            # --- 点数の出入り（局の精算だけ。飛び賞・オカは最終得点のほうに入る） ---
            delta = Counter()
            ron_from: dict[int, int] = {}
            for event in row["events"]:
                if event["a"] == "ron":
                    ron_from[event["s"]] = event["from"]
            for payer, receiver, amount in row["transfers"]:
                delta[payer] -= amount
                delta[receiver] += amount
                pk, rk = seating[payer], seating[receiver]
                if row["kind"] == "draw":
                    flow[pk]["ノーテン罰符"] -= amount
                    flow[rk]["ノーテン罰符"] += amount
                    continue
                if row["fever_wins"]:
                    kind_label = "フィーバー"
                elif receiver in row["winners"]:
                    kind_label = None
                else:
                    kind_label = "その他"
                is_ron = receiver in ron_from
                if kind_label == "フィーバー":
                    flow[rk]["和了（フィーバー）"] += amount
                    flow[pk]["フィーバーへの支払い"] -= amount
                elif is_ron:
                    flow[rk]["和了（ロン）"] += amount
                    flow[pk]["放銃"] -= amount
                else:
                    flow[rk]["和了（ツモ）"] += amount
                    flow[pk]["被ツモ"] -= amount
            for seat_text, amount in row["pot"].items():
                seat = int(seat_text)
                delta[seat] += amount
                flow[seating[seat]]["供託・ご祝儀"] += amount

            for seat, kind in enumerate(seating):
                rounds[kind] += 1

            # --- 和了 ---
            for seat in row["winners"]:
                kind = seating[seat]
                value = values.get(str(seat))
                label = hand_type(ends[seat], value)
                win_type[kind][label] += 1
                win_pts[kind][label] += delta[seat]
                win_size[kind][bucket(delta[seat])] += 1

            # --- 放銃 ---
            for winner, discarder in ron_from.items():
                kind = seating[discarder]
                label = hand_type(ends[winner], values.get(str(winner)))
                lost = -sum(a for p, r, a in row["transfers"] if p == discarder and r == winner)
                deal_in[kind][label] += 1
                deal_in_pts[kind][label] += -lost
                deal_in_size[kind][bucket(-lost)] += 1
                # 放銃した打牌の時点の自分の状態
                last = None
                for event in row["events"]:
                    if event["s"] == discarder and "sh" in event and event["p"] in ("draw", "discard"):
                        last = event
                me = ends[discarder]
                if me["riichi"]:
                    state = "自分も立直"
                elif last is None:
                    state = "不明"
                else:
                    sh = last["sh"]
                    if last.get("thr"):
                        state = f"脅威あり・{min(sh, 3)}向聴" + ("（現物あり）" if last.get("safe_avail") else "")
                    else:
                        state = f"脅威なし・{min(sh, 3)}向聴"
                deal_in_state[kind][state] += 1
                deal_in_state_pts[kind][state] += -lost

            # --- 立直を受けたときの押し引き（打牌ごと） ---
            for event in row["events"]:
                if "safe" in event:
                    kind = seating[event["s"]]
                    sh = min(event["sh"], 3)
                    if event["safe_avail"]:
                        push[kind][(sh, "現物" if event["safe"] else "現物以外")] += 1

            # --- 局ごとの進め方 ---
            for seat, kind in enumerate(seating):
                me = ends[seat]
                if me["fever"]:
                    way = "フィーバー"
                elif me["open_riichi"]:
                    way = "オープン立直"
                elif me["riichi"]:
                    way = "立直"
                elif any(m in ("pon", "chi", "minkan", "kakan") for m in me["melds"]):
                    way = "鳴き"
                else:
                    way = "門前（立直せず）"
                route[kind][way] += 1
                route_pts[kind][way] += delta[seat]
                route_win[kind][way] += seat in row["winners"]
                route_dealin[kind][way] += seat in ron_from.values()
                if row["kind"] == "draw":
                    draw_tenpai[kind]["局"] += 1
                    draw_tenpai[kind]["テンパイ"] += seat in row["tenpai"]

    kinds = [k for k in KINDS if seats[k]] if not focus else focus
    label = lambda k: AI_LABELS[k]  # noqa: E731

    def table(title, rows_by_kind, keys, fmt):
        print(f"\n■ {title}")
        print("  " + "".ljust(18) + "".join(label(k).rjust(12) for k in kinds))
        for key in keys:
            print("  " + str(key).ljust(18) + "".join(fmt(rows_by_kind, k, key).rjust(14) for k in kinds))

    print(f"牌譜: {path}  半荘 {sum(seats.values()) // 3:,} / 局 {sum(rounds.values()) // 3:,}")
    print("\n■ 成績（1半荘あたり）")
    for k in kinds:
        n = seats[k]
        r = ranks[k]
        print(
            f"  {label(k):8} 平均最終得点 {final[k] / n:+8,.0f}  1位 {r[0] / n:5.1%}  2位 {r[1] / n:5.1%}"
            f"  3位 {r[2] / n:5.1%}  飛び {tobi[k] / n:5.1%}  局数 {rounds[k] / n:.2f}"
        )

    flow_keys = ["和了（ロン）", "和了（ツモ）", "和了（フィーバー）", "放銃", "被ツモ",
                 "フィーバーへの支払い", "ノーテン罰符", "供託・ご祝儀"]
    table("点数の出入り（1局あたり・点）", flow, flow_keys,
          lambda d, k, key: f"{d[k][key] / rounds[k]:+,.0f}")
    print("  " + "合計".ljust(18) + "".join(f"{sum(flow[k].values()) / rounds[k]:+,.0f}".rjust(14) for k in kinds))

    types = ["ダマ", "立直", "オープン立直", "鳴き", "脊髄", "フィーバー"]
    table("和了（100局あたりの回数 / 1回の平均点）", win_type, types,
          lambda d, k, key: f"{d[k][key] / rounds[k] * 100:5.2f} / {win_pts[k][key] / max(1, d[k][key]):>7,.0f}")
    table("放銃した相手の手（100局あたりの回数 / 1回の平均失点）", deal_in, types,
          lambda d, k, key: f"{d[k][key] / rounds[k] * 100:5.2f} / {deal_in_pts[k][key] / max(1, d[k][key]):>7,.0f}")
    sizes = ["〜8千", "〜2.4万", "〜4.8万", "〜9.6万", "9.6万超"]
    table("和了1回の収入の分布（100局あたり）", win_size, sizes,
          lambda d, k, key: f"{d[k][key] / rounds[k] * 100:.2f}")
    table("放銃1回の失点の分布（100局あたり）", deal_in_size, sizes,
          lambda d, k, key: f"{d[k][key] / rounds[k] * 100:.2f}")

    states = sorted({s for k in kinds for s in deal_in_state[k]})
    table("放銃した打牌の時点の自分（100局あたりの回数 / 1回の平均失点）", deal_in_state, states,
          lambda d, k, key: f"{d[k][key] / rounds[k] * 100:5.2f} / {deal_in_state_pts[k][key] / max(1, d[k][key]):>7,.0f}")

    ways = ["門前（立直せず）", "立直", "オープン立直", "鳴き", "フィーバー"]
    table("局の進め方: 割合", route, ways, lambda d, k, key: f"{d[k][key] / rounds[k]:.1%}")
    table("局の進め方: その局の平均収支", route_pts, ways,
          lambda d, k, key: f"{d[k][key] / max(1, route[k][key]):+,.0f}")
    table("局の進め方: 和了率 / 放銃率", route_win, ways,
          lambda d, k, key: f"{d[k][key] / max(1, route[k][key]):.0%} / {route_dealin[k][key] / max(1, route[k][key]):.0%}")

    print("\n■ 立直を受けて、現物があるのに現物以外を切った割合（向聴数別）")
    for k in kinds:
        cells = []
        for sh in range(4):
            safe = push[k][(sh, "現物")]
            other = push[k][(sh, "現物以外")]
            total = safe + other
            cells.append(f"{sh}向聴 {other / total:4.0%}（{total:,}打）" if total else f"{sh}向聴 -")
        print(f"  {label(k):8} " + "  ".join(cells))

    print("\n■ 流局時のテンパイ率")
    for k in kinds:
        d = draw_tenpai[k]
        print(f"  {label(k):8} {d['テンパイ'] / max(1, d['局']):.0%}（{d['局']:,}局）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("per_table", type=int)
    rec.add_argument("--seed", type=int, default=1)
    rec.add_argument("--out", type=Path, default=Path("paifu/league.jsonl.gz"))
    rec.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ana = sub.add_parser("analyze")
    ana.add_argument("path", type=Path)
    ana.add_argument("--ai", default="", help="カンマ区切りで AI を絞る")
    args = parser.parse_args()
    if args.command == "record":
        record(args.per_table, args.seed, args.out, args.workers)
    else:
        analyze(args.path, [k for k in args.ai.split(",") if k])


if __name__ == "__main__":
    main()
