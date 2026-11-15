/* mobpc — веб-пульт. Без фреймворков: открывается на любом телефоне по QR-коду. */
"use strict";
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const TOKEN_KEY = "mobpc.token";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватный режим */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const vibrate = (ms) => { try { navigator.vibrate && navigator.vibrate(ms); } catch { /* ignore */ } };
  // Подключение через интернет (туннель или Tailscale), а не по домашнему Wi-Fi
  const IS_REMOTE = location.protocol === "https:" || /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(location.hostname);

  function fmtBytes(n) {
    if (!n && n !== 0) return "";
    const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${u[i]}`;
  }
  function fmtUptime(sec) {
    const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
    if (d) return `${d} д ${h} ч`;
    if (h) return `${h} ч ${m} мин`;
    return `${m} мин`;
  }

  // ---------- тост и нижний лист ----------
  let toastTimer;
  function toast(msg, isError = false, ms = 2600) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " toast--error" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, ms);
  }
  const fail = (e) => toast(e && e.message ? e.message : String(e), true);

  function sheet(title, text, actions) {
    return new Promise((resolve) => {
      const root = $("#sheet");
      $("#sheet-title").textContent = title;
      $("#sheet-text").textContent = text || "";
      const box = $("#sheet-actions");
      box.innerHTML = "";
      const done = (v) => { root.hidden = true; root.onclick = null; resolve(v); };
      for (const a of actions) {
        const b = document.createElement("button");
        b.className = "key " + (a.cls || "key--light");
        b.textContent = a.label;
        b.onclick = (e) => { e.stopPropagation(); done(a.value); };
        box.appendChild(b);
      }
      root.onclick = (e) => { if (e.target === root) done(null); };
      root.hidden = false;
      box.querySelector("button")?.focus();
    });
  }
  const ask = (title, ok = "Да", danger = true) =>
    sheet(title, "", [{ label: ok, cls: danger ? "key--system" : "key--screen", value: true }, { label: "Отмена", value: false }]);

  // ---------- клиент WebSocket ----------
  class Client {
    constructor(token) {
      this.token = token;
      this.ws = null;
      this.pending = new Map();
      this.state = "idle";
      this.retry = 0;
      this.closedByUser = false;
      this.info = null;
      this.onState = () => {};
      this.onEvent = () => {};
      this.onUnauthorized = () => {};
    }
    setState(s) { this.state = s; this.onState(s); }
    connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(this.token)}`);
      this.ws = ws;
      this.setState(this.retry ? "reconnecting" : "connecting");
      ws.onmessage = (e) => this.handle(e.data);
      ws.onclose = (e) => {
        if (this.ws === ws) this.ws = null;
        for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new Error("Связь с компьютером прервалась")); }
        this.pending.clear();
        if (e.code === 4401) { this.setState("unauthorized"); this.onUnauthorized(); return; }
        if (this.closedByUser) return;
        this.setState("reconnecting");
        const delay = Math.min(800 * 2 ** this.retry, 8000);
        this.retry++;
        setTimeout(() => { if (!this.closedByUser) this.connect(); }, delay);
      };
    }
    handle(raw) {
      let m;
      try { m = JSON.parse(raw); } catch { return; }
      if (m.type === "connected") { this.info = m.data; this.retry = 0; this.setState("connected"); return; }
      if ("ok" in m) {
        const p = this.pending.get(m.id);
        if (!p) return;
        this.pending.delete(m.id);
        clearTimeout(p.timer);
        m.ok ? p.resolve(m.data || {}) : p.reject(new Error(m.error || "Команда не выполнена"));
        return;
      }
      const p = m.id && this.pending.get(m.id);
      if (p && p.onEvent) p.onEvent(m);
      this.onEvent(m);
    }
    get ready() { return this.ws && this.ws.readyState === 1 && this.state === "connected"; }
    send(type, payload = {}, { timeout = 30000, onEvent } = {}) {
      return new Promise((resolve, reject) => {
        if (!this.ready) { reject(new Error("Нет связи с компьютером")); return; }
        const id = uid();
        const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("Компьютер не ответил вовремя")); }, timeout);
        this.pending.set(id, { resolve, reject, timer, onEvent });
        this.ws.send(JSON.stringify({ id, type, payload }));
      });
    }
    /** Без ожидания ответа — для частых команд мыши. */
    fire(type, payload = {}) {
      if (this.ready) this.ws.send(JSON.stringify({ id: null, type, payload }));
    }
    close() { this.closedByUser = true; if (this.ws) this.ws.close(); }
  }

  let client = null;

  // ---------- привязка ----------
  function deviceName() {
    const ua = navigator.userAgent;
    let os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android"
      : /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "Устройство";
    const model = ua.match(/Android [\d.]+; ([^;)]+)/);
    if (model && model[1].trim() !== "K") os = model[1].trim();
    const br = /YaBrowser/.test(ua) ? "Яндекс Браузер" : /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera"
      : /Firefox|FxiOS/.test(ua) ? "Firefox" : /SamsungBrowser/.test(ua) ? "Samsung Internet"
      : /CriOS|Chrome/.test(ua) ? "Chrome" : /Safari/.test(ua) ? "Safari" : "браузер";
    return `${os}, ${br}`;
  }

  async function pair(code) {
    const r = await fetch("/api/pairing/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, device_name: deviceName() }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || "Не удалось подключиться");
    store.set(TOKEN_KEY, j.token);
    return j;
  }

  function showPair(error) {
    $("#shell").hidden = true;
    $("#pair").hidden = false;
    const err = $("#pair-error");
    err.hidden = !error;
    err.textContent = error || "";
    $("#pair-submit").disabled = false;
    $("#pair-submit").textContent = "Подключить";
  }

  const codeInput = $("#pair-code");
  codeInput.addEventListener("input", () => {
    const raw = codeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
    codeInput.value = raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
  });
  $("#pair-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#pair-submit");
    btn.disabled = true;
    btn.textContent = "Подключаем…";
    try {
      const j = await pair(codeInput.value);
      start(j.hostname);
    } catch (err) {
      showPair(err.message);
    }
  });

  // ---------- запуск ----------
  function start(hostname) {
    $("#pair").hidden = true;
    $("#shell").hidden = false;
    if (hostname) $("#pc-name").textContent = hostname;
    if (client) client.close();
    client = new Client(store.get(TOKEN_KEY));
    client.onState = renderState;
    client.onEvent = onEvent;
    client.onUnauthorized = () => {
      store.del(TOKEN_KEY);
      showPair("Компьютер больше не принимает этот телефон: доступ отключили или код устарел. Получите новый код на странице «Подключить телефон».");
    };
    client.connect();
    switchTab(currentTab);
  }

  function renderState(s) {
    const dot = $("#conn-dot"), text = $("#conn-text");
    dot.className = "dot " + (s === "connected" ? "dot--ok" : s === "unauthorized" ? "dot--off" : "dot--warn");
    text.textContent = {
      connecting: "Подключение…",
      reconnecting: "Связь потеряна, переподключаемся…",
      connected: IS_REMOTE ? "Подключено через интернет" : "Подключено",
      unauthorized: "Нет доступа",
    }[s] || "";
    if (s === "connected") {
      if (client.info && client.info.hostname) $("#pc-name").textContent = client.info.hostname;
      stream.sync(true);
      panelHooks[currentTab]?.show?.();
    }
  }

  function onEvent(m) {
    if (m.type === "screen.stream") stream.frame(m.data);
  }

  // ---------- вкладки ----------
  let currentTab = "screen";
  const panelHooks = {};
  function switchTab(name) {
    if (panelHooks[currentTab] && currentTab !== name) panelHooks[currentTab].hide?.();
    currentTab = name;
    for (const t of $$(".tab")) t.classList.toggle("is-on", t.dataset.tab === name);
    for (const p of $$(".panel")) p.hidden = p.dataset.panel !== name;
    stream.sync();
    if (client && client.ready) panelHooks[name]?.show?.();
  }
  for (const t of $$(".tab")) t.addEventListener("click", () => switchTab(t.dataset.tab));
  document.addEventListener("visibilitychange", () => {
    if (!client || !client.ready) return;
    stream.sync();
    if (document.hidden) panelHooks[currentTab]?.hide?.();
    else panelHooks[currentTab]?.show?.();
  });

  // ---------- ЭКРАН: просмотр с управлением касаниями ----------
  let tapButton = "left";

  class Viewer {
    constructor(root, { main = false } = {}) {
      this.root = root;
      this.main = main;
      this.stage = $(".viewer__stage", root);
      this.img = $(".viewer__img", root);
      this.empty = $(".viewer__empty", root);
      this.info = null;
      this.zoom = { s: 1, x: 0, y: 0 };
      this.pts = new Map();
      this.gesture = null;
      this.lastTap = null;
      this.bind();
      const strip = $(".viewer__scroll", root);
      if (strip) this.bindScroll(strip);
    }
    show(d, src) {
      this.info = d;
      this.img.src = src;
      this.empty.hidden = true;
    }
    toScreen(cx, cy) {
      const r = this.img.getBoundingClientRect();
      if (!this.info || !r.width) return null;
      const rx = (cx - r.left) / r.width, ry = (cy - r.top) / r.height;
      if (rx < 0 || rx > 1 || ry < 0 || ry > 1) return null;
      return { x: Math.round(this.info.left + rx * this.info.width), y: Math.round(this.info.top + ry * this.info.height) };
    }
    ring(cx, cy, right) {
      const vr = this.root.getBoundingClientRect();
      const el = document.createElement("span");
      el.className = "tap-ring" + (right ? " tap-ring--right" : "");
      el.style.left = cx - vr.left + "px";
      el.style.top = cy - vr.top + "px";
      this.root.appendChild(el);
      setTimeout(() => el.remove(), 500);
    }
    click(cx, cy, button) {
      let p = this.toScreen(cx, cy);
      if (!p || !client) return;
      // Второе касание рядом и быстро — в ту же точку, чтобы Windows засчитала двойной клик
      const now = Date.now();
      const lt = this.lastTap;
      if (lt && now - lt.t < 400 && Math.hypot(cx - lt.cx, cy - lt.cy) < 24 && button === lt.button) p = lt.p;
      this.lastTap = { t: now, cx, cy, p, button };
      this.ring(cx, cy, button === "right");
      client.send("mouse.click", { x: p.x, y: p.y, button }).catch(fail);
    }
    applyZoom() {
      this.stage.style.transform = this.zoom.s === 1 ? "" : `translate(${this.zoom.x}px, ${this.zoom.y}px) scale(${this.zoom.s})`;
      if (this.main) $("#zoom-reset").hidden = this.zoom.s === 1;
    }
    resetZoom() { this.zoom = { s: 1, x: 0, y: 0 }; this.applyZoom(); }
    bind() {
      const root = this.root;
      root.addEventListener("pointerdown", (e) => {
        if (e.target.closest(".viewer__scroll")) return;
        root.setPointerCapture(e.pointerId);
        this.pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (e.pointerType === "mouse") {
          this.gesture = { type: "mouse", x0: e.clientX, y0: e.clientY, button: e.button === 2 ? "right" : "left" };
          return;
        }
        if (this.pts.size === 1) {
          const g = { type: "tap", x0: e.clientX, y0: e.clientY, moved: false, zx: this.zoom.x, zy: this.zoom.y };
          g.timer = setTimeout(() => {
            if (this.gesture === g && !g.moved) { g.type = "done"; vibrate(20); this.click(g.x0, g.y0, "right"); }
          }, 550);
          this.gesture = g;
        } else if (this.pts.size === 2) {
          if (this.gesture && this.gesture.timer) clearTimeout(this.gesture.timer);
          const [a, b] = [...this.pts.values()];
          const vr = root.getBoundingClientRect();
          this.gesture = {
            type: "pinch", d0: Math.hypot(a.x - b.x, a.y - b.y) || 1,
            mx: (a.x + b.x) / 2 - vr.left, my: (a.y + b.y) / 2 - vr.top, s0: this.zoom.s, x0: this.zoom.x, y0: this.zoom.y,
          };
        }
      });
      root.addEventListener("pointermove", (e) => {
        if (!this.pts.has(e.pointerId)) return;
        this.pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        const g = this.gesture;
        if (!g) return;
        if (g.type === "tap") {
          const dx = e.clientX - g.x0, dy = e.clientY - g.y0;
          if (Math.hypot(dx, dy) > 10) g.moved = true;
          if (g.moved && this.zoom.s > 1) { this.zoom.x = g.zx + dx; this.zoom.y = g.zy + dy; this.applyZoom(); }
        } else if (g.type === "pinch" && this.pts.size >= 2) {
          const [a, b] = [...this.pts.values()];
          const vr = root.getBoundingClientRect();
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          const mx = (a.x + b.x) / 2 - vr.left, my = (a.y + b.y) / 2 - vr.top;
          const s = Math.min(5, Math.max(1, g.s0 * d / g.d0));
          const px = (g.mx - g.x0) / g.s0, py = (g.my - g.y0) / g.s0;
          this.zoom = s === 1 ? { s: 1, x: 0, y: 0 } : { s, x: mx - px * s, y: my - py * s };
          this.applyZoom();
        }
      });
      const end = (e) => {
        if (!this.pts.has(e.pointerId)) return;
        this.pts.delete(e.pointerId);
        const g = this.gesture;
        if (!g) return;
        if (g.type === "mouse" && e.type === "pointerup") {
          if (Math.hypot(e.clientX - g.x0, e.clientY - g.y0) < 6) this.click(e.clientX, e.clientY, g.button);
          this.gesture = null;
        } else if (g.type === "tap") {
          clearTimeout(g.timer);
          if (!g.moved && e.type === "pointerup") this.click(g.x0, g.y0, this.main ? tapButton : "left");
          this.gesture = null;
        } else if (this.pts.size === 0) {
          this.gesture = null;
        }
      };
      root.addEventListener("pointerup", end);
      root.addEventListener("pointercancel", end);
      root.addEventListener("contextmenu", (e) => e.preventDefault());
      root.addEventListener("wheel", (e) => {
        e.preventDefault();
        const p = this.toScreen(e.clientX, e.clientY);
        client?.fire("mouse.scroll", { ...(p || {}), dy: e.deltaY > 0 ? -2 : 2 });
      }, { passive: false });
    }
    bindScroll(strip) {
      let y = null, acc = 0;
      strip.addEventListener("pointerdown", (e) => { strip.setPointerCapture(e.pointerId); y = e.clientY; acc = 0; });
      strip.addEventListener("pointermove", (e) => {
        if (y === null) return;
        acc += e.clientY - y;
        y = e.clientY;
        while (Math.abs(acc) >= 22) {
          const dir = Math.sign(acc);
          client?.fire("mouse.scroll", { dy: dir });
          acc -= dir * 22;
        }
      });
      strip.addEventListener("pointerup", () => { y = null; });
      strip.addEventListener("pointercancel", () => { y = null; });
    }
  }

  const mainViewer = new Viewer($("#viewer-main"), { main: true });
  const miniViewers = {};
  for (const box of $$(".mini")) miniViewers[box.dataset.mini] = new Viewer($(".viewer", box));

  // ---------- трансляция: одна на все окна просмотра ----------
  const stream = (() => {
    const PRESETS = {
      sharp: { fps: 8, quality: 72, max_width: 1600 },
      balanced: { fps: 10, quality: 55, max_width: 1280 },
      fast: { fps: 15, quality: 40, max_width: 960 },
      internet: { fps: 6, quality: 38, max_width: 960 },
    };
    const quality = $("#quality");
    quality.value = store.get("mobpc.quality") || (IS_REMOTE ? "internet" : "balanced");
    const hud = $(".viewer__hud", $("#viewer-main"));
    let mainWanted = true;
    const miniOn = { pad: store.get("mobpc.mini.pad") !== "0", keys: store.get("mobpc.mini.keys") !== "0" };
    let running = false, runningPreset = null;
    let frames = 0, bytes = 0, lastHud = performance.now();

    function needed() {
      if (!client || !client.ready || document.hidden) return false;
      if (currentTab === "screen") return mainWanted;
      if (currentTab in miniOn) return miniOn[currentTab];
      return false;
    }
    async function sync(force = false) {
      const want = needed();
      const preset = quality.value;
      if (want && (!running || force || runningPreset !== preset)) {
        running = true;
        runningPreset = preset;
        try { await client.send("screen.stream", { action: "start", ...(PRESETS[preset] || PRESETS.balanced) }); }
        catch (e) { running = false; fail(e); }
      } else if (!want && running) {
        running = false;
        try { await client.send("screen.stream", { action: "stop" }); } catch { /* ignore */ }
      }
      renderToggles();
    }
    function frame(d) {
      const src = "data:image/jpeg;base64," + d.image;
      if (currentTab === "screen") mainViewer.show(d, src);
      else if (miniViewers[currentTab]) miniViewers[currentTab].show(d, src);
      frames++;
      bytes += d.image.length * 0.75;
      const now = performance.now();
      if (now - lastHud > 1000) {
        const fps = frames * 1000 / (now - lastHud);
        hud.textContent = `${fps.toFixed(0)} к/с, ${fmtBytes(bytes / Math.max(frames, 1))} на кадр`;
        frames = 0; bytes = 0; lastHud = now;
      }
    }
    function renderToggles() {
      const b = $("#stream-toggle");
      b.querySelector("use").setAttribute("href", mainWanted ? "#i-stop" : "#i-play");
      b.querySelector("span").textContent = mainWanted ? "Пауза" : "Смотреть";
      hud.hidden = !(running && currentTab === "screen");
      for (const [tab, on] of Object.entries(miniOn)) {
        const box = $(`.mini[data-mini="${tab}"]`);
        if (box) box.hidden = !on;
        const t = $(`[data-mini-toggle="${tab}"]`);
        if (t) { t.classList.toggle("is-on", on); t.setAttribute("aria-pressed", on); }
      }
    }
    $("#stream-toggle").addEventListener("click", () => { mainWanted = !mainWanted; sync(); });
    quality.addEventListener("change", () => { store.set("mobpc.quality", quality.value); sync(true); });
    for (const t of $$("[data-mini-toggle]")) {
      t.addEventListener("click", () => {
        const tab = t.dataset.miniToggle;
        miniOn[tab] = !miniOn[tab];
        store.set(`mobpc.mini.${tab}`, miniOn[tab] ? "1" : "0");
        sync();
      });
    }
    renderToggles();
    return { sync, frame };
  })();

  for (const b of $$(".seg__btn")) {
    b.addEventListener("click", () => {
      tapButton = b.dataset.tap;
      for (const x of $$(".seg__btn")) { x.classList.toggle("is-on", x === b); x.setAttribute("aria-checked", x === b); }
    });
  }
  $("#zoom-reset").addEventListener("click", () => mainViewer.resetZoom());

  // ---------- КЛАВИАТУРА (общая для вкладки «Ввод» и панели под экраном) ----------
  const keyboard = (() => {
    const mods = new Set();
    const MOD_LABELS = [["ctrl", "Ctrl"], ["alt", "Alt"], ["shift", "Shift"], ["win", "Win"]];
    // Кириллица → клавиша латинской раскладки на том же месте (для Ctrl+С = Ctrl+C)
    const RU = "йцукенгшщзхъфывапролджэячсмитьбю", EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.";
    const toLatin = (ch) => { const i = RU.indexOf(ch.toLowerCase()); return i >= 0 ? EN[i] : ch.toLowerCase(); };
    const instances = [];
    let queue = Promise.resolve();
    const enqueue = (fn) => { queue = queue.then(fn).catch(fail); };

    function renderMods() {
      for (const inst of instances) {
        for (const b of $$("[data-mod]", inst)) {
          const on = mods.has(b.dataset.mod);
          b.classList.toggle("is-on", on);
          b.setAttribute("aria-pressed", on);
        }
      }
    }
    function press(key) {
      if (mods.size) {
        const keys = [...mods, key];
        mods.clear();
        renderMods();
        enqueue(() => client.send("keyboard.hotkey", { keys }));
      } else {
        enqueue(() => client.send("keyboard.key", { key }));
      }
      vibrate(8);
    }
    function btn(label, cls, onClick, extra = {}) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "key " + cls;
      b.textContent = label;
      Object.assign(b, extra);
      b.addEventListener("click", onClick);
      return b;
    }

    function build(root, { compact }) {
      root.innerHTML = "";
      root.classList.add("kbd", compact ? "kbd--compact" : "kbd--full");
      const modRow = document.createElement("div");
      modRow.className = "kbd__mods";
      for (const [m, label] of MOD_LABELS) {
        const b = btn(label, "key--light key--mod", () => {
          mods.has(m) ? mods.delete(m) : mods.add(m);
          renderMods();
        });
        b.dataset.mod = m;
        b.setAttribute("aria-pressed", "false");
        modRow.appendChild(b);
      }
      root.appendChild(modRow);

      const line = document.createElement("div");
      line.className = "kbd__line";
      const input = document.createElement("input");
      input.className = "input kbd__input";
      input.placeholder = compact ? "Печатайте — текст сразу появится на ПК" : "Нажмите и печатайте — текст сразу на ПК";
      input.setAttribute("autocomplete", "off");
      input.setAttribute("autocorrect", "off");
      input.setAttribute("autocapitalize", "off");
      input.spellcheck = false;
      input.setAttribute("aria-label", "Печать на компьютере");
      line.appendChild(input);
      line.appendChild(btn("⌫", "key--light key--icon", () => press("backspace"), { title: "Стереть", ariaLabel: "Стереть" }));
      line.appendChild(btn("⏎", "key--input key--icon", () => press("enter"), { title: "Enter", ariaLabel: "Enter" }));
      root.appendChild(line);

      const special = [["Esc", "esc"], ["Tab", "tab"], ["Del", "delete"], ["Пробел", "space"], ["Home", "home"], ["End", "end"], ["PgUp", "page_up"], ["PgDn", "page_down"]];
      const row = document.createElement("div");
      row.className = "kbd__row";
      for (const [label, key] of special) row.appendChild(btn(label, "key--light", () => press(key)));
      if (compact) for (const [label, key] of [["←", "left"], ["↑", "up"], ["↓", "down"], ["→", "right"]]) row.appendChild(btn(label, "key--light", () => press(key)));
      root.appendChild(row);

      if (!compact) {
        const pad = document.createElement("div");
        pad.className = "kbd__arrows";
        pad.appendChild(btn("↑", "key--light a-up", () => press("up"), { ariaLabel: "Вверх" }));
        pad.appendChild(btn("←", "key--light a-left", () => press("left"), { ariaLabel: "Влево" }));
        pad.appendChild(btn("↓", "key--light a-down", () => press("down"), { ariaLabel: "Вниз" }));
        pad.appendChild(btn("→", "key--light a-right", () => press("right"), { ariaLabel: "Вправо" }));
        root.appendChild(pad);
        const frow = document.createElement("div");
        frow.className = "kbd__row kbd__row--f";
        for (let i = 1; i <= 12; i++) frow.appendChild(btn(`F${i}`, "key--light", () => press(`f${i}`)));
        root.appendChild(frow);
      }

      bindLive(input);
      instances.push(root);
      renderMods();
    }

    // Живой ввод: сравниваем старое и новое значение поля — так работают автозамена,
    // составной ввод Gboard/SwiftKey и кириллица.
    function bindLive(input) {
      let prev = "";
      const sync = () => {
        const now = input.value;
        if (mods.size) {
          // С зажатым Ctrl/Alt буква — это сочетание, а не текст
          const added = now.length > prev.length ? now.slice(-1) : "";
          input.value = prev;
          if (added && added.trim()) press(toLatin(added));
          return;
        }
        let i = 0;
        while (i < prev.length && i < now.length && prev[i] === now[i]) i++;
        const removed = prev.length - i;
        const added = now.slice(i);
        prev = now;
        if (removed > 0) enqueue(async () => { for (let k = 0; k < removed; k++) await client.send("keyboard.key", { key: "backspace" }); });
        if (added) enqueue(() => client.send("keyboard.type", { text: added }));
      };
      input.addEventListener("input", (e) => {
        sync();
        if (!e.isComposing && input.value.length > 60) { input.value = ""; prev = ""; }
      });
      input.addEventListener("compositionend", sync);
      input.addEventListener("keydown", (e) => {
        const map = { Enter: "enter", Tab: "tab", Escape: "esc", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
        if (map[e.key]) {
          e.preventDefault();
          press(map[e.key]);
          if (e.key === "Enter") { input.value = ""; prev = ""; }
        } else if (e.key === "Backspace" && input.value === "") {
          e.preventDefault();
          press("backspace");
        }
      });
    }

    return { build, press };
  })();

  keyboard.build($("#keys-kbd"), { compact: false });
  keyboard.build($("#screen-kbd"), { compact: true });
  $("#kbd-toggle").addEventListener("click", () => {
    const drawer = $("#screen-kbd");
    drawer.hidden = !drawer.hidden;
    $("#kbd-toggle").setAttribute("aria-pressed", !drawer.hidden);
    $("#kbd-toggle").classList.toggle("is-on", !drawer.hidden);
    $("#screen-hint").hidden = !drawer.hidden;
    if (!drawer.hidden) $(".kbd__input", drawer).focus();
  });

  // Сочетания клавиш по группам
  (() => {
    const GROUPS = {
      "Презентация": [
        ["Показ с начала", ["f5"], "key--screen"], ["С текущего слайда", ["shift", "f5"], "key--screen"],
        ["Следующий слайд", ["right"], "key--screen"], ["Предыдущий слайд", ["left"], "key--screen"],
        ["Чёрный экран", ["b"], "key--screen"], ["Завершить показ", ["esc"], "key--screen"],
      ],
      "Правка": [
        ["Копировать", ["ctrl", "c"]], ["Вставить", ["ctrl", "v"]], ["Вырезать", ["ctrl", "x"]], ["Отменить", ["ctrl", "z"]],
        ["Повторить", ["ctrl", "y"]], ["Выделить всё", ["ctrl", "a"]], ["Сохранить", ["ctrl", "s"]], ["Найти", ["ctrl", "f"]],
      ],
      "Окна": [
        ["Переключить окно", ["alt", "tab"]], ["Свернуть всё", ["win", "d"]], ["Развернуть окно", ["win", "up"]], ["Закрыть окно", ["alt", "f4"]],
        ["Проводник", ["win", "e"]], ["Сменить язык", ["win", "space"]], ["Диспетчер задач", ["ctrl", "shift", "esc"]], ["Скриншот области", ["win", "shift", "s"]],
      ],
      "Браузер": [
        ["Новая вкладка", ["ctrl", "t"]], ["Закрыть вкладку", ["ctrl", "w"]], ["Следующая вкладка", ["ctrl", "tab"]], ["Обновить", ["f5"]],
        ["Назад", ["alt", "left"]], ["Вперёд", ["alt", "right"]], ["Адресная строка", ["ctrl", "l"]], ["Полный экран", ["f11"]],
      ],
      "Система": [
        ["Пуск", ["win"]], ["Поиск", ["win", "s"]], ["Выполнить", ["win", "r"]], ["Параметры", ["win", "i"]],
        ["Буфер обмена", ["win", "v"]], ["Эмодзи", ["win", "."]],
      ],
    };
    const chips = $("#hk-groups"), grid = $("#hotkeys");
    let group = store.get("mobpc.hkgroup");
    if (!GROUPS[group]) group = "Правка";
    function render() {
      chips.innerHTML = "";
      for (const name of Object.keys(GROUPS)) {
        const c = document.createElement("button");
        c.type = "button";
        c.className = "chip" + (name === group ? " is-on" : "");
        c.setAttribute("role", "tab");
        c.setAttribute("aria-selected", name === group);
        c.textContent = name;
        c.addEventListener("click", () => { group = name; store.set("mobpc.hkgroup", name); render(); });
        chips.appendChild(c);
      }
      grid.innerHTML = "";
      for (const [label, keys, cls] of GROUPS[group]) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "key " + (cls || "key--light");
        b.textContent = label;
        b.title = keys.join(" + ");
        b.addEventListener("click", () => {
          const cmd = keys.length === 1 ? client?.send("keyboard.key", { key: keys[0] }) : client?.send("keyboard.hotkey", { keys });
          cmd?.then(() => vibrate(8)).catch(fail);
        });
        grid.appendChild(b);
      }
    }
    render();

    $("#text-send").addEventListener("click", async () => {
      const ta = $("#text-input");
      if (!ta.value) { ta.focus(); return; }
      try {
        await client.send("keyboard.type", { text: ta.value });
        if ($("#text-enter").checked) await client.send("keyboard.key", { key: "enter" });
        toast("Текст отправлен");
        ta.value = "";
      } catch (e) { fail(e); }
    });
  })();

  // ---------- ТАЧПАД ----------
  (() => {
    const pad = $("#pad");
    const speedEl = $("#pad-speed");
    const saved = parseFloat(store.get("mobpc.padSpeed"));
    if (saved) speedEl.value = saved;
    speedEl.addEventListener("change", () => store.set("mobpc.padSpeed", speedEl.value));

    const pts = new Map();
    let acc = { x: 0, y: 0 }, scrollAcc = 0, flushTimer = null;
    let g = null;

    function queueFlush() {
      if (flushTimer) return;
      flushTimer = setTimeout(() => {
        flushTimer = null;
        const dx = Math.trunc(acc.x), dy = Math.trunc(acc.y);
        if (dx || dy) {
          client?.fire("mouse.move_rel", { dx, dy });
          acc.x -= dx; acc.y -= dy;
        }
      }, 16);
    }
    pad.addEventListener("pointerdown", (e) => {
      pad.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 1) {
        g = { n: 1, t0: Date.now(), dist: 0, drag: false };
        const cur = g;
        g.hold = setTimeout(() => {
          if (g === cur && g.n === 1 && g.dist < 8) {
            g.drag = true;
            pad.classList.add("is-dragging");
            vibrate(25);
            client?.fire("mouse.button", { button: "left", action: "press" });
          }
        }, 500);
      } else if (pts.size === 2 && g) {
        clearTimeout(g.hold);
        g.n = 2;
        g.dist2 = 0;
      }
    });
    pad.addEventListener("pointermove", (e) => {
      const prev = pts.get(e.pointerId);
      if (!prev || !g) return;
      const dx = e.clientX - prev.x, dy = e.clientY - prev.y;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (g.n === 1) {
        const v = Math.hypot(dx, dy);
        g.dist += v;
        const gain = parseFloat(speedEl.value) * Math.min(1 + v * 0.09, 3.2);
        acc.x += dx * gain; acc.y += dy * gain;
        queueFlush();
      } else if (g.n === 2) {
        g.dist2 += Math.abs(dy) + Math.abs(dx);
        scrollAcc += dy / 2;
        while (Math.abs(scrollAcc) >= 14) {
          const dir = Math.sign(scrollAcc);
          client?.fire("mouse.scroll", { dy: dir });
          scrollAcc -= dir * 14;
        }
      }
    });
    const end = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.delete(e.pointerId);
      if (!g || pts.size > 0) return;
      clearTimeout(g.hold);
      const quick = Date.now() - g.t0 < 260;
      if (g.drag) {
        client?.fire("mouse.button", { button: "left", action: "release" });
        pad.classList.remove("is-dragging");
      } else if (g.n === 2 && quick && g.dist2 < 16) {
        client?.fire("mouse.click", { button: "right" });
      } else if (g.n === 1 && quick && g.dist < 8 && e.type === "pointerup") {
        client?.fire("mouse.click", { button: "left" });
      }
      g = null;
      scrollAcc = 0;
    };
    pad.addEventListener("pointerup", end);
    pad.addEventListener("pointercancel", end);
    pad.addEventListener("contextmenu", (e) => e.preventDefault());

    for (const [id, button] of [["#pad-left", "left"], ["#pad-right", "right"]]) {
      const b = $(id);
      b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.classList.add("is-pressed"); client?.fire("mouse.button", { button, action: "press" }); });
      const up = () => { if (!b.classList.contains("is-pressed")) return; b.classList.remove("is-pressed"); client?.fire("mouse.button", { button, action: "release" }); };
      b.addEventListener("pointerup", up);
      b.addEventListener("pointerleave", up);
      b.addEventListener("pointercancel", up);
      b.addEventListener("contextmenu", (e) => e.preventDefault());
    }
  })();

  // ---------- ТЕРМИНАЛ ----------
  (() => {
    const out = $("#term-out"), input = $("#term-input"), shellSel = $("#shell-select");
    let cwd = null;
    const history = [];
    let hIdx = 0;
    const CHIPS = {
      powershell: ["ipconfig", "whoami", "Get-Date", "Get-ChildItem", "Get-Process | Sort-Object WS -Desc | Select -First 8 Name, Id", "ping -n 2 ya.ru", "cls"],
      cmd: ["ipconfig", "whoami", "dir", "ver", "tasklist | more", "cls"],
    };

    function print(text, cls) {
      const span = document.createElement("span");
      if (cls) span.className = cls;
      span.textContent = text;
      out.appendChild(span);
      while (out.childNodes.length > 1500) out.removeChild(out.firstChild);
      out.scrollTop = out.scrollHeight;
    }
    function renderCwd() { $("#term-cwd").textContent = cwd || ""; }
    function renderChips() {
      const box = $("#term-chips");
      box.innerHTML = "";
      for (const c of CHIPS[shellSel.value]) {
        const b = document.createElement("button");
        b.className = "chip";
        b.textContent = c;
        b.addEventListener("click", () => run(c));
        box.appendChild(b);
      }
    }
    shellSel.addEventListener("change", renderChips);
    renderChips();
    $("#term-clear").addEventListener("click", () => { out.innerHTML = ""; });

    async function initCwd() {
      if (cwd) return;
      try {
        const r = await client.send("shell.exec", { command: "[Environment]::GetFolderPath('UserProfile')", shell: "powershell" });
        cwd = r.stdout.trim() || null;
        renderCwd();
        if (!out.childNodes.length) print("Терминал компьютера. Команды выполняются от имени пользователя Windows.\n", "sys");
      } catch { /* попробуем при следующем открытии */ }
    }

    async function run(cmd) {
      cmd = cmd.trim();
      if (!cmd) return;
      history.push(cmd);
      hIdx = history.length;
      if (/^(cls|clear)$/i.test(cmd)) { out.innerHTML = ""; return; }
      const shell = shellSel.value;
      const promptStr = shell === "powershell" ? `PS ${cwd || ""}> ` : `${cwd || ""}> `;
      print(`${promptStr}${cmd}\n`, "cmd");
      let command = cmd;
      const cd = cmd.match(/^\s*(cd|chdir|set-location|sl)(\s+(.+))?$/i);
      if (cd && cd[3]) {
        command = shell === "powershell" ? `Set-Location ${cd[3]}; (Get-Location).Path` : `cd /d ${cd[3]} && cd`;
      }
      let streamed = false;
      try {
        const r = await client.send("shell.exec", { command, shell, cwd }, {
          timeout: 130000,
          onEvent: (m) => {
            if (m.type !== "shell.stream" || cd) return;
            streamed = true;
            print(m.data.data, m.data.stream === "stderr" ? "err" : null);
          },
        });
        if (cd && cd[3]) {
          if (r.exit_code === 0 && r.stdout.trim()) { cwd = r.stdout.trim().split(/\r?\n/).pop(); renderCwd(); }
          else print(r.stderr || "Не удалось перейти в папку\n", "err");
        } else if (!streamed) {
          if (r.stdout) print(r.stdout);
          if (r.stderr) print(r.stderr, "err");
        }
        if (r.exit_code !== 0 && !(cd && cd[3])) print(`[код завершения ${r.exit_code}]\n`, "sys");
      } catch (e) {
        print(`${e.message}\n`, "err");
      }
    }
    $("#term-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const v = input.value;
      input.value = "";
      run(v);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowUp" && hIdx > 0) { hIdx--; input.value = history[hIdx]; e.preventDefault(); }
      if (e.key === "ArrowDown") { hIdx = Math.min(history.length, hIdx + 1); input.value = history[hIdx] || ""; e.preventDefault(); }
    });
    panelHooks.term = { show: initCwd };
  })();

  // ---------- ФАЙЛЫ и ЗАГРУЗКИ ----------
  (() => {
    const list = $("#files-list");
    let path = null, parent = null;
    const join = (dir, name) => (dir.endsWith("\\") ? dir + name : dir + "\\" + name);

    async function open(p) {
      try {
        const r = await client.send("file.list", { path: p });
        path = r.path;
        parent = r.parent;
        render(r.entries, r.path === "");
      } catch (e) { fail(e); }
    }
    function render(entries, isDrives) {
      $("#files-path").textContent = isDrives ? "Этот компьютер" : path;
      $("#files-up").disabled = isDrives;
      list.innerHTML = "";
      if (!entries.length) { list.innerHTML = '<li class="empty">Папка пуста</li>'; return; }
      for (const it of entries) {
        const li = document.createElement("li");
        li.className = it.is_dir ? "is-dir" : "is-file";
        const icon = it.drive ? "i-drive" : it.is_dir ? "i-folder" : "i-file";
        li.innerHTML = `<svg><use href="#${icon}"/></svg><span class="name">${esc(it.name)}</span><span class="size">${it.is_dir && !it.drive ? "" : fmtBytes(it.size)}</span>`;
        li.addEventListener("click", () => {
          if (it.drive) open(it.name);
          else if (it.is_dir) open(join(path, it.name));
          else fileActions(join(path, it.name), it);
        });
        list.appendChild(li);
      }
    }
    async function fileActions(full, it) {
      const v = await sheet(it.name, fmtBytes(it.size), [
        { label: "Скачать на телефон", cls: "key--term", value: "dl" },
        { label: "Открыть на компьютере", value: "open" },
        { label: "Удалить", cls: "key--system", value: "del" },
        { label: "Отмена", value: null },
      ]);
      if (v === "dl") {
        const a = document.createElement("a");
        a.href = `/api/files/download?path=${encodeURIComponent(full)}&token=${encodeURIComponent(store.get(TOKEN_KEY))}`;
        a.download = it.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else if (v === "open") {
        client.send("app.launch", { path: full }).then(() => toast("Открыто на компьютере")).catch(fail);
      } else if (v === "del") {
        if (await ask(`Удалить «${it.name}» с компьютера без корзины?`, "Удалить")) {
          client.send("file.delete", { path: full, dangerous: true }).then(() => { toast("Файл удалён"); open(path); }).catch(fail);
        }
      }
    }
    $("#files-up").addEventListener("click", () => open(parent || "::drives"));
    for (const c of $$(".files__quick .chip")) c.addEventListener("click", () => open(c.dataset.path));

    async function toB64(buf) {
      const bytes = new Uint8Array(buf);
      let s = "";
      for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(s);
    }
    $("#upload-input").addEventListener("change", async (e) => {
      const files = [...e.target.files];
      e.target.value = "";
      if (!path) { toast("Сначала откройте папку", true); return; }
      const CHUNK = 384 * 1024;
      for (const f of files) {
        const target = join(path, f.name);
        try {
          for (let off = 0; off < f.size || off === 0; off += CHUNK) {
            const data = await toB64(await f.slice(off, off + CHUNK).arrayBuffer());
            await client.send("file.write", { path: target, data, append: off > 0 }, { timeout: 60000 });
            toast(`Загрузка ${f.name}: ${Math.min(100, Math.round((off + CHUNK) / Math.max(f.size, 1) * 100))}%`, false, 4000);
            if (f.size === 0) break;
          }
          toast(`Файл ${f.name} загружен на компьютер`);
        } catch (err) { fail(err); }
      }
      open(path);
    });

    // Скачивание на ПК по ссылке
    let dlTimer = null;
    const dlList = $("#dl-list");
    const STATUS = { starting: "Подключаемся…", downloading: "", done: "Готово", error: "Ошибка", cancelled: "Отменено" };
    function renderDownloads(items) {
      dlList.innerHTML = "";
      for (const d of items) {
        const li = document.createElement("li");
        li.className = "dl-item dl-item--" + d.status;
        const pct = d.total ? Math.round((d.received / d.total) * 100) : null;
        const progress = d.status === "downloading"
          ? `${fmtBytes(d.received)}${d.total ? ` из ${fmtBytes(d.total)}` : ""}${d.speed ? `, ${fmtBytes(d.speed)}/с` : ""}`
          : d.status === "error" ? d.error || "" : STATUS[d.status];
        li.innerHTML = `<div class="grow"><strong>${esc(d.name || d.url)}</strong><small>${esc(progress)}</small>
          ${d.status === "downloading" ? `<i class="meter"><b style="width:${pct ?? 30}%" class="${pct === null ? "indeterminate" : ""}"></b></i>` : ""}</div>`;
        if (d.status === "downloading" || d.status === "starting") {
          const b = document.createElement("button");
          b.className = "mini mini--danger";
          b.textContent = "Отменить";
          b.onclick = () => client.send("download.cancel", { id: d.id }).then(poll).catch(fail);
          li.appendChild(b);
        } else if (d.status === "done") {
          const b = document.createElement("button");
          b.className = "mini";
          b.textContent = "Открыть";
          b.onclick = () => client.send("app.launch", { path: d.path }).then(() => toast("Открыто на компьютере")).catch(fail);
          li.appendChild(b);
        }
        dlList.appendChild(li);
      }
    }
    async function poll() {
      try {
        const r = await client.send("download.list");
        renderDownloads(r.downloads.slice(0, 5));
        const active = r.downloads.some((d) => d.status === "downloading" || d.status === "starting");
        clearTimeout(dlTimer);
        if (active && currentTab === "files") dlTimer = setTimeout(poll, 1500);
      } catch { /* нет связи */ }
    }
    $("#dl-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = $("#dl-url");
      try {
        await client.send("download.start", { url: input.value.trim() });
        input.value = "";
        toast("Загрузка началась на компьютере — в папку «Загрузки»");
        poll();
      } catch (err) { fail(err); }
    });

    panelHooks.files = {
      show() { if (path === null) open("~"); poll(); },
      hide() { clearTimeout(dlTimer); },
    };
  })();

  // ---------- СИСТЕМА ----------
  (() => {
    let timer = null;
    const awake = $("#keep-awake");
    const setMeter = (id, pct) => {
      const b = $(id);
      b.style.width = `${Math.max(2, pct)}%`;
      b.className = pct > 85 ? "hot" : pct > 65 ? "warm" : "";
    };
    async function refresh() {
      try {
        const s = await client.send("system.stats");
        $("#st-cpu").textContent = `${Math.round(s.cpu)}%`;
        setMeter("#mt-cpu", s.cpu);
        $("#st-ram").textContent = `${fmtBytes(s.ram.used)} из ${fmtBytes(s.ram.total)}`;
        setMeter("#mt-ram", s.ram.percent);
        if (s.disk) { $("#st-disk").textContent = `${Math.round(s.disk.percent)}% занято`; setMeter("#mt-disk", s.disk.percent); }
        if (s.battery) {
          $("#st-extra-label").textContent = s.battery.plugged ? "Батарея, заряжается" : "Батарея";
          $("#st-extra").textContent = `${s.battery.percent}%`;
        } else {
          $("#st-extra-label").textContent = "Работает без перезагрузки";
          $("#st-extra").textContent = fmtUptime(s.uptime);
        }
        if (document.activeElement !== awake) awake.checked = !!s.keep_awake;
      } catch { /* следующий цикл */ }
    }
    awake.addEventListener("change", () => {
      client.send("power.keep_awake", { enabled: awake.checked })
        .then((r) => toast(r.keep_awake ? "Компьютер не уснёт, пока работает агент" : "Компьютер снова может засыпать"))
        .catch((e) => { awake.checked = !awake.checked; fail(e); });
    });

    for (const b of $$("[data-cmd]")) {
      b.addEventListener("click", async () => {
        if (b.dataset.confirm && !(await ask(b.dataset.confirm, b.textContent))) return;
        const payload = b.dataset.payload ? JSON.parse(b.dataset.payload) : {};
        if (b.dataset.confirm) payload.dangerous = true;
        client.send(b.dataset.cmd, payload).then(() => vibrate(10)).catch(fail);
      });
    }

    const MACROS = [
      ["Блокнот с приветствием", [
        { type: "app.launch", payload: { path: "notepad" }, delay: 1.5 },
        { type: "keyboard.type", payload: { text: "Привет! Этот текст набран с телефона через mobpc." } },
      ]],
      ["Калькулятор", [{ type: "app.launch", payload: { path: "calc" } }]],
      ["Steam: загрузки", [{ type: "app.launch", payload: { path: "steam://open/downloads" } }]],
      ["Steam: библиотека", [{ type: "app.launch", payload: { path: "steam://open/games" } }]],
      ["Свернуть все окна", [{ type: "keyboard.hotkey", payload: { keys: ["win", "d"] } }]],
      ["Диспетчер задач", [{ type: "keyboard.hotkey", payload: { keys: ["ctrl", "shift", "esc"] } }]],
      ["Выключить звук", [{ type: "media.volume", payload: { level: "mute" } }]],
      ["Скриншот области", [{ type: "keyboard.hotkey", payload: { keys: ["win", "shift", "s"] } }]],
    ];
    const mbox = $("#macros");
    for (const [name, steps] of MACROS) {
      const b = document.createElement("button");
      b.className = "key key--light";
      b.textContent = name;
      b.addEventListener("click", () => {
        client.send("macro.run", { name, steps }, { timeout: 60000 })
          .then((r) => {
            const bad = r.results.filter((x) => !x.ok);
            bad.length ? toast(`«${name}»: ${bad[0].error || "ошибка"}`, true) : toast(`Сценарий «${name}» выполнен`);
          })
          .catch(fail);
      });
      mbox.appendChild(b);
    }

    $("#notify-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const t = $("#notify-text");
      client.send("notify.send", { title: "Сообщение с телефона", message: t.value })
        .then(() => { toast("Уведомление показано на компьютере"); t.value = ""; }).catch(fail);
    });
    $("#clip-get").addEventListener("click", () => {
      client.send("clipboard.get").then((r) => { $("#clip-text").value = r.text; toast("Буфер обмена получен"); }).catch(fail);
    });
    $("#clip-set").addEventListener("click", () => {
      client.send("clipboard.set", { text: $("#clip-text").value }).then(() => toast("Текст скопирован в буфер ПК")).catch(fail);
    });

    async function loadWindows() {
      const ul = $("#win-list");
      try {
        const r = await client.send("window.list");
        ul.innerHTML = "";
        const wins = r.windows.filter((w) => w.title.trim()).slice(0, 30);
        if (!wins.length) ul.innerHTML = '<li class="empty">Открытых окон нет</li>';
        for (const w of wins) {
          const li = document.createElement("li");
          li.innerHTML = `<span class="grow">${esc(w.title)}</span><button class="mini" data-a="focus">Показать</button><button class="mini" data-a="min">Свернуть</button><button class="mini mini--danger" data-a="close">Закрыть</button>`;
          li.querySelector('[data-a="focus"]').onclick = () => client.send("window.focus", { hwnd: w.hwnd }).catch(fail);
          li.querySelector('[data-a="min"]').onclick = () => client.send("window.minimize", { hwnd: w.hwnd }).catch(fail);
          li.querySelector('[data-a="close"]').onclick = () => client.send("app.close", { hwnd: w.hwnd }).then(() => setTimeout(loadWindows, 600)).catch(fail);
          ul.appendChild(li);
        }
      } catch (e) { fail(e); }
    }
    let procs = [];
    function renderProcs() {
      const ul = $("#proc-list");
      const q = $("#proc-filter").value.trim().toLowerCase();
      const items = procs.filter((p) => !q || p.name.toLowerCase().includes(q)).slice(0, 40);
      ul.innerHTML = items.length ? "" : '<li class="empty">Ничего не найдено</li>';
      for (const p of items) {
        const li = document.createElement("li");
        li.innerHTML = `<span class="grow">${esc(p.name)}</span><span class="meta">${fmtBytes(p.memory)}</span><button class="mini mini--danger">Завершить</button>`;
        li.querySelector("button").onclick = async () => {
          if (!(await ask(`Завершить процесс ${p.name} (PID ${p.pid})? Несохранённые данные пропадут.`, "Завершить"))) return;
          client.send("process.kill", { pid: p.pid, dangerous: true }).then(() => { toast(`${p.name} завершён`); loadProcs(); }).catch(fail);
        };
        ul.appendChild(li);
      }
    }
    async function loadProcs() {
      try { procs = (await client.send("process.list")).processes; renderProcs(); } catch (e) { fail(e); }
    }
    $("#proc-filter").addEventListener("input", renderProcs);
    $("#win-refresh").addEventListener("click", loadWindows);
    $("#proc-refresh").addEventListener("click", loadProcs);

    panelHooks.system = {
      show() {
        refresh();
        clearInterval(timer);
        timer = setInterval(refresh, 2500);
        if (!procs.length) { loadWindows(); loadProcs(); }
      },
      hide() { clearInterval(timer); timer = null; },
    };
  })();

  // ---------- меню ----------
  $("#menu-btn").addEventListener("click", async () => {
    const name = $("#pc-name").textContent;
    const v = await sheet(name, `Адрес: ${location.host}. Этот телефон: ${deviceName()}.`, [
      { label: "Переподключиться", cls: "key--screen", value: "re" },
      { label: "Описание проекта", value: "home" },
      { label: "Отвязать этот телефон", cls: "key--system", value: "out" },
      { label: "Закрыть", value: null },
    ]);
    if (v === "re") { client.retry = 0; start(); }
    if (v === "home") location.href = "/";
    if (v === "out" && (await ask("Отвязать телефон? Чтобы вернуться, понадобится новый код с компьютера.", "Отвязать"))) {
      store.del(TOKEN_KEY);
      client.close();
      showPair();
    }
  });

  // ---------- старт ----------
  const tabParam = new URLSearchParams(location.search).get("tab");
  if (tabParam && document.querySelector(`.panel[data-panel="${CSS.escape(tabParam)}"]`)) currentTab = tabParam;
  const hash = location.hash.match(/pair=([A-Za-z0-9-]+)/);
  if (hash) {
    history.replaceState(null, "", location.pathname + location.search);
    showPair();
    $("#pair-code").value = hash[1].replace(/^(.{4})(.+)$/, "$1-$2");
    $("#pair-submit").disabled = true;
    $("#pair-submit").textContent = "Подключаем…";
    pair(hash[1]).then((j) => { start(j.hostname); toast(`Телефон подключён к ${j.hostname}`); }).catch((e) => showPair(e.message));
  } else if (store.get(TOKEN_KEY)) {
    start();
  } else {
    showPair();
  }
})();
