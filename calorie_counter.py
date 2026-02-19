import sqlite3
import re
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional


class CalorieCounter:
    def __init__(self, db_path: str = "fitness_bot.db"):
        self.db_path = db_path
        self.init_database()
        
        # База данных продуктов и их калорийности (на 100г или на штуку)
        self.food_database = {
            # Молочные продукты
            'молоко': {'calories_per_100g': 64, 'unit': 'г'},
            'кефир': {'calories_per_100g': 41, 'unit': 'г'},
            'творог': {'calories_per_100g': 159, 'unit': 'г'},
            'сыр': {'calories_per_100g': 363, 'unit': 'г'},
            'йогурт': {'calories_per_100g': 59, 'unit': 'г'},
            'сметана': {'calories_per_100g': 206, 'unit': 'г'},
            
            # Мясо и рыба
            'курица': {'calories_per_100g': 165, 'unit': 'г'},
            'говядина': {'calories_per_100g': 250, 'unit': 'г'},
            'свинина': {'calories_per_100g': 242, 'unit': 'г'},
            'индейка': {'calories_per_100g': 189, 'unit': 'г'},
            'рыба': {'calories_per_100g': 206, 'unit': 'г'},
            'лосось': {'calories_per_100g': 208, 'unit': 'г'},
            'тунец': {'calories_per_100g': 184, 'unit': 'г'},
            'яйца': {'calories_per_item': 70, 'unit': 'шт'},
            'яйцо': {'calories_per_item': 70, 'unit': 'шт'},
            
            # Крупы и зерновые
            'овсянка': {'calories_per_100g': 389, 'unit': 'г'},
            'гречка': {'calories_per_100g': 343, 'unit': 'г'},
            'рис': {'calories_per_100g': 365, 'unit': 'г'},
            'макароны': {'calories_per_100g': 371, 'unit': 'г'},
            'хлеб': {'calories_per_100g': 265, 'unit': 'г'},
            'хлеб белый': {'calories_per_100g': 265, 'unit': 'г'},
            'хлеб черный': {'calories_per_100g': 214, 'unit': 'г'},
            
            # Овощи
            'помидор': {'calories_per_100g': 18, 'unit': 'г'},
            'помидоры': {'calories_per_100g': 18, 'unit': 'г'},
            'огурец': {'calories_per_100g': 16, 'unit': 'г'},
            'огурцы': {'calories_per_100g': 16, 'unit': 'г'},
            'морковь': {'calories_per_100g': 41, 'unit': 'г'},
            'капуста': {'calories_per_100g': 27, 'unit': 'г'},
            'брокколи': {'calories_per_100g': 34, 'unit': 'г'},
            'картофель': {'calories_per_100g': 77, 'unit': 'г'},
            'картошка': {'calories_per_100g': 77, 'unit': 'г'},
            
            # Фрукты
            'яблоко': {'calories_per_item': 52, 'unit': 'шт'},
            'яблоки': {'calories_per_item': 52, 'unit': 'шт'},
            'банан': {'calories_per_item': 89, 'unit': 'шт'},
            'бананы': {'calories_per_item': 89, 'unit': 'шт'},
            'апельсин': {'calories_per_item': 47, 'unit': 'шт'},
            'апельсины': {'calories_per_item': 47, 'unit': 'шт'},
            'груша': {'calories_per_item': 57, 'unit': 'шт'},
            'груши': {'calories_per_item': 57, 'unit': 'шт'},
            
            # Орехи и семена
            'орехи': {'calories_per_100g': 607, 'unit': 'г'},
            'миндаль': {'calories_per_100g': 579, 'unit': 'г'},
            'арахис': {'calories_per_100g': 567, 'unit': 'г'},
            
            # Масла и жиры
            'масло': {'calories_per_100g': 884, 'unit': 'г'},
            'масло подсолнечное': {'calories_per_100g': 884, 'unit': 'г'},
            'масло оливковое': {'calories_per_100g': 884, 'unit': 'г'},
            
            # Другое
            'сахар': {'calories_per_100g': 387, 'unit': 'г'},
            'мед': {'calories_per_100g': 304, 'unit': 'г'},
            'шоколад': {'calories_per_100g': 546, 'unit': 'г'},
        }
    
    def get_connection(self):
        """Получение соединения с базой данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Инициализация базы данных для калорий"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблица для приемов пищи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                meal_name TEXT,
                calories INTEGER NOT NULL,
                date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица для дневных норм калорий
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_limits (
                user_id INTEGER PRIMARY KEY,
                limit_calories INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date)")
        
        conn.commit()
        conn.close()
    
    def parse_food_text(self, text: str) -> List[Dict]:
        """Парсинг текста с описанием еды"""
        items = []
        
        # Убираем лишние символы и приводим к нижнему регистру
        text = text.lower()
        
        # Удаляем названия приемов пищи
        text = re.sub(r'\b(завтрак|обед|ужин|перекус|ланч|полдник)[:\s]*', '', text)
        
        # Разделяем на отдельные продукты (по запятым или "и")
        parts = re.split(r'[,и]', text)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Ищем число и единицу измерения
            # Паттерны: "200г", "2шт", "100мл", "1.5кг" и т.д.
            match = re.search(r'(\d+\.?\d*)\s*(г|кг|мл|л|шт|штук|штуки)', part)
            
            if match:
                amount = float(match.group(1))
                unit = match.group(2)
                
                # Нормализация единиц
                if unit in ['кг', 'л']:
                    amount *= 1000  # Конвертируем в граммы/мл
                    unit = 'г' if unit == 'кг' else 'мл'
                elif unit in ['штук', 'штуки']:
                    unit = 'шт'
                
                # Ищем название продукта (до числа)
                product_name = part[:match.start()].strip()
                
                if product_name:
                    items.append({
                        'name': product_name,
                        'amount': amount,
                        'unit': unit
                    })
            else:
                # Пытаемся найти продукт без указания количества
                # Ищем известные продукты в тексте
                for food_name, food_data in self.food_database.items():
                    if food_name in part:
                        # Пытаемся найти число перед названием
                        num_match = re.search(r'(\d+\.?\d*)', part)
                        if num_match:
                            amount = float(num_match.group(1))
                        else:
                            # Если число не найдено, используем стандартное количество
                            amount = 100 if food_data['unit'] == 'г' else 1
                        
                        items.append({
                            'name': food_name,
                            'amount': amount,
                            'unit': food_data['unit']
                        })
                        break
        
        return items
    
    def calculate_calories(self, food_items: List[Dict]) -> int:
        """Подсчет калорий для списка продуктов"""
        total_calories = 0
        
        for item in food_items:
            food_name = item['name'].lower().strip()
            amount = item['amount']
            unit = item['unit']
            
            # Ищем продукт в базе данных
            food_data = None
            for db_name, db_data in self.food_database.items():
                if db_name in food_name or food_name in db_name:
                    food_data = db_data
                    break
            
            if food_data:
                if 'calories_per_100g' in food_data:
                    # Калории на 100г
                    if unit == 'г':
                        calories = (food_data['calories_per_100g'] / 100) * amount
                    elif unit == 'мл':
                        # Для жидкостей считаем примерно как граммы
                        calories = (food_data['calories_per_100g'] / 100) * amount
                    elif unit == 'шт':
                        # Если указано в штуках, но продукт по граммам, используем средний вес
                        # Например, яблоко ~150г
                        avg_weight = 150
                        calories = (food_data['calories_per_100g'] / 100) * (avg_weight * amount)
                    else:
                        calories = (food_data['calories_per_100g'] / 100) * amount
                elif 'calories_per_item' in food_data:
                    # Калории на штуку
                    if unit == 'шт':
                        calories = food_data['calories_per_item'] * amount
                    else:
                        # Если указано в граммах, но продукт по штукам
                        # Используем средний вес одной штуки
                        avg_weight = 100  # Примерно
                        calories = (food_data['calories_per_item'] / avg_weight) * amount
                else:
                    calories = 0
                
                total_calories += int(calories)
            else:
                # Если продукт не найден, используем среднее значение
                # ~50 ккал на 100г для неизвестных продуктов
                if unit in ['г', 'мл']:
                    total_calories += int((50 / 100) * amount)
                elif unit == 'шт':
                    total_calories += int(50 * amount)
        
        return total_calories
    
    def add_meal_from_text(self, user_id: int, text: str) -> Dict:
        """Добавление приема пищи из текста"""
        items = self.parse_food_text(text)
        
        if not items:
            return {'success': False, 'calories': 0, 'total_today': 0}
        
        calories = self.calculate_calories(items)
        
        # Формируем название приема пищи
        meal_name = ', '.join([f"{item['name']} {item['amount']}{item['unit']}" for item in items])
        
        # Сохраняем в базу данных
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        cursor.execute("""
            INSERT INTO meals (user_id, meal_name, calories, date)
            VALUES (?, ?, ?, ?)
        """, (user_id, meal_name, calories, today))
        
        conn.commit()
        conn.close()
        
        # Получаем общее количество калорий за сегодня
        total_today = self.get_today_stats(user_id)['calories']
        
        return {
            'success': True,
            'calories': calories,
            'total_today': total_today,
            'items': items
        }
    
    def get_today_stats(self, user_id: int) -> Dict:
        """Получение статистики за сегодня"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        cursor.execute("""
            SELECT SUM(calories) as total_calories, 
                   COUNT(*) as meal_count,
                   GROUP_CONCAT(meal_name, '; ') as meals
            FROM meals
            WHERE user_id = ? AND date = ?
        """, (user_id, today))
        
        result = cursor.fetchone()
        conn.close()
        
        total_calories = result['total_calories'] or 0
        meal_count = result['meal_count'] or 0
        
        meals_list = []
        if result['meals']:
            meal_names = result['meals'].split('; ')
            for meal_name in meal_names:
                # Получаем калории для каждого приема пищи
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT calories FROM meals
                    WHERE user_id = ? AND date = ? AND meal_name = ?
                    LIMIT 1
                """, (user_id, today, meal_name))
                meal_result = cursor.fetchone()
                conn.close()
                
                if meal_result:
                    meals_list.append({
                        'name': meal_name,
                        'calories': meal_result['calories']
                    })
        
        return {
            'calories': total_calories,
            'meal_count': meal_count,
            'meals': meals_list
        }
    
    def get_week_stats(self, user_id: int) -> Dict:
        """Получение статистики за неделю"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        week_ago = date.today() - timedelta(days=7)
        
        cursor.execute("""
            SELECT date, SUM(calories) as daily_calories
            FROM meals
            WHERE user_id = ? AND date >= ?
            GROUP BY date
            ORDER BY date DESC
        """, (user_id, week_ago))
        
        days = []
        for row in cursor.fetchall():
            days.append({
                'date': datetime.strptime(row['date'], '%Y-%m-%d').date(),
                'calories': row['daily_calories'] or 0
            })
        
        conn.close()
        
        return {'days': days}
    
    def get_daily_limit(self, user_id: int) -> Optional[int]:
        """Получение дневной нормы калорий"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT limit_calories FROM daily_limits
            WHERE user_id = ?
        """, (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result['limit_calories'] if result else None
    
    def set_daily_limit(self, user_id: int, limit: int):
        """Установка дневной нормы калорий"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO daily_limits (user_id, limit_calories, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (user_id, limit))
        
        conn.commit()
        conn.close()
