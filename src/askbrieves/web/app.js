"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const conversation = $("conversation");
  const question = $("question");
  const dialog = $("access-dialog");
  let token = "";
  let busy = false;
  let activeRequest = null;

  function updateControls() {
    $("send-button").disabled = busy || !question.value.trim();
    $("history-button").disabled = busy;
    $("clear-button").disabled = busy;
    $("access-button").textContent = token ? "Connected" : "Access";
    $("access-button").classList.toggle("connected", Boolean(token));
    $("disconnect-button").hidden = !token;
    question.setAttribute("aria-busy", String(busy));
  }
  function showNotice(text, error = false) {
    $("notice").textContent = text;
    $("notice").classList.toggle("error", error);
  }
  function openAccess() {
    if (!dialog.open) dialog.showModal();
    $("access-token").focus();
  }
  function safeSource(raw) {
    if (typeof raw !== "string") return null;
    try {
      const url = new URL(raw);
      if (url.protocol === "https:" && url.hostname === "home.treasury.gov" && !url.username && !url.password && !url.port && url.pathname.startsWith("/resource-center/data-chart-center/interest-rates/")) {
        // Older saved answers cite the XML feed. Open the readable table instead.
        if (url.pathname.endsWith("/pages/xml") && url.searchParams.get("data") === "daily_treasury_yield_curve") {
          const month = url.searchParams.get("field_tdr_date_value_month");
          if (!/^\d{6}$/.test(month || "")) return null;
          return `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value_month=${month}`;
        }
        return url.href;
      }
    } catch (_) { return null; }
    return null;
  }
  function addMessage(role, text, details = {}) {
    $("empty-state")?.remove();
    const article = document.createElement("article");
    article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
    if (details.error) article.classList.add("message-error");
    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent = role === "user" ? "YOU" : "BRIEVES";
    const body = document.createElement("p");
    const evidence = details.evidence;
    const observations = evidence && Array.isArray(evidence.observations) ? evidence.observations.slice(0, 2) : evidence ? [evidence] : [];
    const sourceUrls = [...new Set(observations.filter((item) => item && safeSource(item.source_url)).map((item) => item.source_url))];
    let content = typeof text === "string" ? text : "No answer available.";
    const citation = (sourceUrls.length === 1 ? "Source: " : "Sources: ") + sourceUrls.join(" | ");
    if (sourceUrls.length && content.endsWith(citation)) content = content.slice(0, -citation.length).trim();
    body.textContent = content;
    article.append(label, body);
    for (const observation of observations) {
      if (!observation || typeof observation !== "object") continue;
      const source = safeSource(observation.source_url);
      const asOf = observation.as_of;
      if (!source && !(typeof asOf === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asOf))) continue;
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
        link.textContent = observations.length === 1 ? "Treasury source ↗" : `Treasury source · ${asOf} ↗`;
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
      const response = await fetch(path, {...options, headers: {"Content-Type": "application/json", "Authorization": `Bearer ${token}`}, cache: "no-store", redirect: "error", credentials: "omit", signal: controller.signal});
      if (response.status === 401) {
        disconnect();
        throw new Error("Access token not accepted. Reconnect to try again.");
      }
      if (response.status === 429) throw new Error("Request limit reached. Please try later; the daily limit resets at midnight UTC.");
      if (response.status === 503) throw new Error("Rates are unavailable right now. Please try again shortly.");
      if (!response.ok) throw new Error("Couldn’t complete that request. Please try again.");
      try { return await response.json(); }
      catch (_) { throw new Error("Unexpected response. Please try again."); }
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Request interrupted. Try again when you’re ready.");
      if (error instanceof TypeError) throw new Error("Couldn’t connect. Check your connection and try again.");
      throw error;
    } finally {
      clearTimeout(timeout);
      if (activeRequest === controller) activeRequest = null;
    }
  }
  $("access-button").addEventListener("click", openAccess);
  $("close-access").addEventListener("click", () => { $("access-token").value = ""; dialog.close(); });
  dialog.addEventListener("cancel", () => { $("access-token").value = ""; });
  $("access-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("access-token").value.trim();
    if (!value || busy) return;
    token = value;
    $("access-token").value = "";
    dialog.close();
    showNotice("Ready. Press send to ask.");
    updateControls();
    question.focus();
  });
  $("disconnect-button").addEventListener("click", () => {
    disconnect();
    dialog.close();
    showNotice("Disconnected.");
  });
  question.addEventListener("input", () => {
    question.rows = Math.min(4, Math.max(1, question.value.split("\n").length));
    updateControls();
  });
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!$("send-button").disabled) $("question-form").requestSubmit();
    }
  });
  document.querySelectorAll(".suggestion").forEach((button) => {
    button.addEventListener("click", () => {
      if (busy) return;
      question.value = button.dataset.question || "";
      updateControls();
      question.focus();
    });
  });
  $("question-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = question.value.trim();
    if (busy || !text || text.length > 500) return;
    if (!token) { openAccess(); return; }
    busy = true;
    showNotice("");
    addMessage("user", text);
    question.value = "";
    question.rows = 1;
    const thinking = addMessage("assistant", "Checking Treasury data…");
    thinking.classList.add("thinking");
    updateControls();
    try {
      const data = await api("/questions", {method: "POST", body: JSON.stringify({question: text.replace(/[\r\n\t]+/g, " ")})});
      thinking.remove();
      addMessage("assistant", data.answer, {evidence: data.evidence});
    } catch (error) {
      thinking.remove();
      addMessage("assistant", error.message, {error: true});
      if (!question.value) question.value = text;
      showNotice("Question restored. Send again to retry.", true);
    } finally {
      busy = false;
      updateControls();
      question.focus();
    }
  });
  $("history-button").addEventListener("click", async () => {
    if (busy) return;
    if (!token) { openAccess(); return; }
    busy = true;
    showNotice("Loading history…");
    updateControls();
    try {
      const data = await api("/history");
      if (!Array.isArray(data.items)) throw new Error("History unavailable.");
      if (!data.items.length) showNotice("No history yet.");
      else {
        conversation.replaceChildren();
        data.items.slice(0, 20).reverse().forEach((item) => {
          if (!item || typeof item !== "object") return;
          addMessage("user", item.question);
          addMessage("assistant", typeof item.answer === "string" ? item.answer : "No completed answer.", {evidence: item.evidence});
        });
        showNotice("Recent questions · Shared demo history");
      }
    } catch (error) { showNotice(error.message, true); }
    finally { busy = false; updateControls(); }
  });
  const initialEmptyState = $("empty-state").cloneNode(true);
  $("clear-button").addEventListener("click", () => {
    if (busy) return;
    conversation.replaceChildren(initialEmptyState.cloneNode(true));
    conversation.querySelectorAll(".suggestion").forEach((button) => button.addEventListener("click", () => {
      question.value = button.dataset.question || "";
      updateControls();
      question.focus();
    }));
    showNotice("");
  });
  window.addEventListener("pagehide", () => {
    token = "";
    $("access-token").value = "";
    if (activeRequest) activeRequest.abort();
  });
  window.addEventListener("pageshow", updateControls);
  updateControls();
})();
