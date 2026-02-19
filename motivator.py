import os
import logging
from typing import Optional
from groq import Groq

logger = logging.getLogger(__name__)


class Motivator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if self.api_key:
            try:
                self.client = Groq(api_key=self.api_key)
                self.use_groq = True
                logger.info("Groq API инициализирован")
            except Exception as e:
                logger.error(f"Ошибка инициализации Groq: {e}")
                self.use_groq = False
                self.client = None
        else:
            self.use_groq = False
            self.client = None
            logger.warning("GROQ_API_KEY не найден, используются статические сообщения")
        
        # Резервные статические сообщения на случай проблем с API
        self.fallback_facts = [
            "Регулярные отжимания укрепляют не только руки, но и корпус, улучшая осанку!",
            "Упражнения на пресс помогают поддерживать здоровье позвоночника и снижают риск травм спины.",
            "Всего 10 минут физической активности в день могут увеличить продолжительность жизни на 2 года!",
            "Силовые тренировки ускоряют метаболизм даже в состоянии покоя - мышцы сжигают калории 24/7.",
            "Регулярные тренировки улучшают качество сна и помогают быстрее засыпать.",
        ]
        
        self.fallback_tips = [
            "Пей достаточно воды - 2-3 литра в день помогут мышцам быстрее восстанавливаться.",
            "Не забывай про разминку перед тренировкой - это снизит риск травм.",
            "Правильная техника важнее количества - лучше сделать меньше, но правильно!",
            "Восстановление так же важно, как тренировка - давай мышцам отдых между днями.",
            "Белковая пища после тренировки помогает мышцам быстрее восстанавливаться.",
        ]
    
    async def generate_motivational_content(self, context: Optional[dict] = None) -> tuple[str, str]:
        """Генерация мотивирующего факта и совета через Groq с учетом контекста группы"""
        if not self.use_groq or not self.client:
            import random
            return random.choice(self.fallback_facts), random.choice(self.fallback_tips)
        
        try:
            # Формируем контекст о программе тренировок
            training_context = ""
            if context:
                training_context = (
                    f"Группа тренируется каждый день: делают 80 отжиманий и 80 упражнений на пресс. "
                    f"Это их ежедневная программа тренировок."
                )
            else:
                training_context = (
                    "Группа тренируется каждый день: делают 80 отжиманий и 80 упражнений на пресс. "
                    "Это их ежедневная программа тренировок."
                )
            
            # Генерируем факт с учетом их программы
            fact_prompt = (
                f"{training_context}\n\n"
                "Придумай короткий (1-2 предложения) мотивирующий факт о пользе именно такой программы тренировок "
                "(80 отжиманий и 80 упражнений на пресс ежедневно). "
                "Факт должен быть научно обоснованным, вдохновляющим и релевантным для их конкретной программы. "
                "Можешь упомянуть пользу отжиманий, упражнений на пресс, или ежедневных тренировок. "
                "Ответ должен быть только фактом, без дополнительных комментариев."
            )
            
            fact_response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Ты помощник, который создает мотивирующие факты о фитнесе и здоровье, учитывая конкретную программу тренировок группы."},
                    {"role": "user", "content": fact_prompt}
                ],
                temperature=0.8,
                max_tokens=120
            )
            
            fact = fact_response.choices[0].message.content.strip()
            
            # Генерируем совет с учетом их программы
            tip_prompt = (
                f"{training_context}\n\n"
                "Придумай короткий (1 предложение) практический совет специально для этой группы. "
                "Совет должен быть конкретным и полезным для людей, которые делают 80 отжиманий и 80 упражнений на пресс каждый день. "
                "Можешь дать совет о технике выполнения, восстановлении, питании, прогрессии, или как избежать перетренированности при ежедневных тренировках. "
                "Совет должен быть релевантным именно для их программы. "
                "Ответ должен быть только советом, без дополнительных комментариев."
            )
            
            tip_response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Ты помощник, который дает практические советы о фитнесе и здоровье, учитывая конкретную программу тренировок группы."},
                    {"role": "user", "content": tip_prompt}
                ],
                temperature=0.8,
                max_tokens=120
            )
            
            tip = tip_response.choices[0].message.content.strip()
            
            return fact, tip
            
        except Exception as e:
            logger.error(f"Ошибка при генерации контента через Groq: {e}")
            import random
            return random.choice(self.fallback_facts), random.choice(self.fallback_tips)
    
    def get_random_fact(self) -> str:
        """Получение случайного факта (для обратной совместимости)"""
        import random
        return random.choice(self.fallback_facts)
    
    def get_random_tip(self) -> str:
        """Получение случайного совета (для обратной совместимости)"""
        import random
        return random.choice(self.fallback_tips)
