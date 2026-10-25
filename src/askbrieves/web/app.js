"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const conversation = $("conversation");
  const question = $("question");
  const dialog = $("access-dialog");
  const initialEmptyState = $("empty-state").cloneNode(true);
  let token = "";
  let busy = false;
  let activeRequest = null;
  let session = 0;
  let contextId = null;

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
      const officialHosts = ["home.treasury.gov", "www.federalreserve.gov", "www.investor.gov", "libertystreeteconomics.newyorkfed.org"];
      if (url.protocol === "https:" && officialHosts.includes(url.hostname) && !url.username && !url.password && !url.port) {
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
    const references = (item) => Array.isArray(item.source_urls) ? item.source_urls.slice(0, 2) : [item.source_url];
    const sourceUrls = [...new Set(observations.filter(Boolean).flatMap(references).filter((url) => safeSource(url)))];
    let content = typeof text === "string" ? text : "No answer available.";
    const citation = (sourceUrls.length === 1 ? "Source: " : "Sources: ") + sourceUrls.join(" | ");
    if (sourceUrls.length && content.endsWith(citation)) content = content.slice(0, -citation.length).trim();
    body.textContent = content;
    article.append(label, body);
    for (const observation of observations) {
      if (!observation || typeof observation !== "object") continue;
      const sources = references(observation).map(safeSource).filter(Boolean);
      const asOf = observation.as_of;
      if (!sources.length && !(typeof asOf === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asOf))) continue;
      const meta = document.createElement("div");
      meta.className = "message-meta";
      if (typeof asOf === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asOf)) {
        const date = document.createElement("span");
        date.textContent = `As of ${asOf}`;
        meta.append(date);
      }
      for (const source of sources) {
        const link = document.createElement("a");
        link.href = source;
        const label = source.includes("newyorkfed.org") ? "New York Fed source" : source.includes("treasury.gov") ? "Treasury source" : source.includes("investor.gov") ? "SEC source" : "Federal Reserve source";
        link.textContent = observations.length === 1 ? `${label} ↗` : `${label} · ${asOf} ↗`;
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
  function bindSuggestions(root) {
    root.querySelectorAll(".suggestion").forEach((button) => {
      button.addEventListener("click", () => {
        if (busy) return;
        question.value = button.dataset.question || "";
        updateControls();
        question.focus();
      });
    });
  }
  function showEmptyState() {
    conversation.replaceChildren(initialEmptyState.cloneNode(true));
    bindSuggestions(conversation);
  }
  function resetSession(nextToken = "", preserveDraft = false) {
    const draft = preserveDraft ? question.value : "";
    // Invalidate callbacks before aborting: cancellation alone cannot revoke them.
    session += 1;
    contextId = null;
    const previousRequest = activeRequest;
    activeRequest = null;
    token = nextToken;
    busy = false;
    $("access-token").value = "";
    question.value = draft;
    question.rows = Math.min(4, Math.max(1, draft.split("\n").length));
    dialog.close();
    showEmptyState();
    showNotice("");
    if (previousRequest) previousRequest.abort();
    updateControls();
  }
  function disconnect() {
    resetSession();
  }
  async function api(path, options = {}, requestSession = session) {
    if (requestSession !== session) throw new Error("Session changed.");
    const controller = new AbortController();
    activeRequest = controller;
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(path, {...options, headers: {"Content-Type": "application/json", "Authorization": `Bearer ${token}`}, cache: "no-store", redirect: "error", credentials: "omit", signal: controller.signal});
      if (requestSession !== session) throw new Error("Session changed.");
      if (response.status === 401) {
        disconnect();
        showNotice("Access token not accepted. Reconnect to try again.", true);
        throw new Error("Access token not accepted. Reconnect to try again.");
      }
      if (response.status === 429) throw new Error("Request limit reached. Retry shortly for a traffic throttle; the review allowance does not reset daily.");
      if (response.status === 403) throw new Error("The seven-day review window is not active. Contact the service owner.");
      if (response.status === 503) throw new Error("Rates are unavailable right now. Please try again shortly.");
      if (!response.ok) throw new Error("Couldn’t complete that request. Please try again.");
      try {
        const data = await response.json();
        if (requestSession !== session) throw new Error("Session changed.");
        return data;
      }
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
    if (!value) return;
    // A draft written while disconnected belongs to the new session. Replacing
    // an existing credential must discard all content owned by that audience.
    if (value !== token) resetSession(value, !token);
    $("access-token").value = "";
    dialog.close();
    if (!busy) showNotice("Ready. Press send to ask.");
    updateControls();
    if (!busy) question.focus();
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
  bindSuggestions(document);
  $("question-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = question.value.trim();
    if (busy || !text || text.length > 500) return;
    if (!token) { openAccess(); return; }
    const requestSession = session;
    busy = true;
    showNotice("");
    addMessage("user", text);
    question.value = "";
    question.rows = 1;
    const thinking = addMessage("assistant", "Checking Treasury data…");
    thinking.classList.add("thinking");
    updateControls();
    try {
      const data = await api("/questions", {method: "POST", body: JSON.stringify({question: text.replace(/[\r\n\t]+/g, " "), ...(contextId ? {context_id: contextId} : {})})}, requestSession);
      if (requestSession !== session) return;
      thinking.remove();
      if (typeof data.context_id === "string") contextId = data.context_id;
      addMessage("assistant", data.answer, {evidence: data.evidence});
    } catch (error) {
      if (requestSession !== session) return;
      thinking.remove();
      addMessage("assistant", error.message, {error: true});
      if (!question.value) question.value = text;
      showNotice("Question restored. Send again to retry.", true);
    } finally {
      if (requestSession === session) {
        busy = false;
        updateControls();
        question.focus();
      }
    }
  });
  $("history-button").addEventListener("click", async () => {
    if (busy) return;
    if (!token) { openAccess(); return; }
    const requestSession = session;
    busy = true;
    showNotice("Loading history…");
    updateControls();
    try {
      const data = await api("/history", {}, requestSession);
      if (requestSession !== session) return;
      if (!Array.isArray(data.items)) throw new Error("History unavailable.");
      contextId = null;
      showEmptyState();
      if (!data.items.length) showNotice("No history yet.");
      else {
        data.items.slice(0, 20).reverse().forEach((item) => {
          if (!item || typeof item !== "object") return;
          addMessage("user", item.question);
          addMessage("assistant", typeof item.answer === "string" ? item.answer : "No completed answer.", {evidence: item.evidence});
        });
        showNotice("Recent questions · Shared demo history");
      }
    } catch (error) {
      if (requestSession === session) showNotice(error.message, true);
    } finally {
      if (requestSession === session) { busy = false; updateControls(); }
    }
  });
  $("clear-button").addEventListener("click", () => {
    if (busy) return;
    contextId = null;
    showEmptyState();
    showNotice("");
  });
  window.addEventListener("pagehide", disconnect);
  window.addEventListener("pageshow", updateControls);
  updateControls();
})();
