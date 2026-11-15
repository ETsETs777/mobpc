/* Страница на ПК: QR-код привязки, таймер, сети, список устройств. */
"use strict";
(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  };
  const KIND = { lan: "Wi-Fi или локальная сеть", tailscale: "Tailscale, доступ через интернет", virtual: "Виртуальный адаптер", other: "Другая сеть", internet: "Через интернет, из любой сети" };

  let host = store.get("mobpc.host");
  let session = null;
  let tick = null, poll = null;

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (r.status === 403) throw Object.assign(new Error("remote"), { remote: true });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }

  function timeLeft() { return session ? Math.max(0, session.expires_at - Date.now() / 1000) : 0; }
  function renderTimer() {
    const left = timeLeft();
    const m = Math.floor(left / 60), s = Math.floor(left % 60);
    $("#timer-text").textContent = left > 0 ? `Код действует ${m}:${String(s).padStart(2, "0")}` : "Код истёк, создаём новый…";
    $("#timer-bar").style.width = `${(left / (session ? session.ttl : 300)) * 100}%`;
    if (left <= 0) newCode();
  }

  async function newCode() {
    clearInterval(tick); clearInterval(poll);
    try {
      session = await api(`/api/pairing${host ? `?host=${encodeURIComponent(host)}` : ""}`, { method: "POST" });
    } catch (e) {
      if (e.remote) { $("#connect-main").hidden = true; $("#remote-note").hidden = false; }
      return;
    }
    host = session.host;
    $("#qr-img").src = `${session.qr_url}&t=${Date.now()}`;
    $("#qr-done").hidden = true;
    $("#qr-card").classList.remove("is-done");
    $("#code-text").textContent = session.display_code;
    $("#manual-url").textContent = session.app_url.split("#")[0];
    renderNets();
    renderTimer();
    tick = setInterval(renderTimer, 1000);
    poll = setInterval(checkPaired, 1500);
  }

  async function checkPaired() {
    if (!session) return;
    try {
      const r = await fetch(`/api/pairing/${session.code}`);
      if (r.status === 404) { newCode(); return; } // агент перезапустился — старый код недействителен
      if (!r.ok) return;
      const st = await r.json();
      if (st.status === "paired") {
        clearInterval(poll); clearInterval(tick);
        $("#qr-card").classList.add("is-done");
        $("#qr-done").hidden = false;
        $("#qr-done-name").textContent = st.device_name || "";
        loadDevices();
        setTimeout(newCode, 6000);
      }
    } catch { /* сеть моргнула */ }
  }

  let nets = [];
  let tunnelUrl = null;
  async function loadNets() {
    try { nets = (await api("/api/network")).addresses; } catch { nets = []; }
    renderNets();
    renderTailscale();
  }
  function renderTailscale() {
    const ts = nets.find((n) => n.kind === "tailscale");
    $("#ts-dot").className = "dot " + (ts ? "dot--ok" : "");
    if (ts) {
      $("#ts-title").textContent = "Tailscale: работает";
      $("#ts-sub").innerHTML = `Постоянный адрес <code>${esc(ts.ip)}</code>. Выберите его ниже и отсканируйте QR телефоном с Tailscale.`;
    } else {
      $("#ts-title").textContent = "Tailscale: не установлен";
      $("#ts-sub").innerHTML = 'Установите на ПК (<code>winget install Tailscale.Tailscale</code>) и на телефон, войдите в один аккаунт, затем обновите эту страницу.';
    }
  }
  function allNets() {
    return tunnelUrl ? [{ ip: tunnelUrl, iface: "Cloudflare Tunnel", kind: "internet" }, ...nets] : nets;
  }
  function renderNets() {
    const box = $("#nets");
    box.innerHTML = "";
    const list = allNets();
    if (!list.length) { box.innerHTML = '<p class="block__text">Сетевые подключения не найдены.</p>'; return; }
    list.forEach((n, idx) => {
      const id = `net-${idx}`;
      const label = document.createElement("label");
      label.className = "net" + (n.ip === host ? " is-on" : "");
      label.htmlFor = id;
      label.innerHTML = `<input type="radio" name="net" id="${id}" value="${esc(n.ip)}" ${n.ip === host ? "checked" : ""}>
        <span class="net__ip">${esc(n.ip)}</span><span class="net__kind">${esc(KIND[n.kind] || n.kind)}, ${esc(n.iface)}</span>`;
      label.querySelector("input").addEventListener("change", () => {
        host = n.ip;
        if (n.kind !== "internet") store.set("mobpc.host", host);
        newCode();
      });
      box.appendChild(label);
    });
  }

  // ---------- доступ через интернет ----------
  let tunnelPoll = null;
  async function tunnelAction(path) {
    try { renderTunnel(await api(path, { method: "POST" })); } catch (e) { if (!e.remote) alert(e.message); }
  }
  function renderTunnel(t) {
    const dot = $("#tunnel-dot"), title = $("#tunnel-title"), sub = $("#tunnel-sub"), btn = $("#tunnel-toggle");
    $("#keep-awake").checked = !!t.keep_awake;
    const prevUrl = tunnelUrl;
    tunnelUrl = t.state === "on" ? t.url : null;
    btn.disabled = t.state === "downloading" || t.state === "starting";
    btn.textContent = t.state === "on" ? "Выключить" : t.state === "error" ? "Повторить" : "Включить";
    btn.className = "key key--sm " + (t.state === "on" ? "key--light" : "key--term");
    dot.className = "dot " + (t.state === "on" ? "dot--ok" : t.state === "error" ? "dot--off" : t.state === "off" ? "" : "dot--warn");
    if (t.state === "on") {
      title.textContent = "Cloudflare: включён";
      sub.innerHTML = `Адрес: <code>${esc(t.url)}</code>`;
    } else if (t.state === "downloading") {
      title.textContent = `Скачиваем cloudflared… ${Math.round(t.progress * 100)}%`;
      sub.textContent = "Один раз, около 60 МБ, в папку agent/tools проекта.";
    } else if (t.state === "starting") {
      title.textContent = "Cloudflare: подключаемся…";
      sub.textContent = "Обычно 5–20 секунд. Ждём, пока туннель реально заработает.";
    } else if (t.state === "error") {
      title.textContent = "Cloudflare: не подключился";
      sub.textContent = t.error || "Неизвестная ошибка";
    } else {
      title.textContent = "Cloudflare: выключен";
      sub.textContent = "Одна кнопка, без регистрации и без приложений на телефоне.";
    }
    if (tunnelUrl !== prevUrl) {
      if (tunnelUrl) host = tunnelUrl;
      else if (prevUrl && host === prevUrl) host = store.get("mobpc.host") || null;
      renderNets();
      if (session) newCode();
    }
    clearTimeout(tunnelPoll);
    if (t.state === "downloading" || t.state === "starting") tunnelPoll = setTimeout(loadTunnel, 1000);
  }
  async function loadTunnel() {
    try { renderTunnel(await api("/api/tunnel")); } catch { /* страница открыта не на ПК */ }
  }
  $("#tunnel-toggle").addEventListener("click", () => tunnelAction(tunnelUrl ? "/api/tunnel/stop" : "/api/tunnel/start"));
  $("#keep-awake").addEventListener("change", async (e) => {
    try { await api(`/api/keep-awake?enabled=${e.target.checked}`, { method: "POST" }); } catch { e.target.checked = !e.target.checked; }
    loadTunnel();
  });

  function ago(ts) {
    const s = Date.now() / 1000 - ts;
    if (s < 60) return "только что";
    if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
    if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
    return new Date(ts * 1000).toLocaleDateString("ru-RU");
  }
  async function loadDevices() {
    let devs;
    try { devs = (await api("/api/devices")).devices; } catch { return; }
    const ul = $("#devices");
    ul.innerHTML = devs.length ? "" : '<li class="devices__empty">Пока ни одного телефона.</li>';
    for (const d of devs) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="dot ${d.online ? "dot--ok" : ""}" aria-hidden="true"></span>
        <span class="devices__name">${esc(d.name)}<small>${d.online ? "на связи сейчас" : `был ${ago(d.last_seen || d.paired_at)}`}</small></span>
        <button class="key key--light key--sm">Отключить</button>`;
      li.querySelector("button").addEventListener("click", async () => {
        if (!confirm(`Отключить «${d.name}»? Телефону понадобится новый код.`)) return;
        await fetch(`/api/devices/${d.id}`, { method: "DELETE" });
        loadDevices();
      });
      ul.appendChild(li);
    }
  }

  async function status() {
    const el = $("#agent-status");
    try {
      const s = await api("/api/status");
      el.innerHTML = `<span class="dot dot--ok" aria-hidden="true"></span><span>Агент работает на ${esc(s.hostname)}</span>`;
    } catch {
      el.innerHTML = '<span class="dot dot--off" aria-hidden="true"></span><span>Агент не отвечает</span>';
    }
  }

  $("#new-code").addEventListener("click", newCode);
  loadNets().then(loadTunnel).then(newCode);
  loadDevices();
  status();
  setInterval(loadDevices, 5000);
  setInterval(status, 10000);
})();
