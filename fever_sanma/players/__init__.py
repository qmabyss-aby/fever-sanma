"""打ち手（人間 / CPU）。"""

import random

from .base import Agent
from .defensive_ai import DefensiveAgent
from .normal_ai import NormalAgent
from .random_ai import RandomAgent
from .sekizui_ai import SekizuiAgent
from .strong_ai import StrongAgent
from .value_ai import ValueAgent

__all__ = [
    "Agent",
    "RandomAgent",
    "StrongAgent",
    "NormalAgent",
    "SekizuiAgent",
    "ValueAgent",
    "DefensiveAgent",
    "HumanCuiAgent",
    "AI_KINDS",
    "AI_LABELS",
    "make_cpu",
    "parse_ai_kinds",
    "resolve_ai_kinds",
    "RANDOM_PICK",
    "PICKABLE_KINDS",
]

AI_KINDS = ("strong", "normal", "sekizui", "value", "defense", "random")
"""選べる CPU の種類。先頭が既定。"""

AI_LABELS = {
    "strong": "最強CPU",
    "normal": "普通CPU",
    "sekizui": "脊髄狙い",
    "value": "高打点狙い",
    "defense": "守備型",
    "random": "ランダム",
}


def make_cpu(kind: str = "strong", rng: random.Random | None = None) -> Agent:
    """CPU の打ち手を作る。"""
    if kind == "strong":
        return StrongAgent(rng)
    if kind == "normal":
        return NormalAgent(rng)
    if kind == "sekizui":
        return SekizuiAgent(rng)
    if kind == "value":
        return ValueAgent(rng)
    if kind == "defense":
        return DefensiveAgent(rng)
    if kind == "random":
        return RandomAgent(rng)
    raise ValueError(f"不明な CPU: {kind!r}")


RANDOM_PICK = "any"
"""「この席の CPU はランダムに選ぶ」という指定。"""

PICKABLE_KINDS = ("strong", "normal", "sekizui", "value", "defense")
"""ランダムに選ぶ対象。弱いランダム打ちは入れない。"""


def parse_ai_kinds(text: str) -> list[str]:
    """"strong,sekizui" のようなカンマ区切りを CPU の種類のリストにする。

    "any" はその席をランダムに選ぶ指定として、そのまま残す（`resolve_ai_kinds` で決める）。
    """
    kinds = [part.strip() for part in text.split(",") if part.strip()]
    unknown = [kind for kind in kinds if kind not in AI_KINDS and kind != RANDOM_PICK]
    if not kinds or unknown:
        choices = ", ".join((*AI_KINDS, RANDOM_PICK))
        raise ValueError(f"CPU の種類は {choices} から選んでください: {text!r}")
    return kinds


def resolve_ai_kinds(kinds: list[str], count: int, rng: random.Random) -> list[str]:
    """count 人ぶんの CPU の種類を決める。"any" の席は、まだ選ばれていない種類から選ぶ。

    count より短い指定は繰り返して使う（"any" だけなら全員ランダム）。
    """
    wanted = [kinds[index % len(kinds)] for index in range(count)]
    fixed = [kind for kind in wanted if kind != RANDOM_PICK]
    pool = [kind for kind in PICKABLE_KINDS if kind not in fixed]
    picks = iter(rng.sample(pool, min(len(pool), wanted.count(RANDOM_PICK))))
    return [
        (next(picks, None) or rng.choice(PICKABLE_KINDS)) if kind == RANDOM_PICK else kind
        for kind in wanted
    ]


def __getattr__(name: str):
    # human_cui は ui に依存するので、使うときだけ読み込む
    if name == "HumanCuiAgent":
        from .human_cui import HumanCuiAgent

        return HumanCuiAgent
    raise AttributeError(name)
