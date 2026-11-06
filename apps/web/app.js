// 文字はすべて textContent で入れる。生徒のコードをHTMLとして解釈させない。
const $ = (id) => document.getElementById(id);
const REASONS = {
  too_long: "実行が終わらない", timeout: "実行が終わらない", error: "実行時にエラー", syntax_error: "文法エラー",
  nondeterministic: "実行ごとに結果が変わる", unsupported_import: "対応していないライブラリ",
  unsupported_code: "対応していない書き方（open や eval など）",
  too_much_output: "出力が多すぎる", no_questions: "問いを作れない", sandbox_error: "実行環境の失敗", not_submitted: "未提出",
};
const FIREBASE_SDK = "https://www.gstatic.com/firebasejs/10.14.1";
// CSP で Trusted Types を必須にしているので、読み込むスクリプトの URL はこのポリシーだけを通す。
// 許すのは Firebase の SDK と Service Worker（offline.js）だけ。CSP が許すポリシー名は mushitori の1つなので、ここで1回だけ作る
const scriptPolicy = window.trustedTypes?.createPolicy("mushitori", {
  createScriptURL: (url) => {
    if (url === "/sw.js" || url.startsWith(`${FIREBASE_SDK}/`)) return url;
    throw new TypeError("許可していないスクリプトです");
  },
}) ?? null;
const trustedScriptURL = (url) => (scriptPolicy ? scriptPolicy.createScriptURL(url) : url);
let teacherAuth = null; // Firebase Hosting で配信したときだけ使う。手元の開発では null
let teacherEmail = null; // 教員として確かめられたアカウント
let assignmentId = null;
let classId = null;
let studentToken = null;
let studentAssignment = null;
let studentCode = "";
let timerHandle = null;
let lastActionAt = Date.now();
let chatHistory = [];

// --- 立ち上がりを速くする ---
// Cloud Run は使われていないと止まり、止まったあとの最初の通信は起動に数秒かかる。
// 画面を開いた時点で起こしておき、画面が見えている間は止まらないように数分ごとに知らせる
const KEEP_WARM_MS = 4 * 60 * 1000;
const wakeServer = () => fetch("/v1/health", { cache: "no-store" }).catch(() => {});
wakeServer();
setInterval(() => { if (document.visibilityState === "visible") wakeServer(); }, KEEP_WARM_MS);

// 前回この端末で教員として確かめられたかどうか（メールアドレスは残さない）。
// 確かめられていた端末では、ログインの確認を待たずに作業画面を先に出し、確認の結果で直す
const LAST_TEACHER_KEY = "mushitori.teacher.v1";
function wasTeacher() {
  try { return localStorage.getItem(LAST_TEACHER_KEY) === "1"; } catch { return false; }
}
function rememberTeacher(yes) {
  try { if (yes) localStorage.setItem(LAST_TEACHER_KEY, "1"); else localStorage.removeItem(LAST_TEACHER_KEY); } catch { /* 保存できなくても動く */ }
}
// 画面は先に出しても、教員の API はログインの状態がわかるまで呼ばない
let markAuthReady;
const authReady = new Promise((resolve) => { markAuthReady = resolve; });

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
    const error = new Error(detail || `通信に失敗しました（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return body;
}
// 教員の認証。Firebase Hosting では Google ログインの ID トークン、手元の開発では仮のヘッダーを送る
async function teacherHeaders() {
  await authReady;
  if (!teacherAuth) return { "X-Dev-Teacher": "demo-teacher" };
  const user = teacherAuth.currentUser;
  if (!user) throw new Error("教員としてログインしてください");
  return { Authorization: `Bearer ${await user.getIdToken()}` };
}

const teacherPost = async (path) => api(path, { method: "POST", headers: await teacherHeaders() });
const setStatus = (text) => { $("status").textContent = text; };

function make(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

// 問いの文面の `x` をコード表記にする。HTMLとしては解釈させない。
function richText(tag, text, className) {
  const element = make(tag, undefined, className);
  text.split("`").forEach((part, index) => {
    if (part) element.append(index % 2 ? make("code", part) : document.createTextNode(part));
  });
  return element;
}

function selectTab(name) {
  for (const key of ["teacher", "student"]) {
    $(key).hidden = key !== name;
    $(`tab-${key}`).setAttribute("aria-selected", String(key === name));
  }
  // 生徒の画面では教員のアカウントを見せない
  $("account").hidden = name !== "teacher" || !teacherEmail;
}
$("tab-teacher").onclick = () => selectTab("teacher");
$("tab-student").onclick = () => selectTab("student");
$("to-student").onclick = () => selectTab("student");

function setButtons({ generate = false, open = false, close = false }) {
  $("generate").disabled = !generate;
  $("open").disabled = !open;
  $("close").disabled = !close;
}

async function guarded(action) {
  try { await action(); } catch (error) { setStatus(error.message); }
}

$("seed").onclick = () => guarded(async () => {
  const created = await teacherPost("/v1/dev/seed");
  assignmentId = created.assignment_id;
  $("class-code").textContent = created.class_code;
  $("class-input").value = created.class_code;
  $("codes").replaceChildren(...Object.entries(created.personal_codes).map(([number, code]) => {
    const row = make("tr");
    row.append(make("td", number), make("td", code, "code"));
    const cell = make("td");
    const use = make("button", "生徒画面で試す");
    use.type = "button";
    use.onclick = () => {
      $("class-input").value = created.class_code;
      $("personal-input").value = code;
      resetStudent();
      selectTab("student");
    };
    cell.append(use);
    row.append(cell);
    return row;
  }));
  $("codes-card").hidden = false;
  $("followups-card").hidden = true;
  classId = created.class_id;
  setButtons({ generate: true });
  $("delete").disabled = false;
  const expires = new Date(created.expires_at * 1000).toLocaleDateString("ja-JP");
  setStatus(`${Object.keys(created.personal_codes).length}人分の提出を登録しました。生徒のデータは ${expires} に自動で消えます。`);
});

// クラスごと消す。提出コード、解答、採点結果、名簿、授業コードと個人コードがすべて消え、元に戻せない
$("delete").onclick = () => guarded(async () => {
  if (!classId || !window.confirm("このクラスの提出コード、解答、採点結果、名簿、コードをすべて消します。元に戻せません。")) return;
  await api(`/v1/classes/${classId}`, { method: "DELETE", headers: await teacherHeaders() });
  classId = null;
  assignmentId = null;
  setButtons({});
  $("delete").disabled = true;
  $("codes-card").hidden = true;
  $("followups-card").hidden = true;
  resetStudent();
  setStatus("クラスのデータをすべて消しました。");
});

$("generate").onclick = () => guarded(async () => {
  setButtons({});
  setStatus("問いを作っています…");
  await teacherPost(`/v1/assignments/${assignmentId}:generate`);
  let state;
  do {
    await new Promise((resolve) => setTimeout(resolve, 500));
    state = await api(`/v1/assignments/${assignmentId}`, { headers: await teacherHeaders() });
  } while (state.state === "generating");
  const ready = state.submissions.ready || 0;
  const excluded = state.submissions.excluded || 0;
  const failed = state.submissions.failed || 0;
  setStatus(`問いを作りました。${ready}人分を作成、対象外 ${excluded}人、失敗 ${failed}人。`);
  setButtons({ open: ready > 0 });
});

$("open").onclick = () => guarded(async () => {
  await teacherPost(`/v1/assignments/${assignmentId}:open`);
  setButtons({ close: true });
  setStatus("受付中です。生徒は授業コードと個人コードで入れます。");
});

$("close").onclick = () => guarded(async () => {
  await teacherPost(`/v1/assignments/${assignmentId}:close`);
  setButtons({});
  setStatus("締め切りました。");
  lastActionAt = Date.now();
  $("followups-card").hidden = false;
  await new Promise((resolve) => setTimeout(resolve, 300));
  await loadFollowups();
});

$("refresh").onclick = () => guarded(loadFollowups);
$("budget").onchange = () => guarded(loadFollowups);

async function record(studentId, action, reason = "") {
  const duration = Date.now() - lastActionAt;
  await api(`/v1/assignments/${assignmentId}/followups/${studentId}`, {
    method: "POST",
    headers: { ...(await teacherHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ action, reason, duration_ms: Math.min(duration, 3600000) }),
  });
  lastActionAt = Date.now();
  await loadFollowups();
}

function actionButtons(row) {
  const actions = make("div", undefined, "row");
  // 質問案で聞いた結果は生徒の記録に残り、次の課題で AI が様子をまとめる材料になる
  const explained = make("button", "聞いて説明できた", "primary");
  explained.onclick = () => guarded(() => record(row.student_id, "explained"));
  const struggled = make("button", "説明が難しかった");
  struggled.onclick = () => guarded(() => record(row.student_id, "not_explained"));
  const ask = make("button", "あとで授業で聞く");
  ask.onclick = () => guarded(() => record(row.student_id, "ask_in_class"));
  const fine = make("button", "問題なし＋理由");
  const bad = make("button", "問いが不適切");
  bad.onclick = () => guarded(() => record(row.student_id, "question_bad"));
  fine.onclick = () => {
    const form = make("form", undefined, "row reason");
    const input = make("input");
    input.required = true;
    input.maxLength = 400;
    input.placeholder = "問題なしと判断した理由";
    input.setAttribute("aria-label", "問題なしと判断した理由");
    const save = make("button", "理由を保存");
    form.append(input, save);
    form.onsubmit = (event) => {
      event.preventDefault();
      guarded(() => record(row.student_id, "no_problem", input.value));
    };
    actions.replaceChildren(form);
    input.focus();
  };
  actions.append(explained, struggled, ask, fine, bad);
  return actions;
}

// クラス全体のつまずき。人数は集計そのもの、まとめは AI（または集計の文）
function classSummaryBlock(summary, minStudents) {
  const box = make("div", undefined, "summary-box");
  const head = make("p", undefined, "memo-head");
  head.append(make("strong", "クラス全体のつまずき"));
  if (summary && summary.by === "gemini") head.append(make("span", "AIのまとめ", "ai-badge"));
  box.append(head);
  if (!summary) {
    box.append(make("p", `解答した生徒が${minStudents}人以上になると、締切のときにまとめを作ります。`, "hint"));
    return box;
  }
  const stats = make("ul", undefined, "summary-stats");
  for (const s of summary.stats) stats.append(make("li", `${s.label}：${s.answered}人中 ${s.wrong}人が誤答`));
  box.append(stats);
  // 既定の文は人数の繰り返しなので、Gemini のまとめのときだけ出す
  if (summary.by === "gemini") {
    const points = make("ul", undefined, "summary-points");
    for (const point of summary.points) points.append(richText("li", point));
    box.append(points);
  }
  return box;
}

function evidenceDetails(row) {
  const details = make("details", undefined, "memo-evidence");
  details.append(make("summary", `誤答した問いと答え（${row.evidence.length}問）`));
  for (const item of row.evidence) {
    const line = richText("p", item.stem);
    line.append(document.createTextNode(`　答え：${item.given || "（未回答）"} ／ 正解：${item.answer}`));
    details.append(line);
  }
  return details;
}

// 以前の締切で作った声かけメモ。新しい締切では reviewBlock を使う
function memoBlock(row) {
  const box = make("div", undefined, "memo");
  const head = make("p", undefined, "memo-head");
  head.append(make("strong", "考えられるつまずき"));
  if (row.memo.by === "gemini") head.append(make("span", "AIの推測", "ai-badge"));
  box.append(head, richText("p", row.memo.hypothesis));
  box.append(make("p", "授業で聞いてみる", "memo-label"));
  const asks = make("ol", undefined, "memo-asks");
  for (const question of row.memo.questions) asks.append(richText("li", question));
  box.append(asks);
  if (row.evidence && row.evidence.length) box.append(evidenceDetails(row));
  return box;
}

// 本人の説明を聞きたい箇所。どの行を挙げるかと根拠は機械的に決め、AI は質問の言い回しだけを書く
function spotBlock(spot, explanations) {
  const item = make("div", undefined, "spot");
  const where = make("p", undefined, "spot-where");
  where.append(make("strong", spot.line ? `${spot.line}行目` : "プログラム全体の流れ"));
  if (spot.code) where.append(make("code", spot.code));
  item.append(where);
  const chips = make("p", undefined, "chips");
  if (spot.unexplained.length) {
    chips.append(make("span", spot.line ? `この行を指す問いに誤答（${spot.unexplained.length}問）` : "最後の表示を予測する問いに誤答", "chip"));
  }
  for (const label of spot.new) chips.append(richText("span", `これまで使っていなかった書き方：${label}`, "chip"));
  for (const label of spot.rare) chips.append(richText("span", `クラスでほとんど使われていない書き方：${label}`, "chip"));
  item.append(chips);
  item.append(richText("p", `聞いてみる：${spot.question}`, "ask"));
  const own = spot.line && explanations[String(spot.line)];
  if (own) item.append(ownWords(spot.line, own));
  return item;
}

// 生徒が自分の言葉で書いた説明。HTML としては解釈させない
function ownWords(line, text) {
  const box = make("p", undefined, "own-words");
  box.append(make("span", `${line}行目の本人の説明`, "chat-who"), document.createTextNode(text));
  return box;
}

function reviewBlock(row) {
  const box = make("div", undefined, "memo");
  const head = make("p", undefined, "memo-head");
  head.append(make("strong", "本人の説明を聞きたい箇所"));
  if (row.review.by === "gemini") head.append(make("span", "質問案とまとめはAI", "ai-badge"));
  box.append(head);
  box.append(make("p", "書いた本人なら説明できるはずの箇所です。説明を聞いて確かめてください。AIを使ったかどうかの判定ではありません。", "hint"));
  for (const spot of row.review.spots) box.append(spotBlock(spot, row.explanations));
  const shown = new Set(row.review.spots.map((spot) => String(spot.line)));
  for (const [line, text] of Object.entries(row.explanations)) if (!shown.has(line)) box.append(ownWords(line, text));
  box.append(make("p", "これまでの様子", "memo-label"), richText("p", row.review.overview));
  return box;
}

const ACTION_LABEL = {
  explained: "聞いて説明できた", not_explained: "説明が難しかった", ask_in_class: "あとで授業で聞く",
  no_problem: "問題なし", question_bad: "問いが不適切",
};

// 生徒ごとのこれまでの記録。開いたときに読み込む
function historyDetails(row) {
  const details = make("details", undefined, "memo-evidence history");
  details.append(make("summary", "これまでの記録"));
  details.ontoggle = () => guarded(async () => {
    if (!details.open || details.dataset.loaded) return;
    details.dataset.loaded = "1";
    const record = await api(`/v1/assignments/${assignmentId}/students/${row.student_id}/record`, { headers: await teacherHeaders() });
    if (!record.entries.length) {
      details.append(make("p", "まだ記録がありません。"));
      return;
    }
    const list = make("ul", undefined, "history-list");
    for (const entry of record.entries) {
      const item = make("li");
      item.append(make("strong", entry.title), document.createTextNode(`　${entry.total}問中 ${entry.score}問正解`));
      if (entry.action) item.append(document.createTextNode(`　／ ${ACTION_LABEL[entry.action.action] || entry.action.action}`));
      for (const spot of entry.spots) {
        const label = spot.line ? `${spot.line}行目` : "全体の流れ";
        const names = spot.constructs.length ? `（${spot.constructs.join("、")}）` : "";
        item.append(richText("p", `説明を聞いた箇所：${label}${names}`, "hint"));
      }
      list.append(item);
    }
    details.append(list);
  });
  return details;
}

async function loadFollowups() {
  const budget = Number($("budget").value) || 0;
  const view = await api(`/v1/assignments/${assignmentId}/followups?budget_sec=${budget}`, { headers: await teacherHeaders() });
  $("tau").textContent = `1人あたり ${Math.round(view.tau_sec)}秒として計算`;
  $("class-summary").replaceChildren(classSummaryBlock(view.class_summary, view.summary_min_students));
  $("order").replaceChildren(...view.order.map((row, index) => {
    const card = make("div", undefined, `card person${row.in_budget ? " now" : ""}`);
    card.append(make("h3", `${index + 1}. 番号 ${row.number}（${row.score}/${row.total} 問正解）`));
    if (!row.in_budget && !row.action) card.append(make("p", "持ち時間の外です。次の空き時間に回します。", "hint"));
    if (row.review) card.append(reviewBlock(row));
    else if (row.memo) card.append(memoBlock(row));
    else if (row.question) card.append(make("p", `聞いてみる：${row.question}`, "ask"));
    else card.append(make("p", "今回は、説明を聞きたい箇所はありません。", "hint"));
    if (row.review && row.evidence.length) card.append(evidenceDetails(row));
    card.append(historyDetails(row));
    if (row.action) card.append(make("p", `処置済み：${ACTION_LABEL[row.action]}`, "done"));
    else card.append(actionButtons(row));
    return card;
  }));
  const others = [];
  for (const item of view.not_attempted) others.push(`番号 ${item.number}：未解答`);
  for (const item of view.excluded) others.push(`番号 ${item.number}：${REASONS[item.reason] || item.reason}`);
  $("others").replaceChildren(...(others.length ? [make("h3", "順番の外（直接確認してください）"), ...others.map((text) => make("p", text, "others"))] : []));
  if (!view.order.length) $("order").replaceChildren(make("p", "まだ解答はありません。", "hint"));
}

function resetChat() {
  chatHistory = [];
  $("chat-log").replaceChildren();
  $("chat-remaining").textContent = "";
  $("chat-error").textContent = "";
  $("chat-input").disabled = false;
  $("chat-send").disabled = false;
}

// who は表示する名前。Gemini の返答は「AI」、既定の文は「ヒント」と分けて見せる
function addChatMessage(role, text, who) {
  const item = richText("p", text, `chat-message ${role}`);
  item.prepend(make("span", who, "chat-who"));
  $("chat-log").append(item);
  item.scrollIntoView({ block: "nearest" });
}

$("chat-form").onsubmit = async (event) => {
  event.preventDefault();
  const message = $("chat-input").value.trim();
  if (!message) return;
  $("chat-error").textContent = "";
  $("chat-send").disabled = true;
  addChatMessage("student", message, "あなた");
  $("chat-input").value = "";
  try {
    const reply = await api(`/v1/assignments/${studentAssignment}/attempt:chat`, {
      method: "POST",
      headers: studentHeaders(),
      body: JSON.stringify({ message, history: chatHistory.slice(-8) }),
    });
    addChatMessage("ai", reply.reply, reply.by === "gemini" ? "AI" : "ヒント");
    chatHistory.push({ role: "student", text: message }, { role: "ai", text: reply.reply });
    $("chat-remaining").textContent = `あと ${reply.remaining} 回質問できます。`;
    const done = reply.remaining <= 0;
    $("chat-input").disabled = done;
    $("chat-send").disabled = done;
  } catch (error) {
    $("chat-error").textContent = error.message;
    $("chat-send").disabled = false;
  }
};

function resetStudent() {
  clearInterval(timerHandle);
  resetChat();
  $("login").hidden = false;
  for (const id of ["ready", "quiz", "result"]) $(id).hidden = true;
  $("login-error").textContent = "";
  studentToken = null;
}

$("login").onsubmit = async (event) => {
  event.preventDefault();
  $("login-error").textContent = "";
  try {
    const session = await api("/v1/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ class_code: $("class-input").value, personal_code: $("personal-input").value }),
    });
    studentToken = session.token;
    studentAssignment = session.assignment_id;
    $("welcome").textContent = `番号 ${session.number} さん`;
    $("login").hidden = true;
    $("ready").hidden = false;
    $("start").disabled = !studentAssignment;
    $("start-error").textContent = studentAssignment ? "" : "今は受付中の課題がありません。";
  } catch (error) {
    $("login-error").textContent = error.message;
  }
};

const studentHeaders = () => ({ Authorization: `Bearer ${studentToken}`, "Content-Type": "application/json" });

function showCode(element, code) {
  element.replaceChildren(...code.replace(/\n$/, "").split("\n").map((line) => make("span", line || " ", "ln")));
}

function questionCard(question, index) {
  const card = make("div", undefined, "card");
  const fieldset = make("fieldset", undefined, "question");
  fieldset.append(richText("legend", `問${index + 1}. ${question.stem}`));
  if (question.options.length) {
    for (const option of question.options) {
      const label = make("label", undefined, "option");
      const input = make("input");
      input.type = "radio";
      input.name = question.id;
      input.value = option;
      label.append(input, make("span", option, "code"));
      fieldset.append(label);
    }
  } else {
    const label = make("label", "答えを入力してください", "free");
    const input = make("input");
    input.name = question.id;
    input.autocomplete = "off";
    label.append(input);
    fieldset.append(label);
  }
  card.append(fieldset);
  return card;
}

function startTimer(seconds) {
  let remaining = seconds;
  const draw = () => {
    const minutes = Math.floor(remaining / 60);
    $("timer").textContent = `残り ${minutes}:${String(remaining % 60).padStart(2, "0")}`;
  };
  draw();
  clearInterval(timerHandle);
  timerHandle = setInterval(() => {
    remaining -= 1;
    draw();
    if (remaining <= 0) {
      clearInterval(timerHandle);
      $("quiz").requestSubmit();
    }
  }, 1000);
}

$("start").onclick = async () => {
  $("start-error").textContent = "";
  try {
    const quiz = await api(`/v1/assignments/${studentAssignment}/attempt:start`, { method: "POST", headers: studentHeaders() });
    studentCode = quiz.code;
    showCode($("code"), quiz.code);
    $("stdin").textContent = quiz.stdin ? `入力：${quiz.stdin.trim()}` : "";
    $("questions").replaceChildren(...quiz.questions.map(questionCard));
    $("ready").hidden = true;
    $("quiz").hidden = false;
    startTimer(quiz.remaining_sec);
  } catch (error) {
    $("start-error").textContent = error.message;
  }
};

$("quiz").onsubmit = async (event) => {
  event.preventDefault();
  const answers = {};
  for (const [name, value] of new FormData($("quiz")).entries()) answers[name] = String(value);
  try {
    const result = await api(`/v1/assignments/${studentAssignment}/attempt:submit`, {
      method: "POST",
      headers: studentHeaders(),
      body: JSON.stringify({ answers }),
    });
    clearInterval(timerHandle);
    $("score").textContent = `${result.total}問中 ${result.score}問 正解`;
    $("notice").textContent = result.notice;
    $("result-items").replaceChildren(...result.results.map((item) => {
      const card = make("div", undefined, "card");
      card.append(richText("p", item.stem));
      card.append(make("p", item.correct ? "正解" : "もう一度たどってみましょう", `mark ${item.correct ? "good" : "bad"}`));
      card.append(make("p", `あなたの答え：${item.given || "（未回答）"} ／ 正解：${item.answer}`));
      card.append(make("p", item.explanation, "hint"));
      return card;
    }));
    showCode($("trace"), result.trace.join("\n"));
    $("trace").style.counterReset = "none";
    showExplainItems(result.results);
    $("quiz").hidden = true;
    resetChat();
    $("result").hidden = false;
  } catch (error) {
    // 通信が切れていたら、解答を端末にためて、つながってから送る（offline.js）
    if (typeof queueOfflineAnswers === "function" && queueOfflineAnswers(error, studentAssignment, studentToken, answers)) return;
    $("quiz-error").textContent = error.message;
  }
};

// まちがえた問いが指す行ごとに、自分の言葉で説明を書く欄を出す。AI は使わず、そのまま先生に届く
function showExplainItems(results) {
  const codeLines = studentCode.split("\n");
  const lines = [...new Set(results.filter((item) => !item.correct && item.line).map((item) => item.line))].sort((a, b) => a - b);
  $("explain-card").hidden = !lines.length;
  $("explain-items").replaceChildren(...lines.map((line) => {
    const form = make("form", undefined, "explain-item");
    const where = make("p", undefined, "spot-where");
    where.append(make("strong", `${line}行目`), make("code", (codeLines[line - 1] || "").trim()));
    const text = make("textarea");
    text.maxLength = 300;
    text.rows = 3;
    text.required = true;
    text.placeholder = "例：この行では、60点以上のときだけ合計に足している。";
    text.setAttribute("aria-label", `${line}行目の説明`);
    const save = make("button", "先生に送る");
    const state = make("p", undefined, "hint");
    state.setAttribute("role", "status");
    form.append(where, text, make("div", undefined, "row"), state);
    form.querySelector(".row").append(save);
    form.onsubmit = async (event) => {
      event.preventDefault();
      save.disabled = true;
      state.textContent = "";
      try {
        await api(`/v1/assignments/${studentAssignment}/attempt:explain`, {
          method: "POST",
          headers: studentHeaders(),
          body: JSON.stringify({ line, text: text.value }),
        });
        state.textContent = "送りました。書き直して、もう一度送ることもできます。";
      } catch (error) {
        state.textContent = error.message;
      }
      save.disabled = false;
    };
    return form;
  }));
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    // 並べて取りに行き、入れた順に実行させる（auth は app のあとに動く必要がある）
    script.async = false;
    script.src = trustedScriptURL(src);
    script.onload = resolve;
    script.onerror = () => reject(new Error(`${src} を読み込めませんでした`));
    document.head.append(script);
  });
}

// Firebase Hosting は /__/firebase/init.json に設定を置く。読めなければ手元の開発として動く
async function setupTeacherAuth() {
  // 前回教員として確かめられた端末では、確認を待たずに作業画面を出す。違っていたら確認のあとで戻す
  if (wasTeacher()) showSignedIn(null);
  let config = null;
  try {
    const response = await fetch("/__/firebase/init.json");
    if (response.ok) config = await response.json();
  } catch {
    config = null;
  }
  if (!config) {
    $("teacher-work").hidden = false;
    markAuthReady();
    return;
  }
  // 初めての端末では、SDK を待たずにログインの案内を出す（ボタンは準備ができてから押せる）
  if (!wasTeacher()) {
    showSignedOut();
    $("signin").disabled = true;
  }
  await Promise.all([loadScript(`${FIREBASE_SDK}/firebase-app-compat.js`), loadScript(`${FIREBASE_SDK}/firebase-auth-compat.js`)]);
  firebase.initializeApp(config);
  teacherAuth = firebase.auth();
  $("signin").onclick = async () => {
    $("signin-error").textContent = "";
    const provider = new firebase.auth.GoogleAuthProvider();
    try {
      await teacherAuth.signInWithPopup(provider);
    } catch (error) {
      if (error.code === "auth/popup-blocked") await teacherAuth.signInWithRedirect(provider);
      else $("signin-error").textContent = "ログインできませんでした。もう一度お試しください。";
    }
  };
  $("signin").disabled = false;
  $("signout").onclick = () => teacherAuth.signOut();
  teacherAuth.onAuthStateChanged(async (user) => {
    // ここで初めてログインの状態がわかるので、待たせていた教員の API を通す
    markAuthReady();
    if (!user) {
      rememberTeacher(false);
      showSignedOut();
      return;
    }
    try {
      const me = await api("/v1/me", { headers: await teacherHeaders() });
      rememberTeacher(true);
      showSignedIn(me.email);
    } catch (error) {
      const message = error.status === 403
        ? `${user.email} は教員として登録されていません。許可されたアカウントでログインしてください。`
        : "ログインを確かめられませんでした。もう一度お試しください。";
      rememberTeacher(false);
      await teacherAuth.signOut();
      showSignedOut(message);
    }
  });
}

function showSignedOut(message) {
  teacherEmail = null;
  $("signin-card").hidden = false;
  $("teacher-work").hidden = true;
  $("account").hidden = true;
  if (message !== undefined) $("signin-error").textContent = message;
}

// email が null のときは、前回の記録から先に出しただけで、まだ確かめていない
function showSignedIn(email) {
  teacherEmail = email;
  $("who").textContent = email ?? "ログインを確認中…";
  $("signin-error").textContent = "";
  $("signin-card").hidden = true;
  $("teacher-work").hidden = false;
  $("account").hidden = $("teacher").hidden;
}

setupTeacherAuth().catch((error) => {
  markAuthReady();
  $("signin-card").hidden = false;
  $("teacher-work").hidden = true;
  $("signin-error").textContent = error.message;
});

// 端末に置いた画面より新しい版を、Service Worker（sw.js）が見つけたら知らせる
navigator.serviceWorker?.addEventListener("message", (event) => {
  if (event.data?.type !== "shell-updated" || $("update-banner")) return;
  const banner = make("div", undefined, "card update-banner");
  banner.id = "update-banner";
  banner.setAttribute("role", "status");
  const reload = make("button", "再読み込み");
  reload.onclick = () => location.reload();
  banner.append(make("span", "新しい版があります。"), reload);
  document.querySelector("main").prepend(banner);
});
