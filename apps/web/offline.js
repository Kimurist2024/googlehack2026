// ネットが落ちても授業を止めないための画面の部品。app.js の後に読み、その関数と変数（api、make、assignmentId など）を使う。
//   ① クラウド：授業パッケージを保存する、校内LANの結果を取り込む
//   ② 校内LAN版：授業パッケージを取り込んで受付を始める、結果を書き出す
//   ③ 生徒の端末：送れなかった解答をためておき、つながったら送る

const PENDING_KEY = "mushitori.pending.v1";
const PENDING_LIMIT = 5;
const FLUSH_INTERVAL_MS = 30000; // ためた解答を送り直す間隔

// --- Service Worker：画面をオフラインでも開けるようにする ---
// CSP で Trusted Types を必須にしているので、登録する URL は app.js のポリシー（trustedScriptURL）を通す
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register(trustedScriptURL("/sw.js")).catch(() => {});
}

// --- ③ 送れなかった解答 ---

function readPending() {
  try {
    const items = JSON.parse(localStorage.getItem(PENDING_KEY) || "[]");
    return Array.isArray(items) ? items : [];
  } catch {
    return [];
  }
}

function writePending(items) {
  try {
    if (items.length) localStorage.setItem(PENDING_KEY, JSON.stringify(items.slice(-PENDING_LIMIT)));
    else localStorage.removeItem(PENDING_KEY);
  } catch {
    // 保存できない端末（プライベートモードなど）では、ためられない
  }
}

function offlineBanner(text) {
  let banner = document.getElementById("offline-banner");
  if (!banner) {
    banner = make("p", "", "card offline-banner");
    banner.id = "offline-banner";
    banner.setAttribute("role", "status");
    document.querySelector("main").prepend(banner);
  }
  banner.textContent = text;
  banner.hidden = !text;
}

// app.js の解答の送信が通信の失敗で止まったときに呼ばれる。ためたら true を返す
function queueOfflineAnswers(error, assignment, token, answers) {
  if (!(error instanceof TypeError) || !assignment || !token) return false;
  const pending = readPending().filter((item) => item.assignment !== assignment || item.token !== token);
  pending.push({ assignment, token, answers, answered_at: Date.now() / 1000 });
  writePending(pending);
  clearInterval(timerHandle);
  $("quiz").hidden = true;
  offlineBanner("通信できないため、解答をこの端末に保存しました。つながると自動で送ります。この画面は閉じても大丈夫です。");
  return true;
}

let flushing = false;
async function flushOfflineAnswers() {
  const pending = readPending();
  if (flushing || !pending.length) return;
  flushing = true;
  const remaining = [];
  const messages = [];
  for (const item of pending) {
    try {
      const response = await fetch(`/v1/assignments/${item.assignment}/attempt:submit-offline`, {
        method: "POST",
        headers: { Authorization: `Bearer ${item.token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ answers: item.answers, answered_at: item.answered_at }),
      });
      if (response.ok) {
        const result = await response.json();
        const lead = result.already_submitted ? "保存していた解答は、すでに届いていました" : "保存していた解答を送りました";
        messages.push(`${lead}（${result.total}問中 ${result.score}問 正解）。`);
      } else if (response.status === 429 || response.status >= 500) {
        remaining.push(item);
      } else {
        // 提出済み、期限切れなどは送り直しても通らないので、端末からも消す
        messages.push("保存していた解答は受け付けられませんでした。先生に伝えてください。");
      }
    } catch {
      remaining.push(item);
    }
  }
  writePending(remaining);
  flushing = false;
  if (messages.length) offlineBanner(messages.join(" "));
  else if (remaining.length) offlineBanner(`この端末に送れていない解答が${remaining.length}件あります。つながると自動で送ります。`);
}

window.addEventListener("online", flushOfflineAnswers);
setInterval(flushOfflineAnswers, FLUSH_INTERVAL_MS);
flushOfflineAnswers();

// --- ①② 教員の画面 ---

// ダウンロードを始めてから、ファイルの URL を手放すまでの待ち時間
const DOWNLOAD_URL_LIFETIME_MS = 1000;

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = make("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_URL_LIFETIME_MS);
}

function offlineCard(title, hint) {
  const card = make("div", undefined, "card");
  card.id = "offline-card";
  card.append(make("h2", title), make("p", hint, "hint"));
  const status = make("p", "", "status");
  status.setAttribute("role", "status");
  return { card, status };
}

function cloudCard() {
  const { card, status } = offlineCard(
    "ネット障害への備え",
    "授業の前に保存しておくと、ネットが落ちても教員のPCで授業を続けられます（校内LAN版）。解除コードはどこにも保存されないので、必ず控えてください。",
  );
  const save = make("button", "授業パッケージを保存");
  const code = make("p", "", "code");
  save.onclick = () => guarded(async () => {
    if (!assignmentId) throw new Error("先に問いを作ってください。");
    const pack = await teacherPost(`/v1/assignments/${assignmentId}/package`);
    download(pack.filename, pack.sealed, "application/octet-stream");
    code.textContent = `解除コード：${pack.unlock_code}`;
    status.textContent = `保存しました。${new Date(pack.not_after * 1000).toLocaleString("ja-JP")} まで使えます。`;
  });
  const label = make("label", "校内LANの結果を取り込む ");
  const file = make("input");
  file.type = "file";
  file.accept = ".json,application/json";
  file.onchange = () => guarded(async () => {
    if (!file.files.length) return;
    const results = JSON.parse(await file.files[0].text());
    const done = await teacherJson(`/v1/assignments/${results.assignment_id}/edge-results`, results);
    status.textContent = `${done.imported}人分を取り込みました（クラウドの正解で採点し直しています）。`;
    file.value = "";
  });
  label.append(file);
  const row = make("div", undefined, "row");
  row.append(save, label);
  card.append(row, code, status);
  return card;
}

function lanCard(state) {
  const { card, status } = offlineCard(
    "校内LANで授業を引き継ぐ",
    "クラウドで保存した授業パッケージと解除コードを入れると、このPCで受付を始めます。生徒は同じ授業コードと個人コードで入れます。",
  );
  const file = make("input");
  file.type = "file";
  file.accept = ".pack";
  const unlock = make("input");
  unlock.placeholder = "解除コード";
  unlock.autocomplete = "off";
  const load = make("button", "取り込む", "primary");
  const urls = make("p", "", "code");
  const showUrls = (list) => {
    urls.textContent = list.length ? `生徒が開くアドレス：${list.join("　")}` : "生徒が開くアドレスは、起動したときの表示を見てください。";
  };
  const useAssignment = (id) => {
    assignmentId = id;
    setButtons({ close: true });
  };
  load.onclick = () => guarded(async () => {
    if (!file.files.length) throw new Error("授業パッケージのファイルを選んでください。");
    // 教員の確認を先に済ませてから、ファイルと解除コードを読む（入力中に直したコードを使うため、この順を変えない）
    const imported = await api("/v1/edge/import", {
      method: "POST",
      headers: { ...(await teacherHeaders()), "Content-Type": "application/json" },
      body: JSON.stringify({ sealed: (await file.files[0].text()).trim(), unlock_code: unlock.value }),
    });
    useAssignment(imported.assignment_id);
    showUrls(imported.student_urls);
    unlock.value = "";
    status.textContent = `「${imported.title}」の受付を始めました。`;
  });
  const exportButton = make("button", "結果を書き出す");
  exportButton.onclick = () => guarded(async () => {
    if (!assignmentId) throw new Error("先に授業パッケージを取り込んでください。");
    const results = await teacherGet(`/v1/edge/results/${assignmentId}`);
    download(`mushitori-results-${assignmentId}.json`, JSON.stringify(results), "application/json");
    status.textContent = "書き出しました。ネットが戻ったら、クラウドの「校内LANの結果を取り込む」から入れてください。";
  });
  const row = make("div", undefined, "row");
  row.append(file, unlock, load, exportButton);
  card.append(row, urls, status);
  showUrls(state.student_urls);
  if (!state.key_configured) status.textContent = "クラウドの公開鍵（PACKAGE_PUBLIC_KEY）が設定されていないため、取り込めません。";
  if (state.assignments.length) {
    useAssignment(state.assignments[0].assignment_id);
    status.textContent = `「${state.assignments[0].title}」を受付中です。`;
  }
  return card;
}

async function setupOfflineCards() {
  let state;
  try {
    state = await api("/v1/edge/status");
  } catch {
    return; // 校内LAN版の生徒の端末では教員の情報を出さない
  }
  const work = $("teacher-work");
  if (state.mode === "lan") {
    // 問いを作る操作はクラウドでだけ行う
    for (const id of ["seed", "generate", "open"]) $(id).hidden = true;
    $("prepare-card").querySelector(".hint").textContent = "校内LAN版で動いています。インターネットには接続しません。";
    work.prepend(lanCard(state));
  } else {
    work.append(cloudCard());
  }
}

setupOfflineCards();
