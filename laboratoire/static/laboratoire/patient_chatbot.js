(() => {
  const launcher = document.querySelector(".as-launcher");
  const panel = document.querySelector("#as-panel");
  if (!launcher || !panel) return;

  const closeButton = panel.querySelector(".as-close");
  const messageLog = panel.querySelector(".as-messages");
  const form = panel.querySelector(".as-form");
  const input = panel.querySelector("#as-question");
  const sendButton = form.querySelector("button[type=submit]");
  const counter = panel.querySelector(".as-counter");
  const suggestions = panel.querySelectorAll(".as-suggestions button");
  let lastFailedQuestion = "";
  let loadingMessage = null;
  let isSending = false;

  const timestamp = () => new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());

  const scrollToLatest = () => {
    messageLog.scrollTop = messageLog.scrollHeight;
  };

  const addMessage = (text, sender, options = {}) => {
    const message = document.createElement("div");
    message.className = `as-message as-message--${sender}`;
    message.setAttribute("dir", "auto");

    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    message.append(paragraph);

    if (options.fallback) {
      const contactLink = document.createElement("a");
      contactLink.href = form.dataset.contactUrl;
      contactLink.textContent = "Contacter le laboratoire";
      message.append(contactLink);
    }
    if (options.retry) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "as-retry";
      retry.textContent = "Réessayer";
      retry.addEventListener("click", () => sendQuestion(options.retry));
      message.append(retry);
    }

    const time = document.createElement("time");
    time.dateTime = new Date().toISOString();
    time.textContent = timestamp();
    message.append(time);
    messageLog.append(message);
    scrollToLatest();
    return message;
  };

  const showLoading = () => {
    loadingMessage = document.createElement("div");
    loadingMessage.className = "as-message as-message--assistant as-loading";
    loadingMessage.setAttribute("role", "status");
    loadingMessage.setAttribute("dir", "auto");
    const label = document.createElement("span");
    label.textContent = "L’assistant écrit";
    const dots = document.createElement("span");
    dots.className = "as-dots";
    dots.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) dots.append(document.createElement("span"));
    loadingMessage.append(label, dots);
    messageLog.append(loadingMessage);
    scrollToLatest();
  };

  const sendQuestion = async (question) => {
    const cleanQuestion = question.trim();
    if (!cleanQuestion || isSending) return;
    isSending = true;
    lastFailedQuestion = cleanQuestion;
    addMessage(cleanQuestion, "patient");
    input.value = "";
    counter.textContent = "0 / 300";
    sendButton.disabled = true;
    suggestions.forEach((button) => { button.disabled = true; });
    showLoading();

    try {
      const payload = new FormData(form);
      payload.set("question", cleanQuestion);
      const response = await fetch(form.action, {
        method: "POST",
        body: payload,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const result = await response.json();
      if (!response.ok || typeof result.answer !== "string") {
        throw new Error("La réponse du service est invalide.");
      }
      loadingMessage.remove();
      loadingMessage = null;
      addMessage(result.answer, "assistant", {
        fallback: result.id === null,
      });
      lastFailedQuestion = "";
    } catch (_error) {
      if (loadingMessage) loadingMessage.remove();
      loadingMessage = null;
      addMessage("Service indisponible, réessayez plus tard.", "assistant", {
        retry: lastFailedQuestion,
      });
    } finally {
      isSending = false;
      sendButton.disabled = input.value.trim().length === 0;
      suggestions.forEach((button) => { button.disabled = false; });
      scrollToLatest();
    }
  };

  const openPanel = () => {
    if (!panel.open) panel.showModal();
    launcher.setAttribute("aria-expanded", "true");
    input.focus();
  };

  const closePanel = () => {
    if (panel.open) panel.close();
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  };

  launcher.addEventListener("click", openPanel);
  closeButton.addEventListener("click", closePanel);
  panel.addEventListener("cancel", (event) => {
    event.preventDefault();
    closePanel();
  });
  panel.addEventListener("close", () => {
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  });
  input.addEventListener("input", () => {
    counter.textContent = `${input.value.length} / 300`;
    sendButton.disabled = input.value.trim().length === 0;
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendQuestion(input.value);
  });
  suggestions.forEach((button) => {
    button.addEventListener("click", () => sendQuestion(button.textContent));
  });
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closePanel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(panel.querySelectorAll(
      "button:not(:disabled), input:not(:disabled), a[href]",
    )).filter((element) => !element.closest("[hidden]"));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
})();
