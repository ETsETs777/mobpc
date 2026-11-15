/* Лендинг: статус агента и интерактивное демо «тачпад → курсор». */
"use strict";
(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- статус агента ----------
  fetch("/api/status").then((r) => (r.ok ? r.json() : Promise.reject())).then((s) => {
    $("#agent-status").innerHTML = `<span class="dot dot--ok" aria-hidden="true"></span><span>Агент работает на ${esc(s.hostname)}</span>`;
  }).catch(() => { /* страница открыта без агента */ });

  // ---------- демо ----------
  const desk = $("#desk"), cursor = $("#cursor"), pad = $("#pad"), finger = $("#finger");
  const win = $("#win"), winTitle = $("#win-title"), winBody = $("#win-body"), winClose = $("#win-close");
  if (!desk) return;

  const clock = $("#clock");
  const tickClock = () => { clock.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }); };
  tickClock();
  setInterval(tickClock, 30000);

  const WINDOWS = {
    olymp: { title: "Олимпиада", rows: [["mobpc — исходный код", "#f2b705"], ["Презентация.pptx", "#e8590c"], ["Речь.docx", "#3b5bdb"], ["Демо.mp4", "#7c8591"]] },
    term: { title: "PowerShell", term: ["PS C:\\> ipconfig", "IPv4-адрес . . . : 192.168.1.42", "PS C:\\> mobpc агент работает", "PS C:\\> _"] },
    bin: { title: "Корзина", rows: [["Корзина пуста", "transparent"]] },
  };

  // Позиция курсора в долях ширины и высоты рабочего стола
  let fx = 0.62, fy = 0.58;
  let userTouched = false;

  function deskRect() { return desk.getBoundingClientRect(); }
  function place() {
    const r = deskRect();
    cursor.style.transform = `translate(${fx * r.width - 2}px, ${fy * r.height - 2}px)`;
    hover();
  }
  function pointAbs() {
    const r = deskRect();
    return { x: r.left + fx * r.width, y: r.top + fy * r.height };
  }
  function hit(el) {
    if (!el || el.offsetParent === null) return false;
    const p = pointAbs(), r = el.getBoundingClientRect();
    return p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom;
  }
  function hover() {
    for (const ic of desk.querySelectorAll(".desk-icon")) ic.classList.toggle("is-hover", hit(ic));
    winClose.classList.toggle("is-hover", !win.hidden && hit(winClose));
  }
  function openWin(key) {
    const w = WINDOWS[key];
    winTitle.textContent = w.title;
    if (w.term) {
      winBody.style.background = "#14171b";
      winBody.innerHTML = w.term.map((l) => `<div style="color:#d6dde5;font-family:var(--font-mono);padding:2px 4px">${esc(l)}</div>`).join("");
    } else {
      winBody.style.background = "";
      winBody.innerHTML = w.rows.map(([t, c]) => `<div class="win__row" style="--row:${c}">${esc(t)}</div>`).join("");
    }
    win.hidden = false;
    win.classList.remove("is-opening");
    void win.offsetWidth;
    win.classList.add("is-opening");
  }
  function clickAt() {
    if (!win.hidden && hit(winClose)) { win.hidden = true; hover(); return; }
    if (!win.hidden && hit(win)) return;
    let opened = false;
    for (const ic of desk.querySelectorAll(".desk-icon")) {
      const on = hit(ic);
      ic.classList.toggle("is-active", on);
      if (on) { openWin(ic.dataset.open); opened = true; }
    }
    if (!opened) for (const ic of desk.querySelectorAll(".desk-icon")) ic.classList.remove("is-active");
  }
  function moveBy(dx, dy) {
    const r = deskRect(), pr = pad.getBoundingClientRect();
    const k = 1.5 * (r.width / pr.width);
    fx = Math.min(0.985, Math.max(0, fx + (dx * k) / r.width));
    fy = Math.min(0.97, Math.max(0, fy + (dy * k) / r.height));
    place();
  }
  function showFinger(cx, cy) {
    const pr = pad.getBoundingClientRect();
    finger.style.transform = `translate(${cx - pr.left}px, ${cy - pr.top}px)`;
    finger.classList.add("is-on");
  }

  // Реальное управление: мышь или палец по тачпаду
  let last = null, start = null;
  pad.addEventListener("pointerdown", (e) => {
    userTouched = true;
    pad.setPointerCapture(e.pointerId);
    last = { x: e.clientX, y: e.clientY };
    start = { x: e.clientX, y: e.clientY, t: Date.now() };
    showFinger(e.clientX, e.clientY);
  });
  pad.addEventListener("pointermove", (e) => {
    if (!last) return;
    moveBy(e.clientX - last.x, e.clientY - last.y);
    last = { x: e.clientX, y: e.clientY };
    showFinger(e.clientX, e.clientY);
  });
  const end = (e) => {
    if (!last) return;
    if (e.type === "pointerup" && Date.now() - start.t < 300 && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 8) clickAt();
    last = null;
    finger.classList.remove("is-on");
  };
  pad.addEventListener("pointerup", end);
  pad.addEventListener("pointercancel", end);
  window.addEventListener("resize", place);
  place();

  // Один показ при загрузке: «невидимый палец» ведёт курсор к папке и открывает её
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) return;
  const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
  function animate(from, to, ms, onStep) {
    return new Promise((resolve) => {
      const t0 = performance.now();
      const step = (now) => {
        if (userTouched) { resolve(false); return; }
        const t = Math.min(1, (now - t0) / ms);
        onStep(from + (to - from) * ease(t), t);
        t < 1 ? requestAnimationFrame(step) : resolve(true);
      };
      requestAnimationFrame(step);
    });
  }
  async function ghost() {
    await new Promise((r) => setTimeout(r, 900));
    if (userTouched) return;
    const target = desk.querySelector('[data-open="olymp"]');
    const r = deskRect(), tr = target.getBoundingClientRect();
    const tx = (tr.left + tr.width / 2 - r.left) / r.width, ty = (tr.top + tr.height * 0.4 - r.top) / r.height;
    const sx = fx, sy = fy;
    const pr = pad.getBoundingClientRect();
    const k = 1.5 * (r.width / pr.width);
    const p0 = { x: pr.left + pr.width * 0.72, y: pr.top + pr.height * 0.7 };
    const p1 = { x: p0.x + ((tx - sx) * r.width) / k, y: p0.y + ((ty - sy) * r.height) / k };
    const ok = await animate(0, 1, 1500, (v) => {
      fx = sx + (tx - sx) * v;
      fy = sy + (ty - sy) * v;
      place();
      showFinger(p0.x + (p1.x - p0.x) * v, p0.y + (p1.y - p0.y) * v);
    });
    if (!ok) return;
    await new Promise((res) => setTimeout(res, 250));
    if (userTouched) return;
    finger.style.boxShadow = "0 0 0 12px rgba(242,183,5,.25)";
    clickAt();
    setTimeout(() => { finger.classList.remove("is-on"); finger.style.boxShadow = ""; }, 350);
  }
  ghost();
})();
