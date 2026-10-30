# DocOfficeBot

Прод-бот для чата ОФИС_Документы: альбом накладных (JPEG/PNG/HEIC) + команда `/send` → письмо в DocsInBox, реестр в Google Sheets, статусы реакциями в Telegram.

## Стек

Python 3.9+ (Docker: 3.12) · aiogram 3 · SQLite · Gmail API · Google Sheets API · Docker Compose

## Быстрый старт

1. Скопировать `.env.example` → `.env` и заполнить.
2. В Google Cloud включить **Gmail API** и **Google Sheets API**.
3. Создать OAuth client (Desktop) → сохранить как `data/gmail_credentials.json`.
4. Таблица Sheets должна быть доступна аккаунту `GMAIL_USER` (владелец/редактор).
5. Один OAuth на почту **и** таблицы (раз в браузере):

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python scripts/oauth_gmail.py
```

6. Запуск: `python -m src.main` или `docker compose up -d --build`

## Google OAuth (Gmail + Sheets, обязательно)

Service account **не нужен**. Один вход под `theofficesakh@gmail.com`.

- Клиент: `data/gmail_credentials.json`
- Токен: `data/gmail_token.json` (не в git) — scopes: gmail.send, gmail.modify, spreadsheets
- Если меняли scopes или токен старый — **удалите** `gmail_token.json` и снова `python scripts/oauth_gmail.py`
- Если refresh отозван: DM админу «нужна переавторизация», заявки ❌ `Gmail auth`

## Поведение

| Событие | Действие |
|---------|----------|
| Альбом + подпись `/send контрагент №…` | 👀 → проверка исключений / типов → письмо → ⚡ |
| Или реплай `/send контрагент №…` на фото | то же |
| Исключение | 🙈, письмо не шлём |
| Ответ «обращение №» | 🤝, номер в Sheets |
| Ответ «обработана» | 👍, СП/ссылки, удаление `data/claims/{id}/` |
| 48ч без 🤝 | повтор письма (до 3 попыток), затем 😐 |
| Ошибки | 👎 в чате + DM админу с деталями |

Реакции бота только из списка Telegram API (`❌📤✅` и т.п. отклоняются).  
Тема письма: `ООО Сфофрендз инн 6501291591\ {подпись}`.

Типы файлов: только JPEG/PNG/HEIC. PDF и прочее → 👎.

## Админ (ЛС боту)

```
/help
/pending
/check_gmail
/check_sheets
/resync_sheets
/wipe_all CONFIRM
```

`/help` — список команд. `/pending` — свод заявок не в статусе «Внесено».  
`/check_*` — проверка OAuth + API.  
`/resync_sheets` — пересобрать лист реестра из SQLite.  
`/wipe_all CONFIRM` — полная очистка заявок в БД, папок вложений и реестра Sheets (лист «Исключения» не трогает).

## Права бота в группе

- Privacy mode: **Disabled** (BotFather → /setprivacy)
- Право ставить реакции
- Один `ALLOWED_CHAT_ID`

Перед боем прогоните полный цикл в тестовом чате, затем смените `ALLOWED_CHAT_ID`.

## Runbook

| Симптом | Действие |
|---------|----------|
| DM «Gmail: нужна переавторизация» | `/check_gmail`, затем `oauth_gmail.py` + restart |
| Sheets недоступен | `/check_sheets`, API в Cloud Console, доступ к таблице |
| DM «Health: gmail_poll stale» | `docker compose logs -f bot`, restart |
| Unmatched письмо | проверить тему / matching |
| Бот молчит в чате | privacy, chat_id, токен |

Бэкапы SQLite: сервис `backup` в compose → `data/backups/` (ротация 7 дней).

## Тесты

```bash
pytest -q
```

## Документация

- [docs/email-examples/](docs/email-examples/)
- [docs/registry-and-storage.md](docs/registry-and-storage.md)
- Публичные страницы (GitHub Pages): [homepage](https://aivantsiv070593.github.io/docofficebot/) · [privacy](https://aivantsiv070593.github.io/docofficebot/privacy.html) — см. [docs/GOOGLE-SITE.md](docs/GOOGLE-SITE.md)
- [Privacy policy (link for Google)](PRIVACY.md) · License: [MIT](LICENSE)
