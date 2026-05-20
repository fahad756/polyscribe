const state = {
  chats: [],
  currentChatId: null,
  messages: [],
  busy: false,
  creatingChat: false,
  selectedFile: null,
  selectedFileMeta: null,
  recording: false,
  recordingChunks: [],
  recordingMimeType: "",
  recordingStartedAt: 0,
  recordingTimerId: null,
  recordingStream: null,
  mediaRecorder: null,
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
  composerTools: document.getElementById("composerTools"),
  attachButton: document.getElementById("attachButton"),
  attachMenu: document.getElementById("attachMenu"),
  uploadOption: document.getElementById("uploadOption"),
  recordOption: document.getElementById("recordOption"),
  recordOptionTitle: document.getElementById("recordOptionTitle"),
  recordOptionMeta: document.getElementById("recordOptionMeta"),
  quickRecordButton: document.getElementById("quickRecordButton"),
  sendButton: document.getElementById("sendButton"),
  dropOverlay: document.getElementById("dropOverlay"),
  sourceToast: document.getElementById("sourceToast"),
  welcomeModal: document.getElementById("welcomeModal"),
  welcomeForm: document.getElementById("welcomeForm"),
  nameInput: document.getElementById("nameInput"),
};

const titleAnimationTimers = new Map();

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
  updateControls();
}

function updateControls() {
  const locked = state.busy || state.creatingChat;
  els.sendButton.disabled = locked || state.recording;
  els.attachButton.disabled = locked;
  els.uploadOption.disabled = locked || state.recording;
  els.recordOption.disabled = locked && !state.recording;
  els.quickRecordButton.disabled = locked && !state.recording;
  els.newChatButton.disabled = locked || state.recording;
  for (const button of document.querySelectorAll(".chat-open, .delete-chat")) {
    button.disabled = locked || state.recording;
  }
  updateRecordOption();
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
    item.dataset.chatId = chat.id;

    const open = document.createElement("button");
    open.type = "button";
    open.className = "chat-open";
    open.disabled = state.busy || state.creatingChat;
    open.addEventListener("click", () => selectChat(chat.id));

    const title = document.createElement("span");
    title.className = "chat-title";
    title.textContent = chat.title || "New chat";
    open.appendChild(title);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete-chat";
    remove.disabled = state.busy || state.creatingChat;
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

function animateChatTitle(chatId, title) {
  const fullTitle = (title || "").trim();
  if (!chatId || !fullTitle || fullTitle === "New chat") return;

  const existingTimers = titleAnimationTimers.get(chatId) || [];
  for (const timerId of existingTimers) clearTimeout(timerId);

  const titleElement = els.chatList.querySelector(`[data-chat-id="${chatId}"] .chat-title`);
  if (!titleElement) return;

  const timers = [];
  titleAnimationTimers.set(chatId, timers);
  titleElement.textContent = "";
  titleElement.classList.add("is-typing");

  let index = 0;
  const step = () => {
    index += 1;
    titleElement.textContent = fullTitle.slice(0, index);
    if (index < fullTitle.length) {
      timers.push(setTimeout(step, 24));
      return;
    }
    titleElement.classList.remove("is-typing");
    titleAnimationTimers.delete(chatId);
  };
  step();
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
    avatar.textContent = message.role === "user" ? "You" : "P";

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
  if (state.recording) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip is-recording";

    const icon = document.createElement("span");
    icon.className = "attachment-icon recording-dot";
    icon.textContent = "";

    const detail = document.createElement("div");
    detail.className = "attachment-detail";

    const name = document.createElement("strong");
    name.textContent = "Listening...";

    const meta = document.createElement("span");
    meta.textContent = `${formatDuration(Date.now() - state.recordingStartedAt)} recorded`;

    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "attachment-remove stop-recording";
    stop.textContent = "Stop";
    stop.setAttribute("aria-label", "Stop listening");
    stop.addEventListener("click", stopRecording);

    detail.append(name, meta);
    chip.append(icon, detail, stop);
    els.attachmentRow.appendChild(chip);
    els.attachmentRow.hidden = false;
    return;
  }

  if (!state.selectedFile) {
    els.attachmentRow.hidden = true;
    return;
  }

  const chip = document.createElement("div");
  chip.className = "attachment-chip";

  const icon = document.createElement("span");
  icon.className = "attachment-icon";
  icon.textContent = state.selectedFileMeta?.source === "recording" ? "R" : "A";

  const detail = document.createElement("div");
  detail.className = "attachment-detail";

  const name = document.createElement("strong");
  name.textContent = state.selectedFileMeta?.source === "recording"
    ? "Recorded audio"
    : state.selectedFile.name;

  const meta = document.createElement("span");
  const duration = state.selectedFileMeta?.durationMs
    ? ` - ${formatDuration(state.selectedFileMeta.durationMs)}`
    : "";
  meta.textContent = `${formatBytes(state.selectedFile.size)}${duration} ready to send`;

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

function stageFile(file, meta = null) {
  if (!file || state.busy || state.recording) return;
  state.selectedFile = file;
  state.selectedFileMeta = meta;
  renderAttachment();
  els.messageInput.focus();
}

function clearAttachment() {
  state.selectedFile = null;
  state.selectedFileMeta = null;
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

function formatDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
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

function openDraftChat({ focus = true } = {}) {
  if (state.busy || state.creatingChat || state.recording) return currentChat();
  state.currentChatId = null;
  state.messages = [];
  els.messageInput.value = "";
  resizeTextarea();
  clearAttachment();
  els.sidebar.classList.remove("is-open");
  renderChats();
  updateActiveTitle();
  renderMessages();
  if (focus) els.messageInput.focus();
  return null;
}

async function createChat() {
  if (state.recording) return null;
  if (state.currentChatId) return currentChat() || { id: state.currentChatId };
  if (state.busy || state.creatingChat) return null;
  state.creatingChat = true;
  updateControls();
  if (!state.busy) els.statusText.textContent = "Starting chat";

  try {
    const data = await api("/api/chats", { method: "POST" });
    if (!data) return null;
    state.currentChatId = data.chat.id;
    updateActiveTitle();
    return data.chat;
  } finally {
    state.creatingChat = false;
    if (!state.busy) els.statusText.textContent = "Ready";
    updateControls();
  }
}

async function selectChat(chatId) {
  if (state.busy || state.creatingChat || state.recording || chatId === state.currentChatId) return;
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
  if (state.busy || state.creatingChat || state.recording) return;
  await api(`/api/chats/${chatId}`, { method: "DELETE" });
  state.chats = state.chats.filter((chat) => chat.id !== chatId);
  if (state.currentChatId === chatId) {
    if (state.chats.length) {
      await selectChat(state.chats[0].id);
    } else {
      openDraftChat({ focus: false });
    }
  }
  renderChats();
}

function updateChatInList(chat) {
  const index = state.chats.findIndex((item) => item.id === chat.id);
  const previousTitle = index >= 0 ? state.chats[index].title || "" : "";
  const nextTitle = chat.title || "New chat";
  if (index >= 0) {
    state.chats[index] = chat;
  } else {
    state.chats.unshift(chat);
  }
  state.chats.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  return nextTitle !== "New chat" && previousTitle !== nextTitle;
}

function showError(error) {
  const message = {
    id: `error-${Date.now()}`,
    role: "assistant",
    content: error.message || "Something went wrong.",
  };
  renderMessages([...state.messages, message]);
}

function setAttachMenu(open) {
  els.attachMenu.hidden = !open;
  els.attachButton.setAttribute("aria-expanded", open ? "true" : "false");
}

function updateRecordOption() {
  els.recordOption.classList.toggle("is-recording", state.recording);
  els.quickRecordButton.classList.toggle("is-recording", state.recording);
  els.recordOptionTitle.textContent = state.recording ? "Stop listening" : "Listen";
  els.recordOptionMeta.textContent = state.recording
    ? `${formatDuration(Date.now() - state.recordingStartedAt)} recorded`
    : "Record from microphone";
  els.quickRecordButton.setAttribute(
    "aria-label",
    state.recording ? "Stop listening" : "Start listening",
  );
}

function recordingSupported() {
  return Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
}

function preferredRecordingMimeType() {
  const types = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  return types.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function recordingExtension(mimeType) {
  if (mimeType.includes("mp4")) return "m4a";
  if (mimeType.includes("ogg")) return "ogg";
  return "webm";
}

function recordingFilename(mimeType) {
  const stamp = new Date()
    .toISOString()
    .replace("T", "-")
    .replaceAll(":", "")
    .replace(/\.\d+Z$/, "");
  return `polyscribe-recording-${stamp}.${recordingExtension(mimeType)}`;
}

async function startRecording() {
  if (state.busy || state.creatingChat || state.recording) return;
  if (!recordingSupported()) {
    showError(new Error("Microphone recording is not supported in this browser."));
    return;
  }

  setAttachMenu(false);
  clearAttachment();

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        autoGainControl: true,
        channelCount: { ideal: 1 },
        echoCancellation: true,
        noiseSuppression: false,
        sampleRate: { ideal: 48000 },
        sampleSize: { ideal: 16 },
      },
    });
    const mimeType = preferredRecordingMimeType();
    const recorderOptions = { audioBitsPerSecond: 160000 };
    if (mimeType) recorderOptions.mimeType = mimeType;
    let recorder;
    try {
      recorder = new MediaRecorder(stream, recorderOptions);
    } catch {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    }

    state.recording = true;
    state.recordingChunks = [];
    state.recordingMimeType = recorder.mimeType || mimeType || "audio/webm";
    state.recordingStartedAt = Date.now();
    state.recordingStream = stream;
    state.mediaRecorder = recorder;

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) state.recordingChunks.push(event.data);
    });
    recorder.addEventListener("stop", finishRecording);
    recorder.start(1000);

    els.statusText.textContent = "Listening";
    state.recordingTimerId = setInterval(() => {
      renderAttachment();
      updateRecordOption();
    }, 1000);
    renderAttachment();
    updateControls();
  } catch (error) {
    cleanupRecording();
    showError(new Error(error.message || "Microphone access was blocked."));
  }
}

function stopRecording() {
  if (!state.recording || !state.mediaRecorder) return;
  if (state.mediaRecorder.state !== "inactive") {
    state.mediaRecorder.stop();
  }
}

function cleanupRecording() {
  if (state.recordingTimerId) clearInterval(state.recordingTimerId);
  if (state.recordingStream) {
    for (const track of state.recordingStream.getTracks()) track.stop();
  }
  state.recordingTimerId = null;
  state.recordingStream = null;
  state.mediaRecorder = null;
  state.recording = false;
}

function finishRecording() {
  const chunks = [...state.recordingChunks];
  const mimeType = state.recordingMimeType || "audio/webm";
  const durationMs = Date.now() - state.recordingStartedAt;

  cleanupRecording();
  state.recordingChunks = [];
  state.recordingMimeType = "";
  state.recordingStartedAt = 0;
  els.statusText.textContent = "Ready";

  if (!chunks.length) {
    renderAttachment();
    updateControls();
    showError(new Error("No microphone audio was captured."));
    return;
  }

  const blob = new Blob(chunks, { type: mimeType });
  const file = new File([blob], recordingFilename(mimeType), {
    type: blob.type || mimeType,
    lastModified: Date.now(),
  });
  state.selectedFile = file;
  state.selectedFileMeta = { source: "recording", durationMs };
  renderAttachment();
  updateControls();
  els.messageInput.focus();
}

async function syncCurrentChat() {
  if (!state.currentChatId) return;
  try {
    const data = await api(`/api/chats/${state.currentChatId}`);
    if (!data) return;
    state.messages = data.messages;
    const shouldAnimateTitle = updateChatInList(data.chat);
    renderChats();
    if (shouldAnimateTitle) animateChatTitle(data.chat.id, data.chat.title);
    updateActiveTitle();
  } catch {
    // Keep the visible error path available even if the refresh also fails.
  }
}

async function startNewChat() {
  try {
    openDraftChat();
  } catch (error) {
    showError(error);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const content = els.messageInput.value.trim();
  if ((!content && !state.selectedFile) || state.busy || state.recording) return;
  setAttachMenu(false);
  if (state.selectedFile) {
    await uploadFile(state.selectedFile, content);
    return;
  }
  if (!state.currentChatId) {
    const chat = await createChat();
    if (!chat) return;
  }

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
    const shouldAnimateTitle = updateChatInList(data.chat);
    renderChats();
    if (shouldAnimateTitle) animateChatTitle(data.chat.id, data.chat.title);
    updateActiveTitle();
    renderMessages();
  } catch (error) {
    await syncCurrentChat();
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function uploadFile(file, prompt = "") {
  if (!file || state.busy || state.recording) return;
  if (!state.currentChatId) {
    const chat = await createChat();
    if (!chat) return;
  }

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
    const shouldAnimateTitle = updateChatInList(data.chat);
    renderChats();
    if (shouldAnimateTitle) animateChatTitle(data.chat.id, data.chat.title);
    updateActiveTitle();
    renderMessages();
  } catch (error) {
    await syncCurrentChat();
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
  els.themeButton.dataset.mode = selected;
  els.themeButton.setAttribute("aria-pressed", selected === "dark" ? "true" : "false");
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
  els.attachButton.addEventListener("click", (event) => {
    event.stopPropagation();
    setAttachMenu(els.attachMenu.hidden);
  });
  els.composerTools.addEventListener("click", (event) => {
    event.stopPropagation();
  });
  els.uploadOption.addEventListener("click", () => {
    setAttachMenu(false);
    els.fileInput.click();
  });
  els.recordOption.addEventListener("click", async () => {
    if (state.recording) {
      setAttachMenu(false);
      stopRecording();
      return;
    }
    await startRecording();
  });
  els.quickRecordButton.addEventListener("click", async () => {
    if (state.recording) {
      stopRecording();
      return;
    }
    await startRecording();
  });
  document.addEventListener("click", () => setAttachMenu(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setAttachMenu(false);
  });
  els.fileInput.addEventListener("change", () => stageFile(els.fileInput.files[0]));
  els.newChatButton.addEventListener("click", startNewChat);
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
    openDraftChat({ focus: false });
  }
}

boot().catch((error) => {
  setBusy(false);
  showError(error);
});
