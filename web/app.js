// フィーバー三麻 ブラウザ版の画面。
//
// ゲームの進行はすべて Python（fever_sanma/ui/web.py の WebSession）が持つ。
// ここは「view を描く」「クリックを Python に渡す」「tick() を時間差で呼ぶ」だけを担当する。

let pyodide = null;
let web = null;       // Python モジュール fever_sanma.ui.web
let session = null;   // WebSession
let faces = [];       // 牌番号 → {top, bottom, color}
let timer = null;
let lastView = null;

const $ = (id) => document.getElementById(id);

async function boot() {
  const text = $("loading-text");
  try {
    text.textContent = "Python を読み込み中…（初回は十数秒かかります）";
    pyodide = await loadPyodide();
    text.textContent = "ゲームを読み込み中…";
    const response = await fetch("fever_sanma.zip", { cache: "no-cache" }) // 毎回サーバーに更新を確かめる;
    if (!response.ok) throw new Error(`fever_sanma.zip を取得できませんでした (${response.status})`);
    pyodide.unpackArchive(await response.arrayBuffer(), "zip", { extractDir: "/home/pyodide/app" });
    pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
    web = pyodide.pyimport("fever_sanma.ui.web");
    faces = JSON.parse(web.faces_json());
  } catch (error) {
    text.textContent = "読み込みに失敗しました: " + error;
    throw error;
  }
  $("loading").hidden = true;
  $("table").hidden = false;
  $("new-match").addEventListener("click", newMatch);
  document.addEventListener("keydown", onKey);
  $("update").addEventListener("click", () => location.reload());
  if (window.Ranking && Ranking.enabled()) {
    $("show-ranking").hidden = false;
    $("show-ranking").addEventListener("click", () => Ranking.show());
  }
  newMatch();
}

function newMatch() {
  checkForUpdate();
  if (session) session.destroy();
  $("log").textContent = "";
  session = web.WebSession($("ai").value);
  refresh();
  schedule(1);
}

// 「もう一度」はページを読み込み直さないので、タブを開いたままだと公開し直した版に
// 切り替わらない。対局を始めるたびにサーバーの版番号を確かめ、新しければ知らせる。
async function checkForUpdate() {
  if (!window.FEVER_BUILD || window.FEVER_BUILD.startsWith("__")) return;
  try {
    const response = await fetch("version.json", { cache: "no-store" });
    if (!response.ok) return;
    const { build } = await response.json();
    $("update").hidden = String(build) === window.FEVER_BUILD;
  } catch {
    // 確かめられなくても遊ぶのには困らない
  }
}

// --- 進行 -------------------------------------------------------------------

function stepMs() {
  return Number($("speed").value);
}

function schedule(steps) {
  // 予約は常に1本だけ（tkinter 版の _schedule と同じ理由）
  clearTimeout(timer);
  timer = setTimeout(run, steps * stepMs());
}

function run() {
  timer = null;
  const steps = session.tick();
  refresh();
  if (steps !== undefined && steps !== null) schedule(steps);
}

function afterInput() {
  refresh();
  schedule(0);
}

function onKey(event) {
  if (!session || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target instanceof HTMLInputElement) return;
  if (session.key(event.key)) refresh();
}

// --- 描画 -------------------------------------------------------------------

function refresh() {
  const view = JSON.parse(session.view_json());
  lastView = view;
  renderInfo(view);
  $("banner").textContent = view.banner;
  const human = view.human;
  const others = [(human + 1) % 3, (human + 2) % 3];
  const opponents = $("opponents");
  opponents.replaceChildren(...others.map((seat) => renderPlayer(view.players[seat], false)));
  $("self").replaceChildren(...renderPlayer(view.players[human], true).childNodes);
  $("prompt").textContent = view.prompt;
  renderButtons(view);
  appendLog(view.log);
  renderDialog(view);
}

function renderInfo(view) {
  const info = $("info");
  const parts = [
    span(`東${view.info.round}局`),
    span(`残り ${view.info.remaining}枚`),
    span(`供託 ${view.info.sticks}本`),
    span("ドラ表示:"),
    tilesBox(view.info.dora),
  ];
  if (view.info.ura.length) parts.push(span("裏ドラ表示:"), tilesBox(view.info.ura));
  info.replaceChildren(...parts);
}

function renderPlayer(player, isOwn) {
  const panel = document.createElement("div");
  panel.className = "panel" + (isOwn ? " own" : "");

  const header = document.createElement("div");
  header.className = "header" + (player.turn ? " turn" : "");
  header.textContent =
    `${player.label}  ${player.score.toLocaleString()}点  [${player.marks.join(" / ")}]`;
  panel.append(header);

  const river = document.createElement("div");
  river.className = "river";
  river.append(span("河"));
  const riverTiles = document.createElement("div");
  riverTiles.className = "tiles";
  for (const item of player.river) {
    riverTiles.append(tileElement(item.tile, item.mark ? `mark-${item.mark}` : ""));
  }
  river.append(riverTiles);
  panel.append(river);

  const row = document.createElement("div");
  row.className = "hand-row";
  const concealed = document.createElement("div");
  concealed.className = "concealed";
  if (player.hand === null) {
    for (let i = 0; i < player.hidden; i++) concealed.append(backTile());
  } else if (isOwn) {
    for (const item of player.hand) concealed.append(ownTile(item));
  } else {
    for (const item of player.hand) concealed.append(tileElement(item.tile));
  }
  row.append(concealed);

  if (player.kita) {
    row.append(meldElement(`抜きドラ ×${player.kita}`, Array(player.kita).fill(23)));
  }
  for (const meld of player.melds) row.append(meldElement(meld.label, meld.tiles));
  panel.append(row);
  return panel;
}

function ownTile(item) {
  const element = tileElement(item.tile, "big");
  if (item.drawn) element.classList.add("drawn");
  if (item.playable) {
    element.classList.add("playable");
    element.addEventListener("click", () => {
      if (session.click_tile(item.tile)) afterInput();
    });
  } else if (hasHumanChoice()) {
    element.classList.add("blocked"); // 自分の番なのに切れない牌（喰い替え禁止・立直の宣言牌選び）
  }
  return element;
}

function hasHumanChoice() {
  const own = lastView.players[lastView.human].hand || [];
  return own.some((item) => item.playable) || lastView.buttons.length > 0;
}

function renderButtons(view) {
  const box = $("buttons");
  box.replaceChildren(
    ...view.buttons.map((button) => {
      const element = document.createElement("button");
      element.type = "button";
      element.textContent = button.label;
      if (button.active) element.classList.add("active");
      element.addEventListener("click", () => {
        session.press(button.id);
        afterInput();
      });
      return element;
    })
  );
}

function appendLog(lines) {
  if (!lines.length) return;
  const log = $("log");
  log.textContent += lines.join("\n") + "\n";
  log.scrollTop = log.scrollHeight;
}

function renderDialog(view) {
  const overlay = $("dialog");
  const dialog = view.dialog;
  if (!dialog) {
    overlay.hidden = true;
    return;
  }
  // 同じポップアップを描き直さない（ランキングの名前入力が消えないように）
  const key = dialog.title + "\n" + dialog.text;
  if (!overlay.hidden && overlay.dataset.key === key) return;
  overlay.dataset.key = key;
  $("dialog-title").textContent = dialog.title;
  $("dialog-text").textContent = dialog.text;
  const extra = $("dialog-extra");
  extra.replaceChildren(...(dialog.hands || []).map(winningHandElement));
  if (view.state === "match_end" && view.result && window.Ranking && Ranking.enabled()) {
    extra.append(Ranking.submitForm(view.result));
  }
  $("dialog-buttons").replaceChildren(
    ...dialog.buttons.map((label, index) => {
      const element = document.createElement("button");
      element.type = "button";
      element.textContent = label;
      element.addEventListener("click", () => {
        overlay.hidden = true;
        session.dialog_button(index);
        afterInput();
      });
      return element;
    })
  );
  overlay.hidden = false;
  overlay.querySelector("button")?.focus();
}

// 和了形を牌の絵で見せる（点数が妥当か確かめられるように）。和了牌は少し離して色を変える
function winningHandElement(hand) {
  const box = document.createElement("div");
  box.className = "win-hand";
  box.append(span(`${hand.label}の和了形（和了牌: ${faces[hand.win_tile].top}${faces[hand.win_tile].bottom} ${hand.how}）`));
  const row = document.createElement("div");
  row.className = "hand-row";
  const concealed = document.createElement("div");
  concealed.className = "concealed";
  for (const tile of hand.concealed) concealed.append(tileElement(tile));
  concealed.append(tileElement(hand.win_tile, "win-tile"));
  row.append(concealed);
  if (hand.kita) row.append(meldElement(`抜きドラ ×${hand.kita}`, Array(hand.kita).fill(23)));
  for (const meld of hand.melds) row.append(meldElement(meld.label, meld.tiles));
  box.append(row);
  return box;
}

// --- 部品 -------------------------------------------------------------------

function span(text) {
  const element = document.createElement("span");
  element.textContent = text;
  return element;
}

function tilesBox(tiles) {
  const box = document.createElement("span");
  box.className = "tiles";
  for (const tile of tiles) box.append(tileElement(tile));
  return box;
}

function tileElement(tile, extraClass = "") {
  const face = faces[tile];
  const element = document.createElement("div");
  element.className = "tile" + (extraClass ? " " + extraClass : "");
  element.style.color = face.color;
  const top = document.createElement("span");
  top.textContent = face.top;
  element.append(top);
  if (face.bottom) {
    const bottom = document.createElement("span");
    bottom.textContent = face.bottom;
    element.append(bottom);
  }
  return element;
}

function backTile() {
  const element = document.createElement("div");
  element.className = "tile back";
  return element;
}

function meldElement(label, tiles) {
  const box = document.createElement("div");
  box.className = "meld";
  box.append(span(label));
  const row = document.createElement("div");
  row.className = "tiles";
  for (const tile of tiles) row.append(tileElement(tile));
  box.append(row);
  return box;
}

boot();
