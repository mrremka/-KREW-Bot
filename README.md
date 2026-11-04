<div align="center">
  <img src="assets/krew-cover.svg" alt="KREW — Telegram community system" width="100%" />

  <br /><br />

  <a href="https://github.com/mrremka/-KREW-Bot/actions/workflows/ci.yml">
    <img alt="KREW CI" src="https://github.com/mrremka/-KREW-Bot/actions/workflows/ci.yml/badge.svg?branch=main" />
  </a>
  <a href="https://github.com/mrremka/-KREW-Bot/releases">
    <img alt="Beta releases" src="https://img.shields.io/badge/channel-beta-9384F7" />
  </a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-367CA4?logo=python&logoColor=white" />

  <h3>Порядок в чате. Живое сообщество.</h3>
  <p>Модерация, аналитика и игровые механики в одном Telegram-боте.</p>

  <p>
    <a href="#возможности">Возможности</a> ·
    <a href="#проект">Проект</a> ·
    <a href="#релизы">Релизы</a>
  </p>
</div>

---

## Возможности

| Модуль | Что умеет |
| --- | --- |
| **Shield** 🛡️ | Антиспам, фильтрация ссылок, капча, анти-рейд и предупреждения |
| **Reports** ⚖️ | Жалобы с причинами решений, журнал модерации и уведомления |
| **Control Center 2.0** 🎛️ | Обзор сообщества, заявки, аналитика с графиками и удобная мобильная панель |
| **Community** ✨ | Профили, XP, уровни, игровые монеты, задания и рейтинги |
| **Interface** ◈ | Интерактивный `/help`, безопасные подтверждения, компактные сообщения и таблицы |
| **Updates** ↻ | Проверяемые обновления, резервные копии и автоматическая публикация релизов |

## Проект

```text
KREW
├── krew/            ядро бота, база данных и Mini App
├── scripts/         автоматическая сборка релизов
├── tests/           автоматические проверки
├── updates/         каналы версий
├── main.py          точка входа бота
├── launcher.py      контроль процесса и автообновление
└── updater.py       проверка, установка и откат обновлений
```

**Стек:** Python 3.11+, Telegram Bot API, SQLite, Telegram Mini App и GitHub Actions.

## Релизы

- [**GitHub Releases**](https://github.com/mrremka/-KREW-Bot/releases) — архивы и описание каждой версии
- [**Changelog**](CHANGELOG.md) — история изменений
- [**VERSION**](VERSION) — текущая версия исходного кода
- [**CI**](https://github.com/mrremka/-KREW-Bot/actions/workflows/ci.yml) — результат автоматических проверок

Текущая beta-версия: **1.0.0-rc.8**. Интерфейс Mini App оптимизирован под телефон и десктоп.

KREW находится на стадии **release candidate**. Автоматические тесты проходят, но проверка в реальных группах и под нагрузкой продолжается.

<div align="center">
  <sub>KREW · Built for better Telegram communities</sub>
</div>
