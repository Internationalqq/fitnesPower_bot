import asyncio
import logging
from typing import Optional, Dict, List

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
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


async def send_daily_summary(chat_id: int):
    """Отправка ежедневной сводки в группу"""
    try:
        from datetime import date, timedelta
        
        # Статистика за вчерашний день
        yesterday = date.today() - timedelta(days=1)
        
        # Получаем статистику за вчера
        stats = db.get_group_stats_by_date(chat_id, yesterday)
        
        if not stats:
            logger.info(f"Нет статистики за {yesterday} для чата {chat_id}")
            return
        
        # Получаем список user_id из статистики
        user_ids = [stat['user_id'] for stat in stats]
        
        # Получаем имена участников из Telegram
        members_dict = await get_chat_members_dict(chat_id, user_ids)
        
        # Формируем сообщение
        date_str = yesterday.strftime("%d.%m.%Y")
        message = f"‼️⚠️{date_str}⚠️‼️\n"
        
        # Объединяем имена из Telegram и базы данных
        # Используем имя из Telegram, если есть, иначе username из базы
        for stat in stats:
            user_id = stat['user_id']
            if user_id not in members_dict:
                # Если не получили имя через API, используем имя из базы
                members_dict[user_id] = stat['username']
        
        # Сортируем по именам для единообразия
        sorted_stats = sorted(stats, key=lambda x: members_dict.get(x['user_id'], x['username']))
        
        for i, stat in enumerate(sorted_stats):
            user_id = stat['user_id']
            name = members_dict.get(user_id, stat['username'])
            pushups = stat['pushups']
            abs_count = stat['abs']
            
            message += f"{name}:\n"
            message += f"отжимания: {pushups}"
            if pushups >= 80:
                message += "; ⚠️"
            else:
                message += ";"
            message += "\n"
            
            message += f"пресс: {abs_count}"
            if i == len(sorted_stats) - 1:
                # Для последнего участника ставим точку вместо точки с запятой
                if abs_count >= 80:
                    message += ". ⚠️"
                else:
                    message += "."
            else:
                if abs_count >= 80:
                    message += "; ⚠️"
                else:
                    message += ";"
                message += "\n"
        
        await bot.send_message(chat_id, message)
        logger.info(f"Отправлена ежедневная сводка в чат {chat_id} за {yesterday}")
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневной сводки в чат {chat_id}: {e}")


async def send_daily_summary_to_all_chats():
    """Отправка ежедневной сводки во все активные группы"""
    try:
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
        minute=0,
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
            "/help - помощь\n\n"
            "Также ты можешь просто написать мне что-то вроде:\n"
            "<code>Завтрак: овсянка 200г, банан 1шт</code>\n"
            "И я посчитаю калории!"
        )
        await message.answer(text, parse_mode='HTML')
    else:
        # Групповой чат - статистика тренировок
        text = (
            "💪 Привет! Я буду вести статистику ваших тренировок!\n\n"
            "📊 <b>Доступные команды:</b>\n"
            "/pushups [количество] - добавить отжимания\n"
            "/отжимания [количество] - вычесть отжимания\n"
            "/abs [количество] - добавить упражнения на пресс\n"
            "/пресс [количество] - вычесть упражнения на пресс\n"
            "/stats - статистика за сегодня\n"
            "/leaderboard - таблица лидеров\n"
            "/my_stats - моя статистика\n"
            "/help - помощь"
        )
        await message.answer(text, parse_mode='HTML')


async def cmd_help(message: Message):
    """Обработка команды /help"""
    if message.chat.type == "private":
        text = (
            "📝 <b>Подсчет калорий:</b>\n\n"
            "• Используй /add_meal для добавления приема пищи\n"
            "• Или просто напиши: <code>Завтрак: яйца 2шт, хлеб 50г</code>\n"
            "• /today - посмотреть калории за сегодня\n"
            "• /week - статистика за неделю\n"
            "• /set_limit 2000 - установить дневную норму\n\n"
            "Я автоматически распознаю продукты и их количество!"
        )
    else:
        text = (
            "💪 <b>Статистика тренировок:</b>\n\n"
            "• /pushups 80 - добавить 80 отжиманий\n"
            "• /отжимания 20 - вычесть 20 отжиманий (покажет остаток до нормы)\n"
            "• /abs 80 - добавить 80 упражнений на пресс\n"
            "• /пресс 20 - вычесть 20 упражнений на пресс (покажет остаток до нормы)\n"
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
            total_today = db.get_user_pushups_today(user_id, message.chat.id)
            remaining = max(0, 80 - total_today)
            
            await message.answer(
                f"Молодец {user_name}! Тебе осталось {remaining} отжиманий.",
                reply_to_message_id=message.message_id
            )
        else:
            # Добавляем (положительное значение)
            db.add_pushups(user_id, username, count, message.chat.id)
            total_today = db.get_user_pushups_today(user_id, message.chat.id)
            
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
            total_today = db.get_user_abs_today(user_id, message.chat.id)
            remaining = max(0, 80 - total_today)
            
            await message.answer(
                f"Молодец {user_name}! Тебе осталось {remaining} пресс.",
                reply_to_message_id=message.message_id
            )
        else:
            # Добавляем (положительное значение)
            db.add_abs(user_id, username, count, message.chat.id)
            total_today = db.get_user_abs_today(user_id, message.chat.id)
            
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
    """Вычитание отжиманий (русская команда - всегда вычитает)"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /отжимания [количество]\nПример: /отжимания 20")
            return
        
        count = int(args[1])
        # Берем абсолютное значение (на случай если пользователь напишет отрицательное)
        count = abs(count)
        
        if count == 0:
            await message.answer("Количество не может быть нулем!")
            return
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        # Получаем имя из Telegram
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += f" {message.from_user.last_name}"
        
        # Всегда вычитаем
        db.add_pushups(user_id, username, -count, message.chat.id)
        total_today = db.get_user_pushups_today(user_id, message.chat.id)
        remaining = max(0, 80 - total_today)
        
        await message.answer(
            f"Молодец {user_name}! Тебе осталось {remaining} отжиманий.",
            reply_to_message_id=message.message_id
        )
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при вычитании отжиманий: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


async def cmd_press(message: Message):
    """Вычитание упражнений на пресс (русская команда - всегда вычитает)"""
    if message.chat.type == "private":
        await message.answer("Эта команда работает только в групповом чате!")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /пресс [количество]\nПример: /пресс 20")
            return
        
        count = int(args[1])
        # Берем абсолютное значение (на случай если пользователь напишет отрицательное)
        count = abs(count)
        
        if count == 0:
            await message.answer("Количество не может быть нулем!")
            return
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        # Получаем имя из Telegram
        user_name = message.from_user.first_name
        if message.from_user.last_name:
            user_name += f" {message.from_user.last_name}"
        
        # Всегда вычитаем
        db.add_abs(user_id, username, -count, message.chat.id)
        total_today = db.get_user_abs_today(user_id, message.chat.id)
        remaining = max(0, 80 - total_today)
        
        await message.answer(
            f"Молодец {user_name}! Тебе осталось {remaining} пресс.",
            reply_to_message_id=message.message_id
        )
    except ValueError:
        await message.answer("Пожалуйста, укажи число!")
    except Exception as e:
        logger.error(f"Ошибка при вычитании упражнений на пресс: {e}")
        await message.answer("Произошла ошибка. Попробуй еще раз.")


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


# Обработчики для личных сообщений (подсчет калорий)
async def cmd_add_meal(message: Message):
    """Добавление приема пищи"""
    if message.chat.type != "private":
        return
    
    await message.answer(
        "📝 Напиши что ты съел в формате:\n"
        "<code>Завтрак: овсянка 200г, банан 1шт, молоко 100мл</code>\n\n"
        "Или просто:\n"
        "<code>яйца 2шт, хлеб 50г</code>",
        parse_mode='HTML'
    )


async def cmd_today(message: Message):
    """Статистика калорий за сегодня"""
    if message.chat.type != "private":
        return
    
    try:
        user_id = message.from_user.id
        stats = calorie_counter.get_today_stats(user_id)
        limit = calorie_counter.get_daily_limit(user_id)
        
        text = f"📊 <b>Калории за сегодня:</b>\n\n"
        text += f"🔥 Съедено: {stats['calories']} ккал\n"
        
        if limit:
            remaining = limit - stats['calories']
            percentage = (stats['calories'] / limit) * 100
            text += f"🎯 Норма: {limit} ккал\n"
            text += f"📉 Осталось: {remaining} ккал ({100-percentage:.1f}%)\n"
            
            if percentage > 100:
                text += "⚠️ Превышена норма!"
            elif percentage > 90:
                text += "⚡ Почти достигнута норма!"
        
        if stats['meals']:
            text += f"\n🍽️ <b>Приемы пищи ({len(stats['meals'])}):</b>\n"
            for meal in stats['meals']:
                text += f"• {meal['name']}: {meal['calories']} ккал\n"
        
        await message.answer(text, parse_mode='HTML')
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


async def handle_text(message: Message):
    """Обработка текстовых сообщений"""
    if message.chat.type == "private":
        # Обработка сообщений о еде в личке
        user_id = message.from_user.id
        text = message.text.lower()
        
        # Простая проверка - если сообщение содержит слова про еду или числа с единицами измерения
        if any(keyword in text for keyword in ['г', 'кг', 'мл', 'л', 'шт', 'калори', 'ккал', 'еда', 'съел', 'завтрак', 'обед', 'ужин']):
            try:
                result = calorie_counter.add_meal_from_text(user_id, message.text)
                
                if result['success']:
                    response = f"✅ Добавлено: {result['calories']} ккал\n"
                    response += f"📊 Всего за сегодня: {result['total_today']} ккал"
                    
                    limit = calorie_counter.get_daily_limit(user_id)
                    if limit:
                        remaining = limit - result['total_today']
                        percentage = (result['total_today'] / limit) * 100
                        response += f"\n🎯 Осталось: {remaining} ккал ({100-percentage:.1f}%)"
                    
                    await message.answer(response)
                else:
                    await message.answer(
                        f"❌ Не удалось распознать продукты.\n\n"
                        f"Попробуй формат:\n"
                        f"<code>овсянка 200г, банан 1шт</code>\n"
                        f"или\n"
                        f"<code>Завтрак: яйца 2шт, хлеб 50г</code>",
                        parse_mode='HTML'
                    )
            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения о еде: {e}")
                await message.answer("Произошла ошибка. Попробуй еще раз.")


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
    
    # Инициализация модулей
    db = Database()
    # Инициализируем Motivator с API ключом из переменных окружения или используем переданный ключ
    groq_api_key = os.getenv("GROQ_API_KEY")
    motivator = Motivator(api_key=groq_api_key)
    calorie_counter = CalorieCounter()
    
    # Регистрация обработчиков
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_pushups, Command("pushups"))
    dp.message.register(cmd_abs, Command("abs"))
    dp.message.register(cmd_otzhimaniya, Command("отжимания"))
    dp.message.register(cmd_press, Command("пресс"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_my_stats, Command("my_stats"))
    dp.message.register(cmd_leaderboard, Command("leaderboard"))
    dp.message.register(cmd_add_meal, Command("add_meal"))
    dp.message.register(cmd_today, Command("today"))
    dp.message.register(cmd_week, Command("week"))
    dp.message.register(cmd_set_limit, Command("set_limit"))
    dp.message.register(handle_text)
    
    # Настройка планировщика для мотивирующих сообщений
    await setup_scheduler()
    
    logger.info("Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
