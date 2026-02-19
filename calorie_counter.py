import sqlite3
import re
import os
import logging
import aiohttp
import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CalorieCounter:
    def __init__(self, db_path: str = "fitness_bot.db", groq_client=None):
        self.db_path = db_path
        self.groq_client = groq_client
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
            
            # Протеиновые продукты
            'протеиновый батончик': {'calories_per_item': 200, 'unit': 'шт'},
            'протеиновый': {'calories_per_100g': 400, 'unit': 'г'},
            'протеин': {'calories_per_100g': 400, 'unit': 'г'},
            'батончик': {'calories_per_item': 200, 'unit': 'шт'},
            'boombar': {'calories_per_item': 200, 'unit': 'шт'},
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
        original_text = text
        text = text.lower()
        
        # Удаляем названия приемов пищи и лишние слова
        text = re.sub(r'\b(завтрак|обед|ужин|перекус|ланч|полдник|съел|съела|ел|ела|поел|поела)[:\s]*', '', text)
        # Удаляем скобки и их содержимое (комментарии)
        text = re.sub(r'\([^)]*\)', '', text)
        text = text.strip()
        
        # Нормализация единиц (английские -> русские)
        unit_map = {
            'g': 'г', 'kg': 'кг', 'ml': 'мл', 'l': 'л',
            'pcs': 'шт', 'piece': 'шт', 'pieces': 'шт'
        }
        
        # Сначала пытаемся найти продукты с явным указанием количества
        # Паттерны: "200г", "2шт", "100мл", "1.5кг", "20g", "20g протеина" и т.д.
        # Поддерживаем как русские, так и английские единицы
        match = re.search(r'(\d+\.?\d*)\s*(г|кг|мл|л|шт|штук|штуки|g|kg|ml|l|pcs|piece)', text, re.IGNORECASE)
        
        if match:
            amount = float(match.group(1))
            unit = match.group(2).lower()
            
            # Нормализация единиц (английские -> русские)
            if unit in unit_map:
                unit = unit_map[unit]
            
            # Нормализация единиц
            if unit in ['кг', 'л']:
                amount *= 1000  # Конвертируем в граммы/мл
                unit = 'г' if unit == 'кг' else 'мл'
            elif unit in ['штук', 'штуки']:
                unit = 'шт'
            
            # Ищем название продукта (до числа или после единицы)
            text_before = text[:match.start()].strip()
            text_after = text[match.end():].strip()
            
            # Пробуем найти название продукта
            product_name = ""
            if text_before:
                # Берем последнее слово перед числом как название продукта
                words_before = text_before.split()
                if words_before:
                    product_name = words_before[-1]
            elif text_after:
                # Берем первое слово после единицы
                words_after = text_after.split()
                if words_after:
                    product_name = words_after[0]
            
            # Если нашли "протеин" или "протеина" рядом, это протеин
            if 'протеин' in text or 'протеина' in text:
                product_name = 'протеин'
            
            if product_name:
                items.append({
                    'name': product_name,
                    'amount': amount,
                    'unit': unit
                })
                return items
        
        # Если не нашли с явным количеством, ищем известные продукты
        found_products = []
        for food_name, food_data in self.food_database.items():
            # Ищем продукт в тексте (как отдельное слово или часть слова)
            # Используем более гибкий поиск
            if food_name in text or any(word in food_name for word in text.split() if len(word) > 3):
                # Пытаемся найти число перед или после названия
                num_patterns = [
                    r'(\d+\.?\d*)\s*(г|кг|мл|л|шт|g|kg|ml|l|pcs)\s*' + re.escape(food_name),
                    re.escape(food_name) + r'\s*(\d+\.?\d*)\s*(г|кг|мл|л|шт|g|kg|ml|l|pcs)',
                    r'(\d+\.?\d*)\s*' + re.escape(food_name),
                    re.escape(food_name) + r'\s*(\d+\.?\d*)',
                ]
                
                amount = None
                unit = food_data['unit']
                
                for num_pattern in num_patterns:
                    num_match = re.search(num_pattern, text, re.IGNORECASE)
                    if num_match:
                        amount = float(num_match.group(1))
                        if len(num_match.groups()) > 1 and num_match.group(2):
                            unit_raw = num_match.group(2).lower()
                            unit = unit_map.get(unit_raw, unit_raw)
                        break
                
                if amount is None:
                    # Если число не найдено, используем стандартное количество
                    amount = 100 if food_data['unit'] == 'г' else 1
                
                found_products.append({
                    'name': food_name,
                    'amount': amount,
                    'unit': unit,
                    'priority': len(food_name)  # Приоритет более длинным названиям
                })
        
        # Сортируем по приоритету (более длинные названия сначала)
        found_products.sort(key=lambda x: x['priority'], reverse=True)
        
        # Если нашли продукты, возвращаем их
        if found_products:
            # Берем первый найденный продукт (самый длинный)
            product = found_products[0]
            items.append({
                'name': product['name'],
                'amount': product['amount'],
                'unit': product['unit']
            })
        else:
            # Если ничего не нашли, но есть числа в тексте, пытаемся извлечь
            # Например: "20g протеина" -> протеин 20г
            num_match = re.search(r'(\d+\.?\d*)\s*(г|кг|мл|л|шт|g|kg|ml|l|pcs)', text, re.IGNORECASE)
            if num_match:
                amount = float(num_match.group(1))
                unit_raw = num_match.group(2).lower()
                unit = unit_map.get(unit_raw, unit_raw)
                
                # Ищем название продукта в тексте
                if 'батончик' in text or 'boombar' in text:
                    product_name = 'протеиновый батончик'
                    unit = 'шт'
                    amount = 1
                elif 'протеин' in text or 'протеина' in text:
                    # Если указано количество протеина (например, 20g протеина)
                    product_name = 'протеин'
                    unit = 'г'
                    # amount уже установлен из num_match
                else:
                    # Берем первое существительное из текста
                    words = text.split()
                    product_name = words[0] if words else "продукт"
                
                items.append({
                    'name': product_name,
                    'amount': amount,
                    'unit': unit
                })
        
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
    
    async def parse_with_groq(self, text: str) -> Optional[Dict]:
        """Парсинг и подсчет калорий с помощью Groq"""
        if not self.groq_client:
            return None
        
        try:
            prompt = (
                f"Пользователь написал описание еды: '{text}'\n\n"
                "Распознай все продукты и их количество из этого текста. "
                "Верни ответ ТОЛЬКО в формате JSON массива, где каждый элемент это объект с полями:\n"
                "- name: название продукта (на русском)\n"
                "- amount: количество (число)\n"
                "- unit: единица измерения ('г', 'мл', 'шт', 'кг', 'л')\n"
                "- calories: калории для этого количества (число)\n\n"
                "Пример ответа:\n"
                '[{"name": "овсянка", "amount": 200, "unit": "г", "calories": 778}, {"name": "банан", "amount": 1, "unit": "шт", "calories": 89}]\n\n'
                "Используй стандартные значения калорийности продуктов. Если не можешь определить точное количество, используй разумные оценки. "
                "Ответ должен быть ТОЛЬКО JSON массивом, без дополнительного текста."
            )
            
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Ты помощник для подсчета калорий. Ты распознаешь продукты из текста и считаешь калории. Всегда отвечаешь только валидным JSON массивом без дополнительного текста."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            import json
            result_text = response.choices[0].message.content.strip()
            
            # Убираем markdown код блоки если есть
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                result_text = '\n'.join(lines[1:-1]) if len(lines) > 2 else result_text
            
            # Пытаемся извлечь JSON из ответа
            try:
                parsed = json.loads(result_text)
                # Если это объект с массивом внутри
                if isinstance(parsed, dict):
                    # Ищем массив в значениях
                    items = None
                    for key, value in parsed.items():
                        if isinstance(value, list):
                            items = value
                            break
                    # Или может быть ключ "items" или "products"
                    if not items:
                        items = parsed.get('items') or parsed.get('products') or parsed.get('food')
                    if not items:
                        return None
                elif isinstance(parsed, list):
                    items = parsed
                else:
                    return None
                
                # Проверяем структуру
                if not items or not isinstance(items, list):
                    return None
                
                # Валидируем и обрабатываем элементы
                valid_items = []
                for item in items:
                    if isinstance(item, dict) and 'name' in item:
                        valid_items.append({
                            'name': item.get('name', ''),
                            'amount': item.get('amount', 0),
                            'unit': item.get('unit', 'г'),
                            'calories': item.get('calories', 0)
                        })
                
                if not valid_items:
                    return None
                
                total_calories = sum(item.get('calories', 0) for item in valid_items)
                meal_name = ', '.join([f"{item['name']} {item['amount']}{item['unit']}" for item in valid_items])
                
                return {
                    'success': True,
                    'items': valid_items,
                    'calories': int(total_calories),
                    'meal_name': meal_name
                }
            except json.JSONDecodeError as e:
                logger.error(f"Не удалось распарсить JSON от Groq: {result_text[:200]}... Ошибка: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при использовании Groq для парсинга еды: {e}")
            return None
    
    async def add_meal_from_text(self, user_id: int, text: str) -> Dict:
        """Добавление приема пищи из текста (с использованием Groq если доступен)"""
        # Сначала пробуем использовать Groq
        groq_result = await self.parse_with_groq(text)
        
        if groq_result and groq_result.get('success'):
            # Используем результат от Groq
            calories = groq_result['calories']
            meal_name = groq_result['meal_name']
            items = groq_result['items']
        else:
            # Используем старый метод парсинга
            items = self.parse_food_text(text)
            
            if not items:
                return {'success': False, 'calories': 0, 'total_today': 0}
            
            calories = self.calculate_calories(items)
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
            'items': items if isinstance(items, list) else []
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
    
    async def search_product_by_barcode_openfoodfacts(self, barcode: str) -> Optional[Dict]:
        """Поиск продукта по штрих-коду через Open Food Facts API"""
        try:
            url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('status') == 1 and data.get('product'):
                            product = data['product']
                            
                            # Извлекаем информацию о продукте
                            product_name = product.get('product_name', '') or product.get('product_name_en', '') or product.get('product_name_ru', '')
                            if not product_name:
                                product_name = product.get('abbreviated_product_name', 'Неизвестный продукт')
                            
                            # Получаем КБЖУ (может быть в разных полях)
                            calories = None
                            proteins = None
                            fats = None
                            carbs = None
                            
                            if 'nutriments' in product:
                                nutriments = product['nutriments']
                                
                                # Калории могут быть в разных единицах
                                calories = (
                                    nutriments.get('energy-kcal_100g') or
                                    nutriments.get('energy-kcal') or
                                    nutriments.get('energy_100g') or
                                    (nutriments.get('energy', 0) / 4.184 if nutriments.get('energy') else None)  # Конвертация из кДж
                                )
                                
                                # Белки (на 100г)
                                proteins = (
                                    nutriments.get('proteins_100g') or
                                    nutriments.get('proteins') or
                                    nutriments.get('protein_100g') or
                                    nutriments.get('protein')
                                )
                                
                                # Жиры (на 100г)
                                fats = (
                                    nutriments.get('fat_100g') or
                                    nutriments.get('fats_100g') or
                                    nutriments.get('fat') or
                                    nutriments.get('fats')
                                )
                                
                                # Углеводы (на 100г)
                                carbs = (
                                    nutriments.get('carbohydrates_100g') or
                                    nutriments.get('carbs_100g') or
                                    nutriments.get('carbohydrates') or
                                    nutriments.get('carbs')
                                )
                            
                            # Если калории не найдены, используем среднее значение
                            if calories is None or calories == 0:
                                calories = 250  # Среднее значение для неизвестных продуктов
                            
                            # Получаем вес продукта (если указан)
                            quantity = product.get('quantity', '')
                            weight_match = re.search(r'(\d+)\s*(г|g|кг|kg)', quantity, re.IGNORECASE)
                            weight = None
                            if weight_match:
                                weight = float(weight_match.group(1))
                                unit = weight_match.group(2).lower()
                                if unit in ['кг', 'kg']:
                                    weight *= 1000
                            
                            return {
                                'success': True,
                                'name': product_name,
                                'calories_per_100g': int(calories) if calories else None,
                                'proteins_per_100g': round(proteins, 1) if proteins else None,
                                'fats_per_100g': round(fats, 1) if fats else None,
                                'carbs_per_100g': round(carbs, 1) if carbs else None,
                                'weight': weight,
                                'barcode': barcode,
                                'brand': product.get('brands', ''),
                                'image_url': product.get('image_url', ''),
                                'source': 'Open Food Facts'
                            }
                        else:
                            logger.warning(f"Продукт с штрих-кодом {barcode} не найден в базе Open Food Facts")
                            return None
                    else:
                        logger.error(f"Ошибка при запросе к Open Food Facts API: {response.status}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при запросе к Open Food Facts API для штрих-кода {barcode}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при поиске продукта по штрих-коду {barcode}: {e}")
            return None
    
    async def search_product_by_barcode_upcitemdb(self, barcode: str) -> Optional[Dict]:
        """Поиск продукта по штрих-коду через UPCitemdb API"""
        try:
            url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={barcode}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('code') == 'OK' and data.get('items'):
                            item = data['items'][0]  # Берем первый результат
                            
                            product_name = item.get('title', 'Неизвестный продукт')
                            brand = item.get('brand', '')
                            
                            # UPCitemdb не всегда имеет КБЖУ, но может иметь описание
                            # Попробуем найти информацию о питании в описании
                            description = item.get('description', '')
                            
                            # Парсим КБЖУ из описания если есть
                            calories = None
                            proteins = None
                            fats = None
                            carbs = None
                            
                            # Ищем числа в описании (калории обычно указаны)
                            cal_match = re.search(r'(\d+)\s*(ккал|калори|calories|kcal)', description, re.IGNORECASE)
                            if cal_match:
                                calories = int(cal_match.group(1))
                            
                            return {
                                'success': True,
                                'name': product_name,
                                'calories_per_100g': calories,
                                'proteins_per_100g': proteins,
                                'fats_per_100g': fats,
                                'carbs_per_100g': carbs,
                                'weight': None,
                                'barcode': barcode,
                                'brand': brand,
                                'image_url': item.get('images', [None])[0] if item.get('images') else None,
                                'source': 'UPCitemdb',
                                'description': description
                            }
                        else:
                            logger.warning(f"Продукт с штрих-кодом {barcode} не найден в базе UPCitemdb")
                            return None
                    else:
                        return None
        except Exception as e:
            logger.debug(f"Ошибка при поиске в UPCitemdb для штрих-кода {barcode}: {e}")
            return None
    
    async def search_product_by_barcode(self, barcode: str) -> Optional[Dict]:
        """Поиск продукта по штрих-коду через несколько источников"""
        # Пробуем сначала Open Food Facts (самый надежный источник с КБЖУ)
        result = await self.search_product_by_barcode_openfoodfacts(barcode)
        if result and result.get('success'):
            return result
        
        # Если не нашли, пробуем UPCitemdb
        logger.info(f"Продукт не найден в Open Food Facts, пробуем UPCitemdb...")
        result = await self.search_product_by_barcode_upcitemdb(barcode)
        if result and result.get('success'):
            return result
        
        # Если ничего не нашли, возвращаем None
        logger.warning(f"Продукт с штрих-кодом {barcode} не найден ни в одном источнике")
        return None
    
    async def get_product_info_by_barcode(self, barcode: str) -> Dict:
        """Получение информации о продукте по штрих-коду (без добавления в дневник)"""
        product_info = await self.search_product_by_barcode(barcode)
        
        if not product_info or not product_info.get('success'):
            return {
                'success': False,
                'message': 'Продукт не найден в базе данных Open Food Facts.'
            }
        
        return product_info
    
    async def add_meal_from_barcode(self, user_id: int, barcode: str) -> Dict:
        """Добавление приема пищи по штрих-коду"""
        product_info = await self.search_product_by_barcode(barcode)
        
        if not product_info or not product_info.get('success'):
            return {
                'success': False,
                'message': 'Продукт не найден в базе данных. Попробуй добавить вручную, описав что ты съел.'
            }
        
        # Рассчитываем калории
        calories_per_100g = product_info.get('calories_per_100g', 250)
        weight = product_info.get('weight')
        
        if weight:
            # Если известен вес продукта, используем его
            calories = int((calories_per_100g / 100) * weight)
            meal_name = f"{product_info['name']} {int(weight)}г"
        else:
            # Если вес не указан, используем стандартное значение (100г или 1шт)
            calories = calories_per_100g
            meal_name = f"{product_info['name']} 100г"
        
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
            'product_name': product_info['name'],
            'brand': product_info.get('brand', ''),
            'product_info': product_info  # Добавляем полную информацию о продукте
        }
