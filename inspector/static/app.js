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

/** Timeline: การ์ด Interaction ใหม่สุดอยู่บน แต่ละการ์ดมีแถว Exchange อยู่ข้างใน
 *  สอนแนวคิด: state ใน object — จำว่าการ์ดและแถวไหนวาดไว้แล้ว (Map) เพื่ออัปเดตที่เดิม ไม่วาดใหม่ทั้งหน้า */
class TimelineView {
  constructor(listElement, emptyElement) {
    this.list = listElement;
    this.empty = emptyElement;
    this.cards = new Map(); // interaction id → <li class="card">
    this.rows = new Map(); // exchange id → <li class="exchange">
  }

  reset(interactions, exchanges) {
    this.list.replaceChildren();
    this.cards.clear();
    this.rows.clear();
    interactions.forEach((interaction) => this.upsertInteraction(interaction, false));
    exchanges.forEach((exchange) => this.upsertExchange(exchange));
    this.updateEmpty();
  }

  /** การ์ดใหม่ขึ้นบนสุดพร้อมไฮไลต์ การ์ดเดิมเปลี่ยนแค่หัวการ์ด ไม่ย้ายตำแหน่ง */
  upsertInteraction(interaction, highlight = true) {
    const existing = this.cards.get(interaction.id);
    if (existing) {
      existing.querySelector(".card-head").replaceWith(cardHead(interaction));
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
    const row = renderExchangeRow(exchange);
    const existing = this.rows.get(exchange.id);
    if (existing) {
      existing.replaceWith(row);
    } else {
      card.querySelector(".exchange-list").append(row);
      card.classList.remove("is-empty");
    }
    this.rows.set(exchange.id, row);
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
  card.className = `card kind-${interaction.kind} is-empty`;
  card.dataset.id = interaction.id;
  const rows = document.createElement("ol");
  rows.className = "exchange-list";
  card.append(cardHead(interaction), rows);
  if (interaction.kind === "click") {
    card.append(textSpan("no-calls", "ไม่มี API call — ปุ่มนี้ทำงานในเบราว์เซอร์อย่างเดียว"));
  }
  return card;
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

function renderExchangeRow(exchange) {
  const li = document.createElement("li");
  li.className = "exchange";
  li.dataset.id = exchange.id;
  li.append(
    badge(exchange.request.method, `method-${exchange.request.method}`),
    // LRM ครอบไว้ เพื่อไม่ให้ direction: rtl (ที่ใช้ตัด path จากซ้าย) ย้าย "/" ไปไว้ท้าย
    textSpan("path", `\u200e${exchange.request.path}\u200e`, exchange.request.url),
    redactionFlags(exchange),
    statusBadge(exchange),
    textSpan("ms", exchange.duration_ms == null ? "" : `${Math.round(exchange.duration_ms)} ms`),
  );
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

/** ประกอบทุกส่วนเข้าด้วยกัน */
function main() {
  const timeline = new TimelineView(
    document.getElementById("timeline"),
    document.getElementById("timeline-empty"),
  );
  const status = new StatusView(document.getElementById("chrome-status"));
  const chromeHelp = new ChromeHelpView(
    document.getElementById("chrome-setup"),
    document.getElementById("chrome-banner"),
  );
  const banner = document.getElementById("socket-banner");
  const showStatus = (data) => {
    status.show(data);
    chromeHelp.show(data);
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
