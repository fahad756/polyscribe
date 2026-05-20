const state = {
  chats: [],
  currentChatId: null,
  messages: [],
  busy: false,
  selectedFile: null,
};

const els = {
  sidebar: document.getElementById("sidebar"),
  menuButton: document.getElementById("menuButton"),
  newChatButton: document.getElementById("newChatButton"),
  themeButton: document.getElementById("themeButton"),
  chatList: document.getElementById("chatList"),
  activeChatTitle: document.getElementById("activeChatTitle"),
  statusText: document.getElementById("statusText"),
  messageList: document.getElementById("messageList"),
  emptyState: document.getElementById("emptyState"),
  emptyGreeting: document.getElementById("emptyGreeting"),
  emptySubtitle: document.getElementById("emptySubtitle"),
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("messageInput"),
  fileInput: document.getElementById("fileInput"),
  attachmentRow: document.getElementById("attachmentRow"),
  attachButton: document.getElementById("attachButton"),
  sendButton: document.getElementById("sendButton"),
  dropOverlay: document.getElementById("dropOverlay"),
  sourceToast: document.getElementById("sourceToast"),
  welcomeModal: document.getElementById("welcomeModal"),
  welcomeForm: document.getElementById("welcomeForm"),
  nameInput: document.getElementById("nameInput"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });

  if (response.status === 401) {
    window.location.href = "/login";
    return null;
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed with status ${response.status}`);
  }
  return data;
}

function setBusy(value, label = "Ready") {
  state.busy = value;
  els.statusText.textContent = label;
  els.sendButton.disabled = value;
  els.attachButton.disabled = value;
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    els.messageList.scrollTop = els.messageList.scrollHeight;
  });
}

function currentChat() {
  return state.chats.find((chat) => chat.id === state.currentChatId);
}

function renderChats() {
  els.chatList.textContent = "";
  for (const chat of state.chats) {
    const item = document.createElement("div");
    item.className = `chat-item${chat.id === state.currentChatId ? " is-active" : ""}`;

    const open = document.createElement("button");
    open.type = "button";
    open.className = "chat-open";
    open.addEventListener("click", () => selectChat(chat.id));

    const title = document.createElement("span");
    title.className = "chat-title";
    title.textContent = chat.title || "New chat";
    open.appendChild(title);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete-chat";
    remove.textContent = "x";
    remove.title = "Delete chat";
    remove.setAttribute("aria-label", "Delete chat");
    remove.addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteChat(chat.id);
    });

    item.append(open, remove);
    els.chatList.appendChild(item);
  }
}

function renderMessages(messages = state.messages) {
  els.messageList.textContent = "";

  if (!messages.length) {
    els.messageList.appendChild(els.emptyState);
    return;
  }

  for (const message of messages) {
    const article = document.createElement("article");
    article.className = `message ${message.role}${message.pending ? " pending" : ""}`;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = message.role === "user" ? "You" : "AI";

    const content = document.createElement("div");
    content.className = "message-content";

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = message.role === "user" ? "You" : "PolyScribe";

    const body = document.createElement("div");
    body.className = "message-body";
    body.textContent = message.content;

    content.append(meta, body);

    if (message.role === "assistant" && !message.pending) {
      const actions = document.createElement("div");
      actions.className = "message-actions";
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy-button";
      copy.textContent = "Copy";
      copy.addEventListener("click", async () => {
        await navigator.clipboard.writeText(message.content);
        copy.textContent = "Copied";
        setTimeout(() => {
          copy.textContent = "Copy";
        }, 1200);
      });
      actions.appendChild(copy);
      content.appendChild(actions);
    }

    article.append(avatar, content);
    els.messageList.appendChild(article);
  }
  scrollToBottom();
}

function renderAttachment() {
  els.attachmentRow.textContent = "";
  if (!state.selectedFile) {
    els.attachmentRow.hidden = true;
    return;
  }

  const chip = document.createElement("div");
  chip.className = "attachment-chip";

  const icon = document.createElement("span");
  icon.className = "attachment-icon";
  icon.textContent = "A";

  const detail = document.createElement("div");
  detail.className = "attachment-detail";

  const name = document.createElement("strong");
  name.textContent = state.selectedFile.name;

  const meta = document.createElement("span");
  meta.textContent = `${formatBytes(state.selectedFile.size)} ready to send`;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "attachment-remove";
  remove.textContent = "x";
  remove.setAttribute("aria-label", "Remove attachment");
  remove.addEventListener("click", clearAttachment);

  detail.append(name, meta);
  chip.append(icon, detail, remove);
  els.attachmentRow.appendChild(chip);
  els.attachmentRow.hidden = false;
}

function stageFile(file) {
  if (!file || state.busy) return;
  state.selectedFile = file;
  renderAttachment();
  els.messageInput.focus();
}

function clearAttachment() {
  state.selectedFile = null;
  els.fileInput.value = "";
  renderAttachment();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function updateActiveTitle() {
  const chat = currentChat();
  els.activeChatTitle.textContent = chat?.title || "New chat";
}

async function refreshChats() {
  const data = await api("/api/chats");
  if (!data) return;
  state.chats = data.chats;
  renderChats();
  updateActiveTitle();
}

async function createChat() {
  const data = await api("/api/chats", { method: "POST" });
  if (!data) return;
  state.chats = [data.chat, ...state.chats];
  state.currentChatId = data.chat.id;
  state.messages = [];
  renderChats();
  renderMessages();
  updateActiveTitle();
}

async function selectChat(chatId) {
  state.currentChatId = chatId;
  els.sidebar.classList.remove("is-open");
  renderChats();
  updateActiveTitle();
  const data = await api(`/api/chats/${chatId}`);
  if (!data) return;
  state.messages = data.messages;
  updateChatInList(data.chat);
  renderChats();
  updateActiveTitle();
  renderMessages();
}

async function deleteChat(chatId) {
  await api(`/api/chats/${chatId}`, { method: "DELETE" });
  state.chats = state.chats.filter((chat) => chat.id !== chatId);
  if (state.currentChatId === chatId) {
    if (state.chats.length) {
      await selectChat(state.chats[0].id);
    } else {
      await createChat();
    }
  }
  renderChats();
}

function updateChatInList(chat) {
  const index = state.chats.findIndex((item) => item.id === chat.id);
  if (index >= 0) {
    state.chats[index] = chat;
  } else {
    state.chats.unshift(chat);
  }
  state.chats.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
}

function showError(error) {
  const message = {
    id: `error-${Date.now()}`,
    role: "assistant",
    content: error.message || "Something went wrong.",
  };
  renderMessages([...state.messages, message]);
}

async function sendMessage(event) {
  event.preventDefault();
  const content = els.messageInput.value.trim();
  if ((!content && !state.selectedFile) || state.busy) return;
  if (state.selectedFile) {
    await uploadFile(state.selectedFile, content);
    return;
  }
  if (!state.currentChatId) await createChat();

  els.messageInput.value = "";
  resizeTextarea();
  setBusy(true, "Thinking");
  renderMessages([
    ...state.messages,
    { id: "pending-user", role: "user", content },
    { id: "pending-assistant", role: "assistant", content: "Thinking...", pending: true },
  ]);

  try {
    const data = await api(`/api/chats/${state.currentChatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    if (!data) return;
    state.messages = data.messages;
    updateChatInList(data.chat);
    renderChats();
    updateActiveTitle();
    renderMessages();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function uploadFile(file, prompt = "") {
  if (!file || state.busy) return;
  if (!state.currentChatId) await createChat();

  els.messageInput.value = "";
  resizeTextarea();
  clearAttachment();

  const body = new FormData();
  body.append("file", file);
  body.append("prompt", prompt);
  body.append("language", "");

  setBusy(true, "Transcribing");
  const uploadText = prompt ? `Uploaded ${file.name}\n\n${prompt}` : `Uploaded ${file.name}`;
  renderMessages([
    ...state.messages,
    { id: "pending-upload", role: "user", content: uploadText },
    { id: "pending-transcribing", role: "assistant", content: "Listening closely...", pending: true },
  ]);

  try {
    const data = await api(`/api/chats/${state.currentChatId}/uploads`, {
      method: "POST",
      body,
    });
    if (!data) return;
    state.messages = data.messages;
    updateChatInList(data.chat);
    renderChats();
    updateActiveTitle();
    renderMessages();
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
    els.fileInput.value = "";
  }
}

function resizeTextarea() {
  const input = els.messageInput;
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

function applyTheme(theme) {
  const selected = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = selected;
  localStorage.setItem("polyscribe-theme", selected);
  els.themeButton.textContent = selected === "dark" ? "Light" : "Dark";
  els.themeButton.setAttribute(
    "aria-label",
    selected === "dark" ? "Switch to light mode" : "Switch to dark mode",
  );
}

function installThemeToggle() {
  const stored = localStorage.getItem("polyscribe-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(stored || preferred);
  els.themeButton.addEventListener("click", () => {
    const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    applyTheme(current === "dark" ? "light" : "dark");
  });
}

function applyVisitorName(name, firstVisit = false) {
  const cleanName = (name || "").trim();
  if (!cleanName) {
    els.emptyGreeting.textContent = "PolyScribe";
    els.emptySubtitle.textContent = "Audio in. Clean words out. Then ask away.";
    return;
  }
  els.emptyGreeting.textContent = firstVisit ? `Welcome, ${cleanName}` : `Welcome back, ${cleanName}`;
  els.emptySubtitle.textContent = "Attach audio, add a prompt, and I will handle the transcript first.";
}

function installWelcomeFlow() {
  const storedName = localStorage.getItem("polyscribe-name") || "";
  if (storedName.trim()) {
    applyVisitorName(storedName);
    return;
  }

  els.welcomeModal.hidden = false;
  requestAnimationFrame(() => els.nameInput.focus());
  els.welcomeForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = els.nameInput.value.trim();
    if (!name) {
      els.nameInput.focus();
      return;
    }
    localStorage.setItem("polyscribe-name", name);
    els.welcomeModal.hidden = true;
    applyVisitorName(name, true);
  });
}

function showSourceToast() {
  els.sourceToast.classList.add("is-visible");
  clearTimeout(showSourceToast.timeoutId);
  showSourceToast.timeoutId = setTimeout(() => {
    els.sourceToast.classList.remove("is-visible");
  }, 1800);
}

function installSourceGuard() {
  window.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    showSourceToast();
  });

  window.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    const blocked =
      event.key === "F12" ||
      (event.ctrlKey && event.shiftKey && ["i", "j", "c"].includes(key)) ||
      (event.ctrlKey && key === "u");

    if (blocked) {
      event.preventDefault();
      showSourceToast();
    }
  });
}

function installDragAndDrop() {
  let dragDepth = 0;

  window.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragDepth += 1;
    document.body.classList.add("is-dragging");
  });

  window.addEventListener("dragover", (event) => {
    event.preventDefault();
  });

  window.addEventListener("dragleave", (event) => {
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) document.body.classList.remove("is-dragging");
  });

  window.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    document.body.classList.remove("is-dragging");
    const file = event.dataTransfer.files[0];
    stageFile(file);
  });
}

function bindEvents() {
  els.composer.addEventListener("submit", sendMessage);
  els.messageInput.addEventListener("input", resizeTextarea);
  els.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      els.composer.requestSubmit();
    }
  });
  els.attachButton.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", () => stageFile(els.fileInput.files[0]));
  els.newChatButton.addEventListener("click", createChat);
  els.menuButton.addEventListener("click", () => els.sidebar.classList.toggle("is-open"));

  installWelcomeFlow();
  installThemeToggle();
  installSourceGuard();
  installDragAndDrop();
}

async function boot() {
  bindEvents();
  await refreshChats();
  if (state.chats.length) {
    await selectChat(state.chats[0].id);
  } else {
    await createChat();
  }
}

boot().catch((error) => {
  setBusy(false);
  showError(error);
});
