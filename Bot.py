import asyncio
import logging
import random
import time
import uuid
import math
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    FSInputFile, 
    InputMediaPhoto, 
    BotCommand, 
    LabeledPrice, 
    PreCheckoutQuery
)
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА И ГЛОБАЛЬНЫЕ НАСТРОЙКИ
# ========================================================================
BOT_TOKEN = "8932860761:AAHda6SvVX7SGEZyT4Jeej24gKONOSgXiXI"
SUPER_ADMIN_ID = 5341904332 
DB_NAME = "database.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ========================================================================
# АНТИ-СПАМ СИСТЕМА И БЕЗОПАСНЫЙ ИНТЕРФЕЙС СООБЩЕНИЙ
# ========================================================================
user_last_action = {}
user_attack_cooldown = {}

BUTTON_COOLDOWN = 1.0  
ATTACK_COOLDOWN = 300  

def is_spam(user_id: int) -> bool:
    """Проверяет время между кликами пользователя для защиты от флуда кнопками."""
    now = time.time()
    if now - user_last_action.get(user_id, 0) < BUTTON_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def get_attack_cooldown(user_id: int) -> int:
    """Возвращает оставшееся время кулдауна на проведение военных операций."""
    now = time.time()
    passed = now - user_attack_cooldown.get(user_id, 0)
    if passed < ATTACK_COOLDOWN:
        return int(ATTACK_COOLDOWN - passed)
    return 0

def set_attack_cooldown(user_id: int):
    """Устанавливает отметку времени последней атаки для пользователя."""
    user_attack_cooldown[user_id] = time.time()

async def safe_edit(message: types.Message, text: str, reply_markup=None, photo_id=None):
    """
    Умное редактирование сообщений. 
    Корректно обрабатывает переходы между текстовыми сообщениями и медиа-сообщениями.
    """
    try:
        if photo_id:
            if message.photo:
                await message.edit_media(
                    InputMediaPhoto(media=photo_id, caption=text, parse_mode="HTML"), 
                    reply_markup=reply_markup
                )
            else:
                await message.delete()
                await message.answer_photo(
                    photo=photo_id, 
                    caption=text, 
                    reply_markup=reply_markup, 
                    parse_mode="HTML"
                )
        else:
            if message.photo:
                await message.delete()
                await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            else:
                await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass

def df(flag: str) -> str:
    """Возвращает графический значок картинки, если флаг является медиа-файлом, либо сам эмодзи-символ."""
    if not flag:
        return "🏳️"
    return "🖼" if flag.startswith("photo:") else flag

# ========================================================================
# ГЛОБАЛЬНЫЕ СПРАВОЧНИКИ И ИГРОВАЯ МЕХАНИКА
# ========================================================================
ACTIVE_TRADES = {}
RES_MAP = {
    "budget": "💰 Бюджет", 
    "materials": "🧱 Материалы", 
    "steel": "⚙️ Сталь", 
    "electronics": "💻 Электроника",
    "oil": "🛢 Нефть", 
    "food": "🥩 Еда"
}

GOV_TYPES = {
    "democracy": {"name": "Демократия", "desc": "Доход +10%, Прирост граждан +10%"},
    "communism": {"name": "Коммунизм", "desc": "Материалы +15%, Прирост граждан -5%"},
    "monarchy": {"name": "Монархия", "desc": "Еда +15%, Нефть +5%"},
    "dictatorship": {"name": "Диктатура", "desc": "Атака в бою +10%, Доход -5%"},
    "theocracy": {"name": "Теократия", "desc": "Доход +5%, Еда +10%"}
}

RELIGIONS = {
    "christianity": {"name": "Христианство", "desc": "Бюджет +10%, Граждане +5%"},
    "islam": {"name": "Ислам", "desc": "Мощь войск +10%, Добыча нефти +10%"},
    "buddhism": {"name": "Буддизм", "desc": "Потребление еды -15%, Защита +10%"},
    "hinduism": {"name": "Индуизм", "desc": "Производство еды +15%, Граждане +10%"},
    "shintoism": {"name": "Синтоизм", "desc": "Электроника +20%, Материалы +5%"},
    "pastafarianism": {"name": "Пастафарианство", "desc": "Прирост еды +25%, Атака -5%"},
    "atheism": {"name": "Атеизм", "desc": "Нет бонусов"}
}

LAWS = {
    "law_health": {"name": "⚕️ Беспл. медицина", "desc": "Бюджет -10%, Прирост граждан +20%"},
    "law_martial": {"name": "🪖 Военное положение", "desc": "Потребление еды -20%, Прирост граждан -50%"},
    "law_trade": {"name": "🤝 Свободная торговля", "desc": "Бюджет +15%, Материалы -10%"},
    "law_subsidies": {"name": "🌾 Субсидии фермерам", "desc": "Бюджет -15%, Произв. еды +25%"},
    "law_propaganda": {"name": "📺 Гос. пропаганда", "desc": "Бюджет -5%, Защита в бою +10%"},
    "law_mobilization": {"name": "🏭 Трудовая мобилизация", "desc": "Материалы +20%, Бюджет -5%"},
    "law_conscription": {"name": "🪖 Обязательная служба", "desc": "Мощь атаки +10%, Прирост граждан -15%"},
    "law_ecology": {"name": "🌱 Экологические нормы", "desc": "Прирост граждан +15%, Нефть -15%, Материалы -10%"},
    "law_luxury_tax": {"name": "💎 Налог на роскошь", "desc": "Бюджет +20%"},
    "law_closed_borders": {"name": "🚧 Закрытые границы", "desc": "Защита в бою +15%, Бюджет -10%"}
}

BUILDING_STATS = {
    "factories": {"name": "🏭 Завод", "cost": {"budget": 5000, "materials": 500, "steel": 0, "electronics": 0, "oil": 0, "food": 0}, "desc": "+150 Мат/тик"},
    "oil_rigs": {"name": "🛢 Нефтевышка", "cost": {"budget": 8000, "materials": 1000, "steel": 100, "electronics": 0, "oil": 0, "food": 0}, "desc": "+100 Нефти/тик"},
    "farms": {"name": "🌾 Ферма", "cost": {"budget": 3000, "materials": 200, "steel": 0, "electronics": 0, "oil": 0, "food": 0}, "desc": "+300 Еды/тик"},
    "bridges": {"name": "🌉 Мост", "cost": {"budget": 2000, "materials": 800, "steel": 50, "electronics": 0, "oil": 0, "food": 0}, "desc": "Снижает штраф рек"},
    "steel_mills": {"name": "⚙️ Сталелитейный", "cost": {"budget": 10000, "materials": 2000, "steel": 0, "electronics": 0, "oil": 0, "food": 0}, "desc": "+50 Стали/тик"},
    "tech_factories": {"name": "💻 Тех.Фабрика", "cost": {"budget": 20000, "materials": 3000, "steel": 1000, "electronics": 0, "oil": 0, "food": 0}, "desc": "+15 Электр/тик"},
    "settlements": {"name": "🏘 Поселение", "cost": {"budget": 15000, "materials": 2000, "steel": 0, "electronics": 0, "oil": 0, "food": 2000}, "desc": "+500 Бюдж, +50 Граждан"},
    "fishing_fleets": {"name": "🚢 Рыболовный флот", "cost": {"budget": 12000, "materials": 1500, "steel": 500, "electronics": 50, "oil": 200, "food": 0}, "desc": "+1200 Еды/тик. Решает голод!"},
    "agro_complexes": {"name": "🚜 Агрокомплекс", "cost": {"budget": 18000, "materials": 2500, "steel": 800, "electronics": 300, "oil": 0, "food": 0}, "desc": "+2500 Еды/тик"},
    "bakeries": {"name": "🍞 Пекарня", "cost": {"budget": 4000, "materials": 500, "steel": 50, "electronics": 0, "oil": 0, "food": 0}, "desc": "Преобразует еду в +300 Бюджета"},
    "hospitals": {"name": "🏥 Больница", "cost": {"budget": 25000, "materials": 4000, "steel": 1000, "electronics": 500, "oil": 0, "food": 0}, "desc": "+250 Граждан/тик"},
    "malls": {"name": "🏪 Торговый центр", "cost": {"budget": 30000, "materials": 5000, "steel": 1500, "electronics": 800, "oil": 0, "food": 0}, "desc": "+1500 Бюджета/тик"}
}

ARMY_STATS = {
    # Наземные
    "infantry": {"cat": "ground", "name": "🪖 Пехота (x10)", "qty_mod": 10, "power": 10, "cost": {"budget": 100, "materials": 0, "steel": 0, "electronics": 0, "oil": 0, "food": 50}},
    "machine_guns": {"cat": "ground", "name": "🎯 Пулемет", "qty_mod": 1, "power": 3, "cost": {"budget": 200, "materials": 50, "steel": 10, "electronics": 0, "oil": 0, "food": 50}},
    "mortars": {"cat": "ground", "name": "💥 Миномет", "qty_mod": 1, "power": 5, "cost": {"budget": 400, "materials": 150, "steel": 50, "electronics": 0, "oil": 0, "food": 50}},
    "artillery": {"cat": "ground", "name": "💥 Артиллерия", "qty_mod": 1, "power": 10, "cost": {"budget": 800, "materials": 300, "steel": 200, "electronics": 0, "oil": 0, "food": 0}},
    "cars": {"cat": "ground", "name": "🚙 Авто", "qty_mod": 1, "power": 2, "cost": {"budget": 300, "materials": 100, "steel": 50, "electronics": 0, "oil": 0, "food": 0}},
    "hummers": {"cat": "ground", "name": "🚙 Хаммер", "qty_mod": 1, "power": 5, "cost": {"budget": 600, "materials": 200, "steel": 100, "electronics": 0, "oil": 0, "food": 0}},
    "military_cars": {"cat": "ground", "name": "🚜 Воен.машина", "qty_mod": 1, "power": 8, "cost": {"budget": 1000, "materials": 400, "steel": 200, "electronics": 0, "oil": 0, "food": 0}},
    "trucks": {"cat": "ground", "name": "🚛 Грузовик", "qty_mod": 1, "power": 4, "cost": {"budget": 500, "materials": 200, "steel": 100, "electronics": 0, "oil": 0, "food": 0}},
    "tanks": {"cat": "ground", "name": "🚜 Танк", "qty_mod": 1, "power": 20, "cost": {"budget": 2000, "materials": 1000, "steel": 500, "electronics": 0, "oil": 0, "food": 0}},
    "bunkers": {"cat": "ground", "name": "🛡 Бункер", "qty_mod": 1, "power": 50, "cost": {"budget": 3000, "materials": 1500, "steel": 500, "electronics": 0, "oil": 0, "food": 0}},
    "aa_guns": {"cat": "ground", "name": "📡 Зенитка", "qty_mod": 1, "power": 30, "cost": {"budget": 1500, "materials": 500, "steel": 300, "electronics": 0, "oil": 0, "food": 0}},
    "sam_systems": {"cat": "ground", "name": "🚀 ЗРК", "qty_mod": 1, "power": 120, "cost": {"budget": 5000, "materials": 1500, "steel": 800, "electronics": 300, "oil": 0, "food": 0}},
    "spies": {"cat": "ground", "name": "🕵️‍♂️ Шпион", "qty_mod": 1, "power": 0, "cost": {"budget": 1000, "materials": 0, "steel": 0, "electronics": 0, "oil": 0, "food": 0}},
    
    # Флот
    "boats": {"cat": "naval", "name": "🛶 Лодка", "qty_mod": 1, "power": 5, "cost": {"budget": 800, "materials": 200, "steel": 50, "electronics": 0, "oil": 0, "food": 0}},
    "corvettes": {"cat": "naval", "name": "🚤 Корвет", "qty_mod": 1, "power": 20, "cost": {"budget": 1500, "materials": 500, "steel": 400, "electronics": 0, "oil": 0, "food": 0}},
    "submarines": {"cat": "naval", "name": "🌊 Подлодка", "qty_mod": 1, "power": 40, "cost": {"budget": 2500, "materials": 1000, "steel": 1000, "electronics": 200, "oil": 0, "food": 0}},
    "destroyers": {"cat": "naval", "name": "🛥 Эсминец", "qty_mod": 1, "power": 50, "cost": {"budget": 3000, "materials": 1000, "steel": 800, "electronics": 100, "oil": 0, "food": 0}},
    "cruisers": {"cat": "naval", "name": "🛳 Крейсер", "qty_mod": 1, "power": 150, "cost": {"budget": 7000, "materials": 2500, "steel": 2000, "electronics": 300, "oil": 0, "food": 0}},
    "battleships": {"cat": "naval", "name": "⛴ Линкор", "qty_mod": 1, "power": 500, "cost": {"budget": 15000, "materials": 5000, "steel": 4000, "electronics": 500, "oil": 0, "food": 0}},
    "carriers": {"cat": "naval", "name": "🛩 Авианосец", "qty_mod": 1, "power": 1000, "cost": {"budget": 30000, "materials": 10000, "steel": 8000, "electronics": 2000, "oil": 0, "food": 0}},
    
    # Воздух
    "fighters": {"cat": "air", "name": "✈️ Истребитель", "qty_mod": 1, "power": 100, "cost": {"budget": 5000, "materials": 1000, "steel": 500, "electronics": 200, "oil": 0, "food": 0}},
    "bombers": {"cat": "air", "name": "🛩 Бомбардировщик", "qty_mod": 1, "power": 250, "cost": {"budget": 12000, "materials": 2000, "steel": 1000, "electronics": 400, "oil": 0, "food": 0}},
    "helicopters": {"cat": "air", "name": "🚁 Верт. Боевой", "qty_mod": 1, "power": 80, "cost": {"budget": 4000, "materials": 800, "steel": 300, "electronics": 100, "oil": 0, "food": 0}},
    
    # Дроны
    "uavs": {"cat": "drones", "name": "🛸 БПЛА", "qty_mod": 1, "power": 20, "cost": {"budget": 1000, "materials": 200, "steel": 50, "electronics": 150, "oil": 0, "food": 0}},
    "jet_uavs": {"cat": "drones", "name": "🚀 Реак. БПЛА", "qty_mod": 1, "power": 60, "cost": {"budget": 3000, "materials": 500, "steel": 200, "electronics": 400, "oil": 0, "food": 0}},
    "baba_yaga": {"cat": "drones", "name": "🦇 Баба Яга", "qty_mod": 1, "power": 40, "cost": {"budget": 2000, "materials": 300, "steel": 100, "electronics": 250, "oil": 0, "food": 0}},
    "fpv_drones": {"cat": "drones", "name": "🐝 ФПВ-Дрон", "qty_mod": 1, "power": 15, "cost": {"budget": 200, "materials": 50, "steel": 10, "electronics": 30, "oil": 0, "food": 0}},
}

# ========================================================================
# ИНИЦИАЛИЗАЦИЯ И МИГРАЦИИ БАЗЫ ДАННЫХ SQLite
# ========================================================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER UNIQUE,
                username TEXT DEFAULT '',
                is_unclaimed INTEGER DEFAULT 0,
                name TEXT,
                flag TEXT,
                budget INTEGER DEFAULT 10000,
                gdp INTEGER DEFAULT 100,
                territory INTEGER DEFAULT 10,
                settlements INTEGER DEFAULT 1,
                citizens INTEGER DEFAULT 10000,
                
                infantry INTEGER DEFAULT 100,
                machine_guns INTEGER DEFAULT 10,
                mortars INTEGER DEFAULT 5,
                cars INTEGER DEFAULT 5,
                hummers INTEGER DEFAULT 0,
                military_cars INTEGER DEFAULT 0,
                trucks INTEGER DEFAULT 2,
                tanks INTEGER DEFAULT 0,
                artillery INTEGER DEFAULT 0,
                aa_guns INTEGER DEFAULT 0,
                sam_systems INTEGER DEFAULT 0,
                
                fighters INTEGER DEFAULT 0,
                bombers INTEGER DEFAULT 0,
                helicopters INTEGER DEFAULT 0,
                
                uavs INTEGER DEFAULT 0,
                jet_uavs INTEGER DEFAULT 0,
                baba_yaga INTEGER DEFAULT 0,
                fpv_drones INTEGER DEFAULT 0,
                
                boats INTEGER DEFAULT 0,
                ships INTEGER DEFAULT 0,
                submarines INTEGER DEFAULT 0,
                corvettes INTEGER DEFAULT 0,
                destroyers INTEGER DEFAULT 0,
                cruisers INTEGER DEFAULT 0,
                battleships INTEGER DEFAULT 0,
                carriers INTEGER DEFAULT 0,
                
                materials INTEGER DEFAULT 1000,
                steel INTEGER DEFAULT 500,
                electronics INTEGER DEFAULT 100,
                oil INTEGER DEFAULT 500,
                food INTEGER DEFAULT 2000,
                
                factories INTEGER DEFAULT 1,
                steel_mills INTEGER DEFAULT 0,
                tech_factories INTEGER DEFAULT 0,
                oil_rigs INTEGER DEFAULT 1,
                farms INTEGER DEFAULT 2,
                fishing_fleets INTEGER DEFAULT 0,
                agro_complexes INTEGER DEFAULT 0,
                bakeries INTEGER DEFAULT 0,
                hospitals INTEGER DEFAULT 0,
                malls INTEGER DEFAULT 0,
                
                bridges INTEGER DEFAULT 0,
                rivers INTEGER DEFAULT 0,
                seas INTEGER DEFAULT 0,
                mountains INTEGER DEFAULT 0,
                forests INTEGER DEFAULT 0,
                deserts INTEGER DEFAULT 0,
                
                laws TEXT DEFAULT 'Нет законов',
                bunkers INTEGER DEFAULT 0,
                spies INTEGER DEFAULT 0,
                war_wins INTEGER DEFAULT 0,
                war_losses INTEGER DEFAULT 0,
                alliance_id INTEGER DEFAULT 0,
                gov_type TEXT DEFAULT 'Не выбрано',
                religion TEXT DEFAULT 'Атеизм',
                active_laws TEXT DEFAULT '',
                f16 INTEGER DEFAULT 0,
                oreshnik INTEGER DEFAULT 0
            )
        """)
        
        await db.execute("CREATE TABLE IF NOT EXISTS alliances (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, flag TEXT, leader_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS alliance_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, alliance_id INTEGER, user_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS feedbacks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, text_content TEXT, photo_id TEXT, is_answered INTEGER DEFAULT 0)")
        
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        
        # Полные миграции для поддержки всех обновлений данных
        new_columns = [
            ("bunkers", "INTEGER DEFAULT 0"), ("spies", "INTEGER DEFAULT 0"),
            ("war_wins", "INTEGER DEFAULT 0"), ("war_losses", "INTEGER DEFAULT 0"), 
            ("alliance_id", "INTEGER DEFAULT 0"),
            ("ships", "INTEGER DEFAULT 0"), ("destroyers", "INTEGER DEFAULT 0"),
            ("cruisers", "INTEGER DEFAULT 0"), ("battleships", "INTEGER DEFAULT 0"),
            ("artillery", "INTEGER DEFAULT 0"), ("submarines", "INTEGER DEFAULT 0"), 
            ("corvettes", "INTEGER DEFAULT 0"), ("carriers", "INTEGER DEFAULT 0"), 
            ("materials", "INTEGER DEFAULT 1000"), ("oil", "INTEGER DEFAULT 500"), 
            ("food", "INTEGER DEFAULT 2000"), ("factories", "INTEGER DEFAULT 1"), 
            ("oil_rigs", "INTEGER DEFAULT 1"), ("farms", "INTEGER DEFAULT 2"), 
            ("bridges", "INTEGER DEFAULT 0"), ("rivers", "INTEGER DEFAULT 0"), 
            ("seas", "INTEGER DEFAULT 0"), ("username", "TEXT DEFAULT ''"),
            ("is_unclaimed", "INTEGER DEFAULT 0"), ("citizens", "INTEGER DEFAULT 10000"), 
            ("gov_type", "TEXT DEFAULT 'Не выбрано'"), ("religion", "TEXT DEFAULT 'Атеизм'"), 
            ("active_laws", "TEXT DEFAULT ''"), ("machine_guns", "INTEGER DEFAULT 0"), 
            ("mortars", "INTEGER DEFAULT 0"), ("hummers", "INTEGER DEFAULT 0"), 
            ("military_cars", "INTEGER DEFAULT 0"), ("boats", "INTEGER DEFAULT 0"),
            ("mountains", "INTEGER DEFAULT 0"), ("forests", "INTEGER DEFAULT 0"), ("deserts", "INTEGER DEFAULT 0"),
            ("steel", "INTEGER DEFAULT 500"), ("electronics", "INTEGER DEFAULT 100"),
            ("steel_mills", "INTEGER DEFAULT 0"), ("tech_factories", "INTEGER DEFAULT 0"),
            ("fighters", "INTEGER DEFAULT 0"), ("bombers", "INTEGER DEFAULT 0"), ("helicopters", "INTEGER DEFAULT 0"),
            ("uavs", "INTEGER DEFAULT 0"), ("jet_uavs", "INTEGER DEFAULT 0"), ("baba_yaga", "INTEGER DEFAULT 0"), 
            ("fpv_drones", "INTEGER DEFAULT 0"), ("aa_guns", "INTEGER DEFAULT 0"), ("sam_systems", "INTEGER DEFAULT 0"),
            ("f16", "INTEGER DEFAULT 0"), ("oreshnik", "INTEGER DEFAULT 0"),
            ("fishing_fleets", "INTEGER DEFAULT 0"), ("agro_complexes", "INTEGER DEFAULT 0"),
            ("bakeries", "INTEGER DEFAULT 0"), ("hospitals", "INTEGER DEFAULT 0"), ("malls", "INTEGER DEFAULT 0")
        ]
        for col, col_type in new_columns:
            try:
                await db.execute(f"ALTER TABLE countries ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError:
                pass
        await db.commit()

async def get_db_connection():
    db = await aiosqlite.connect(DB_NAME)
    db.row_factory = aiosqlite.Row
    return db

async def fetch_one(query, params=()):
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchone()
            return dict(result) if result else None
    finally:
        await db.close()

async def fetch_all(query, params=()):
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchall()
            return [dict(row) for row in result]
    finally:
        await db.close()

async def execute_db(query, params=()):
    db = await get_db_connection()
    try:
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()

async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    res = await fetch_one("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return bool(res)

async def update_username(user_id: int, username: str):
    if username:
        await execute_db("UPDATE countries SET username = ? WHERE owner_id = ?", (username, user_id))

# ========================================================================
# МАКРОЭКОНОМИКА: РАСЧЕТ ТИКОВЫХ ПОКАЗАТЕЛЕЙ И БОНУСОВ
# ========================================================================
def calc_economy_rates(c):
    gov = c.get('gov_type', 'Не выбрано')
    rel = c.get('religion', 'Атеизм')
    active_laws = c.get('active_laws') or ''
    laws = [l for l in active_laws.split(',') if l]
    
    mod_budget, mod_materials, mod_food_prod, mod_food_cons, mod_oil, mod_citizens, mod_electronics = 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0
    combat_att_mod, combat_def_mod = 1.0, 1.0
    
    # Формы правления
    if gov == "democracy": 
        mod_budget += 0.10
        mod_citizens += 0.10
    elif gov == "communism": 
        mod_materials += 0.15
        mod_citizens -= 0.05
    elif gov == "monarchy": 
        mod_food_prod += 0.15
        mod_oil += 0.05
    elif gov == "dictatorship": 
        mod_budget -= 0.05
        combat_att_mod += 0.10
    elif gov == "theocracy": 
        mod_budget += 0.05
        mod_food_prod += 0.10
        
    # Влияние действующих законов
    if "law_health" in laws: 
        mod_budget -= 0.10
        mod_citizens += 0.20
    if "law_martial" in laws: 
        mod_food_cons -= 0.20
        mod_citizens -= 0.50
    if "law_trade" in laws: 
        mod_budget += 0.15
        mod_materials -= 0.10
    if "law_subsidies" in laws: 
        mod_budget -= 0.15
        mod_food_prod += 0.25
    if "law_propaganda" in laws: 
        mod_budget -= 0.05
        combat_def_mod += 0.10
    if "law_mobilization" in laws: 
        mod_materials += 0.20
        mod_budget -= 0.05
    if "law_conscription" in laws: 
        combat_att_mod += 0.10
        mod_citizens -= 0.15
    if "law_ecology" in laws: 
        mod_citizens += 0.15
        mod_oil -= 0.15
        mod_materials -= 0.10
    if "law_luxury_tax" in laws: 
        mod_budget += 0.20
    if "law_closed_borders" in laws: 
        combat_def_mod += 0.15
        mod_budget -= 0.10
    
    # Религиозные верования
    if rel == "Христианство": 
        mod_budget += 0.10
        mod_citizens += 0.05
    elif rel == "Ислам": 
        combat_att_mod += 0.10
        mod_oil += 0.10
    elif rel == "Буддизм": 
        mod_food_cons -= 0.15
        combat_def_mod += 0.10
    elif rel == "Индуизм": 
        mod_food_prod += 0.15
        mod_citizens += 0.10
    elif rel == "Синтоизм": 
        mod_electronics += 0.20
        mod_materials += 0.05
    elif rel == "Пастафарианство": 
        mod_food_prod += 0.25
        combat_att_mod -= 0.05

    # Базовое производство по фабрикам, заводам, ТЦ и пекарням
    prod_money = int(((c.get('settlements', 1) * 500) + c.get('gdp', 100) + (c.get('malls', 0) * 1500) + (c.get('bakeries', 0) * 300)) * mod_budget)
    prod_materials = int((c.get('factories', 0) * 150) * mod_materials)
    prod_steel = int((c.get('steel_mills', 0) * 50) * mod_materials)
    prod_electronics = int((c.get('tech_factories', 0) * 15) * mod_electronics)
    prod_oil = int((c.get('oil_rigs', 0) * 100) * mod_oil)
    
    base_food = (c.get('farms', 0) * 300) + (c.get('fishing_fleets', 0) * 1200) + (c.get('agro_complexes', 0) * 2500)
    prod_food = int(base_food * mod_food_prod)
    
    cons_food = int((
        int(c.get('infantry', 0) * 1.5) + (c.get('machine_guns', 0) * 1) + 
        (c.get('mortars', 0) * 2) + (c.get('artillery', 0) * 2) + 
        (c.get('aa_guns', 0) * 1) + (c.get('sam_systems', 0) * 3) + 
        (c.get('spies', 0) * 5) + int(c.get('citizens', 0) * 0.05)
    ) * mod_food_cons)
    
    cons_oil = int(
        c.get('cars', 0) * 0.5 + c.get('hummers', 0) * 1 + c.get('military_cars', 0) * 2 + 
        c.get('trucks', 0) * 1 + c.get('tanks', 0) * 3 + c.get('boats', 0) * 1 + 
        c.get('submarines', 0) * 4 + c.get('corvettes', 0) * 3 + c.get('destroyers', 0) * 5 + 
        c.get('cruisers', 0) * 10 + c.get('battleships', 0) * 20 + c.get('carriers', 0) * 50 +
        c.get('fighters', 0) * 5 + c.get('bombers', 0) * 10 + c.get('helicopters', 0) * 3 +
        c.get('uavs', 0) * 1 + c.get('jet_uavs', 0) * 3 + c.get('baba_yaga', 0) * 1 +
        c.get('f16', 0) * 15 + c.get('fishing_fleets', 0) * 5 
    )
    
    citizens_base_growth = int(c.get('citizens', 10000) * 0.01) + (c.get('settlements', 1) * 50) + (c.get('hospitals', 0) * 250)
    actual_growth = int(citizens_base_growth * mod_citizens)
    
    return {
        "prod_money": prod_money, "prod_materials": prod_materials, "prod_steel": prod_steel, "prod_electronics": prod_electronics,
        "prod_oil": prod_oil, "prod_food": prod_food, "cons_food": cons_food, "cons_oil": cons_oil,
        "growth_cit": actual_growth, "att_mod": combat_att_mod, "def_mod": combat_def_mod
    }

async def economy_tick():
    while True:
        await asyncio.sleep(180)
        db = await get_db_connection()
        try:
            async with db.execute("SELECT * FROM countries WHERE owner_id IS NOT NULL AND is_unclaimed = 0") as cursor:
                countries = await cursor.fetchall()
            
            for c in countries:
                c_dict = dict(c)
                rates = calc_economy_rates(c_dict)
                
                new_budget = c_dict['budget'] + rates['prod_money']
                new_materials = c_dict['materials'] + rates['prod_materials']
                new_steel = c_dict.get('steel', 0) + rates['prod_steel']
                new_electronics = c_dict.get('electronics', 0) + rates['prod_electronics']
                
                new_food = c_dict['food'] + rates['prod_food'] - rates['cons_food']
                new_oil = c_dict['oil'] + rates['prod_oil'] - rates['cons_oil']
                
                infantry_penalty = 0
                vehicle_penalty = 0
                citizens_penalty = 0
                
                if new_food < 0:
                    infantry_penalty = abs(new_food) // 2 
                    citizens_penalty = abs(new_food) * 2
                    new_food = 0
                if new_oil < 0:
                    vehicle_penalty = abs(new_oil) // 5 
                    new_oil = 0
                
                new_citizens = max(0, c_dict['citizens'] + rates['growth_cit'] - citizens_penalty)
                final_infantry = max(0, c_dict['infantry'] - infantry_penalty)
                final_cars = max(0, c_dict['cars'] - vehicle_penalty)
                final_tanks = max(0, c_dict['tanks'] - (vehicle_penalty // 2))
                final_fighters = max(0, c_dict.get('fighters', 0) - (vehicle_penalty // 3))
                
                await db.execute("""
                    UPDATE countries 
                    SET budget = ?, materials = ?, steel = ?, electronics = ?, food = ?, oil = ?, citizens = ?,
                        infantry = ?, cars = ?, tanks = ?, fighters = ?
                    WHERE id = ?
                """, (new_budget, new_materials, new_steel, new_electronics, new_food, new_oil, new_citizens,
                      final_infantry, final_cars, final_tanks, final_fighters, c_dict['id']))
            await db.commit()
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Экономика: Тик успешно выполнен!")
        except Exception as e:
            logging.error(f"Ошибка экономики: {e}")
        finally:
            await db.close()

# ========================================================================
# МАШИНА СОСТОЯНИЙ (FSM)
# ========================================================================
class CreateCountry(StatesGroup):
    name = State()
    flag = State()

class CustomizeState(StatesGroup):
    new_name = State()
    new_flag = State()

class CreateAlliance(StatesGroup):
    name = State()
    flag = State()

class TradeState(StatesGroup):
    waiting_give_amt = State()
    waiting_take_amt = State()

class FeedbackState(StatesGroup):
    waiting_message = State()
    
class DeleteCountryState(StatesGroup):
    confirm = State()

class ShopState(StatesGroup):
    waiting_for_stars = State()

class PurchaseState(StatesGroup):
    waiting_for_quantity = State()
    confirm_purchase = State()

class AdminState(StatesGroup):
    npc_name = State()
    npc_flag = State()
    waiting_for_db = State()
    del_country = State()
    del_alliance = State()
    add_admin = State()
    rem_admin = State()
    give_target = State()
    give_type = State()
    give_amount = State()

class AdminTroopState(StatesGroup):
    give_target = State()
    give_type = State()
    give_amount = State()

class AdminFeedbackState(StatesGroup):
    replying_to = State()

# ========================================================================
# ГЕНЕРАТОР ТАБЛИЦ И СТРУКТУР ИНТЕРФЕЙСА
# ========================================================================
def generate_table_text(items_dict, category=None):
    """Формирует текстовую псевдотаблицу цен и параметров предметов."""
    text = "<pre>\n"
    text += f"{'Название'.ljust(12)}|{'💰'.center(5)}|{'🧱'.center(5)}|{'⚙️'.center(5)}|{'💻'.center(4)}|{'🛢'.center(4)}|{'🥩'.center(5)}"
    if category in ['ground', 'naval', 'air', 'drones']:
        text += f"|{'⚔️'.center(4)}\n"
    else:
        text += "\n"
    text += "-" * 54 + "\n"
    
    for key, data in items_dict.items():
        if category and data.get('cat') != category and category != 'buildings':
            continue
            
        name = data['name'].split()[1][:10] if len(data['name'].split()) > 1 else data['name'][:10]
        c = data['cost']
        row = f"{name.ljust(12)}|{str(c.get('budget',0)).center(5)}|{str(c.get('materials',0)).center(5)}|{str(c.get('steel',0)).center(5)}|{str(c.get('electronics',0)).center(4)}|{str(c.get('oil',0)).center(4)}|{str(c.get('food',0)).center(5)}"
        if 'power' in data:
            row += f"|{str(data['power']).center(4)}\n"
        else:
            row += f"\n"
        text += row
    text += "</pre>"
    return text

def create_buy_keyboard(items_dict, category, return_callback):
    """Строит сетку кнопок выбора товаров для покупки."""
    kb = []
    row = []
    for key, data in items_dict.items():
        if category != 'buildings' and data.get('cat') != category:
            continue
        btn_text = f"🛒 {data['name'].split()[1] if len(data['name'].split())>1 else data['name']}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"buyitem_{key}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: 
        kb.append(row)
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data=return_callback)])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ========================================================================
# НАВИГАЦИОННЫЕ И ИГРОВЫЕ КЛАВИАТУРЫ
# ========================================================================
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Моя Страна", callback_data="menu_profile"), InlineKeyboardButton(text="⚔️ Война", callback_data="menu_war")],
        [InlineKeyboardButton(text="🏭 Экономика", callback_data="menu_economy"), InlineKeyboardButton(text="🪖 Военкомат", callback_data="menu_army")],
        [InlineKeyboardButton(text="🤝 Альянс", callback_data="menu_alliance"), InlineKeyboardButton(text="📜 Политика и Религия", callback_data="menu_laws")],
        [InlineKeyboardButton(text="✉️ Поддержка", callback_data="menu_feedback"), InlineKeyboardButton(text="💎 Донат Магазин", callback_data="menu_shop")]
    ])

def army_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 Наземные войска и ПВО", callback_data="menu_army_ground")],
        [InlineKeyboardButton(text="⚓️ Военно-морской флот", callback_data="menu_army_naval")],
        [InlineKeyboardButton(text="🛩 Воздушные силы", callback_data="menu_army_air")],
        [InlineKeyboardButton(text="🛸 Беспилотные Войска", callback_data="menu_army_drones")],
        [InlineKeyboardButton(text="◀️ Назад в штаб", callback_data="menu_main")]
    ])

def policy_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Изменить форму правления", callback_data="policy_gov")],
        [InlineKeyboardButton(text="🕊 Изменить религию", callback_data="policy_rel")],
        [InlineKeyboardButton(text="📜 Принять/Отменить Законы", callback_data="policy_laws")],
        [InlineKeyboardButton(text="🎨 Кастомизация (Название/Флаг)", callback_data="policy_custom")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu_main")]
    ])

def shop_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✈️ Истребитель F-16 (50 ⭐️ | ⚔️5000)", callback_data="shop_buy_f16")],
        [InlineKeyboardButton(text="🚀 Ракета «Орешник» (200 ⭐️ | ⚔️12000)", callback_data="shop_buy_oreshnik")],
        [InlineKeyboardButton(text="💰 Бюджет (1⭐️ = 1500 💰)", callback_data="shop_res_budget"), InlineKeyboardButton(text="🧱 Материалы (1⭐️ = 150 🧱)", callback_data="shop_res_materials")],
        [InlineKeyboardButton(text="⚙️ Сталь (1⭐️ = 100 ⚙️)", callback_data="shop_res_steel"), InlineKeyboardButton(text="💻 Электроника (1⭐️ = 80 💻)", callback_data="shop_res_electronics")],
        [InlineKeyboardButton(text="🛢 Нефть (1⭐️ = 250 🛢)", callback_data="shop_res_oil"), InlineKeyboardButton(text="🥩 Еда (1⭐️ = 500 🥩)", callback_data="shop_res_food")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def policy_gov_kb(current_gov):
    kb = []
    for g_id, g_data in GOV_TYPES.items():
        marker = "✅ " if current_gov == g_id else ""
        kb.append([InlineKeyboardButton(text=f"{marker}{g_data['name']}", callback_data=f"setgov_{g_id}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_laws")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def policy_rel_kb(current_rel):
    kb = []
    for r_id, r_data in RELIGIONS.items():
        marker = "✅ " if current_rel == r_data['name'] else ""
        kb.append([InlineKeyboardButton(text=f"{marker}{r_data['name']}", callback_data=f"setrel_{r_id}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_laws")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def policy_laws_kb(active_laws_str):
    kb = []
    active = [l for l in (active_laws_str or "").split(",") if l]
    for l_id, l_data in LAWS.items():
        status = "🟢" if l_id in active else "🔴"
        kb.append([InlineKeyboardButton(text=f"{status} {l_data['name']}", callback_data=f"togglelaw_{l_id}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_laws")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def customization_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Сменить название (5,000$)", callback_data="custom_name")],
        [InlineKeyboardButton(text="🖼 Сменить флаг/фото (3,000$)", callback_data="custom_flag")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu_laws")]
    ])

def alliance_none_kb(alliances):
    kb = [[InlineKeyboardButton(text="➕ Создать Альянс (10,000$)", callback_data="aly_create")]]
    for aly in alliances:
        kb.append([InlineKeyboardButton(text=f"Подать заявку в {df(aly.get('flag'))} {aly.get('name')}", callback_data=f"aly_join_{aly.get('id')}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def alliance_member_kb(is_leader):
    kb = []
    if is_leader:
        kb.append([InlineKeyboardButton(text="📥 Заявки на вступление", callback_data="aly_reqs")])
        kb.append([InlineKeyboardButton(text="❌ Распустить Альянс", callback_data="aly_disband")])
    else:
        kb.append([InlineKeyboardButton(text="🚪 Покинуть Альянс", callback_data="aly_leave")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Сообщения игроков", callback_data="adm_feedbacks")],
        [InlineKeyboardButton(text="💰 Выдать/Забрать Ресурсы", callback_data="adm_resources"), InlineKeyboardButton(text="🪖 Выдать Войска", callback_data="adm_troops")],
        [InlineKeyboardButton(text="🎲 Запустить Случайный Ивент", callback_data="adm_event")],
        [InlineKeyboardButton(text="🌍 Управление Стран.", callback_data="adm_countries"), InlineKeyboardButton(text="🤝 Альянсы", callback_data="adm_alliances")],
        [InlineKeyboardButton(text="📦 Бэкапы и Откаты БД", callback_data="adm_backups")],
        [InlineKeyboardButton(text="👮‍♂️ Администраторы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="menu_main")]
    ])

def admin_countries_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Свободную Страну", callback_data="admin_create_free")],
        [InlineKeyboardButton(text="🤖 Создать NPC-страну", callback_data="admin_create_npc")],
        [InlineKeyboardButton(text="🗑 Удалить страну", callback_data="admin_del_country")],
        [InlineKeyboardButton(text="📋 Список стран (ID)", callback_data="admin_list_countries")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]
    ])

def admin_backups_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать базу (Бэкап)", callback_data="admin_download_db")],
        [InlineKeyboardButton(text="📤 Загрузить базу (Откат)", callback_data="admin_upload_db")],
        [InlineKeyboardButton(text="◀️ В админ-меню", callback_data="adm_main")]
    ])

def admin_alliances_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить альянс", callback_data="admin_del_alliance")],
        [InlineKeyboardButton(text="📋 Список альянсов (ID)", callback_data="admin_list_alliances")],
        [InlineKeyboardButton(text="◀️ В админ-меню", callback_data="adm_main")]
    ])

def admin_admins_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Назначить админа", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="➖ Снять админа", callback_data="admin_rem_admin")],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="◀️ В админ-меню", callback_data="adm_main")]
    ])

def admin_troop_type_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 Пех.", callback_data="atr_infantry"), InlineKeyboardButton(text="🎯 Пул.", callback_data="atr_machine_guns"), InlineKeyboardButton(text="💥 Мин.", callback_data="atr_mortars")],
        [InlineKeyboardButton(text="🚙 Авто", callback_data="atr_cars"), InlineKeyboardButton(text="🚙 Хамм.", callback_data="atr_hummers"), InlineKeyboardButton(text="🚛 Груз.", callback_data="atr_trucks")],
        [InlineKeyboardButton(text="🚜 ВМ", callback_data="atr_military_cars"), InlineKeyboardButton(text="💥 Арт.", callback_data="atr_artillery"), InlineKeyboardButton(text="🚜 Танк", callback_data="atr_tanks")],
        [InlineKeyboardButton(text="📡 Зенитка", callback_data="atr_aa_guns"), InlineKeyboardButton(text="🚀 ЗРК", callback_data="atr_sam_systems"), InlineKeyboardButton(text="🛡 Бункер", callback_data="atr_bunkers")],
        [InlineKeyboardButton(text="✈️ Истр.", callback_data="atr_fighters"), InlineKeyboardButton(text="🛩 Бомб.", callback_data="atr_bombers"), InlineKeyboardButton(text="🚁 Верт.", callback_data="atr_helicopters")],
        [InlineKeyboardButton(text="🛸 БПЛА", callback_data="atr_uavs"), InlineKeyboardButton(text="🚀 РБПЛА", callback_data="atr_jet_uavs"), InlineKeyboardButton(text="🦇 Б.Яга", callback_data="atr_baba_yaga")],
        [InlineKeyboardButton(text="🐝 ФПВ", callback_data="atr_fpv_drones"), InlineKeyboardButton(text="🛶 Лодка", callback_data="atr_boats"), InlineKeyboardButton(text="🚤 Корв.", callback_data="atr_corvettes")],
        [InlineKeyboardButton(text="🌊 Подл.", callback_data="atr_submarines"), InlineKeyboardButton(text="🛥 Эсм.", callback_data="atr_destroyers"), InlineKeyboardButton(text="🛳 Крейс.", callback_data="atr_cruisers")],
        [InlineKeyboardButton(text="⛴ Линкор", callback_data="atr_battleships"), InlineKeyboardButton(text="🛩 Авианосец", callback_data="atr_carriers")],
        [InlineKeyboardButton(text="◀️ В админ-меню", callback_data="adm_main")]
    ])

# ========================================================================
# БОЕВАЯ МОЩЬ И РАСЧЕТЫ БОЕВ
# ========================================================================
def get_base_power(country):
    c = dict(country)
    power = sum(c.get(k, 0) * v['power'] for k, v in ARMY_STATS.items() if k in c)
    power += c.get('f16', 0) * 5000
    power += c.get('oreshnik', 0) * 12000
    return power

async def get_alliance_support(alliance_id, exclude_country_id):
    if not alliance_id:
        return 0, 0
    allies = await fetch_all("SELECT * FROM countries WHERE alliance_id = ? AND id != ?", (alliance_id, exclude_country_id))
    if not allies:
        return 0, 0
    total_power = sum(get_base_power(ally) for ally in allies)
    support_power = int(total_power * 0.25)
    return support_power, len(allies)

# ========================================================================
# ИНТЕРАКТИВНАЯ СИСТЕМА ПОКУПКИ (С КУПЛЕЙ ПО КОЛИЧЕСТВУ)
# ========================================================================
@dp.callback_query(F.data.startswith("buyitem_"))
async def start_buy_item(callback: types.CallbackQuery, state: FSMContext):
    if is_spam(callback.from_user.id): 
        return await callback.answer("⏳ Не так быстро!")
        
    item_key = callback.data.split("_")[1]
    item_data = ARMY_STATS.get(item_key) or BUILDING_STATS.get(item_key)
    
    if not item_data: 
        return await callback.answer("Ошибка: предмет не найден.", show_alert=True)
    
    await state.update_data(buy_item_key=item_key, is_army=item_key in ARMY_STATS)
    await safe_edit(callback.message, 
        f"🛒 <b>Покупка: {item_data['name']}</b>\n\n"
        f"Введите в чат <b>желаемое число</b> для приобретения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="menu_main")]])
    )
    await state.set_state(PurchaseState.waiting_for_quantity)
    await callback.answer()

@dp.message(PurchaseState.waiting_for_quantity)
async def process_buy_quantity(message: types.Message, state: FSMContext):
    try:
        qty = int(message.text)
        if qty <= 0: 
            return await message.answer("Число должно быть больше нуля!")
    except ValueError:
        return await message.answer("Пожалуйста, введите корректное число.")
        
    data = await state.get_data()
    item_key = data['buy_item_key']
    is_army = data['is_army']
    item_data = ARMY_STATS.get(item_key) if is_army else BUILDING_STATS.get(item_key)
    
    total_cost = {k: v * qty for k, v in item_data['cost'].items()}
    await state.update_data(buy_qty=qty, total_cost=total_cost)
    
    receipt = f"🧾 <b>Чек на проведение транзакции</b>\n\nТовар: {item_data['name']} x{qty}\n\n<b>Итого к списанию:</b>\n"
    for res_key, amount in total_cost.items():
        if amount > 0: 
            receipt += f"• {RES_MAP[res_key]}: {amount:,}\n"
        
    receipt += "\nПодтверждаете проведение платежа?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплатить", callback_data="confirm_purchase")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_main")]
    ])
    await message.answer(receipt, reply_markup=kb)
    await state.set_state(PurchaseState.confirm_purchase)

@dp.callback_query(PurchaseState.confirm_purchase, F.data == "confirm_purchase")
async def execute_purchase(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_key = data['buy_item_key']
    qty = data['buy_qty']
    cost = data['total_cost']
    is_army = data['is_army']
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    for res_key, amount in cost.items():
        if country.get(res_key, 0) < amount:
            await state.clear()
            return await safe_edit(callback.message, f"❌ Недостаточно средств: не хватает {RES_MAP[res_key]}!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В меню", callback_data="menu_main")]]))

    set_query = ", ".join([f"{res} = {res} - {amt}" for res, amt in cost.items() if amt > 0])
    item_data = ARMY_STATS.get(item_key) if is_army else BUILDING_STATS.get(item_key)
    added_qty = qty * item_data.get('qty_mod', 1)
    
    if is_army:
        query = f"UPDATE countries SET {set_query}, {item_key} = {item_key} + {added_qty} WHERE id = {country['id']}"
    else:
        if item_key == "settlements":
            query = f"UPDATE countries SET {set_query}, settlements = settlements + {qty}, gdp = gdp + {200 * qty} WHERE id = {country['id']}"
        else:
            query = f"UPDATE countries SET {set_query}, {item_key} = {item_key} + {qty} WHERE id = {country['id']}"

    await execute_db(query)
    await state.clear()
    await safe_edit(callback.message, f"✅ Успешно приобретено: {item_data['name']} (x{added_qty})!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Вернуться в штаб", callback_data="menu_main")]]))
    await callback.answer()

# ========================================================================
# ТАКТИКА, РАЗВЕДКА И ВОЕННЫЕ СРАЖЕНИЯ
# ========================================================================
@dp.callback_query(F.data.startswith("prepwar_"))
async def prepare_war(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    geo_info = "\n<b>Особенности ландшафта цели:</b>\n"
    if defender.get('mountains', 0) > 0:
        geo_info += "⛰ Горы: Значительно повышает уровень обороны противника.\n"
    if defender.get('forests', 0) > 0:
        geo_info += "🌲 Леса: Замедляют движение, штраф к силе атаки.\n"
    if defender.get('deserts', 0) > 0:
        geo_info += "🏜 Пустыни: Чистая открытая местность.\n"
    if defender.get('rivers', 0) > 0:
        geo_info += f"🏞 Реки ({defender.get('rivers')} шт.): Потребуются понтонные мосты.\n"
    if defender.get('seas', 0) > 0:
        geo_info += "🌊 Выход к морю: Десантирование без флота ослабит атаку наполовину!\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Блицкриг (Атака +30%, Риск потерь)", callback_data=f"tactic_blitz_{target_id}")],
        [InlineKeyboardButton(text="🛡 Осада (Атака -10%, Меньше потерь)", callback_data=f"tactic_siege_{target_id}")],
        [InlineKeyboardButton(text="⚖️ Стандартный бой", callback_data=f"tactic_balance_{target_id}")],
        [InlineKeyboardButton(text="🕵️‍♂️ Разведка (1 Шпион)", callback_data=f"spy_{target_id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu_war")]
    ])
    await safe_edit(callback.message, f"⚔️ <b>Определите доктрину атаки на {df(defender.get('flag'))} {defender.get('name')}:</b>\n{geo_info}\n<i>Кампания стоит 200 Еды и 100 Нефти на снабжение.</i>", reply_markup=kb)

@dp.callback_query(F.data.startswith("spy_"))
async def process_spy(callback: types.CallbackQuery):
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        return await callback.answer(f"⏳ Разведчики перегруппируются! Будет готово через {cd} сек.", show_alert=True)
        
    target_id = int(callback.data.split("_")[1])
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if attacker.get('spies', 0) < 1:
        return await callback.answer("У вас нет свободных шпионов!", show_alert=True)
        
    await execute_db("UPDATE countries SET spies = spies - 1 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id)
    
    if random.random() < 0.2:
        await callback.answer("Шпион обнаружен и нейтрализован контрразведкой!", show_alert=True)
        return await safe_edit(callback.message, "💥 <b>Провал операции!</b> Ваш агент был раскрыт на границе.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_war")]]]))
        
    def_power_est = get_base_power(defender)
    text = (
        f"🕵️‍♂️ <b>Шпионский рапорт по {df(defender.get('flag'))} {defender.get('name')}</b>:\n\n"
        f"💰 Бюджет: ~{defender.get('budget', 0):,}$ | 🛢 Нефть: {defender.get('oil', 0):,}\n"
        f"🪖 Пехота: {defender.get('infantry', 0)} | 🚜 Танки: {defender.get('tanks', 0)}\n"
        f"🛡 Оборона: {defender.get('bunkers', 0)} бункеров | {defender.get('sam_systems',0)} ЗРК\n\n"
        f"📊 Расчетная базовая мощь врага: <b>{def_power_est}</b>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Блицкриг", callback_data=f"tactic_blitz_{target_id}")],
        [InlineKeyboardButton(text="🛡 Осада", callback_data=f"tactic_siege_{target_id}")],
        [InlineKeyboardButton(text="⚖️ Стандарт", callback_data=f"tactic_balance_{target_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_war")]
    ])
    await safe_edit(callback.message, text, reply_markup=kb)
    await callback.answer("Данные внедрения получены!")

@dp.callback_query(F.data.startswith("tactic_"))
async def execute_war(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): 
        return await callback.answer("⏳ Не так быстро!")
    
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        return await callback.answer(f"Генеральный штаб на перегруппировке! Доступно через {cd} сек.", show_alert=True)
        
    parts = callback.data.split("_")
    tactic = parts[1]
    target_id = int(parts[2])
    
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if not attacker or not defender: 
        return await callback.answer("Ошибка: Страна не найдена.", show_alert=True)
    if attacker['food'] < 200 or attacker['oil'] < 100:
        return await callback.answer("Не хватает ресурсов для мобилизации (200 Еды, 100 Нефти)!", show_alert=True)

    await execute_db("UPDATE countries SET food = food - 200, oil = oil - 100 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id)

    await safe_edit(callback.message, "🚀 <b>Войска пересекают границу...</b>\n\n🛰 Развертывание систем спутникового слежения...")
    await asyncio.sleep(2)

    att_rates = calc_economy_rates(attacker)
    def_rates = calc_economy_rates(defender)
    
    att_ally_support, att_ally_count = await get_alliance_support(attacker.get('alliance_id'), attacker['id'])
    def_ally_support, def_ally_count = await get_alliance_support(defender.get('alliance_id'), defender['id'])
    
    att_power = get_base_power(attacker) * att_rates['att_mod'] + att_ally_support
    def_power = get_base_power(defender) * def_rates['def_mod'] + def_ally_support
    
    report = [f"<blockquote>🌍 <b>СВОДКА ВОЕННЫХ ДЕЙСТВИЙ: {df(attacker.get('flag'))} против {df(defender.get('flag'))}</b></blockquote>\n"]
    
    if att_ally_count > 0:
        report.append(f"🤝 Силы союзников по альянсу прибыли на помощь! (+{att_ally_support} к атаке)")
    if def_ally_count > 0:
        report.append(f"⚠️ Оборонительный пакт врага активирован! Соседние страны защищают его (+{def_ally_support} к защите)")

    if tactic == "blitz": 
        att_power *= 1.3
    elif tactic == "siege": 
        att_power *= 0.9

    # Ландшафтные модификаторы защитника
    def_bonus = 1.0 + (defender.get('mountains', 0) * 0.15) + (defender.get('forests', 0) * 0.05)
    def_power *= def_bonus
    if defender.get('mountains', 0) > 0:
        report.append("⛰ Оборонительные редуты в горах дают врагу +15% к стойкости.")
    if defender.get('forests', 0) > 0:
        report.append("🌲 Густые леса снижают эффективность вашей бронетехники.")
        
    bridges_used = 0
    if defender.get('rivers', 0) > 0:
        if attacker.get('bridges', 0) >= defender.get('rivers', 0):
            bridges_used = defender['rivers']
            report.append(f"🌉 Ваши инженерные войска навели {bridges_used} понтонных мостов для форсирования рек.")
        else:
            att_power *= 0.70
            report.append("🏞 Речные преграды не форсированы! Наступление замедлено (Штраф атаки -30%).")
            
    if defender.get('seas', 0) > 0:
        has_navy = (attacker.get('destroyers', 0) > 0 or attacker.get('cruisers', 0) > 0 or attacker.get('battleships', 0) > 0 or attacker.get('carriers', 0) > 0)
        if not has_navy:
            att_power *= 0.50
            report.append("🌊 Морской берег не прикрыт флотом! Наступающие десантные силы понесли огромные потери (Штраф -50%).")
        else:
            report.append("⛴ Корабли поддержки успешно подавили береговые батареи противника!")

    # Скрытое донатное оружие
    att_f16, def_f16 = attacker.get('f16', 0), defender.get('f16', 0)
    att_oreshnik, def_oreshnik = attacker.get('oreshnik', 0), defender.get('oreshnik', 0)
    
    if att_f16 > 0:
        report.append(f"✈️ Скрытые звенья истребителей F-16 Falcon ({att_f16} шт.) захватили господство в воздухе!")
    if def_f16 > 0:
        report.append(f"⚠️ Вражеские скрытые F-16 Falcon ({def_f16} шт.) сорвали планы вашей авиации!")
    if att_oreshnik > 0:
        report.append(f"☄️ Ракета Орешник ({att_oreshnik} шт.) уничтожила командные бункеры врага!")
    if def_oreshnik > 0:
        report.append(f"☠️ Силы ПВО зафиксировали удар гиперзвукового Орешника ({def_oreshnik} шт.) по нашим тылам!")

    # Рандомизация (±15%)
    att_final = int(att_power * random.uniform(0.85, 1.15))
    def_final = int(def_power * random.uniform(0.85, 1.15))
    
    loss_ratio_att = random.uniform(0.05, 0.20) if tactic != "blitz" else random.uniform(0.15, 0.30)
    loss_ratio_def = random.uniform(0.10, 0.25) if tactic != "siege" else random.uniform(0.05, 0.15)

    report.append(f"\n⚔️ Расчетная мощь наступления: <b>{att_final:,}</b>")
    report.append(f"🛡 Расчетная мощь обороны: <b>{def_final:,}</b>\n")

    if att_final > def_final:
        stolen_budget = int(defender['budget'] * random.uniform(0.2, 0.35))
        stolen_materials = int(defender['materials'] * random.uniform(0.2, 0.35))
        stolen_steel = int(defender.get('steel', 0) * random.uniform(0.15, 0.3))
        stolen_electronics = int(defender.get('electronics', 0) * random.uniform(0.15, 0.3))
        stolen_oil = int(defender.get('oil', 0) * random.uniform(0.15, 0.3))
        stolen_territory = random.randint(1, 3)
        
        await execute_db("""
            UPDATE countries 
            SET budget = budget + ?, materials = materials + ?, steel = steel + ?, electronics = electronics + ?, oil = oil + ?,
                war_wins = war_wins + 1, territory = territory + ?, bridges = MAX(0, bridges - ?) 
            WHERE id = ?
        """, (stolen_budget, stolen_materials, stolen_steel, stolen_electronics, stolen_oil, stolen_territory, bridges_used, attacker['id']))
        
        await execute_db("""
            UPDATE countries 
            SET budget = max(0, budget - ?), materials = max(0, materials - ?), steel = max(0, steel - ?), 
                electronics = max(0, electronics - ?), oil = max(0, oil - ?),
                war_losses = war_losses + 1, territory = max(1, territory - ?), gdp = max(10, gdp - ?), bunkers = max(0, bunkers - 1)
            WHERE id = ?
        """, (stolen_budget, stolen_materials, stolen_steel, stolen_electronics, stolen_oil, stolen_territory, stolen_territory * 5, defender['id']))
        
        report.append("🏆 <b>Вы одержали ПОЛНУЮ ПОБЕДУ!</b> Оборона была сметена.")
        report.append("<b>────────────────────────</b>")
        report.append(f"💰 Захвачено: {stolen_budget:,}$ | 🧱 {stolen_materials:,} мат. | ⚙️ {stolen_steel:,} стали")
        report.append(f"🛢 Изъято нефти: {stolen_oil:,} | 💻 Электроника: {stolen_electronics:,}")
        report.append(f"🗺 Аннексированная территория: +{stolen_territory} км² (+{stolen_territory * 5} к ВВП)")
    else:
        await execute_db("UPDATE countries SET war_losses = war_losses + 1, bridges = MAX(0, bridges - ?) WHERE id = ?", (bridges_used, attacker['id']))
        await execute_db("UPDATE countries SET war_wins = war_wins + 1 WHERE id = ?", (defender['id'],))
        report.append("💀 <b>Вы потерпели разгромное ПОРАЖЕНИЕ!</b> Наступление захлебнулось.")

    # Вычисление потерь армий
    att_inf_loss = int(attacker.get('infantry', 0) * loss_ratio_att)
    att_tank_loss = int(attacker.get('tanks', 0) * (loss_ratio_att / 2))
    def_inf_loss = int(defender.get('infantry', 0) * loss_ratio_def)
    def_tank_loss = int(defender.get('tanks', 0) * (loss_ratio_def / 2))
    
    await execute_db("UPDATE countries SET infantry = max(0, infantry - ?), tanks = max(0, tanks - ?) WHERE id = ?", (att_inf_loss, att_tank_loss, attacker['id']))
    await execute_db("UPDATE countries SET infantry = max(0, infantry - ?), tanks = max(0, tanks - ?) WHERE id = ?", (def_inf_loss, def_tank_loss, defender['id']))
    
    report.append(f"\n🩸 <b>Наши безвозвратные потери:</b> {att_inf_loss} Пехоты, {att_tank_loss} Танков.")
    report.append(f"💥 <b>Потери противника:</b> {def_inf_loss} Пехоты, {def_tank_loss} Танков.")
    
    if defender.get('owner_id'):
        try:
            await bot.send_message(defender['owner_id'], f"🚨 <b>ГЕОПОЛИТИЧЕСКАЯ УГРОЗА!</b>\nСтрана {df(attacker['flag'])} {attacker['name']} напала на ваши рубежи!\nРезультат: {'Наши рубежи прорваны!' if att_final > def_final else 'Мы успешно отбились!'}")
        except: 
            pass

    await safe_edit(callback.message, "\n".join(report), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В штаб", callback_data="menu_main")]]))

# ========================================================================
# ТОРГОВАЯ СИСТЕМА И РЫНОК ОБМЕНА МЕЖДУ ИГРОКАМИ (/trade)
# ========================================================================
def trade_builder_kb(trade_id, t_data):
    g_res = RES_MAP[t_data['give_res']]
    t_res = RES_MAP[t_data['take_res']]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Отдаю: {g_res}", callback_data=f"tr_cyclegive_{trade_id}")],
        [InlineKeyboardButton(text=f"Кол-во на отдачу: {t_data['give_amt']}", callback_data=f"tr_setgive_{trade_id}")],
        [InlineKeyboardButton(text=f"🔄 Прошу: {t_res}", callback_data=f"tr_cycletake_{trade_id}")],
        [InlineKeyboardButton(text=f"Кол-во получения: {t_data['take_amt']}", callback_data=f"tr_settake_{trade_id}")],
        [InlineKeyboardButton(text="✅ Отправить предложение", callback_data=f"tr_send_{trade_id}")],
        [InlineKeyboardButton(text="❌ Отмена сделки", callback_data=f"tr_cancel_{trade_id}")]
    ])

@dp.message(Command("trade"))
async def cmd_trade(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        return await message.answer(
            "🤝 <b>Рыночный сектор и Дипломатический Обмен</b>\n\n"
            "Вы можете обмениваться ресурсами напрямую.\n"
            "Использование: <code>/trade [ID игрока или @username]</code>\n"
            "<i>Пример:</i> <code>/trade @alex_rules</code>"
        )
    
    target_str = args[1]
    sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not sender: 
        return await message.answer("❌ У вас нет зарегистрированного государства!")
    
    target_country = None
    if target_str.startswith("@"):
        target_username = target_str[1:]
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target_username,))
    elif target_str.isdigit():
        target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target_str),))
        
    if not target_country:
        return await message.answer("❌ Целевое государство не найдено в реестрах ООН.")
    if sender['id'] == target_country['id']:
        return await message.answer("❌ Вы не можете торговать с собственной экономикой.")

    t_id = str(uuid.uuid4())[:8]
    ACTIVE_TRADES[t_id] = {
        'sender_id': sender['owner_id'], 'receiver_id': target_country['owner_id'],
        'give_res': 'budget', 'give_amt': 0, 'take_res': 'materials', 'take_amt': 0,
        'target_name': f"{df(target_country.get('flag'))} {target_country.get('name')}"
    }
    
    await message.answer(
        f"🛠 <b>Конструктор внешнеторгового договора</b> с {ACTIVE_TRADES[t_id]['target_name']}\n\nУстановите параметры соглашения:",
        reply_markup=trade_builder_kb(t_id, ACTIVE_TRADES[t_id])
    )

@dp.callback_query(F.data.startswith("tr_cycle"))
async def tr_cycle_res(callback: types.CallbackQuery):
    try:
        action, t_id = callback.data.split("_")[1], callback.data.split("_")[2]
        if t_id not in ACTIVE_TRADES: 
            return await callback.answer("Сделка аннулирована.", show_alert=True)
        
        res_list = list(RES_MAP.keys())
        field = 'give_res' if action == 'cyclegive' else 'take_res'
        
        cur_idx = res_list.index(ACTIVE_TRADES[t_id][field])
        ACTIVE_TRADES[t_id][field] = res_list[(cur_idx + 1) % len(res_list)]
        
        await callback.message.edit_reply_markup(reply_markup=trade_builder_kb(t_id, ACTIVE_TRADES[t_id]))
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Системный сбой смены ресурса!", show_alert=True)

@dp.callback_query(F.data.startswith("tr_set"))
async def tr_set_amt(callback: types.CallbackQuery, state: FSMContext):
    try:
        action, t_id = callback.data.split("_")[1], callback.data.split("_")[2]
        if t_id not in ACTIVE_TRADES: 
            return await callback.answer("Сделка просрочена.", show_alert=True)
        
        await state.update_data(current_trade_id=t_id, trade_msg_id=callback.message.message_id)
        if action == 'setgive':
            await callback.message.answer("Укажите объем передаваемых ресурсов:")
            await state.set_state(TradeState.waiting_give_amt)
        else:
            await callback.message.answer("Укажите объем запрашиваемых взамен ресурсов:")
            await state.set_state(TradeState.waiting_take_amt)
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Системный сбой ввода объема!", show_alert=True)

@dp.message(TradeState.waiting_give_amt)
@dp.message(TradeState.waiting_take_amt)
async def tr_process_amt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = data.get('current_trade_id')
    if t_id not in ACTIVE_TRADES: 
        await state.clear()
        return await message.answer("Сделка аннулирована.")
        
    try: 
        amt = int(message.text)
    except ValueError: 
        return await message.answer("Пожалуйста, введите корректное целое число.")
    
    if amt < 0: 
        amt = 0
    
    current_state = await state.get_state()
    if current_state == TradeState.waiting_give_amt.state:
        ACTIVE_TRADES[t_id]['give_amt'] = amt
    else:
        ACTIVE_TRADES[t_id]['take_amt'] = amt
        
    await state.clear()
    try: 
        await message.delete()
    except: 
        pass
    
    try:
        await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=data['trade_msg_id'], reply_markup=trade_builder_kb(t_id, ACTIVE_TRADES[t_id]))
    except: 
        pass

@dp.callback_query(F.data.startswith("tr_cancel_"))
async def tr_cancel(callback: types.CallbackQuery):
    t_id = callback.data.split("_")[2]
    if t_id in ACTIVE_TRADES: 
        del ACTIVE_TRADES[t_id]
    await safe_edit(callback.message, "Конструктор сделки закрыт.")
    await callback.answer("Сделка отменена.")

@dp.callback_query(F.data.startswith("tr_send_"))
async def tr_send_offer(callback: types.CallbackQuery):
    t_id = callback.data.split("_")[2]
    trade = ACTIVE_TRADES.get(t_id)
    if not trade: 
        return await callback.answer("Сделка просрочена.", show_alert=True)
    
    sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (trade['sender_id'],))
    if sender.get(trade['give_res'], 0) < trade['give_amt']:
        return await callback.answer("У вас нет такого количества ресурсов для отдачи!", show_alert=True)
        
    await safe_edit(callback.message, f"⏳ Предложение успешно отправлено {trade['target_name']}. Ожидаем решения...")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подписать договор", callback_data=f"tr_accept_{t_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tr_decline_{t_id}")]
    ])
    try:
        await bot.send_message(
            trade['receiver_id'], 
            f"🤝 <b>Внешнеторговое соглашение на подпись!</b>\nОтправитель: {df(sender.get('flag'))} {sender.get('name')}\n\n"
            f"📦 <b>Вам отправляют:</b> {trade['give_amt']} {RES_MAP[trade['give_res']]}\n"
            f"🛒 <b>Взамен требуют:</b> {trade['take_amt']} {RES_MAP[trade['take_res']]}",
            reply_markup=kb
        )
    except:
        await callback.message.answer("Не удалось связаться с дипломатической миссией получателя.")
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_accept_"))
async def tr_accept(callback: types.CallbackQuery):
    t_id = callback.data.split("_")[2]
    trade = ACTIVE_TRADES.get(t_id)
    if not trade: 
        return await callback.answer("Сделка более недееспособна.", show_alert=True)
    
    if callback.from_user.id != trade['receiver_id']: 
        return await callback.answer("Это соглашение адресовано не вам!", show_alert=True)
    
    sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (trade['sender_id'],))
    receiver = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (trade['receiver_id'],))
    
    if sender.get(trade['give_res'], 0) < trade['give_amt']:
        return await callback.answer("У отправителя иссякли резервы!", show_alert=True)
    if receiver.get(trade['take_res'], 0) < trade['take_amt']:
        return await callback.answer(f"У вас недостаточно {RES_MAP[trade['take_res']]}!", show_alert=True)
        
    await execute_db(f"UPDATE countries SET {trade['give_res']} = {trade['give_res']} - ? WHERE id = ?", (trade['give_amt'], sender['id']))
    await execute_db(f"UPDATE countries SET {trade['take_res']} = {trade['take_res']} + ? WHERE id = ?", (trade['take_amt'], sender['id']))
    
    await execute_db(f"UPDATE countries SET {trade['give_res']} = {trade['give_res']} + ? WHERE id = ?", (trade['give_amt'], receiver['id']))
    await execute_db(f"UPDATE countries SET {trade['take_res']} = {trade['take_res']} - ? WHERE id = ?", (trade['take_amt'], receiver['id']))
    
    await safe_edit(callback.message, "✅ Сделка подписана! Ресурсы распределены по экономикам.")
    try: 
        await bot.send_message(trade['sender_id'], f"✅ Игрок {df(receiver.get('flag'))} {receiver.get('name')} подписал ваш внешнеторговый договор!")
    except: 
        pass
    del ACTIVE_TRADES[t_id]
    await callback.answer("Сделка закрыта!")

@dp.callback_query(F.data.startswith("tr_decline_"))
async def tr_decline(callback: types.CallbackQuery):
    t_id = callback.data.split("_")[2]
    trade = ACTIVE_TRADES.get(t_id)
    if trade:
        try: 
            await bot.send_message(trade['sender_id'], "❌ Торговое соглашение было расторгнуто принимающей стороной.")
        except: 
            pass
        del ACTIVE_TRADES[t_id]
    await safe_edit(callback.message, "Сделка отклонена.")
    await callback.answer("Сделка отклонена.")

# ========================================================================
# СТАРТ, ОСНОВАНИЕ И КАРТОГРАФИЯ СТРАНЫ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await update_username(message.from_user.id, message.from_user.username)
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if country:
        return await message.answer(
            f"С возвращением, Правитель!\nТвоя страна: <b>{df(country.get('flag'))} {country.get('name')}</b>", 
            reply_markup=main_menu_kb()
        )
        
    unclaimed = await fetch_all("SELECT * FROM countries WHERE is_unclaimed = 1")
    if unclaimed:
        kb = [[InlineKeyboardButton(text="➕ Основать новую страну", callback_data="start_create")]]
        for c in unclaimed:
            kb.append([InlineKeyboardButton(text=f"👑 Занять {df(c.get('flag'))} {c.get('name')} (Готовая)", callback_data=f"claim_free_{c.get('id')}")])
        await message.answer(
            "🌍 <b>Добро пожаловать в геополитический симулятор!</b>\n\n"
            "Вы можете основать нацию с нуля или занять место лидера в брошенном государстве:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        await message.answer("🌍 <b>Основание государства!</b>\nВведите <b>Название</b> вашей новой державы:")
        await state.set_state(CreateCountry.name)

@dp.callback_query(F.data == "start_create")
async def start_create_btn(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Введите <b>Название</b> новой державы:")
    await state.set_state(CreateCountry.name)
    await callback.answer()

@dp.callback_query(F.data.startswith("claim_free_"))
async def claim_free_country(callback: types.CallbackQuery):
    c_id = int(callback.data.split("_")[2])
    country = await fetch_one("SELECT * FROM countries WHERE id = ? AND is_unclaimed = 1", (c_id,))
    
    if not country:
        return await callback.answer("Эта страна уже занята другим правителем!", show_alert=True)
        
    await execute_db(
        "UPDATE countries SET owner_id = ?, username = ?, is_unclaimed = 0 WHERE id = ?",
        (callback.from_user.id, callback.from_user.username or "", c_id)
    )
    await safe_edit(callback.message, 
        f"🎉 Вы успешно возглавили развивающееся государство <b>{df(country.get('flag'))} {country.get('name')}</b>!\n"
        f"Откройте профиль, чтобы ознакомиться с текущими запасами и армией.",
        reply_markup=main_menu_kb()
    )
    await callback.answer()

@dp.message(CreateCountry.name)
async def process_country_name(message: types.Message, state: FSMContext):
    if len(message.text) > 30:
        return await message.answer("Слишком длинное имя! Максимум 30 символов:")
    await state.update_data(name=message.text[:30])
    await message.answer("Пришлите <b>Эмодзи</b> флага вашей страны ИЛИ загрузите <b>Фотографию</b> герба (разрешение 16:9):")
    await state.set_state(CreateCountry.flag)

@dp.message(CreateCountry.flag, F.text | F.photo)
async def process_country_flag(message: types.Message, state: FSMContext):
    if message.photo:
        photo = message.photo[-1]
        flag = f"photo:{photo.file_id}"
    elif message.text:
        flag = message.text[:2] 
    else:
        return await message.answer("❌ Пожалуйста, пришлите эмодзи или загрузите фото флага/герба!")

    data = await state.get_data()
    rivers = random.randint(0, 3)
    seas = random.randint(0, 1)
    mountains = random.randint(0, 2)
    forests = random.randint(0, 3)
    deserts = random.randint(0, 1)
    
    await execute_db(
        """INSERT INTO countries 
           (owner_id, username, name, flag, budget, materials, steel, electronics, oil, food, citizens, 
            rivers, seas, mountains, forests, deserts) 
           VALUES (?, ?, ?, ?, 20000, 5000, 1000, 500, 2000, 10000, 15000, ?, ?, ?, ?, ?)""",
        (message.from_user.id, message.from_user.username or "", data['name'], flag, rivers, seas, mountains, forests, deserts)
    )
    
    await message.answer(
        f"🎉 Государство <b>{df(flag)} {data['name']}</b> успешно основано!\n\n"
        f"🏞 <b>Ландшафт ваших территорий:</b> Реки ({rivers}), Море ({'Есть' if seas else 'Нет'}), Горы ({mountains}), Леса ({forests}), Пустыни ({deserts})\n"
        f"💰 Вам начислен стартовый капитал на развитие инфраструктуры.",
        reply_markup=main_menu_kb()
    )
    await state.clear()

# ========================================================================
# ИГРОВЫЕ МЕНЮ И НАВИГАЦИОННАЯ СИСТЕМА
# ========================================================================
@dp.callback_query(F.data.startswith("menu_"))
async def process_menus(callback: types.CallbackQuery, state: FSMContext):
    if is_spam(callback.from_user.id): 
        return await callback.answer("⏳ Не так быстро!", show_alert=False)
        
    if state: 
        await state.clear()
        
    await update_username(callback.from_user.id, callback.from_user.username)
    action = callback.data.split("_", 1)[1]
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: 
        return await callback.answer("У вас нет государства! Напишите /start", show_alert=True)

    if action == "profile":
        aly_text = "Нет"
        if country.get('alliance_id'):
            aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
            if aly: 
                aly_text = f"{df(aly.get('flag'))} {aly.get('name')}"

        geo = f"🏞 Рек: {country.get('rivers', 0)} | 🌊 Море: {'Есть' if country.get('seas', 0) else 'Нет'} | ⛰ Гор: {country.get('mountains',0)} | 🌲 Лесов: {country.get('forests',0)} | 🏜 Пустынь: {country.get('deserts',0)}"
        gov_name = GOV_TYPES.get(country.get('gov_type'), {}).get('name', 'Не выбрано')
        
        flag = country.get('flag') or "🏳️"
        photo_id = flag.split(":")[1] if flag.startswith("photo:") else None

        text = (
            f"🌍 <b>Государство:</b> {df(flag)} {country['name']} (Побед: {country.get('war_wins', 0)} / Поражений: {country.get('war_losses', 0)})\n"
            f"🏛 <b>Правление:</b> {gov_name} | 🕊 <b>Религия:</b> {country.get('religion', 'Атеизм')}\n"
            f"👥 <b>Граждане:</b> {country.get('citizens', 10000):,}\n"
            f"🤝 <b>Дип.Альянс:</b> {aly_text}\n"
            f"🗺 <b>Ландшафт:</b> {geo}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"💰 <b>Бюджет:</b> {country.get('budget', 0):,}$\n"
            f"🧱 <b>Мат:</b> {country.get('materials', 0):,} | ⚙️ <b>Сталь:</b> {country.get('steel',0):,} | 💻 <b>Электр.:</b> {country.get('electronics',0):,}\n"
            f"🛢 <b>Нефть:</b> {country.get('oil', 0):,} | 🥩 <b>Еда:</b> {country.get('food', 0):,}\n"
            f"⚔️ <b>Армейская мощь:</b> {get_base_power(country):,}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"<i>Для управления нажимайте на кнопки панели:</i>"
        )
        p_kb = main_menu_kb().inline_keyboard.copy()
        p_kb.append([InlineKeyboardButton(text="🧨 Покинуть пост (Удалить страну)", callback_data="delete_self_warn")])
        await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=p_kb), photo_id=photo_id)
        await callback.answer()

    elif action == "main":
        await safe_edit(callback.message, "Штаб Главнокомандующего. Ожидаю приказов:", reply_markup=main_menu_kb())
        await callback.answer()

    elif action == "economy":
        rates = calc_economy_rates(country)
        text = f"🏭 <b>Министерство Экономики (Тик: 3 мин)</b>\n"
        text += f"💵 {country['budget']:,}$ (+{rates['prod_money']}) | 🧱 {country['materials']:,} (+{rates['prod_materials']}) | ⚙️ {country.get('steel',0):,} (+{rates['prod_steel']})\n"
        text += f"💻 {country.get('electronics',0):,} (+{rates['prod_electronics']}) | 🛢 {country['oil']:,} (+{rates['prod_oil']}-{rates['cons_oil']}) | 🥩 {country['food']:,} (+{rates['prod_food']}-{rates['cons_food']})\n\n"
        text += "<b>Доступные постройки (Таблица стоимости):</b>\n"
        text += generate_table_text(BUILDING_STATS, category='buildings')
        text += "\n<i>Выберите здание для приобретения:</i>"
        await safe_edit(callback.message, text, reply_markup=create_buy_keyboard(BUILDING_STATS, 'buildings', "menu_main"))
        await callback.answer()

    elif action == "army":
        await safe_edit(callback.message, "🪖 <b>Министерство Обороны</b>\nВыберите род войск для открытия таблицы закупок:", reply_markup=army_main_kb())
        await callback.answer()

    elif action in ["army_ground", "army_naval", "army_air", "army_drones"]:
        cat = action.replace("army_", "")
        cat_names = {"ground": "Наземные", "naval": "Флот", "air": "Авиация", "drones": "БПЛА"}
        text = f"🪖 <b>{cat_names[cat]} войска - Сводная Таблица:</b>\n"
        text += f"Ваши ресурсы: 💰{country['budget']:,}$ 🥩{country['food']:,} 🧱{country['materials']:,} ⚙️{country.get('steel',0):,} 💻{country.get('electronics',0):,}\n\n"
        text += generate_table_text(ARMY_STATS, category=cat)
        text += "\n<i>Выберите юнит для оптовой закупки:</i>"
        await safe_edit(callback.message, text, reply_markup=create_buy_keyboard(ARMY_STATS, cat, "menu_army"))
        await callback.answer()

    elif action == "laws":
        gov_name = GOV_TYPES.get(country.get('gov_type'), {}).get('name', 'Не выбрано')
        rel_name = country.get('religion', 'Атеизм')
        rel_desc = RELIGIONS.get(rel_name, {}).get('desc', '')
        text = (f"📜 <b>Внутренняя Политика</b>\n\n"
                f"🏛 <b>Форма правления:</b> {gov_name}\n"
                f"🕊 <b>Религия:</b> {rel_name} ({rel_desc})\n\n"
                f"<i>Вы можете изменять политический курс вашей страны здесь.</i>")
        await safe_edit(callback.message, text, reply_markup=policy_main_kb())
        await callback.answer()

    elif action == "war":
        targets = await fetch_all("SELECT * FROM countries WHERE id != ? AND is_unclaimed = 0 ORDER BY RANDOM() LIMIT 20", (country['id'],))
        kb = [[InlineKeyboardButton(text=f"{df(t['flag'])} {t['name']} (⚔️ {get_base_power(t):,})", callback_data=f"prepwar_{t['id']}")] for t in targets]
        kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
        await safe_edit(callback.message, "⚔️ <b>Радар: Доступные цели</b>\nВыберите государство для атаки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.answer()
        
    elif action == "feedback":
        await safe_edit(callback.message, "✉️ <b>Обратная связь с Администрацией</b>\n\nОтправьте ваше сообщение текстом ИЛИ фотографию с подписью. Мы постараемся ответить как можно скорее!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]]))
        await state.set_state(FeedbackState.waiting_message)
        await callback.answer()
        
    elif action == "shop":
        await safe_edit(callback.message, 
            "💎 <b>Донат Магазин за Telegram Stars (⭐️)</b>\n\n"
            "Здесь вы можете приобрести секретное вооружение или моментально пополнить дефицитные государственные запасы ресурсов по выгодному курсу!\n\n"
            "<b>Ваш государственный баланс ресурсов:</b>\n"
            f"💵 Бюджет: {country.get('budget', 0):,}$ | 🧱 Матер.: {country.get('materials', 0):,}\n"
            f"⚙️ Сталь: {country.get('steel', 0):,} | 💻 Электр.: {country.get('electronics', 0):,}\n"
            f"🛢 Нефть: {country.get('oil', 0):,} | 🥩 Еда: {country.get('food', 0):,}\n",
            reply_markup=shop_main_kb()
        )
        await callback.answer()

# ========================================================================
# ПОЛИТИЧЕСКИЙ СЕКТОР, ЗАКОНОТВОРЧЕСТВО И ВЕРОИСПОВЕДАНИЯ
# ========================================================================
@dp.callback_query(F.data.startswith("policy_"))
async def process_policy(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: 
        return await callback.answer("Ошибка: Страна не найдена.", show_alert=True)
    
    if action == "gov":
        text = "🏛 <b>Выбор формы правления</b>\nСмена государственного строя обойдется казне в <b>10,000$</b>.\n\n"
        for g_id, g_data in GOV_TYPES.items():
            text += f"🏛 <b>{g_data['name']}</b>: {g_data['desc']}\n"
        await safe_edit(callback.message, text, reply_markup=policy_gov_kb(country.get('gov_type')))
        
    elif action == "rel":
        text = "🕊 <b>Выбор вероисповедания</b>\nРеформации стоят <b>5,000$</b> (с Атеизма переход бесплатный).\n\n"
        for r_id, r_data in RELIGIONS.items():
            text += f"🕊 <b>{r_data['name']}</b>: {r_data['desc']}\n"
        await safe_edit(callback.message, text, reply_markup=policy_rel_kb(country.get('religion')))
        
    elif action == "laws":
        text = "📜 <b>Принятие конституционных законов</b>\nУтверждение или отзыв бесплатны. Баффы и дебаффы рассчитываются каждый тик:\n\n"
        for l_id, l_data in LAWS.items():
            text += f"📜 <b>{l_data['name']}</b>: {l_data['desc']}\n"
        await safe_edit(callback.message, text, reply_markup=policy_laws_kb(country.get('active_laws')))
        
    elif action == "custom":
        await safe_edit(callback.message, "🎨 <b>Центр брендинга и кастомизации</b>\nЗдесь вы можете изменить государственную символику:", reply_markup=customization_kb())
        
    await callback.answer()

@dp.callback_query(F.data.startswith("setgov_"))
async def process_setgov(callback: types.CallbackQuery):
    g_id = callback.data.split("_", 1)[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if country.get('gov_type') == g_id: 
        return await callback.answer("Ваша страна уже использует этот политический строй!", show_alert=True)
    cost = 0 if country.get('gov_type') == "Не выбрано" else 10000
    if country.get('budget', 0) < cost: 
        return await callback.answer(f"❌ Казне нужно {cost}$.", show_alert=True)
        
    await execute_db("UPDATE countries SET budget = budget - ?, gov_type = ? WHERE id = ?", (cost, g_id, country['id']))
    await callback.answer(f"✅ Внедрен новый государственный строй: {GOV_TYPES[g_id]['name']}!", show_alert=True)
    callback.data = "menu_laws"
    await process_menus(callback, None)

@dp.callback_query(F.data.startswith("setrel_"))
async def process_setrel(callback: types.CallbackQuery):
    r_id = callback.data.split("_", 1)[1]
    rel_name = RELIGIONS[r_id]['name']
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if country.get('religion') == rel_name: 
        return await callback.answer("Ваше общество уже исповедует это учение!", show_alert=True)
    cost = 0 if country.get('religion') == "Атеизм" else 5000
    if country.get('budget', 0) < cost: 
        return await callback.answer(f"❌ Бюджету необходимо {cost}$.", show_alert=True)
        
    await execute_db("UPDATE countries SET budget = budget - ?, religion = ? WHERE id = ?", (cost, rel_name, country['id']))
    await callback.answer(f"✅ Духовным курсом общества выбрано {rel_name}!", show_alert=True)
    callback.data = "menu_laws"
    await process_menus(callback, None)

@dp.callback_query(F.data.startswith("togglelaw_"))
async def process_togglelaw(callback: types.CallbackQuery):
    l_id = callback.data.split("_", 1)[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    active_laws_str = country.get('active_laws') or ''
    active = [l for l in active_laws_str.split(",") if l]
    if l_id in active:
        active.remove(l_id)
        msg = f"🔴 Закон '{LAWS[l_id]['name']}' успешно упразднен!"
    else:
        active.append(l_id)
        msg = f"🟢 Закон '{LAWS[l_id]['name']}' успешно ратифицирован!"
        
    new_laws = ",".join(active)
    await execute_db("UPDATE countries SET active_laws = ? WHERE id = ?", (new_laws, country['id']))
    await callback.answer(msg)
    
    text = "📜 <b>Принятие конституционных законов</b>\nУтверждение или отзыв бесплатны. Баффы и дебаффы рассчитываются каждый тик:\n\n"
    for l, l_data in LAWS.items():
        text += f"📜 <b>{l_data['name']}</b>: {l_data['desc']}\n"
    await safe_edit(callback.message, text, reply_markup=policy_laws_kb(new_laws))

@dp.callback_query(F.data == "custom_name")
async def process_custom_name(callback: types.CallbackQuery, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if country.get('budget', 0) < 5000:
        return await callback.answer("❌ В бюджете недостаточно денег! Требуется 5,000$.", show_alert=True)
    await safe_edit(callback.message, "Укажите <b>новое название</b> вашего государства (с баланса будет списано 5,000$):")
    await state.set_state(CustomizeState.new_name)
    await callback.answer()

@dp.message(CustomizeState.new_name)
async def finish_custom_name(message: types.Message, state: FSMContext):
    new_name = message.text[:30]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if country.get('budget', 0) < 5000:
        await state.clear()
        return await message.answer("Недостаточно средств в бюджете.")
        
    await execute_db("UPDATE countries SET budget = budget - 5000, name = ? WHERE id = ?", (new_name, country['id']))
    await message.answer(f"✅ Название страны изменено на <b>{new_name}</b>!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data == "custom_flag")
async def process_custom_flag(callback: types.CallbackQuery, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if country.get('budget', 0) < 3000:
        return await callback.answer("❌ В бюджете недостаточно денег! Требуется 3,000$.", show_alert=True)
    await safe_edit(callback.message, "Отправьте <b>новый эмодзи</b> ИЛИ <b>картинку флага 16:9</b> (с баланса будет списано 3,000$):")
    await state.set_state(CustomizeState.new_flag)
    await callback.answer()

@dp.message(CustomizeState.new_flag, F.text | F.photo)
async def finish_custom_flag(message: types.Message, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if country.get('budget', 0) < 3000:
        await state.clear()
        return await message.answer("Недостаточно средств в бюджете.")

    if message.photo:
        photo = message.photo[-1]
        flag = f"photo:{photo.file_id}"
    elif message.text:
        flag = message.text[:2] 
    else:
        return await message.answer("❌ Пришлите эмодзи флага или фотографию герба!")

    await execute_db("UPDATE countries SET budget = budget - 3000, flag = ? WHERE id = ?", (flag, country['id']))
    await message.answer("✅ Государственная символика успешно обновлена!", reply_markup=main_menu_kb())
    await state.clear()

# ========================================================================
# ДИПЛОМАТИЯ: СОЗДАНИЕ И УПРАВЛЕНИЕ АЛЬЯНСАМИ
# ========================================================================
@dp.callback_query(F.data.startswith("aly_join_"))
async def cmd_aly_join_req(callback: types.CallbackQuery):
    aly_id = int(callback.data.split("_")[2])
    exists = await fetch_one("SELECT id FROM alliance_requests WHERE user_id = ? AND alliance_id = ?", (callback.from_user.id, aly_id))
    if exists:
        return await callback.answer("Заявка на вступление уже находится на рассмотрении у лидера!", show_alert=True)
        
    await execute_db("INSERT INTO alliance_requests (alliance_id, user_id) VALUES (?, ?)", (aly_id, callback.from_user.id))
    await callback.answer("✅ Дипломатический запрос отправлен лидеру альянса!", show_alert=True)

@dp.callback_query(F.data == "aly_reqs")
async def cmd_aly_reqs(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    reqs = await fetch_all("SELECT * FROM alliance_requests WHERE alliance_id = ?", (country['alliance_id'],))
    
    if not reqs:
        return await callback.answer("На данный момент входящих заявок нет.", show_alert=True)
        
    kb = []
    for r in reqs:
        user_c = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (r['user_id'],))
        if user_c:
            kb.append([InlineKeyboardButton(text=f"✅ Одобрить {df(user_c.get('flag'))} {user_c.get('name')}", callback_data=f"aly_acc_{r['id']}_{user_c['owner_id']}")])
            kb.append([InlineKeyboardButton(text=f"❌ Отклонить {df(user_c.get('flag'))} {user_c.get('name')}", callback_data=f"aly_rej_{r['id']}")])
            
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_alliance")])
    await safe_edit(callback.message, "📥 <b>Входящие дипломатические прошения:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("aly_acc_"))
async def aly_accept(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[3])
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    await execute_db("UPDATE countries SET alliance_id = ? WHERE owner_id = ?", (country['alliance_id'], user_id))
    await execute_db("DELETE FROM alliance_requests WHERE user_id = ?", (user_id,))
    await callback.answer("Государство принято в союз!", show_alert=True)
    await cmd_aly_reqs(callback)

@dp.callback_query(F.data.startswith("aly_rej_"))
async def aly_reject(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[2])
    await execute_db("DELETE FROM alliance_requests WHERE id = ?", (req_id,))
    await callback.answer("Заявка отклонена.", show_alert=True)
    await cmd_aly_reqs(callback)

@dp.callback_query(F.data == "aly_create")
async def cmd_aly_create(callback: types.CallbackQuery, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if country.get('budget', 0) < 10000:
        return await callback.answer("Бюджету не хватает 10,000$ для создания союза!", show_alert=True)
    await safe_edit(callback.message, "Введите <b>Название</b> дипломатического Альянса (до 30 символов):")
    await state.set_state(CreateAlliance.name)
    await callback.answer()

@dp.message(CreateAlliance.name)
async def aly_name_step(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text[:30])
    await message.answer("Укажите <b>Эмодзи</b> в качестве символа союза:")
    await state.set_state(CreateAlliance.flag)

@dp.message(CreateAlliance.flag)
async def aly_flag_step(message: types.Message, state: FSMContext):
    flag = message.text[:2]
    data = await state.get_data()
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    
    await execute_db("UPDATE countries SET budget = budget - 10000 WHERE id = ?", (country['id'],))
    await execute_db("INSERT INTO alliances (name, flag, leader_id) VALUES (?, ?, ?)", (data['name'], flag, country['owner_id']))
    
    new_aly = await fetch_one("SELECT id FROM alliances WHERE leader_id = ?", (country['owner_id'],))
    await execute_db("UPDATE countries SET alliance_id = ? WHERE id = ?", (new_aly['id'], country['id']))
    
    await message.answer(f"✅ Альянс <b>{flag} {data['name']}</b> успешно зарегистрирован на международной арене!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data == "aly_leave")
async def cmd_aly_leave(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE id = ?", (country['id'],))
    await callback.answer("Вы вышли из дипломатического блока.", show_alert=True)
    await safe_edit(callback.message, "Вы покинули дипломатический блок.", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "aly_disband")
async def cmd_aly_disband(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    aly_id = country.get('alliance_id', 0)
    
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly_id,))
    await execute_db("DELETE FROM alliances WHERE id = ?", (aly_id,))
    await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (aly_id,))
    
    await callback.answer("Дипломатический блок полностью распущен!", show_alert=True)
    await safe_edit(callback.message, "Ваш Альянс прекратил свое существование.", reply_markup=main_menu_kb())

# ========================================================================
# СЛУЖБА ПОДДЕРЖКИ И ОБРАТНАЯ СВЯЗЬ С ПОЛЬЗОВАТЕЛЯМИ
# ========================================================================
@dp.message(FeedbackState.waiting_message, F.text | F.photo)
async def process_feedback_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or f"ID:{user_id}"
    photo_id = message.photo[-1].file_id if message.photo else None
    text_content = message.caption or message.text or ""
        
    await execute_db(
        "INSERT INTO feedbacks (user_id, username, text_content, photo_id) VALUES (?, ?, ?, ?)",
        (user_id, username, text_content, photo_id)
    )
    await message.answer("✅ <b>Ваше обращение зафиксировано и отправлено дежурным администраторам!</b>", reply_markup=main_menu_kb())
    await state.clear()
    
    try:
        await bot.send_message(SUPER_ADMIN_ID, "✉️ <b>Входящее сообщение в техподдержку!</b> Откройте /admin для ответа.")
    except:
        pass

# ========================================================================
# ПЛАТЕЖНАЯ СИСТЕМА (TELEGRAM STARS)
# ========================================================================
@dp.callback_query(F.data == "shop_buy_f16")
async def shop_buy_f16(callback: types.CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title="✈️ Истребитель F-16 Falcon",
            description="Воздушное доминирование. +5000 к скрытой военной мощи (не отображается в профиле, учитывается в битвах)!",
            payload="buy_f16",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="F-16 Falcon", amount=50)]
        )
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка формирования счета.", show_alert=True)

@dp.callback_query(F.data == "shop_buy_oreshnik")
async def shop_buy_oreshnik(callback: types.CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title="🚀 Комплекс «Орешник»",
            description="Гиперзвуковая баллистическая атака. +12000 к скрытой военной мощи!",
            payload="buy_oreshnik",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Ракета Орешник", amount=200)]
        )
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка формирования счета.", show_alert=True)

@dp.callback_query(F.data.startswith("shop_res_"))
async def shop_res_select(callback: types.CallbackQuery, state: FSMContext):
    res_type = callback.data.split("_")[2]
    await state.update_data(donate_res_type=res_type)
    
    rates = {
        "budget": "1500 💰 Бюджета",
        "materials": "150 🧱 Материалов",
        "steel": "100 ⚙️ Стали",
        "electronics": "80 💻 Электроники",
        "oil": "250 🛢 Нефти",
        "food": "500 🥩 Еды"
    }
    
    await safe_edit(callback.message, 
        f"🛒 <b>Покупка стратегического запаса за Stars (⭐️)</b>\n\n"
        f"Тарифный курс: <b>1 ⭐️ = {rates[res_type]}</b>.\n\n"
        f"Укажите в ответном сообщении количество Звезд (⭐️), которые вы хотите инвестировать в экономику (целое число):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в магазин", callback_data="menu_shop")]])
    )
    await state.set_state(ShopState.waiting_for_stars)
    await callback.answer()

@dp.message(ShopState.waiting_for_stars)
async def shop_process_stars_input(message: types.Message, state: FSMContext):
    try:
        stars = int(message.text)
        if stars <= 0:
            return await message.answer("Сумма должна быть положительной!")
    except ValueError:
        return await message.answer("Пожалуйста, введите корректное число звезд:")
        
    data = await state.get_data()
    res_type = data.get("donate_res_type")
    
    rates = {"budget": 1500, "materials": 150, "steel": 100, "electronics": 80, "oil": 250, "food": 500}
    total_res = stars * rates[res_type]
    res_name = RES_MAP.get(res_type, res_type)
    
    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=f"Поставка: {res_name}",
            description=f"Целевой транш: зачисление {total_res:,} ед. {res_name} в гос. резервы страны.",
            payload=f"buy_res:{res_type}:{stars}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"Оплата за {res_name}", amount=stars)]
        )
        await state.clear()
    except Exception as e:
        await message.answer("❌ Ошибка отправки платежного инвойса.", reply_markup=main_menu_kb())
        await state.clear()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    user_id = message.from_user.id
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (user_id,))
    if not country:
        return await message.answer("❌ Ошибка: Страна не найдена, но Stars были списаны. Срочно напишите нам в поддержку (/feedback).")
        
    if payload == "buy_f16":
        await execute_db("UPDATE countries SET f16 = f16 + 1 WHERE id = ?", (country['id'],))
        await message.answer("✈️ <b>ВВС пополнились истребителем F-16 Falcon!</b>\nСкрытая мощь атаки увеличена на +5000.", reply_markup=main_menu_kb())
    elif payload == "buy_oreshnik":
        await execute_db("UPDATE countries SET oreshnik = oreshnik + 1 WHERE id = ?", (country['id'],))
        await message.answer("🚀 <b>Баллистическая ракета «Орешник» развернута в шахтах!</b>\nСкрытая военная мощь увеличена на +12000.", reply_markup=main_menu_kb())
    elif payload.startswith("buy_res:"):
        _, res_type, stars_str = payload.split(":")
        stars = int(stars_str)
        rates = {"budget": 1500, "materials": 150, "steel": 100, "electronics": 80, "oil": 250, "food": 500}
        amount = stars * rates[res_type]
        res_name = RES_MAP.get(res_type, res_type)
        
        await execute_db(f"UPDATE countries SET {res_type} = {res_type} + ? WHERE id = ?", (amount, country['id']))
        await message.answer(f"✅ <b>Баланс пополнен!</b> На склады зачислено: +{amount:,} {res_name}.", reply_markup=main_menu_kb())

# ========================================================================
# УДАЛЕНИЕ СТРАНЫ С СЕРВЕРА
# ========================================================================
@dp.callback_query(F.data == "delete_self_warn")
async def process_delete_warn(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ ДА, СТЕРЕТЬ ГОСУДАРСТВО", callback_data="delete_self_confirm")],
        [InlineKeyboardButton(text="◀️ ОТМЕНА", callback_data="menu_profile")]
    ])
    await safe_edit(callback.message, "🧨 <b>ВНИМАНИЕ! КАТАСТРОФА!</b>\nУдаление сотрет весь ваш прогресс, постройки, армию и ресурсы навсегда.", reply_markup=kb)
    await state.set_state(DeleteCountryState.confirm)
    await callback.answer()

@dp.callback_query(F.data == "delete_self_confirm")
async def process_delete_confirm(callback: types.CallbackQuery, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if country:
        aly = await fetch_one("SELECT * FROM alliances WHERE leader_id = ?", (callback.from_user.id,))
        if aly:
            await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly['id'],))
            await execute_db("DELETE FROM alliances WHERE id = ?", (aly['id'],))
            await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (aly['id'],))
        await execute_db("DELETE FROM countries WHERE id = ?", (country['id'],))
        
    await state.clear()
    await safe_edit(callback.message, "💥 <b>Страна полностью стёрта из мировой истории.</b>\nВы можете основать новую цивилизацию, написав /start.")
    await callback.answer("Страна удалена.", show_alert=True)

# ========================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА И СЕРВЕРНЫЙ КОНТРОЛЬ
# ========================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): 
        return await message.answer("Ошибка 403: Доступ запрещен.")
    await state.clear()
    await message.answer("🔧 <b>Панель Управления Сервером</b>\nВыберите задачу:", reply_markup=admin_main_kb())

@dp.message(Command("announce"))
async def cmd_announce(message: types.Message):
    if not await is_admin(message.from_user.id): 
        return
    text = message.text.replace("/announce", "").strip()
    if not text:
        return await message.answer("Укажите текст: <code>/announce Внимание!</code>")
        
    users = await fetch_all("SELECT DISTINCT owner_id FROM countries WHERE owner_id IS NOT NULL")
    count = 0
    await message.answer(f"⏳ Начинаю рассылку...")
    for u in users:
        try:
            await bot.send_message(u['owner_id'], f"📢 <b>Срочные новости от Администрации:</b>\n\n{text}")
            count += 1
            await asyncio.sleep(0.05)
        except: 
            pass
    await message.answer(f"✅ Рассылка завершена. Доставлено {count} игрокам.")

@dp.callback_query(F.data.startswith("adm_"))
async def adm_menus(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): 
        return
    await state.clear()
    act = callback.data.split("_")[1]
    
    if act == "main": 
        await safe_edit(callback.message, "🔧 <b>Панель Управления Сервером</b>\nВыберите задачу:", reply_markup=admin_main_kb())
    elif act == "countries": 
        await safe_edit(callback.message, "🌍 <b>Управление державами на карте:</b>", reply_markup=admin_countries_kb())
    elif act == "backups":
        await safe_edit(callback.message, "📦 <b>Бэкапы базы данных сервера:</b>", reply_markup=admin_backups_kb())
    elif act == "alliances":
        await safe_edit(callback.message, "🤝 <b>Роспуск дипломатических альянсов:</b>", reply_markup=admin_alliances_kb())
    elif act == "admins":
        await safe_edit(callback.message, "👮‍♂️ <b>Штат администраторов симулятора:</b>", reply_markup=admin_admins_kb())
    elif act == "resources":
        await safe_edit(callback.message, "Отправьте ID игрока, которому хотите отредактировать баланс ресурсов:")
        await state.set_state(AdminState.give_target)
    elif act == "troops":
        await safe_edit(callback.message, "Отправьте ID игрока, которому хотите изменить количество войск:")
        await state.set_state(AdminTroopState.give_target)
    elif act == "feedbacks":
        await process_admin_feedbacks(callback)
    elif act == "event":
        events = ["Урожай (Все нации: Еда +2000)", "Кризис экономики (Все нации: Бюджет -20%)", "Гуманитарный конвой (Все нации: Мат +1000)"]
        ev = random.choice(events)
        if "Урожай" in ev: 
            await execute_db("UPDATE countries SET food = food + 2000 WHERE owner_id IS NOT NULL")
        elif "Кризис" in ev: 
            await execute_db("UPDATE countries SET budget = CAST(budget * 0.8 AS INT) WHERE owner_id IS NOT NULL")
        elif "Гуманитарный" in ev: 
            await execute_db("UPDATE countries SET materials = materials + 1000 WHERE owner_id IS NOT NULL")
        await callback.answer(f"✅ Запущен ивент: {ev}!", show_alert=True)
    await callback.answer()

async def process_admin_feedbacks(callback: types.CallbackQuery):
    fb = await fetch_one("SELECT * FROM feedbacks WHERE is_answered = 0 ORDER BY id ASC LIMIT 1")
    if not fb:
        await safe_edit(callback.message, "✅ Все тикеты в техподдержку успешно обработаны!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]]]))
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Написать ответ", callback_data=f"fb_reply_{fb['id']}")],
        [InlineKeyboardButton(text="⏭ Пропустить тикет", callback_data=f"fb_skip_{fb['id']}")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="adm_main")]
    ])
    text = f"📨 <b>Обращение #{fb['id']}</b>\nОт: <code>{fb['username']}</code> (ID: {fb['user_id']})\n\n<b>Текст:</b> {fb['text_content']}"
    
    if fb['photo_id']:
        await safe_edit(callback.message, text, reply_markup=kb, photo_id=fb['photo_id'])
    else:
        await safe_edit(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data.startswith("fb_skip_"))
async def adm_fb_skip(callback: types.CallbackQuery):
    fb_id = int(callback.data.split("_")[2])
    await execute_db("UPDATE feedbacks SET is_answered = 1 WHERE id = ?", (fb_id,))
    await process_admin_feedbacks(callback)

@dp.callback_query(F.data.startswith("fb_reply_"))
async def adm_fb_reply(callback: types.CallbackQuery, state: FSMContext):
    fb_id = int(callback.data.split("_")[2])
    fb = await fetch_one("SELECT * FROM feedbacks WHERE id = ?", (fb_id,))
    
    await state.update_data(reply_to_user_id=fb['user_id'], fb_id=fb_id)
    await safe_edit(callback.message, "Введите текст ответа (или пришлите фото с описанием):")
    await state.set_state(AdminFeedbackState.replying_to)
    await callback.answer()

@dp.message(AdminFeedbackState.replying_to, F.text | F.photo)
async def adm_send_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['reply_to_user_id']
    fb_id = data['fb_id']
    
    try:
        if message.photo:
            await bot.send_photo(user_id, photo=message.photo[-1].file_id, caption=f"👨‍💻 <b>Официальный ответ поддержки:</b>\n\n{message.caption or ''}")
        else:
            await bot.send_message(user_id, f"👨‍💻 <b>Официальный ответ поддержки:</b>\n\n{message.text}")
        await execute_db("UPDATE feedbacks SET is_answered = 1 WHERE id = ?", (fb_id,))
        await message.answer("✅ Ответ отправлен!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text="Далее ⏭", callback_data="adm_feedbacks")]]]))
    except:
        await message.answer("❌ Игрок заблокировал бота, отправить ответ не удалось.", reply_markup=admin_main_kb())
        await execute_db("UPDATE feedbacks SET is_answered = 1 WHERE id = ?", (fb_id,))
    await state.clear()

@dp.message(AdminState.give_target)
async def adm_res_target(message: types.Message, state: FSMContext):
    target = message.text
    if target.startswith("@"): 
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target[1:],))
    else: 
        try:
            target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target),))
        except ValueError:
            return await message.answer("Неверный ID.")
            
    if not target_country: 
        return await message.answer("Страна не найдена.")
        
    await state.update_data(res_target_id=target_country['id'])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Бюджет", callback_data="res_budget"), InlineKeyboardButton(text="🧱 Мат.", callback_data="res_materials")],
        [InlineKeyboardButton(text="⚙️ Сталь", callback_data="res_steel"), InlineKeyboardButton(text="💻 Электр.", callback_data="res_electronics")],
        [InlineKeyboardButton(text="🛢 Нефть", callback_data="res_oil"), InlineKeyboardButton(text="🥩 Еда", callback_data="res_food")],
    ])
    await message.answer(f"Выбрана страна: {target_country['name']}.\nВыберите ресурс для корректировки:", reply_markup=kb)
    await state.set_state(AdminState.give_type)

@dp.callback_query(AdminState.give_type, F.data.startswith("res_"))
async def adm_res_type(callback: types.CallbackQuery, state: FSMContext):
    res_type = callback.data.split("_")[1]
    await state.update_data(res_type=res_type)
    await safe_edit(callback.message, "Введите количество (положительное, чтобы начислить, отрицательное, чтобы забрать):")
    await state.set_state(AdminState.give_amount)

@dp.message(AdminState.give_amount)
async def adm_res_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        await execute_db(f"UPDATE countries SET {data['res_type']} = max(0, {data['res_type']} + ?) WHERE id = ?", (amount, data['res_target_id']))
        await message.answer("✅ Баланс успешно изменен!", reply_markup=admin_main_kb())
        await state.clear()
    except ValueError:
        await message.answer("Некорректное число.")

@dp.message(AdminTroopState.give_target)
async def adm_troop_target(message: types.Message, state: FSMContext):
    target = message.text
    if target.startswith("@"): 
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target[1:],))
    else: 
        try:
            target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target),))
        except ValueError:
            return await message.answer("Неверный формат.")
            
    if not target_country: 
        return await message.answer("Игрок не найден.")
        
    await state.update_data(res_target_id=target_country['id'])
    await message.answer(f"Выбрана страна: {target_country['name']}. Какой вид войск выдать?", reply_markup=admin_troop_type_kb())
    await state.set_state(AdminTroopState.give_type)

@dp.callback_query(AdminTroopState.give_type, F.data.startswith("atr_"))
async def adm_troop_type(callback: types.CallbackQuery, state: FSMContext):
    t_type = callback.data.split("_", 1)[1]
    await state.update_data(troop_type=t_type)
    await safe_edit(callback.message, f"Редактируем {t_type}.\nУкажите число изменений:")
    await state.set_state(AdminTroopState.give_amount)

@dp.message(AdminTroopState.give_amount)
async def adm_troop_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        await execute_db(f"UPDATE countries SET {data['troop_type']} = max(0, {data['troop_type']} + ?) WHERE id = ?", (amount, data['res_target_id']))
        await message.answer("✅ Военный арсенал скорректирован!", reply_markup=admin_main_kb())
        await state.clear()
    except ValueError:
        await message.answer("Введите целое число.")

@dp.callback_query(F.data == "admin_download_db")
async def admin_download_db(callback: types.CallbackQuery):
    filename = f"backup_{datetime.now().strftime('%Y-%m-%d')}.db"
    file = FSInputFile(DB_NAME, filename=filename)
    await bot.send_document(chat_id=callback.message.chat.id, document=file, caption="📦 Свежий бэкап геополитического мира.")
    await callback.answer()

@dp.callback_query(F.data == "admin_upload_db")
async def admin_upload_db(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "⚠️ <b>ОПАСНОСТЬ: ОТКАТ БАЗЫ ДАННЫХ!</b>\nОтправьте файл <code>database.db</code>:")
    await state.set_state(AdminState.waiting_for_db)
    await callback.answer()

@dp.message(AdminState.waiting_for_db, F.document)
async def admin_upload_db_finish(message: types.Message, state: FSMContext):
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, DB_NAME)
    await message.answer("✅ Мир успешно восстановлен из резервной копии!", reply_markup=admin_main_kb())
    await state.clear()

@dp.callback_query(F.data == "admin_create_free")
async def admin_create_free(callback: types.CallbackQuery):
    name = f"Свободные земли {random.randint(100, 999)}"
    await execute_db(
        """INSERT INTO countries (name, flag, budget, is_unclaimed) VALUES (?, '🏳️', 10000, 1)""", (name,)
    )
    await callback.answer(f"✅ Страна '{name}' создана как свободный слот для новичков!", show_alert=True)

@dp.callback_query(F.data == "admin_create_npc")
async def admin_npc_start(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Укажите имя NPC страны:")
    await state.set_state(AdminState.npc_name)

@dp.message(AdminState.npc_name)
async def admin_npc_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Пришлите эмодзи флага для NPC:")
    await state.set_state(AdminState.npc_flag)

@dp.message(AdminState.npc_flag)
async def admin_npc_flag(message: types.Message, state: FSMContext):
    flag = message.text[:2]
    data = await state.get_data()
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, infantry, tanks, destroyers, materials, oil, food, is_unclaimed) 
           VALUES (?, ?, 50000, 500, 50, 1000, 50, 5, 20000, 10000, 20000, 0)""",
        (data['name'], flag)
    )
    await message.answer(f"✅ NPC-страна {flag} {data['name']} успешно создана на геокарте!")
    await state.clear()

@dp.callback_query(F.data == "admin_list_countries")
async def admin_list_countries(callback: types.CallbackQuery):
    countries = await fetch_all("SELECT id, flag, name, owner_id FROM countries")
    text = "📋 <b>Державы мира:</b>\n\n"
    for c in countries:
        status = f"Игрок: <code>{c['owner_id']}</code>" if c['owner_id'] else "Свободная земля / NPC"
        text += f"ID: <code>{c['id']}</code> | {df(c['flag'])} {c['name']} ({status})\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_countries")]]]))

@dp.callback_query(F.data == "admin_del_country")
async def admin_del_country(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Укажите ID страны для удаления:")
    await state.set_state(AdminState.del_country)

@dp.message(AdminState.del_country)
async def admin_del_country_finish(message: types.Message, state: FSMContext):
    try:
        c_id = int(message.text)
        await execute_db("DELETE FROM countries WHERE id = ?", (c_id,))
        await message.answer("✅ Страна удалена!", reply_markup=admin_main_kb())
    except:
        await message.answer("ID должен быть числом.")
    await state.clear()

@dp.callback_query(F.data == "admin_list_alliances")
async def admin_list_alliances(callback: types.CallbackQuery):
    alliances = await fetch_all("SELECT id, flag, name FROM alliances")
    text = "📋 <b>Союзы на планете:</b>\n\n"
    for a in alliances:
        text += f"ID: <code>{a['id']}</code> | {df(a['flag'])} {a['name']}\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_alliances")]]]))

@dp.callback_query(F.data == "admin_del_alliance")
async def admin_del_alliance(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Укажите ID альянса для ликвидации:")
    await state.set_state(AdminState.del_alliance)

@dp.message(AdminState.del_alliance)
async def admin_del_alliance_finish(message: types.Message, state: FSMContext):
    try:
        a_id = int(message.text)
        await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (a_id,))
        await execute_db("DELETE FROM alliances WHERE id = ?", (a_id,))
        await message.answer("✅ Альянс принудительно аннулирован!", reply_markup=admin_main_kb())
    except:
        await message.answer("Неверный ID.")
    await state.clear()

@dp.callback_query(F.data == "admin_add_admin")
async def admin_add_admin(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Введите Telegram ID нового администратора:")
    await state.set_state(AdminState.add_admin)

@dp.message(AdminState.add_admin)
async def admin_add_admin_finish(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await execute_db("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await message.answer("✅ Администратор добавлен в систему!", reply_markup=admin_main_kb())
    except:
        await message.answer("Неверный ID.")
    await state.clear()

@dp.callback_query(F.data == "admin_rem_admin")
async def admin_rem_admin(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Введите Telegram ID для отзыва админ-прав:")
    await state.set_state(AdminState.rem_admin)

@dp.message(AdminState.rem_admin)
async def admin_rem_admin_finish(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        if user_id == SUPER_ADMIN_ID:
            return await message.answer("Нельзя снять главного администратора.")
        await execute_db("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await message.answer("✅ Администратор разжалован!", reply_markup=admin_main_kb())
    except:
        await message.answer("Неверный ID.")
    await state.clear()

@dp.callback_query(F.data == "admin_list_admins")
async def admin_list_admins(callback: types.CallbackQuery):
    admins = await fetch_all("SELECT user_id FROM admins")
    text = "👮‍♂️ <b>Текущий штат администрации:</b>\n\n"
    for a in admins:
        text += f"• <code>{a['user_id']}</code>\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_admins")]]]))

# ========================================================================
# ТОЧКА ВХОДА И ЗАПУСК СЕРВЕРА БОТА
# ========================================================================
async def main():
    await init_db()
    asyncio.create_task(economy_tick())
    
    commands = [
        BotCommand(command="start", description="Командный штаб"),
        BotCommand(command="trade", description="Торговля с нацией (/trade ID)"),
        BotCommand(command="admin", description="Панель администратора")
    ]
    await bot.set_my_commands(commands)
    
    logging.info("Игровая экономика и база данных успешно синхронизированы. Бот готов к приему игроков!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
