# mobpc

Удалённое управление Windows-ПК с телефона через Flutter-приложение и Python-агент.

## Возможности

- Управление мышью и клавиатурой
- Просмотр экрана ПК в реальном времени
- Терминал (PowerShell / cmd)
- Файловый менеджер
- Управление процессами, окнами, питанием
- Доступ через интернет (Tailscale / Cloudflare Tunnel)

## Структура

```
agent/    — Python-агент для Windows
mobile/   — Flutter-приложение
shared/   — Протокол команд
scripts/  — Скрипты установки и туннеля
docs/     — Документация
```

## Быстрый старт

### 1. Агент на ПК

```powershell
cd agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 2. Подключение через Tailscale

```powershell
.\scripts\setup-tunnel.ps1
```

### 3. Flutter-приложение

```bash
cd mobile
flutter pub get
flutter run
```

Подробнее: [docs/SETUP.md](docs/SETUP.md)

## Протокол

Команды передаются как JSON через WebSocket. Схема: [shared/protocol.json](shared/protocol.json).

## Лицензия

MIT
