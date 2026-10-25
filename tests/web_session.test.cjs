"use strict";

// Execute the shipped browser script offline. This fixture models only the DOM
// operations app.js uses; fetch and its JSON body can be completed independently.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const sourcePath = path.join(__dirname, "../src/askbrieves/web/app.js");
const source = fs.readFileSync(sourcePath, "utf8");
const OWNER = "synthetic-owner";
const REVIEWER = "synthetic-reviewer";
const OWNER_QUESTION = "SYNTHETIC OWNER QUESTION";
const OWNER_ANSWER = "SYNTHETIC OWNER ANSWER";
const REVIEWER_QUESTION = "SYNTHETIC REVIEWER QUESTION";
const REVIEWER_ANSWER = "SYNTHETIC REVIEWER ANSWER";
const EXAMPLE = "What's the 10-year Treasury yield?";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function fixture() {
  let focused = null;
  class Element {
    constructor(tag = "div", id = "") {
      this.tagName = tag.toUpperCase();
      this.id = id;
      this.children = [];
      this.parentElement = null;
      this.listeners = new Map();
      this.value = "";
      this.rows = 1;
      this.disabled = false;
      this.hidden = false;
      this.open = false;
      this.className = "";
      this.dataset = {};
      this.attributes = {};
      this._text = "";
      this.classList = {
        contains: (name) => this.className.split(/\s+/).includes(name),
        add: (...names) => names.forEach((name) => this.classList.toggle(name, true)),
        remove: (...names) => names.forEach((name) => this.classList.toggle(name, false)),
        toggle: (name, enabled) => {
          const names = new Set(this.className.split(/\s+/).filter(Boolean));
          const present = enabled === undefined ? !names.has(name) : Boolean(enabled);
          if (present) names.add(name); else names.delete(name);
          this.className = [...names].join(" ");
          return present;
        },
      };
    }
    set textContent(value) { this.replaceChildren(); this._text = String(value); }
    get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
    get scrollHeight() { return this.children.length; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    append(...children) {
      for (const child of children) {
        child.remove();
        child.parentElement = this;
        this.children.push(child);
      }
    }
    replaceChildren(...children) {
      for (const child of this.children) child.parentElement = null;
      this.children = [];
      this._text = "";
      this.append(...children);
    }
    remove() {
      if (this.parentElement) {
        this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
      }
      this.parentElement = null;
    }
    addEventListener(type, callback) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(callback);
    }
    focus() { focused = this; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    querySelectorAll(selector) {
      assert.ok(selector.startsWith("."), `Unsupported fixture selector: ${selector}`);
      return this.children.flatMap((child) => [
        ...(child.classList.contains(selector.slice(1)) ? [child] : []),
        ...child.querySelectorAll(selector),
      ]);
    }
    cloneNode(deep) {
      const copy = new Element(this.tagName, this.id);
      copy.className = this.className;
      copy.dataset = {...this.dataset};
      copy.attributes = {...this.attributes};
      copy._text = this._text;
      if (deep) copy.append(...this.children.map((child) => child.cloneNode(true)));
      return copy;
    }
  }

  const root = new Element("body");
  for (const id of ["conversation", "question", "access-dialog", "send-button", "history-button",
    "clear-button", "access-button", "disconnect-button", "notice", "access-token", "close-access",
    "access-form", "question-form"]) root.append(new Element("div", id));
  const find = (id, element = root) => element.id === id ? element
    : element.children.map((child) => find(id, child)).find(Boolean) || null;
  const welcome = new Element("section", "empty-state");
  welcome.className = "empty-state";
  const heading = new Element("h1");
  heading.textContent = "Ask about rates.";
  const suggestion = new Element("button");
  suggestion.className = "suggestion";
  suggestion.dataset.question = EXAMPLE;
  suggestion.textContent = "10-year Treasury yield";
  welcome.append(heading, suggestion);
  find("conversation").append(welcome);

  const requests = [];
  const windowListeners = new Map();
  const timers = new Map();
  let timerId = 0;
  const fetch = (url, options) => {
    const response = deferred();
    const request = {
      url, options,
      respond(data, status = 200) {
        response.resolve({status, ok: status >= 200 && status < 300, json: async () => data});
      },
      reject(error) { response.reject(error); },
      async deferJson() {
        const body = deferred();
        const started = deferred();
        response.resolve({status: 200, ok: true, json: () => {
          started.resolve();
          return body.promise;
        }});
        await started.promise;
        return body;
      },
    };
    // Deliberately allow a response after abort: cancellation alone cannot prove
    // session isolation when a response or its JSON parsing has already started.
    requests.push(request);
    return response.promise;
  };
  const emitCallbacks = (listeners, type, fields = {}) => Promise.all(
    (listeners.get(type) || []).map((callback) => callback({preventDefault() {}, ...fields})),
  );
  const emit = (id, type, fields) => emitCallbacks(find(id).listeners, type, fields);
  find("question-form").requestSubmit = () => emit("question-form", "submit");
  vm.runInNewContext(source, {
    document: {
      getElementById: find,
      createElement: (tag) => new Element(tag),
      querySelectorAll: (selector) => root.querySelectorAll(selector),
    },
    window: {addEventListener: (type, callback) => {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(callback);
    }},
    fetch, URL, AbortController,
    setTimeout: (callback) => { const id = ++timerId; timers.set(id, callback); return id; },
    clearTimeout: (id) => timers.delete(id),
  }, {filename: sourcePath});

  return {
    get: find, requests, emit,
    window: (type) => emitCallbacks(windowListeners, type),
    async type(value) { find("question").value = value; await emit("question", "input"); },
    async connect(value) {
      find("access-token").value = value;
      await emit("access-form", "submit");
    },
    submit(value) {
      find("question").value = value;
      return emit("question-form", "submit");
    },
    messages() {
      return find("conversation").children.filter((child) => child.tagName === "ARTICLE")
        .map((article) => article.children[1].textContent);
    },
    snapshot() {
      return {
        transcript: find("conversation").textContent,
        question: find("question").value,
        rows: find("question").rows,
        notice: find("notice").textContent,
        noticeError: find("notice").classList.contains("error"),
        accessInput: find("access-token").value,
        access: find("access-button").textContent,
        dialogOpen: find("access-dialog").open,
        disconnectHidden: find("disconnect-button").hidden,
        sendDisabled: find("send-button").disabled,
        historyDisabled: find("history-button").disabled,
        clearDisabled: find("clear-button").disabled,
        ariaBusy: find("question").getAttribute("aria-busy"),
        focused: focused && focused.id,
      };
    },
  };
}

function assertEmpty(ui, connected = false) {
  assert.deepEqual(ui.messages(), [], "Previous messages must be removed");
  assert.ok(ui.get("empty-state"), "The welcome state must replace the old transcript");
  assert.equal(ui.get("question").value, "", "The old draft must be removed");
  assert.equal(ui.get("question").rows, 1);
  assert.equal(ui.get("access-token").value, "");
  assert.equal(ui.get("send-button").disabled, true);
  assert.equal(ui.get("history-button").disabled, false);
  assert.equal(ui.get("clear-button").disabled, false);
  assert.equal(ui.get("question").getAttribute("aria-busy"), "false");
  assert.equal(ui.get("access-button").textContent, connected ? "Connected" : "Access");
  assert.equal(ui.get("disconnect-button").hidden, !connected);
  assert.equal(ui.get("access-dialog").open, false);
  assert.doesNotMatch(ui.get("notice").textContent, /SYNTHETIC OWNER|Loading history|Question restored|Recent questions|Shared demo/);
}

async function seedOwnerHistory(ui) {
  await ui.connect(OWNER);
  const pending = ui.emit("history-button", "click");
  const request = ui.requests.at(-1);
  assert.equal(request.url, "/history");
  request.respond({items: [{question: OWNER_QUESTION, answer: OWNER_ANSWER}]});
  await pending;
  assert.deepEqual(ui.messages(), [OWNER_QUESTION, OWNER_ANSWER]);
}

function abortError() {
  const error = new Error("Synthetic request cancellation");
  error.name = "AbortError";
  return error;
}

test("first connection preserves an unauthenticated draft without fetching", async () => {
  const ui = fixture();
  await ui.type(REVIEWER_QUESTION);
  await ui.emit("question-form", "submit");
  assert.equal(ui.get("access-dialog").open, true);
  await ui.connect(REVIEWER);
  assert.equal(ui.get("question").value, REVIEWER_QUESTION);
  assert.equal(ui.get("send-button").disabled, false);
  assert.equal(ui.get("access-dialog").open, false);
  assert.equal(ui.get("access-token").value, "");
  assert.equal(ui.requests.length, 0, "Connecting must not require an extra token-validation request");
});

test("same-session question success renders its answer and evidence", async () => {
  const ui = fixture();
  await ui.connect(REVIEWER);
  const pending = ui.submit(REVIEWER_QUESTION);
  const request = ui.requests[0];
  assert.equal(request.url, "/questions");
  assert.equal(request.options.headers.Authorization, `Bearer ${REVIEWER}`);
  assert.deepEqual(JSON.parse(request.options.body), {question: REVIEWER_QUESTION});
  assert.equal(ui.get("question").getAttribute("aria-busy"), "true");
  request.respond({answer: REVIEWER_ANSWER, evidence: {
    as_of: "2026-10-23", source_url: "https://home.treasury.gov/resource-center",
  }});
  await pending;
  assert.deepEqual(ui.messages(), [REVIEWER_QUESTION, REVIEWER_ANSWER]);
  assert.match(ui.get("conversation").textContent, /As of 2026-10-23/);
  assert.equal(ui.get("question").value, "");
  assert.equal(ui.get("question").getAttribute("aria-busy"), "false");
  assert.equal(ui.get("history-button").disabled, false);
});

test("a same-session error restores the question and a successful retry works", async () => {
  const ui = fixture();
  await ui.connect(REVIEWER);
  const failed = ui.submit(REVIEWER_QUESTION);
  ui.requests[0].respond({}, 503);
  await failed;
  assert.match(ui.messages()[1], /unavailable/i);
  assert.equal(ui.get("question").value, REVIEWER_QUESTION);
  assert.equal(ui.get("send-button").disabled, false);
  assert.equal(ui.get("notice").classList.contains("error"), true);
  assert.match(ui.get("notice").textContent, /retry/i);
  const retried = ui.emit("question-form", "submit");
  ui.requests[1].respond({answer: REVIEWER_ANSWER});
  await retried;
  assert.equal(ui.messages().at(-1), REVIEWER_ANSWER);
  assert.equal(ui.get("notice").classList.contains("error"), false);
  assert.equal(ui.get("question").value, "");
});

test("quota and traffic throttles never promise a daily reset", async () => {
  const ui = fixture();
  await ui.connect(REVIEWER);
  const pending = ui.submit(REVIEWER_QUESTION);
  ui.requests[0].respond({code: "review_limit_exceeded"}, 429);
  await pending;
  assert.match(ui.messages()[1], /does not reset daily/);
  assert.doesNotMatch(ui.messages()[1], /midnight|resets at/i);
  assert.equal(ui.get("question").value, REVIEWER_QUESTION);
});

test("a closed review window explains expiry without disconnecting history access", async () => {
  const ui = fixture();
  await ui.connect(OWNER);
  const pending = ui.submit(OWNER_QUESTION);
  ui.requests[0].respond({code: "review_window_closed"}, 403);
  await pending;
  assert.match(ui.messages()[1], /seven-day review window is not active/i);
  assert.equal(ui.get("access-button").textContent, "Connected");
  assert.equal(ui.get("question").getAttribute("aria-busy"), "false");
});

test("same-session history replaces the transcript and preserves chronological order", async () => {
  const ui = fixture();
  await seedOwnerHistory(ui);
  const pending = ui.emit("history-button", "click");
  ui.requests[1].respond({items: [
    {question: "Synthetic newest question", answer: "Synthetic newest answer"},
    {question: "Synthetic oldest question", answer: "Synthetic oldest answer"},
  ]});
  await pending;
  assert.deepEqual(ui.messages(), ["Synthetic oldest question", "Synthetic oldest answer",
    "Synthetic newest question", "Synthetic newest answer"]);
  assert.equal(ui.get("history-button").disabled, false);
});

test("empty history replaces an existing transcript with working welcome examples", async () => {
  const ui = fixture();
  await seedOwnerHistory(ui);
  const pending = ui.emit("history-button", "click");
  ui.requests[1].respond({items: []});
  await pending;
  assert.deepEqual(ui.messages(), []);
  assert.ok(ui.get("empty-state"));
  assert.match(ui.get("notice").textContent, /No history/i);
  const suggestion = ui.get("conversation").querySelectorAll(".suggestion")[0];
  await Promise.all((suggestion.listeners.get("click") || []).map((callback) => callback({})));
  assert.equal(ui.get("question").value, EXAMPLE);
  assert.equal(ui.get("send-button").disabled, false);
});

test("clear chat restores working examples and keeps the current connection", async () => {
  const ui = fixture();
  await seedOwnerHistory(ui);
  await ui.emit("clear-button", "click");
  assert.deepEqual(ui.messages(), []);
  assert.ok(ui.get("empty-state"));
  assert.equal(ui.get("access-button").textContent, "Connected");
  const suggestion = ui.get("conversation").querySelectorAll(".suggestion")[0];
  await Promise.all((suggestion.listeners.get("click") || []).map((callback) => callback({})));
  assert.equal(ui.get("question").value, EXAMPLE);
});

test("closing or cancelling the access dialog clears its credential input", async () => {
  const ui = fixture();
  for (const [id, event] of [["close-access", "click"], ["access-dialog", "cancel"]]) {
    await ui.emit("access-button", "click");
    ui.get("access-token").value = OWNER;
    await ui.emit(id, event);
    assert.equal(ui.get("access-token").value, "");
  }
  assert.equal(ui.requests.length, 0);
});

test("replacing credentials clears prior transcript, draft, and session notice", async () => {
  const ui = fixture();
  await seedOwnerHistory(ui);
  const failed = ui.submit(OWNER_QUESTION);
  ui.requests[1].respond({}, 503);
  await failed;
  await ui.type("SYNTHETIC OWNER DRAFT\nprivate draft line");
  await ui.emit("access-button", "click");
  await ui.connect(REVIEWER);
  assertEmpty(ui, true);
  assert.equal(ui.get("notice").classList.contains("error"), false);
  const pending = ui.emit("history-button", "click");
  assert.equal(ui.requests[2].options.headers.Authorization, `Bearer ${REVIEWER}`);
  ui.requests[2].respond({items: []});
  await pending;
  assertEmpty(ui, true);
});

test("disconnect clears completed messages, draft, and credential input", async () => {
  const ui = fixture();
  await seedOwnerHistory(ui);
  await ui.type("SYNTHETIC OWNER DRAFT\nprivate draft line");
  await ui.emit("access-button", "click");
  ui.get("access-token").value = OWNER;
  await ui.emit("disconnect-button", "click");
  assertEmpty(ui);
  assert.equal(ui.get("notice").classList.contains("error"), false);
});

test("pagehide clears private state and pageshow cannot restore it", async () => {
  const ui = fixture();
  await seedOwnerHistory(ui);
  await ui.type("SYNTHETIC OWNER DRAFT\nprivate draft line");
  await ui.emit("access-button", "click");
  ui.get("access-token").value = OWNER;
  await ui.window("pagehide");
  assertEmpty(ui);
  await ui.window("pageshow");
  assertEmpty(ui);
});

for (const kind of ["question", "history"]) {
  test(`current-session ${kind} 401 clears private state and explains reconnection`, async () => {
    const ui = fixture();
    await seedOwnerHistory(ui);
    const pending = kind === "question" ? ui.submit(OWNER_QUESTION) : ui.emit("history-button", "click");
    ui.get("access-token").value = OWNER;
    ui.requests[1].respond({}, 401);
    await pending;
    assertEmpty(ui);
    assert.match(ui.get("notice").textContent, /reconnect/i);
    assert.equal(ui.get("notice").classList.contains("error"), true);
  });
}

for (const kind of ["question", "history"]) {
  for (const completion of ["success", "error", "abort", "401", "JSON success", "JSON error"]) {
    test(`late old-session ${kind} ${completion} cannot affect a newer pending question`, async () => {
      const ui = fixture();
      await ui.connect(OWNER);
      const ownerPending = kind === "question" ? ui.submit(OWNER_QUESTION) : ui.emit("history-button", "click");
      const oldRequest = ui.requests[0];
      const body = completion.startsWith("JSON") ? await oldRequest.deferJson() : null;
      await ui.connect(REVIEWER);
      assertEmpty(ui, true);
      assert.equal(oldRequest.options.signal.aborted, true, "Replacing a session must cancel its request");
      const reviewerPending = ui.submit(REVIEWER_QUESTION);
      const currentRequest = ui.requests[1];
      assert.ok(currentRequest, "Credential replacement must work while the prior request is pending");
      assert.equal(currentRequest.options.headers.Authorization, `Bearer ${REVIEWER}`);
      const before = ui.snapshot();
      const payload = kind === "question" ? {answer: OWNER_ANSWER}
        : {items: [{question: OWNER_QUESTION, answer: OWNER_ANSWER}]};
      if (completion === "success") oldRequest.respond(payload);
      else if (completion === "error") oldRequest.reject(new Error("SYNTHETIC OWNER ERROR"));
      else if (completion === "abort") oldRequest.reject(abortError());
      else if (completion === "401") oldRequest.respond({}, 401);
      else if (completion === "JSON success") body.resolve(payload);
      else body.reject(new Error("SYNTHETIC OWNER JSON ERROR"));
      await ownerPending;
      assert.deepEqual(ui.snapshot(), before, "Stale render, retry, auth, and finally callbacks must have no visible effect");
      assert.equal(currentRequest.options.signal.aborted, false, "An old response must not cancel the new request");
      currentRequest.respond({answer: REVIEWER_ANSWER});
      await reviewerPending;
      assert.deepEqual(ui.messages(), [REVIEWER_QUESTION, REVIEWER_ANSWER]);
      assert.equal(ui.get("question").getAttribute("aria-busy"), "false");
    });
  }
}

for (const kind of ["question", "history"]) {
  for (const boundary of ["disconnect", "pagehide"]) {
    test(`${boundary} makes an aborted pending ${kind} callback inert`, async () => {
      const ui = fixture();
      await ui.connect(OWNER);
      const pending = kind === "question" ? ui.submit(OWNER_QUESTION) : ui.emit("history-button", "click");
      const request = ui.requests[0];
      if (boundary === "disconnect") await ui.emit("disconnect-button", "click");
      else await ui.window("pagehide");
      assertEmpty(ui);
      assert.equal(request.options.signal.aborted, true);
      const before = ui.snapshot();
      request.reject(abortError());
      await pending;
      assert.deepEqual(ui.snapshot(), before, "Cancellation must not restore the old draft or error notice");
    });
  }
}

test("an old request's finally cannot release the newer request's cancellation handle", async () => {
  const ui = fixture();
  await ui.connect(OWNER);
  const oldPending = ui.submit(OWNER_QUESTION);
  await ui.connect(REVIEWER);
  const newPending = ui.submit(REVIEWER_QUESTION);
  const current = ui.requests[1];
  assert.ok(current, "The new session must be able to submit immediately");
  ui.requests[0].respond({answer: OWNER_ANSWER});
  await oldPending;
  await ui.emit("disconnect-button", "click");
  assert.equal(current.options.signal.aborted, true, "Disconnect must still cancel the current session's request");
  const before = ui.snapshot();
  current.respond({answer: REVIEWER_ANSWER});
  await newPending;
  assert.deepEqual(ui.snapshot(), before);
  assertEmpty(ui);
});
