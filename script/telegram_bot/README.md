# Telegram-бот для выгрузок

Даёт три вещи:
1. Уведомления в Telegram об успешной выгрузке или об ошибке (шлют сами `main.py`,
   `main_ozon.py`, `main_yandex.py`, `main_files.py`, `ozon_transaction/ozon_sync.py`,
   `ozon_transaction/ozon_advert_sync.py` — через `telegram_bot/notifier.py`).
2. Обновление `ozon_transaction/cookies.json` прямо из чата — пришли боту файл
   `cookies.json`, либо просто текстом абсолютный путь к файлу, уже лежащему
   на сервере (например `/home/user/cookies.json`) — бот сам его прочитает
   и скопирует.
3. Ручной запуск любой выгрузки командой `/run <job>`.

## Настройка

1. Создай бота через [@BotFather](https://t.me/BotFather), получи токен.
2. `cp telegram_bot/.env.example telegram_bot/.env` и заполни `TELEGRAM_BOT_TOKEN`.
3. Напиши боту `/start` — он в ответ пришлёт твой `user_id`.
4. Впиши свой id в `TELEGRAM_ALLOWED_USER_IDS` в `telegram_bot/.env` (через запятую,
   если несколько человек). Без этого `/run` и загрузка cookies.json будут отклоняться.
5. В `TELEGRAM_CHAT_ID` укажи chat_id, куда слать уведомления (обычно тот же id,
   что и твой user_id, если хочешь получать уведомления в личку с ботом).
6. Установи зависимости: `pip install -r requirements.txt` (requests + PySocks —
   последний нужен, только если будешь использовать SOCKS5-прокси, см. ниже).

## Прокси до Telegram (если сервер не может достучаться напрямую)

Если сервер (например РФ-хостинг) не видит `api.telegram.org` напрямую, нужен
локальный прокси-туннель прямо на самом сервере — прокси на другой машине
(например на твоём Маке) не поможет, туда сервер тоже не достучится.

### Основной способ: Xray-core + VLESS (xhttp)

Аккаунт ezhikvpn даёт и VLESS-конфиг (тот же провайдер, другой сервер/протокол).
VLESS+xhttp — стандартный протокол open-source `Xray-core`, поэтому не нужен
никакой особый бинарник — обычный Xray съедает конфиг Happ почти как есть.

1. Поставить Xray-core:
   ```bash
   bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
   ```
2. Положить конфиг в `/usr/local/etc/xray/config.json` — это конфиг из Happ
   (VLESS vnext на `network.ezhikvpn.xyz:8002`, xhttp+tls), только путь лога
   поправлен под линукс (`/var/log/xray/access.log`) и `dnsLog` выключен.
   Inbound `socks` на `127.0.0.1:10808` — оставь как есть, порт совпадает
   с тем, что бот ждёт в `.env`.
3. Официальный установщик уже создаёт systemd-юнит `xray`, читающий именно
   этот путь:
   ```bash
   sudo systemctl enable --now xray
   sudo systemctl status xray --no-pager
   ```
4. Проверить: `curl -x socks5h://127.0.0.1:10808 -o /dev/null -w "%{http_code}\n" https://api.telegram.org`
   должен вернуть `302`.
5. В `telegram_bot/.env`: `TELEGRAM_PROXY_URL=socks5h://127.0.0.1:10808`.

### Запасной способ: Hysteria2

Если у аккаунта есть отдельный Hysteria2-сервер (`hysteria2://...`, протокол
`hysteria` в конфиге Happ), для него нужен именно официальный клиент Hysteria2
(не Xray — `hysteria` в конфиге Happ — проприетарное расширение их сборки,
обычный `Xray-core` его не понимает):

```bash
curl -fsSL https://get.hy2.sh/ | sudo bash
```

Конфиг `telegram_bot/hysteria-client.yaml`:
```yaml
server: <host>:<port>
auth: <auth-UUID>

tls:
  sni: <host>

socks5:
  listen: 127.0.0.1:10808
```

Systemd-сервис `/etc/systemd/system/hysteria-client.service`:
```ini
[Unit]
Description=Hysteria2 client proxy for Telegram
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/hysteria client -c /home/user/script/telegram_bot/hysteria-client.yaml
Restart=always
RestartSec=5
User=user

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hysteria-client
```

Не гоняй Xray и Hysteria2-клиент одновременно на одном порту (`10808`) —
конфликт биндинга. Держи включённым только тот, который реально нужен:
`sudo systemctl disable --now hysteria-client` при переходе на Xray, и наоборот.

Прокси используется **только** для запросов к Telegram API (`notifier.py`,
`bot.py`) — БД и запросы к WB/Ozon/Yandex через него не идут.

Если сервер и так видит Telegram напрямую (не заблокирован) — оставь
`TELEGRAM_PROXY_URL` пустым, шаги выше не нужны.

## Запуск бота

Бот — постоянно работающий процесс (не cron), слушает Telegram через long polling:

```bash
python3 telegram_bot/bot.py
```

### Автозапуск через systemd (рекомендуется для сервера)

Создай `/etc/systemd/system/mp-telegram-bot.service`:

```ini
[Unit]
Description=Telegram bot for marketplace data sync
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/script
ExecStart=/usr/bin/python3 /home/user/script/telegram_bot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mp-telegram-bot
sudo systemctl status mp-telegram-bot
```

## Команды бота

- `/help`, `/start` — список команд
- `/jobs` — список задач, доступных для ручного запуска
- `/status` — время последнего лога по каждой задаче + время последнего обновления cookies.json
- `/run <job>` — запустить выгрузку вручную (`wb`, `ozon`, `yandex`, `files`, `ozon_tx`, `ozon_advert`)
- Файл `cookies.json` в чате, или просто текстом абсолютный путь к `.json`-файлу
  на сервере (например `/home/user/cookies.json`) — обновляет
  `ozon_transaction/cookies.json`

Доступ к `/run`, `/status` и загрузке cookies.json ограничен списком
`TELEGRAM_ALLOWED_USER_IDS` — все остальные получат отказ с указанием их id.

## Как это подключено к скриптам выгрузки

Каждый из `main.py`, `main_ozon.py`, `main_yandex.py`, `main_files.py` и оба
скрипта в `ozon_transaction/` при старте регистрируют `sys.excepthook`, который
шлёт в Telegram сообщение об ошибке при любом необработанном исключении, и в
конце успешного прогона шлют сообщение об успехе. Никакого отдельного процесса
для этого не нужно — уведомление отправляет сам скрипт выгрузки в момент своего
завершения. Если `telegram_bot/.env` не заполнен, уведомления просто не
отправляются (в лог пишется предупреждение), сама выгрузка при этом не падает.
