import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional


class Database:
    def __init__(self, db_path: str = "fitness_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Получение соединения с базой данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблица для отжиманий
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pushups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                count INTEGER NOT NULL,
                date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица для упражнений на пресс
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS abs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                count INTEGER NOT NULL,
                date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Индексы для быстрого поиска
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pushups_user_date ON pushups(user_id, chat_id, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_abs_user_date ON abs(user_id, chat_id, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pushups_chat_date ON pushups(chat_id, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_abs_chat_date ON abs(chat_id, date)")
        
        conn.commit()
        conn.close()
    
    def add_pushups(self, user_id: int, username: str, count: int, chat_id: int):
        """Добавление отжиманий (обновляет запись за сегодня, если есть, иначе создаёт новую)"""
        import logging
        logger = logging.getLogger(__name__)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        # Проверяем, есть ли запись за сегодня
        cursor.execute("""
            SELECT id, count FROM pushups
            WHERE user_id = ? AND chat_id = ? AND date = ?
            LIMIT 1
        """, (user_id, chat_id, today))
        
        existing = cursor.fetchone()
        if existing:
            # Обновляем существующую запись: count = count + новое значение
            new_count = existing['count'] + count
            cursor.execute("""
                UPDATE pushups SET count = ?, username = ?
                WHERE id = ?
            """, (new_count, username, existing['id']))
            logger.info(f"Обновлена запись отжиманий: user_id={user_id}, chat_id={chat_id}, old_count={existing['count']}, new_count={new_count}")
        else:
            # Создаём новую запись (даже если count=0, чтобы пользователь попал в список)
            cursor.execute("""
                INSERT INTO pushups (user_id, username, chat_id, count, date)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, chat_id, count, today))
            logger.info(f"Создана новая запись отжиманий: user_id={user_id}, chat_id={chat_id}, count={count}, date={today}")
        
        conn.commit()
        conn.close()
    
    def add_abs(self, user_id: int, username: str, count: int, chat_id: int):
        """Добавление упражнений на пресс (обновляет запись за сегодня, если есть, иначе создаёт новую)"""
        import logging
        logger = logging.getLogger(__name__)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        # Проверяем, есть ли запись за сегодня
        cursor.execute("""
            SELECT id, count FROM abs
            WHERE user_id = ? AND chat_id = ? AND date = ?
            LIMIT 1
        """, (user_id, chat_id, today))
        
        existing = cursor.fetchone()
        if existing:
            # Обновляем существующую запись: count = count + новое значение
            new_count = existing['count'] + count
            cursor.execute("""
                UPDATE abs SET count = ?, username = ?
                WHERE id = ?
            """, (new_count, username, existing['id']))
            logger.info(f"Обновлена запись пресса: user_id={user_id}, chat_id={chat_id}, old_count={existing['count']}, new_count={new_count}")
        else:
            # Создаём новую запись (даже если count=0, чтобы пользователь попал в список)
            cursor.execute("""
                INSERT INTO abs (user_id, username, chat_id, count, date)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, chat_id, count, today))
            logger.info(f"Создана новая запись пресса: user_id={user_id}, chat_id={chat_id}, count={count}, date={today}")
        
        conn.commit()
        conn.close()
    
    def get_user_pushups_today(self, user_id: int, chat_id: int) -> int:
        """Получение количества отжиманий пользователя за сегодня"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        cursor.execute("""
            SELECT SUM(count) as total
            FROM pushups
            WHERE user_id = ? AND chat_id = ? AND date = ?
        """, (user_id, chat_id, today))
        
        result = cursor.fetchone()
        conn.close()
        
        return result['total'] if result['total'] else 0
    
    def get_user_abs_today(self, user_id: int, chat_id: int) -> int:
        """Получение количества упражнений на пресс пользователя за сегодня"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        cursor.execute("""
            SELECT SUM(count) as total
            FROM abs
            WHERE user_id = ? AND chat_id = ? AND date = ?
        """, (user_id, chat_id, today))
        
        result = cursor.fetchone()
        conn.close()
        
        return result['total'] if result['total'] else 0
    
    def get_user_pushups_debt(self, user_id: int, chat_id: int) -> int:
        """Получение долга по отжиманиям (сумма всех count за все дни, если > 0)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(count) as total
            FROM pushups
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        result = cursor.fetchone()
        conn.close()
        total = result['total'] if result['total'] else 0
        return max(0, total)
    
    def get_user_abs_debt(self, user_id: int, chat_id: int) -> int:
        """Получение долга по прессу (сумма всех count за все дни, если > 0)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(count) as total
            FROM abs
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        result = cursor.fetchone()
        conn.close()
        total = result['total'] if result['total'] else 0
        return max(0, total)
    
    def get_group_stats_today(self, chat_id: int) -> List[Dict]:
        """Получение статистики группы за сегодня"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = date.today()
        
        # Получаем статистику по отжиманиям
        cursor.execute("""
            SELECT user_id, username, SUM(count) as pushups
            FROM pushups
            WHERE chat_id = ? AND date = ?
            GROUP BY user_id, username
        """, (chat_id, today))
        
        pushups_dict = {row['user_id']: {'username': row['username'], 'pushups': row['pushups']} 
                       for row in cursor.fetchall()}
        
        # Получаем статистику по прессу
        cursor.execute("""
            SELECT user_id, username, SUM(count) as abs_count
            FROM abs
            WHERE chat_id = ? AND date = ?
            GROUP BY user_id, username
        """, (chat_id, today))
        
        abs_dict = {row['user_id']: {'username': row['username'], 'abs': row['abs_count']} 
                   for row in cursor.fetchall()}
        
        # Объединяем данные
        all_users = set(pushups_dict.keys()) | set(abs_dict.keys())
        stats = []
        
        for user_id in all_users:
            pushups = pushups_dict.get(user_id, {}).get('pushups', 0) or 0
            abs_count = abs_dict.get(user_id, {}).get('abs', 0) or 0
            username = pushups_dict.get(user_id, {}).get('username') or abs_dict.get(user_id, {}).get('username')
            
            stats.append({
                'user_id': user_id,
                'username': username,
                'pushups': pushups,
                'abs': abs_count,
                'total': pushups + abs_count
            })
        
        # Сортируем по общему количеству
        stats.sort(key=lambda x: x['total'], reverse=True)
        
        conn.close()
        return stats
    
    def get_user_stats(self, user_id: int, chat_id: int) -> Optional[Dict]:
        """Получение общей статистики пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Общее количество отжиманий
        cursor.execute("""
            SELECT SUM(count) as total_pushups
            FROM pushups
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        
        total_pushups = cursor.fetchone()['total_pushups'] or 0
        
        # Общее количество упражнений на пресс
        cursor.execute("""
            SELECT SUM(count) as total_abs
            FROM abs
            WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        
        total_abs = cursor.fetchone()['total_abs'] or 0
        
        # Количество дней тренировок
        cursor.execute("""
            SELECT COUNT(DISTINCT date) as days
            FROM (
                SELECT date FROM pushups WHERE user_id = ? AND chat_id = ?
                UNION
                SELECT date FROM abs WHERE user_id = ? AND chat_id = ?
            )
        """, (user_id, chat_id, user_id, chat_id))
        
        days = cursor.fetchone()['days'] or 0
        
        conn.close()
        
        if days == 0:
            return None
        
        avg_per_day = (total_pushups + total_abs) / days if days > 0 else 0
        
        return {
            'total_pushups': total_pushups,
            'total_abs': total_abs,
            'days': days,
            'avg_per_day': avg_per_day
        }
    
    def get_leaderboard(self, chat_id: int, limit: int = 10) -> List[Dict]:
        """Получение таблицы лидеров"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Получаем статистику по отжиманиям
        cursor.execute("""
            SELECT user_id, username, SUM(count) as total_pushups
            FROM pushups
            WHERE chat_id = ?
            GROUP BY user_id, username
        """, (chat_id,))
        
        pushups_dict = {row['user_id']: {'username': row['username'], 'pushups': row['total_pushups']} 
                       for row in cursor.fetchall()}
        
        # Получаем статистику по прессу
        cursor.execute("""
            SELECT user_id, username, SUM(count) as total_abs
            FROM abs
            WHERE chat_id = ?
            GROUP BY user_id, username
        """, (chat_id,))
        
        abs_dict = {row['user_id']: {'username': row['username'], 'abs': row['total_abs']} 
                   for row in cursor.fetchall()}
        
        # Объединяем данные
        all_users = set(pushups_dict.keys()) | set(abs_dict.keys())
        leaders = []
        
        for user_id in all_users:
            pushups = pushups_dict.get(user_id, {}).get('pushups', 0) or 0
            abs_count = abs_dict.get(user_id, {}).get('abs', 0) or 0
            username = pushups_dict.get(user_id, {}).get('username') or abs_dict.get(user_id, {}).get('username')
            
            leaders.append({
                'user_id': user_id,
                'username': username,
                'total_pushups': pushups,
                'total_abs': abs_count,
                'total': pushups + abs_count
            })
        
        # Сортируем по общему количеству
        leaders.sort(key=lambda x: x['total'], reverse=True)
        
        conn.close()
        return leaders[:limit]
    
    def get_active_chats(self) -> List[int]:
        """Получение списка активных чатов (где есть записи за последние 7 дней)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        from datetime import timedelta
        week_ago = date.today() - timedelta(days=7)
        
        cursor.execute("""
            SELECT DISTINCT chat_id
            FROM (
                SELECT chat_id FROM pushups WHERE date >= ?
                UNION
                SELECT chat_id FROM abs WHERE date >= ?
            )
        """, (week_ago, week_ago))
        
        chats = [row['chat_id'] for row in cursor.fetchall()]
        conn.close()
        
        return chats
    
    def get_group_stats_by_date(self, chat_id: int, target_date: date) -> List[Dict]:
        """Получение статистики группы за конкретную дату"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Получаем статистику по отжиманиям за дату
        cursor.execute("""
            SELECT user_id, username, SUM(count) as pushups
            FROM pushups
            WHERE chat_id = ? AND date = ?
            GROUP BY user_id, username
        """, (chat_id, target_date))
        
        pushups_dict = {row['user_id']: {'username': row['username'], 'pushups': row['pushups']} 
                       for row in cursor.fetchall()}
        
        # Получаем статистику по прессу за дату
        cursor.execute("""
            SELECT user_id, username, SUM(count) as abs_count
            FROM abs
            WHERE chat_id = ? AND date = ?
            GROUP BY user_id, username
        """, (chat_id, target_date))
        
        abs_dict = {row['user_id']: {'username': row['username'], 'abs': row['abs_count']} 
                   for row in cursor.fetchall()}
        
        # Объединяем данные
        all_users = set(pushups_dict.keys()) | set(abs_dict.keys())
        stats = []
        
        for user_id in all_users:
            pushups = pushups_dict.get(user_id, {}).get('pushups', 0) or 0
            abs_count = abs_dict.get(user_id, {}).get('abs', 0) or 0
            username = pushups_dict.get(user_id, {}).get('username') or abs_dict.get(user_id, {}).get('username')
            
            stats.append({
                'user_id': user_id,
                'username': username,
                'pushups': pushups,
                'abs': abs_count
            })
        
        conn.close()
        return stats

    def get_all_chat_participants(self, chat_id: int) -> List[Dict]:
        """Все пользователи, которые когда-либо делали отжимания/пресс в этом чате (user_id, username)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, MAX(username) as username FROM (
                SELECT user_id, username FROM pushups WHERE chat_id = ?
                UNION ALL
                SELECT user_id, username FROM abs WHERE chat_id = ?
            ) GROUP BY user_id
        """, (chat_id, chat_id))
        rows = cursor.fetchall()
        conn.close()
        return [{'user_id': row['user_id'], 'username': row['username'] or ''} for row in rows]

    def get_active_chat_participants(self, chat_id: int, days: int = 7) -> List[Dict]:
        """Участники, у которых есть хотя бы одна запись отжиманий или пресса за последние days дней."""
        from datetime import timedelta
        conn = self.get_connection()
        cursor = conn.cursor()
        since = date.today() - timedelta(days=days)
        cursor.execute("""
            SELECT user_id, MAX(username) as username FROM (
                SELECT user_id, username FROM pushups WHERE chat_id = ? AND date >= ?
                UNION ALL
                SELECT user_id, username FROM abs WHERE chat_id = ? AND date >= ?
            ) GROUP BY user_id
        """, (chat_id, since, chat_id, since))
        rows = cursor.fetchall()
        conn.close()
        return [{'user_id': row['user_id'], 'username': row['username'] or ''} for row in rows]

    def get_chat_first_activity_date(self, chat_id: int) -> Optional[date]:
        """Дата первой активности в чате (первая запись отжиманий или пресса)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MIN(d) as first_date FROM (
                SELECT date as d FROM pushups WHERE chat_id = ?
                UNION ALL
                SELECT date as d FROM abs WHERE chat_id = ?
            )
        """, (chat_id, chat_id))
        row = cursor.fetchone()
        conn.close()
        if row and row['first_date']:
            d = row['first_date']
            return d if isinstance(d, date) else date.fromisoformat(str(d))
        return None
