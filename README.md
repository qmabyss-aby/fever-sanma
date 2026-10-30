# フィーバー三麻

ローカルルール三人麻雀「フィーバー三麻」の対局プログラムです。
ルールは [フィーバー三麻 Wiki](https://wiki3.jp/fever_sanma) に従います（詳細は [CLAUDE.md](CLAUDE.md)）。

## ブラウザで遊ぶ

https://qmabyss-aby.github.io/fever-sanma/ （インストール不要。初回の読み込みに十数秒かかります）

仕組みとランキングの設定は [web/README.md](web/README.md) を参照。

## 手元で遊ぶ

Python 3.12 以上が必要です。

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows（macOS/Linux は source .venv/bin/activate）
pip install -r requirements.txt
python -m fever_sanma            # GUI で対局（あなた + CPU 2人）
python -m fever_sanma --cui      # ターミナルで対局
python -m fever_sanma --ai any   # CPU 2人をランダムに選ぶ
```

CPU の種類（`--ai`）: `strong`（最強CPU）/ `normal`（普通CPU）/ `sekizui`（脊髄狙い）/ `value`（高打点狙い）/ `defense`（守備型）/ `random`

## CPU の比較

```bash
python -m fever_sanma --league 100   # 4種の CPU を総当たりで対戦させる
```

## テスト

```bash
python -m pytest
```
