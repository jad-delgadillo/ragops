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
  repoUrl: document.getElementById("repo-url"),
  repoRef: document.getElementById("repo-ref"),
  repoCollection: document.getElementById("repo-collection"),
  repoGenerateManuals: document.getElementById("repo-generate-manuals"),
  repoResetCollections: document.getElementById("repo-reset-collections"),
  repoOnboardBtn: document.getElementById("repo-onboard-btn"),
  repoStatus: document.getElementById("repo-status"),
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
    if (el.repoUrl) el.repoUrl.value = data.repoUrl || "";
    if (el.repoRef) el.repoRef.value = data.repoRef || "main";
    if (el.repoCollection) el.repoCollection.value = data.repoCollection || "";
    if (el.repoGenerateManuals) el.repoGenerateManuals.checked = data.repoGenerateManuals !== false;
    if (el.repoResetCollections) el.repoResetCollections.checked = data.repoResetCollections !== false;
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
    repoUrl: el.repoUrl ? el.repoUrl.value.trim() : "",
    repoRef: el.repoRef ? el.repoRef.value.trim() : "main",
    repoCollection: el.repoCollection ? el.repoCollection.value.trim() : "",
    repoGenerateManuals: el.repoGenerateManuals ? el.repoGenerateManuals.checked : true,
    repoResetCollections: el.repoResetCollections ? el.repoResetCollections.checked : true,
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
  el.sendBtn.textContent = active ? "Sending..." : "Send";
  el.question.disabled = active;
}

function setRepoStatus(text, kind = "idle") {
  if (!el.repoStatus) return;
  el.repoStatus.textContent = text;
  el.repoStatus.className = `status-pill ${kind}`;
}

function setOnboarding(active) {
  if (!el.repoOnboardBtn) return;
  el.repoOnboardBtn.disabled = active;
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

function jsonHeaders() {
  return {
    "Content-Type": "application/json",
    ...baseHeaders(),
  };
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatInlineMarkdown(text) {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
}

function renderMarkdownSafe(rawText) {
  const normalized = String(rawText || "").replace(/\r\n?/g, "\n").trim();
  if (!normalized) return "";

  const placeholders = [];
  let escaped = escapeHtml(normalized);
  escaped = escaped.replace(/```([a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g, (_, _lang, code) => {
    const token = `@@CODEBLOCK_${placeholders.length}@@`;
    placeholders.push(`<pre class="md-code"><code>${code.trim()}</code></pre>`);
    return token;
  });

  const lines = escaped.split("\n");
  const html = [];
  let listType = null;

  function closeList() {
    if (!listType) return;
    html.push(listType === "ol" ? "</ol>" : "</ul>");
    listType = null;
  }

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      return;
    }
    if (/^@@CODEBLOCK_\d+@@$/.test(trimmed)) {
      closeList();
      html.push(trimmed);
      return;
    }

    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${formatInlineMarkdown(bullet[1])}</li>`);
      return;
    }

    const numbered = trimmed.match(/^(\d+)\.\s+(.+)$/);
    if (numbered) {
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${formatInlineMarkdown(numbered[2])}</li>`);
      return;
    }

    closeList();
    html.push(`<p>${formatInlineMarkdown(trimmed)}</p>`);
  });
  closeList();

  let rendered = html.join("");
  placeholders.forEach((block, idx) => {
    rendered = rendered.replace(`@@CODEBLOCK_${idx}@@`, block);
  });
  return rendered;
}

function compactSourceLabel(source) {
  const normalized = String(source || "unknown").replaceAll("\\", "/");
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length <= 3) return normalized;
  return `.../${segments.slice(-3).join("/")}`;
}

function createMessage(role, text, meta = "") {
  const node = el.tpl.content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  node.querySelector(".role").textContent = role;
  node.querySelector(".meta").textContent = meta;
  const content = node.querySelector(".content");
  if (role === "assistant") {
    content.innerHTML = renderMarkdownSafe(text);
  } else {
    content.textContent = text;
  }
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
    const compact = compactSourceLabel(src);
    li.title = src;
    li.innerHTML = `<code>${escapeHtml(compact)}</code> (L${start}-L${end}, ${score})`;
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
      headers: jsonHeaders(),
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
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Chat failed (${res.status}): ${text}`);
  }
  return res.json();
}

async function submitRepoOnboard() {
  const repoUrl = el.repoUrl?.value.trim() || "";
  if (!repoUrl) {
    throw new Error("Set a GitHub repo URL first");
  }
  const payload = {
    repo_url: repoUrl,
    ref: el.repoRef?.value.trim() || "main",
    collection: el.repoCollection?.value.trim() || undefined,
    generate_manuals: el.repoGenerateManuals?.checked ?? true,
    reset_code_collection: el.repoResetCollections?.checked ?? true,
    reset_manuals_collection: el.repoResetCollections?.checked ?? true,
    lazy: true,
    async: true,
  };
  const res = await fetch(endpoint(el.apiUrl.value, "/v1/repos/onboard"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Repo onboarding failed (${res.status}): ${text}`);
  }
  return res.json();
}

async function fetchRepoOnboardStatus(jobId) {
  const res = await fetch(endpoint(el.apiUrl.value, "/v1/repos/onboard"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      action: "status",
      job_id: jobId,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Repo onboarding status failed (${res.status}): ${text}`);
  }
  return res.json();
}

async function pollRepoOnboardJob(jobId) {
  const maxAttempts = 120;
  const delayMs = 3000;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    const data = await fetchRepoOnboardStatus(jobId);
    const status = String(data.status || "").toLowerCase();
    if (status === "queued" || status === "running") {
      setRepoStatus(`Onboarding (${status})`, "busy");
      setStatus(`Repo onboarding (${status})`, "busy");
      continue;
    }
    if (status === "succeeded") {
      return data.result || {};
    }
    if (status === "failed") {
      throw new Error(`Repo onboarding failed: ${data.error || "unknown error"}`);
    }
    throw new Error(`Unexpected onboarding status: ${status || "unknown"}`);
  }
  throw new Error(`Repo onboarding is still running. Job ID: ${jobId}`);
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

if (el.repoOnboardBtn) {
  el.repoOnboardBtn.addEventListener("click", async () => {
    if (!el.apiUrl.value.trim()) {
      setRepoStatus("Set API URL first", "error");
      return;
    }
    setOnboarding(true);
    setRepoStatus("Onboarding...", "busy");
    setStatus("Onboarding repo...", "busy");
    try {
      let data = await submitRepoOnboard();
      if ((data.status || "").toLowerCase() === "queued" && data.job_id) {
        setRepoStatus(`Queued (${data.job_id.slice(0, 8)}...)`, "busy");
        setStatus("Repo onboarding queued", "busy");
        data = await pollRepoOnboardJob(data.job_id);
      }
      if (data.collection) {
        el.collection.value = data.collection;
      }
      if (data.manuals_collection && !el.repoCollection.value.trim()) {
        el.repoCollection.value = data.name || "";
      }
      saveSettings();
      const isLazy = data.mode === "lazy";
      if (isLazy) {
        const fileCount = data.embeddable_files ?? 0;
        setRepoStatus(`Ready: ${data.collection}`, "idle");
        setStatus(`Lazy onboarded (${fileCount} files indexed). Content embedded on-demand per query.`, "idle");
      } else {
        const indexed = data.ingest?.indexed_docs ?? 0;
        const chunks = data.ingest?.total_chunks ?? 0;
        setRepoStatus(`Ready: ${data.collection}`, "idle");
        setStatus(`Repo onboarded (${indexed} files, ${chunks} chunks)`, "idle");
      }
    } catch (err) {
      console.error(err);
      setRepoStatus("Failed", "error");
      const errMsg = err.message || String(err);
      setStatus(`Onboarding failed: ${errMsg.slice(0, 80)}`, "error");
      addAssistantMessage({
        question: "",
        answer: String(err),
        citations: [],
        sessionId: state.sessionId,
        turnIndex: null,
        answerStyle: el.answerStyle.value || "concise",
        contextSnippets: [],
      });
    } finally {
      setOnboarding(false);
    }
  });
}

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
  el.repoUrl,
  el.repoRef,
  el.repoCollection,
  el.repoGenerateManuals,
  el.repoResetCollections,
]
  .filter(Boolean)
  .forEach((node) => node.addEventListener("change", saveSettings));

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
setRepoStatus("Idle", "idle");
