// click_hook.js — สคริปต์เล็กๆ ที่ ClickTracker ฉีดเข้าทุก Watched tab
// อ่านอย่างเดียว: ไม่เรียก preventDefault/stopPropagation และไม่อ่านค่าที่พิมพ์ในช่อง input
// Python แทนที่ __IGNORED_ORIGINS__ และ __REPORT_DOCUMENT__ ก่อนฉีด
(() => {
  const IGNORED_ORIGINS = __IGNORED_ORIGINS__;
  const REPORT_DOCUMENT = __REPORT_DOCUMENT__;
  if (window.top !== window || window.__wtiClickHookInstalled || IGNORED_ORIGINS.includes(location.origin)) return;
  window.__wtiClickHookInstalled = true;

  const MEANINGFUL = "button, a, [role=button], input, [onclick]";
  const LABEL_INPUT_TYPES = ["submit", "button", "reset"];
  const now = () => performance.timeOrigin + performance.now();

  /** ข้อความที่ผู้ใช้เห็นบนปุ่ม ช่อง input ทั่วไปคืนค่าว่างเสมอ (ห้ามส่งค่าที่พิมพ์ เช่นรหัสผ่าน) */
  function visibleText(element) {
    if (element instanceof HTMLInputElement) {
      return LABEL_INPUT_TYPES.includes(element.type) ? element.value : "";
    }
    if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return "";
    return (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
  }

  /** selector สั้นๆ ไม่เกิน 3 ชั้น เช่น "div.product-card > button.btn-cart" */
  function shortSelector(element) {
    const parts = [];
    for (let node = element; node instanceof Element && parts.length < 3; node = node.parentElement) {
      if (node.id) {
        parts.unshift(`${node.localName}#${CSS.escape(node.id)}`);
        break;
      }
      const firstClass = node.classList[0];
      parts.unshift(firstClass ? `${node.localName}.${CSS.escape(firstClass)}` : node.localName);
    }
    return parts.join(" > ");
  }

  function report(binding, data) {
    try {
      const send = window[binding];
      if (typeof send === "function") send(data);
    } catch (error) {
      // Inspector หลุดไปแล้ว: เว็บต้องทำงานต่อได้ตามปกติ
    }
  }

  document.addEventListener(
    "click",
    (event) => {
      if (!(event.target instanceof Element)) return;
      const element = event.target.closest(MEANINGFUL) || event.target;
      const link = element.closest("a[href]");
      report("__wtiReportClick", {
        tag: element.localName,
        text: visibleText(element).slice(0, 40),
        aria_label: element.getAttribute("aria-label"),
        element_id: element.id || null,
        classes: Array.from(element.classList).slice(0, 3),
        href: link ? link.href : null,
        selector: shortSelector(element),
        page_url: location.href,
        ts: now(),
      });
    },
    { capture: true, passive: true },
  );

  // Navigation = document ใหม่ของ main frame (pushState ไม่ได้รันสคริปต์นี้ใหม่ จึงไม่นับ)
  if (REPORT_DOCUMENT) report("__wtiReportNavigation", { url: location.href, ts: performance.timeOrigin });
  window.addEventListener("pageshow", (event) => {
    // กด back แล้ว Chrome ดึงหน้าเดิมจาก cache (bfcache): ไม่มี document ใหม่ แต่ผู้ใช้เห็นว่าเปลี่ยนหน้า
    if (event.persisted) report("__wtiReportNavigation", { url: location.href, ts: now() });
  });
})();
