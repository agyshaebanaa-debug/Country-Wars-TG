import asyncio
import logging
import os
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, FSInputFile, InputMediaPhoto
)
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА И ПЕРЕМЕННЫЕ
# ========================================================================
# Рекомендуется использовать переменные окружения: os.getenv("BOT_TOKEN", "ваш_токен")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8596473788:AAGrGjeH2Dq_PHJQdmnUcE8OV-xt6t1cEIs")
SUPER_ADMIN_ID = 5341904332 
DB_NAME = "database.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# Кэш в памяти для предотвращения спама (в продакшене лучше использовать Redis)
user_last_action: Dict[int, float] = {}
user_attack_cooldown: Dict[int, float] = {}

BUTTON_COOLDOWN = 1.0  
ATTACK_COOLDOWN = 300.0  

# ========================================================================
# ОПРЕДЕЛЕНИЕ ЗАКОНОВ, РЕЛИГИЙ И СТРОЕВ (БАФФЫ/ДЕБАФФЫ)
# ========================================================================
LAWS_INFO = {
    1: {
        "name": "🚨 Военное положение",
        "desc": "Увеличивает боевую мощь армии на 25%, но снижает пассивный доход бюджета на 15% и рост граждан на 10%.",
        "cost_act": 2000, "cost_rep": 1000
    },
    2: {
        "name": "📈 Свободный рынок",
        "desc": "Приносит +25% к пассивному доходу бюджета, но увеличивает потребление нефти техникой на 15%.",
        "cost_act": 3000, "cost_rep": 1500
    },
    3: {
        "name": "🌾 Продналог",
        "desc": "Увеличивает производство еды на 30%, но снижает приток граждан на 10% и доход бюджета на 5%.",
        "cost_act": 1500, "cost_rep": 500
    },
    4: {
        "name": "🏭 Индустриализация",
        "desc": "Повышает производство материалов заводами на 25%, но увеличивает потребление нефти на 10%.",
        "cost_act": 4000, "cost_rep": 2000
    },
    5: {
        "name": "🪖 Всеобщая мобилизация",
        "desc": "Снижает стоимость закупки пехоты в военкомате на 50%, но снижает производство материалов на 15% (рабочие ушли на фронт).",
        "cost_act": 2500, "cost_rep": 1000
    },
    6: {
        "name": "🌱 Экологический контроль",
        "desc": "Приток граждан растет на 15%, производство еды на 10%, но снижает добычу нефти и материалов на 15%.",
        "cost_act": 3000, "cost_rep": 1500
    }
}

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ
# ========================================================================
def is_spam(user_id: int) -> bool:
    """Проверка на слишком частые нажатия кнопок."""
    now = time.time()
    if now - user_last_action.get(user_id, 0) < BUTTON_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def get_attack_cooldown(user_id: int) -> int:
    """Получение оставшегося времени до следующей атаки."""
    now = time.time()
    passed = now - user_attack_cooldown.get(user_id, 0)
    if passed < ATTACK_COOLDOWN:
        return int(ATTACK_COOLDOWN - passed)
    return 0

def set_attack_cooldown(user_id: int) -> None:
    """Установка времени последней атаки."""
    user_attack_cooldown[user_id] = time.time()

async def safe_edit(message: Message, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, photo_id: Optional[str] = None) -> None:
    """Безопасное редактирование сообщения с обработкой исключений Telegram."""
    try:
        if photo_id:
            if message.photo:
                await message.edit_media(InputMediaPhoto(media=photo_id, caption=text, parse_mode="HTML"), reply_markup=reply_markup)
            else:
                await message.delete()
                await message.answer_photo(photo=photo_id, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            if message.photo:
                await message.delete()
                await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            else:
                await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        pass # Игнорируем ошибки, если сообщение не изменилось

def df(flag: str) -> str:
    """Форматирование флага. Возвращает эмодзи-заглушку, если флаг является фото."""
    return "🖼" if flag.startswith("photo:") else flag

# ========================================================================
# БАЗА ДАННЫХ
# ========================================================================
async def init_db() -> None:
    """Инициализация таблиц базы данных и выполнение миграций."""
    async with aiosqlite.connect(DB_NAME, timeout=10.0) as db:
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
                cars INTEGER DEFAULT 5,
                trucks INTEGER DEFAULT 2,
                tanks INTEGER DEFAULT 0,
                ships INTEGER DEFAULT 0,
                destroyers INTEGER DEFAULT 0,
                cruisers INTEGER DEFAULT 0,
                battleships INTEGER DEFAULT 0,
                materials INTEGER DEFAULT 1000,
                oil INTEGER DEFAULT 500,
                food INTEGER DEFAULT 2000,
                factories INTEGER DEFAULT 1,
                oil_rigs INTEGER DEFAULT 1,
                farms INTEGER DEFAULT 2,
                bridges INTEGER DEFAULT 0,
                rivers INTEGER DEFAULT 0,
                seas INTEGER DEFAULT 0,
                laws TEXT DEFAULT 'Нет законов',
                bunkers INTEGER DEFAULT 0,
                spies INTEGER DEFAULT 0,
                war_wins INTEGER DEFAULT 0,
                alliance_id INTEGER DEFAULT 0,
                government TEXT DEFAULT 'Анархия',
                religion TEXT DEFAULT 'Нет',
                enacted_laws TEXT DEFAULT ''
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alliances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                flag TEXT,
                leader_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS alliance_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alliance_id INTEGER,
                user_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        
        # Безопасные миграции колонок для старых версий БД
        new_columns = [
            ("bunkers", "INTEGER DEFAULT 0"), ("spies", "INTEGER DEFAULT 0"),
            ("war_wins", "INTEGER DEFAULT 0"), ("alliance_id", "INTEGER DEFAULT 0"),
            ("ships", "INTEGER DEFAULT 0"), ("destroyers", "INTEGER DEFAULT 0"),
            ("cruisers", "INTEGER DEFAULT 0"), ("battleships", "INTEGER DEFAULT 0"),
            ("materials", "INTEGER DEFAULT 1000"), ("oil", "INTEGER DEFAULT 500"), 
            ("food", "INTEGER DEFAULT 2000"), ("factories", "INTEGER DEFAULT 1"), 
            ("oil_rigs", "INTEGER DEFAULT 1"), ("farms", "INTEGER DEFAULT 2"), 
            ("bridges", "INTEGER DEFAULT 0"), ("rivers", "INTEGER DEFAULT 0"), 
            ("seas", "INTEGER DEFAULT 0"), ("username", "TEXT DEFAULT ''"),
            ("is_unclaimed", "INTEGER DEFAULT 0"), ("citizens", "INTEGER DEFAULT 10000"),
            ("government", "TEXT DEFAULT 'Анархия'"), ("religion", "TEXT DEFAULT 'Нет'"),
            ("enacted_laws", "TEXT DEFAULT ''")
        ]
        for col, col_type in new_columns:
            try:
                await db.execute(f"ALTER TABLE countries ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError:
                pass # Колонка уже существует
        await db.commit()

async def get_db_connection() -> aiosqlite.Connection:
    """Создает соединение с БД с настройкой row_factory."""
    db = await aiosqlite.connect(DB_NAME, timeout=10.0)
    db.row_factory = aiosqlite.Row
    return db

async def fetch_one(query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
    """Выполнение SELECT запроса, возвращающего одну строку."""
    async with await get_db_connection() as db:
        async with db.execute(query, params) as cursor:
            return await cursor.fetchone()

async def fetch_all(query: str, params: tuple = ()) -> List[aiosqlite.Row]:
    """Выполнение SELECT запроса, возвращающего список строк."""
    async with await get_db_connection() as db:
        async with db.execute(query, params) as cursor:
            return await cursor.fetchall()

async def execute_db(query: str, params: tuple = ()) -> None:
    """Выполнение INSERT/UPDATE/DELETE запросов."""
    async with await get_db_connection() as db:
        await db.execute(query, params)
        await db.commit()

async def is_admin(user_id: int) -> bool:
    """Проверка наличия прав администратора."""
    if user_id == SUPER_ADMIN_ID:
        return True
    res = await fetch_one("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return bool(res)

async def update_username(user_id: int, username: Optional[str]) -> None:
    """Обновление username пользователя в базе."""
    if username:
        await execute_db("UPDATE countries SET username = ? WHERE owner_id = ?", (username, user_id))

# ========================================================================
# ИГРОВАЯ МЕХАНИКА И МАТЕМАТИКА
# ========================================================================
def calculate_multipliers(country: aiosqlite.Row) -> Dict[str, float]:
    """Вычисление итоговых множителей на основе строя, религии и законов."""
    mults = {
        "budget": 1.0, "materials": 1.0, "oil": 1.0, "food": 1.0,
        "citizens": 1.0, "army_power": 1.0, "oil_cons": 1.0, "food_cons": 1.0
    }
    
    # Влияние строя
    gov = country.get('government', 'Анархия')
    if gov == "Демократия":
        mults["budget"] += 0.15; mults["citizens"] += 0.05; mults["army_power"] -= 0.10
    elif gov == "Коммунизм":
        mults["materials"] += 0.25; mults["oil"] += 0.25; mults["budget"] -= 0.15
    elif gov == "Монархия":
        mults["budget"] += 0.10; mults["citizens"] -= 0.15
    elif gov == "Военная Хунта":
        mults["army_power"] += 0.20; mults["budget"] -= 0.20
    elif gov == "Теократия":
        mults["food"] += 0.30; mults["materials"] -= 0.15
        
    # Влияние религии
    rel = country.get('religion', 'Нет')
    if rel == "Христианство":
        mults["citizens"] += 0.10; mults["budget"] += 0.10; mults["army_power"] -= 0.05
    elif rel == "Ислам":
        mults["army_power"] += 0.05; mults["food"] += 0.10; mults["budget"] -= 0.10
    elif rel == "Буддизм":
        mults["food"] += 0.15; mults["army_power"] -= 0.20
    elif rel == "Атеизм":
        mults["materials"] += 0.15; mults["oil"] += 0.10; mults["citizens"] -= 0.10
        
    # Влияние законов
    raw_laws = country.get('enacted_laws', '')
    active_ids = [int(x) for x in raw_laws.split(',') if x.strip().isdigit()]
    
    if 1 in active_ids: mults["army_power"] += 0.25; mults["budget"] -= 0.15; mults["citizens"] -= 0.10
    if 2 in active_ids: mults["budget"] += 0.25; mults["oil_cons"] += 0.15
    if 3 in active_ids: mults["food"] += 0.30; mults["citizens"] -= 0.10; mults["budget"] -= 0.05
    if 4 in active_ids: mults["materials"] += 0.25; mults["oil_cons"] += 0.10
    if 5 in active_ids: mults["materials"] -= 0.15
    if 6 in active_ids: mults["citizens"] += 0.15; mults["food"] += 0.10; mults["oil"] -= 0.15; mults["materials"] -= 0.15
        
    return mults

def get_base_power(country: aiosqlite.Row) -> int:
    """Вычисление базовой боевой мощи страны на основе количества техники и пехоты."""
    power = (
        country.get('infantry', 0) * 1 +
        country.get('cars', 0) * 2 +
        country.get('trucks', 0) * 1 +
        country.get('tanks', 0) * 10 +
        country.get('destroyers', 0) * 50 +
        country.get('cruisers', 0) * 100 +
        country.get('battleships', 0) * 300 +
        country.get('bunkers', 0) * 20
    )
    return power

async def get_alliance_support(alliance_id: int, exclude_country_id: int) -> Tuple[int, int]:
    """Вычисление поддержки от альянса. Возвращает (доп. мощь, количество союзников)."""
    if not alliance_id or alliance_id == 0:
        return 0, 0
    
    members = await fetch_all("SELECT * FROM countries WHERE alliance_id = ? AND id != ?", (alliance_id, exclude_country_id))
    if not members:
        return 0, 0
        
    total_ally_power = sum(get_base_power(m) for m in members)
    # Альянс предоставляет 20% от своей общей мощи в виде поддержки
    support_power = int(total_ally_power * 0.20)
    return support_power, len(members)

# ========================================================================
# ФОНОВЫЕ ЗАДАЧИ (ЭКОНОМИКА - 3 МИНУТЫ)
# ========================================================================
async def economy_tick() -> None:
    """Фоновый цикл начисления ресурсов всем активным странам."""
    while True:
        await asyncio.sleep(180)
        async with await get_db_connection() as db:
            try:
                async with db.execute("SELECT * FROM countries WHERE owner_id IS NOT NULL AND is_unclaimed = 0") as cursor:
                    countries = await cursor.fetchall()
                
                for c in countries:
                    mults = calculate_multipliers(c)
                    
                    prod_money = int(((c['settlements'] * 500) + c['gdp']) * mults['budget'])
                    prod_materials = int((c['factories'] * 150) * mults['materials'])
                    prod_oil = int((c['oil_rigs'] * 100) * mults['oil'])
                    prod_food = int((c['farms'] * 300) * mults['food'])
                    
                    cons_food = int((int(c['infantry'] * 1.5) + (c['spies'] * 5) + int(c['citizens'] * 0.05)) * mults['food_cons'])
                    cons_oil = int((int(c['cars'] * 0.5 + c['trucks'] * 1 + c['tanks'] * 2 + 
                                   c['destroyers'] * 5 + c['cruisers'] * 10 + c['battleships'] * 20)) * mults['oil_cons'])
                    
                    new_budget = c['budget'] + prod_money
                    new_materials = c['materials'] + prod_materials
                    new_food = c['food'] + prod_food - cons_food
                    new_oil = c['oil'] + prod_oil - cons_oil
                    
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
                    
                    new_citizens = max(0, c['citizens'] + int(c['citizens'] * 0.01 * mults['citizens']) + (c['settlements'] * 50) - citizens_penalty)
                    final_infantry = max(0, c['infantry'] - infantry_penalty)
                    final_cars = max(0, c['cars'] - vehicle_penalty)
                    final_tanks = max(0, c['tanks'] - (vehicle_penalty // 2))
                    
                    await db.execute("""
                        UPDATE countries 
                        SET budget = ?, materials = ?, food = ?, oil = ?, citizens = ?,
                            infantry = ?, cars = ?, tanks = ?
                        WHERE id = ?
                    """, (new_budget, new_materials, new_food, new_oil, new_citizens,
                          final_infantry, final_cars, final_tanks, c['id']))
                    
                    # Небольшая пауза, чтобы не блокировать event loop при тысячах стран
                    await asyncio.sleep(0.001)
                    
                await db.commit()
                logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Экономика: Тик 3 минуты успешно завершен.")
            except Exception as e:
                logger.error(f"Ошибка в цикле экономики: {e}")

# ========================================================================
# МАШИНА СОСТОЯНИЙ (FSM)
# ========================================================================
class CreateCountry(StatesGroup):
    name = State()
    flag = State()

class CreateAlliance(StatesGroup):
    name = State()
    flag = State()

class CustomState(StatesGroup):
    change_name = State()
    change_flag = State()

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

# ========================================================================
# КЛАВИАТУРЫ ИГРОКА
# ========================================================================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Моя Страна", callback_data="menu_profile"),
         InlineKeyboardButton(text="⚔️ Война", callback_data="menu_war")],
        [InlineKeyboardButton(text="🏭 Экономика", callback_data="menu_economy"),
         InlineKeyboardButton(text="🪖 Военкомат", callback_data="menu_army")],
        [InlineKeyboardButton(text="🤝 Альянс", callback_data="menu_alliance"),
         InlineKeyboardButton(text="📜 Политика и Законы", callback_data="menu_politics_hub")]
    ])

def economy_build_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏭 Завод (5k$, 500 Мат.)", callback_data="build_factory"),
         InlineKeyboardButton(text="🛢 Вышка (8k$, 1k Мат.)", callback_data="build_rig")],
        [InlineKeyboardButton(text="🌾 Ферма (3k$, 200 Мат.)", callback_data="build_farm"),
         InlineKeyboardButton(text="🌉 Мост (2k$, 800 Мат.)", callback_data="build_bridge")],
        [InlineKeyboardButton(text="🏘 Основать Поселение (15k$, 2k Мат., 2k Еды)", callback_data="build_settlement")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def army_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 Наземные войска", callback_data="menu_army_ground")],
        [InlineKeyboardButton(text="⚓️ Военно-морской флот", callback_data="menu_army_naval")],
        [InlineKeyboardButton(text="✈️ Воздушные силы", callback_data="menu_army_air")],
        [InlineKeyboardButton(text="◀️ Назад в штаб", callback_data="menu_main")]
    ])

def army_ground_kb(inf_price: int, car_price: int, truck_price: int, tank_price: int, bunker_price: int, spy_price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🪖 10 Пехоты ({inf_price}$)", callback_data="buy_infantry"),
         InlineKeyboardButton(text=f"🚙 1 Авто ({car_price}$)", callback_data="buy_cars")],
        [InlineKeyboardButton(text=f"🚛 1 Груз. ({truck_price}$)", callback_data="buy_trucks"),
         InlineKeyboardButton(text=f"🚜 1 Танк ({tank_price}$)", callback_data="buy_tanks")],
        [InlineKeyboardButton(text=f"🛡 Бункер ({bunker_price}$)", callback_data="buy_bunkers"),
         InlineKeyboardButton(text=f"🕵️‍♂️ 1 Шпион ({spy_price}$)", callback_data="buy_spies")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def army_naval_kb(destroyer_price: int, cruiser_price: int, battleship_price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🚤 Эсминец ({destroyer_price}$)", callback_data="buy_destroyers"),
         InlineKeyboardButton(text=f"🛳 Крейсер ({cruiser_price}$)", callback_data="buy_cruisers")],
        [InlineKeyboardButton(text=f"⛴ Линкор ({battleship_price}$)", callback_data="buy_battleships")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def tactics_kb(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Блицкриг (Атака +30%, Риск)", callback_data=f"tactic_blitz_{target_id}")],
        [InlineKeyboardButton(text="🛡 Осада (Меньше потерь, Атака -10%)", callback_data=f"tactic_siege_{target_id}")],
        [InlineKeyboardButton(text="⚖️ Стандартный бой", callback_data=f"tactic_balance_{target_id}")],
        [InlineKeyboardButton(text="🕵️‍♂️ Разведка (1 Шпион)", callback_data=f"spy_{target_id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu_war")]
    ])

def war_targets_kb(targets: List[aiosqlite.Row]) -> InlineKeyboardMarkup:
    kb = []
    for t in targets:
        type_str = "👤" if t['owner_id'] else "🤖"
        geo = ""
        if t['rivers'] > 0: geo += "🏞"
        if t['seas'] > 0: geo += "🌊"
        kb.append([InlineKeyboardButton(text=f"{df(t['flag'])} {t['name']} {type_str} {geo}", callback_data=f"prepwar_{t['id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def alliance_none_kb(alliances: List[aiosqlite.Row]) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text="➕ Создать Альянс (10,000$)", callback_data="aly_create")]]
    for aly in alliances:
        kb.append([InlineKeyboardButton(text=f"Подать заявку в {aly['flag']} {aly['name']}", callback_data=f"aly_join_{aly['id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def alliance_member_kb(is_leader: bool) -> InlineKeyboardMarkup:
    kb = []
    if is_leader:
        kb.append([InlineKeyboardButton(text="📥 Заявки на вступление", callback_data="aly_reqs")])
        kb.append([InlineKeyboardButton(text="❌ Распустить Альянс", callback_data="aly_disband")])
    else:
        kb.append([InlineKeyboardButton(text="🚪 Покинуть Альянс", callback_data="aly_leave")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def politics_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Свод законов", callback_data="politics_laws_list")],
        [InlineKeyboardButton(text="🏛 Тип правления", callback_data="politics_gov_menu"),
         InlineKeyboardButton(text="⛪️ Религия", callback_data="politics_rel_menu")],
        [InlineKeyboardButton(text="🎨 Кастомизация", callback_data="custom_menu")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def gov_menu_kb(current_gov: str) -> InlineKeyboardMarkup:
    govs = ["Демократия", "Коммунизм", "Монархия", "Военная Хунта", "Теократия", "Анархия"]
    kb = []
    for g in govs:
        status = "👑 " if g == current_gov else ""
        kb.append([InlineKeyboardButton(text=f"{status}{g}", callback_data=f"gov_switch_{g}")])
    kb.append([InlineKeyboardButton(text="◀️ В Политический хаб", callback_data="menu_politics_hub")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def rel_menu_kb(current_rel: str) -> InlineKeyboardMarkup:
    rels = ["Христианство", "Ислам", "Буддизм", "Атеизм", "Нет"]
    kb = []
    for r in rels:
        status = "⛪️ " if r == current_rel else ""
        kb.append([InlineKeyboardButton(text=f"{status}{r}", callback_data=f"rel_switch_{r}")])
    kb.append([InlineKeyboardButton(text="◀️ В Политический хаб", callback_data="menu_politics_hub")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def laws_list_kb(enacted_laws_str: str) -> InlineKeyboardMarkup:
    active_ids = [int(x) for x in enacted_laws_str.split(',') if x.strip().isdigit()]
    kb = []
    for idx, l in LAWS_INFO.items():
        is_active = idx in active_ids
        status_str = "📜 Действует" if is_active else "❌ Выключен"
        action_btn_text = f"Отменить ({l['cost_rep']}$)" if is_active else f"Принять ({l['cost_act']}$)"
        action_callback = f"law_toggle_{idx}_{'rep' if is_active else 'act'}"
        
        kb.append([
            InlineKeyboardButton(text=f"{l['name']}", callback_data=f"law_desc_{idx}"),
            InlineKeyboardButton(text=action_btn_text, callback_data=action_callback)
        ])
    kb.append([InlineKeyboardButton(text="◀️ В Политический хаб", callback_data="menu_politics_hub")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def custom_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Сменить название (5,000$)", callback_data="cust_change_name")],
        [InlineKeyboardButton(text="🖼 Сменить флаг/фото (5,000$)", callback_data="cust_change_flag")],
        [InlineKeyboardButton(text="◀️ В Политический хаб", callback_data="menu_politics_hub")]
    ])

# Клавиатуры администратора (были упущены в оригинале)
def admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Страны", callback_data="adm_countries"),
         InlineKeyboardButton(text="🤝 Альянсы", callback_data="adm_alliances")],
        [InlineKeyboardButton(text="📦 Бэкапы", callback_data="adm_backups"),
         InlineKeyboardButton(text="👮‍♂️ Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="⚡️ Запустить Ивент", callback_data="adm_event")],
        [InlineKeyboardButton(text="💰 Выдать Ресурсы", callback_data="adm_resources")]
    ])

def admin_countries_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Список стран", callback_data="admin_list_countries")],
        [InlineKeyboardButton(text="Создать NPC", callback_data="admin_create_npc"),
         InlineKeyboardButton(text="Создать свободную", callback_data="admin_create_free")],
        [InlineKeyboardButton(text="Удалить страну", callback_data="admin_del_country")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]
    ])

def admin_backups_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скачать БД", callback_data="admin_download_db")],
        [InlineKeyboardButton(text="Загрузить (Откат)", callback_data="admin_upload_db")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]
    ])

def admin_alliances_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Список альянсов", callback_data="admin_list_alliances")],
        [InlineKeyboardButton(text="Удалить альянс", callback_data="admin_del_alliance")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]
    ])

def admin_admins_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Список админов", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="Добавить", callback_data="admin_add_admin"),
         InlineKeyboardButton(text="Удалить", callback_data="admin_rem_admin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]
    ])

# ========================================================================
# ТОРГОВЛЯ МЕЖДУ ИГРОКАМИ (/send)
# ========================================================================
@dp.message(Command("send"))
async def cmd_send(message: Message) -> None:
    if not message.text: return
    args = message.text.split()
    if len(args) != 4:
        await message.answer(
            "📦 <b>Рынок и Торговля</b>\n\n"
            "Использование: <code>/send [ID или @юзернейм] [Ресурс] [Количество]</code>\n\n"
            "<b>Доступные ресурсы:</b> <code>budget</code> (деньги), <code>materials</code> (материалы), <code>oil</code> (нефть), <code>food</code> (еда)\n\n"
            "<i>Пример:</i> <code>/send @alex budget 5000</code>"
        )
        return
    
    target_str, res_type, amount_str = args[1], args[2].lower(), args[3]
    valid_res = {"budget": "Бюджет", "materials": "Материалы", "oil": "Нефть", "food": "Еда"}
    
    if res_type not in valid_res:
        await message.answer(f"❌ Неверный тип ресурса. Доступно: {', '.join(valid_res.keys())}")
        return
        
    try:
        amount = int(amount_str)
        if amount <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Количество должно быть положительным числом.")
        return
        
    sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not sender: 
        await message.answer("❌ У вас нет страны!")
        return
    
    if sender[res_type] < amount:
        await message.answer(f"❌ Недостаточно ресурса {valid_res[res_type]}! У вас только {sender[res_type]}.")
        return

    target_country = None
    if target_str.startswith("@"):
        target_username = target_str[1:]
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target_username,))
    elif target_str.isdigit():
        target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target_str),))
        
    if not target_country:
        await message.answer("❌ Страна получателя не найдена. Убедитесь, что игрок запустил бота и создал страну.")
        return
        
    if sender['id'] == target_country['id']:
        await message.answer("❌ Нельзя отправить ресурсы самому себе.")
        return

    await execute_db(f"UPDATE countries SET {res_type} = {res_type} - ? WHERE id = ?", (amount, sender['id']))
    await execute_db(f"UPDATE countries SET {res_type} = {res_type} + ? WHERE id = ?", (amount, target_country['id']))
    
    await message.answer(f"✅ Успешный перевод!\nОтправлено <b>{amount} {valid_res[res_type]}</b> в страну {df(target_country['flag'])} {target_country['name']}.")
    
    try:
        if target_country['owner_id']:
            await bot.send_message(
                target_country['owner_id'], 
                f"📦 <b>Гуманитарная помощь!</b>\nСтрана {df(sender['flag'])} {sender['name']} перевела вам <b>{amount} {valid_res[res_type]}</b>."
            )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление пользователю: {e}")

# ========================================================================
# СТАРТ И СОЗДАНИЕ/ВЫБОР СТРАНЫ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await update_username(message.from_user.id, message.from_user.username)
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if country:
        await message.answer(
            f"С возвращением, Правитель!\nТвоя страна: <b>{df(country['flag'])} {country['name']}</b>", 
            reply_markup=main_menu_kb()
        )
        return
        
    unclaimed = await fetch_all("SELECT * FROM countries WHERE is_unclaimed = 1")
    
    if unclaimed:
        kb = [[InlineKeyboardButton(text="➕ Основать новую страну", callback_data="start_create")]]
        for c in unclaimed:
            kb.append([InlineKeyboardButton(text=f"👑 Занять {df(c['flag'])} {c['name']} (Готовая)", callback_data=f"claim_free_{c['id']}")])
        
        await message.answer(
            "🌍 <b>Добро пожаловать в 'Войну Стран'!</b>\n\n"
            "В мире есть заброшенные, но развитые государства. Вы можете возглавить одно из них или начать с нуля:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        await message.answer("🌍 <b>Добро пожаловать!</b>\nПридумай <b>Название</b> для своей страны:")
        await state.set_state(CreateCountry.name)

@dp.callback_query(F.data == "start_create")
async def start_create_btn(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    await safe_edit(callback.message, "Придумай <b>Название</b> для своей новой страны:")
    await state.set_state(CreateCountry.name)
    await callback.answer()

@dp.callback_query(F.data.startswith("claim_free_"))
async def claim_free_country(callback: CallbackQuery) -> None:
    if not callback.message: return
    c_id = int(callback.data.split("_")[2])
    country = await fetch_one("SELECT * FROM countries WHERE id = ? AND is_unclaimed = 1", (c_id,))
    
    if not country:
        await callback.answer("Эта страна уже занята!", show_alert=True)
        return
        
    await execute_db(
        "UPDATE countries SET owner_id = ?, username = ?, is_unclaimed = 0 WHERE id = ?",
        (callback.from_user.id, callback.from_user.username or "", c_id)
    )
    
    await safe_edit(callback.message, 
        f"🎉 Вы успешно возглавили государство <b>{df(country['flag'])} {country['name']}</b>!\n"
        f"Переходите в главное меню для управления.",
        reply_markup=main_menu_kb()
    )
    await callback.answer()

@dp.message(CreateCountry.name)
async def process_country_name(message: Message, state: FSMContext) -> None:
    if not message.text: return
    if len(message.text) > 30:
        await message.answer("Слишком длинное! Максимум 30 символов:")
        return
    await state.update_data(name=message.text)
    await message.answer("Отправь <b>Эмодзи</b> для иконки страны ИЛИ <b>Фотографию</b> (только 16:9 или 1920x1080):")
    await state.set_state(CreateCountry.flag)

@dp.message(CreateCountry.flag, F.text | F.photo)
async def process_country_flag(message: Message, state: FSMContext) -> None:
    flag = ""
    if message.photo:
        photo = message.photo[-1]
        ratio = photo.width / photo.height
        if not (1.7 < ratio < 1.8) and not (photo.width == 1920 and photo.height == 1080):
            await message.answer("❌ Фото должно быть в разрешении 1920x1080 или в соотношении сторон 16:9!\nОтправь другое фото или простой эмодзи:")
            return
        flag = f"photo:{photo.file_id}"
    elif message.text:
        flag = message.text[:2] 
    else:
        await message.answer("❌ Пожалуйста, отправь фото или эмодзи!")
        return

    data = await state.get_data()
    rivers, seas = random.randint(0, 3), random.randint(0, 1)
    
    await execute_db(
        "INSERT INTO countries (owner_id, username, name, flag, rivers, seas) VALUES (?, ?, ?, ?, ?, ?)",
        (message.from_user.id, message.from_user.username or "", data.get('name', 'Страна'), flag, rivers, seas)
    )
    
    await message.answer(
        f"🎉 Страна <b>{df(flag)} {data.get('name', 'Страна')}</b> основана!\n"
        f"Реки: {rivers}, Выход к морю: {'Да' if seas else 'Нет'}",
        reply_markup=main_menu_kb()
    )
    await state.clear()

# ========================================================================
# ХЭНДЛЕРЫ МЕНЮ
# ========================================================================
@dp.callback_query(F.data.startswith("menu_"))
async def process_menus(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    if is_spam(callback.from_user.id): 
        await callback.answer("⏳ Не так быстро!", show_alert=False)
        return
        
    await state.clear()
    await update_username(callback.from_user.id, callback.from_user.username)
    
    action = callback.data.split("_", 1)[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if not country:
        await callback.answer("У вас нет страны! Напишите /start", show_alert=True)
        return

    if action == "profile":
        aly_text = "Нет"
        if country['alliance_id']:
            aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
            if aly: aly_text = f"{df(aly['flag'])} {aly['name']}"

        geo = f"🏞 Рек: {country['rivers']} | 🌊 Море: {'Есть' if country['seas'] else 'Нет'}"
        photo_id = country['flag'].split(":")[1] if country['flag'].startswith("photo:") else None

        text = (
            f"🌍 <b>Страна:</b> {df(country['flag'])} {country['name']} (Побед: {country['war_wins']} 🏅)\n"
            f"👤 <b>Строй:</b> {country['government']} | ⛪️ <b>Вера:</b> {country['religion']}\n"
            f"👥 <b>Граждане:</b> {country['citizens']:,}\n"
            f"🤝 <b>Альянс:</b> {aly_text}\n"
            f"🗺 <b>Ландшафт:</b> {geo}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"💰 <b>Бюджет:</b> {country['budget']:,}$\n"
            f"🧱 <b>Материалы:</b> {country['materials']:,} | 🛢 <b>Нефть:</b> {country['oil']:,} | 🥩 <b>Еда:</b> {country['food']:,}\n"
            f"📈 <b>Базовый ВВП:</b> {country['gdp']:,}$\n"
            f"🗺 <b>Территория:</b> {country['territory']:,} км²\n"
            f"🏘 <b>Поселения (Города):</b> {country['settlements']}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🏭 Заводы: {country['factories']} | 🛢 Вышки: {country['oil_rigs']} | 🌾 Фермы: {country['farms']}\n"
            f"🌉 Понтонные мосты: {country['bridges']}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"⚔️ <b>Наземные:</b> {country['infantry']} Пех. | {country['cars']} Авто | {country['trucks']} Груз | {country['tanks']} Танков\n"
            f"⚓️ <b>Флот:</b> {country['destroyers']} Эсм. | {country['cruisers']} Крейс. | {country['battleships']} Линкоров\n"
            f"🛡 <b>Защита:</b> {country['bunkers']} Бункеры | 🕵️‍♂️ Шпионы: {country['spies']}"
        )
        await safe_edit(callback.message, text, reply_markup=main_menu_kb(), photo_id=photo_id)
        
    elif action == "main":
        await safe_edit(callback.message, "Штаб Главнокомандующего. Ожидаю приказов:", reply_markup=main_menu_kb())
        
    elif action == "economy":
        mults = calculate_multipliers(country)
        prod_money = int(((country['settlements'] * 500) + country['gdp']) * mults['budget'])
        prod_materials = int((country['factories'] * 150) * mults['materials'])
        prod_oil = int((country['oil_rigs'] * 100) * mults['oil'])
        prod_food = int((country['farms'] * 300) * mults['food'])
        
        cons_food = int((int(country['infantry'] * 1.5) + (country['spies'] * 5) + int(country['citizens'] * 0.05)) * mults['food_cons'])
        cons_oil = int((int(country['cars'] * 0.5 + country['trucks'] * 1 + country['tanks'] * 2 + 
                       country['destroyers'] * 5 + country['cruisers'] * 10 + country['battleships'] * 20)) * mults['oil_cons'])
        
        text = (
            f"🏭 <b>Министерство Экономики</b>\n"
            f"<i>Тик происходит каждые 3 минуты</i>\n\n"
            f"<b>Склады и запасы:</b>\n"
            f"💵 Бюджет: {country['budget']:,}$\n"
            f"🧱 Материалы: {country['materials']:,}\n"
            f"🛢 Нефть: {country['oil']:,}\n"
            f"🥩 Еда: {country['food']:,}\n\n"
            f"<b>Прогноз на следующий тик:</b>\n"
            f"💵 Деньги: +{prod_money}$\n"
            f"🧱 Материалы: +{prod_materials}\n"
            f"🛢 Нефть: +{prod_oil} / -{cons_oil} (Итог: {prod_oil - cons_oil})\n"
            f"🥩 Еда: +{prod_food} / -{cons_food} (Итог: {prod_food - cons_food})\n\n"
            f"<i>⚠️ При нехватке нефти техника начнет простаивать, а при дефиците еды начнется голод.</i>"
        )
        await safe_edit(callback.message, text, reply_markup=economy_build_kb())

    elif action == "army":
        await safe_edit(callback.message, 
            f"🪖 <b>Министерство Обороны</b>\n\nВыберите категорию войск для закупки:\n💵 Доступно: {country['budget']}$ | 🧱 {country['materials']} мат. | 🥩 {country['food']} еды", 
            reply_markup=army_main_kb()
        )
    elif action == "army_ground":
        mults = calculate_multipliers(country)
        inf_cost_mult = 0.5 if 5 in [int(x) for x in country['enacted_laws'].split(',') if x.strip().isdigit()] else 1.0
        gov_land_mult = 0.85 if country['government'] == "Военная Хунта" else 1.0
        
        inf_price = int(100 * inf_cost_mult * gov_land_mult)
        car_price = int(300 * gov_land_mult)
        truck_price = int(500 * gov_land_mult)
        tank_price = int(2000 * gov_land_mult)
        bunker_price = int(3000 * gov_land_mult)
        spy_price = 700 if country['government'] == "Теократия" else 1000
        
        await safe_edit(callback.message, 
            "🪖 <b>Наземные войска и укрепления:</b>", 
            reply_markup=army_ground_kb(inf_price, car_price, truck_price, tank_price, bunker_price, spy_price)
        )
    elif action == "army_naval":
        gov_navy_mult = 0.85 if country['government'] == "Военная Хунта" else 1.0
        dest_price = int(3000 * gov_navy_mult)
        cruis_price = int(7000 * gov_navy_mult)
        batt_price = int(15000 * gov_navy_mult)
        
        await safe_edit(callback.message, "⚓️ <b>Военно-морские верфи:</b>", reply_markup=army_naval_kb(dest_price, cruis_price, batt_price))
    elif action == "army_air":
        await callback.answer("✈️ Воздушные силы находятся в разработке! 🛠", show_alert=True)

    elif action == "politics_hub":
        raw_laws = country['enacted_laws']
        active_ids = [int(x) for x in raw_laws.split(',') if x.strip().isdigit()]
        laws_str = ", ".join([LAWS_INFO[x]['name'] for x in active_ids]) if active_ids else "Нет принятых законов"
        
        text = (
            f"🏛 <b>Политический штаб вашей страны</b>\n\n"
            f"⚙️ <b>Текущий строй:</b> {country['government']}\n"
            f"⛪️ <b>Гос. религия:</b> {country['religion']}\n"
            f"📜 <b>Активные законы:</b> {laws_str}\n"
        )
        await safe_edit(callback.message, text, reply_markup=politics_hub_kb())

    elif action == "alliance":
        if country['alliance_id'] == 0:
            top_alliances = await fetch_all("SELECT * FROM alliances LIMIT 5")
            await safe_edit(callback.message, "🤝 <b>Дипломатия Альянсов</b>\n\nВы не состоите в альянсе.", reply_markup=alliance_none_kb(top_alliances))
        else:
            aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
            if aly:
                members = await fetch_all("SELECT * FROM countries WHERE alliance_id = ?", (aly['id'],))
                total_power = sum(get_base_power(m) for m in members)
                
                text = f"🤝 <b>Альянс:</b> {df(aly['flag'])} {aly['name']}\n\n"
                text += f"Участников: {len(members)}\n"
                text += f"Суммарная мощь войск альянса: ⚔️ {total_power}\n\n<b>Список стран:</b>\n"
                for m in members:
                    role = "👑 Лидер" if m['owner_id'] == aly['leader_id'] else "👤 Участник"
                    text += f"- {df(m['flag'])} {m['name']} ({role})\n"
                    
                is_leader = (country['owner_id'] == aly['leader_id'])
                await safe_edit(callback.message, text, reply_markup=alliance_member_kb(is_leader))

    elif action == "war":
        targets = await fetch_all("SELECT * FROM countries WHERE id != ? AND is_unclaimed = 0 ORDER BY RANDOM() LIMIT 10", (country['id'],))
        if not targets:
            await callback.answer("В мире пока нет других стран для атаки!", show_alert=True)
            return
            
        await safe_edit(callback.message, 
            "⚔️ <b>Командование: Выбор цели</b>\n"
            "👤 Игроки | 🤖 NPC | 🏞 Реки | 🌊 Море\n\n"
            "<i>Для атаки требуется 200 Еды и 100 Нефти на мобилизацию!</i>",
            reply_markup=war_targets_kb(targets)
        )
    await callback.answer()

# ========================================================================
# ПОЛИТИЧЕСКИЕ CALLBACK-ХЭНДЛЕРЫ
# ========================================================================
@dp.callback_query(F.data == "menu_politics_hub")
async def callback_pol_hub(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    await state.clear()
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    raw_laws = country['enacted_laws']
    active_ids = [int(x) for x in raw_laws.split(',') if x.strip().isdigit()]
    laws_str = ", ".join([LAWS_INFO[x]['name'] for x in active_ids]) if active_ids else "Нет принятых законов"
    
    text = (
        f"🏛 <b>Политический штаб вашей страны</b>\n\n"
        f"⚙️ <b>Текущий строй:</b> {country['government']}\n"
        f"⛪️ <b>Гос. религия:</b> {country['religion']}\n"
        f"📜 <b>Активные законы:</b> {laws_str}\n"
    )
    await safe_edit(callback.message, text, reply_markup=politics_hub_kb())
    await callback.answer()

@dp.callback_query(F.data == "politics_gov_menu")
async def callback_gov_menu(callback: CallbackQuery) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    await safe_edit(callback.message, "🏛 <b>Смена государственного строя</b>\nВы можете переформатировать правление:\n\n<i>Стоимость смены строя составляет 2,000$</i>", reply_markup=gov_menu_kb(country['government']))
    await callback.answer()

@dp.callback_query(F.data.startswith("gov_switch_"))
async def callback_gov_switch(callback: CallbackQuery) -> None:
    new_gov = callback.data.split("_")[2]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    if country['government'] == new_gov:
        await callback.answer("Ваша страна уже использует этот тип правления!", show_alert=True)
        return
        
    if country['budget'] < 2000:
        await callback.answer("❌ Недостаточно средств для смены строя! Требуется 2,000$.", show_alert=True)
        return
        
    await execute_db("UPDATE countries SET budget = budget - 2000, government = ? WHERE id = ?", (new_gov, country['id']))
    await callback.answer(f"🎉 Вы успешно установили строй: {new_gov}!", show_alert=True)
    await callback_gov_menu(callback)

@dp.callback_query(F.data == "politics_rel_menu")
async def callback_rel_menu(callback: CallbackQuery) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    await safe_edit(callback.message, "⛪️ <b>Государственная религия</b>\nПринятие или изменение официальной веры дает определенные эффекты.\n\n<i>Стоимость принятия/смены веры составляет 1,500$</i>", reply_markup=rel_menu_kb(country['religion']))
    await callback.answer()

@dp.callback_query(F.data.startswith("rel_switch_"))
async def callback_rel_switch(callback: CallbackQuery) -> None:
    new_rel = callback.data.split("_")[2]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    if country['religion'] == new_rel:
        await callback.answer("В вашей стране уже принята эта вера!", show_alert=True)
        return
        
    if country['budget'] < 1500:
        await callback.answer("❌ Недостаточно средств для принятия веры! Требуется 1,500$.", show_alert=True)
        return
        
    await execute_db("UPDATE countries SET budget = budget - 1500, religion = ? WHERE id = ?", (new_rel, country['id']))
    await callback.answer(f"⛪️ Вы официально приняли: {new_rel}!", show_alert=True)
    await callback_rel_menu(callback)

@dp.callback_query(F.data == "politics_laws_list")
async def callback_laws_list(callback: CallbackQuery) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    await safe_edit(callback.message, "📜 <b>Государственный свод законов</b>\nЗдесь вы можете принять важные указы:", reply_markup=laws_list_kb(country['enacted_laws']))
    await callback.answer()

@dp.callback_query(F.data.startswith("law_desc_"))
async def callback_law_desc(callback: CallbackQuery) -> None:
    law_id = int(callback.data.split("_")[2])
    law = LAWS_INFO[law_id]
    await callback.answer(f"ℹ️ {law['name']}\n{law['desc']}", show_alert=True)

@dp.callback_query(F.data.startswith("law_toggle_"))
async def callback_law_toggle(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    law_id = int(parts[2])
    action = parts[3]
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    raw_laws = country['enacted_laws']
    active_ids = [int(x) for x in raw_laws.split(',') if x.strip().isdigit()]
    law = LAWS_INFO[law_id]
    
    if action == "act":
        if law_id in active_ids:
            await callback.answer("Этот закон уже действует!", show_alert=True)
            return
        if country['budget'] < law['cost_act']:
            await callback.answer(f"❌ Нужно {law['cost_act']}$ для принятия этого закона!", show_alert=True)
            return
            
        active_ids.append(law_id)
        new_laws_str = ",".join(map(str, active_ids))
        await execute_db("UPDATE countries SET budget = budget - ?, enacted_laws = ? WHERE id = ?", (law['cost_act'], new_laws_str, country['id']))
        await callback.answer(f"📜 Закон '{law['name']}' успешно принят!", show_alert=True)
        
    elif action == "rep":
        if law_id not in active_ids:
            await callback.answer("Этот закон не принят в вашей стране!", show_alert=True)
            return
        if country['budget'] < law['cost_rep']:
            await callback.answer(f"❌ Нужно {law['cost_rep']}$ для отмены этого закона!", show_alert=True)
            return
            
        active_ids.remove(law_id)
        new_laws_str = ",".join(map(str, active_ids))
        await execute_db("UPDATE countries SET budget = budget - ?, enacted_laws = ? WHERE id = ?", (law['cost_rep'], new_laws_str, country['id']))
        await callback.answer(f"❌ Закон '{law['name']}' успешно отменен!", show_alert=True)

    await callback_laws_list(callback)

# ========================================================================
# КАСТОМИЗАЦИЯ СТРАНЫ ЗА ДЕНЬГИ
# ========================================================================
@dp.callback_query(F.data == "custom_menu")
async def callback_custom_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    await state.clear()
    await safe_edit(callback.message, "🎨 <b>Кастомизация вашей Державы</b>\nВы можете изменить название или внешний вид (флаг) своей страны за игровую валюту.\n\nКаждое изменение стоит <b>5,000$</b>.", reply_markup=custom_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "cust_change_name")
async def callback_change_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    if country['budget'] < 5000:
        await callback.answer("❌ Недостаточно средств! Нужно 5,000$.", show_alert=True)
        return
        
    await safe_edit(callback.message, "✏️ <b>Смена названия страны (5,000$)</b>\nВведите новое название для вашей державы (не более 30 символов):")
    await state.set_state(CustomState.change_name)
    await callback.answer()

@dp.message(CustomState.change_name)
async def process_custom_name(message: Message, state: FSMContext) -> None:
    if not message.text: return
    if len(message.text) > 30:
        await message.answer("Слишком длинное! Максимум 30 символов. Попробуйте еще раз:")
        return
        
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not country: return
    
    if country['budget'] < 5000:
        await state.clear()
        await message.answer("❌ За время ввода у вас не осталось нужного количества бюджета!")
        return
        
    await execute_db("UPDATE countries SET budget = budget - 5000, name = ? WHERE id = ?", (message.text, country['id']))
    await message.answer(f"🎉 Ваша страна успешно переименована в <b>{message.text}</b>!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data == "cust_change_flag")
async def callback_change_flag_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    if country['budget'] < 5000:
        await callback.answer("❌ Недостаточно средств! Нужно 5,000$.", show_alert=True)
        return
        
    await safe_edit(callback.message, "🖼 <b>Смена герба/флага (5,000$)</b>\nПришлите новый <b>эмодзи</b> или качественное <b>фото</b> (строго соотношение 16:9 или 1920x1080):")
    await state.set_state(CustomState.change_flag)
    await callback.answer()

@dp.message(CustomState.change_flag, F.text | F.photo)
async def process_custom_flag(message: Message, state: FSMContext) -> None:
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not country: return
    
    if country['budget'] < 5000:
        await state.clear()
        await message.answer("❌ У вас не хватает 5,000$ для применения изменений!")
        return

    flag = ""
    if message.photo:
        photo = message.photo[-1]
        ratio = photo.width / photo.height
        if not (1.7 < ratio < 1.8) and not (photo.width == 1920 and photo.height == 1080):
            await message.answer("❌ Фото должно быть в разрешении 1920x1080 или в соотношении сторон 16:9!\nОтправьте другое фото или простой эмодзи:")
            return
        flag = f"photo:{photo.file_id}"
    elif message.text:
        flag = message.text[:2] 
    else:
        await message.answer("❌ Пожалуйста, отправьте фото или эмодзи флага!")
        return
        
    await execute_db("UPDATE countries SET budget = budget - 5000, flag = ? WHERE id = ?", (flag, country['id']))
    await message.answer(f"🎉 Герб/Флаг вашей страны успешно изменен!", reply_markup=main_menu_kb())
    await state.clear()

# ========================================================================
# АЛЬЯНСЫ: ЗАЯВКИ И УПРАВЛЕНИЕ
# ========================================================================
@dp.callback_query(F.data.startswith("aly_join_"))
async def cmd_aly_join_req(callback: CallbackQuery) -> None:
    if is_spam(callback.from_user.id): 
        await callback.answer("⏳", show_alert=False)
        return
    
    aly_id = int(callback.data.split("_")[2])
    exists = await fetch_one("SELECT id FROM alliance_requests WHERE user_id = ? AND alliance_id = ?", (callback.from_user.id, aly_id))
    if exists:
        await callback.answer("Вы уже подали заявку в этот альянс!", show_alert=True)
        return
        
    await execute_db("INSERT INTO alliance_requests (alliance_id, user_id) VALUES (?, ?)", (aly_id, callback.from_user.id))
    await callback.answer("✅ Заявка отправлена лидеру альянса!", show_alert=True)

@dp.callback_query(F.data == "aly_reqs")
async def cmd_aly_reqs(callback: CallbackQuery) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    reqs = await fetch_all("SELECT * FROM alliance_requests WHERE alliance_id = ?", (country['alliance_id'],))
    if not reqs:
        await callback.answer("Заявок на вступление пока нет.", show_alert=True)
        return
        
    kb = []
    for r in reqs:
        user_c = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (r['user_id'],))
        if user_c:
            kb.append([InlineKeyboardButton(text=f"✅ Принять {df(user_c['flag'])} {user_c['name']}", callback_data=f"aly_acc_{r['id']}_{user_c['owner_id']}")])
            kb.append([InlineKeyboardButton(text=f"❌ Отклонить {df(user_c['flag'])} {user_c['name']}", callback_data=f"aly_rej_{r['id']}")])
            
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_alliance")])
    await safe_edit(callback.message, "📥 <b>Заявки на вступление:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("aly_acc_"))
async def aly_accept(callback: CallbackQuery) -> None:
    parts = callback.data.split("_")
    req_id, user_id = int(parts[2]), int(parts[3])
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    await execute_db("UPDATE countries SET alliance_id = ? WHERE owner_id = ?", (country['alliance_id'], user_id))
    await execute_db("DELETE FROM alliance_requests WHERE user_id = ?", (user_id,))
    
    await callback.answer("Игрок принят в альянс!", show_alert=True)
    await cmd_aly_reqs(callback)

@dp.callback_query(F.data.startswith("aly_rej_"))
async def aly_reject(callback: CallbackQuery) -> None:
    req_id = int(callback.data.split("_")[2])
    await execute_db("DELETE FROM alliance_requests WHERE id = ?", (req_id,))
    await callback.answer("Заявка успешно отклонена.", show_alert=True)
    await cmd_aly_reqs(callback)

@dp.callback_query(F.data == "aly_create")
async def cmd_aly_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    if country['budget'] < 10000:
        await callback.answer("Недостаточно средств! Нужно 10,000$", show_alert=True)
        return
        
    await safe_edit(callback.message, "Введите <b>Название</b> вашего нового Альянса (до 30 символов):")
    await state.set_state(CreateAlliance.name)

@dp.message(CreateAlliance.name)
async def aly_name_step(message: Message, state: FSMContext) -> None:
    if not message.text: return
    await state.update_data(name=message.text[:30])
    await message.answer("Теперь отправьте <b>Эмодзи</b> для Альянса:")
    await state.set_state(CreateAlliance.flag)

@dp.message(CreateAlliance.flag)
async def aly_flag_step(message: Message, state: FSMContext) -> None:
    if not message.text: return
    flag = message.text[:2]
    data = await state.get_data()
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not country: return
    
    await execute_db("UPDATE countries SET budget = budget - 10000 WHERE id = ?", (country['id'],))
    await execute_db("INSERT INTO alliances (name, flag, leader_id) VALUES (?, ?, ?)", (data.get('name', 'Альянс'), flag, country['owner_id']))
    new_aly = await fetch_one("SELECT id FROM alliances WHERE leader_id = ?", (country['owner_id'],))
    if new_aly:
        await execute_db("UPDATE countries SET alliance_id = ? WHERE id = ?", (new_aly['id'], country['id']))
    
    await message.answer(f"✅ Альянс <b>{flag} {data.get('name', 'Альянс')}</b> успешно создан!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data == "aly_leave")
async def cmd_aly_leave(callback: CallbackQuery) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE id = ?", (country['id'],))
    await callback.answer("Вы покинули Альянс.", show_alert=True)
    await safe_edit(callback.message, "Вы покинули Альянс.", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "aly_disband")
async def cmd_aly_disband(callback: CallbackQuery) -> None:
    if not callback.message: return
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    aly_id = country['alliance_id']
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly_id,))
    await execute_db("DELETE FROM alliances WHERE id = ?", (aly_id,))
    await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (aly_id,))
    await callback.answer("Альянс распущен!", show_alert=True)
    await safe_edit(callback.message, "Ваш Альянс был навсегда распущен.", reply_markup=main_menu_kb())

# ========================================================================
# ХЭНДЛЕРЫ: СТРОИТЕЛЬСТВО И ПОКУПКА
# ========================================================================
@dp.callback_query(F.data.startswith("build_"))
async def process_economy_build(callback: CallbackQuery) -> None:
    if not callback.message: return
    if is_spam(callback.from_user.id): 
        await callback.answer("⏳ Подождите...")
        return
    
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    settlement_mult = 0.90 if country['government'] == "Монархия" else 1.0
    
    if item == "settlement":
        req_money = int(15000 * settlement_mult)
        req_materials = int(2000 * settlement_mult)
        req_food = int(2000 * settlement_mult)
        
        if country['budget'] < req_money or country['materials'] < req_materials or country['food'] < req_food:
            await callback.answer(f"❌ Нужно {req_money}$, {req_materials} Мат., {req_food} Еды.", show_alert=True)
            return
        await execute_db(
            "UPDATE countries SET budget = budget - ?, materials = materials - ?, food = food - ?, settlements = settlements + 1, gdp = gdp + 200 WHERE id = ?", 
            (req_money, req_materials, req_food, country['id'])
        )
        await callback.answer("✅ Основано новое Поселение!", show_alert=True)
    else:
        costs = {
            "factory": (5000, 500, "factories", "Завод"),
            "rig": (8000, 1000, "oil_rigs", "Нефтевышка"),
            "farm": (3000, 200, "farms", "Ферма"),
            "bridge": (2000, 800, "bridges", "Понтонный мост")
        }
        if item not in costs: return
        price_money, price_mat, db_field, name = costs[item]
        
        if country['budget'] < price_money or country['materials'] < price_mat:
            await callback.answer(f"❌ Нужно {price_money}$ и {price_mat} матер.", show_alert=True)
            return
            
        await execute_db(
            f"UPDATE countries SET budget = budget - ?, materials = materials - ?, {db_field} = {db_field} + 1 WHERE id = ?",
            (price_money, price_mat, country['id'])
        )
        await callback.answer(f"✅ Успешно построено: {name}!", show_alert=True)
    
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    if not new_country: return
    text = (
        f"🏭 <b>Министерство Экономики</b>\n"
        f"💵 Бюджет: {new_country['budget']:,}$ | 🧱 Матер.: {new_country['materials']:,} | 🥩 Еда: {new_country['food']:,}\n"
        f"🏘 Поселения: {new_country['settlements']}\n"
        f"🏭 Заводы: {new_country['factories']} | 🛢 Вышки: {new_country['oil_rigs']} | 🌾 Фермы: {new_country['farms']}\n"
        f"🌉 Мосты: {new_country['bridges']}"
    )
    await safe_edit(callback.message, text, reply_markup=economy_build_kb())

@dp.callback_query(F.data.startswith("buy_"))
async def process_army_buy(callback: CallbackQuery) -> None:
    if not callback.message: return
    if is_spam(callback.from_user.id): 
        await callback.answer("⏳ Не закупайте так быстро!")
        return
    
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if not country: return
    
    inf_cost_mult = 0.5 if 5 in [int(x) for x in country['enacted_laws'].split(',') if x.strip().isdigit()] else 1.0
    gov_land_mult = 0.85 if country['government'] == "Военная Хунта" else 1.0
    
    costs = {
        "infantry": {"money": int(100 * inf_cost_mult * gov_land_mult), "food": 50, "materials": 0, "amount": 10, "name": "Пехоты"},
        "cars": {"money": int(300 * gov_land_mult), "food": 0, "materials": 100, "amount": 1, "name": "Авто"},
        "trucks": {"money": int(500 * gov_land_mult), "food": 0, "materials": 200, "amount": 1, "name": "Грузовик"},
        "tanks": {"money": int(2000 * gov_land_mult), "food": 0, "materials": 1000, "amount": 1, "name": "Танк"},
        "destroyers": {"money": int(3000 * gov_land_mult), "food": 0, "materials": 1000, "amount": 1, "name": "Эсминец"},
        "cruisers": {"money": int(7000 * gov_land_mult), "food": 0, "materials": 2500, "amount": 1, "name": "Крейсер"},
        "battleships": {"money": int(15000 * gov_land_mult), "food": 0, "materials": 5000, "amount": 1, "name": "Линкор"},
        "bunkers": {"money": int(3000 * gov_land_mult), "food": 0, "materials": 1500, "amount": 1, "name": "Бункер"},
        "spies": {"money": 700 if country['government'] == "Теократия" else 1000, "food": 0, "materials": 0, "amount": 1, "name": "Шпион"}
    }
    
    if item not in costs: return
    req = costs[item]
    
    if country['budget'] < req["money"] or country['food'] < req["food"] or country['materials'] < req["materials"]:
        await callback.answer(f"❌ Не хватает ресурсов!", show_alert=True)
        return
        
    await execute_db(
        f"UPDATE countries SET budget = budget - ?, food = food - ?, materials = materials - ?, {item} = {item} + ? WHERE id = ?",
        (req["money"], req["food"], req["materials"], req["amount"], country['id'])
    )
    await callback.answer(f"✅ Успешно куплено: {req['amount']} {req['name']}!", show_alert=False)
    
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    if not new_country: return
    
    if item in ["destroyers", "cruisers", "battleships"]:
        gov_navy_mult = 0.85 if new_country['government'] == "Военная Хунта" else 1.0
        dest_price = int(3000 * gov_navy_mult)
        cruis_price = int(7000 * gov_navy_mult)
        batt_price = int(15000 * gov_navy_mult)
        await safe_edit(callback.message, "⚓️ <b>Военно-морские верфи:</b>", reply_markup=army_naval_kb(dest_price, cruis_price, batt_price))
    else:
        inf_price = int(100 * inf_cost_mult * gov_land_mult)
        car_price = int(300 * gov_land_mult)
        truck_price = int(500 * gov_land_mult)
        tank_price = int(2000 * gov_land_mult)
        bunker_price = int(3000 * gov_land_mult)
        spy_price = 700 if new_country['government'] == "Теократия" else 1000
        
        await safe_edit(callback.message, "🪖 <b>Наземные войска и укрепления:</b>", reply_markup=army_ground_kb(inf_price, car_price, truck_price, tank_price, bunker_price, spy_price))

# ========================================================================
# ХЭНДЛЕРЫ: БОЕВАЯ СИСТЕМА
# ========================================================================
@dp.callback_query(F.data.startswith("prepwar_"))
async def process_prepwar(callback: CallbackQuery) -> None:
    if not callback.message: return
    if is_spam(callback.fromuser.id if hasattr(callback, 'from_user') else callback.from_user.id): 
        await callback.answer("⏳")
        return
        
    target_id = int(callback.data.split("_")[1])
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    if not defender: return
    
    geo_info = "\n<b>Ландшафт врага:</b>\n"
    if defender['rivers'] > 0:
        geo_info += f"🏞 Реки ({defender['rivers']}). Нужны понтонные мосты.\n"
    if defender['seas'] > 0:
        geo_info += f"🌊 Море. Без кораблей (эсминцев, крейсеров или линкоров) штраф -50%!\n"

    await safe_edit(callback.message, 
        f"⚔️ <b>Подготовка к вторжению в {df(defender['flag'])} {defender['name']}</b>\n{geo_info}\n",
        reply_markup=tactics_kb(target_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("spy_"))
async def process_spy(callback: CallbackQuery) -> None:
    if not callback.message: return
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        await callback.answer(f"⏳ Шпионы еще в пути! Доступно через {cd} сек.", show_alert=True)
        return
        
    target_id = int(callback.data.split("_")[1])
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if not attacker or not defender: return
    
    if attacker['spies'] < 1:
        await callback.answer("Нет шпионов!", show_alert=True)
        return
        
    await execute_db("UPDATE countries SET spies = spies - 1 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id)
    
    if random.random() < 0.2:
        await callback.answer("Операция провалена!", show_alert=True)
        await safe_edit(callback.message, "💥 <b>Провал операции!</b>\nШпион раскрыт.", reply_markup=tactics_kb(target_id))
        return
        
    def_power_est = get_base_power(defender)
    text = (
        f"🕵️‍♂️ <b>Секретный рапорт по {df(defender['flag'])} {defender['name']}</b>:\n\n"
        f"💰 Бюджет: ~{defender['budget']}$ | 🛢 Нефть: {defender['oil']}\n"
        f"🪖 Наземные: {defender['infantry']} пехоты, {defender['tanks']} танков\n"
        f"⛴ Флот: {defender['destroyers']} Эсм. | {defender['cruisers']} Крейс. | {defender['battleships']} Линкор.\n"
        f"🛡 Укрепления: {defender['bunkers']} бункеров\n\n"
        f"📊 Оценочная базовая мощь: <b>{def_power_est}</b>\n"
    )
    await safe_edit(callback.message, text, reply_markup=tactics_kb(target_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("tactic_"))
async def process_attack(callback: CallbackQuery) -> None:
    if not callback.message: return
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        await callback.answer(f"⏳ Войска на перегруппировке! Атака доступна через {cd} сек.", show_alert=True)
        return

    parts = callback.data.split("_")
    tactic, target_id = parts[1], int(parts[2])
    
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if not attacker or not defender: 
        await callback.answer("Ошибка данных.", show_alert=True)
        return
    if attacker['id'] == defender['id']: 
        await callback.answer("Нельзя напасть на себя!", show_alert=True)
        return
    
    if attacker['food'] < 200 or attacker['oil'] < 100:
        await callback.answer("❌ Для мобилизации армии нужно 200 Еды и 100 Нефти!", show_alert=True)
        return
        
    await execute_db("UPDATE countries SET food = food - 200, oil = oil - 100 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id)
    
    await safe_edit(callback.message, "🚀 <b>Войска пересекают границу...</b>\n\n🛰 Идет оценка обстановки...")
    await asyncio.sleep(2) # Имитация времени боя

    try:
        att_base = get_base_power(attacker)
        def_base = get_base_power(defender)
        
        att_ally_support, att_ally_count = await get_alliance_support(attacker['alliance_id'], attacker['id'])
        def_ally_support, def_ally_count = await get_alliance_support(defender['alliance_id'], defender['id'])

        report = [f"<blockquote>🌍 <b>БОЕВОЙ РАПОРТ: {df(attacker['flag'])} против {df(defender['flag'])}</b></blockquote>\n"]
        
        if att_ally_count > 0: 
            report.append(f"🤝 Ваш Альянс помог! (+{att_ally_support} мощи)")
        if def_ally_count > 0: 
            report.append(f"⚠️ Альянс врага защищает его! (+{def_ally_support} мощи)")

        att_mults = calculate_multipliers(attacker)
        def_mults = calculate_multipliers(defender)
        
        att_total = int((att_base + att_ally_support) * att_mults['army_power'])
        
        bridges_used = 0
        if defender['rivers'] > 0:
            if attacker['bridges'] >= defender['rivers']:
                bridges_used = defender['rivers']
                report.append(f"🌉 Использовано {bridges_used} понтонных мостов.")
            else:
                att_total = int(att_total * 0.70)
                report.append(f"🏞 <b>Катастрофа на переправе!</b> Штраф атаки: -30%!")
                
        if defender['seas'] > 0:
            has_navy = (attacker['destroyers'] > 0 or attacker['cruisers'] > 0 or attacker['battleships'] > 0 or attacker['ships'] > 0)
            if has_navy:
                report.append(f"⛴ Ваш флот успешно прикрыл десант и подавил береговую оборону врага!")
            else:
                att_total = int(att_total * 0.50)
                report.append(f"🌊 <b>Смертельный десант!</b> У вас нет флота. Штраф атаки: -50%!")

        def_total = int((def_base + def_ally_support) * def_mults['army_power'])
        
        if defender['religion'] == "Ислам":
            def_total = int(def_total * 1.15)
            report.append(f"⛪️ Вражеские солдаты яростно бьются за свою веру (Ислам: +15% к защите).")

        att_mult = 1.0 + (min(attacker['war_wins'], 50) * 0.01)
        att_casualty_rate, def_casualty_rate = 0.5, 0.4
        
        if attacker['religion'] == "Буддизм":
            att_casualty_rate *= 0.8
        if defender['religion'] == "Буддизм":
            def_casualty_rate *= 0.8

        if tactic == "blitz":
            att_mult *= 1.3
            att_casualty_rate = 0.7
        elif tactic == "siege":
            att_mult *= 0.9
            att_casualty_rate = 0.2

        att_power = int(att_total * att_mult * random.uniform(0.9, 1.2))
        def_power = int(def_total * random.uniform(0.9, 1.2))

        report.append(f"\n⚔️ Мощь атаки: <b>{att_power}</b>")
        report.append(f"🛡 Мощь защиты: <b>{def_power}</b>\n")

        if att_power > def_power:
            stolen_money = int(defender['budget'] * random.uniform(0.2, 0.4))
            stolen_materials = int(defender['materials'] * random.uniform(0.2, 0.4))
            stolen_oil = int(defender['oil'] * random.uniform(0.2, 0.4))
            stolen_territory = random.randint(1, 3)
            
            att_inf_lost = int(attacker['infantry'] * 0.15 * att_casualty_rate)
            att_tanks_lost = int(attacker['tanks'] * 0.10 * att_casualty_rate)
            
            def_inf_lost = int(defender['infantry'] * def_casualty_rate)
            def_tanks_lost = int(defender['tanks'] * (def_casualty_rate / 2))
            
            await execute_db("""
                UPDATE countries 
                SET budget = budget + ?, materials = materials + ?, oil = oil + ?,
                    territory = territory + ?, war_wins = war_wins + 1,
                    infantry = MAX(0, infantry - ?), tanks = MAX(0, tanks - ?),
                    bridges = bridges - ? WHERE id = ?
            """, (stolen_money, stolen_materials, stolen_oil, stolen_territory, att_inf_lost, att_tanks_lost, bridges_used, attacker['id']))
            
            await execute_db("""
                UPDATE countries 
                SET budget = MAX(0, budget - ?), materials = MAX(0, materials - ?), oil = MAX(0, oil - ?),
                    territory = MAX(1, territory - ?), gdp = MAX(10, gdp - ?),
                    infantry = MAX(0, infantry - ?), tanks = MAX(0, tanks - ?), bunkers = MAX(0, bunkers - 1)
                WHERE id = ?
            """, (stolen_money, stolen_materials, stolen_oil, stolen_territory, stolen_territory * 5, 
                  def_inf_lost, def_tanks_lost, defender['id']))
            
            report.append("🎉 <b>ПОБЕДА! Оборона противника прорвана!</b>")
            report.append("<b>━━━━━━━━━━━━━━━━━━━━</b>")
            report.append(f"💰 <b>Трофеи:</b> {stolen_money}$, {stolen_materials} Мат., {stolen_oil} Нефти")
            report.append(f"🗺 <b>Аннексия:</b> {stolen_territory} км² (+{stolen_territory*5} к ВВП)")
            report.append(f"🩸 <b>Наши потери:</b> {att_inf_lost} Пехоты, {att_tanks_lost} Танков")
            report.append(f"💥 <b>Урон врагу:</b> {def_inf_lost} Пехоты, {def_tanks_lost} Танков")
        else:
            att_inf_lost = int(attacker['infantry'] * att_casualty_rate)
            att_cars_lost = int(attacker['cars'] * att_casualty_rate)
            att_tanks_lost = int(attacker['tanks'] * att_casualty_rate)
            
            def_inf_lost = int(defender['infantry'] * (def_casualty_rate / 2))
            
            await execute_db("UPDATE countries SET infantry = MAX(0, infantry - ?), cars = MAX(0, cars - ?), tanks = MAX(0, tanks - ?), bridges = bridges - ? WHERE id = ?", 
                             (att_inf_lost, att_cars_lost, att_tanks_lost, bridges_used, attacker['id']))
            await execute_db("UPDATE countries SET infantry = MAX(0, infantry - ?) WHERE id = ?", 
                             (def_inf_lost, defender['id']))

            report.append("☠️ <b>ПОРАЖЕНИЕ! Наступление захлебнулось.</b>")
            report.append("<b>━━━━━━━━━━━━━━━━━━━━</b>")
            report.append(f"🩸 <b>Наши потери:</b> {att_inf_lost} Пехоты, {att_cars_lost} Авто, {att_tanks_lost} Танков")
            report.append(f"🛡 <b>Потери врага:</b> {def_inf_lost} Пехоты")

        await safe_edit(callback.message, "\n".join(report), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В штаб", callback_data="menu_war")]]))
        await callback.answer()

    except Exception as e:
        logger.exception("Error during battle simulation")
        await safe_edit(
            callback.message, 
            f"❌ <b>Критическая ошибка симуляции боя:</b>\n<code>{e}</code>\n\n"
            f"Сообщите разработчику для исправления.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В штаб", callback_data="menu_war")]])
        )
        await callback.answer()

# ========================================================================
# ХЭНДЛЕРЫ: АДМИН ПАНЕЛЬ
# ========================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    await state.clear()
    await message.answer("🔧 <b>Главная Панель Администратора</b>\n\nВыберите раздел для управления сервером:", reply_markup=admin_main_kb())

@dp.callback_query(F.data.startswith("adm_"))
async def adm_menus(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await state.clear()
    act = callback.data.split("_")[1]
    
    if act == "main": 
        await safe_edit(callback.message, "🔧 <b>Главная Панель Администратора</b>\nВыберите раздел:", reply_markup=admin_main_kb())
    elif act == "countries": 
        await safe_edit(callback.message, "🌍 <b>Управление Странами</b>\nСоздавайте NPC или удаляйте любые страны с карты.", reply_markup=admin_countries_kb())
    elif act == "backups":
        await safe_edit(callback.message, "📦 <b>Бэкапы и Откаты</b>\nЗдесь можно сохранить базу данных или полностью откатить мир (сброс даты).", reply_markup=admin_backups_kb())
    elif act == "alliances":
        await safe_edit(callback.message, "🤝 <b>Управление Альянсами</b>\nПринудительно удаляйте любые объединения.", reply_markup=admin_alliances_kb())
    elif act == "admins":
        await safe_edit(callback.message, "👮‍♂️ <b>Администраторы сервера</b>\nДобавляйте или снимайте полномочия с пользователей.", reply_markup=admin_admins_kb())
    elif act == "event":
        events = ["Урожай (Еда +2000)", "Кризис (Бюджет -20%)", "Поставки (Мат +1000)"]
        ev = random.choice(events)
        
        if "Урожай" in ev: 
            await execute_db("UPDATE countries SET food = food + 2000 WHERE owner_id IS NOT NULL AND is_unclaimed = 0")
        elif "Кризис" in ev: 
            await execute_db("UPDATE countries SET budget = CAST(budget * 0.8 AS INT) WHERE owner_id IS NOT NULL AND is_unclaimed = 0")
        elif "Поставки" in ev: 
            await execute_db("UPDATE countries SET materials = materials + 1000 WHERE owner_id IS NOT NULL AND is_unclaimed = 0")
        
        await callback.answer(f"✅ Ивент '{ev}' запущен для всех активных игроков!", show_alert=True)
    elif act == "resources":
        await safe_edit(callback.message, "Введите ID или @username игрока, которому нужно изменить ресурсы:")
        await state.set_state(AdminState.give_target)
    
    await callback.answer()

@dp.message(AdminState.give_target)
async def adm_res_target(message: Message, state: FSMContext) -> None:
    if not message.text: return
    target = message.text
    if target.startswith("@"): 
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target[1:],))
    else: 
        try:
            target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target),))
        except ValueError:
            await message.answer("❌ Введите корректный ID или @username.")
            return
    
    if not target_country: 
        await message.answer("❌ Игрок не найден. Введите снова:")
        return
        
    await state.update_data(res_target_id=target_country['id'])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Бюджет", callback_data="res_budget"), InlineKeyboardButton(text="🧱 Мат.", callback_data="res_materials")],
        [InlineKeyboardButton(text="🛢 Нефть", callback_data="res_oil"), InlineKeyboardButton(text="🥩 Еда", callback_data="res_food")],
    ])
    await message.answer(f"Выбрана страна: {df(target_country['flag'])} {target_country['name']}\nКакой ресурс изменить?", reply_markup=kb)
    await state.set_state(AdminState.give_type)

@dp.callback_query(AdminState.give_type, F.data.startswith("res_"))
async def adm_res_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message: return
    res_type = callback.data.split("_")[1]
    await state.update_data(res_type=res_type)
    await safe_edit(callback.message, "Введите количество (например `1000` чтобы выдать, или `-500` чтобы забрать):")
    await state.set_state(AdminState.give_amount)
    await callback.answer()

@dp.message(AdminState.give_amount)
async def adm_res_amount(message: Message, state: FSMContext) -> None:
    if not message.text: return
    try:
        amount = int(message.text)
        data = await state.get_data()
        c_id, r_type = data['res_target_id'], data['res_type']
        
        await execute_db(f"UPDATE countries SET {r_type} = MAX(0, {r_type} + ?) WHERE id = ?", (amount, c_id))
        await message.answer(f"✅ Ресурсы успешно обновлены!", reply_markup=admin_main_kb())
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число.")

@dp.callback_query(F.data == "admin_download_db")
async def admin_download_db(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    filename = f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.db"
    file = FSInputFile(DB_NAME, filename=filename)
    await bot.send_document(chat_id=callback.message.chat.id, document=file, caption="📦 Текущий бэкап мира.")
    await callback.answer()

@dp.callback_query(F.data == "admin_upload_db")
async def admin_upload_db_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await safe_edit(callback.message, 
        "⚠️ <b>ВНИМАНИЕ: ОТКАТ МИРА!</b>\n\n"
        "Загрузка нового файла <code>.db</code> <b>ПОЛНОСТЬЮ ОТКАТИТ ДАТУ ПОЛЬЗОВАТЕЛЕЙ</b> на момент сохранения!\n"
        "Отправь мне файл базы данных в этот чат:"
    )
    await state.set_state(AdminState.waiting_for_db)
    await callback.answer()

@dp.message(AdminState.waiting_for_db, F.document)
async def admin_upload_db_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id): return
    if not message.document: return
    file = await bot.get_file(message.document.file_id)
    if file.file_path:
        await bot.download_file(file.file_path, DB_NAME)
        await message.answer("✅ <b>МИР УСПЕШНО ОТКАТИЛСЯ И ВОССТАНОВЛЕН ИЗ ФАЙЛА!</b>\nВсе данные пользователей сброшены на загруженные.", reply_markup=admin_main_kb())
    await state.clear()

@dp.callback_query(F.data == "admin_create_free")
async def admin_free_country(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id): return
    flag, name = "🏴‍☠️", f"Свободные Земли {random.randint(10,99)}"
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, settlements, infantry, cars, trucks, materials, oil, food, factories, oil_rigs, farms, citizens, is_unclaimed) 
           VALUES (?, ?, 10000, 100, 10, 1, 100, 5, 2, 1000, 500, 2000, 1, 1, 2, 10000, 1)""",
        (name, flag)
    )
    await callback.answer(f"✅ Свободная страна создана! Новички увидят её при старте.", show_alert=True)

@dp.callback_query(F.data == "admin_create_npc")
async def admin_npc_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await safe_edit(callback.message, "Введите название NPC-страны:")
    await state.set_state(AdminState.npc_name)
    await callback.answer()

@dp.message(AdminState.npc_name)
async def admin_npc_name(message: Message, state: FSMContext) -> None:
    if not message.text: return
    await state.update_data(name=message.text)
    await message.answer("Отправьте эмодзи-флаг для NPC:")
    await state.set_state(AdminState.npc_flag)

@dp.message(AdminState.npc_flag)
async def admin_npc_flag(message: Message, state: FSMContext) -> None:
    if not message.text: return
    flag = message.text[:2]
    data = await state.get_data()
    rivers, seas = random.randint(0, 3), random.randint(0, 1)
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, infantry, tanks, destroyers, bunkers, materials, oil, food, rivers, seas) 
           VALUES (?, ?, 15000, 500, 50, 1000, 25, 2, 5, 5000, 5000, 5000, ?, ?)""",
        (data.get('name', 'NPC'), flag, rivers, seas)
    )
    await message.answer(f"✅ NPC-страна <b>{flag} {data.get('name', 'NPC')}</b> добавлена на карту!")
    await state.clear()

@dp.callback_query(F.data == "admin_list_countries")
async def admin_list_countries(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    countries = await fetch_all("SELECT id, flag, name FROM countries")
    text = "📋 <b>Список Стран (ID):</b>\n\n"
    for c in countries: text += f"ID: <code>{c['id']}</code> | {df(c['flag'])} {c['name']}\n"
    
    # Ограничение длины текста Telegram (4096)
    if len(text) > 4000: text = text[:4000] + "...\n(Список обрезан)"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_countries")]]))
    await callback.answer()

@dp.callback_query(F.data == "admin_del_country")
async def admin_del_country_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await safe_edit(callback.message, "🗑 <b>Удаление Страны</b>\n\nОтправьте мне <b>ID страны</b> для её полного удаления с сервера (узнать ID можно в списке стран):")
    await state.set_state(AdminState.del_country)
    await callback.answer()

@dp.message(AdminState.del_country)
async def admin_del_country_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id): return
    if not message.text: return
    try:
        c_id = int(message.text)
        country = await fetch_one("SELECT * FROM countries WHERE id = ?", (c_id,))
        if not country:
            await message.answer("❌ Страна с таким ID не найдена.")
            return
        await execute_db("DELETE FROM countries WHERE id = ?", (c_id,))
        await message.answer(f"✅ Страна <b>{df(country['flag'])} {country['name']}</b> была стёрта с лица Земли!")
    except ValueError:
        await message.answer("❌ Пожалуйста, отправьте только число (ID).")
    await state.clear()

@dp.callback_query(F.data == "admin_list_alliances")
async def admin_list_all(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    alliances = await fetch_all("SELECT id, flag, name FROM alliances")
    if not alliances: 
        await callback.message.answer("Альянсов нет.")
        return
    text = "📋 <b>Список Альянсов (ID):</b>\n\n"
    for a in alliances: text += f"ID: <code>{a['id']}</code> | {df(a['flag'])} {a['name']}\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_alliances")]]))
    await callback.answer()

@dp.callback_query(F.data == "admin_del_alliance")
async def admin_del_aly_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await safe_edit(callback.message, "🗑 <b>Удаление Альянса</b>\nОтправьте <b>ID альянса</b>:")
    await state.set_state(AdminState.del_alliance)
    await callback.answer()

@dp.message(AdminState.del_alliance)
async def admin_del_aly_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id): return
    if not message.text: return
    try:
        a_id = int(message.text)
        aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (a_id,))
        if not aly: 
            await message.answer("❌ Альянс не найден.")
            return
        await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (a_id,))
        await execute_db("DELETE FROM alliances WHERE id = ?", (a_id,))
        await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (a_id,))
        await message.answer(f"✅ Альянс <b>{df(aly['flag'])} {aly['name']}</b> был принудительно распущен администрацией!")
    except ValueError:
        await message.answer("❌ Нужно число (ID).")
    await state.clear()

@dp.callback_query(F.data == "admin_list_admins")
async def admin_list_adm(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    admins = await fetch_all("SELECT user_id FROM admins")
    text = "👮‍♂️ <b>Администраторы:</b>\n"
    for a in admins: 
        role = " (Главный)" if a['user_id'] == SUPER_ADMIN_ID else ""
        text += f"- <code>{a['user_id']}</code>{role}\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_admins")]]))
    await callback.answer()

@dp.callback_query(F.data == "admin_add_admin")
async def admin_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await safe_edit(callback.message, "➕ <b>Назначение Админа</b>\nПришлите Telegram ID пользователя:")
    await state.set_state(AdminState.add_admin)
    await callback.answer()

@dp.message(AdminState.add_admin)
async def admin_add_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id): return
    if not message.text: return
    try:
        new_adm = int(message.text)
        await execute_db("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_adm,))
        await message.answer(f"✅ Пользователь <code>{new_adm}</code> назначен администратором!")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
    await state.clear()

@dp.callback_query(F.data == "admin_rem_admin")
async def admin_rem_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id): return
    if not callback.message: return
    await safe_edit(callback.message, "➖ <b>Снятие Админа</b>\nПришлите Telegram ID пользователя:")
    await state.set_state(AdminState.rem_admin)
    await callback.answer()

@dp.message(AdminState.rem_admin)
async def admin_rem_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id): return
    if not message.text: return
    try:
        rem_adm = int(message.text)
        if rem_adm == SUPER_ADMIN_ID:
            await message.answer("❌ Вы не можете снять Главного Администратора (Создателя)!")
            return
        await execute_db("DELETE FROM admins WHERE user_id = ?", (rem_adm,))
        await message.answer(f"✅ Пользователь <code>{rem_adm}</code> больше не администратор.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
    await state.clear()

# ========================================================================
# ЗАПУСК БОТА
# ========================================================================
async def main() -> None:
    """Главная функция инициализации и запуска бота."""
    logger.info("Инициализация базы данных...")
    await init_db()
    
    logger.info("Запуск фоновой задачи экономики...")
    asyncio.create_task(economy_tick())
    
    logger.info("Бот запущен. Мир начал свое существование...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.critical(f"Критическая ошибка запуска: {e}")
