# Соедини точки — Telegram Mini App с рейтингом

## Запуск
1. Создайте бота у @BotFather, получите токен.
2. `pip install -r requirements.txt`
3. Нужен HTTPS-адрес (Telegram требует его для Mini App):
   - локально: `cloudflared tunnel --url http://localhost:8080` или `ngrok http 8080`
   - или любой хостинг (Render, Railway, VPS + nginx)
4. Запуск:
   ```
   export BOT_TOKEN="токен"
   export WEBAPP_URL="https://ваш-https-адрес"
   export CHANNEL_URL="https://t.me/vibexxxapk"
   python bot.py
   ```
5. В боте: `/start` → «🎮 Играть», `/top` → рейтинг в чате.

## Как считаются очки
За уровень: 100 + 20 за каждую точку + бонус за скорость (до 200) − 15 за каждую ошибку.
Подсказка стоит 10 очков. В рейтинге — лучший результат игрока.

## Защита
Сервер проверяет подпись Telegram (initData), срок её жизни и правдоподобность очков.
