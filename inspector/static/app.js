// Web Traffic Inspector — ฝั่งหน้าเว็บ (vanilla JS ไม่มี build step)
// แบ่งเป็น class เล็กๆ ล้อกับฝั่ง Python: InspectorSocket ≈ Broadcaster, TimelineView ≈ EventStore
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

/** แสดงรายการ Exchange ใหม่สุดอยู่บน
 *  สอนแนวคิด: state ใน object — จำว่า Exchange ไหนวาดไว้แล้ว (Map) เพื่ออัปเดตแถวเดิม */
class TimelineView {
  constructor(listElement, emptyElement) {
    this.list = listElement;
    this.empty = emptyElement;
    this.rows = new Map(); // exchange id → <li>
  }

  reset(exchanges) {
    this.list.replaceChildren();
    this.rows.clear();
    exchanges.forEach((exchange) => this.upsert(exchange));
    this.updateEmpty();
  }

  upsert(exchange) {
    const row = this.renderRow(exchange);
    const existing = this.rows.get(exchange.id);
    if (existing) {
      existing.replaceWith(row);
    } else {
      this.list.prepend(row);
    }
    this.rows.set(exchange.id, row);
    this.updateEmpty();
  }

  updateEmpty() {
    this.empty.hidden = this.rows.size > 0;
  }

  renderRow(exchange) {
    const li = document.createElement("li");
    li.className = "exchange";
    li.dataset.id = exchange.id;
    li.append(
      badge(exchange.request.method, `method-${exchange.request.method}`),
      textSpan("path", exchange.request.path, exchange.request.url),
      redactionFlags(exchange),
      statusBadge(exchange),
      textSpan("ms", exchange.duration_ms == null ? "" : `${Math.round(exchange.duration_ms)} ms`),
    );
    return li;
  }
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
    this.setup.hidden = connected;
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
    document.getElementById("exchange-list"),
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
      timeline.reset(data.exchanges);
      showStatus(data.status);
    },
    "exchange.new": (data) => timeline.upsert(data),
    "exchange.update": (data) => timeline.upsert(data),
    status: showStatus,
  };

  const socket = new InspectorSocket(
    (message) => handlers[message.type]?.(message.data),
    (connected) => { banner.hidden = connected; },
  );
  socket.connect();
}

main();
