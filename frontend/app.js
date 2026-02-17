const storageKey = "ragops-onboarding-ui";

const state = {
  sessionId: "",
  sending: false,
  entries: [],
};

const el = {
  apiUrl: document.getElementById("api-url"),
  apiKey: document.getElementById("api-key"),
  collection: document.getElementById("collection"),
  mode: document.getElementById("mode"),
  answerStyle: document.getElementById("answer-style"),
  topK: document.getElementById("top-k"),
  sessionId: document.getElementById("session-id"),
  status: document.getElementById("status-pill"),
  feed: document.getElementById("chat-feed"),
  form: document.getElementById("chat-form"),
  question: document.getElementById("question-input"),
  sendBtn: document.getElementById("send-btn"),
  newSessionBtn: document.getElementById("new-session-btn"),
  tpl: document.getElementById("message-template"),
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return;
    const data = JSON.parse(raw);
    el.apiUrl.value = data.apiUrl || "http://localhost:8090";
    el.apiKey.value = data.apiKey || "";
    el.collection.value = data.collection || "default";
    el.mode.value = data.mode || "explain_like_junior";
    el.answerStyle.value = data.answerStyle || "concise";
    el.topK.value = String(data.topK || 5);
    state.sessionId = data.sessionId || "";
    el.sessionId.value = state.sessionId;
  } catch (err) {
    console.error("Failed to load settings", err);
  }
}

function saveSettings() {
  const payload = {
    apiUrl: el.apiUrl.value.trim(),
    apiKey: el.apiKey.value.trim(),
    collection: el.collection.value.trim(),
    mode: el.mode.value,
    answerStyle: el.answerStyle.value,
    topK: Number(el.topK.value) || 5,
    sessionId: state.sessionId,
  };
  localStorage.setItem(storageKey, JSON.stringify(payload));
}

function setStatus(text, kind = "idle") {
  el.status.textContent = text;
  el.status.className = `status-pill ${kind}`;
}

function setSending(active) {
  state.sending = active;
  el.sendBtn.disabled = active;
  el.question.disabled = active;
}

function endpoint(baseUrl, path) {
  const trimmed = baseUrl.trim().replace(/\/+$/, "");
  if (!trimmed) return path;
  if (trimmed.endsWith(path)) return trimmed;
  return `${trimmed}${path}`;
}

function baseHeaders() {
  const headers = {};
  const key = el.apiKey.value.trim();
  if (key) headers["X-API-Key"] = key;
  return headers;
}

function createMessage(role, text, meta = "") {
  const node = el.tpl.content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  node.querySelector(".role").textContent = role;
  node.querySelector(".meta").textContent = meta;
  node.querySelector(".content").textContent = text;
  return node;
}

function addUserMessage(question) {
  const msg = createMessage("user", question, new Date().toLocaleTimeString());
  el.feed.appendChild(msg);
  el.feed.scrollTop = el.feed.scrollHeight;
}

function renderCitations(node, citations) {
  if (!Array.isArray(citations) || citations.length === 0) return;
  const wrap = node.querySelector(".citations-wrap");
  const list = node.querySelector(".citations");
  wrap.classList.remove("hidden");
  list.innerHTML = "";
  citations.forEach((cite) => {
    const li = document.createElement("li");
    const src = cite.source || "unknown";
    const start = cite.line_start ?? "?";
    const end = cite.line_end ?? "?";
    const score = cite.similarity != null ? `${Math.round(cite.similarity * 100)}%` : "n/a";
    li.textContent = `${src} (L${start}-L${end}, ${score})`;
    list.appendChild(li);
  });
}

function renderRawContext(node, snippets) {
  if (!Array.isArray(snippets) || snippets.length === 0) return;
  const wrap = node.querySelector(".context-wrap");
  const btn = node.querySelector(".context-btn");
  const list = node.querySelector(".context-list");
  wrap.classList.remove("hidden");
  list.innerHTML = "";
  snippets.forEach((snippet) => {
    const li = document.createElement("li");
    const source = snippet.source || "unknown";
    const start = snippet.line_start ?? "?";
    const end = snippet.line_end ?? "?";
    const score = snippet.similarity != null ? `${Math.round(snippet.similarity * 100)}%` : "n/a";
    const content = snippet.content || "";
    li.textContent = `${source} (L${start}-L${end}, ${score}) :: ${content}`;
    list.appendChild(li);
  });
  btn.addEventListener("click", () => {
    const hidden = list.classList.contains("hidden");
    list.classList.toggle("hidden", !hidden);
    btn.textContent = hidden ? "Hide Raw Context" : "Show Raw Context";
  });
}

async function submitFeedback(payload, button) {
  try {
    const comment = window.prompt("Optional feedback note", "") || "";
    if (comment) payload.comment = comment;
    const res = await fetch(endpoint(el.apiUrl.value, "/v1/feedback"), {
      method: "POST",
      headers: baseHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Feedback failed: ${text}`);
    }
    button.classList.add(payload.verdict === "positive" ? "sent-positive" : "sent-negative");
    setStatus("Feedback saved", "idle");
  } catch (err) {
    console.error(err);
    setStatus("Feedback error", "error");
  }
}

function addAssistantMessage(entry) {
  const meta = `session=${entry.sessionId || "-"} turn=${entry.turnIndex ?? "-"} style=${entry.answerStyle || "concise"}`;
  const node = createMessage("assistant", entry.answer || "", meta);
  renderCitations(node, entry.citations);
  renderRawContext(node, entry.contextSnippets);

  const feedbackWrap = node.querySelector(".feedback-wrap");
  feedbackWrap.classList.remove("hidden");
  node.querySelectorAll(".feedback-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const verdict = btn.dataset.verdict;
      const payload = {
        verdict,
        collection: el.collection.value.trim() || "default",
        session_id: entry.sessionId || null,
        mode: el.mode.value,
        question: entry.question,
        answer: entry.answer,
        citations: entry.citations || [],
        metadata: {
          surface: "frontend-chat-screen",
          turn_index: entry.turnIndex ?? null,
        },
      };
      submitFeedback(payload, btn);
    });
  });

  el.feed.appendChild(node);
  el.feed.scrollTop = el.feed.scrollHeight;
}

async function submitChat(question) {
  const payload = {
    question,
    collection: el.collection.value.trim() || "default",
    mode: el.mode.value,
    answer_style: el.answerStyle.value || "concise",
    top_k: Number(el.topK.value) || 5,
    include_context: true,
  };
  if (state.sessionId) payload.session_id = state.sessionId;

  const res = await fetch(endpoint(el.apiUrl.value, "/v1/chat"), {
    method: "POST",
    headers: baseHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Chat failed (${res.status}): ${text}`);
  }
  return res.json();
}

el.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.sending) return;

  const question = el.question.value.trim();
  if (!question) return;
  if (!el.apiUrl.value.trim()) {
    setStatus("Set API URL first", "error");
    return;
  }

  addUserMessage(question);
  setSending(true);
  setStatus("Thinking...", "busy");

  try {
    const data = await submitChat(question);
    state.sessionId = data.session_id || state.sessionId;
    el.sessionId.value = state.sessionId;
    const entry = {
      question,
      answer: data.answer || "",
      citations: data.citations || [],
      sessionId: state.sessionId,
      turnIndex: data.turn_index,
      answerStyle: data.answer_style || (el.answerStyle.value || "concise"),
      contextSnippets: data.context_snippets || [],
    };
    state.entries.push(entry);
    addAssistantMessage(entry);
    saveSettings();
    setStatus("Ready", "idle");
    el.question.value = "";
    el.question.focus();
  } catch (err) {
    console.error(err);
    addAssistantMessage({
      question,
      answer: String(err),
      citations: [],
      sessionId: state.sessionId,
      turnIndex: null,
      answerStyle: el.answerStyle.value || "concise",
      contextSnippets: [],
    });
    setStatus("Request failed", "error");
  } finally {
    setSending(false);
  }
});

el.newSessionBtn.addEventListener("click", () => {
  state.sessionId = "";
  state.entries = [];
  el.sessionId.value = "";
  el.feed.innerHTML = "";
  saveSettings();
  setStatus("New session", "idle");
});

el.sessionId.addEventListener("change", () => {
  state.sessionId = el.sessionId.value.trim();
  saveSettings();
});

[
  el.apiUrl,
  el.apiKey,
  el.collection,
  el.mode,
  el.answerStyle,
  el.topK,
].forEach((node) => node.addEventListener("change", saveSettings));

loadSettings();
if (!el.apiUrl.value) {
  el.apiUrl.value = "http://localhost:8090";
}
if (!el.mode.value) {
  el.mode.value = "explain_like_junior";
}
if (!el.answerStyle.value) {
  el.answerStyle.value = "concise";
}
setStatus("Ready", "idle");
