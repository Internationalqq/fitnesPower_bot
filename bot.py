import sys
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Добавляем директорию скрипта в путь для поиска локальных модулей
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import asyncio
import logging
import re
from typing import Optional, Dict, List
from aiohttp import web
from aiohttp.web import Response

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, MenuButtonWebApp
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database
from motivator import Motivator
from calorie_counter import CalorieCounter

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# Включаем DEBUG для handle_text для отладки
logging.getLogger(__name__).setLevel(logging.DEBUG)

# Инициализация бота и диспетчера
bot: Optional[Bot] = None
dp: Dispatcher = None
db: Database = None
motivator: Motivator = None
calorie_counter: CalorieCounter = None
scheduler: AsyncIOScheduler = None


async def get_chat_members_dict(chat_id: int, user_ids: List[int]) -> Dict[int, str]:
    """Получение словаря участников группы: user_id -> имя"""
    members_dict = {}
    try:
        # Получаем имена для каждого user_id из базы данных
        for user_id in user_ids:
            try:
                # Пытаемся получить информацию о пользователе через get_chat_member
                chat_member = await bot.get_chat_member(chat_id, user_id)
                user = chat_member.user
                name = user.first_name
                if user.last_name:
                    name += f" {user.last_name}"
                members_dict[user_id] = name
            except Exception as e:
                # Если не удалось получить через API, используем имя из базы
                logger.debug(f"Не удалось получить имя для user_id {user_id}: {e}")
                continue
    except Exception as e:
        logger.error(f"Ошибка при получении участников чата {chat_id}: {e}")
    
    return members_dict


async def send_daily_summary_for_date(chat_id: int, target_date):  # target_date: date
    """Отправка сводки за указанную дату в группу (используется и для утра, и для теста)."""
    from datetime import date, timedelta
    stats = db.get_group_stats_by_date(chat_id, target_date)
    if not stats:
        return
    user_ids = [stat['user_id'] for stat in stats]
    members_dict = await get_chat_members_dict(chat_id, user_ids)
    date_str = target_date.strftime("%d.%m.%Y")
    message = f"‼️⚠️{date_str}⚠️‼️\n"
    for stat in stats:
        if stat['user_id'] not in members_dict:
            members_dict[stat['user_id']] = stat['username']
    sorted_stats = sorted(stats, key=lambda x: members_dict.get(x['user_id'], x['username']))
    for i, stat in enumerate(sorted_stats):
        name = members_dict.get(stat['user_id'], stat['username'])
        pushups, abs_count = stat['pushups'], stat['abs']
        message += f"{name}:\nотжимания: {pushups}" + ("; ⚠️" if pushups >= 80 else ";") + "\n"
        message += f"пресс: {abs_count}" + (". ⚠️" if i == len(sorted_stats) - 1 and abs_count >= 80 else "; ⚠️" if abs_count >= 80 else "." if i == len(sorted_stats) - 1 else ";") + "\n"
    await bot.send_message(chat_id, message)
    first_date = db.get_chat_first_activity_date(chat_id)
    if first_date:
        days = (date.today() - first_date).days
        if days >= 0:
            if days == 0:
                days_text = "сегодня первый день — так держать!"
            elif days == 1:
                days_text = "вы занимаетесь уже 1 день."
            elif 2 <= days <= 4:
                days_text = f"вы занимаетесь уже {days} дня."
            else:
                days_text = f"вы занимаетесь уже {days} дней."
            await bot.send_message(chat_id, f"🏆 {days_text.capitalize()}")


async def send_daily_summary(chat_id: int):
    """Отправка ежедневной сводки в группу (план на сегодня)"""
    try:
        from datetime import date
        # Только те, кто писал /отжимания или /пресс за последние 7 дней
        all_participants = db.get_active_chat_participants(chat_id, days=7)
        if not all_participants:
            logger.info(f"Нет участников в чате {chat_id}")
            return
        user_ids = [p['user_id'] for p in all_participants]
        members_dict = await get_chat_members_dict(chat_id, user_ids)
        for p in all_participants:
            if p['user_id'] not in members_dict:
                members_dict[p['user_id']] = p['username']
        sorted_participants = sorted(all_participants, key=lambda x: members_dict.get(x['user_id'], x['username']))
        # «Вы занимаетесь уже N дней»
        first_date = db.get_chat_first_activity_date(chat_id)
        if first_date:
            days = (date.today() - first_date).days
            if days >= 0:
                if days == 0:
                    days_text = "сегодня первый день — так держать!"
                elif days == 1:
                    days_text = "вы занимаетесь уже 1 день."
                elif 2 <= days <= 4:
                    days_text = f"вы занимаетесь уже {days} дня."
                else:
                    days_text = f"вы занимаетесь уже {days} дней."
                await bot.send_message(chat_id, f"🏆 {days_text.capitalize()}")
        # Сообщение: сегодня нужно (долг + 80)
        message_today = "📋 <b>Сегодня нужно сделать:</b>\n\n"
        for participant in sorted_participants:
            user_id = participant['user_id']
            name = members_dict.get(user_id, participant['username'])
            name_escaped = str(name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # Долг = сумма всех count за все дни (если > 0)
            pushups_debt = db.get_user_pushups_debt(user_id, chat_id)
            abs_debt = db.get_user_abs_debt(user_id, chat_id)
            # Сегодня нужно = долг + 80
            pushups_today = pushups_debt + 80
            abs_today = abs_debt + 80
            message_today += f"<u>{name_escaped}</u>:\n"
            push_line = f"Отжимания: {pushups_today} ({pushups_debt} долг + 80)"
            if pushups_today > 80:
                push_line += " ⚠️"
            message_today += push_line + "\n"
            abs_line = f"Пресс: {abs_today} ({abs_debt} долг + 80)"
            if abs_today > 80:
                abs_line += " ⚠️"
            message_today += abs_line + "\n\n"
        await bot.send_message(chat_id, message_today.strip(), parse_mode='HTML')
        logger.info(f"Отправлена ежедневная сводка в чат {chat_id} (план на сегодня)")
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневной сводки в чат {chat_id}: {e}")


async def add_daily_norm_to_all_chats():
    """Каждый день добавляет +80 к долгу всем, кто был активен за последние 7 дней."""
    try:
        active_chats = db.get_active_chats()
        for chat_id in active_chats:
            participants = db.get_active_chat_participants(chat_id, days=7)
            for p in participants:
                db.add_pushups(p['user_id'], p['username'] or '', 80, chat_id)
                db.add_abs(p['user_id'], p['username'] or '', 80, chat_id)
        if active_chats:
            logger.info(f"Добавлена дневная норма +80 в {len(active_chats)} чатах")
    except Exception as e:
        logger.error(f"Ошибка при добавлении дневной нормы: {e}")


async def send_daily_summary_to_all_chats():
    """Отправка ежедневной сводки во все активные группы"""
    try:
        await add_daily_norm_to_all_chats()
        active_chats = db.get_active_chats()
        for chat_id in active_chats:
            await send_daily_summary(chat_id)
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневных сводок: {e}")


async def send_motivational_message(chat_id: int):
    """Отправка мотивирующего сообщения в группу"""
    try:
        # Формируем контекст о программе тренировок группы
        context = {
            "program": "80 отжиманий и 80 упражнений на пресс ежедневно",
            "frequency": "каждый день"
        }
        
        fact, tip = await motivator.generate_motivational_content(context=context)
        
        message = f"💪 <b>Мотивация на сегодня!</b>\n\n"
        message += f"📊 <b>Факт:</b> {fact}\n\n"
        message += f"💡 <b>Совет:</b> {tip}"
        
        await bot.send_message(chat_id, message, parse_mode='HTML')
        logger.info(f"Отправлено мотивирующее сообщение в чат {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке мотивирующего сообщения: {e}")


async def send_motivational_to_all_chats():
    """Отправка мотивирующих сообщений во все активные группы"""
    try:
        active_chats = db.get_active_chats()
        for chat_id in active_chats:
            await send_motivational_message(chat_id)
    except Exception as e:
        logger.error(f"Ошибка при отправке мотивирующих сообщений: {e}")


async def setup_scheduler():
    """Настройка расписания для отправки ежедневной сводки и мотивации"""
    global scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Yekaterinburg")
    
    # Отправка ежедневной сводки в 8:00 по Екатеринбургу
    scheduler.add_job(
        send_daily_summary_to_all_chats,
        'cron',
        hour=8,
        minute=00,
        id='daily_summary'
    )
    
    # Отправка мотивирующих сообщений в 9:00 и 20:00
    scheduler.add_job(
        send_motivational_to_all_chats,
        'cron',
        hour=9,
        minute=0,
        id='morning_motivation'
    )
    
    scheduler.add_job(
        send_motivational_to_all_chats,
        'cron',
        hour=20,
        minute=0,
        id='evening_motivation'
    )
    
    scheduler.start()
    logger.info("Планировщик запущен (8:00 сводка, 9:00 и 20:00 мотивация)")


async def cmd_start(message: Message):
    """Обработка команды /start"""
    if message.chat.type == "private":
        # Личные сообщения - помощь с калориями
        text = (
            "👋 Привет! Я помогу тебе вести подсчет калорий.\n\n"
            "📝 <b>Доступные команды:</b>\n"
            "/add_meal - добавить прием пищи\n"
            "/today - статистика за сегодня\n"
            "/week - статистика за неделю\n"
            "/set_limit - установить дневную норму калорий\n"
            "/scanner - открыть сканер штрих-кодов 📷\n"
            "/help - помощь\n\n"
            "Также ты можешь:\n"
            "• Написать что съел: <code>овсянка 200г, банан 1шт</code>\n"
            "• Или просто: <code>Съел борщ с хлебом и салат</code>\n"
            "• Отправить фото штрих-кода продукта 📷\n"
            "• Или написать штрих-код текстом: <code>4610169567144</code>\n"
            "• Или открыть сканер камеры 📱\n\n"
            "Я покажу КБЖУ (калории, белки, жиры, углеводы) и добавлю продукт в дневник!"
        )
        
        # Создаем кнопку для Mini App
        # ВАЖНО: Замени URL на свой публичный URL веб-приложения
        # Для тестирования можно использовать ngrok или другой туннель
        web_app_url = os.getenv("WEB_APP_URL", "https://your-domain.com/webapp/index.html")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📷 Открыть сканер камеры",
                web_app=WebAppInfo(url=web_app_url)
            )]
        ])
        
        await message.answer(text, parse_mode='HTML', reply_markup=keyboard)
    else:
        # Групповой чат - статистика тренировок
        text = (
            "💪 Привет! Я буду вести статистику ваших тренировок!\n\n"
            "📊 <b>Доступные команды:</b>\n"
            "/pushups [количество] - добавить отжимания\n"
            "/отжимания [количество] - отметить сделанные отжимания (остаток до 80)\n"
            "/abs [количество] - добавить упражнения на пресс\n"
            "/пресс [количество] - отметить сделанный пресс (остаток до 80)\n"
            "/stats - статистика за сегодня\n"
            "/leaderboard - таблица лидеров\n"
            "/my_stats - моя статистика\n"
            "/help - помощь"
        )
        await message.answer(text, parse_mode='HTML')


async def cmd_scanner(message: Message):
    """Обработка команды /scanner - открытие сканера штрих-кодов"""
    if message.chat.type != "private":
        await message.answer("Эта команда работает только в личных сообщениях!")
        return
    
    web_app_url = os.getenv("WEB_APP_URL", "https://your-domain.com/webapp/index.html")
    
    if web_app_url == "https://your-domain.com/webapp/index.html":
        await message.answer(
            "❌ Сканер не настроен.\n\n"
            "Для работы сканера нужно:\n"
            "1. Загрузить веб-приложение на хостинг\n"
            "2. Добавить URL в .env файл:\n"
            "<code>WEB_APP_URL=https://your-domain.com/webapp/index.html</code>\n\n"
            "💡 Пока можешь использовать:\n"
            "• Отправку фото штрих-кода боту\n"
            "• Или написать штрих-код текстом",
            parse_mode='HTML'
        )
        return
    
    text = (
        "📷 <b>Сканер штрих-кодов</b>\n\n"
        "Нажми кнопку ниже, чтобы открыть сканер:\n"
        "• Сканирование через камеру\n"
        "• Ручной ввод штрих-кода\n"
        "• Автоматический поиск продукта\n"
        "• Добавление в дневник калорий"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📷 Открыть сканер",
            web_app=WebAppInfo(url=web_app_url)
        )]
    ])
    
    await message.answer(text, parse_mode='HTML', reply_markup=keyboard)


async def cmd_help(message: Message):
    """Обработка команды /help"""
    if message.chat.type == "private":
        text = (
            "📝 <b>Подсчет калорий:</b>\n\n"
            "• Используй /add_meal для добавления приема пищи\n"
            "• Или просто напиши что съел: <code>Завтрак: яйца 2шт, хлеб 50г</code>\n"
            "• Можно писать свободно: <code>Съел борщ с хлебом</code>\n"
            "• /today - посмотреть калории за сегодня\n"
            "• /week - статистика за неделю\n"
            "• /set_limit 2000 - установить дневную норму\n\n"
            "Я автоматически распознаю продукты и их количество!"
        )
    else:
        text = (
            "💪 <b>Статистика тренировок:</b>\n\n"
            "• /отжимания 20 — отметить отжимания; /отжимания 0 — записаться в список\n"
            "• /пресс 20 — отметить пресс; /пресс 0 — записаться в список\n"
            "• /записаться — кинуть в чат приглашение (все пишут /отжимания 0)\n"
            "• /pushups, /abs — добавить к долгу (редко нужно)\n"
            "• /stats - статистика группы за сегодня\n"
            "• /my_stats - твоя личная статистика\n"
            "• /leaderboard - кто больше всех отжался\n\n"
            "Я буду отправлять ежедневную сводку в 8:00 утра и мотивирующие сообщения в 9:00 и 20:00!"
        )
    await message.answer(text, parse_mode='HTML')


async def cmd_pushups(message: Message):
    """Добавление или вычитание отжиманий"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /pushups [количество]\nПример: /pushups 80 или /pushups -20")
            return
        
        count = int(args[1])
        if count == 0:
            await message.answer("Количество не может быть нулем!")
            return
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        # Получаем имя из Telegram
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += f" {message.from_user.last_name}"
        
        if count < 0:
            # Вычитаем (отрицательное значение)
            db.add_pushups(user_id, username, count, message.chat.id)  # count уже отрицательный
            total_today = max(0, db.get_user_pushups_today(user_id, message.chat.id))
            remaining = max(0, 80 - total_today)
            
            await message.answer(
                f"Молодец, {user_name}! Тебе осталось {remaining} отжиманий.",
                reply_to_message_id=message.message_id
            )
        else:
            # Добавляем (положительное значение)
            db.add_pushups(user_id, username, count, message.chat.id)
            total_today = max(0, db.get_user_pushups_today(user_id, message.chat.id))
            
            await message.answer(
                f"✅ {username} добавил {count} отжиманий!\n"
                f"📊 Всего за сегодня: {total_today}",
                reply_to_message_id=message.message_id
            )
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при добавлении отжиманий: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_abs(message: Message):
    """Добавление или вычитание упражнений на пресс"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /abs [количество]\nПример: /abs 80 или /abs -20")
            return
        
        count = int(args[1])
        if count == 0:
            await message.answer("Количество не может быть нулем!")
            return
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        # Получаем имя из Telegram
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += f" {message.from_user.last_name}"
        
        if count < 0:
            # Вычитаем (отрицательное значение)
            db.add_abs(user_id, username, count, message.chat.id)  # count уже отрицательный
            total_today = max(0, db.get_user_abs_today(user_id, message.chat.id))
            remaining = max(0, 80 - total_today)
            
            await message.answer(
                f"Молодец, {user_name}! Тебе осталось {remaining} пресс.",
                reply_to_message_id=message.message_id
            )
        else:
            # Добавляем (положительное значение)
            db.add_abs(user_id, username, count, message.chat.id)
            total_today = max(0, db.get_user_abs_today(user_id, message.chat.id))
            
            await message.answer(
                f"✅ {username} добавил {count} упражнений на пресс!\n"
                f"📊 Всего за сегодня: {total_today}",
                reply_to_message_id=message.message_id
            )
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при добавлении упражнений на пресс: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_otzhimaniya(message: Message):
    """Отметить сделанные отжимания (вычитает из долга)"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer(
                "Использование: /отжимания [количество]\n"
                "Пример: /отжимания 20 — отметить 20 отжиманий.\n"
                "Напиши /отжимания 0 — чтобы записаться в список (с завтра будешь в отчёте)."
            )
            return
        
        count = int(args[1])
        count = abs(count)
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += f" {message.from_user.last_name}"
        
        if count == 0:
            # Регистрация в списке: одна запись в оба типа, чтобы попал в отчёт
            try:
                db.add_pushups(user_id, username, 0, message.chat.id)
                db.add_abs(user_id, username, 0, message.chat.id)
                
                # Проверяем, что записи действительно созданы
                pushups_today = db.get_user_pushups_today(user_id, message.chat.id)
                abs_today = db.get_user_abs_today(user_id, message.chat.id)
                logger.info(f"Регистрация пользователя: user_id={user_id}, chat_id={message.chat.id}, pushups_today={pushups_today}, abs_today={abs_today}")
                
                await message.answer(
                    f"✅ {user_name}, ты в списке! С завтра будешь в утреннем отчёте с нормой 80 отжиманий и 80 пресса.",
                    reply_to_message_id=message.message_id
                )
            except Exception as e:
                logger.error(f"Ошибка при регистрации пользователя {user_id} в чате {message.chat.id}: {e}", exc_info=True)
                await message.answer(
                    f"❌ Произошла ошибка при регистрации. Попробуй еще раз.",
                    reply_to_message_id=message.message_id
                )
            return
        
        # «Сделал N» = вычитаем N из долга
        db.add_pushups(user_id, username, -count, message.chat.id)
        debt_after = db.get_user_pushups_debt(user_id, message.chat.id)
        await message.answer(
            f"Молодец, {user_name}! Сделано {count} отжиманий. Осталось: {debt_after}.",
            reply_to_message_id=message.message_id
        )
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при отметке отжиманий: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_press(message: Message):
    """Отметить сделанный пресс (вычитает из долга)"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer(
                "Использование: /пресс [количество]\n"
                "Пример: /пресс 20 — отметить 20 пресса.\n"
                "Напиши /пресс 0 — чтобы записаться в список (с завтра будешь в отчёте)."
            )
            return
        
        count = int(args[1])
        count = abs(count)
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += f" {message.from_user.last_name}"
        
        if count == 0:
            # Регистрация в списке: одна запись в оба типа, чтобы попал в отчёт
            try:
                db.add_pushups(user_id, username, 0, message.chat.id)
                db.add_abs(user_id, username, 0, message.chat.id)
                
                # Проверяем, что записи действительно созданы
                pushups_today = db.get_user_pushups_today(user_id, message.chat.id)
                abs_today = db.get_user_abs_today(user_id, message.chat.id)
                logger.info(f"Регистрация пользователя: user_id={user_id}, chat_id={message.chat.id}, pushups_today={pushups_today}, abs_today={abs_today}")
                
                await message.answer(
                    f"✅ {user_name}, ты в списке! С завтра будешь в утреннем отчёте с нормой 80 отжиманий и 80 пресса.",
                    reply_to_message_id=message.message_id
                )
            except Exception as e:
                logger.error(f"Ошибка при регистрации пользователя {user_id} в чате {message.chat.id}: {e}", exc_info=True)
                await message.answer(
                    f"❌ Произошла ошибка при регистрации. Попробуй еще раз.",
                    reply_to_message_id=message.message_id
                )
            return
        
        db.add_abs(user_id, username, -count, message.chat.id)
        debt_after = db.get_user_abs_debt(user_id, message.chat.id)
        await message.answer(
            f"Молодец, {user_name}! Сделано {count} пресс. Осталось: {debt_after}.",
            reply_to_message_id=message.message_id
        )
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при отметке пресс: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_join_invite(message: Message):
    """Отправить в чат приглашение: кто хочет участвовать — напишите /отжимания 0"""
    if message.chat.type == "private":
        await message.answer("Команда только для группы.")
        return
    await message.answer(
        "👋 <b>Кто хочет участвовать в челлендже (80 отжиманий + 80 пресса в день)</b> — "
        "напишите прямо сейчас в чат:\n\n"
        "<code>/отжимания 0</code>\n\n"
        "или\n\n"
        "<code>/пресс 0</code>\n\n"
        "Так вы попадёте в список. С завтра будете в утреннем отчёте с вашей нормой.",
        parse_mode='HTML'
    )


async def cmd_stats(message: Message):
    """Статистика за сегодня"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        stats = db.get_group_stats_today(message.chat.id)
        
        if not stats:
            await message.answer("📊 Пока нет статистики за сегодня. Начни тренироваться!")
            return
        
        text = "📊 <b>Статистика за сегодня:</b>\n\n"
        
        for user_stats in stats[:10]:  # Показываем топ-10
            text += f"👤 {user_stats['username']}\n"
            text += f"   💪 Отжимания: {user_stats['pushups']}\n"
            text += f"   🏋️ Пресс: {user_stats['abs']}\n"
            text += f"   📈 Всего: {user_stats['total']}\n\n"
        
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_my_stats(message: Message):
    """Личная статистика пользователя"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        user_id = message.from_user.id
        stats = db.get_user_stats(user_id, message.chat.id)
        
        if not stats:
            await message.answer("У тебя пока нет статистики в этом чате.")
            return
        
        text = f"📊 <b>Твоя статистика:</b>\n\n"
        text += f"💪 Всего отжиманий: {stats['total_pushups']}\n"
        text += f"🏋️ Всего упражнений на пресс: {stats['total_abs']}\n"
        text += f"📅 Дней тренировок: {stats['days']}\n"
        text += f"📈 Среднее в день: {stats['avg_per_day']:.1f}"
        
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при получении личной статистики: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_leaderboard(message: Message):
    """Таблица лидеров"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        leaders = db.get_leaderboard(message.chat.id)
        
        if not leaders:
            await message.answer("📊 Пока нет данных для таблицы лидеров.")
            return
        
        text = "🏆 <b>Таблица лидеров (все время):</b>\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, leader in enumerate(leaders[:10]):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {leader['username']}\n"
            text += f"   💪 Отжимания: {leader['total_pushups']}\n"
            text += f"   🏋️ Пресс: {leader['total_abs']}\n"
            text += f"   📈 Всего: {leader['total']}\n\n"
        
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при получении таблицы лидеров: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_test_report(message: Message):
    """Тест: отправить утренний отчёт (как в 8:00) — только в группе"""
    if message.chat.type == "private":
        await message.answer("Команда для теста отчёта работает только в группе. Добавь бота в тестовую группу и напиши /test_report там.")
        return
    try:
        from datetime import date, timedelta
        yesterday = date.today() - timedelta(days=1)
        stats_yesterday = db.get_group_stats_by_date(message.chat.id, yesterday)
        if stats_yesterday:
            await message.answer("Отправляю тестовый отчёт за вчера…")
            await send_daily_summary(message.chat.id)
        else:
            # Нет данных за вчера — шлём отчёт за сегодня (для теста)
            today = date.today()
            stats_today = db.get_group_stats_by_date(message.chat.id, today)
            if stats_today:
                await message.answer("Нет данных за вчера. Отправляю отчёт за сегодня (тест):")
                await send_daily_summary_for_date(message.chat.id, today)
            else:
                await message.answer(
                    "Нет данных ни за вчера, ни за сегодня. Сначала добавь отжимания или пресс: "
                    "/pushups 50 и /abs 50 (или /пресс 50), затем снова /test_report."
                )
    except Exception as e:
        logger.error(f"Ошибка при тестовом отчёте: {e}")
        await message.answer(f"Ошибка: {e}")


async def cmd_test_motivation(message: Message):
    """Тест: отправить мотивационное сообщение (как в 9:00 и 20:00) — только в группе"""
    if message.chat.type == "private":
        await message.answer("Команда для теста мотивации работает только в группе. Добавь бота в тестовую группу и напиши /test_motivation там.")
        return
    try:
        await send_motivational_message(message.chat.id)
    except Exception as e:
        logger.error(f"Ошибка при тестовой мотивации: {e}")
        await message.answer(f"Ошибка: {e}")


# Обработчики для личных сообщений (подсчет калорий)
async def cmd_add_meal(message: Message):
    """Добавление приема пищи"""
    if message.chat.type != "private":
        return
    
    await message.answer(
        "📝 Напиши что ты съел. Можешь указать:\n"
        "• Точные количества: <code>овсянка 200г, банан 1шт</code>\n"
        "• Или просто описание: <code>Съел борщ с хлебом и салат</code>\n"
        "• Или: <code>Завтрак: яичница из 2 яиц, тост с маслом</code>\n\n"
        "Я распознаю продукты и посчитаю калории автоматически!",
        parse_mode='HTML'
    )


def build_today_message(user_id: int):
    """Формирует текст и клавиатуру для «калории за сегодня» (как /today). Возвращает (text, reply_markup)."""
    stats = calorie_counter.get_today_stats(user_id)
    meals_list = calorie_counter.get_today_meals_list(user_id)
    limit = calorie_counter.get_daily_limit(user_id)
    
    text = f"📊 <b>Калории за сегодня:</b>\n\n"
    text += f"🔥 Съедено: {stats['calories']} ккал\n"
    
    if stats.get('proteins') is not None or stats.get('fats') is not None or stats.get('carbs') is not None:
        text += f"\n📊 <b>КБЖУ:</b>\n"
        if stats.get('proteins') is not None:
            text += f"🥩 Белки: {stats['proteins']} г\n"
        if stats.get('fats') is not None:
            text += f"🧈 Жиры: {stats['fats']} г\n"
        if stats.get('carbs') is not None:
            text += f"🍞 Углеводы: {stats['carbs']} г\n"
    
    if limit:
        remaining = limit - stats['calories']
        percentage = (stats['calories'] / limit) * 100
        text += f"\n🎯 Норма: {limit} ккал\n"
        text += f"📉 Осталось: {remaining} ккал ({100-percentage:.1f}%)\n"
        
        if percentage > 100:
            text += "⚠️ Превышена норма!"
        elif percentage > 90:
            text += "⚡ Почти достигнута норма!"
    else:
        text += "\n💡 Используй /set_limit чтобы установить дневную норму калорий"
    
    if meals_list:
        text += f"\n\n🍽️ <b>Список за сегодня ({len(meals_list)}):</b>\n"
        for i, meal in enumerate(meals_list, 1):
            name_short = (meal.get('meal_name', '—')[:35] + '…') if len(meal.get('meal_name', '')) > 35 else meal.get('meal_name', '—')
            text += f"{i}. {name_short} — {meal.get('calories', 0)} ккал\n"
        text += "\n👇 Нажми на кнопку ниже, чтобы удалить продукт:"
    
    reply_markup = None
    if meals_list:
        buttons = []
        for i, meal in enumerate(meals_list, 1):
            if 'id' not in meal or not meal.get('id'):
                continue
            name = meal.get('meal_name', '') or '—'
            short = (name[:15] + '…') if len(name) > 15 else name
            calories = meal.get('calories', 0)
            label = f"🗑 {i}. {short} ({calories} ккал)"
            if len(label) > 60:
                short = name[:10] + '…' if len(name) > 10 else name
                label = f"🗑 {i}. {short} ({calories})"
            callback_data = f"delete_meal_{meal['id']}"
            if len(callback_data.encode('utf-8')) > 64:
                continue
            buttons.append([InlineKeyboardButton(text=label, callback_data=callback_data)])
        
        if buttons:
            reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    return text, reply_markup


async def cmd_today(message: Message):
    """Статистика калорий за сегодня + список продуктов с кнопками удаления"""
    if message.chat.type != "private":
        return
    
    try:
        user_id = message.from_user.id
        text, reply_markup = build_today_message(user_id)
        await message.answer(text, parse_mode='HTML', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка при получении статистики калорий: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_week(message: Message):
    """Статистика калорий за неделю"""
    if message.chat.type != "private":
        return
    
    try:
        user_id = message.from_user.id
        stats = calorie_counter.get_week_stats(user_id)
        
        text = "📊 <b>Статистика за неделю:</b>\n\n"
        
        total_calories = sum(day['calories'] for day in stats['days'])
        avg_calories = total_calories / len(stats['days']) if stats['days'] else 0
        
        text += f"🔥 Всего за неделю: {total_calories} ккал\n"
        text += f"📈 Среднее в день: {avg_calories:.0f} ккал\n\n"
        
        for day in stats['days']:
            date_str = day['date'].strftime('%d.%m')
            text += f"📅 {date_str}: {day['calories']} ккал\n"
        
        await message.answer(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при получении статистики за неделю: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_set_limit(message: Message):
    """Установка дневной нормы калорий"""
    if message.chat.type != "private":
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /set_limit [количество]\nПример: /set_limit 2000")
            return
        
        limit = int(args[1])
        if limit <= 0:
            await message.answer("Норма должна быть больше нуля!")
            return
        
        user_id = message.from_user.id
        calorie_counter.set_daily_limit(user_id, limit)
        
        await message.answer(f"✅ Дневная норма установлена: {limit} ккал")
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при установке нормы: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def handle_photo(message: Message):
    """Обработка фото со штрих-кодом"""
    if message.chat.type != "private":
        return
    
    try:
        user_id = message.from_user.id
        
        # Получаем фото (берем самое большое)
        if not message.photo:
            await message.answer("❌ Фото не найдено. Отправь фото со штрих-кодом.")
            return
        
        photo = message.photo[-1]
        
        # Скачиваем фото
        import io
        from PIL import Image
        from pyzbar import pyzbar
        
        # Получаем информацию о файле и скачиваем
        photo_bytes = io.BytesIO()
        try:
            # Получаем информацию о файле
            file_info = await bot.get_file(photo.file_id)
            # Скачиваем через file_path (правильный способ в aiogram 3.x)
            await bot.download(file_info.file_path, destination=photo_bytes)
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла: {e}", exc_info=True)
            await message.answer(
                "❌ Не удалось скачать фото. Возможные причины:\n"
                "• Фото устарело (отправь заново, сразу после съемки)\n"
                "• Проблемы с сетью\n"
                "• Файл временно недоступен\n\n"
                "💡 Попробуй:\n"
                "• Отправить фото заново (сразу после съемки)\n"
                "• Или отправь штрих-код текстом (только цифры)"
            )
            return
        
        photo_bytes.seek(0)
        
        # Открываем изображение
        try:
            image = Image.open(photo_bytes)
        except Exception as e:
            logger.error(f"Ошибка при открытии изображения: {e}")
            await message.answer(
                "❌ Не удалось обработать изображение. Убедись, что отправлено фото (не документ)."
            )
            return
        
        # Распознаем штрих-код
        barcodes = pyzbar.decode(image)
        
        if not barcodes:
            await message.answer(
                "❌ Штрих-код не найден на фото.\n\n"
                "Убедись, что:\n"
                "• Штрих-код четко виден\n"
                "• Фото хорошо освещено\n"
                "• Штрих-код не размыт"
            )
            return
        
        # Берем первый найденный штрих-код
        barcode_data = barcodes[0].data.decode('utf-8')
        barcode_type = barcodes[0].type
        
        logger.info(f"Найден штрих-код: {barcode_data} (тип: {barcode_type})")
        
        # Отправляем сообщение о поиске
        search_msg = await message.answer(f"🔍 Найден штрих-код: <code>{barcode_data}</code>\nИщу продукт...", parse_mode='HTML')
        
        # Функция для обновления статуса поиска
        async def update_status(text: str):
            try:
                await search_msg.edit_text(f"🔍 Найден штрих-код: <code>{barcode_data}</code>\n{text}", parse_mode='HTML')
            except Exception as e:
                logger.debug(f"Не удалось обновить статус: {e}")
        
        # Ищем продукт по штрих-коду (только информацию, без добавления)
        product_info = await calorie_counter.get_product_info_by_barcode(barcode_data, status_callback=update_status)
        
        if product_info.get('success'):
            # Формируем ответ с КБЖУ
            response = f"✅ Продукт найден!\n\n"
            response += f"📦 <b>{product_info['name']}</b>\n"
            if product_info.get('brand'):
                response += f"🏷 Бренд: {product_info['brand']}\n"
            response += "\n📊 <b>КБЖУ на 100г:</b>\n"
            
            calories = product_info.get('calories_per_100g')
            proteins = product_info.get('proteins_per_100g')
            fats = product_info.get('fats_per_100g')
            carbs = product_info.get('carbs_per_100g')
            
            if calories:
                response += f"🔥 Калории: {calories} ккал\n"
            if proteins is not None:
                response += f"🥩 Белки: {proteins} г\n"
            if fats is not None:
                response += f"🧈 Жиры: {fats} г\n"
            if carbs is not None:
                response += f"🍞 Углеводы: {carbs} г\n"
            
            # Если вес продукта известен, показываем КБЖУ для всего продукта
            weight = product_info.get('weight')
            if weight:
                response += f"\n📏 Вес продукта: {int(weight)}г\n"
                response += f"<b>КБЖУ для всего продукта:</b>\n"
                if calories:
                    total_cal = int((calories / 100) * weight)
                    response += f"🔥 Калории: {total_cal} ккал\n"
                if proteins is not None:
                    total_prot = round((proteins / 100) * weight, 1)
                    response += f"🥩 Белки: {total_prot} г\n"
                if fats is not None:
                    total_fats = round((fats / 100) * weight, 1)
                    response += f"🧈 Жиры: {total_fats} г\n"
                if carbs is not None:
                    total_carbs = round((carbs / 100) * weight, 1)
                    response += f"🍞 Углеводы: {total_carbs} г\n"
            
            if product_info.get('source'):
                response += f"\n📡 Источник: {product_info['source']}\n"
            
            response += f"\n💡 Напиши <code>+{barcode_data}</code> чтобы добавить этот продукт в дневник"
            
            await search_msg.edit_text(response, parse_mode='HTML')
        else:
            # Пробуем найти хотя бы название продукта через другие источники
            await search_msg.edit_text("🔍 Ищу в других источниках...")
            
            # Функция для обновления статуса поиска
            async def update_status_retry(text: str):
                try:
                    await search_msg.edit_text(f"🔍 Найден штрих-код: <code>{barcode_data}</code>\n{text}", parse_mode='HTML')
                except Exception as e:
                    logger.debug(f"Не удалось обновить статус: {e}")
            
            # Пробуем еще раз через все источники
            product_info = await calorie_counter.get_product_info_by_barcode(barcode_data, status_callback=update_status_retry)
            
            if product_info.get('success'):
                # Если нашли хотя бы название, показываем его
                response = f"📦 <b>{product_info['name']}</b>\n"
                if product_info.get('brand'):
                    response += f"🏷 Бренд: {product_info['brand']}\n"
                
                calories = product_info.get('calories_per_100g')
                proteins = product_info.get('proteins_per_100g')
                fats = product_info.get('fats_per_100g')
                carbs = product_info.get('carbs_per_100g')
                
                if calories or proteins is not None or fats is not None or carbs is not None:
                    response += "\n📊 <b>КБЖУ на 100г:</b>\n"
                    if calories:
                        response += f"🔥 Калории: {calories} ккал\n"
                    if proteins is not None:
                        response += f"🥩 Белки: {proteins} г\n"
                    if fats is not None:
                        response += f"🧈 Жиры: {fats} г\n"
                    if carbs is not None:
                        response += f"🍞 Углеводы: {carbs} г\n"
                else:
                    response += "\n⚠️ КБЖУ не найдено в базе данных.\n"
                    response += "Можешь добавить продукт вручную, описав что ты съел.\n"
                
                if product_info.get('source'):
                    response += f"\n📡 Источник: {product_info['source']}\n"
                
                response += f"\n💡 Напиши <code>+{barcode_data}</code> чтобы добавить этот продукт в дневник"
                
                await search_msg.edit_text(response, parse_mode='HTML')
            else:
                await search_msg.edit_text(
                    f"❌ Продукт с штрих-кодом <code>{barcode_data}</code> не найден в базах данных.\n\n"
                    f"Попробуй:\n"
                    f"• Проверить правильность штрих-кода\n"
                    f"• Или добавь продукт вручную, описав что ты съел\n"
                    f"• Или отправь штрих-код текстом",
                    parse_mode='HTML'
                )
            
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при обработке фото.\n\n"
            "Попробуй:\n"
            "• Сделать фото заново\n"
            "• Убедиться, что штрих-код четко виден\n"
            "• Или добавь продукт вручную, описав что ты съел"
        )


async def handle_web_app_callback(callback: CallbackQuery):
    """Обработка данных от Telegram Web App через callback_query"""
    try:
        import json
        
        # Проверяем, это удаление продукта или данные от Web App
        if callback.data.startswith('delete_meal_'):
            # Обработка удаления продукта
            meal_id_str = callback.data.replace('delete_meal_', '')
            try:
                if not meal_id_str or meal_id_str == '':
                    logger.warning(f"Пустой meal_id в callback: {callback.data}")
                    await callback.answer("Ошибка: не указан ID продукта")
                    return
                
                meal_id = int(meal_id_str)
                user_id = callback.from_user.id
                
                logger.info(f"Удаление продукта: user_id={user_id}, meal_id={meal_id}")
                
                # Получаем информацию о продукте перед удалением
                try:
                    conn = calorie_counter.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT meal_name, calories, proteins, fats, carbs, source FROM meals
                        WHERE id = ? AND user_id = ?
                    """, (meal_id, user_id))
                    meal_info = cursor.fetchone()
                    conn.close()
                    
                    logger.info(f"Информация о продукте: {meal_info}")
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о продукте: {e}", exc_info=True)
                    meal_info = None
                
                # Удаляем продукт
                deleted_meal = calorie_counter.delete_meal(user_id, meal_id)
                
                if deleted_meal:
                    try:
                        await callback.answer("Продукт удален")
                        # Обновляем то же сообщение: показываем заново полный список как /today (статистика + список + кнопки)
                        text, reply_markup = build_today_message(user_id)
                        try:
                            await callback.message.edit_text(text, parse_mode='HTML', reply_markup=reply_markup)
                        except Exception as edit_err:
                            logger.warning(f"Не удалось отредактировать сообщение: {edit_err}")
                            await callback.message.answer(text, parse_mode='HTML', reply_markup=reply_markup)
                    except Exception as e:
                        logger.error(f"Ошибка при отправке ответа об удалении: {e}", exc_info=True)
                        await callback.answer("Продукт удален")
                else:
                    logger.warning(f"Не удалось удалить продукт: user_id={user_id}, meal_id={meal_id}")
                    await callback.answer("Не удалось удалить продукт")
            except ValueError as e:
                logger.error(f"Ошибка при парсинге meal_id: {e}, callback.data={callback.data}")
                await callback.answer("Ошибка: неверный ID продукта")
            except Exception as e:
                logger.error(f"Ошибка при удалении продукта: {e}", exc_info=True)
                await callback.answer("Произошла ошибка при удалении")
                try:
                    await callback.message.answer("❌ Произошла ошибка при удалении продукта")
                except:
                    pass
            return
        
        # Данные от Web App приходят в callback_query.data
        data_str = callback.data
        if not data_str:
            await callback.answer("Ошибка: нет данных")
            return
        
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            # Если это не JSON, возможно это просто штрих-код
            data = {'action': 'add_product', 'barcode': data_str}
        
        if data.get('action') == 'add_product' and data.get('barcode'):
            user_id = callback.from_user.id
            barcode = data['barcode']
            
            await callback.answer("Ищу продукт...")
            
            # Создаем сообщение для статуса поиска
            status_msg = await callback.message.answer("🔍 Ищу продукт...")
            
            # Функция для обновления статуса поиска
            async def update_status(text: str):
                try:
                    await status_msg.edit_text(text, parse_mode='HTML')
                except Exception as e:
                    logger.debug(f"Не удалось обновить статус: {e}")
            
            # Сначала получаем информацию о продукте
            product_info = await calorie_counter.get_product_info_by_barcode(barcode, status_callback=update_status)
            
            if product_info.get('success'):
                # Добавляем продукт в дневник
                result = await calorie_counter.add_meal_from_barcode(user_id, barcode, status_callback=update_status)
                
                if result.get('success'):
                    response = f"✅ Продукт добавлен из сканера!\n\n"
                    response += f"📦 <b>{result['product_name']}</b>\n"
                    if result.get('brand'):
                        response += f"🏷 Бренд: {result['brand']}\n"
                    response += f"📊 Штрих-код: <code>{barcode}</code>\n"
                    
                    calories = result.get('calories', 0)
                    
                    # Показываем КБЖУ если есть
                    if calories or result.get('proteins') is not None or result.get('fats') is not None or result.get('carbs') is not None:
                        response += f"\n📊 <b>КБЖУ:</b>\n"
                        if calories:
                            response += f"🔥 Калории: {calories} ккал\n"
                        if result.get('proteins') is not None:
                            response += f"🥩 Белки: {result['proteins']} г\n"
                        if result.get('fats') is not None:
                            response += f"🧈 Жиры: {result['fats']} г\n"
                        if result.get('carbs') is not None:
                            response += f"🍞 Углеводы: {result['carbs']} г\n"
                    
                    # Показываем источник информации
                    source = result.get('source') or result.get('product_info', {}).get('source')
                    if source:
                        response += f"\n📡 Источник: {source}\n"
                    
                    response += f"\n📊 Всего за сегодня: {result['total_today']} ккал"
                    
                    limit = calorie_counter.get_daily_limit(user_id)
                    if limit:
                        remaining = limit - result['total_today']
                        percentage = (result['total_today'] / limit) * 100
                        response += f"\n🎯 Осталось: {remaining} ккал ({100-percentage:.1f}%)"
                    
                    # Добавляем кнопку для удаления только если есть meal_id
                    meal_id = result.get('meal_id')
                    if meal_id:
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="🗑 Удалить этот продукт",
                                callback_data=f"delete_meal_{meal_id}"
                            )]
                        ])
                        await callback.message.answer(response, parse_mode='HTML', reply_markup=keyboard)
                    else:
                        await callback.message.answer(response, parse_mode='HTML')
                else:
                    # Показываем информацию о продукте даже если не удалось добавить
                    response = f"📦 <b>{product_info.get('name', 'Продукт')}</b>\n"
                    response += f"📊 Штрих-код: <code>{barcode}</code>\n\n"
                    
                    if product_info.get('calories_per_100g'):
                        response += f"🔥 Калории: {product_info['calories_per_100g']} ккал/100г\n"
                    if product_info.get('proteins_per_100g'):
                        response += f"🥩 Белки: {product_info['proteins_per_100g']} г/100г\n"
                    if product_info.get('fats_per_100g'):
                        response += f"🧈 Жиры: {product_info['fats_per_100g']} г/100г\n"
                    if product_info.get('carbs_per_100g'):
                        response += f"🍞 Углеводы: {product_info['carbs_per_100g']} г/100г\n"
                    
                    response += f"\n❌ Не удалось добавить в дневник.\n"
                    response += f"💡 Попробуй написать боту: <code>+{barcode}</code>"
                    
                    await callback.message.answer(response, parse_mode='HTML')
            else:
                # Продукт не найден, но штрих-код распознан
                response = f"📊 Штрих-код распознан: <code>{barcode}</code>\n\n"
                response += f"❌ Продукт не найден в базах данных.\n\n"
                response += f"💡 Попробуй:\n"
                response += f"• Добавить продукт вручную, описав что ты съел\n"
                response += f"• Или написать боту: <code>+{barcode}</code> для повторной попытки\n"
                response += f"• Или отправить фото штрих-кода боту"
                
                await callback.message.answer(response, parse_mode='HTML')
        else:
            await callback.answer("Неизвестное действие")
    except Exception as e:
        logger.error(f"Ошибка при обработке данных от Web App: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")
        await callback.message.answer(
            "❌ Произошла ошибка при обработке данных от сканера.\n\n"
            "💡 Попробуй отправить штрих-код текстом боту или фото штрих-кода."
        )


async def handle_web_app_data(message: Message):
    """Обработка данных от Telegram Web App (резервный метод)"""
    # В aiogram 3.x данные от Web App обычно приходят через callback_query
    # Этот обработчик может не понадобиться, но оставим на всякий случай
    pass


async def handle_text(message: Message):
    """Обработка текстовых сообщений"""
    logger.info(f"[handle_text] Получено сообщение: chat_type={message.chat.type}, text={message.text}, from_user={message.from_user.id if message.from_user else None}")
    
    if message.chat.type == "private":
        # Проверяем, что есть текст
        if not message.text:
            logger.debug("[handle_text] Нет текста в сообщении, выходим")
            return
        
        # Обработка сообщений о еде в личке
        user_id = message.from_user.id
        text = message.text.strip()
        text_lower = text.lower()
        
        logger.info(f"[handle_text] Обработка текстового сообщения от {user_id}: '{text}'")
        
        # Проверка: если сообщение состоит только из цифр (штрих-код) или штрих-код с "+" для добавления
        barcode = None
        add_to_diary = False
        
        if text.startswith('+') and text[1:].strip().isdigit():
            barcode = text[1:].strip()
            add_to_diary = True
        elif text.endswith('+') and text[:-1].strip().isdigit():
            barcode = text[:-1].strip()
            add_to_diary = True
        elif text.isdigit() and len(text) >= 8:  # Штрих-коды обычно от 8 до 13 цифр
            barcode = text
            add_to_diary = False
        
        if barcode:
            try:
                if add_to_diary:
                    # Добавляем продукт в дневник
                    search_msg = await message.answer("🔍 Ищу и добавляю продукт...")
                    
                    # Функция для обновления статуса поиска
                    async def update_status(text: str):
                        try:
                            await search_msg.edit_text(text, parse_mode='HTML')
                        except Exception as e:
                            logger.debug(f"Не удалось обновить статус: {e}")
                    
                    result = await calorie_counter.add_meal_from_barcode(user_id, barcode, status_callback=update_status)
                    
                    if result.get('success'):
                        product_info = result.get('product_info', {})
                        response = f"✅ Продукт добавлен!\n\n"
                        response += f"📦 <b>{result['product_name']}</b>\n"
                        if result.get('brand'):
                            response += f"🏷 Бренд: {result['brand']}\n"
                        # Показываем КБЖУ добавленного продукта
                        response += f"\n📊 <b>КБЖУ добавлено:</b>\n"
                        response += f"🔥 Калории: {result['calories']} ккал\n"
                        if result.get('proteins') is not None:
                            response += f"🥩 Белки: {result['proteins']} г\n"
                        if result.get('fats') is not None:
                            response += f"🧈 Жиры: {result['fats']} г\n"
                        if result.get('carbs') is not None:
                            response += f"🍞 Углеводы: {result['carbs']} г\n"
                        
                        # Показываем источник информации
                        source = product_info.get('source') or result.get('source')
                        if source:
                            response += f"\n📡 Источник: {source}\n"
                        
                        response += f"\n📊 Всего за сегодня: {result['total_today']} ккал"
                        
                        # Показываем КБЖУ на 100г если есть
                        if product_info.get('proteins_per_100g') is not None or product_info.get('fats_per_100g') is not None or product_info.get('carbs_per_100g') is not None:
                            response += f"\n\n📊 <b>КБЖУ на 100г:</b>\n"
                            if product_info.get('calories_per_100g'):
                                response += f"🔥 Калории: {product_info['calories_per_100g']} ккал\n"
                            if product_info.get('proteins_per_100g') is not None:
                                response += f"🥩 Белки: {product_info['proteins_per_100g']} г\n"
                            if product_info.get('fats_per_100g') is not None:
                                response += f"🧈 Жиры: {product_info['fats_per_100g']} г\n"
                            if product_info.get('carbs_per_100g') is not None:
                                response += f"🍞 Углеводы: {product_info['carbs_per_100g']} г\n"
                        
                        limit = calorie_counter.get_daily_limit(user_id)
                        if limit:
                            remaining = limit - result['total_today']
                            percentage = (result['total_today'] / limit) * 100
                            response += f"\n🎯 Осталось: {remaining} ккал ({100-percentage:.1f}%)"
                        
                        # Добавляем кнопку для удаления только если есть meal_id
                        meal_id = result.get('meal_id')
                        if meal_id:
                            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(
                                    text="🗑 Удалить этот продукт",
                                    callback_data=f"delete_meal_{meal_id}"
                                )]
                            ])
                            await search_msg.edit_text(response, parse_mode='HTML', reply_markup=keyboard)
                        else:
                            logger.warning(f"meal_id отсутствует в результате: {result}")
                            await search_msg.edit_text(response, parse_mode='HTML')
                    else:
                        await search_msg.edit_text(
                            result.get('message', '❌ Продукт не найден в базе данных.')
                        )
                else:
                    # Только показываем информацию о продукте
                    search_msg = await message.answer("🔍 Ищу продукт по штрих-коду...")
                    
                    # Функция для обновления статуса поиска
                    async def update_status(text: str):
                        try:
                            await search_msg.edit_text(text, parse_mode='HTML')
                        except Exception as e:
                            logger.debug(f"Не удалось обновить статус: {e}")
                    
                    product_info = await calorie_counter.get_product_info_by_barcode(barcode, status_callback=update_status)
                    
                    if product_info.get('success'):
                        # Проверяем, что название продукта валидное и не пустое
                        product_name = product_info.get('name', '').strip()
                        if not product_name or product_name.lower() in ['поиск', 'search', 'product', 'товар', 'неизвестный', 'unknown']:
                            # Если название невалидное, пробуем найти в других источниках
                            logger.warning(f"Найдено невалидное название продукта: {product_name}, продолжаем поиск")
                            product_info = None
                        else:
                            # Формируем ответ с КБЖУ
                            response = f"📦 <b>{product_name}</b>\n"
                            if product_info.get('brand'):
                                response += f"🏷 Бренд: {product_info['brand']}\n"
                            
                            calories = product_info.get('calories_per_100g')
                            proteins = product_info.get('proteins_per_100g')
                            fats = product_info.get('fats_per_100g')
                            carbs = product_info.get('carbs_per_100g')
                            
                            # Показываем КБЖУ только если есть хотя бы одно значение
                            if calories or proteins is not None or fats is not None or carbs is not None:
                                response += "\n📊 <b>КБЖУ на 100г:</b>\n"
                                if calories:
                                    response += f"🔥 Калории: {calories} ккал\n"
                                if proteins is not None:
                                    response += f"🥩 Белки: {proteins} г\n"
                                if fats is not None:
                                    response += f"🧈 Жиры: {fats} г\n"
                                if carbs is not None:
                                    response += f"🍞 Углеводы: {carbs} г\n"
                                
                                # Если вес продукта известен, показываем КБЖУ для всего продукта
                                weight = product_info.get('weight')
                                if weight:
                                    response += f"\n📏 Вес продукта: {int(weight)}г\n"
                                    response += f"<b>КБЖУ для всего продукта:</b>\n"
                                    if calories:
                                        total_cal = int((calories / 100) * weight)
                                        response += f"🔥 Калории: {total_cal} ккал\n"
                                    if proteins is not None:
                                        total_prot = round((proteins / 100) * weight, 1)
                                        response += f"🥩 Белки: {total_prot} г\n"
                                    if fats is not None:
                                        total_fats = round((fats / 100) * weight, 1)
                                        response += f"🧈 Жиры: {total_fats} г\n"
                                    if carbs is not None:
                                        total_carbs = round((carbs / 100) * weight, 1)
                                        response += f"🍞 Углеводы: {total_carbs} г\n"
                            else:
                                # Если КБЖУ нет, но название есть
                                response += "\n⚠️ КБЖУ не найдено в базе данных.\n"
                                response += "Можешь добавить продукт вручную, описав что ты съел.\n"
                            
                            if product_info.get('source'):
                                response += f"\n📡 Источник: {product_info['source']}\n"
                            
                            response += f"\n💡 Напиши <code>+{barcode}</code> чтобы добавить этот продукт в дневник"
                            
                            await search_msg.edit_text(response, parse_mode='HTML')
                            return
                    
                    # Если не нашли или название невалидное, пробуем найти в других источниках
                    if not product_info or not product_info.get('success'):
                        # Пробуем найти хотя бы название продукта через другие источники
                        await search_msg.edit_text("🔍 Ищу в других источниках...")
                        
                        # Функция для обновления статуса поиска
                        async def update_status_retry(text: str):
                            try:
                                await search_msg.edit_text(text, parse_mode='HTML')
                            except Exception as e:
                                logger.debug(f"Не удалось обновить статус: {e}")
                        
                        # Пробуем еще раз через все источники
                        product_info = await calorie_counter.get_product_info_by_barcode(barcode, status_callback=update_status_retry)
                        
                        if product_info and product_info.get('success'):
                            product_name = product_info.get('name', '').strip()
                            if product_name and product_name.lower() not in ['поиск', 'search', 'product', 'товар', 'неизвестный', 'unknown']:
                                # Если нашли хотя бы название, показываем его
                                response = f"📦 <b>{product_name}</b>\n"
                                if product_info.get('brand'):
                                    response += f"🏷 Бренд: {product_info['brand']}\n"
                                
                                calories = product_info.get('calories_per_100g')
                                proteins = product_info.get('proteins_per_100g')
                                fats = product_info.get('fats_per_100g')
                                carbs = product_info.get('carbs_per_100g')
                                
                                if calories or proteins is not None or fats is not None or carbs is not None:
                                    response += "\n📊 <b>КБЖУ на 100г:</b>\n"
                                    if calories:
                                        response += f"🔥 Калории: {calories} ккал\n"
                                    if proteins is not None:
                                        response += f"🥩 Белки: {proteins} г\n"
                                    if fats is not None:
                                        response += f"🧈 Жиры: {fats} г\n"
                                    if carbs is not None:
                                        response += f"🍞 Углеводы: {carbs} г\n"
                                else:
                                    response += "\n⚠️ КБЖУ не найдено в базе данных.\n"
                                    response += "Можешь добавить продукт вручную, описав что ты съел.\n"
                                
                                if product_info.get('source'):
                                    response += f"\n📡 Источник: {product_info['source']}\n"
                                
                                response += f"\n💡 Напиши <code>+{barcode}</code> чтобы добавить этот продукт в дневник"
                                
                                await search_msg.edit_text(response, parse_mode='HTML')
                            else:
                                await search_msg.edit_text(
                                    f"❌ Продукт с штрих-кодом <code>{barcode}</code> не найден в базах данных.\n\n"
                                    f"Попробуй:\n"
                                    f"• Проверить правильность штрих-кода\n"
                                    f"• Или добавь продукт вручную, описав что ты съел\n"
                                    f"• Или отправь фото штрих-кода",
                                    parse_mode='HTML'
                                )
                        else:
                            await search_msg.edit_text(
                                f"❌ Продукт с штрих-кодом <code>{barcode}</code> не найден в базах данных.\n\n"
                                f"Попробуй:\n"
                                f"• Проверить правильность штрих-кода\n"
                                f"• Или добавь продукт вручную, описав что ты съел\n"
                                f"• Или отправь фото штрих-кода",
                                parse_mode='HTML'
                            )
            except Exception as e:
                logger.error(f"Ошибка при поиске по штрих-коду: {e}", exc_info=True)
                await message.answer("Произошла ошибка при поиске продукта. Попробуй еще раз.")
            return
        
        
        # Простая проверка - если сообщение содержит слова про еду или числа с единицами измерения
        food_keywords = ['г', 'кг', 'мл', 'л', 'шт', 'штук', 'штуки', 'калори', 'ккал', 'еда', 'съел', 'съела', 
                        'завтрак', 'обед', 'ужин', 'поел', 'поела', 'съела', 'съел', 'конфет', 'конфетка',
                        'пельмен', 'вареник', 'блин', 'борщ', 'суп', 'салат', 'хлеб', 'мясо', 'рыба', 'куриц',
                        'яйц', 'молок', 'творог', 'сыр', 'йогурт', 'кефир', 'овсянк', 'гречк', 'рис', 'макарон',
                        'картошк', 'овощ', 'фрукт', 'яблок', 'банан', 'апельсин', 'мандарин', 'помидор', 'огурц',
                        'морков', 'капуст', 'лук', 'чеснок', 'перец', 'петрушк', 'укроп', 'сметан', 'майонез',
                        'масло', 'сахар', 'соль', 'перец', 'специ', 'соус', 'кетчуп', 'горчиц', 'хрен',
                        'колбас', 'сосиск', 'ветчин', 'бекон', 'свинин', 'говядин', 'баран', 'индейк',
                        'лосос', 'тунец', 'селедк', 'икр', 'креветк', 'кальмар', 'миди', 'краб',
                        'творог', 'сметан', 'сливк', 'масло', 'маргарин', 'спред', 'сыр', 'брынз', 'фет',
                        'йогурт', 'кефир', 'ряженк', 'простокваш', 'варенец', 'тан', 'айран',
                        'хлеб', 'батон', 'булк', 'бутерброд', 'тост', 'сухар', 'гренк', 'круассан',
                        'печень', 'торт', 'пирожн', 'конфет', 'шоколад', 'вафел', 'печень', 'кекс', 'маффин',
                        'морожен', 'желе', 'пудинг', 'мусс', 'крем', 'безе', 'зефир', 'мармелад', 'халв',
                        'орех', 'миндал', 'фундук', 'грецк', 'кешью', 'фисташк', 'арахис', 'семечк', 'кунжут',
                        'изюм', 'кураг', 'чернослив', 'финик', 'инжир', 'клюкв', 'брусник', 'облепих',
                        'чай', 'кофе', 'какао', 'сок', 'компот', 'морс', 'кисел', 'лимонад', 'газировк',
                        'пиво', 'вино', 'водк', 'коньяк', 'виски', 'ром', 'джин', 'ликер', 'шампанск',
                        'вод', 'минералк', 'газировк', 'энергетик', 'спортпит', 'протеин', 'гейнер', 'креатин', 
                        'конфеты', 'батончик', 'печенье', 'йогурт', 'молоко', 'хлеб', 'сыр', 'мясо', 'рыба',
                        'овощ', 'фрукт', 'яблоко', 'банан', 'овсянка', 'каша', 'суп', 'борщ', 'салат']
        
        # Проверяем наличие ключевых слов или паттернов с числами и единицами измерения
        has_food_keyword = any(keyword in text_lower for keyword in food_keywords)
        # Улучшенный паттерн для распознавания количества (поддерживает "250гр", "250 г", "250г" и т.д.)
        has_number_with_unit = bool(re.search(r'\d+\s*(г|кг|мл|л|шт|штук|штуки|грамм|граммов|килограмм|килограммов|миллилитр|литр|штука)', text_lower))
        
        # Находим какие именно ключевые слова найдены
        found_keywords = [kw for kw in food_keywords if kw in text_lower]
        
        logger.info(f"[handle_text] Проверка текста '{text}': has_food_keyword={has_food_keyword}, has_number_with_unit={has_number_with_unit}, found_keywords={found_keywords}")
        
        if has_food_keyword or has_number_with_unit:
            logger.info(f"[handle_text] Текст распознан как сообщение о еде, начинаю парсинг")
            try:
                logger.info(f"Обрабатываю сообщение о еде: {message.text}")
                result = await calorie_counter.add_meal_from_text(user_id, message.text)
                
                if result['success']:
                    response = f"✅ Добавлено: {result['calories']} ккал\n"
                    response += f"📦 {result.get('meal_name', 'Продукт')}\n"
                    
                    # Показываем КБЖУ если есть
                    if result.get('proteins') is not None or result.get('fats') is not None or result.get('carbs') is not None:
                        response += f"\n📊 <b>КБЖУ:</b>\n"
                        response += f"🔥 Калории: {result['calories']} ккал\n"
                        if result.get('proteins') is not None:
                            response += f"🥩 Белки: {result['proteins']} г\n"
                        if result.get('fats') is not None:
                            response += f"🧈 Жиры: {result['fats']} г\n"
                        if result.get('carbs') is not None:
                            response += f"🍞 Углеводы: {result['carbs']} г\n"
                    
                    # Показываем источник информации
                    source = result.get('source', 'Неизвестно')
                    if source:
                        response += f"\n📡 Источник: {source}\n"
                    
                    response += f"\n📊 Всего за сегодня: {result['total_today']} ккал"
                    
                    limit = calorie_counter.get_daily_limit(user_id)
                    if limit:
                        remaining = limit - result['total_today']
                        percentage = (result['total_today'] / limit) * 100
                        response += f"\n🎯 Осталось: {remaining} ккал ({100-percentage:.1f}%)"
                    
                    # Добавляем кнопку для удаления только если есть meal_id
                    meal_id = result.get('meal_id')
                    if meal_id:
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="🗑 Удалить этот продукт",
                                callback_data=f"delete_meal_{meal_id}"
                            )]
                        ])
                        await message.answer(response, parse_mode='HTML', reply_markup=keyboard)
                    else:
                        logger.warning(f"meal_id отсутствует в результате: {result}")
                        await message.answer(response, parse_mode='HTML')
                else:
                    error_message = result.get('message', 'Не удалось распознать продукты.')
                    await message.answer(
                        f"❌ {error_message}\n\n"
                        f"💡 Попробуй:\n"
                        f"• Указать количество явно: <code>овсянка 200г, банан 1шт</code>\n"
                        f"• Или отправь штрих-код продукта (только цифры)",
                        parse_mode='HTML'
                    )
            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения о еде: {e}", exc_info=True)
                await message.answer("Произошла ошибка. Попробуй еще раз.")
        else:
            logger.info(f"[handle_text] Текст '{text}' не распознан как сообщение о еде (has_food_keyword={has_food_keyword}, has_number_with_unit={has_number_with_unit})")


async def main():
    """Главная функция"""
    global bot, dp, db, motivator, calorie_counter
    
    # Загрузка токена из переменной окружения или файла
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    
    if not token:
        logger.error("BOT_TOKEN не найден! Создай файл .env с BOT_TOKEN=твой_токен")
        return
    
    bot = Bot(token=token)
    dp = Dispatcher()
    
    # Устанавливаем кнопку меню для Mini App (большая кнопка слева внизу в ЛС)
    web_app_url = os.getenv("WEB_APP_URL", "https://your-domain.com/webapp/index.html")
    if web_app_url != "https://your-domain.com/webapp/index.html":
        try:
            menu_button = MenuButtonWebApp(
                text="📷 Сканер",
                web_app=WebAppInfo(url=web_app_url)
            )
            # Устанавливаем кнопку меню для всех пользователей (chat_id=None означает глобальная настройка)
            await bot.set_chat_menu_button(menu_button=menu_button)
            logger.info("✅ Кнопка меню бота установлена (будет видна в ЛС)")
        except Exception as e:
            logger.warning(f"Не удалось установить кнопку меню: {e}")
            logger.warning("Кнопка меню будет доступна только через команду /scanner")
    else:
        logger.warning("WEB_APP_URL не настроен, кнопка меню не будет установлена")
    
    # Инициализация модулей
    db = Database()
    # Инициализируем Motivator с API ключом из переменных окружения
    groq_api_key = os.getenv("GROQ_API_KEY")
    
    # Инициализируем Groq клиент для использования в Motivator и CalorieCounter
    from groq import Groq
    groq_client = None
    
    if groq_api_key:
        try:
            # Инициализируем Groq клиент (в версии 1.0.0 проблема с proxies решена)
            groq_client = Groq(api_key=groq_api_key)
            logger.info("✅ Groq клиент инициализирован")
            
            # Проверяем что клиент работает, делая тестовый запрос
            try:
                test_response = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=5
                )
                logger.info("✅ Groq клиент работает для подсчета калорий")
            except Exception as test_error:
                logger.warning(f"Groq клиент создан, но тестовый запрос не прошел: {test_error}")
                logger.warning("Клиент будет использоваться без тестового запроса")
                # Не обнуляем groq_client, возможно тестовый запрос просто не нужен
        except Exception as e:
            logger.error(f"Ошибка при инициализации Groq клиента: {e}", exc_info=True)
            groq_client = None
    else:
        logger.warning("GROQ_API_KEY не найден в переменных окружения. Подсчет калорий будет использовать базовый метод.")
    
    # Логируем финальный статус Groq клиента
    if groq_client:
        logger.info("✅ Groq клиент готов к использованию")
    else:
        logger.error("❌ Groq клиент недоступен! Текстовые сообщения о еде не будут обрабатываться.")
    
    motivator = Motivator(api_key=groq_api_key)
    calorie_counter = CalorieCounter(groq_client=groq_client)
    
    # Регистрация обработчиков
    # ВАЖНО: Порядок регистрации имеет значение!
    # Сначала регистрируем команды (они имеют приоритет)
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_scanner, Command("scanner"))
    dp.message.register(cmd_pushups, Command("pushups"))
    dp.message.register(cmd_abs, Command("abs"))
    dp.message.register(cmd_otzhimaniya, Command("отжимания"))
    dp.message.register(cmd_press, Command("пресс"))
    dp.message.register(cmd_join_invite, Command("записаться"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_my_stats, Command("my_stats"))
    dp.message.register(cmd_leaderboard, Command("leaderboard"))
    dp.message.register(cmd_test_report, Command("test_report"))
    dp.message.register(cmd_test_motivation, Command("test_motivation"))
    dp.message.register(cmd_add_meal, Command("add_meal"))
    dp.message.register(cmd_today, Command("today"))
    dp.message.register(cmd_week, Command("week"))
    dp.message.register(cmd_set_limit, Command("set_limit"))
    
    # Затем регистрируем специфичные обработчики (фото)
    dp.message.register(handle_photo, F.photo)
    
    # И только потом общий обработчик текста (он должен быть последним)
    # чтобы обрабатывать все текстовые сообщения, которые не обработаны командами
    dp.message.register(handle_text)
    
    # Обработчик данных от Web App (может быть не нужен, но оставим)
    dp.message.register(handle_web_app_data)
    
    # Обработчик callback_query для Web App
    dp.callback_query.register(handle_web_app_callback)
    
    # Настройка планировщика для мотивирующих сообщений
    await setup_scheduler()
    
    # Запускаем HTTP сервер для webapp (статики)
    async def webapp_handler(request):
        """Обработчик для раздачи webapp/index.html"""
        webapp_path = os.path.join(script_dir, 'webapp', 'index.html')
        try:
            with open(webapp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return Response(text=content, content_type='text/html')
        except FileNotFoundError:
            return Response(text='WebApp not found', status=404)
    
    # Создаём HTTP сервер для webapp
    app = web.Application()
    app.router.add_get('/webapp/index.html', webapp_handler)
    app.router.add_get('/webapp/', webapp_handler)
    
    # Получаем порт из переменной окружения (Railway автоматически задаёт PORT)
    port = int(os.getenv('PORT', 8000))
    
    # Запускаем HTTP сервер в фоне
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✅ HTTP сервер запущен на порту {port}. WebApp доступен по: http://0.0.0.0:{port}/webapp/index.html")
    
    # Получаем публичный URL (Railway даёт его в переменной RAILWAY_PUBLIC_DOMAIN или можно использовать PORT)
    railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if railway_domain:
        webapp_public_url = f"https://{railway_domain}/webapp/index.html"
        logger.info(f"🌐 Публичный URL WebApp: {webapp_public_url}")
        logger.info(f"💡 Установи переменную WEB_APP_URL={webapp_public_url} в Railway")
    
    logger.info("Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
