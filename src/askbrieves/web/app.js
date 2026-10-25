"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const conversation = $("conversation");
  const question = $("question");
  const sendButton = $("send-button");
  const historyButton = $("history-button");
  const notice = $("notice");
  let token = "";
  let busy = false;
  let activeRequest = null;

  function updateControls() {
    sendButton.disabled = busy || !token || !question.value.trim();
    historyButton.disabled = busy || !token;
    $("clear-button").disabled = busy;
    $("send-label").textContent = busy ? "One moment…" : "Ask Brieves";
    $("character-count").textContent = `${question.value.length} / 500`;
    $("connection-state").classList.toggle("ready", Boolean(token));
    $("connection-label").textContent = token ? "Ready to ask" : "Access required";
    $("disconnect-button").hidden = !token;
    $("access-panel").hidden = Boolean(token);
    question.setAttribute("aria-busy", String(busy));
  }

  function showNotice(message, error = false) {
    notice.textContent = message;
    notice.classList.toggle("error", error);
  }

  function safeSource(raw) {
    if (typeof raw !== "string") return null;
    try {
      const url = new URL(raw);
      if (url.protocol === "https:" && url.hostname === "home.treasury.gov" && !url.username && !url.password && !url.port && url.pathname.startsWith("/resource-center/data-chart-center/interest-rates/")) return url.href;
    } catch (_) {
      return null;
    }
    return null;
  }

  function addMessage(role, text, details = {}) {
    const article = document.createElement("article");
    article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
    if (details.error) article.classList.add("message-error");
    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent = role === "user" ? "YOU" : details.status === "declined" ? "BRIEVES · OUT OF SCOPE" : "BRIEVES";
    const body = document.createElement("p");
    const source = safeSource(details.evidence && details.evidence.source_url);
    let content = typeof text === "string" ? text : "No answer was returned. Please try again.";
    if (source && content.endsWith(`Source: ${details.evidence.source_url}`)) {
      content = content.slice(0, -(`Source: ${details.evidence.source_url}`).length).trim();
    }
    body.textContent = content;
    article.append(label, body);
    const asOf = details.evidence && details.evidence.as_of;
    if (source || (typeof asOf === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asOf))) {
      const meta = document.createElement("div");
      meta.className = "message-meta";
      if (typeof asOf === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asOf)) {
        const date = document.createElement("span");
        date.textContent = `As of ${asOf}`;
        meta.append(date);
      }
      if (source) {
        const link = document.createElement("a");
        link.href = source;
        link.textContent = "View Treasury source ↗";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        meta.append(link);
      }
      article.append(meta);
    }
    conversation.append(article);
    conversation.scrollTop = conversation.scrollHeight;
    return article;
  }

  function disconnect() {
    token = "";
    $("access-token").value = "";
    if (activeRequest) activeRequest.abort();
    updateControls();
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    activeRequest = controller;
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(path, {
        ...options,
        headers: {"Content-Type": "application/json", "Authorization": `Bearer ${token}`},
        cache: "no-store",
        redirect: "error",
        credentials: "omit",
        signal: controller.signal,
      });
      if (response.status === 401) {
        disconnect();
        throw new Error("Your access token was not accepted. Enter a valid token to reconnect.");
      }
      if (response.status === 429) throw new Error("The request limit has been reached. Please wait and try again later; the daily allowance resets at midnight UTC.");
      if (response.status === 503) throw new Error("Brieves couldn’t verify an answer right now. Please try again in a moment.");
      if (!response.ok) throw new Error("That request couldn’t be completed. Please check your question and try again.");
      try {
        return await response.json();
      } catch (_) {
        throw new Error("An unexpected response arrived. Please try again.");
      }
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The request was interrupted or took too long. You can try again when you’re ready.");
      if (error instanceof TypeError) throw new Error("Couldn’t reach Brieves. Check your connection and try again.");
      throw error;
    } finally {
      clearTimeout(timeout);
      if (activeRequest === controller) activeRequest = null;
    }
  }

  $("access-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("access-token").value.trim();
    if (!value || busy) return;
    token = value;
    $("access-token").value = "";
    showNotice("Ready. Ask a question below.");
    updateControls();
    question.focus();
  });

  $("disconnect-button").addEventListener("click", () => {
    disconnect();
    showNotice("Disconnected. Enter an access token to continue.");
    $("access-token").focus();
  });

  question.addEventListener("input", updateControls);
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!sendButton.disabled) $("question-form").requestSubmit();
      else if (!token) {
        showNotice("Connect with your access token first.");
        $("access-token").focus();
      }
    }
  });

  document.querySelectorAll(".example-button").forEach((button) => {
    button.addEventListener("click", () => {
      if (busy) return;
      question.value = button.dataset.question || "";
      updateControls();
      question.focus();
      if (!token) showNotice("Connect with your access token, then send your question.");
    });
  });

  $("question-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = question.value.trim();
    if (busy || !token || !text || text.length > 500) return;
    busy = true;
    showNotice("");
    addMessage("user", text);
    question.value = "";
    const thinking = addMessage("assistant", "Checking the latest published data…");
    thinking.classList.add("thinking");
    updateControls();
    try {
      const data = await api("/questions", {method: "POST", body: JSON.stringify({question: text.replace(/[\r\n\t]+/g, " ")})});
      thinking.remove();
      addMessage("assistant", data.answer, {evidence: data.evidence, status: data.status});
    } catch (error) {
      thinking.remove();
      addMessage("assistant", error.message, {error: true});
      showNotice("Your question has been restored. Retrying sends a new request.", true);
      if (!question.value) question.value = text;
    } finally {
      busy = false;
      updateControls();
      if (token) question.focus();
    }
  });

  historyButton.addEventListener("click", async () => {
    if (busy || !token) return;
    busy = true;
    showNotice("Loading recent questions…");
    updateControls();
    try {
      const data = await api("/history");
      if (!Array.isArray(data.items)) throw new Error("Recent history isn’t available right now.");
      if (!data.items.length) {
        showNotice("No saved questions yet. Your first brief starts above.");
      } else {
        conversation.replaceChildren();
        data.items.slice(0, 20).reverse().forEach((item) => {
          if (!item || typeof item !== "object") return;
          addMessage("user", item.question);
          addMessage("assistant", typeof item.answer === "string" ? item.answer : "This question did not have a completed answer.", {evidence: item.evidence, status: item.status});
        });
        showNotice("Showing recent questions from this shared demo.");
      }
    } catch (error) {
      showNotice(error.message, true);
    } finally {
      busy = false;
      updateControls();
    }
  });

  $("clear-button").addEventListener("click", () => {
    if (busy) return;
    conversation.replaceChildren();
    addMessage("assistant", "A fresh page. What would you like to know about Treasury yields?");
    showNotice("Chat cleared in this tab. Saved history is unchanged.");
  });

  window.addEventListener("pagehide", () => {
    token = "";
    $("access-token").value = "";
    if (activeRequest) activeRequest.abort();
  });
  window.addEventListener("pageshow", updateControls);
  updateControls();
})();
