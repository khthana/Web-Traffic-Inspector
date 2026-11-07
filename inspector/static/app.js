// Web Traffic Inspector — ฝั่งหน้าเว็บ (vanilla JS ไม่มี build step)
// แบ่งเป็น class เล็กๆ ล้อกับฝั่ง Python: InspectorSocket ≈ Broadcaster, TimelineView ≈ EventStore + Correlator
"use strict";

/** เชื่อม WebSocket /ws และเชื่อมใหม่เองแบบ backoff เมื่อหลุด
 *  สอนแนวคิด: callback — ส่งต่อข้อความให้ผู้อื่นจัดการ ไม่ต้องรู้ว่าใครใช้ */
class InspectorSocket {
  constructor(onMessage, onConnectionChange) {
    this.onMessage = onMessage;
    this.onConnectionChange = onConnectionChange;
    this.retryDelay = 1000;
  }

  connect() {
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
    const ws = new WebSocket(url);
    ws.addEventListener("open", () => {
      this.retryDelay = 1000;
      this.onConnectionChange(true);
    });
    ws.addEventListener("message", (event) => this.onMessage(JSON.parse(event.data)));
    ws.addEventListener("close", () => {
      this.onConnectionChange(false);
      setTimeout(() => this.connect(), this.retryDelay);
      this.retryDelay = Math.min(this.retryDelay * 2, 5000);
    });
  }
}

/** Timeline: การ์ด Interaction ใหม่สุดอยู่บน แต่ละการ์ดมีแถว Exchange อยู่ข้างใน คลิกแถวเพื่อเลือกดูใน Detail
 *  สอนแนวคิด: state ใน object — จำว่าการ์ดและแถวไหนวาดไว้แล้ว (Map) เพื่ออัปเดตที่เดิม ไม่วาดใหม่ทั้งหน้า
 *  และ callback — บอก onSelect ว่าเลือก Exchange ไหน โดยไม่ต้องรู้ว่าใครเอาไปแสดง */
class TimelineView {
  constructor(listElement, emptyElement, onSelect) {
    this.list = listElement;
    this.empty = emptyElement;
    this.onSelect = onSelect;
    this.cards = new Map(); // interaction id → <li class="card">
    this.rows = new Map(); // exchange id → <li class="exchange">
    this.exchanges = new Map(); // exchange id → ข้อมูลล่าสุดของ Exchange
    this.selectedId = null;
    listElement.addEventListener("click", (event) => this.selectRow(event.target));
    listElement.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.selectRow(event.target);
      }
    });
  }

  reset(interactions, exchanges) {
    this.list.replaceChildren();
    this.cards.clear();
    this.rows.clear();
    this.exchanges.clear();
    interactions.forEach((interaction) => this.upsertInteraction(interaction, false));
    exchanges.forEach((exchange) => this.upsertExchange(exchange));
    if (!this.exchanges.has(this.selectedId)) this.select(null); // Exchange ที่เลือกไว้ถูกตัดออกจาก store แล้ว
    this.updateEmpty();
  }

  selectRow(target) {
    const row = target.closest(".exchange");
    if (row) this.select(row.dataset.id);
  }

  select(id) {
    this.rows.get(this.selectedId)?.setAttribute("aria-selected", "false");
    this.selectedId = id;
    this.rows.get(id)?.setAttribute("aria-selected", "true");
    this.onSelect(this.exchanges.get(id) ?? null);
  }

  /** การ์ดใหม่ขึ้นบนสุดพร้อมไฮไลต์ การ์ดเดิมเปลี่ยนแค่หัวการ์ด ไม่ย้ายตำแหน่ง */
  upsertInteraction(interaction, highlight = true) {
    const existing = this.cards.get(interaction.id);
    if (existing) {
      existing.querySelector(".card-head").replaceWith(cardHead(interaction));
      existing.dataset.total = String(interaction.exchange_ids.length);
      refreshCard(existing);
      return;
    }
    const card = renderCard(interaction);
    if (highlight) card.classList.add("is-new");
    this.list.prepend(card);
    this.cards.set(interaction.id, card);
    this.updateEmpty();
  }

  upsertExchange(exchange) {
    const card = this.cards.get(exchange.interaction_id);
    if (!card) return; // การ์ดถูกตัดออกจาก store ไปแล้ว
    this.exchanges.set(exchange.id, exchange);
    const row = renderExchangeRow(exchange, exchange.id === this.selectedId);
    const existing = this.rows.get(exchange.id);
    if (existing) {
      existing.replaceWith(row);
    } else {
      card.querySelector(".exchange-list").append(row);
    }
    this.rows.set(exchange.id, row);
    refreshCard(card);
    if (exchange.id === this.selectedId) this.onSelect(exchange); // ได้คำตอบแล้ว: Detail ต้องเห็นข้อมูลใหม่
  }

  updateEmpty() {
    this.empty.hidden = this.cards.size > 0;
  }
}

const KIND_ICONS = {
  // เมาส์ = คลิก, เอกสาร = โหลดหน้า, นาฬิกา = เกิดเองเบื้องหลัง
  click: '<rect x="4" y="1.5" width="8" height="13" rx="4" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 3.5v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
  page_load: '<path d="M4 1.5h5l3 3v10H4Zm5 0v3h3M6 8h4M6 10.5h4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  background: '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
};

function renderCard(interaction) {
  const card = document.createElement("li");
  card.className = `card kind-${interaction.kind}`;
  card.dataset.id = interaction.id;
  card.dataset.total = String(interaction.exchange_ids.length);
  const rows = document.createElement("ol");
  rows.className = "exchange-list";
  rows.setAttribute("role", "listbox");
  rows.setAttribute("aria-label", "Exchange ของ Interaction นี้");
  card.append(cardHead(interaction), rows);
  if (interaction.kind === "click") {
    card.append(
      textSpan("no-calls", "ไม่มี API call — ปุ่มนี้ทำงานในเบราว์เซอร์อย่างเดียว"),
      textSpan("hidden-note", ""),
    );
  }
  refreshCard(card);
  return card;
}

/** การ์ดที่ไม่มี Exchange ที่มองเห็นได้ class "no-visible": การ์ดคลิกบอกว่าไม่มี API call
 *  ส่วนการ์ดโหลดหน้า/เบื้องหลังถูกซ่อนไปเลย (ยกเว้นตอนเปิดปุ่ม "ซ่อน N รายการ") */
function refreshCard(card) {
  const rows = [...card.querySelectorAll(".exchange")];
  const visible = rows.filter((row) => !row.classList.contains("is-hidden")).length;
  const tracking = rows.filter((row) => row.dataset.tracking === "true").length;
  // Exchange ที่อยู่ใน exchange_ids แต่ไม่มีแถว คือถูกตัดออกจาก store ไปแล้ว ไม่รู้ว่าเคยมองเห็นไหม:
  // การ์ดคลิกนับเป็นมองเห็น (จะได้ไม่บอกผิดว่า "ไม่มี API call") การ์ดอื่นไม่มีอะไรให้ดูแล้วจึงซ่อนได้
  const dropped = card.classList.contains("kind-click") ? Math.max(Number(card.dataset.total) - rows.length, 0) : 0;
  card.classList.toggle("no-visible", visible + dropped === 0);
  const note = card.querySelector(".hidden-note");
  if (note) note.textContent = tracking > 0 ? `(มี tracking ${tracking} รายการที่ซ่อนอยู่)` : "";
}

function cardHead(interaction) {
  const head = document.createElement("div");
  head.className = "card-head";
  const icon = document.createElement("span");
  icon.className = "card-icon";
  icon.innerHTML = `<svg viewBox="0 0 16 16" width="1.1em" height="1.1em" aria-hidden="true" focusable="false">${KIND_ICONS[interaction.kind]}</svg>`;
  const page = safeUrl(interaction.page_url);
  head.append(
    icon,
    textSpan("card-title", cardTitle(interaction)),
    textSpan("card-meta", `${clockTime(interaction.started_at)}${page ? ` · ${page.host}` : ""}`),
  );
  return head;
}

function cardTitle(interaction) {
  if (interaction.kind === "background") return "เกิดเองโดยไม่มีคลิก";
  if (interaction.kind === "page_load") return `เปิดหน้า ${pathOf(interaction.page_url)}`;
  const element = interaction.click.element;
  const label = shorten(element.text || element.aria_label || element.selector, 40);
  const title = `คลิก <${element.tag}> "${label}"`;
  return interaction.navigated_to ? `${title} → เปลี่ยนหน้าไป ${pathOf(interaction.navigated_to)}` : title;
}

function renderExchangeRow(exchange, selected) {
  const li = document.createElement("li");
  li.className = exchange.hidden ? "exchange is-hidden" : "exchange";
  li.dataset.id = exchange.id;
  li.tabIndex = 0;
  li.setAttribute("role", "option");
  li.setAttribute("aria-selected", String(selected));
  li.dataset.tracking = String(Boolean(exchange.hidden_reason?.startsWith("tracking:")));
  li.append(
    methodBadge(exchange.request.method),
    // LRM ครอบไว้ เพื่อไม่ให้ direction: rtl (ที่ใช้ตัด path จากซ้าย) ย้าย "/" ไปไว้ท้าย
    textSpan("path", `\u200e${exchange.request.path}\u200e`, exchange.request.url),
    redactionFlags(exchange),
    statusBadge(exchange),
    textSpan("ms", durationText(exchange)),
    textSpan("summary", exchange.summary),
  );
  if (exchange.hidden_reason) li.append(textSpan("hidden-reason", exchange.hidden_reason));
  return li;
}

function safeUrl(url) {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

function pathOf(url) {
  const parsed = safeUrl(url);
  return parsed ? parsed.pathname + parsed.search : url;
}

function clockTime(epochMs) {
  return new Date(epochMs).toLocaleTimeString("th-TH", { hour12: false });
}

function shorten(text, max) {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/** จุดสถานะ Chrome ที่ top bar
 *  สอนแนวคิด: single responsibility — class นี้รู้แค่เรื่องแสดงสถานะ */
class StatusView {
  constructor(element) {
    this.element = element;
  }

  show(status) {
    const connected = status.chrome === "connected";
    this.element.dataset.state = status.chrome;
    this.element.querySelector(".label").textContent = connected
      ? `เชื่อมต่อแล้ว · ${status.tabs.length} แท็บ`
      : "ไม่พบ Chrome";
  }
}

/** บอกวิธีเปิด Chrome ทุกครั้งที่ไม่ได้เชื่อม และแถบเหลืองเมื่อ Chrome หลุดกลางคาบ
 *  สอนแนวคิด: state ใน object — จำว่า "เคยเชื่อมสำเร็จแล้วหรือยัง" เพื่อรู้ว่าควรเตือนว่าหลุดไหม */
class ChromeHelpView {
  constructor(setupElement, bannerElement) {
    this.setup = setupElement;
    this.banner = bannerElement;
    this.wasConnected = false;
    this.setup.querySelector("#copy-command").addEventListener("click", () => this.copyCommand());
  }

  show(status) {
    const connected = status.chrome === "connected";
    if (connected) this.wasConnected = true;
    this.setup.querySelector("#chrome-command").textContent = status.chrome_launch_command;
    this.setup.hidden = connected || !status.chrome_launch_command; // โหมด --demo ไม่ต้องใช้ Chrome
    this.banner.hidden = connected || !this.wasConnected;
  }

  async copyCommand() {
    const button = this.setup.querySelector("#copy-command");
    try {
      await navigator.clipboard.writeText(this.setup.querySelector("#chrome-command").textContent);
      button.textContent = "คัดลอกแล้ว ✓";
    } catch {
      button.textContent = "คัดลอกไม่ได้ — เลือกข้อความเองนะ";
    }
    setTimeout(() => { button.textContent = "คัดลอกคำสั่ง"; }, 2000);
  }
}

const LOCK_ICON = `<svg viewBox="0 0 16 16" width="1em" height="1em" aria-hidden="true" focusable="false">
  <path fill="currentColor" d="M5 7V5a3 3 0 0 1 6 0v2h1a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h1Zm1.5 0h3V5a1.5 1.5 0 0 0-3 0v2Z"/>
</svg>`;

/** ป้ายบอกเรื่อง Redaction: กุญแจ = มีค่าลับถูกซ่อน, ป้ายเหลือง = มี body ที่ไม่ได้ตรวจ */
function redactionFlags(exchange) {
  const span = document.createElement("span");
  span.className = "flags";
  if (exchange.has_redactions) {
    const lock = document.createElement("span");
    lock.className = "flag-lock";
    lock.innerHTML = LOCK_ICON;
    lock.title = "มีข้อมูลลับถูกซ่อนไว้";
    lock.setAttribute("role", "img");
    lock.setAttribute("aria-label", "มีข้อมูลลับถูกซ่อนไว้");
    span.append(lock);
  }
  const parts = [exchange.request, exchange.response].filter(Boolean);
  if (parts.some((part) => part.body && part.body_unscanned)) {
    span.append(textSpan("flag-unscanned", "ไม่ได้ตรวจหาข้อมูลลับ", "body นี้ไม่ใช่ JSON หรือ form แบบ urlencoded (เช่น text, multipart, binary) จึงไม่ได้ตรวจหาข้อมูลลับ — ระวังก่อนแสดงหน้าห้อง"));
  }
  return span;
}

function durationText(exchange) {
  return exchange.duration_ms == null ? "" : `${Math.round(exchange.duration_ms)} ms`;
}

/** method ที่ไม่มีสีของตัวเอง (HEAD, OPTIONS) ใช้สี --other-method จาก class "method" */
function methodBadge(method) {
  return badge(method, `method method-${method}`);
}

function badge(text, className) {
  const span = document.createElement("span");
  span.className = `badge ${className}`;
  span.textContent = text;
  return span;
}

function statusBadge(exchange) {
  if (exchange.state === "pending") return badge("รอคำตอบ…", "status-pending");
  if (exchange.state === "failed") return badge("failed", "status-failed");
  const status = exchange.response.status;
  return badge(String(status), `status-${Math.floor(status / 100)}xx`);
}

function textSpan(className, text, title) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  if (title) span.title = title;
  return span;
}

/** ปุ่ม "ซ่อน N รายการ": toggle แสดง Hidden exchange แบบจางพร้อม Hidden reason
 *  สอนแนวคิด: single responsibility — รู้แค่เรื่องปุ่มนี้ ส่วนการแสดงผลจริงให้ CSS จัดการจาก class บน body */
class HiddenToggle {
  constructor(button) {
    this.button = button;
    button.addEventListener("click", () => {
      const showing = document.body.classList.toggle("show-hidden");
      button.setAttribute("aria-pressed", String(showing));
    });
  }

  show(status) {
    this.button.textContent = `ซ่อน ${status.hidden_count} รายการ`;
  }
}

const LIST_FIELDS = ["focus_hosts", "focus_path_prefixes", "block_hosts", "block_path_prefixes", "redact_keys"];

/** dropdown เลือก Preset และฟอร์มแก้กฎของ "กำหนดเอง…" คุยกับ GET/PUT /api/filters
 *  สอนแนวคิด: encapsulation — เก็บสถานะล่าสุดจาก server ไว้ใน this.view ที่เดียว */
class FilterControls {
  constructor(select, form) {
    this.select = select;
    this.form = form;
    this.view = null;
    select.addEventListener("change", () => this.choose(select.value));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.saveCustom();
    });
    form.querySelector("#custom-close").addEventListener("click", () => { form.hidden = true; });
  }

  async load() {
    this.render(await (await fetch("/api/filters")).json());
  }

  /** มีคนเปลี่ยนกฎ (อาจเป็นหน้าจออื่น): status บอกเลขรุ่นใหม่ จึงโหลดกฎมาใหม่ ฟอร์มจะได้ไม่ทับกฎของคนอื่น */
  show(status) {
    if (this.version !== undefined && status.filters_version !== this.version) this.load();
    this.version = status.filters_version;
  }

  async choose(name) {
    if (await this.put({ selected: name })) this.form.hidden = name !== "custom";
  }

  async saveCustom() {
    const rules = { ...this.view.rules };
    for (const field of LIST_FIELDS) {
      rules[field] = this.form.elements[field].value.split(",").map((value) => value.trim()).filter(Boolean);
    }
    await this.put({ selected: "custom", rules });
  }

  async put(body) {
    const error = this.form.querySelector("#custom-error");
    const response = await fetch("/api/filters", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    error.hidden = response.ok;
    if (!response.ok) {
      error.textContent = typeof data.detail === "string" ? data.detail : "กฎไม่ถูกต้อง ลองตรวจอีกครั้ง";
      this.form.hidden = false;
      this.select.value = this.view.selected;
      return false;
    }
    this.render(data);
    return true;
  }

  render(view) {
    this.view = view;
    this.select.replaceChildren(...view.choices.map((choice) => new Option(choice.label, choice.name)));
    this.select.value = view.selected;
    for (const field of LIST_FIELDS) this.form.elements[field].value = view.rules[field].join(", ");
    this.form.querySelector("#base-blocklist").textContent = view.base_blocklist.join(", ");
  }
}

const REDACTED = "••••"; // ค่าที่ Redactor ใส่แทนข้อมูลลับ (ฝั่ง Python: inspector/redactor.py)
const HTTP_VERSION = "HTTP/1.1"; // Chrome ไม่บอกเวอร์ชันจริง ใช้รูปแบบที่สอนง่ายที่สุด
const JSON_OPEN_DEPTH = 2;
const JSON_ARRAY_PREVIEW = 10;

/** สร้าง element พร้อม class และลูก (ข้อความใส่เป็น text node เสมอ จึงไม่มี HTML injection) */
function el(tag, className, ...children) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.append(...children.filter((child) => child != null));
  return element;
}

function redactedChip() {
  return el("span", "json-redacted", "ซ่อนไว้");
}

/** JSON tree: ย่อ/ขยายได้ เปิดไว้ JSON_OPEN_DEPTH ชั้นแรก สีตามชนิดข้อมูล และสลับเป็นข้อความดิบได้
 *  สอนแนวคิด: recursion — object/array ซ้อนกันกี่ชั้นก็วาดได้ด้วยเมธอดเดียวที่เรียกตัวเอง */
class JsonViewer {
  constructor(value) {
    this.tree = el("ul", "json-tree", this.node(null, value, 0));
    this.raw = el("pre", "raw-body", JSON.stringify(value, null, 2));
    this.raw.hidden = true;
    const toggle = el("button", "raw-toggle", "ดูข้อความดิบ");
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      this.raw.hidden = !this.raw.hidden;
      this.tree.hidden = !this.raw.hidden;
      toggle.textContent = this.raw.hidden ? "ดูข้อความดิบ" : "ดูแบบ tree";
    });
    this.element = el("div", "json-viewer", toggle, this.tree, this.raw);
  }

  node(key, value, depth) {
    const label = key == null ? null : el("span", "json-key", `${key}: `);
    if (value === null || typeof value !== "object" || Object.keys(value).length === 0) {
      return el("li", "json-leaf", label, this.leaf(value));
    }
    const isArray = Array.isArray(value);
    const entries = Object.entries(value);
    const shown = isArray ? entries.slice(0, JSON_ARRAY_PREVIEW) : entries;
    const children = el("ul", "json-children", ...shown.map(([k, v]) => this.node(k, v, depth + 1)));
    if (shown.length < entries.length) {
      children.append(el("li", "json-more", `…อีก ${entries.length - shown.length} รายการ`));
    }
    const count = isArray ? `[${entries.length} รายการ]` : `{${entries.length} คีย์}`;
    const details = el("details", "json-branch", el("summary", null, label, el("span", "json-count", count)), children);
    details.open = depth < JSON_OPEN_DEPTH;
    return el("li", null, details);
  }

  leaf(value) {
    if (value === REDACTED) return redactedChip();
    if (value === null) return el("span", "json-null", "null");
    if (typeof value === "object") return el("span", "json-empty", Array.isArray(value) ? "[]" : "{}");
    if (typeof value === "string") return el("span", "json-string", JSON.stringify(value));
    return el("span", `json-${typeof value}`, String(value));
  }
}

/** แสดง body ตามชนิด: JSON เป็น tree, form เป็นตาราง, อ่านไม่ได้ก็บอกเหตุผล */
function bodyView(part) {
  const box = el("div", "body-view");
  if (part.body_error) return el("div", "body-view", el("p", "body-note", part.body_error));
  if (part.body == null || part.body === "") return el("div", "body-view", el("p", "body-note", "ไม่มี body"));
  if (part.body_unscanned) {
    box.append(el("p", "flag-unscanned", "ไม่ได้ตรวจหาข้อมูลลับ — ระวังก่อนแสดงหน้าห้อง"));
  }
  box.append(bodyContent(part));
  if (part.body_truncated_bytes > 0) {
    box.append(el("p", "body-note", `ตัดไว้ที่ 64 KB (ยังมีอีก ${part.body_truncated_bytes.toLocaleString()} bytes)`));
  }
  return box;
}

function bodyContent(part) {
  if (part.body_kind === "json") {
    try {
      return new JsonViewer(JSON.parse(part.body)).element;
    } catch {
      // ถูกตัดที่ 64 KB จึง parse ไม่ได้: แสดงข้อความดิบแทน
    }
  }
  if (part.body_kind === "form") {
    return keyValueTable("form-table", [...new URLSearchParams(part.body)]);
  }
  return el("pre", "raw-body", part.body);
}

/** ตาราง key/value ค่าที่ถูกซ่อนแสดงเป็น chip "ซ่อนไว้" */
function keyValueTable(className, pairs) {
  const rows = pairs.map(([key, value]) => el("tr", null, el("td", null, key), el("td", null, value === REDACTED ? redactedChip() : value)));
  return el("table", `kv-table ${className}`, el("tbody", null, ...rows));
}

/** headers: key ตัวหนา ค่าที่ซ่อนไว้มีไอคอนกุญแจ */
function headersTable(headers) {
  const rows = Object.entries(headers).map(([name, value]) => {
    const cell = el("td", null, value);
    if (value.includes(REDACTED)) cell.prepend(lockIcon());
    return el("tr", null, el("th", null, name), cell);
  });
  if (rows.length === 0) return el("p", "body-note", "ไม่มี header");
  return el("table", "kv-table headers-table", el("tbody", null, ...rows));
}

function lockIcon() {
  const lock = el("span", "flag-lock");
  lock.innerHTML = LOCK_ICON;
  lock.title = "ค่านี้ถูกซ่อนไว้";
  return lock;
}

function contentType(headers) {
  const entry = Object.entries(headers).find(([name]) => name.toLowerCase() === "content-type");
  return entry ? entry[1] : "—";
}

function requestLine(request) {
  const url = safeUrl(request.url);
  return `${request.method} ${url ? url.pathname + url.search : request.path} ${HTTP_VERSION}`;
}

function statusLine(response) {
  return `${HTTP_VERSION} ${response.status} ${response.status_text}`.trim();
}

/** ยังไม่มีคำตอบ: บอกว่ารออยู่หรือล้มเหลวเพราะอะไร */
function noResponseNote(exchange) {
  const text = exchange.state === "failed" ? `ไม่ได้คำตอบ: ${exchange.failure ?? "ล้มเหลว"}` : "รอคำตอบจากเซิร์ฟเวอร์…";
  return el("p", "body-note", text);
}

function rawHttp(firstLine, headers, part) {
  const lines = Object.entries(headers).map(([name, value]) => `${name}: ${value}`);
  const body = part.body_error ? `(${part.body_error})` : part.body ?? "";
  return el("pre", "raw-http", [firstLine, ...lines, "", body].join("\n"));
}

function field(label, ...value) {
  return el("div", "field", el("dt", null, label), el("dd", null, ...value));
}

const DETAIL_TABS = [
  { id: "overview", label: "ภาพรวม" },
  { id: "request", label: "ขาออก (Request)" },
  { id: "response", label: "ขาเข้า (Response)" },
  { id: "raw", label: "ดิบ (Raw)" },
];

/** คอลัมน์ขวา: หัว Detail + แท็บ ภาพรวม / ขาออก / ขาเข้า / ดิบ
 *  สอนแนวคิด: state ใน object — จำแท็บที่เลือกไว้ (this.tab) แม้จะเปลี่ยนไปดู Exchange อื่น */
class DetailView {
  constructor(element) {
    this.element = element;
    this.tab = "overview";
    this.exchange = null;
    this.render();
  }

  show(exchange) {
    this.exchange = exchange;
    this.render();
  }

  choose(tab) {
    this.tab = tab;
    this.render();
  }

  render() {
    if (!this.exchange) {
      this.element.replaceChildren(el("p", "empty", "เลือก Exchange ทางซ้ายเพื่อดูรายละเอียด"));
      return;
    }
    this.element.replaceChildren(this.head(), this.tabs(), el("div", "tab-panel", ...this.panel()));
  }

  head() {
    const exchange = this.exchange;
    return el(
      "header",
      "detail-head",
      el("div", "detail-line", methodBadge(exchange.request.method), statusBadge(exchange), textSpan("ms", durationText(exchange))),
      el("p", "detail-url", exchange.request.url),
      el("p", "detail-summary", exchange.summary),
    );
  }

  tabs() {
    const list = el("div", "tabs");
    list.setAttribute("role", "tablist");
    for (const tab of DETAIL_TABS) {
      const button = el("button", "tab", tab.label);
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(tab.id === this.tab));
      button.addEventListener("click", () => this.choose(tab.id));
      list.append(button);
    }
    return list;
  }

  panel() {
    const { request, response } = this.exchange;
    if (this.tab === "request") {
      return [el("p", "request-line", requestLine(request)), el("h3", null, "Headers"), headersTable(request.headers),
        el("h3", null, "Body"), bodyView(request)];
    }
    if (this.tab === "response") {
      if (!response) return [noResponseNote(this.exchange)];
      return [el("p", "status-line", statusLine(response)), el("h3", null, "Headers"), headersTable(response.headers),
        el("h3", null, "Body"), bodyView(response)];
    }
    if (this.tab === "raw") {
      return [
        el("h3", null, "ขาออก (Request)"), rawHttp(requestLine(request), request.headers, request),
        el("h3", null, "ขาเข้า (Response)"),
        response ? rawHttp(statusLine(response), response.headers, response) : noResponseNote(this.exchange),
      ];
    }
    return [el("div", "overview", this.requestSide(), this.responseSide())];
  }

  requestSide() {
    const request = this.exchange.request;
    const query = Object.entries(request.query).flatMap(([key, values]) => values.map((value) => [key, value]));
    return el(
      "section",
      "side side-request",
      el("h3", null, "ขาออก (Request)"),
      el("dl", null, field("method", methodBadge(request.method)), field("path", el("code", null, request.path)),
        field("query", query.length ? keyValueTable("query-table", query) : "—")),
      el("h4", null, "body"),
      bodyView(request),
    );
  }

  responseSide() {
    const response = this.exchange.response;
    const side = el("section", "side side-response", el("h3", null, "ขาเข้า (Response)"));
    if (!response) {
      side.append(noResponseNote(this.exchange));
      return side;
    }
    side.append(
      el("dl", null, field("status", statusBadge(this.exchange), ` ${response.status_text}`),
        field("content-type", el("code", null, contentType(response.headers)))),
      el("h4", null, "body"),
      bodyView(response),
    );
    return side;
  }
}

/** ประกอบทุกส่วนเข้าด้วยกัน */
function main() {
  const detail = new DetailView(document.getElementById("detail"));
  const timeline = new TimelineView(
    document.getElementById("timeline"),
    document.getElementById("timeline-empty"),
    (exchange) => detail.show(exchange),
  );
  const status = new StatusView(document.getElementById("chrome-status"));
  const chromeHelp = new ChromeHelpView(
    document.getElementById("chrome-setup"),
    document.getElementById("chrome-banner"),
  );
  const hiddenToggle = new HiddenToggle(document.getElementById("hidden-toggle"));
  const filters = new FilterControls(document.getElementById("preset"), document.getElementById("custom-filters"));
  filters.load();
  const banner = document.getElementById("socket-banner");
  const showStatus = (data) => {
    status.show(data);
    chromeHelp.show(data);
    hiddenToggle.show(data);
    filters.show(data);
    // CSS ใช้ค่านี้รอให้ครบ Correlation window ก่อนบอกว่าคลิกนี้ "ไม่มี API call"
    document.documentElement.style.setProperty("--correlation-window", `${data.correlation_window_ms}ms`);
  };

  const handlers = {
    snapshot: (data) => {
      timeline.reset(data.interactions, data.exchanges);
      showStatus(data.status);
    },
    "interaction.new": (data) => timeline.upsertInteraction(data),
    "interaction.update": (data) => timeline.upsertInteraction(data),
    "exchange.new": (data) => timeline.upsertExchange(data),
    "exchange.update": (data) => timeline.upsertExchange(data),
    status: showStatus,
  };

  const socket = new InspectorSocket(
    (message) => handlers[message.type]?.(message.data),
    (connected) => { banner.hidden = connected; },
  );
  socket.connect();
}

main();
