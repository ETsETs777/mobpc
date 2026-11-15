# mobpc — подключение

## В одной сети Wi-Fi (самый простой способ)

1. Запустите `start.bat` в корне проекта.
2. Откроется `http://127.0.0.1:8765/connect` с QR-кодом.
3. Наведите камеру телефона на QR — пульт откроется в браузере.

Если у компьютера несколько сетей (VPN, виртуальные адаптеры), выберите на странице ту, к которой подключён телефон.
В гостевых и школьных сетях устройства часто изолированы друг от друга — тогда раздайте Wi-Fi с телефона и подключите к нему ПК.

# Подключение через интернет

## Tailscale (рекомендуется)

### На ПК

1. Установите Tailscale:
   ```powershell
   winget install Tailscale.Tailscale
   ```
2. Войдите в аккаунт Tailscale.
3. Запустите агент:
   ```powershell
   cd agent
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python main.py
   ```
4. Получите Tailscale IP:
   ```powershell
   .\scripts\setup-tunnel.ps1
   ```

### На телефоне

1. Установите Tailscale из Play Store / App Store.
2. Войдите в тот же аккаунт.
3. В mobpc → «Добавить ПК»:
   - **Host:** Tailscale IP ПК (например `100.x.x.x`)
   - **Port:** `8765`
   - **TLS:** выкл

4. На ПК откройте `http://127.0.0.1:8765/connect`, выберите сеть Tailscale (`100.x.x.x`).
5. Отсканируйте QR камерой или в приложении mobpc.

Код привязки можно создать только на самом ПК — запросы из сети получат 403.

---

## Cloudflare Tunnel (запасной вариант)

### На ПК

1. Установите cloudflared:
   ```powershell
   winget install Cloudflare.cloudflared
   ```
2. Запустите агент (см. выше).
3. Запустите туннель:
   ```powershell
   .\scripts\setup-tunnel.ps1 -UseCloudflare
   ```
4. Скопируйте HTTPS URL из вывода (например `https://xxx.trycloudflare.com`).

### На телефоне

- **Host:** домен из cloudflared (без `https://`)
- **Port:** `443` или оставьте пустым если URL уже полный
- **TLS:** вкл

> Для production рекомендуется именованный туннель Cloudflare с постоянным доменом.

---

## Автозапуск агента

```powershell
.\scripts\install-agent.ps1
```

Агент будет запускаться при входе в Windows через Планировщик заданий.

---

## Проверка

```powershell
# Health check
curl http://127.0.0.1:8765/api/health

# Создать код привязки (только с самого ПК)
curl -X POST http://127.0.0.1:8765/api/pairing

# Автотесты
cd agent; .venv\Scripts\python -m unittest discover -s tests -v
```
