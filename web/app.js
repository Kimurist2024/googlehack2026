// 文字はすべて textContent で入れる。生徒のコードをHTMLとして解釈させない。
const $ = (id) => document.getElementById(id);
const REASONS = {
  too_long: "実行が終わらない", timeout: "実行が終わらない", error: "実行時にエラー", syntax_error: "文法エラー",
  nondeterministic: "実行ごとに結果が変わる", unsupported_import: "対応していないライブラリ",
  too_much_output: "出力が多すぎる", no_questions: "問いを作れない", sandbox_error: "実行環境の失敗", not_submitted: "未提出",
};
const FIREBASE_SDK = "https://www.gstatic.com/firebasejs/10.14.1";
let teacherAuth = null; // Firebase Hosting で配信したときだけ使う。手元の開発では null
let teacherEmail = null; // 教員として確かめられたアカウント
let assignmentId = null;
let studentToken = null;
let studentAssignment = null;
let timerHandle = null;
let lastActionAt = Date.now();

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
  setButtons({ generate: true });
  setStatus(`${Object.keys(created.personal_codes).length}人分の提出を登録しました。`);
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
  const ask = make("button", "授業で聞く");
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
  actions.append(ask, fine, bad);
  return actions;
}

const ACTION_LABEL = { ask_in_class: "授業で聞く", no_problem: "問題なし", question_bad: "問いが不適切" };

async function loadFollowups() {
  const budget = Number($("budget").value) || 0;
  const view = await api(`/v1/assignments/${assignmentId}/followups?budget_sec=${budget}`, { headers: await teacherHeaders() });
  $("tau").textContent = `1人あたり ${Math.round(view.tau_sec)}秒として計算`;
  $("order").replaceChildren(...view.order.map((row, index) => {
    const card = make("div", undefined, `card person${row.in_budget ? " now" : ""}`);
    card.append(make("h3", `${index + 1}. 番号 ${row.number}（${row.score}/${row.total} 問正解）`));
    if (!row.in_budget && !row.action) card.append(make("p", "持ち時間の外です。次の空き時間に回します。", "hint"));
    if (row.question) card.append(make("p", `聞いてみる：${row.question}`, "ask"));
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

function resetStudent() {
  clearInterval(timerHandle);
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
    $("quiz").hidden = true;
    $("result").hidden = false;
  } catch (error) {
    $("quiz-error").textContent = error.message;
  }
};

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`${src} を読み込めませんでした`));
    document.head.append(script);
  });
}

// Firebase Hosting は /__/firebase/init.json に設定を置く。読めなければ手元の開発として動く
async function setupTeacherAuth() {
  let config = null;
  try {
    const response = await fetch("/__/firebase/init.json");
    if (response.ok) config = await response.json();
  } catch {
    config = null;
  }
  if (!config) {
    $("teacher-work").hidden = false;
    return;
  }
  await loadScript(`${FIREBASE_SDK}/firebase-app-compat.js`);
  await loadScript(`${FIREBASE_SDK}/firebase-auth-compat.js`);
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
  $("signout").onclick = () => teacherAuth.signOut();
  // ログインの状態がわかるまでは、案内も作業の画面も出さない
  teacherAuth.onAuthStateChanged(async (user) => {
    if (!user) {
      showSignedOut();
      return;
    }
    try {
      const me = await api("/v1/me", { headers: await teacherHeaders() });
      showSignedIn(me.email);
    } catch (error) {
      const message = error.status === 403
        ? `${user.email} は教員として登録されていません。許可されたアカウントでログインしてください。`
        : "ログインを確かめられませんでした。もう一度お試しください。";
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

function showSignedIn(email) {
  teacherEmail = email;
  $("who").textContent = email;
  $("signin-error").textContent = "";
  $("signin-card").hidden = true;
  $("teacher-work").hidden = false;
  $("account").hidden = $("teacher").hidden;
}

setupTeacherAuth().catch((error) => {
  $("signin-card").hidden = false;
  $("signin-error").textContent = error.message;
});
