# ブラウザ版

ブラウザの中で Python（[Pyodide](https://pyodide.org/)）を動かし、`fever_sanma` のルールエンジンと CPU をそのまま使う。
画面は `app.js`、進行は `fever_sanma/ui/web.py`（`WebSession`）。

## 手元で動かす

```bash
python tools/build_web.py                       # _site/ に組み立てる
python -m http.server 8765 --directory _site    # http://localhost:8765 を開く
```

`main` に push すると GitHub Actions（`.github/workflows/pages.yml`）がテストを通してから GitHub Pages に公開する。

## ランキング（Supabase）の設定

`config.js` が空のあいだはランキングのボタンも登録フォームも出ない。

1. [Supabase](https://supabase.com/) で無料のプロジェクトを作る
2. 左メニューの **SQL Editor** を開き、`web/supabase.sql` の中身を貼り付けて **Run**
3. **Project Settings → API Keys**（または Data API）で次の2つを控える
   - Project URL（`https://xxxx.supabase.co`）
   - publishable key（`sb_publishable_...`。古い画面では anon public key）
4. `web/config.js` の `supabaseUrl` と `supabaseKey` に入れて push する

publishable key はブラウザに置く前提の公開してよい鍵で、できるのは `supabase.sql` で許した
「成績を読む」「成績を追加する」だけ。**service_role key（secret key）は絶対に入れないこと。**

登録した成績は自己申告なので、書き換えれば偽の記録も送れる（身内で遊ぶ前提）。
変な記録を消すときは Supabase の **Table Editor** で `results` の行を削除する。
