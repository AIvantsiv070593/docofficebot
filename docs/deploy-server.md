# Деплой на сервер (архив → scp → compose)

Сервер: `root@89.125.244.145`  
Каталог на сервере: `~/DocOfficeBot`

---

## 1. PowerShell (на своём ПК)

```powershell
cd D:\Dev\DocOfficeBot

# архив без .venv / .git / .cursor
& "$env:SystemRoot\System32\tar.exe" `
  --exclude='.venv' `
  --exclude='.git' `
  --exclude='.cursor' `
  -czvf D:\Dev\DocOfficeBot.tar.gz .

# копирование на сервер
scp D:\Dev\DocOfficeBot.tar.gz root@89.125.244.145:~/
```

Если `scp` не находится:

```powershell
& "$env:SystemRoot\System32\OpenSSH\scp.exe" D:\Dev\DocOfficeBot.tar.gz root@89.125.244.145:~/
```

---

## 2. SSH на сервер

```powershell
ssh root@89.125.244.145
```

или:

```powershell
& "$env:SystemRoot\System32\OpenSSH\ssh.exe" root@89.125.244.145
```

---

## 3. На сервере — распаковать поверх существующего каталога и запустить

```bash
cd ~

# остановить контейнеры (каталог уже есть)
cd ~/DocOfficeBot
docker-compose down

# распаковать архив поверх ~/DocOfficeBot (файлы перезапишутся)
cd ~
tar -xzf ~/DocOfficeBot.tar.gz -C ~/DocOfficeBot

# сборка и запуск
cd ~/DocOfficeBot
docker-compose up -d --build

# проверка
docker-compose ps
docker-compose logs -f --tail=80 bot
```

Выход из логов: `Ctrl+C`.

В Telegram: `/help` боту в ЛС.

---

## Заметки

- В архив попадают `.env` и `data/` — на сервере они **перезапишутся**. Если на сервере уже актуальная БД/токены и их нельзя затирать, перед `tar` на ПК исключите `data`:

  ```powershell
  & "$env:SystemRoot\System32\tar.exe" `
    --exclude='.venv' --exclude='.git' --exclude='.cursor' --exclude='data' `
    -czvf D:\Dev\DocOfficeBot.tar.gz .
  ```

  `.env` при этом всё равно уедет; не кладите его в архив только если серверный `.env` правильный — тогда добавьте `--exclude='.env'`.

- На сервере должен быть `docker-compose` (с дефисом) или плагин `docker compose`.
- Не держите второй инстанс бота с тем же `BOT_TOKEN` (например на домашнем ПК).
