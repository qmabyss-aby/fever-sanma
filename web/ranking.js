// ランキング（身内向け）。終局時に名前を入れて成績を登録し、一覧を見られる。
//
// 送るのは自己申告の成績なので、書き換えれば偽の記録も登録できる。身内で楽しむ前提の作り。
// 保存先は Supabase の results テーブル（web/supabase.sql）。

window.Ranking = (() => {
  const config = window.FEVER_CONFIG || {};
  const NAME_KEY = "fever-sanma-name";
  const MIN_GAMES = 5; // 平均・トップ率の表に載る最低対局数
  const VERSION = "web-1";

  const enabled = () => Boolean(config.supabaseUrl && config.supabaseKey);

  async function request(path, options = {}) {
    const response = await fetch(`${config.supabaseUrl}/rest/v1/${path}`, {
      ...options,
      headers: {
        apikey: config.supabaseKey,
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    if (!response.ok) throw new Error(`${response.status} ${text}`);
    // 登録（POST）は成否をステータスだけで判断し、本文は読まない。return=minimal の本文は
    // 空のはずだが、環境によっては空白などが混ざって JSON として読めないことがあった。
    if ((options.method || "GET") !== "GET") return null;
    return JSON.parse(text);
  }

  function savedName() {
    try {
      return localStorage.getItem(NAME_KEY) || "";
    } catch {
      return "";
    }
  }

  function saveName(name) {
    try {
      localStorage.setItem(NAME_KEY, name);
    } catch {
      // 保存できなくても登録自体はできる
    }
  }

  // 終局ポップアップに差し込む登録フォーム
  function submitForm(result) {
    const box = document.createElement("div");
    const form = document.createElement("form");
    form.className = "ranking-form";
    const input = document.createElement("input");
    input.maxLength = 20;
    input.placeholder = "名前";
    input.value = savedName();
    input.required = true;
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "ランキングに登録";
    const status = document.createElement("span");
    form.append(input, button, status);
    box.append(form);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = input.value.trim();
      if (!name) return;
      button.disabled = true;
      status.textContent = "登録中…";
      try {
        await request("results", {
          method: "POST",
          headers: { Prefer: "return=minimal" },
          body: JSON.stringify({
            name,
            raw_score: result.raw,
            final_score: result.final,
            rank: result.rank,
            opponents: result.opponents.join(" / "),
            version: VERSION,
          }),
        });
        saveName(name);
        input.disabled = true;
        status.textContent = "登録しました";
      } catch (error) {
        button.disabled = false;
        status.textContent = "登録に失敗しました: " + error.message;
      }
    });
    return box;
  }

  const TABS = [
    {
      label: "最高素点",
      path: "results?select=name,raw_score,opponents,created_at&order=raw_score.desc&limit=20",
      columns: ["順位", "名前", "素点", "対戦相手", "日付"],
      row: (r) => [r.name, r.raw_score.toLocaleString(), r.opponents, day(r.created_at)],
    },
    {
      label: "平均最終得点",
      path: `player_stats?select=*&games=gte.${MIN_GAMES}&order=avg_final.desc&limit=20`,
      columns: ["順位", "名前", "平均", "対局数", "トップ率"],
      row: (r) => [r.name, signed(r.avg_final), r.games, `${r.top_rate}%`],
      note: `${MIN_GAMES}局以上打った人だけを載せています`,
    },
    {
      label: "トップ率",
      path: `player_stats?select=*&games=gte.${MIN_GAMES}&order=top_rate.desc&limit=20`,
      columns: ["順位", "名前", "トップ率", "対局数", "平均"],
      row: (r) => [r.name, `${r.top_rate}%`, r.games, signed(r.avg_final)],
      note: `${MIN_GAMES}局以上打った人だけを載せています`,
    },
    {
      label: "対局数",
      path: "player_stats?select=*&order=games.desc&limit=20",
      columns: ["順位", "名前", "対局数", "平均", "最高素点"],
      row: (r) => [r.name, r.games, signed(r.avg_final), r.best_raw.toLocaleString()],
    },
  ];

  const day = (iso) => new Date(iso).toLocaleDateString("ja-JP");
  const signed = (n) => (n > 0 ? "+" : "") + Number(n).toLocaleString();

  async function show(index = 0) {
    const overlay = document.getElementById("ranking");
    const body = document.getElementById("ranking-body");
    const tabs = document.getElementById("ranking-tabs");
    overlay.hidden = false;
    tabs.replaceChildren(
      ...TABS.map((tab, i) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = tab.label;
        if (i === index) button.classList.add("active");
        button.addEventListener("click", () => show(i));
        return button;
      })
    );
    const tab = TABS[index];
    body.textContent = "読み込み中…";
    try {
      const rows = await request(tab.path);
      const table = document.createElement("table");
      table.className = "ranking-table";
      const head = table.insertRow();
      for (const column of tab.columns) {
        const th = document.createElement("th");
        th.textContent = column;
        head.append(th);
      }
      rows.forEach((r, i) => {
        const tr = table.insertRow();
        for (const value of [i + 1, ...tab.row(r)]) tr.insertCell().textContent = value;
      });
      const parts = [];
      if (tab.note) {
        const note = document.createElement("p");
        note.className = "ranking-note";
        note.textContent = tab.note;
        parts.push(note);
      }
      parts.push(rows.length ? table : document.createTextNode("まだ記録がありません"));
      body.replaceChildren(...parts);
    } catch (error) {
      body.textContent = "読み込みに失敗しました: " + error.message;
    }
  }

  function hide() {
    document.getElementById("ranking").hidden = true;
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("ranking-close")?.addEventListener("click", hide);
  });

  return { enabled, submitForm, show, hide };
})();
