"""
Простой скрипт для проверки базовой функциональности бота
"""
import sys
import os

# Устанавливаем UTF-8 для вывода
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Добавляем пути
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

site_packages = r"C:\Users\UserVik\Python311\Lib\site-packages"
if site_packages not in sys.path:
    sys.path.insert(0, site_packages)

from dotenv import load_dotenv
load_dotenv()

def test_imports():
    """Проверка импортов"""
    print("1. Проверка импортов...")
    try:
        from aiogram import Bot, Dispatcher
        print("   [OK] aiogram импортирован")
        
        from database import Database
        print("   [OK] database импортирован")
        
        from motivator import Motivator
        print("   [OK] motivator импортирован")
        
        from calorie_counter import CalorieCounter
        print("   [OK] calorie_counter импортирован")
        
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        print("   [OK] apscheduler импортирован")
        
        return True
    except Exception as e:
        print(f"   [ERROR] Ошибка импорта: {e}")
        return False

def test_env():
    """Проверка переменных окружения"""
    print("\n2. Проверка переменных окружения...")
    token = os.getenv("BOT_TOKEN")
    groq_key = os.getenv("GROQ_API_KEY")
    
    if token:
        print(f"   [OK] BOT_TOKEN найден (длина: {len(token)})")
    else:
        print("   [ERROR] BOT_TOKEN не найден!")
    
    if groq_key:
        print(f"   [OK] GROQ_API_KEY найден (длина: {len(groq_key)})")
    else:
        print("   [WARN] GROQ_API_KEY не найден (бот будет работать без AI)")
    
    return bool(token)

def test_database():
    """Проверка базы данных"""
    print("\n3. Проверка базы данных...")
    try:
        from database import Database
        db = Database()
        print("   [OK] База данных инициализирована")
        
        # Проверяем структуру
        test_chat_id = -999999999
        stats = db.get_group_stats_by_date(test_chat_id, "2024-01-01")
        print("   [OK] Методы базы данных работают")
        return True
    except Exception as e:
        print(f"   [ERROR] Ошибка базы данных: {e}")
        return False

def test_bot_connection():
    """Проверка подключения к Telegram"""
    print("\n4. Проверка подключения к Telegram...")
    try:
        from aiogram import Bot
        token = os.getenv("BOT_TOKEN")
        if not token:
            print("   [WARN] BOT_TOKEN не найден, пропускаем проверку")
            return False
        
        bot = Bot(token=token)
        print("   [OK] Бот создан успешно")
        print("   [INFO] Для полной проверки нужно запустить бота и отправить /start в Telegram")
        return True
    except Exception as e:
        print(f"   [ERROR] Ошибка создания бота: {e}")
        return False

def main():
    print("=" * 50)
    print("ТЕСТИРОВАНИЕ БОТА")
    print("=" * 50)
    
    results = []
    results.append(("Импорты", test_imports()))
    results.append(("Переменные окружения", test_env()))
    results.append(("База данных", test_database()))
    results.append(("Подключение к Telegram", test_bot_connection()))
    
    print("\n" + "=" * 50)
    print("РЕЗУЛЬТАТЫ:")
    print("=" * 50)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{name}: {status}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n[OK] Все базовые тесты пройдены!")
        print("\nСледующие шаги:")
        print("1. Запусти бота: python bot.py")
        print("2. Найди бота в Telegram: @fitnesPower_bot")
        print("3. Отправь /start в личке с ботом")
        print("4. Добавь бота в группу и протестируй команды")
    else:
        print("\n[WARN] Некоторые тесты не пройдены. Проверь ошибки выше.")
    
    return all_passed

if __name__ == "__main__":
    main()
