"use strict";

// All server text goes through textContent: answers and documents are never parsed as HTML.

const EXAMPLES = [
  "Какая арендная плата по договору с ООО «Северный Склад» и до какого числа её нужно вносить?",
  "Договор на 12 млн рублей заключали в августе 2024 года. Нужно ли было одобрение генерального директора?",
  "Что нужно сделать до подписания договора с иностранным поставщиком?",
  "Какой размер пособия по беременности и родам?",
];

const history = [];
const documentCache = new Map();
let documentRequest = 0;
const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollToBottom() {
  const box = $("messages");
  box.scrollTop = box.scrollHeight;
}

function sourceButton(source) {
  const button = element("button", source.cited ? "source cited" : "source", source.title);
  button.type = "button";
  button.addEventListener("click", () => openDocument(source.doc_id, source.chunk_ids));
  return button;
}

function renderAnswer(data) {
  const wrapper = element("div", "message assistant");
  wrapper.append(element("div", "text", data.answer));
  if (data.trimmed) {
    wrapper.append(element("p", "notice", "Часть утверждений удалена: она не подтверждается документами базы."));
  }
  const cited = data.sources.filter((s) => s.cited);
  const other = data.sources.filter((s) => !s.cited);
  if (cited.length) {
    const list = element("div", "sources");
    list.append(element("span", "sources-label", "Источники:"));
    cited.forEach((s) => list.append(sourceButton(s)));
    wrapper.append(list);
  }
  if (other.length) {
    const details = element("details", "more");
    details.append(element("summary", "", `Также просмотрено документов: ${other.length}`));
    const list = element("div", "sources");
    other.forEach((s) => list.append(sourceButton(s)));
    details.append(list);
    wrapper.append(details);
  }
  $("messages").append(wrapper);
  if (cited.length) openDocument(cited[0].doc_id, cited[0].chunk_ids);
}

function renderUser(text) {
  $("messages").append(element("div", "message user", text));
}

function renderError(text) {
  $("messages").append(element("div", "message error", text));
}

async function ask(text) {
  const question = text.trim();
  if (!question) return;
  $("examples").hidden = true;
  // History changes only after a valid answer: a failed request leaves nothing to undo.
  const messages = [...history, { role: "user", text: question }].slice(-20);
  renderUser(question);
  const pending = element("div", "message assistant pending", "Ищу ответ в документах…");
  $("messages").append(pending);
  scrollToBottom();
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    });
    const data = await response.json().catch(() => ({}));
    pending.remove();
    const valid = typeof data.answer === "string" && data.answer && Array.isArray(data.sources);
    if (!response.ok || !valid) {
      renderError(typeof data.detail === "string" ? data.detail : "Не удалось получить ответ. Повторите запрос.");
      return;
    }
    history.push(messages.at(-1), { role: "assistant", text: data.answer });
    renderAnswer(data);
  } catch {
    pending.remove();
    renderError("Сервер недоступен. Проверьте подключение и повторите запрос.");
  } finally {
    setBusy(false);
    scrollToBottom();
    $("input").focus();
  }
}

function setBusy(busy) {
  $("send").disabled = busy;
  $("input").disabled = busy;
}

async function loadDocument(docId) {
  if (!documentCache.has(docId)) {
    const response = await fetch(`/api/documents/${encodeURIComponent(docId)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    documentCache.set(docId, await response.json());
  }
  return documentCache.get(docId);
}

async function openDocument(docId, chunkIds) {
  const view = $("document");
  const request = ++documentRequest;
  let doc;
  try {
    doc = await loadDocument(docId);
  } catch {
    if (request === documentRequest) {
      view.replaceChildren(element("p", "placeholder", "Не удалось загрузить документ."));
    }
    return;
  }
  if (request !== documentRequest) return; // a later click wins
  $("doc-select").value = docId;
  const marked = doc.chunks.filter((c) => chunkIds.includes(c.chunk_id)).sort((a, b) => a.start - b.start);
  const body = element("div", "doc-text");
  let position = 0;
  for (const chunk of marked) {
    if (chunk.start < position) continue;
    body.append(document.createTextNode(doc.text.slice(position, chunk.start)));
    const mark = element("mark", "", doc.text.slice(chunk.start, chunk.end));
    if (chunk.address) mark.title = chunk.address;
    body.append(mark);
    position = chunk.end;
  }
  body.append(document.createTextNode(doc.text.slice(position)));
  view.replaceChildren(element("h2", "doc-title", doc.title), body);
  const first = body.querySelector("mark");
  if (first) first.scrollIntoView({ block: "center" });
  else view.scrollTop = 0;
}

async function loadDocumentList() {
  try {
    const response = await fetch("/api/documents");
    const docs = response.ok ? await response.json() : [];
    if (!Array.isArray(docs)) return;
    const select = $("doc-select");
    const groups = { company: element("optgroup"), law: element("optgroup") };
    groups.company.label = "Документы компании";
    groups.law.label = "Законы";
    for (const doc of docs) {
      const option = element("option", "", doc.title);
      option.value = doc.doc_id;
      groups[doc.kind === "law" ? "law" : "company"].append(option);
    }
    select.append(groups.company, groups.law);
  } catch {
    // The chat still works without the list.
  }
}

function renderExamples() {
  const box = $("examples");
  box.replaceChildren(element("p", "examples-label", "Например:"));
  for (const text of EXAMPLES) {
    const button = element("button", "example", text);
    button.type = "button";
    button.addEventListener("click", () => ask(text));
    box.append(button);
  }
  box.hidden = false;
}

function reset() {
  history.length = 0;
  $("messages").replaceChildren();
  renderExamples();
  $("input").focus();
}

document.addEventListener("DOMContentLoaded", () => {
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("input").value;
    $("input").value = "";
    ask(text);
  });
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("doc-select").addEventListener("change", (event) => {
    if (event.target.value) openDocument(event.target.value, []);
  });
  $("reset").addEventListener("click", reset);
  loadDocumentList();
  renderExamples();
});
