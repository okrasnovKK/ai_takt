# ai-takt

Event-Manager-Agent — корпоративный ассистент мероприятий (Telegram bot).

## Быстрый старт

```bash
cd ai-takt
pip install -r requirements.txt
python run.py
```

## Команды

```bash
python cli.py chat "Привет всем!"                    # в командный чат
python cli.py user 123456789 "Личное сообщение"       # личное сообщение
python cli.py broadcast "Всем привет!"                # всем пользователям
python cli.py users                                   # список пользователей
```

## Структура

```
ai-takt/
├── .env                      # Токен бота и ID чата
├── requirements.txt          # Зависимости
├── run.py                    # Точка входа
├── cli.py                    # CLI-утилита
├── data/
│   └── users.json            # База пользователей (автосоздаётся)
└── src/
    ├── config.py             # Конфигурация
    ├── bot.py                # Основной бот
    ├── handlers/
    │   └── handlers.py       # Обработчики команд
    └── services/
        ├── database.py       # База пользователей
        └── messenger.py      # Сервис отправки сообщений
```

## Telegram bot

Бот: @ai_takt_bot
Токен: задаётся в .env
Чат команды: задаётся в .env

### Функционал (этап 1)
- [x] Регистрация пользователей при /start или любом сообщении
- [x] Отправка сообщений в командный чат
- [x] Отправка личных сообщений зарегистрированным пользователям
- [x] CLI для отправки сообщений
- [x] Broadcast всем пользователям"# ai_takt" 
