"""ターミナルで人間が打つための打ち手。"""

from __future__ import annotations

from ..core import hidden
from ..core.game import Action, ActionType, Round
from ..ui import cui


class HumanCuiAgent:
    """卓の状況を表示して、番号で手を選ばせる。

    ルールエンジンの選択肢は「牌の種類」単位で重複しないが、それをそのまま並べると
    「手牌は14枚なのに候補が11個しかない」と見えて紛らわしい。ここで手牌の枚数どおりに
    展開し、0番をツモ牌にしている。立直は番号を占有しないよう、牌を選んだあとに聞く。

    番号の代わりに隠しコマンド（fever / benz）を入力すると on_command が呼ばれる。
    """

    def __init__(self, on_command=None) -> None:
        self.on_command = on_command

    def choose(self, game: Round, seat: int, options: list[Action]) -> Action:
        if len(options) == 1:
            # 選択の余地が無いときは聞かない（フィーバー中の強制ツモ切りなど）
            return options[0]

        entries = cui.build_menu(game, seat, options)
        print()
        print(cui.render_menu(game, seat, entries))

        entry = self._ask_entry(entries)
        if entry.action.type is ActionType.DISCARD:
            kita = cui.kita_choice(options, entry.action.tile)
            if kita is not None:
                chosen = self._ask_kita(entry.action, kita)
                if chosen.type is ActionType.KITA:
                    return chosen
            riichi = cui.riichi_choices(options, entry.action.tile)
            if riichi:
                return self._ask_riichi(entry.action, riichi)
        return entry.action

    def _ask_entry(self, entries: list[cui.MenuEntry]) -> cui.MenuEntry:
        last = len(entries) - 1
        while True:
            raw = input(f"番号を選んでください (0-{last}): ").strip()
            if self.on_command is not None and raw.lower() in hidden.COMMANDS:
                if self.on_command(raw.lower()):
                    print(f"（隠しコマンド: 次の配牌で{hidden.DESCRIPTIONS[raw.lower()]}）")
                continue
            if not raw.isdigit() or not 0 <= int(raw) <= last:
                print("入力が正しくありません。")
                continue
            entry = entries[int(raw)]
            if not entry.selectable:
                print(f"その牌は選べません（{entry.note}）。")
                continue
            return entry

    def _ask_kita(self, discard: Action, kita: Action) -> Action:
        """北を選んだときに、抜きドラにするか河に捨てるかを聞く。"""
        choices = {"k": kita, "s": discard}
        while True:
            raw = input("  k=抜きドラにする / s=河に捨てる: ").strip().lower()
            if raw in choices:
                return choices[raw]
            print("  入力が正しくありません。")

    def _ask_riichi(self, discard: Action, riichi: list[Action]) -> Action:
        choices: dict[str, Action] = {"n": discard}
        prompt = ["n=立直しない"]
        for action in riichi:
            if action.type is ActionType.RIICHI:
                choices["r"] = action
                prompt.append("r=立直")
            else:
                choices["o"] = action
                prompt.append("o=オープン立直")
        while True:
            raw = input(f"  {' / '.join(prompt)}: ").strip().lower()
            if raw in choices:
                return choices[raw]
            print("  入力が正しくありません。")
