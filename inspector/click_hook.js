// click_hook.js — สคริปต์เล็กๆ ที่ ClickTracker ฉีดเข้าทุก Watched tab
// อ่านอย่างเดียว: ไม่เรียก preventDefault/stopPropagation และไม่อ่านค่าที่พิมพ์ในช่อง input
// Python แทนที่ค่าตัวพิมพ์ใหญ่ที่ขึ้นต้นด้วย __ ก่อนฉีด (ดู hook_script ใน click_tracker.py)
// ไม่ส่งเวลา: Python ประทับเวลาเองตอนรับ เพื่อให้เทียบกับเวลาของ Exchange ได้ (docs/adr/0001)
(() => {
  const IGNORED_ORIGINS = __IGNORED_ORIGINS__;
  const REPORT_DOCUMENT = __REPORT_DOCUMENT__;
  const CLICK_BINDING = __CLICK_BINDING__;
  const NAVIGATION_BINDING = __NAVIGATION_BINDING__;
  const MAX_TEXT = __MAX_TEXT__;
  const MAX_CLASSES = __MAX_CLASSES__;
  if (window.top !== window || window.__wtiClickHookInstalled || IGNORED_ORIGINS.includes(location.origin)) return;
  window.__wtiClickHookInstalled = true;

  const MEANINGFUL = "button, a, [role=button], input, [onclick]";
  const LABEL_INPUT_TYPES = ["submit", "button", "reset"];

  /** ข้อความที่ผู้ใช้เห็นบนปุ่ม ช่องที่พิมพ์ได้คืนค่าว่างเสมอ (ห้ามส่งค่าที่พิมพ์ เช่นรหัสผ่าน หรือร่างอีเมล) */
  function visibleText(element) {
    if (element instanceof HTMLElement && element.isContentEditable) return "";
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

  // ฟังที่ window ช่วง capture: ได้คลิกก่อน listener ของเว็บทุกตัว
  window.addEventListener(
    "click",
    (event) => {
      if (!(event.target instanceof Element)) return;
      const element = event.target.closest(MEANINGFUL) || event.target;
      const link = element.closest("a[href]");
      report(CLICK_BINDING, {
        tag: element.localName,
        text: visibleText(element).slice(0, MAX_TEXT),
        aria_label: element.getAttribute("aria-label"),
        element_id: element.id || null,
        classes: Array.from(element.classList).slice(0, MAX_CLASSES),
        href: link ? link.href : null,
        selector: shortSelector(element),
        page_url: location.href,
      });
    },
    { capture: true, passive: true },
  );

  // Navigation = document ใหม่ของ main frame (pushState ไม่ได้รันสคริปต์นี้ใหม่ จึงไม่นับ)
  if (REPORT_DOCUMENT) report(NAVIGATION_BINDING, { url: location.href });
  window.addEventListener("pageshow", (event) => {
    // กด back แล้ว Chrome ดึงหน้าเดิมจาก cache (bfcache): ไม่มี document ใหม่ แต่ผู้ใช้เห็นว่าเปลี่ยนหน้า
    if (event.persisted) report(NAVIGATION_BINDING, { url: location.href });
  });
})();
