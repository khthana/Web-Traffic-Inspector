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
    this.interactions = new Map(); // interaction id → ข้อมูลล่าสุดของ Interaction
    this.selectedId = null;
    listElement.addEventListener("click", (event) => this.selectRow(event.target));
    // Enter เท่านั้น: Space สงวนไว้ให้ "หยุด/เริ่มต่อ" (SPEC 6.3)
    listElement.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.selectRow(event.target);
    });
  }

  reset(interactions, exchanges) {
    this.list.replaceChildren();
    this.cards.clear();
    this.rows.clear();
    this.exchanges.clear();
    this.interactions.clear();
    interactions.forEach((interaction) => this.upsertInteraction(interaction, false));
    exchanges.forEach((exchange) => this.upsertExchange(exchange));
    if (!this.exchanges.has(this.selectedId)) this.select(null); // Exchange ที่เลือกไว้ถูกตัดออกจาก store แล้ว
    this.updateEmpty();
  }

  selectRow(target) {
    const row = target.closest(".exchange");
    if (row) this.select(row.dataset.id, true);
  }

  /** byUser = ผู้สอนเลือกเอง (คลิก/Enter) ไม่ใช่โปรแกรมเลือกให้ */
  select(id, byUser = false) {
    this.rows.get(this.selectedId)?.setAttribute("aria-selected", "false");
    this.selectedId = id;
    this.rows.get(id)?.setAttribute("aria-selected", "true");
    this.notify(this.exchanges.get(id) ?? null, byUser);
  }

  notify(exchange, byUser = false) {
    this.onSelect(exchange, exchange ? this.interactions.get(exchange.interaction_id) ?? null : null, byUser);
  }

  /** ↑/↓: เลื่อนการเลือกไปแถวก่อน/ถัดไปที่อยู่บนจอ (แถวที่ซ่อนอยู่ข้ามไป) ยังไม่ได้เลือกก็เริ่มที่แถวบนสุด */
  moveSelection(step) {
    // ดูที่ตัวแถวและการ์ด ไม่ดูทั้ง Timeline: จอแคบที่ Detail เปิดเต็มจอ Timeline ถูกซ่อน แต่ยังไล่แถวต่อได้
    const rows = [...this.list.querySelectorAll(".exchange")].filter((row) => isShown(row) && isShown(row.closest(".card")));
    if (rows.length === 0) return;
    const current = rows.indexOf(this.rows.get(this.selectedId));
    const next = current === -1 ? 0 : Math.min(Math.max(current + step, 0), rows.length - 1);
    rows[next].focus();
    this.select(rows[next].dataset.id, true);
  }

  /** Exchange ที่มองเห็นได้ (ไม่ถูกกรอง) ของ Interaction หนึ่ง เรียงตามเวลาที่ request ออก */
  visibleExchangesOf(interactionId) {
    return [...this.exchanges.values()]
      .filter((exchange) => exchange.interaction_id === interactionId && !exchange.hidden)
      .sort((a, b) => a.started_at - b.started_at);
  }

  /** การ์ดใหม่ขึ้นบนสุดพร้อมไฮไลต์ การ์ดเดิมเปลี่ยนแค่หัวการ์ด ไม่ย้ายตำแหน่ง */
  upsertInteraction(interaction, highlight = true) {
    this.interactions.set(interaction.id, interaction);
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
    if (exchange.id === this.selectedId) this.notify(exchange); // ได้คำตอบแล้ว: Detail ต้องเห็นข้อมูลใหม่
  }

  updateEmpty() {
    this.empty.hidden = this.cards.size > 0;
  }

  focusSelected() {
    this.rows.get(this.selectedId)?.focus();
  }

  isCardShown(interactionId) {
    const card = this.cards.get(interactionId);
    return card !== undefined && isShown(card);
  }
}

/** element นี้ไม่ได้ถูก CSS ซ่อนด้วย display: none ที่ตัวมันเอง (ถูกกรอง, การ์ดว่าง) */
function isShown(element) {
  return getComputedStyle(element).display !== "none";
}

/** ปุ่มลอย "มี N รายการใหม่ ↑": ผู้สอนเลื่อนลงไปดูของเก่าอยู่ การ์ดใหม่ไม่ดึงจอขึ้นไป (Chrome คงตำแหน่งให้เอง:
 *  scroll anchoring) แค่นับไว้ กดปุ่มหรือเลื่อนกลับขึ้นบนสุดเองแล้วปุ่มหายไป
 *  นับเฉพาะการ์ดที่มองเห็นได้จริง การ์ดเบื้องหลังที่มีแต่ tracking ถูกซ่อนอยู่ จึงไม่ทำให้ตัวเลขพอง
 *  สอนแนวคิด: state ใน object — this.unseen จำ Interaction ที่มาถึงตอนผู้สอนไม่ได้อยู่บนสุด */
class NewItemsNotice {
  constructor(scroller, button, timeline) {
    this.scroller = scroller;
    this.button = button;
    this.timeline = timeline;
    this.unseen = new Set(); // interaction id
    scroller.addEventListener("scroll", () => {
      if (this.atTop()) this.reset();
    });
    button.addEventListener("click", () => {
      scroller.scrollTo({ top: 0 });
      this.reset();
    });
  }

  atTop() {
    return this.scroller.scrollTop < 1;
  }

  onNewInteraction(interactionId) {
    if (!this.atTop()) this.unseen.add(interactionId); // อยู่บนสุด: เห็นการ์ดใหม่อยู่แล้ว
    this.refresh();
  }

  /** นับใหม่ทุกครั้งที่การ์ดอาจเปลี่ยนจากซ่อนเป็นเห็น (Exchange มาถึง, เปิดปุ่ม "ซ่อน N รายการ") */
  refresh() {
    const count = [...this.unseen].filter((id) => this.timeline.isCardShown(id)).length;
    this.button.textContent = `มี ${count} รายการใหม่ ↑`;
    this.button.hidden = count === 0;
  }

  reset() {
    this.unseen.clear();
    this.refresh();
  }
}

/** ข้อมูลที่ขึ้นกับชนิดของ Interaction รวมไว้ที่เดียว
 *  icon: เมาส์ = คลิก, เอกสาร = โหลดหน้า, นาฬิกา = เกิดเองเบื้องหลัง
 *  notFromClick: คำอธิบายในแท็บ "คลิก (Event)" เมื่อ Exchange ไม่ได้เกิดจากคลิก */
const INTERACTION_KINDS = {
  click: { icon: '<rect x="4" y="1.5" width="8" height="13" rx="4" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 3.5v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' },
  page_load: {
    notFromClick: "Exchange นี้ไม่ได้เกิดจากคลิก — เกิดตอนเบราว์เซอร์เปิดหน้าเว็บ",
    icon: '<path d="M4 1.5h5l3 3v10H4Zm5 0v3h3M6 8h4M6 10.5h4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  },
  background: {
    notFromClick: "Exchange นี้ไม่ได้เกิดจากคลิก — หน้าเว็บส่งเองเบื้องหลัง (เช่น polling)",
    icon: '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
  },
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
  icon.innerHTML = `<svg viewBox="0 0 16 16" width="1.1em" height="1.1em" aria-hidden="true" focusable="false">${INTERACTION_KINDS[interaction.kind].icon}</svg>`;
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
    textSpan("path", ltrText(exchange.request.path), exchange.request.url),
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

const LRM = String.fromCharCode(0x200e); // left-to-right mark

/** ครอบ path ด้วย LRM: direction: rtl (ที่ใช้ตัด path ยาวจากซ้าย) จะได้ไม่ย้าย "/" ไปไว้ท้าย */
function ltrText(text) {
  return `${LRM}${text}${LRM}`;
}

function shorten(text, max) {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/** จุดสถานะ Chrome ที่ top bar
 *  สอนแนวคิด: single responsibility — class นี้รู้แค่เรื่องแสดงสถานะ */
/** โหมด Recording playback: เปิดไฟล์ที่ export ไว้ ไม่ต่อ Chrome และไม่มี traffic ใหม่เข้ามา */
function isPlayback(status) {
  return status.mode === "playback";
}

class StatusView {
  constructor(element) {
    this.element = element;
  }

  /** Chrome หลุดสำคัญกว่าการหยุด (การหยุดยังเห็นจากแถบเหลือง) */
  show(status) {
    this.element.dataset.state = status.chrome;
    this.element.dataset.paused = String(status.paused);
    this.element.dataset.mode = status.mode;
    this.element.querySelector(".label").textContent = this.label(status);
  }

  label(status) {
    if (isPlayback(status)) return `Open Recording: ${status.recording_file}`; // ไม่ต่อ Chrome โดยตั้งใจ
    if (status.chrome !== "connected") return "ไม่พบ Chrome";
    return status.paused ? "หยุดชั่วคราว" : `เชื่อมต่อแล้ว · ${status.tabs.length} แท็บ`;
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
    // Recording playback ไม่ต่อ Chrome โดยตั้งใจ จึงไม่ต้องสอนวิธีเปิด Chrome หรือเตือนว่าหลุด
    const connected = status.chrome === "connected" || isPlayback(status);
    if (connected) this.wasConnected = true;
    this.setup.querySelector("#chrome-command").textContent = status.chrome_launch_command;
    this.setup.hidden = connected || !status.chrome_launch_command; // โหมด --demo ไม่ต้องใช้ Chrome
    this.banner.hidden = connected || !this.wasConnected;
  }

  copyCommand() {
    return copyText(this.setup.querySelector("#copy-command"), this.setup.querySelector("#chrome-command").textContent);
  }
}

/** คัดลอกข้อความลง clipboard แล้วให้ปุ่มบอกผลสักครู่ ก่อนกลับเป็นข้อความเดิม */
async function copyText(button, text) {
  const label = button.dataset.label ?? button.textContent;
  button.dataset.label = label; // กดซ้ำระหว่างที่ปุ่มยังบอกผลอยู่ จะได้ไม่จำ "คัดลอกแล้ว ✓" เป็นข้อความเดิม
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "คัดลอกแล้ว ✓";
  } catch {
    button.textContent = "คัดลอกไม่ได้ — เลือกข้อความเองนะ";
  }
  setTimeout(() => { button.textContent = label; }, 2000);
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
    span.append(textSpan("flag-unscanned", "ไม่ได้ตรวจหาข้อมูลลับ", "body นี้อ่านรูปแบบไม่ออก (เช่น text, binary หรือ JSON/multipart ที่ผิดรูปหรือถูกตัด) จึงไม่ได้ตรวจหาข้อมูลลับ — ระวังก่อนแสดงหน้าห้อง"));
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

/** กลุ่มของ status ที่ใช้เลือกสี: pending, failed, 2xx, 3xx, 4xx, 5xx (Timeline, Detail และ Flow strip ใช้ร่วมกัน) */
function statusKind(exchange) {
  if (exchange.state !== "done") return exchange.state;
  return `${Math.floor(exchange.response.status / 100)}xx`;
}

function statusBadge(exchange) {
  const kind = statusKind(exchange);
  const text = { pending: "รอคำตอบ…", failed: "failed" }[kind] ?? String(exchange.response.status);
  return badge(text, `status-${kind}`);
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

/** el = "element": สร้าง element พร้อม class และลูก (ข้อความใส่เป็น text node เสมอ จึงไม่มี HTML injection)
 *  ใช้บ่อยมากใน Detail จึงตั้งชื่อสั้น */
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
  /** rawText คือ body เดิม: โหมดดิบแสดงตามนี้ ไม่ใช้ค่าที่ parse แล้ว (เลขที่ใหญ่เกิน 2^53 จะได้ไม่เพี้ยน) */
  constructor(value, rawText) {
    this.tree = el("ul", "json-tree", this.node(null, value, 0));
    this.raw = el("pre", "raw-body", rawText);
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
  if (part.body_error || !part.body) {
    box.append(el("p", "body-note", part.body_error || "ไม่มี body"));
    return box;
  }
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
      return new JsonViewer(JSON.parse(part.body), part.body).element;
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

/** หนึ่งแถวของ <dl>: ชื่อ (dt) + ค่า (dd) */
function definitionRow(label, ...value) {
  return el("div", "field", el("dt", null, label), el("dd", null, ...value));
}

/** แต่ละแท็บรู้วิธีวาดเนื้อหาของตัวเอง เพิ่มแท็บใหม่ (คลิก, โค้ด) ได้ที่นี่ที่เดียว */
const DETAIL_TABS = [
  { id: "overview", label: "ภาพรวม", render: (view) => [el("div", "overview", view.requestSide(), view.responseSide())] },
  { id: "request", label: "ขาออก (Request)", render: (view) => view.requestPanel() },
  { id: "response", label: "ขาเข้า (Response)", render: (view) => view.responsePanel() },
  { id: "raw", label: "ดิบ (Raw)", render: (view) => view.rawPanel() },
  { id: "click", label: "คลิก (Event)", render: (view) => view.clickPanel() },
  { id: "code", label: "โค้ด", render: (view) => view.codePanel() },
];

/** โค้ดหนึ่งภาษา: ปุ่ม Copy as … + ตัวโค้ด (เลือกข้อความเองก็ได้ถ้าคัดลอกไม่ได้) */
function codeBlock(snippet) {
  const button = el("button", "tool-button copy-code", snippet.label);
  button.type = "button";
  button.addEventListener("click", () => copyText(button, snippet.code));
  const code = el("pre", "code-snippet", snippet.code);
  code.dataset.language = snippet.language;
  return el("section", "code-block", button, el("p", "code-hint", snippet.hint), code);
}


/** ขาออกและขาเข้าหน้าตาเหมือนกัน: บรรทัดแรก + headers + body */
function messagePanel(firstLine, part) {
  return [firstLine, el("h3", null, "Headers"), headersTable(part.headers), el("h3", null, "Body"), bodyView(part)];
}

/** ส่วนของ Exchange ที่ Detail แสดง (การซ่อนตาม Preset ไม่เกี่ยว) ใช้เทียบว่าต้องวาดใหม่ไหม */
function shownPart(exchange) {
  const { hidden, hidden_reason, ...shown } = exchange;
  return JSON.stringify(shown);
}

/** คอลัมน์ขวา: หัว Detail + แท็บ ภาพรวม / ขาออก / ขาเข้า / ดิบ
 *  สอนแนวคิด: state ใน object — จำแท็บที่เลือกไว้ (this.tab) แม้จะเปลี่ยนไปดู Exchange อื่น */
class DetailView {
  constructor(element) {
    this.element = element;
    this.tab = "overview";
    this.exchange = null;
    this.interaction = null; // Interaction ที่ Exchange นี้อยู่ (ใช้ในแท็บคลิก)
    this.render();
  }

  /** snapshot หรือ update ที่ไม่เปลี่ยนสิ่งที่ Detail แสดงจะไม่วาดใหม่ โหนด JSON ที่กางไว้และโหมดดิบจึงไม่หาย */
  show(exchange, interaction = null) {
    if (exchange && this.exchange && shownPart(exchange) === shownPart(this.exchange)
      && interaction?.id === this.interaction?.id) return;
    this.exchange = exchange;
    this.interaction = interaction;
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
      el("div", "detail-line", methodBadge(exchange.request.method), statusBadge(exchange), textSpan("ms", durationText(exchange)),
        textSpan("detail-clock", clockTime(exchange.started_at)), this.exportLink()),
      el("p", "detail-url", exchange.request.url),
      el("p", "detail-summary", exchange.summary),
    );
  }

  /** ดาวน์โหลด Recording ของ Interaction ที่ Exchange นี้อยู่ (ใช้เป็นโจทย์แลบได้ทีละเรื่อง) */
  exportLink() {
    if (!this.interaction) return null;
    const link = el("a", "export-one", "Export Interaction นี้");
    link.href = `/api/export?interaction_id=${encodeURIComponent(this.interaction.id)}`;
    link.download = "";
    return link;
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
    return DETAIL_TABS.find((tab) => tab.id === this.tab).render(this);
  }

  requestPanel() {
    const request = this.exchange.request;
    return messagePanel(el("p", "request-line", requestLine(request)), request);
  }

  responsePanel() {
    const response = this.exchange.response;
    if (!response) return [noResponseNote(this.exchange)];
    return messagePanel(el("p", "status-line", statusLine(response)), response);
  }

  rawPanel() {
    const { request, response } = this.exchange;
    return [
      el("h3", null, "ขาออก (Request)"), rawHttp(requestLine(request), request.headers, request),
      el("h3", null, "ขาเข้า (Response)"),
      response ? rawHttp(statusLine(response), response.headers, response) : noResponseNote(this.exchange),
    ];
  }

  clickPanel() {
    const click = this.interaction?.click;
    if (!click) {
      return [el("p", "body-note", INTERACTION_KINDS[this.interaction?.kind]?.notFromClick ?? "Exchange นี้ไม่ได้เกิดจากคลิก")];
    }
    const element = click.element;
    return [el("dl", "field-list click-info",
      definitionRow("element", el("code", "click-tag", `<${element.tag}>`)),
      definitionRow("ข้อความ", el("span", "click-text", element.text || element.aria_label || "—")),
      definitionRow("selector", el("code", "click-selector", element.selector)),
      element.href ? definitionRow("ลิงก์ไป", el("code", null, element.href)) : null,
      definitionRow("คลิกเมื่อ", clockTime(click.ts)),
      definitionRow("คลิก → request ออก", el("span", "click-delay", `${Math.round(this.exchange.started_at - click.ts)} ms`)),
    )];
  }

  /** โค้ดสร้างที่ server (GET /api/exchanges/{id}/code) จาก Exchange ที่ผ่าน Redaction แล้ว ไม่มี header ที่ถูกซ่อน */
  codePanel() {
    const panel = el("div", "code-panel", el("p", "body-note", "กำลังเตรียมโค้ด…"));
    fetch(`/api/exchanges/${encodeURIComponent(this.exchange.id)}/code`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(response.statusText))))
      .then((snippets) => panel.replaceChildren(...snippets.map(codeBlock)))
      .catch(() => panel.replaceChildren(el("p", "body-note", "โหลดโค้ดไม่ได้ (Exchange นี้อาจถูกล้างไปแล้ว)")));
    return [panel];
  }

  requestSide() {
    const request = this.exchange.request;
    const query = Object.entries(request.query).flatMap(([key, values]) => values.map((value) => [key, value]));
    return el(
      "section",
      "side side-request",
      el("h3", null, "ขาออก (Request)"),
      el("dl", "field-list", definitionRow("method", methodBadge(request.method)), definitionRow("path", el("code", null, request.path)),
        definitionRow("query", query.length ? keyValueTable("query-table", query) : "—")),
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
      el("dl", "field-list", definitionRow("status", statusBadge(this.exchange), ` ${response.status_text}`),
        definitionRow("content-type", el("code", null, contentType(response.headers)))),
      el("h4", null, "body"),
      bodyView(response),
    );
    return side;
  }
}

/** แต่ละจังหวะของ Flow strip: ยาวกี่ ms ที่ความเร็ว 1x และวิ่งไปทางไหน (out = ซ้ายไปขวา, back = ขวาไปซ้าย)
 *  รวมช่องว่างระหว่างจังหวะแล้วประมาณ 2 วินาที (SPEC 6.5) */
const FLOW_STEPS = {
  click: { ms: 500, direction: "out" },
  request: { ms: 700, direction: "out" },
  response: { ms: 700, direction: "back" },
};
const FLOW_GAP_MS = 50;
const FLOW_SPEEDS = [1, 0.5, 0.25];
const LANE_START = { left: "0%", transform: "translateX(0)" };
const LANE_END = { left: "100%", transform: "translateX(-100%)" };

/** keyframes ของจุด/ซองที่วิ่งตามทิศของจังหวะ จางเข้าตอนออกตัวและจางออกตอนถึง */
function travel(direction) {
  const [from, to] = direction === "out" ? [LANE_START, LANE_END] : [LANE_END, LANE_START];
  return [{ ...from, opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.9 }, { ...to, opacity: 0 }];
}

/** Flow strip ด้านบนของ Detail: เล่นจังหวะ click → request → response ของ Exchange ที่เลือก
 *  เล่นใหม่เมื่อเลือก Exchange อื่น หรือเมื่อคำตอบของ Exchange ที่รออยู่มาถึง (เล่นเฉพาะจังหวะ response)
 *  ป้ายของแต่ละจังหวะค่อยๆ ขึ้นตามลำดับเสมอ ส่วนจุด/ซองวิ่งเฉพาะจังหวะที่เกิดขึ้นจริง
 *  (ไม่มีคลิกข้ามจังหวะแรก ยังรอคำตอบหรือล้มเหลวไม่มีซองวิ่งกลับ)
 *  ใช้ Web Animations API (element.animate) แทน CSS animation จึงต่อจังหวะ หยุด และเล่นซ้ำได้จากโค้ดตรงๆ
 *  ผู้ใช้ตั้ง prefers-reduced-motion ไว้: ไม่มีอะไรวิ่ง แสดงป้ายทุกจังหวะนิ่งๆ แทน
 *  สอนแนวคิด: encapsulation — คนอื่นเรียกแค่ show(exchange, interaction) ลำดับจังหวะและความเร็วเป็นเรื่องภายใน */
class FlowStrip {
  constructor(element, preferences, reducedMotion) {
    this.element = element;
    this.preferences = preferences;
    this.reducedMotion = reducedMotion; // MediaQueryList: อ่าน .matches ทุกครั้งที่เล่น ผู้ใช้เปลี่ยนกลางทางก็ได้ผล
    this.exchange = null;
    this.interaction = null;
    this.animations = [];
    const saved = Number(preferences.get("flowSpeed", 1));
    this.speed = FLOW_SPEEDS.includes(saved) ? saved : 1;
    this.lanes = Object.fromEntries(Object.keys(FLOW_STEPS).map((step) => {
      const lane = element.querySelector(`[data-step="${step}"]`);
      return [step, { label: lane.querySelector(".flow-label"), token: lane.querySelector(".flow-token") }];
    }));
    this.speedButtons = FLOW_SPEEDS.map((speed) => {
      const button = el("button", "tool-button", `${speed}x`);
      button.type = "button";
      button.dataset.speed = String(speed);
      button.addEventListener("click", () => this.changeSpeed(speed));
      return button;
    });
    element.querySelector(".flow-speed").replaceChildren(...this.speedButtons);
    element.querySelector("#flow-again").addEventListener("click", () => this.play(this.steps()));
    this.showSpeed();
  }

  show(exchange, interaction) {
    const previous = this.exchange;
    this.exchange = exchange;
    this.interaction = interaction;
    this.element.hidden = !exchange;
    if (!exchange) {
      this.stop();
      return;
    }
    this.fill();
    if (previous?.id !== exchange.id) this.play(this.steps());
    else if (previous.state === "pending" && exchange.state === "done") this.play(["response"]);
  }

  fromClick() {
    return this.interaction?.kind === "click";
  }

  /** จังหวะที่เล่าได้: ไม่มีคลิกข้ามจังหวะแรก */
  steps() {
    return [...(this.fromClick() ? ["click"] : []), "request", "response"];
  }

  /** จังหวะนี้มีอะไรวิ่งไหม: ซองวิ่งกลับเฉพาะเมื่อได้คำตอบแล้ว */
  moves(step) {
    return step !== "response" || this.exchange.state === "done";
  }

  fill() {
    const { request } = this.exchange;
    this.element.dataset.fromClick = String(this.fromClick());
    this.element.dataset.status = statusKind(this.exchange); // CSS ใช้ระบายสีซองขากลับให้ตรงกับ badge
    this.lanes.click.label.textContent = this.fromClick() ? "click" : "ไม่มีคลิก";
    // path ยาวตัดจากซ้ายแบบเดียวกับ Timeline (…/cart/add) ส่วนท้ายของ path บอกว่าเรียกอะไร
    this.lanes.request.label.replaceChildren(`${request.method} `, textSpan("flow-path", ltrText(request.path), request.url));
    const duration = durationText(this.exchange);
    this.lanes.response.label.replaceChildren(statusBadge(this.exchange), duration ? ` · ${duration}` : "");
    this.element.querySelector(".flow-host").textContent = request.host;
  }

  play(steps) {
    this.stop();
    if (this.reducedMotion.matches) return;
    let delay = 0;
    for (const step of steps) {
      const duration = FLOW_STEPS[step].ms / this.speed;
      const { label, token } = this.lanes[step];
      const timing = { duration, delay, fill: "both", easing: "ease-in-out" };
      if (this.moves(step)) this.animations.push(token.animate(travel(FLOW_STEPS[step].direction), timing));
      this.animations.push(label.animate([{ opacity: 0 }, { opacity: 1 }], { ...timing, duration: duration / 2 }));
      delay += duration + FLOW_GAP_MS / this.speed;
    }
  }

  stop() {
    for (const animation of this.animations) animation.cancel();
    this.animations = [];
  }

  changeSpeed(speed) {
    this.speed = speed;
    this.preferences.set("flowSpeed", speed);
    this.showSpeed();
    if (this.exchange) this.play(this.steps());
  }

  showSpeed() {
    for (const button of this.speedButtons) {
      button.setAttribute("aria-pressed", String(Number(button.dataset.speed) === this.speed));
    }
  }
}

const ACTION_WORDS = new Set(["add", "delete", "remove", "update", "create", "login", "logout", "register", "signin", "signup", "submit", "save", "checkout", "pay"]);
const READ_WORDS = new Set(["get", "list", "fetch", "search", "data"]);
const TOP_SCORE = 3;

/** คำใน path (ไม่รวม query): แยกที่ตัวที่ไม่ใช่ตัวอักษรและที่ camelCase เช่น /api/addToCart → api, add, to, cart */
function pathWords(url) {
  const path = safeUrl(url)?.pathname ?? url.split("?")[0];
  return path.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase().split(/[^a-z]+/).filter(Boolean);
}

/** ความน่าจะเป็น Exchange หลักของคลิก: 3 = เปลี่ยนข้อมูลและ path บอก action (cart/add)
 *  2 = ไม่ใช่ GET แต่ path ไม่บอกอะไร, 1 = ไม่ใช่ GET แต่ path บอกว่าแค่อ่าน (เว็บที่ใช้ POST ทุก API), 0 = GET */
function mainExchangeScore(exchange) {
  if (exchange.request.method === "GET") return 0;
  const words = pathWords(exchange.request.url);
  if (words.some((word) => ACTION_WORDS.has(word))) return TOP_SCORE;
  return words.some((word) => READ_WORDS.has(word)) ? 1 : 2;
}

/** "ตามคลิกล่าสุด": เมื่อมีคลิกใหม่ เลือก Exchange หลักของคลิกนั้นให้ ผู้สอนไม่ต้องสลับหน้าต่างมากด
 *  Exchange หลัก = ตัวที่มองเห็นและได้ mainExchangeScore สูงสุด คะแนนเท่ากันเลือกตัวที่มาก่อน
 *  Exchange ทยอยมาทีละตัว ตัวที่มาทีหลังแย่งการเลือกได้เมื่อคะแนนสูงกว่าเท่านั้น
 *  Hidden exchange (tracking, นอกโฟกัส) ไม่ถูกเลือกเลย แม้จะเปิดปุ่ม "ซ่อน N รายการ" อยู่ เพราะไม่ใช่สิ่งที่สอน
 *  สอนแนวคิด: single responsibility — รู้แค่ "ควรเลือกอะไร" ส่วนการเก็บแถวและวาด Detail เป็นงานของ TimelineView/DetailView */
class ClickFollower {
  constructor(timeline, checkbox) {
    this.timeline = timeline;
    this.checkbox = checkbox;
    this.clickInteractionId = null; // Click interaction ที่กำลังรอ Exchange หลักอยู่
    checkbox.addEventListener("change", () => { if (!checkbox.checked) this.stop(); });
  }

  onNewInteraction(interaction) {
    if (interaction.kind === "click" && this.checkbox.checked) this.clickInteractionId = interaction.id;
  }

  onExchange(exchange) {
    if (exchange.interaction_id === this.clickInteractionId) this.choose();
  }

  /** snapshot ใหม่ (เช่นเปลี่ยน Preset) อาจทำให้ Exchange ที่เคยซ่อนกลับมามองเห็น: เลือกใหม่ */
  onSnapshot() {
    if (this.clickInteractionId !== null) this.choose();
  }

  /** เลือกตัวที่คะแนนสูงสุดในตอนนี้ (reduce เก็บตัวแรกเมื่อเท่ากัน) ได้คะแนนสูงสุดที่เป็นไปได้แล้วก็เลิกตาม */
  choose() {
    const visible = this.timeline.visibleExchangesOf(this.clickInteractionId);
    if (visible.length === 0) return;
    const scored = visible.map((exchange) => ({ exchange, score: mainExchangeScore(exchange) }));
    const best = scored.reduce((winner, candidate) => (candidate.score > winner.score ? candidate : winner));
    if (best.exchange.id !== this.timeline.selectedId) this.timeline.select(best.exchange.id);
    if (best.score === TOP_SCORE) this.stop(); // ตัวที่มาทีหลังคะแนนเท่ากันอย่างมาก แย่งไม่ได้อยู่แล้ว
  }

  /** ผู้สอนเลือกเองหรือปิด checkbox: เลิกตามคลิกนี้ */
  stop() {
    this.clickInteractionId = null;
  }
}

/** ปุ่ม หยุด/เริ่มต่อ และ ล้าง คุยกับ POST /api/pause|resume|clear ส่วนหน้าจอเปลี่ยนตาม status ที่ server ส่งกลับมา
 *  สอนแนวคิด: encapsulation — คนอื่นสั่งได้แค่ togglePause() / clear() ไม่ต้องรู้ว่าเรียก API ตัวไหน */
class CaptureControls {
  constructor(pauseButton, clearButton, banner) {
    this.pauseButton = pauseButton;
    this.clearButton = clearButton;
    this.banner = banner;
    this.paused = false;
    this.playback = false;
    pauseButton.addEventListener("click", () => this.togglePause());
    clearButton.addEventListener("click", () => this.clear());
  }

  show(status) {
    this.paused = status.paused;
    // Recording playback: ไม่มีอะไรให้เก็บ (หยุดไม่มีความหมาย) และล้างแล้วโหลดไฟล์กลับไม่ได้
    this.playback = isPlayback(status);
    this.pauseButton.hidden = this.playback;
    this.clearButton.hidden = this.playback;
    this.pauseButton.textContent = status.paused ? "เริ่มต่อ" : "หยุด";
    this.pauseButton.setAttribute("aria-pressed", String(status.paused));
    this.banner.hidden = !status.paused;
  }

  /** เปลี่ยน this.paused ทันที กดซ้ำเร็วๆ ก่อน status กลับมาจึงสลับถูกทาง (status จาก server ยืนยันอีกครั้ง) */
  togglePause() {
    if (this.playback) return Promise.resolve();
    this.paused = !this.paused;
    return fetch(this.paused ? "/api/pause" : "/api/resume", { method: "POST" });
  }

  clear() {
    if (this.playback) return Promise.resolve();
    return fetch("/api/clear", { method: "POST" });
  }
}

/** คีย์ลัดทั้งหน้า: ↑/↓ เลือก Exchange, Space หยุด/เริ่มต่อ, C ล้าง (ไม่ใช้ Ctrl+L เพราะชนกับเบราว์เซอร์)
 *  ดูจาก event.code (ตำแหน่งปุ่ม) ไม่ใช่ event.key: เปิดแป้นภาษาไทยอยู่ ปุ่ม C ได้ key เป็น "แ" แต่ code ยังเป็น KeyC
 *  สอนแนวคิด: lookup table แทน if/else — ปุ่มไหนทำอะไรอ่านได้จากตาราง this.actions ที่เดียว */
class KeyboardShortcuts {
  constructor(timeline, controls) {
    this.actions = {
      ArrowDown: () => timeline.moveSelection(1),
      ArrowUp: () => timeline.moveSelection(-1),
      Space: () => controls.togglePause(),
      KeyC: () => controls.clear(),
    };
    document.addEventListener("keydown", (event) => this.handle(event));
  }

  handle(event) {
    const action = this.actions[event.code];
    if (!action || event.repeat || event.ctrlKey || event.metaKey || event.altKey || this.belongsToTarget(event)) return;
    event.preventDefault(); // ไม่ให้ Space/ลูกศรเลื่อนหน้าจอ
    action();
  }

  /** คีย์นี้เป็นของ element ที่โฟกัสอยู่: ช่องกรอก/checkbox/dropdown ใช้ทุกปุ่ม,
   *  ปุ่มใช้ Space กดตัวเอง, แผง Detail ใช้ลูกศรเลื่อนอ่าน */
  belongsToTarget(event) {
    const target = event.target;
    if (!target.closest) return false;
    if (target.closest("input, select, textarea, [contenteditable]")) return true;
    if (event.code === "Space" && target.closest("button, summary")) return true;
    return event.code.startsWith("Arrow") && Boolean(target.closest("#detail"));
  }
}

/** ค่าที่ผู้ใช้เลือกไว้ (ขนาดตัวอักษร ธีม การปิดแถบเตือน ความเร็วของ Flow strip) เก็บใน localStorage ของเบราว์เซอร์ ไม่เขียนไฟล์ใดๆ
 *  เปิดแบบ private หรือเบราว์เซอร์บล็อก storage ไว้ก็ยังใช้ได้ แค่จำค่าไม่ได้ (แค่อ่าน window.localStorage
 *  ก็ throw ได้ จึงรับเป็นฟังก์ชันที่เปิด storage แล้วเรียกใน try ทุกครั้ง)
 *  สอนแนวคิด: dependency injection — class อื่นรับ Preferences เข้ามา ไม่เรียก localStorage เอง */
class Preferences {
  constructor(openStorage, prefix = "wti.") {
    this.openStorage = openStorage;
    this.prefix = prefix;
  }

  get(key, fallback) {
    try {
      return this.openStorage().getItem(this.prefix + key) ?? fallback;
    } catch {
      return fallback;
    }
  }

  set(key, value) {
    try {
      this.openStorage().setItem(this.prefix + key, String(value));
    } catch {
      // จำไม่ได้ก็ไม่เป็นไร ค่าใช้ได้จนปิดหน้า
    }
  }
}

const FONT_SIZES = [14, 17, 20]; // px: ระดับ A− / ปกติ / A+ (SPEC 6.2) ค่าเริ่มต้นอยู่ที่ --font-size ใน style.css ที่เดียว

/** ปุ่ม A− / A+ เปลี่ยนขนาดตัวอักษรทั้งหน้าทีละระดับ สุดทางแล้วปุ่มกดไม่ได้
 *  สอนแนวคิด: invariant — this.level อยู่ในช่วงของ FONT_SIZES เสมอ เพราะเปลี่ยนได้ทาง step() ทางเดียว */
class FontSizeControl {
  constructor(smaller, bigger, preferences) {
    this.smaller = smaller;
    this.bigger = bigger;
    this.preferences = preferences;
    const cssDefault = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--font-size"), 10);
    const saved = FONT_SIZES.indexOf(Number(preferences.get("fontSize", cssDefault)));
    this.level = saved === -1 ? FONT_SIZES.indexOf(cssDefault) : saved;
    smaller.addEventListener("click", () => this.step(-1));
    bigger.addEventListener("click", () => this.step(1));
    this.apply();
  }

  step(direction) {
    this.level = Math.min(Math.max(this.level + direction, 0), FONT_SIZES.length - 1);
    this.preferences.set("fontSize", FONT_SIZES[this.level]);
    this.apply();
  }

  apply() {
    document.documentElement.style.setProperty("--font-size", `${FONT_SIZES[this.level]}px`);
    this.smaller.disabled = this.level === 0;
    this.bigger.disabled = this.level === FONT_SIZES.length - 1;
  }
}

/** ธีมแต่ละแบบ: กดปุ่มแล้วไปธีมไหน และปุ่มเขียนว่าอะไร (บอกว่ากดแล้วจะได้ธีมไหน) */
const THEMES = {
  light: { next: "dark", buttonLabel: "ธีมมืด" },
  dark: { next: "light", buttonLabel: "ธีมสว่าง" },
};

/** สลับธีมสว่าง/มืด ค่าเริ่มต้นสว่าง (โปรเจกเตอร์อ่านง่ายกว่า) สีทั้งหมดเป็น CSS variables ใน style.css
 *  สอนแนวคิด: lookup table แทน if/else — ธีมถัดไปและข้อความบนปุ่มอ่านจากตาราง THEMES */
class ThemeSwitch {
  constructor(button, preferences) {
    this.button = button;
    this.preferences = preferences;
    const saved = preferences.get("theme", "light");
    this.theme = saved in THEMES ? saved : "light";
    button.addEventListener("click", () => this.toggle());
    this.apply();
  }

  toggle() {
    this.theme = THEMES[this.theme].next;
    this.preferences.set("theme", this.theme);
    this.apply();
  }

  apply() {
    document.documentElement.dataset.theme = this.theme;
    this.button.textContent = THEMES[this.theme].buttonLabel;
  }
}

/** แถบเตือนจริยธรรม แสดงตอนเปิดครั้งแรกจนกว่าจะกดปิด (SPEC 10)
 *  สอนแนวคิด: dependency injection — รับ Preferences เข้ามา test หรือหน้าอื่นส่งที่เก็บแบบอื่นให้ได้ */
class EthicsNotice {
  constructor(banner, closeButton, preferences) {
    banner.hidden = preferences.get("ethicsDismissed", "") === "yes";
    closeButton.addEventListener("click", () => {
      banner.hidden = true;
      preferences.set("ethicsDismissed", "yes");
    });
  }
}

/** จอแคบกว่า 900 px: Timeline กับ Detail ซ้อนกัน (CSS ดู class detail-open) ผู้สอนเลือก Exchange แล้ว Detail เปิดเต็มจอ
 *  ปุ่มย้อนกลับพาไปที่แถวเดิมใน Timeline จอกว้างไม่มีผลอะไร เพราะเห็นทั้งสองคอลัมน์อยู่แล้ว
 *  สอนแนวคิด: แยกหน้าที่ (separation of concerns) — JS บอกแค่ "เปิด Detail อยู่" ส่วน CSS ตัดสินว่าจอขนาดนี้ต้องซ่อนอะไร */
class StackedLayout {
  constructor(layout, backButton, timeline) {
    this.layout = layout;
    this.timeline = timeline;
    backButton.addEventListener("click", () => this.back());
  }

  openDetail() {
    this.layout.classList.add("detail-open");
  }

  back() {
    this.layout.classList.remove("detail-open");
    this.timeline.focusSelected();
  }
}

/** ประกอบทุกส่วนเข้าด้วยกัน */
function main() {
  const preferences = new Preferences(() => window.localStorage);
  new FontSizeControl(document.getElementById("font-smaller"), document.getElementById("font-bigger"), preferences);
  new ThemeSwitch(document.getElementById("theme-toggle"), preferences);
  new EthicsNotice(document.getElementById("ethics-banner"), document.getElementById("ethics-close"), preferences);
  const detail = new DetailView(document.getElementById("detail-body"));
  const flow = new FlowStrip(document.getElementById("flow-strip"), preferences, window.matchMedia("(prefers-reduced-motion: reduce)"));
  // callback นี้ถูกเรียกตอนผู้ใช้เลือกแถว ซึ่งเกิดหลังสร้าง follower (บรรทัดถัดไป) เสร็จแล้วเสมอ
  const timeline = new TimelineView(
    document.getElementById("timeline"),
    document.getElementById("timeline-empty"),
    (exchange, interaction, byUser) => {
      if (byUser) follower.stop(); // ผู้สอนเลือกเอง: โปรแกรมไม่แย่ง
      detail.show(exchange, interaction);
      flow.show(exchange, interaction);
      if (exchange === null) stacked.back(); // ไม่มีอะไรให้ดูแล้ว (เช่นหลังล้าง)
      else if (byUser) stacked.openDetail(); // โปรแกรมเลือกให้ (ตามคลิก) ไม่แย่งหน้า Timeline บนจอแคบ
    },
  );
  const stacked = new StackedLayout(document.querySelector(".layout"), document.getElementById("detail-back"), timeline);
  const newItems = new NewItemsNotice(document.querySelector(".timeline"), document.getElementById("new-items"), timeline);
  const follower = new ClickFollower(timeline, document.getElementById("follow-clicks"));
  const status = new StatusView(document.getElementById("chrome-status"));
  const chromeHelp = new ChromeHelpView(
    document.getElementById("chrome-setup"),
    document.getElementById("chrome-banner"),
  );
  const hiddenToggle = new HiddenToggle(document.getElementById("hidden-toggle"));
  document.getElementById("hidden-toggle").addEventListener("click", () => newItems.refresh());
  const controls = new CaptureControls(
    document.getElementById("pause-toggle"),
    document.getElementById("clear"),
    document.getElementById("paused-banner"),
  );
  new KeyboardShortcuts(timeline, controls);
  const filters = new FilterControls(document.getElementById("preset"), document.getElementById("custom-filters"));
  filters.load();
  const banner = document.getElementById("socket-banner");
  const showStatus = (data) => {
    status.show(data);
    chromeHelp.show(data);
    hiddenToggle.show(data);
    filters.show(data);
    controls.show(data);
    // CSS ใช้ค่านี้รอให้ครบ Correlation window ก่อนบอกว่าคลิกนี้ "ไม่มี API call"
    document.documentElement.style.setProperty("--correlation-window", `${data.correlation_window_ms}ms`);
  };

  const showExchange = (data) => {
    timeline.upsertExchange(data);
    newItems.refresh();
    follower.onExchange(data);
  };

  const handlers = {
    snapshot: (data) => {
      timeline.reset(data.interactions, data.exchanges);
      newItems.reset();
      follower.onSnapshot();
      showStatus(data.status);
    },
    "interaction.new": (data) => {
      timeline.upsertInteraction(data);
      newItems.onNewInteraction(data.id);
      follower.onNewInteraction(data);
    },
    "interaction.update": (data) => timeline.upsertInteraction(data),
    "exchange.new": showExchange,
    "exchange.update": showExchange,
    status: showStatus,
    cleared: () => {
      follower.stop();
      timeline.reset([], []);
      newItems.reset();
    },
  };

  const socket = new InspectorSocket(
    (message) => handlers[message.type]?.(message.data),
    (connected) => { banner.hidden = connected; },
  );
  socket.connect();
}

main();
