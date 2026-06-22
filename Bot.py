import asyncio
import logging
import random
import time
import uuid
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, InputMediaPhoto, BotCommand
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
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
# АНТИ-СПАМ СИСТЕМА (ЗАЩИТА ОТ АБУЗА)
# ========================================================================
user_last_action = {}
user_attack_cooldown = {}

BUTTON_COOLDOWN = 1.0  
ATTACK_COOLDOWN = 300  

def is_spam(user_id: int) -> bool:
    """Проверяет, превысил ли пользователь лимит частоты нажатий."""
    now = time.time()
    if now - user_last_action.get(user_id, 0) < BUTTON_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def get_attack_cooldown(user_id: int) -> int:
    """Возвращает оставшееся время кулдауна атаки."""
    now = time.time()
    passed = now - user_attack_cooldown.get(user_id, 0)
    if passed < ATTACK_COOLDOWN:
        return int(ATTACK_COOLDOWN - passed)
    return 0

def set_attack_cooldown(user_id: int):
    """Устанавливает кулдаун атаки для пользователя."""
    user_attack_cooldown[user_id] = time.time()

async def safe_edit(message: types.Message, text: str, reply_markup=None, photo_id=None):
    """Умное редактирование сообщений, поддерживающее переход от текста к фото и наоборот"""
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
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            logging.error(f"Telegram API Error: {e}")

def df(flag: str) -> str:
    """Отображает иконку картинки, если флаг - это фото, иначе сам эмодзи-флаг"""
    if not flag:
        return "🏳️"
    return "🖼" if flag.startswith("photo:") else flag

# ========================================================================
# ГЛОБАЛЬНАЯ ТОРГОВАЯ СИСТЕМА И КОНСТАНТЫ ПОЛИТИКИ
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
    "christianity": {"name": "Христианство"},
    "islam": {"name": "Ислам"},
    "buddhism": {"name": "Буддизм"},
    "hinduism": {"name": "Индуизм"},
    "shintoism": {"name": "Синтоизм"},
    "pastafarianism": {"name": "Пастафарианство"},
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

# ========================================================================
# БАЗА ДАННЫХ И МИГРАЦИИ
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
                alliance_id INTEGER DEFAULT 0,
                gov_type TEXT DEFAULT 'Не выбрано',
                religion TEXT DEFAULT 'Атеизм',
                active_laws TEXT DEFAULT ''
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
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                text_content TEXT,
                photo_id TEXT,
                is_answered INTEGER DEFAULT 0
            )
        """)
        
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        
        # Обширная миграция для добавления новых колонок в старые БД
        new_columns = [
            ("bunkers", "INTEGER DEFAULT 0"), ("spies", "INTEGER DEFAULT 0"),
            ("war_wins", "INTEGER DEFAULT 0"), ("alliance_id", "INTEGER DEFAULT 0"),
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
            
            # Новые ландшафты
            ("mountains", "INTEGER DEFAULT 0"), ("forests", "INTEGER DEFAULT 0"), ("deserts", "INTEGER DEFAULT 0"),
            
            # Новая экономика
            ("steel", "INTEGER DEFAULT 500"), ("electronics", "INTEGER DEFAULT 100"),
            ("steel_mills", "INTEGER DEFAULT 0"), ("tech_factories", "INTEGER DEFAULT 0"),
            
            # Новые войска (Воздух, ПВО и Дроны)
            ("fighters", "INTEGER DEFAULT 0"), ("bombers", "INTEGER DEFAULT 0"), ("helicopters", "INTEGER DEFAULT 0"),
            ("uavs", "INTEGER DEFAULT 0"), ("jet_uavs", "INTEGER DEFAULT 0"), ("baba_yaga", "INTEGER DEFAULT 0"), 
            ("fpv_drones", "INTEGER DEFAULT 0"), ("aa_guns", "INTEGER DEFAULT 0"), ("sam_systems", "INTEGER DEFAULT 0")
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
    """Возвращает строку в виде словаря dict для предотвращения AttributeError в aiogram."""
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchone()
            if result:
                return dict(result)
            return None
    finally:
        await db.close()

async def fetch_all(query, params=()):
    """Возвращает список словарей dict."""
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
# ФОНОВЫЕ ЗАДАЧИ (ОПТИМИЗИРОВАННАЯ ЭКОНОМИКА - 3 МИНУТЫ)
# ========================================================================
def calc_economy_rates(c):
    """Вычисляет притоки, оттоки и боевые модификаторы на основе законов и правления"""
    gov = c.get('gov_type', 'Не выбрано')
    active_laws = c.get('active_laws') or ''
    laws = [l for l in active_laws.split(',') if l]
    
    mod_budget, mod_materials, mod_food_prod, mod_food_cons, mod_oil, mod_citizens = 1.0, 1.0, 1.0, 1.0, 1.0, 1.0
    combat_att_mod, combat_def_mod = 1.0, 1.0
    
    if gov == "democracy": mod_budget += 0.10; mod_citizens += 0.10
    elif gov == "communism": mod_materials += 0.15; mod_citizens -= 0.05
    elif gov == "monarchy": mod_food_prod += 0.15; mod_oil += 0.05
    elif gov == "dictatorship": mod_budget -= 0.05; combat_att_mod += 0.10
    elif gov == "theocracy": mod_budget += 0.05; mod_food_prod += 0.10
        
    if "law_health" in laws: mod_budget -= 0.10; mod_citizens += 0.20
    if "law_martial" in laws: mod_food_cons -= 0.20; mod_citizens -= 0.50
    if "law_trade" in laws: mod_budget += 0.15; mod_materials -= 0.10
    if "law_subsidies" in laws: mod_budget -= 0.15; mod_food_prod += 0.25
    if "law_propaganda" in laws: mod_budget -= 0.05; combat_def_mod += 0.10
    if "law_mobilization" in laws: mod_materials += 0.20; mod_budget -= 0.05
    if "law_conscription" in laws: combat_att_mod += 0.10; mod_citizens -= 0.15
    if "law_ecology" in laws: mod_citizens += 0.15; mod_oil -= 0.15; mod_materials -= 0.10
    if "law_luxury_tax" in laws: mod_budget += 0.20
    if "law_closed_borders" in laws: combat_def_mod += 0.15; mod_budget -= 0.10

    prod_money = int(((c.get('settlements', 1) * 500) + c.get('gdp', 100)) * mod_budget)
    prod_materials = int((c.get('factories', 0) * 150) * mod_materials)
    
    # Новые производства
    prod_steel = int((c.get('steel_mills', 0) * 50) * mod_materials)
    prod_electronics = int((c.get('tech_factories', 0) * 15) * mod_materials)
    
    prod_oil = int((c.get('oil_rigs', 0) * 100) * mod_oil)
    prod_food = int((c.get('farms', 0) * 300) * mod_food_prod)
    
    cons_food = int((
        int(c.get('infantry', 0) * 1.5) + 
        (c.get('machine_guns', 0) * 1) + 
        (c.get('mortars', 0) * 2) + 
        (c.get('artillery', 0) * 2) + 
        (c.get('aa_guns', 0) * 1) + 
        (c.get('sam_systems', 0) * 3) + 
        (c.get('spies', 0) * 5) + 
        int(c.get('citizens', 0) * 0.05)
    ) * mod_food_cons)
    
    cons_oil = int(
        c.get('cars', 0) * 0.5 + 
        c.get('hummers', 0) * 1 + 
        c.get('military_cars', 0) * 2 + 
        c.get('trucks', 0) * 1 + 
        c.get('tanks', 0) * 3 + 
        c.get('boats', 0) * 1 + 
        c.get('submarines', 0) * 4 + 
        c.get('corvettes', 0) * 3 +
        c.get('destroyers', 0) * 5 + 
        c.get('cruisers', 0) * 10 + 
        c.get('battleships', 0) * 20 +
        c.get('carriers', 0) * 50 +
        # Авиация и дроны
        c.get('fighters', 0) * 5 +
        c.get('bombers', 0) * 10 +
        c.get('helicopters', 0) * 3 +
        c.get('uavs', 0) * 1 +
        c.get('jet_uavs', 0) * 3 +
        c.get('baba_yaga', 0) * 1
    )
    
    citizens_base_growth = int(c.get('citizens', 10000) * 0.01) + (c.get('settlements', 1) * 50)
    actual_growth = int(citizens_base_growth * mod_citizens)
    
    return {
        "prod_money": prod_money, "prod_materials": prod_materials,
        "prod_steel": prod_steel, "prod_electronics": prod_electronics,
        "prod_oil": prod_oil, "prod_food": prod_food,
        "cons_food": cons_food, "cons_oil": cons_oil,
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
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Экономика: Тик 3 минуты прошел!")
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

class TradeState(StatesGroup):
    waiting_give_amt = State()
    waiting_take_amt = State()

class FeedbackState(StatesGroup):
    waiting_message = State()

class AdminFeedbackState(StatesGroup):
    replying_to = State()
    
class DeleteCountryState(StatesGroup):
    confirm = State()

# ========================================================================
# КЛАВИАТУРЫ ИГРОКА
# ========================================================================
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Моя Страна", callback_data="menu_profile"),
         InlineKeyboardButton(text="⚔️ Война", callback_data="menu_war")],
        [InlineKeyboardButton(text="🏭 Экономика", callback_data="menu_economy"),
         InlineKeyboardButton(text="🪖 Военкомат", callback_data="menu_army")],
        [InlineKeyboardButton(text="🤝 Альянс", callback_data="menu_alliance"),
         InlineKeyboardButton(text="📜 Политика и Законы", callback_data="menu_laws")],
        [InlineKeyboardButton(text="✉️ Связь с админами", callback_data="menu_feedback")]
    ])

def economy_build_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏭 Завод (5k$, 500 Мат.)", callback_data="build_factory"),
         InlineKeyboardButton(text="🛢 Вышка (8k$, 1k Мат.)", callback_data="build_rig")],
        [InlineKeyboardButton(text="🌾 Ферма (3k$, 200 Мат.)", callback_data="build_farm"),
         InlineKeyboardButton(text="🌉 Мост (2k$, 800 Мат.)", callback_data="build_bridge")],
        [InlineKeyboardButton(text="⚙️ Сталелитейный (10k$, 2k Мат.)", callback_data="build_steelmill")],
        [InlineKeyboardButton(text="💻 Тех. Фабрика (20k$, 3k Мат., 1k Ст.)", callback_data="build_techfac")],
        [InlineKeyboardButton(text="🏘 Основать Поселение (15k$, 2k Мат., 2k Еды)", callback_data="build_settlement")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def army_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 Наземные войска и ПВО", callback_data="menu_army_ground")],
        [InlineKeyboardButton(text="⚓️ Военно-морской флот", callback_data="menu_army_naval")],
        [InlineKeyboardButton(text="🛩 Воздушные силы", callback_data="menu_army_air")],
        [InlineKeyboardButton(text="🛸 Беспилотные Войска", callback_data="menu_army_drones")],
        [InlineKeyboardButton(text="◀️ Назад в штаб", callback_data="menu_main")]
    ])

def army_ground_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 10 Пехоты (100$)", callback_data="buy_infantry"),
         InlineKeyboardButton(text="🎯 1 Пулемёт (200$)", callback_data="buy_machineguns")],
        [InlineKeyboardButton(text="💥 1 Миномёт (400$)", callback_data="buy_mortars"),
         InlineKeyboardButton(text="💥 1 Артиллерия (800$)", callback_data="buy_artillery")],
        [InlineKeyboardButton(text="🚙 1 Авто (300$)", callback_data="buy_cars"),
         InlineKeyboardButton(text="🚙 1 Хаммер (600$)", callback_data="buy_hummers")],
        [InlineKeyboardButton(text="🚜 1 Воен.машина (1k$)", callback_data="buy_milcars"),
         InlineKeyboardButton(text="🚛 1 Грузовик (500$)", callback_data="buy_trucks")],
        [InlineKeyboardButton(text="🚜 1 Танк (2k$)", callback_data="buy_tanks"),
         InlineKeyboardButton(text="🛡 Бункер (3k$)", callback_data="buy_bunkers")],
        [InlineKeyboardButton(text="📡 1 Зенитка (1.5k$)", callback_data="buy_aaguns"),
         InlineKeyboardButton(text="🚀 1 ЗРК (5k$)", callback_data="buy_sams")],
        [InlineKeyboardButton(text="🕵️‍♂️ 1 Шпион (1k$)", callback_data="buy_spies")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def army_naval_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛶 Обычная лодка (800$)", callback_data="buy_boats"),
         InlineKeyboardButton(text="🚤 Корвет (1.5k$)", callback_data="buy_corvettes")],
        [InlineKeyboardButton(text="🌊 Подлодка (2.5k$)", callback_data="buy_submarines"),
         InlineKeyboardButton(text="🛥 Эсминец (3k$)", callback_data="buy_destroyers")],
        [InlineKeyboardButton(text="🛳 Крейсер (7k$)", callback_data="buy_cruisers"),
         InlineKeyboardButton(text="⛴ Линкор (15k$)", callback_data="buy_battleships")],
        [InlineKeyboardButton(text="🛩 Авианосец (30k$)", callback_data="buy_carriers")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def army_air_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✈️ Истребитель (5k$)", callback_data="buy_fighters")],
        [InlineKeyboardButton(text="🛩 Бомбардировщик (12k$)", callback_data="buy_bombers")],
        [InlineKeyboardButton(text="🚁 Боевой вертолет (4k$)", callback_data="buy_helicopters")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def army_drones_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛸 БПЛА-Разведчик (1k$)", callback_data="buy_uavs"),
         InlineKeyboardButton(text="🚀 Реактивный БПЛА (3k$)", callback_data="buy_jetuavs")],
        [InlineKeyboardButton(text="🦇 БПЛА: Баба Яга (2k$)", callback_data="buy_babayaga"),
         InlineKeyboardButton(text="🐝 ФПВ-Дрон (200$)", callback_data="buy_fpv")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def tactics_kb(target_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Блицкриг (Атака +30%, Риск)", callback_data=f"tactic_blitz_{target_id}")],
        [InlineKeyboardButton(text="🛡 Осада (Меньше потерь, Атака -10%)", callback_data=f"tactic_siege_{target_id}")],
        [InlineKeyboardButton(text="⚖️ Стандартный бой", callback_data=f"tactic_balance_{target_id}")],
        [InlineKeyboardButton(text="🕵️‍♂️ Разведка (1 Шпион)", callback_data=f"spy_{target_id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu_war")]
    ])

def war_targets_kb(targets):
    kb = []
    for t in targets:
        type_str = "👤" if t.get('owner_id') else "🤖"
        geo = ""
        if t.get('mountains', 0) > 0: geo += "⛰"
        if t.get('forests', 0) > 0: geo += "🌲"
        if t.get('deserts', 0) > 0: geo += "🏜"
        if t.get('rivers', 0) > 0: geo += "🏞"
        if t.get('seas', 0) > 0: geo += "🌊"
        kb.append([InlineKeyboardButton(text=f"{df(t.get('flag'))} {t.get('name')} {type_str} {geo}", callback_data=f"prepwar_{t.get('id')}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

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

def policy_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Изменить форму правления", callback_data="policy_gov")],
        [InlineKeyboardButton(text="🕊 Изменить религию", callback_data="policy_rel")],
        [InlineKeyboardButton(text="📜 Принять/Отменить Законы", callback_data="policy_laws")],
        [InlineKeyboardButton(text="🎨 Кастомизация (Название/Флаг)", callback_data="policy_custom")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu_main")]
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

# ========================================================================
# КЛАВИАТУРЫ АДМИН-ПАНЕЛИ
# ========================================================================
def admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Сообщения игроков", callback_data="adm_feedbacks")],
        [InlineKeyboardButton(text="💰 Выдать/Забрать Ресурсы", callback_data="adm_resources"),
         InlineKeyboardButton(text="🪖 Выдать Войска", callback_data="adm_troops")],
        [InlineKeyboardButton(text="🎲 Запустить Случайный Ивент", callback_data="adm_event")],
        [InlineKeyboardButton(text="🌍 Управление Стран.", callback_data="adm_countries"),
         InlineKeyboardButton(text="🤝 Альянсы", callback_data="adm_alliances")],
        [InlineKeyboardButton(text="📦 Бэкапы и Откаты БД", callback_data="adm_backups")],
        [InlineKeyboardButton(text="👮‍♂️ Администраторы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="menu_main")]
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

def profile_delete_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧨 Покинуть пост (Удалить страну)", callback_data="delete_self_warn")],
    ])

# ========================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (СИЛА АРМИИ)
# ========================================================================
def get_base_power(country):
    """Суммирует общую боевую мощь всех родов войск игрока."""
    c = country
    power = (c.get('infantry', 0) * 1) + \
            (c.get('machine_guns', 0) * 3) + \
            (c.get('mortars', 0) * 5) + \
            (c.get('cars', 0) * 2) + \
            (c.get('hummers', 0) * 5) + \
            (c.get('trucks', 0) * 4) + \
            (c.get('military_cars', 0) * 8) + \
            (c.get('artillery', 0) * 10) + \
            (c.get('tanks', 0) * 20) + \
            (c.get('aa_guns', 0) * 30) + \
            (c.get('sam_systems', 0) * 120) + \
            (c.get('fighters', 0) * 100) + \
            (c.get('bombers', 0) * 250) + \
            (c.get('helicopters', 0) * 80) + \
            (c.get('uavs', 0) * 20) + \
            (c.get('jet_uavs', 0) * 60) + \
            (c.get('baba_yaga', 0) * 40) + \
            (c.get('fpv_drones', 0) * 15) + \
            (c.get('boats', 0) * 5) + \
            (c.get('submarines', 0) * 40) + \
            (c.get('corvettes', 0) * 20) + \
            (c.get('destroyers', 0) * 50) + \
            (c.get('cruisers', 0) * 150) + \
            (c.get('battleships', 0) * 500) + \
            (c.get('carriers', 0) * 1000) + \
            (c.get('bunkers', 0) * 50)
    if 'ships' in c and c['ships'] > 0:
        power += c['ships'] * 50
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
# ТОРГОВЛЯ МЕЖДУ ИГРОКАМИ (/trade)
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
            "🤝 <b>Рынок и Торговля</b>\n\n"
            "Интерактивная система обмена ресурсами с другими игроками.\n"
            "Использование: <code>/trade [ID или @юзернейм]</code>\n"
            "<i>Пример:</i> <code>/trade @alex</code>"
        )
    
    target_str = args[1]
    sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not sender: return await message.answer("❌ У вас нет страны!")
    
    target_country = None
    if target_str.startswith("@"):
        target_username = target_str[1:]
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target_username,))
    elif target_str.isdigit():
        target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target_str),))
        
    if not target_country:
        return await message.answer("❌ Страна получателя не найдена.")
    if sender['id'] == target_country['id']:
        return await message.answer("❌ Нельзя торговать с самим собой.")

    t_id = str(uuid.uuid4())[:8]
    ACTIVE_TRADES[t_id] = {
        'sender_id': sender['owner_id'], 'receiver_id': target_country['owner_id'],
        'give_res': 'budget', 'give_amt': 0, 'take_res': 'materials', 'take_amt': 0,
        'target_name': f"{df(target_country.get('flag'))} {target_country.get('name')}"
    }
    
    await message.answer(
        f"🛠 <b>Конструктор Сделки</b> с {ACTIVE_TRADES[t_id]['target_name']}\n\nНастройте ресурсы и количество:",
        reply_markup=trade_builder_kb(t_id, ACTIVE_TRADES[t_id])
    )

@dp.callback_query(F.data.startswith("tr_cycle"))
async def tr_cycle_res(callback: types.CallbackQuery):
    try:
        action, t_id = callback.data.split("_")[1], callback.data.split("_")[2]
        if t_id not in ACTIVE_TRADES: return await callback.answer("Сделка устарела.", show_alert=True)
        
        res_list = list(RES_MAP.keys())
        field = 'give_res' if action == 'cyclegive' else 'take_res'
        
        cur_idx = res_list.index(ACTIVE_TRADES[t_id][field])
        ACTIVE_TRADES[t_id][field] = res_list[(cur_idx + 1) % len(res_list)]
        
        await callback.message.edit_reply_markup(reply_markup=trade_builder_kb(t_id, ACTIVE_TRADES[t_id]))
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("❌ Ошибка смены ресурса!", show_alert=True)

@dp.callback_query(F.data.startswith("tr_set"))
async def tr_set_amt(callback: types.CallbackQuery, state: FSMContext):
    try:
        action, t_id = callback.data.split("_")[1], callback.data.split("_")[2]
        if t_id not in ACTIVE_TRADES: return await callback.answer("Сделка устарела.", show_alert=True)
        
        await state.update_data(current_trade_id=t_id, trade_msg_id=callback.message.message_id)
        if action == 'setgive':
            await callback.message.answer("Введите количество ресурса, которое вы ОТДАЕТЕ:")
            await state.set_state(TradeState.waiting_give_amt)
        else:
            await callback.message.answer("Введите количество ресурса, которое вы ХОТИТЕ ПОЛУЧИТЬ:")
            await state.set_state(TradeState.waiting_take_amt)
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("❌ Ошибка ввода количества!", show_alert=True)

@dp.message(TradeState.waiting_give_amt)
@dp.message(TradeState.waiting_take_amt)
async def tr_process_amt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_id = data.get('current_trade_id')
    if t_id not in ACTIVE_TRADES: 
        await state.clear()
        return await message.answer("Сделка была отменена или устарела.")
        
    try: 
        amt = int(message.text)
    except ValueError: 
        return await message.answer("Пожалуйста, введите целое число.")
    
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
    try:
        t_id = callback.data.split("_")[2]
        if t_id in ACTIVE_TRADES: 
            del ACTIVE_TRADES[t_id]
        await safe_edit(callback.message, "Сделка отменена.")
        await callback.answer("Сделка отменена.")
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка отмены.", show_alert=True)

@dp.callback_query(F.data.startswith("tr_send_"))
async def tr_send_offer(callback: types.CallbackQuery):
    try:
        t_id = callback.data.split("_")[2]
        trade = ACTIVE_TRADES.get(t_id)
        if not trade: 
            return await callback.answer("Сделка устарела.", show_alert=True)
        
        sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (trade['sender_id'],))
        if sender.get(trade['give_res'], 0) < trade['give_amt']:
            return await callback.answer("У вас нет такого количества ресурсов для отдачи!", show_alert=True)
            
        await safe_edit(callback.message, f"⏳ Предложение отправлено {trade['target_name']}. Ожидаем ответа...")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять сделку", callback_data=f"tr_accept_{t_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tr_decline_{t_id}")]
        ])
        try:
            await bot.send_message(
                trade['receiver_id'], 
                f"🤝 <b>Входящее торговое предложение!</b>\nОт: {df(sender.get('flag'))} {sender.get('name')}\n\n"
                f"📦 <b>Он предлагает:</b> {trade['give_amt']} {RES_MAP[trade['give_res']]}\n"
                f"🛒 <b>Он просит взамен:</b> {trade['take_amt']} {RES_MAP[trade['take_res']]}",
                reply_markup=kb
            )
        except:
            await callback.message.answer("Игрок заблокировал бота, сделка невозможна.")
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка при отправке предложения.", show_alert=True)

@dp.callback_query(F.data.startswith("tr_accept_"))
async def tr_accept(callback: types.CallbackQuery):
    try:
        t_id = callback.data.split("_")[2]
        trade = ACTIVE_TRADES.get(t_id)
        if not trade: 
            return await callback.answer("Сделка больше не действительна.", show_alert=True)
        
        if callback.from_user.id != trade['receiver_id']: 
            return await callback.answer("Это не для вас!", show_alert=True)
        
        sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (trade['sender_id'],))
        receiver = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (trade['receiver_id'],))
        
        if sender.get(trade['give_res'], 0) < trade['give_amt']:
            return await callback.answer("У отправителя больше нет этого ресурса!", show_alert=True)
        if receiver.get(trade['take_res'], 0) < trade['take_amt']:
            return await callback.answer(f"У вас не хватает: {RES_MAP[trade['take_res']]}!", show_alert=True)
            
        await execute_db(f"UPDATE countries SET {trade['give_res']} = {trade['give_res']} - ? WHERE id = ?", (trade['give_amt'], sender['id']))
        await execute_db(f"UPDATE countries SET {trade['take_res']} = {trade['take_res']} + ? WHERE id = ?", (trade['take_amt'], sender['id']))
        
        await execute_db(f"UPDATE countries SET {trade['give_res']} = {trade['give_res']} + ? WHERE id = ?", (trade['give_amt'], receiver['id']))
        await execute_db(f"UPDATE countries SET {trade['take_res']} = {trade['take_res']} - ? WHERE id = ?", (trade['take_amt'], receiver['id']))
        
        await safe_edit(callback.message, "✅ Сделка успешно завершена! Ресурсы обменяны.")
        try: 
            await bot.send_message(trade['sender_id'], f"✅ Игрок {df(receiver.get('flag'))} {receiver.get('name')} принял вашу сделку! Обмен произведен.")
        except: 
            pass
        del ACTIVE_TRADES[t_id]
        await callback.answer("Сделка завершена!")
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка проведения сделки.", show_alert=True)

@dp.callback_query(F.data.startswith("tr_decline_"))
async def tr_decline(callback: types.CallbackQuery):
    try:
        t_id = callback.data.split("_")[2]
        trade = ACTIVE_TRADES.get(t_id)
        if trade:
            try: 
                await bot.send_message(trade['sender_id'], "❌ Ваше торговое предложение было отклонено.")
            except: 
                pass
            del ACTIVE_TRADES[t_id]
        await safe_edit(callback.message, "Сделка отклонена.")
        await callback.answer("Сделка отклонена.")
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка отклонения.", show_alert=True)

# ========================================================================
# СТАРТ И СОЗДАНИЕ/ВЫБОР СТРАНЫ
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
            "🌍 <b>Добро пожаловать в 'Войну Стран'!</b>\n\n"
            "В мире есть заброшенные, но развитые государства. Вы можете возглавить одно из них или начать с нуля:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        await message.answer("🌍 <b>Добро пожаловать!</b>\nПридумай <b>Название</b> для своей страны:")
        await state.set_state(CreateCountry.name)

@dp.callback_query(F.data == "start_create")
async def start_create_btn(callback: types.CallbackQuery, state: FSMContext):
    try:
        await safe_edit(callback.message, "Придумай <b>Название</b> для своей новой страны:")
        await state.set_state(CreateCountry.name)
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Произошла ошибка создания.", show_alert=True)

@dp.callback_query(F.data.startswith("claim_free_"))
async def claim_free_country(callback: types.CallbackQuery):
    try:
        c_id = int(callback.data.split("_")[2])
        country = await fetch_one("SELECT * FROM countries WHERE id = ? AND is_unclaimed = 1", (c_id,))
        
        if not country:
            return await callback.answer("Эта страна уже занята!", show_alert=True)
            
        await execute_db(
            "UPDATE countries SET owner_id = ?, username = ?, is_unclaimed = 0 WHERE id = ?",
            (callback.from_user.id, callback.from_user.username or "", c_id)
        )
        
        await safe_edit(callback.message, 
            f"🎉 Вы успешно возглавили государство <b>{df(country.get('flag'))} {country.get('name')}</b>!\n"
            f"Переходите в главное меню для управления.",
            reply_markup=main_menu_kb()
        )
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Не удалось занять страну.", show_alert=True)

@dp.message(CreateCountry.name)
async def process_country_name(message: types.Message, state: FSMContext):
    if len(message.text) > 30:
        return await message.answer("Слишком длинное! Максимум 30 символов:")
    await state.update_data(name=message.text)
    await message.answer("Отправь <b>Эмодзи</b> для иконки страны ИЛИ <b>Фотографию</b> (только 16:9 или 1920x1080):")
    await state.set_state(CreateCountry.flag)

@dp.message(CreateCountry.flag, F.text | F.photo)
async def process_country_flag(message: types.Message, state: FSMContext):
    if message.photo:
        photo = message.photo[-1]
        ratio = photo.width / photo.height
        if not (1.7 < ratio < 1.8) and not (photo.width == 1920 and photo.height == 1080):
            return await message.answer("❌ Фото должно быть в разрешении 1920x1080 или в соотношении сторон 16:9!\nОтправь другое фото или простой эмодзи:")
        flag = f"photo:{photo.file_id}"
    elif message.text:
        flag = message.text[:2] 
    else:
        return await message.answer("❌ Пожалуйста, отправь фото или эмодзи!")

    data = await state.get_data()
    rivers, seas = random.randint(0, 3), random.randint(0, 1)
    mountains, forests, deserts = random.randint(0, 2), random.randint(0, 3), random.randint(0, 1)
    
    await execute_db(
        "INSERT INTO countries (owner_id, username, name, flag, rivers, seas, mountains, forests, deserts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (message.from_user.id, message.from_user.username or "", data['name'], flag, rivers, seas, mountains, forests, deserts)
    )
    
    await message.answer(
        f"🎉 Страна <b>{df(flag)} {data['name']}</b> основана!\n\n"
        f"🏞 <b>Ландшафт:</b> Реки ({rivers}), Море ({'Есть' if seas else 'Нет'}), Горы ({mountains}), Леса ({forests}), Пустыни ({deserts})\n\n"
        f"<i>Не забудьте зайти в «Политика и Законы» и выбрать форму правления!</i>",
        reply_markup=main_menu_kb()
    )
    await state.clear()

# ========================================================================
# ХЭНДЛЕРЫ МЕНЮ И ПРОФИЛЯ
# ========================================================================
@dp.callback_query(F.data.startswith("menu_"))
async def process_menus(callback: types.CallbackQuery, state: FSMContext):
    try:
        if is_spam(callback.from_user.id): 
            return await callback.answer("⏳ Не так быстро!", show_alert=False)
            
        if state is not None:
            await state.clear()
            
        await update_username(callback.from_user.id, callback.from_user.username)
        action = callback.data.split("_", 1)[1]
        
        if action == "feedback":
            await safe_edit(callback.message, "✉️ <b>Обратная связь с Администрацией</b>\n\nОтправьте ваше сообщение текстом ИЛИ фотографию с подписью. Мы постараемся ответить как можно скорее!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]]))
            if state is not None:
                await state.set_state(FeedbackState.waiting_message)
            return await callback.answer()
            
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        
        if not country:
            return await callback.answer("У вас нет страны! Напишите /start", show_alert=True)

        if action == "profile":
            aly_text = "Нет"
            if country.get('alliance_id'):
                aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
                if aly: 
                    aly_text = f"{df(aly.get('flag'))} {aly.get('name')}"

            geo = f"🏞 Рек: {country.get('rivers', 0)} | 🌊 Море: {'Есть' if country.get('seas', 0) else 'Нет'} | ⛰ Гор: {country.get('mountains',0)} | 🌲 Лесов: {country.get('forests',0)} | 🏜 Пустынь: {country.get('deserts',0)}"
            
            gov_name = GOV_TYPES.get(country.get('gov_type'), {}).get('name', 'Не выбрано')
            active_laws_str = country.get('active_laws') or ''
            active = [l for l in active_laws_str.split(",") if l]
            laws_count = len(active)
            
            flag = country.get('flag') or "🏳️"
            photo_id = flag.split(":")[1] if flag.startswith("photo:") else None

            text = (
                f"🌍 <b>Страна:</b> {df(flag)} {country.get('name')} (Побед: {country.get('war_wins', 0)} 🏅)\n"
                f"🏛 <b>Правление:</b> {gov_name} | 🕊 <b>Религия:</b> {country.get('religion', 'Атеизм')}\n"
                f"👥 <b>Граждане:</b> {country.get('citizens', 10000):,}\n"
                f"🤝 <b>Альянс:</b> {aly_text}\n"
                f"🗺 <b>Ландшафт:</b> {geo}\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"💰 <b>Бюджет:</b> {country.get('budget', 0):,}$\n"
                f"🧱 <b>Мат:</b> {country.get('materials', 0):,} | ⚙️ <b>Сталь:</b> {country.get('steel',0):,} | 💻 <b>Электр.:</b> {country.get('electronics',0):,}\n"
                f"🛢 <b>Нефть:</b> {country.get('oil', 0):,} | 🥩 <b>Еда:</b> {country.get('food', 0):,}\n"
                f"📈 <b>Базовый ВВП:</b> {country.get('gdp', 100):,}$\n"
                f"🗺 <b>Территория:</b> {country.get('territory', 10):,} км²\n"
                f"🏘 <b>Поселения (Города):</b> {country.get('settlements', 1)}\n"
                f"📜 <b>Активных законов:</b> {laws_count}\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🏭 Заводы: {country.get('factories', 1)} | ⚙️ Сталелит.: {country.get('steel_mills',0)} | 💻 Тех.Фабрики: {country.get('tech_factories',0)}\n"
                f"🛢 Вышки: {country.get('oil_rigs', 1)} | 🌾 Фермы: {country.get('farms', 2)}\n"
                f"🌉 Понтонные мосты: {country.get('bridges', 0)}\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"⚔️ <b>Наземные:</b> {country.get('infantry', 0)} Пех. | {country.get('machine_guns', 0)} Пул. | {country.get('mortars', 0)} Мин.\n"
                f"🚙 <b>Техника:</b> {country.get('cars', 0)} Авто | {country.get('hummers', 0)} Хамм. | {country.get('military_cars', 0)} ВМ | {country.get('trucks', 0)} Груз | {country.get('tanks', 0)} Танков\n"
                f"💥 <b>Арт. и ПВО:</b> {country.get('artillery', 0)} Арт. | {country.get('aa_guns',0)} Зениток | {country.get('sam_systems',0)} ЗРК\n"
                f"🛩 <b>Авиация:</b> {country.get('fighters',0)} Истр. | {country.get('bombers',0)} Бомб. | {country.get('helicopters',0)} Верт.\n"
                f"🛸 <b>Дроны:</b> {country.get('uavs',0)} БПЛА | {country.get('jet_uavs',0)} Реак. | {country.get('baba_yaga',0)} Б.Яга | {country.get('fpv_drones',0)} ФПВ\n"
                f"⚓️ <b>Флот:</b> {country.get('boats', 0)} Лодок | {country.get('corvettes',0)} Корв. | {country.get('submarines',0)} Подл. | {country.get('destroyers', 0)} Эсм. | {country.get('cruisers', 0)} Крейс. | {country.get('battleships', 0)} Линк. | {country.get('carriers',0)} Авианос.\n"
                f"🛡 <b>Защита:</b> {country.get('bunkers', 0)} Бункеры | 🕵️‍♂️ Шпионы: {country.get('spies', 0)}"
            )
            
            p_kb = main_menu_kb().inline_keyboard.copy()
            p_kb.append([InlineKeyboardButton(text="🧨 Покинуть пост (Удалить страну)", callback_data="delete_self_warn")])
            
            await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=p_kb), photo_id=photo_id)
            await callback.answer("Данные о стране обновлены.")
            
        elif action == "main":
            await safe_edit(callback.message, "Штаб Главнокомандующего. Ожидаю приказов:", reply_markup=main_menu_kb())
            await callback.answer()
            
        elif action == "economy":
            rates = calc_economy_rates(country)
            net_money = rates['prod_money']
            net_materials = rates['prod_materials']
            net_steel = rates['prod_steel']
            net_electronics = rates['prod_electronics']
            net_food = rates['prod_food'] - rates['cons_food']
            net_oil = rates['prod_oil'] - rates['cons_oil']
            
            await safe_edit(callback.message, 
                f"🏭 <b>Министерство Экономики</b>\n"
                f"<i>Тик происходит каждые 3 минуты. На производство влияют Законы и Правление.</i>\n\n"
                f"<b>Склады и запасы:</b>\n"
                f"💵 Бюджет: {country.get('budget', 0):,}$\n"
                f"🧱 Материалы: {country.get('materials', 0):,}\n"
                f"⚙️ Сталь: {country.get('steel',0):,}\n"
                f"💻 Электроника: {country.get('electronics',0):,}\n"
                f"🛢 Нефть: {country.get('oil', 0):,}\n"
                f"🥩 Еда: {country.get('food', 0):,}\n\n"
                f"<b>Приток ресурсов (за 1 тик / 3 мин):</b>\n"
                f"💵 Бюджет: +{rates['prod_money']}/-0 (итог: +{net_money}$/тик)\n"
                f"🧱 Материалы: +{rates['prod_materials']}/-0 (итог: +{net_materials}/тик)\n"
                f"⚙️ Сталь: +{rates['prod_steel']}/-0 (итог: +{net_steel}/тик)\n"
                f"💻 Электроника: +{rates['prod_electronics']}/-0 (итог: +{net_electronics}/тик)\n"
                f"🛢 Нефть: +{rates['prod_oil']}/-{rates['cons_oil']} (итог: {net_oil}/тик)\n"
                f"🥩 Еда: +{rates['prod_food']}/-{rates['cons_food']} (итог: {net_food}/тик)\n",
                reply_markup=economy_build_kb()
            )
            await callback.answer("Экономический отчет составлен.")

        elif action == "army":
            await safe_edit(callback.message, 
                f"🪖 <b>Министерство Обороны</b>\n\nВыберите категорию войск:\n💵 Доступно: {country.get('budget', 0)}$ | 🧱 {country.get('materials', 0)} мат. | ⚙️ {country.get('steel',0)} стали | 💻 {country.get('electronics',0)} электр. | 🥩 {country.get('food', 0)} еды", 
                reply_markup=army_main_kb()
            )
            await callback.answer()

        elif action == "army_ground":
            await safe_edit(callback.message, "🪖 <b>Наземные войска, ПВО и укрепления:</b>", reply_markup=army_ground_kb())
            await callback.answer()

        elif action == "army_naval":
            await safe_edit(callback.message, "⚓️ <b>Военно-морские верфи:</b>", reply_markup=army_naval_kb())
            await callback.answer()

        elif action == "army_air":
            await safe_edit(callback.message, "🛩 <b>Военно-воздушные силы:</b>", reply_markup=army_air_kb())
            await callback.answer()

        elif action == "army_drones":
            await safe_edit(callback.message, "🛸 <b>Заводы Беспилотных Войск:</b>", reply_markup=army_drones_kb())
            await callback.answer()
            
        elif action == "laws":
            gov_name = GOV_TYPES.get(country.get('gov_type'), {}).get('name', 'Не выбрано')
            active_laws_str = country.get('active_laws') or ''
            active = [l for l in active_laws_str.split(",") if l]
            laws_text = "\n".join([f"🟢 {LAWS[l]['name']}" for l in active]) if active else "🔴 Нет активных законов"
            
            text = (
                f"📜 <b>Внутренняя Политика</b>\n\n"
                f"🏛 <b>Форма правления:</b> {gov_name}\n"
                f"🕊 <b>Религия:</b> {country.get('religion', 'Атеизм')}\n\n"
                f"<b>Активные законы:</b>\n{laws_text}\n\n"
                f"<i>Законы и форма правления изменяют экономические показатели страны во время каждого тика (3 мин).</i>"
            )
            await safe_edit(callback.message, text, reply_markup=policy_main_kb())
            await callback.answer()

        elif action == "alliance":
            if country.get('alliance_id', 0) == 0:
                top_alliances = await fetch_all("SELECT * FROM alliances LIMIT 5")
                await safe_edit(callback.message, "🤝 <b>Дипломатия Альянсов</b>\n\nВы не состоите в альянсе.", reply_markup=alliance_none_kb(top_alliances))
            else:
                aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
                members = await fetch_all("SELECT * FROM countries WHERE alliance_id = ?", (aly['id'],))
                total_power = sum(get_base_power(m) for m in members)
                
                text = f"🤝 <b>Альянс:</b> {df(aly.get('flag'))} {aly.get('name')}\n\n"
                text += f"Участников: {len(members)}\n"
                text += f"Суммарная мощь войск альянса: ⚔️ {total_power}\n\n<b>Список стран:</b>\n"
                for m in members:
                    role = "👑 Лидер" if m.get('owner_id') == aly.get('leader_id') else "👤 Участник"
                    text += f"- {df(m.get('flag'))} {m.get('name')} ({role})\n"
                    
                is_leader = (country.get('owner_id') == aly.get('leader_id'))
                await safe_edit(callback.message, text, reply_markup=alliance_member_kb(is_leader))
            await callback.answer()

        elif action == "war":
            targets = await fetch_all("SELECT * FROM countries WHERE id != ? AND is_unclaimed = 0 ORDER BY RANDOM() LIMIT 10", (country['id'],))
            if not targets:
                return await callback.answer("В мире пока нет других стран для атаки!", show_alert=True)
                
            await safe_edit(callback.message, 
                "⚔️ <b>Командование: Выбор цели</b>\n"
                "👤 Игроки | 🤖 NPC\n"
                "🏞 Реки | 🌊 Море | ⛰ Горы | 🌲 Леса | 🏜 Пустыни\n\n"
                "<i>Для атаки требуется 200 Еды и 100 Нефти на мобилизацию!</i>",
                reply_markup=war_targets_kb(targets)
            )
            await callback.answer("Штабные карты обновлены.")
    except Exception as e:
        logging.exception(e)
        await callback.answer("❌ Сбой в обработке меню. Пожалуйста, попробуйте еще раз.", show_alert=True)

# ========================================================================
# УДАЛЕНИЕ СТРАНЫ ПОЛЬЗОВАТЕЛЕМ
# ========================================================================
@dp.callback_query(F.data == "delete_self_warn")
async def process_delete_warn(callback: types.CallbackQuery, state: FSMContext):
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ ДА, НАВСЕГДА УДАЛИТЬ СТРАНУ", callback_data="delete_self_confirm")],
            [InlineKeyboardButton(text="◀️ ОТМЕНА", callback_data="menu_profile")]
        ])
        await safe_edit(callback.message, "🧨 <b>ВНИМАНИЕ!</b>\nВы собираетесь навсегда удалить свою страну.\nВсе ваши войска, ресурсы, здания и достижения будут уничтожены без возможности восстановления.\n\nВы уверены?", reply_markup=kb)
        if state is not None:
            await state.set_state(DeleteCountryState.confirm)
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Не удалось инициировать удаление.", show_alert=True)

@dp.callback_query(F.data == "delete_self_confirm")
async def process_delete_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        if country:
            aly = await fetch_one("SELECT * FROM alliances WHERE leader_id = ?", (callback.from_user.id,))
            if aly:
                await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly['id'],))
                await execute_db("DELETE FROM alliances WHERE id = ?", (aly['id'],))
                await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (aly['id'],))
                
            await execute_db("DELETE FROM countries WHERE id = ?", (country['id'],))
            
        if state is not None:
            await state.clear()
        await safe_edit(callback.message, "💥 <b>Ваша страна была полностью стёрта с лица Земли.</b>\n\nВы можете начать игру заново, написав /start.")
        await callback.answer("Страна удалена.", show_alert=True)
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка при удалении страны.", show_alert=True)

# ========================================================================
# ХЭНДЛЕРЫ: ОБРАТНАЯ СВЯЗЬ
# ========================================================================
@dp.message(FeedbackState.waiting_message, F.text | F.photo)
async def process_feedback_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or f"ID:{user_id}"
    
    photo_id = None
    text_content = ""
    
    if message.photo:
        photo_id = message.photo[-1].file_id
        text_content = message.caption or ""
    elif message.text:
        text_content = message.text
        
    await execute_db(
        "INSERT INTO feedbacks (user_id, username, text_content, photo_id) VALUES (?, ?, ?, ?)",
        (user_id, username, text_content, photo_id)
    )
    
    await message.answer("✅ <b>Ваше сообщение успешно отправлено администрации!</b>\nОжидайте ответа.", reply_markup=main_menu_kb())
    await state.clear()
    
    try:
        await bot.send_message(SUPER_ADMIN_ID, "✉️ <b>Новое сообщение от игрока!</b>\nПроверьте Админ-Панель.")
    except:
        pass

# ========================================================================
# ХЭНДЛЕРЫ: ПОЛИТИКА, ЗАКОНЫ И КАСТОМИЗАЦИЯ
# ========================================================================
@dp.callback_query(F.data.startswith("policy_"))
async def process_policy(callback: types.CallbackQuery):
    try:
        action = callback.data.split("_")[1]
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        if not country:
            return await callback.answer("Ошибка: Страна не найдена.", show_alert=True)
        
        if action == "gov":
            text = "🏛 <b>Выбор формы правления</b>\nПервый выбор бесплатный, последующие смены стоят <b>10,000$</b>.\n\n"
            for g_id, g_data in GOV_TYPES.items():
                text += f"<b>{g_data['name']}</b>: {g_data['desc']}\n"
            await safe_edit(callback.message, text, reply_markup=policy_gov_kb(country.get('gov_type')))
            
        elif action == "rel":
            text = "🕊 <b>Выбор религии</b>\nПервый выбор бесплатный (с Атеизма), смена стоит <b>5,000$</b>.\n"
            await safe_edit(callback.message, text, reply_markup=policy_rel_kb(country.get('religion')))
            
        elif action == "laws":
            text = "📜 <b>Управление законами</b>\nВключение или отмена бесплатны, но их эффекты постоянно влияют на экономику.\n\n"
            for l_id, l_data in LAWS.items():
                text += f"<b>{l_data['name']}</b>: {l_data['desc']}\n"
            await safe_edit(callback.message, text, reply_markup=policy_laws_kb(country.get('active_laws')))
            
        elif action == "custom":
            await safe_edit(callback.message, "🎨 <b>Кастомизация страны</b>\nЗдесь вы можете за деньги сменить название или флаг (эмодзи/картинку).", reply_markup=customization_kb())
            
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка полит-панели.", show_alert=True)

@dp.callback_query(F.data.startswith("setgov_"))
async def process_setgov(callback: types.CallbackQuery):
    try:
        g_id = callback.data.split("_", 1)[1]
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        
        if country.get('gov_type') == g_id:
            return await callback.answer("У вас уже установлена эта форма правления!", show_alert=True)
            
        cost = 0 if country.get('gov_type') == "Не выбрано" else 10000
        if country.get('budget', 0) < cost:
            return await callback.answer(f"❌ Недостаточно средств! Нужно {cost}$.", show_alert=True)
            
        await execute_db("UPDATE countries SET budget = budget - ?, gov_type = ? WHERE id = ?", (cost, g_id, country['id']))
        await callback.answer(f"✅ Форма правления изменена на {GOV_TYPES[g_id]['name']}!", show_alert=True)
        callback.data = "menu_laws"
        await process_menus(callback, None)
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка смены формы правления.", show_alert=True)

@dp.callback_query(F.data.startswith("setrel_"))
async def process_setrel(callback: types.CallbackQuery):
    try:
        r_id = callback.data.split("_", 1)[1]
        rel_name = RELIGIONS[r_id]['name']
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        
        if country.get('religion') == rel_name:
            return await callback.answer("У вас уже установлена эта религия!", show_alert=True)
            
        cost = 0 if country.get('religion') == "Атеизм" else 5000
        if country.get('budget', 0) < cost:
            return await callback.answer(f"❌ Недостаточно средств! Нужно {cost}$.", show_alert=True)
            
        await execute_db("UPDATE countries SET budget = budget - ?, religion = ? WHERE id = ?", (cost, rel_name, country['id']))
        await callback.answer(f"✅ Религия изменена на {rel_name}!", show_alert=True)
        callback.data = "menu_laws"
        await process_menus(callback, None)
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка смены религии.", show_alert=True)

@dp.callback_query(F.data.startswith("togglelaw_"))
async def process_togglelaw(callback: types.CallbackQuery):
    try:
        l_id = callback.data.split("_", 1)[1]
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        
        active_laws_str = country.get('active_laws') or ''
        active = [l for l in active_laws_str.split(",") if l]
        if l_id in active:
            active.remove(l_id)
            msg = f"🔴 Закон {LAWS[l_id]['name']} отменен!"
        else:
            active.append(l_id)
            msg = f"🟢 Закон {LAWS[l_id]['name']} принят!"
            
        new_laws = ",".join(active)
        await execute_db("UPDATE countries SET active_laws = ? WHERE id = ?", (new_laws, country['id']))
        await callback.answer(msg)
        
        text = "📜 <b>Управление законами</b>\nВключение или отмена бесплатны, но их эффекты постоянно влияют на экономику.\n\n"
        for l, l_data in LAWS.items():
            text += f"<b>{l_data['name']}</b>: {l_data['desc']}\n"
        await safe_edit(callback.message, text, reply_markup=policy_laws_kb(new_laws))
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка изменения законов.", show_alert=True)

@dp.callback_query(F.data == "custom_name")
async def process_custom_name(callback: types.CallbackQuery, state: FSMContext):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        if country.get('budget', 0) < 5000:
            return await callback.answer("❌ Недостаточно средств! Нужно 5,000$.", show_alert=True)
        await safe_edit(callback.message, "Введите <b>новое название</b> страны (снимется 5,000$):")
        await state.set_state(CustomizeState.new_name)
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка смены названия.", show_alert=True)

@dp.message(CustomizeState.new_name)
async def finish_custom_name(message: types.Message, state: FSMContext):
    new_name = message.text[:30]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if country.get('budget', 0) < 5000:
        await state.clear()
        return await message.answer("Не хватает денег для смены названия.")
        
    await execute_db("UPDATE countries SET budget = budget - 5000, name = ? WHERE id = ?", (new_name, country['id']))
    await message.answer(f"✅ Название страны успешно изменено на <b>{new_name}</b>!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data == "custom_flag")
async def process_custom_flag(callback: types.CallbackQuery, state: FSMContext):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        if country.get('budget', 0) < 3000:
            return await callback.answer("❌ Недостаточно средств! Нужно 3,000$.", show_alert=True)
        await safe_edit(callback.message, "Отправьте <b>новый эмодзи</b> или <b>фото 16:9</b> (снимется 3,000$):")
        await state.set_state(CustomizeState.new_flag)
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка изменения флага.", show_alert=True)

@dp.message(CustomizeState.new_flag, F.text | F.photo)
async def finish_custom_flag(message: types.Message, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if country.get('budget', 0) < 3000:
        await state.clear()
        return await message.answer("Не хватает денег для смены флага.")

    if message.photo:
        photo = message.photo[-1]
        flag = f"photo:{photo.file_id}"
    elif message.text:
        flag = message.text[:2] 
    else:
        return await message.answer("❌ Пожалуйста, отправь фото или эмодзи!")

    await execute_db("UPDATE countries SET budget = budget - 3000, flag = ? WHERE id = ?", (flag, country['id']))
    await message.answer(f"✅ Флаг страны успешно обновлен!", reply_markup=main_menu_kb())
    await state.clear()

# ========================================================================
# АЛЬЯНСЫ: ЗАЯВКИ И УПРАВЛЕНИЕ
# ========================================================================
@dp.callback_query(F.data.startswith("aly_join_"))
async def cmd_aly_join_req(callback: types.CallbackQuery):
    try:
        if is_spam(callback.from_user.id): return await callback.answer("⏳", show_alert=False)
        
        aly_id = int(callback.data.split("_")[2])
        exists = await fetch_one("SELECT id FROM alliance_requests WHERE user_id = ? AND alliance_id = ?", (callback.from_user.id, aly_id))
        if exists:
            return await callback.answer("Вы уже подали заявку в этот альянс!", show_alert=True)
            
        await execute_db("INSERT INTO alliance_requests (alliance_id, user_id) VALUES (?, ?)", (aly_id, callback.from_user.id))
        await callback.answer("✅ Заявка отправлена лидеру альянса!", show_alert=True)
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка вступления.", show_alert=True)

@dp.callback_query(F.data == "aly_reqs")
async def cmd_aly_reqs(callback: types.CallbackQuery):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        reqs = await fetch_all("SELECT * FROM alliance_requests WHERE alliance_id = ?", (country['alliance_id'],))
        
        if not reqs:
            return await callback.answer("Заявок на вступление пока нет.", show_alert=True)
            
        kb = []
        for r in reqs:
            user_c = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (r['user_id'],))
            if user_c:
                kb.append([InlineKeyboardButton(text=f"✅ Принять {df(user_c.get('flag'))} {user_c.get('name')}", callback_data=f"aly_acc_{r['id']}_{user_c['owner_id']}")])
                kb.append([InlineKeyboardButton(text=f"❌ Отклонить {df(user_c.get('flag'))} {user_c.get('name')}", callback_data=f"aly_rej_{r['id']}")])
                
        kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_alliance")])
        await safe_edit(callback.message, "📥 <b>Заявки на вступление:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка запроса списка заявок.", show_alert=True)

@dp.callback_query(F.data.startswith("aly_acc_"))
async def aly_accept(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        req_id, user_id = int(parts[2]), int(parts[3])
        
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        await execute_db("UPDATE countries SET alliance_id = ? WHERE owner_id = ?", (country['alliance_id'], user_id))
        await execute_db("DELETE FROM alliance_requests WHERE user_id = ?", (user_id,))
        
        await callback.answer("Игрок принят в альянс!", show_alert=True)
        await cmd_aly_reqs(callback)
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка одобрения заявки.", show_alert=True)

@dp.callback_query(F.data.startswith("aly_rej_"))
async def aly_reject(callback: types.CallbackQuery):
    try:
        req_id = int(callback.data.split("_")[2])
        await execute_db("DELETE FROM alliance_requests WHERE id = ?", (req_id,))
        await callback.answer("Заявка успешно отклонена.", show_alert=True)
        await cmd_aly_reqs(callback)
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка отклонения заявки.", show_alert=True)

@dp.callback_query(F.data == "aly_create")
async def cmd_aly_create(callback: types.CallbackQuery, state: FSMContext):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        if country.get('budget', 0) < 10000:
            return await callback.answer("Недостаточно средств! Нужно 10,000$", show_alert=True)
        await safe_edit(callback.message, "Введите <b>Название</b> вашего нового Альянса (до 30 символов):")
        await state.set_state(CreateAlliance.name)
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка создания альянса.", show_alert=True)

@dp.message(CreateAlliance.name)
async def aly_name_step(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text[:30])
    await message.answer("Теперь отправьте <b>Эмодзи</b> для Альянса:")
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
    
    await message.answer(f"✅ Альянс <b>{flag} {data['name']}</b> успешно создан!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data == "aly_leave")
async def cmd_aly_leave(callback: types.CallbackQuery):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        await execute_db("UPDATE countries SET alliance_id = 0 WHERE id = ?", (country['id'],))
        await callback.answer("Вы покинули Альянс.", show_alert=True)
        await safe_edit(callback.message, "Вы покинули Альянс.", reply_markup=main_menu_kb())
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка выхода из альянса.", show_alert=True)

@dp.callback_query(F.data == "aly_disband")
async def cmd_aly_disband(callback: types.CallbackQuery):
    try:
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        aly_id = country.get('alliance_id', 0)
        await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly_id,))
        await execute_db("DELETE FROM alliances WHERE id = ?", (aly_id,))
        await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (aly_id,))
        await callback.answer("Альянс распущен!", show_alert=True)
        await safe_edit(callback.message, "Ваш Альянс был навсегда распущен.", reply_markup=main_menu_kb())
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка роспуска.", show_alert=True)

# ========================================================================
# ХЭНДЛЕРЫ: СТРОИТЕЛЬСТВО И ПОКУПКА
# ========================================================================
@dp.callback_query(F.data.startswith("build_"))
async def process_economy_build(callback: types.CallbackQuery):
    try:
        if is_spam(callback.from_user.id): return await callback.answer("⏳ Подождите...")
        
        item = callback.data.split("_")[1]
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        
        if item == "settlement":
            if country.get('budget', 0) < 15000 or country.get('materials', 0) < 2000 or country.get('food', 0) < 2000:
                return await callback.answer("❌ Нужно 15000$, 2000 Мат., 2000 Еды.", show_alert=True)
            await execute_db(
                "UPDATE countries SET budget = budget - 15000, materials = materials - 2000, food = food - 2000, settlements = settlements + 1, gdp = gdp + 200 WHERE id = ?", 
                (country['id'],)
            )
            await callback.answer("✅ Основано новое Поселение!", show_alert=True)
        else:
            costs = {
                "factory": {"money": 5000, "mat": 500, "steel": 0, "elec": 0, "db": "factories", "name": "Завод"},
                "rig": {"money": 8000, "mat": 1000, "steel": 100, "elec": 0, "db": "oil_rigs", "name": "Нефтевышка"},
                "farm": {"money": 3000, "mat": 200, "steel": 0, "elec": 0, "db": "farms", "name": "Ферма"},
                "bridge": {"money": 2000, "mat": 800, "steel": 50, "elec": 0, "db": "bridges", "name": "Понтонный мост"},
                "steelmill": {"money": 10000, "mat": 2000, "steel": 0, "elec": 0, "db": "steel_mills", "name": "Сталелитейный завод"},
                "techfac": {"money": 20000, "mat": 3000, "steel": 1000, "elec": 0, "db": "tech_factories", "name": "Фабрика электроники"}
            }
            req = costs[item]
            
            if country.get('budget', 0) < req["money"] or country.get('materials', 0) < req["mat"] or country.get('steel',0) < req['steel'] or country.get('electronics',0) < req['elec']:
                return await callback.answer(f"❌ Недостаточно ресурсов для постройки!", show_alert=True)
                
            await execute_db(
                f"UPDATE countries SET budget = budget - ?, materials = materials - ?, steel = steel - ?, electronics = electronics - ?, {req['db']} = {req['db']} + 1 WHERE id = ?",
                (req["money"], req["mat"], req["steel"], req["elec"], country['id'])
            )
            await callback.answer(f"✅ Успешно построено: {req['name']}!", show_alert=True)
        
        new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
        text = (
            f"🏭 <b>Министерство Экономики</b>\n"
            f"💵 Бюджет: {new_country.get('budget', 0):,}$ | 🧱 Матер.: {new_country.get('materials', 0):,} | ⚙️ Сталь: {new_country.get('steel',0):,}\n"
            f"💻 Электр.: {new_country.get('electronics',0):,} | 🥩 Еда: {new_country.get('food', 0):,}\n"
            f"🏘 Поселения: {new_country.get('settlements', 1)}\n"
            f"🏭 Заводы: {new_country.get('factories', 1)} | ⚙️ Сталелит.: {new_country.get('steel_mills',0)} | 💻 Тех.Фабрики: {new_country.get('tech_factories',0)}\n"
            f"🛢 Вышки: {new_country.get('oil_rigs', 1)} | 🌾 Фермы: {new_country.get('farms', 2)}\n"
            f"🌉 Мосты: {new_country.get('bridges', 0)}"
        )
        await safe_edit(callback.message, text, reply_markup=economy_build_kb())
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка при строительстве.", show_alert=True)

@dp.callback_query(F.data.startswith("buy_"))
async def process_army_buy(callback: types.CallbackQuery):
    try:
        if is_spam(callback.from_user.id): return await callback.answer("⏳ Не закупайте так быстро!")
        
        item = callback.data.split("_")[1]
        country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        
        costs = {
            "infantry": {"money": 100, "food": 50, "materials": 0, "amount": 10, "name": "Пехоты"},
            "machineguns": {"money": 200, "food": 50, "materials": 50, "steel": 10, "amount": 1, "name": "Пулемёт", "db": "machine_guns"},
            "mortars": {"money": 400, "food": 50, "materials": 150, "steel": 50, "amount": 1, "name": "Миномёт", "db": "mortars"},
            "cars": {"money": 300, "food": 0, "materials": 100, "steel": 50, "amount": 1, "name": "Авто"},
            "hummers": {"money": 600, "food": 0, "materials": 200, "steel": 100, "amount": 1, "name": "Хаммер", "db": "hummers"},
            "milcars": {"money": 1000, "food": 0, "materials": 400, "steel": 200, "amount": 1, "name": "Воен.машина", "db": "military_cars"},
            "trucks": {"money": 500, "food": 0, "materials": 200, "steel": 100, "amount": 1, "name": "Грузовик"},
            "tanks": {"money": 2000, "food": 0, "materials": 1000, "steel": 500, "amount": 1, "name": "Танк"},
            "artillery": {"money": 800, "food": 0, "materials": 300, "steel": 200, "amount": 1, "name": "Артиллерия"},
            "aaguns": {"money": 1500, "food": 0, "materials": 500, "steel": 300, "amount": 1, "name": "Зенитка", "db": "aa_guns"},
            "sams": {"money": 5000, "food": 0, "materials": 1500, "steel": 800, "electronics": 300, "amount": 1, "name": "ЗРК", "db": "sam_systems"},
            
            "boats": {"money": 800, "food": 0, "materials": 200, "steel": 50, "amount": 1, "name": "Лодка", "db": "boats"},
            "destroyers": {"money": 3000, "food": 0, "materials": 1000, "steel": 800, "electronics": 100, "amount": 1, "name": "Эсминец"},
            "cruisers": {"money": 7000, "food": 0, "materials": 2500, "steel": 2000, "electronics": 300, "amount": 1, "name": "Крейсер"},
            "battleships": {"money": 15000, "food": 0, "materials": 5000, "steel": 4000, "electronics": 500, "amount": 1, "name": "Линкор"},
            "submarines": {"money": 2500, "food": 0, "materials": 1000, "steel": 1000, "electronics": 200, "amount": 1, "name": "Подлодка"},
            "corvettes": {"money": 1500, "food": 0, "materials": 500, "steel": 400, "amount": 1, "name": "Корвет"},
            "carriers": {"money": 30000, "food": 0, "materials": 10000, "steel": 8000, "electronics": 2000, "amount": 1, "name": "Авианосец"},
            
            "fighters": {"money": 5000, "food": 0, "materials": 1000, "steel": 500, "electronics": 200, "amount": 1, "name": "Истребитель", "db": "fighters"},
            "bombers": {"money": 12000, "food": 0, "materials": 2000, "steel": 1000, "electronics": 400, "amount": 1, "name": "Бомбардировщик", "db": "bombers"},
            "helicopters": {"money": 4000, "food": 0, "materials": 800, "steel": 300, "electronics": 100, "amount": 1, "name": "Вертолет", "db": "helicopters"},
            
            "uavs": {"money": 1000, "food": 0, "materials": 200, "steel": 50, "electronics": 150, "amount": 1, "name": "БПЛА", "db": "uavs"},
            "jetuavs": {"money": 3000, "food": 0, "materials": 500, "steel": 200, "electronics": 400, "amount": 1, "name": "Реак.БПЛА", "db": "jet_uavs"},
            "babayaga": {"money": 2000, "food": 0, "materials": 300, "steel": 100, "electronics": 250, "amount": 1, "name": "Баба Яга", "db": "baba_yaga"},
            "fpv": {"money": 200, "food": 0, "materials": 50, "steel": 10, "electronics": 30, "amount": 1, "name": "ФПВ-Дрон", "db": "fpv_drones"},
            
            "bunkers": {"money": 3000, "food": 0, "materials": 1500, "steel": 500, "amount": 1, "name": "Бункер"},
            "spies": {"money": 1000, "food": 0, "materials": 0, "amount": 1, "name": "Шпион"}
        }
        
        if item not in costs: return await callback.answer("Ошибка товара.", show_alert=True)
        req = costs[item]
        db_field = req.get("db", item)
        req_steel = req.get("steel", 0)
        req_elec = req.get("electronics", 0)
        
        if country.get('budget', 0) < req["money"] or country.get('food', 0) < req["food"] or country.get('materials', 0) < req["materials"] or country.get('steel',0) < req_steel or country.get('electronics',0) < req_elec:
            return await callback.answer(f"❌ Не хватает ресурсов (Бюджет, Еда, Мат, Сталь или Электр.)!", show_alert=True)
            
        await execute_db(
            f"UPDATE countries SET budget = budget - ?, food = food - ?, materials = materials - ?, steel = steel - ?, electronics = electronics - ?, {db_field} = {db_field} + ? WHERE id = ?",
            (req["money"], req["food"], req["materials"], req_steel, req_elec, req["amount"], country['id'])
        )
        await callback.answer(f"✅ Успешно куплено: {req['amount']} {req['name']}!", show_alert=False)
        
        if item in ["boats", "destroyers", "cruisers", "battleships", "submarines", "corvettes", "carriers"]:
            await safe_edit(callback.message, "⚓️ <b>Военно-морские верфи:</b>", reply_markup=army_naval_kb())
        elif item in ["fighters", "bombers", "helicopters"]:
            await safe_edit(callback.message, "🛩 <b>Военно-воздушные силы:</b>", reply_markup=army_air_kb())
        elif item in ["uavs", "jetuavs", "babayaga", "fpv"]:
            await safe_edit(callback.message, "🛸 <b>Заводы Беспилотных Войск:</b>", reply_markup=army_drones_kb())
        else:
            await safe_edit(callback.message, "🪖 <b>Наземные войска и укрепления:</b>", reply_markup=army_ground_kb())
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка приобретения отрядов.", show_alert=True)

# ========================================================================
# ХЭНДЛЕРЫ: БОЕВАЯ СИСТЕМА
# ========================================================================
@dp.callback_query(F.data.startswith("prepwar_"))
async def process_prepwar(callback: types.CallbackQuery):
    try:
        if is_spam(callback.from_user.id): return await callback.answer("⏳")
        target_id = int(callback.data.split("_")[1])
        defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
        
        geo_info = "\n<b>Ландшафт врага:</b>\n"
        if defender.get('mountains', 0) > 0:
            geo_info += f"⛰ Горы. Значительно повышает защиту врага.\n"
        if defender.get('forests', 0) > 0:
            geo_info += f"🌲 Леса. Усложняет наступление (штраф к атаке).\n"
        if defender.get('deserts', 0) > 0:
            geo_info += f"🏜 Пустыни. Открытая местность.\n"
        if defender.get('rivers', 0) > 0:
            geo_info += f"🏞 Реки ({defender.get('rivers')}). Нужны понтонные мосты.\n"
        if defender.get('seas', 0) > 0:
            geo_info += f"🌊 Море. Без кораблей штраф -50%!\n"

        await safe_edit(callback.message, 
            f"⚔️ <b>Подготовка к вторжению в {df(defender.get('flag'))} {defender.get('name')}</b>\n{geo_info}\n",
            reply_markup=tactics_kb(target_id)
        )
        await callback.answer()
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка планирования атаки.", show_alert=True)

@dp.callback_query(F.data.startswith("spy_"))
async def process_spy(callback: types.CallbackQuery):
    try:
        cd = get_attack_cooldown(callback.from_user.id)
        if cd > 0:
            return await callback.answer(f"⏳ Шпионы еще в пути! Доступно через {cd} сек.", show_alert=True)
            
        target_id = int(callback.data.split("_")[1])
        attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
        
        if attacker.get('spies', 0) < 1:
            return await callback.answer("Нет шпионов!", show_alert=True)
            
        await execute_db("UPDATE countries SET spies = spies - 1 WHERE id = ?", (attacker['id'],))
        set_attack_cooldown(callback.from_user.id)
        
        if random.random() < 0.2:
            await callback.answer("Операция провалена!", show_alert=True)
            return await safe_edit(callback.message, "💥 <b>Провал операции!</b>\nШпион раскрыт.", reply_markup=tactics_kb(target_id))
            
        def_power_est = get_base_power(defender)
        text = (
            f"🕵️‍♂️ <b>Секретный рапорт по {df(defender.get('flag'))} {defender.get('name')}</b>:\n\n"
            f"💰 Бюджет: ~{defender.get('budget', 0)}$ | 🛢 Нефть: {defender.get('oil', 0)}\n"
            f"🪖 Наземные: {defender.get('infantry', 0)} пех, {defender.get('tanks', 0)} танков\n"
            f"⛴ Флот: {defender.get('destroyers', 0)} Эсм. | {defender.get('cruisers', 0)} Крейс. | {defender.get('battleships', 0)} Линкор.\n"
            f"🛩 Авиация и Дроны присутствуют.\n"
            f"🛡 Укрепления: {defender.get('bunkers', 0)} бункеров | {defender.get('sam_systems',0)} ЗРК\n\n"
            f"📊 Оценочная базовая мощь: <b>{def_power_est}</b>\n"
        )
        await safe_edit(callback.message, text, reply_markup=tactics_kb(target_id))
        await callback.answer("Шпионский рапорт готов!")
    except Exception as e:
        logging.exception(e)
        await callback.answer("Ошибка внедрения шпионов.", show_alert=True)

@dp.callback_query(F.data.startswith("tactic_"))
async def process_attack(callback: types.CallbackQuery):
    try:
        cd = get_attack_cooldown(callback.from_user.id)
        if cd > 0:
            return await callback.answer(f"⏳ Войска на перегруппировке! Атака доступна через {cd} сек.", show_alert=True)

        parts = callback.data.split("_")
        tactic, target_id = parts[1], int(parts[2])
        
        attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
        defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
        
        if not attacker or not defender: 
            return await callback.answer("Ошибка данных.", show_alert=True)
        if attacker['id'] == defender['id']: 
            return await callback.answer("Нельзя напасть на себя!", show_alert=True)
        
        if attacker.get('food', 0) < 200 or attacker.get('oil', 0) < 100:
            return await callback.answer("❌ Для мобилизации армии нужно 200 Еды и 100 Нефти!", show_alert=True)
            
        await execute_db("UPDATE countries SET food = food - 200, oil = oil - 100 WHERE id = ?", (attacker['id'],))
        set_attack_cooldown(callback.from_user.id)
        
        await safe_edit(callback.message, "🚀 <b>Войска пересекают границу...</b>\n\n🛰 Идет оценка обстановки...")
        await asyncio.sleep(2)

        att_base = get_base_power(attacker)
        def_base = get_base_power(defender)
        
        att_rates = calc_economy_rates(attacker)
        def_rates = calc_economy_rates(defender)
        
        att_ally_support, att_ally_count = await get_alliance_support(attacker.get('alliance_id'), attacker['id'])
        def_ally_support, def_ally_count = await get_alliance_support(defender.get('alliance_id'), defender['id'])

        report = [f"<blockquote>🌍 <b>БОЕВОЙ РАПОРТ: {df(attacker.get('flag'))} против {df(defender.get('flag'))}</b></blockquote>\n"]
        
        if att_ally_count > 0: 
            report.append(f"🤝 Ваш Альянс помог! (+{att_ally_support} мощи)")
        if def_ally_count > 0: 
            report.append(f"⚠️ Альянс врага защищает его! (+{def_ally_support} мощи)")

        att_total = att_base + att_ally_support
        
        # Ландшафтные модификаторы
        if defender.get('mountains', 0) > 0:
            def_base = int(def_base * 1.15)
            report.append("⛰ Враг занял оборону в горах! Защита +15%.")
        if defender.get('forests', 0) > 0:
            att_total = int(att_total * 0.90)
            report.append("🌲 Густые леса замедляют ваше наступление! Атака -10%.")
            
        bridges_used = 0
        if defender.get('rivers', 0) > 0:
            if attacker.get('bridges', 0) >= defender.get('rivers', 0):
                bridges_used = defender['rivers']
                report.append(f"🌉 Использовано {bridges_used} понтонных мостов.")
            else:
                att_total = int(att_total * 0.70)
                report.append(f"🏞 <b>Катастрофа на переправе!</b> Штраф атаки: -30%!")
                
        if defender.get('seas', 0) > 0:
            has_navy = (attacker.get('destroyers', 0) > 0 or attacker.get('cruisers', 0) > 0 or attacker.get('battleships', 0) > 0 or attacker.get('carriers', 0) > 0 or attacker.get('submarines', 0) > 0)
            if has_navy:
                report.append(f"⛴ Ваш флот успешно прикрыл десант и подавил береговую оборону врага!")
            else:
                att_total = int(att_total * 0.50)
                report.append(f"🌊 <b>Смертельный десант!</b> У вас нет флота. Штраф атаки: -50%!")

        def_total = def_base + def_ally_support
        
        att_total = int(att_total * att_rates['att_mod'])
        def_total = int(def_total * def_rates['def_mod'])
        
        att_mult = 1.0 + (min(attacker.get('war_wins', 0), 50) * 0.01)
        att_casualty_rate, def_casualty_rate = 0.5, 0.4
        
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
            stolen_money = int(defender.get('budget', 0) * random.uniform(0.2, 0.4))
            stolen_materials = int(defender.get('materials', 0) * random.uniform(0.2, 0.4))
            stolen_steel = int(defender.get('steel', 0) * random.uniform(0.2, 0.4))
            stolen_electronics = int(defender.get('electronics', 0) * random.uniform(0.2, 0.4))
            stolen_oil = int(defender.get('oil', 0) * random.uniform(0.2, 0.4))
            stolen_territory = random.randint(1, 3)
            
            att_inf_lost = int(attacker.get('infantry', 0) * 0.15)
            att_tanks_lost = int(attacker.get('tanks', 0) * 0.10)
            
            def_inf_lost = int(defender.get('infantry', 0) * def_casualty_rate)
            def_tanks_lost = int(defender.get('tanks', 0) * (def_casualty_rate / 2))
            
            await execute_db("""
                UPDATE countries 
                SET budget = budget + ?, materials = materials + ?, steel = steel + ?, electronics = electronics + ?, oil = oil + ?,
                    territory = territory + ?, war_wins = war_wins + 1,
                    infantry = MAX(0, infantry - ?), tanks = MAX(0, tanks - ?),
                    bridges = bridges - ? WHERE id = ?
            """, (stolen_money, stolen_materials, stolen_steel, stolen_electronics, stolen_oil, stolen_territory, att_inf_lost, att_tanks_lost, bridges_used, attacker['id']))
            
            await execute_db("""
                UPDATE countries 
                SET budget = MAX(0, budget - ?), materials = MAX(0, materials - ?), steel = MAX(0, steel - ?), electronics = MAX(0, electronics - ?), oil = MAX(0, oil - ?),
                    territory = MAX(1, territory - ?), gdp = MAX(10, gdp - ?),
                    infantry = MAX(0, infantry - ?), tanks = MAX(0, tanks - ?), bunkers = MAX(0, bunkers - 1)
                WHERE id = ?
            """, (stolen_money, stolen_materials, stolen_steel, stolen_electronics, stolen_oil, stolen_territory, stolen_territory * 5, 
                  def_inf_lost, def_tanks_lost, defender['id']))
            
            report.append("🎉 <b>ПОБЕДА! Оборона противника прорвана!</b>")
            report.append("<b>━━━━━━━━━━━━━━━━━━━━</b>")
            report.append(f"💰 <b>Трофеи:</b> {stolen_money}$, {stolen_materials} Мат., {stolen_steel} Стали, {stolen_oil} Нефти")
            report.append(f"🗺 <b>Аннексия:</b> {stolen_territory} км² (+{stolen_territory*5} к ВВП)")
            report.append(f"🩸 <b>Наши потери:</b> {att_inf_lost} Пехоты, {att_tanks_lost} Танков")
            report.append(f"💥 <b>Урон врагу:</b> {def_inf_lost} Пехоты, {def_tanks_lost} Танков")
        else:
            att_inf_lost = int(attacker.get('infantry', 0) * att_casualty_rate)
            att_cars_lost = int(attacker.get('cars', 0) * att_casualty_rate)
            att_tanks_lost = int(attacker.get('tanks', 0) * att_casualty_rate)
            
            def_inf_lost = int(defender.get('infantry', 0) * (def_casualty_rate / 2))
            
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
        logging.exception("Error during battle simulation")
        await safe_edit(
            callback.message, 
            f"❌ <b>Критическая ошибка симуляции боя:</b>\n<code>{e}</code>\n\nСообщите разработчику для исправления.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В штаб", callback_data="menu_war")]])
        )
        await callback.answer()

# ========================================================================
# ХЭНДЛЕРЫ: АДМИН ПАНЕЛЬ
# ========================================================================
@dp.message(Command("announce"))
async def cmd_announce(message: types.Message):
    if not await is_admin(message.from_user.id): return
    text = message.text.replace("/announce", "").strip()
    
    if not text:
        return await message.answer("ℹ️ <b>Использование:</b> <code>/announce Текст сообщения</code>\n\nРассылает сообщение всем активным игрокам.")
        
    users = await fetch_all("SELECT DISTINCT owner_id FROM countries WHERE owner_id IS NOT NULL")
    count = 0
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} игроков...")
    
    for u in users:
        try:
            await bot.send_message(u['owner_id'], f"📢 <b>Объявление от Администрации:</b>\n\n{text}")
            count += 1
            await asyncio.sleep(0.05)
        except:
            pass
            
    await message.answer(f"✅ Успешно разослано {count} активным игрокам.")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return await message.answer("У вас нет доступа к этой команде.")
    await state.clear()
    await message.answer("🔧 <b>Главная Панель Администратора</b>\n\nВыберите раздел для управления сервером:", reply_markup=admin_main_kb())

@dp.callback_query(F.data.startswith("adm_"))
async def adm_menus(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
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
        await safe_edit(callback.message, "Введите ID или @username игрока, которому нужно выдать <b>РЕСУРСЫ</b>:")
        await state.set_state(AdminState.give_target)
    elif act == "troops":
        await safe_edit(callback.message, "Введите ID или @username игрока, которому нужно выдать <b>ВОЙСКА</b>:")
        await state.set_state(AdminTroopState.give_target)
    elif act == "feedbacks":
        await process_admin_feedbacks(callback)
    
    if act != "feedbacks":
        await callback.answer()

# === Админская Обратная Связь ===
async def process_admin_feedbacks(callback: types.CallbackQuery):
    fb = await fetch_one("SELECT * FROM feedbacks WHERE is_answered = 0 ORDER BY id ASC LIMIT 1")
    if not fb:
        await safe_edit(callback.message, "✅ <b>Нет новых сообщений.</b>\nВы ответили на все тикеты.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]]))
        return await callback.answer()
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ответить пользователю", callback_data=f"fb_reply_{fb['id']}")],
        [InlineKeyboardButton(text="⏭ Отметить как прочитанное (Скип)", callback_data=f"fb_skip_{fb['id']}")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="adm_main")]
    ])
    
    text = f"📨 <b>Новое сообщение (#{fb['id']})</b>\nОт: <code>{fb['username']}</code> (ID: {fb['user_id']})\n\n<b>Текст:</b> {fb['text_content']}"
    
    if fb['photo_id']:
        await safe_edit(callback.message, text, reply_markup=kb, photo_id=fb['photo_id'])
    else:
        await safe_edit(callback.message, text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("fb_skip_"))
async def adm_fb_skip(callback: types.CallbackQuery):
    fb_id = int(callback.data.split("_")[2])
    await execute_db("UPDATE feedbacks SET is_answered = 1 WHERE id = ?", (fb_id,))
    await process_admin_feedbacks(callback)

@dp.callback_query(F.data.startswith("fb_reply_"))
async def adm_fb_reply(callback: types.CallbackQuery, state: FSMContext):
    fb_id = int(callback.data.split("_")[2])
    fb = await fetch_one("SELECT * FROM feedbacks WHERE id = ?", (fb_id,))
    if not fb: return await callback.answer("Ошибка: сообщение не найдено.", show_alert=True)
    
    await state.update_data(reply_to_user_id=fb['user_id'], fb_id=fb_id)
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("✏️ Введите ваш ответ (текст или фото). Он будет отправлен пользователю.")
    else:
        await safe_edit(callback.message, "✏️ Введите ваш ответ (текст или фото). Он будет отправлен пользователю.")
        
    await state.set_state(AdminFeedbackState.replying_to)
    await callback.answer()

@dp.message(AdminFeedbackState.replying_to, F.text | F.photo)
async def adm_send_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['reply_to_user_id']
    fb_id = data['fb_id']
    
    try:
        if message.photo:
            await bot.send_photo(user_id, photo=message.photo[-1].file_id, caption=f"👨‍💻 <b>Ответ Администратора:</b>\n\n{message.caption or ''}", parse_mode="HTML")
        else:
            await bot.send_message(user_id, f"👨‍💻 <b>Ответ Администратора:</b>\n\n{message.text}", parse_mode="HTML")
            
        await execute_db("UPDATE feedbacks SET is_answered = 1 WHERE id = ?", (fb_id,))
        await message.answer("✅ Ответ успешно отправлен пользователю!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Продолжить проверку ⏭", callback_data="adm_feedbacks")]]))
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки (Пользователь заблокировал бота?):\n{e}", reply_markup=admin_main_kb())
        await execute_db("UPDATE feedbacks SET is_answered = 1 WHERE id = ?", (fb_id,))
        
    await state.clear()

# === Админский редактор ресурсов ===
@dp.message(AdminState.give_target)
async def adm_res_target(message: types.Message, state: FSMContext):
    target = message.text
    if target.startswith("@"): 
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target[1:],))
    else: 
        try:
            target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target),))
        except ValueError:
            return await message.answer("❌ Введите корректный ID или @username.")
    
    if not target_country: return await message.answer("❌ Игрок не найден. Введите снова:")
    await state.update_data(res_target_id=target_country['id'])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Бюджет", callback_data="res_budget"), InlineKeyboardButton(text="🧱 Мат.", callback_data="res_materials")],
        [InlineKeyboardButton(text="⚙️ Сталь", callback_data="res_steel"), InlineKeyboardButton(text="💻 Электр.", callback_data="res_electronics")],
        [InlineKeyboardButton(text="🛢 Нефть", callback_data="res_oil"), InlineKeyboardButton(text="🥩 Еда", callback_data="res_food")],
    ])
    await message.answer(f"Выбрана страна: {df(target_country.get('flag'))} {target_country.get('name')}\nКакой ресурс изменить?", reply_markup=kb)
    await state.set_state(AdminState.give_type)

@dp.callback_query(AdminState.give_type, F.data.startswith("res_"))
async def adm_res_type(callback: types.CallbackQuery, state: FSMContext):
    res_type = callback.data.split("_")[1]
    await state.update_data(res_type=res_type)
    await safe_edit(callback.message, "Введите количество (например `1000` чтобы выдать, или `-500` чтобы забрать):")
    await state.set_state(AdminState.give_amount)
    await callback.answer()

@dp.message(AdminState.give_amount)
async def adm_res_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        c_id, r_type = data['res_target_id'], data['res_type']
        
        await execute_db(f"UPDATE countries SET {r_type} = MAX(0, {r_type} + ?) WHERE id = ?", (amount, c_id))
        await message.answer(f"✅ Ресурсы успешно обновлены!", reply_markup=admin_main_kb())
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число.")

# === Админский редактор войск ===
@dp.message(AdminTroopState.give_target)
async def adm_troop_target(message: types.Message, state: FSMContext):
    target = message.text
    if target.startswith("@"): 
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target[1:],))
    else: 
        try:
            target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target),))
        except ValueError:
            return await message.answer("❌ Введите корректный ID или @username.")
    
    if not target_country: return await message.answer("❌ Игрок не найден. Введите снова:")
    await state.update_data(res_target_id=target_country['id'])
    
    await message.answer(f"Выбрана страна: {df(target_country.get('flag'))} {target_country.get('name')}\nКакой вид войск изменить?", reply_markup=admin_troop_type_kb())
    await state.set_state(AdminTroopState.give_type)

@dp.callback_query(AdminTroopState.give_type, F.data.startswith("atr_"))
async def adm_troop_type(callback: types.CallbackQuery, state: FSMContext):
    troop_type = callback.data.split("_", 1)[1]
    await state.update_data(troop_type=troop_type)
    await safe_edit(callback.message, f"Тип войск: <b>{troop_type}</b>.\nВведите количество (например `100` выдать, `-50` забрать):")
    await state.set_state(AdminTroopState.give_amount)
    await callback.answer()

@dp.message(AdminTroopState.give_amount)
async def adm_troop_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        c_id, t_type = data['res_target_id'], data['troop_type']
        
        await execute_db(f"UPDATE countries SET {t_type} = MAX(0, {t_type} + ?) WHERE id = ?", (amount, c_id))
        await message.answer(f"✅ Войска успешно обновлены!", reply_markup=admin_main_kb())
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число.")

# === Бэкапы ===
@dp.callback_query(F.data == "admin_download_db")
async def admin_download_db(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    filename = f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.db"
    file = FSInputFile(DB_NAME, filename=filename)
    await bot.send_document(chat_id=callback.message.chat.id, document=file, caption="📦 Текущий бэкап мира.")
    await callback.answer()

@dp.callback_query(F.data == "admin_upload_db")
async def admin_upload_db_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await safe_edit(callback.message, 
        "⚠️ <b>ВНИМАНИЕ: ОТКАТ МИРА!</b>\n\n"
        "Загрузка нового файла <code>.db</code> <b>ПОЛНОСТЬЮ ОТКАТИТ ДАТУ ПОЛЬЗОВАТЕЛЕЙ</b> на момент сохранения!\n"
        "Отправь мне файл базы данных в этот чат:"
    )
    await state.set_state(AdminState.waiting_for_db)
    await callback.answer()

@dp.message(AdminState.waiting_for_db, F.document)
async def admin_upload_db_finish(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, DB_NAME)
    await message.answer("✅ <b>МИР УСПЕШНО ОТКАТИЛСЯ И ВОССТАНОВЛЕН ИЗ ФАЙЛА!</b>\nВсе данные пользователей сброшены на загруженные.", reply_markup=admin_main_kb())
    await state.clear()

# === Страны ===
@dp.callback_query(F.data == "admin_create_free")
async def admin_free_country(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    flag, name = "🏴‍☠️", f"Свободные Земли {random.randint(10,99)}"
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, settlements, infantry, cars, trucks, materials, oil, food, factories, oil_rigs, farms, citizens, is_unclaimed) 
           VALUES (?, ?, 10000, 100, 10, 1, 100, 5, 2, 1000, 500, 2000, 1, 1, 2, 10000, 1)""",
        (name, flag)
    )
    await callback.answer(f"✅ Свободная страна создана! Новички увидят её при старте.", show_alert=True)

@dp.callback_query(F.data == "admin_create_npc")
async def admin_npc_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await safe_edit(callback.message, "Введите название NPC-страны:")
    await state.set_state(AdminState.npc_name)
    await callback.answer()

@dp.message(AdminState.npc_name)
async def admin_npc_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отправьте эмодзи-флаг для NPC:")
    await state.set_state(AdminState.npc_flag)

@dp.message(AdminState.npc_flag)
async def admin_npc_flag(message: types.Message, state: FSMContext):
    flag = message.text[:2]
    data = await state.get_data()
    rivers, seas = random.randint(0, 3), random.randint(0, 1)
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, infantry, tanks, destroyers, bunkers, materials, oil, food, rivers, seas) 
           VALUES (?, ?, 15000, 500, 50, 1000, 25, 2, 5, 5000, 5000, 5000, ?, ?)""",
        (data['name'], flag, rivers, seas)
    )
    await message.answer(f"✅ NPC-страна <b>{flag} {data['name']}</b> добавлена на карту!")
    await state.clear()

@dp.callback_query(F.data == "admin_list_countries")
async def admin_list_countries(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    countries = await fetch_all("SELECT id, flag, name FROM countries")
    text = "📋 <b>Список Стран (ID):</b>\n\n"
    for c in countries: text += f"ID: <code>{c['id']}</code> | {df(c.get('flag'))} {c.get('name')}\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_countries")]]))
    await callback.answer()

@dp.callback_query(F.data == "admin_del_country")
async def admin_del_country_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await safe_edit(callback.message, "🗑 <b>Удаление Страны</b>\n\nОтправьте мне <b>ID страны</b> для её полного удаления с сервера (узнать ID можно в списке стран):")
    await state.set_state(AdminState.del_country)
    await callback.answer()

@dp.message(AdminState.del_country)
async def admin_del_country_finish(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        c_id = int(message.text)
        country = await fetch_one("SELECT * FROM countries WHERE id = ?", (c_id,))
        if not country:
            return await message.answer("❌ Страна с таким ID не найдена.")
        await execute_db("DELETE FROM countries WHERE id = ?", (c_id,))
        await message.answer(f"✅ Страна <b>{df(country.get('flag'))} {country.get('name')}</b> была стёрта с лица Земли!")
    except ValueError:
        await message.answer("❌ Пожалуйста, отправьте только число (ID).")
    await state.clear()

# === Альянсы ===
@dp.callback_query(F.data == "admin_list_alliances")
async def admin_list_all(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    alliances = await fetch_all("SELECT id, flag, name FROM alliances")
    if not alliances: return await callback.message.answer("Альянсов нет.")
    text = "📋 <b>Список Альянсов (ID):</b>\n\n"
    for a in alliances: text += f"ID: <code>{a['id']}</code> | {df(a.get('flag'))} {a.get('name')}\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_alliances")]]))
    await callback.answer()

@dp.callback_query(F.data == "admin_del_alliance")
async def admin_del_aly_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await safe_edit(callback.message, "🗑 <b>Удаление Альянса</b>\nОтправьте <b>ID альянса</b>:")
    await state.set_state(AdminState.del_alliance)
    await callback.answer()

@dp.message(AdminState.del_alliance)
async def admin_del_aly_finish(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        a_id = int(message.text)
        aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (a_id,))
        if not aly: return await message.answer("❌ Альянс не найден.")
        await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (a_id,))
        await execute_db("DELETE FROM alliances WHERE id = ?", (a_id,))
        await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (a_id,))
        await message.answer(f"✅ Альянс <b>{df(aly.get('flag'))} {aly.get('name')}</b> был принудительно распущен администрацией!")
    except ValueError:
        await message.answer("❌ Нужно число (ID).")
    await state.clear()

# === Админы ===
@dp.callback_query(F.data == "admin_list_admins")
async def admin_list_adm(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    admins = await fetch_all("SELECT user_id FROM admins")
    text = "👮‍♂️ <b>Администраторы:</b>\n"
    for a in admins: 
        role = " (Главный)" if a['user_id'] == SUPER_ADMIN_ID else ""
        text += f"- <code>{a['user_id']}</code>{role}\n"
    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_admins")]]))
    await callback.answer()

@dp.callback_query(F.data == "admin_add_admin")
async def admin_add_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await safe_edit(callback.message, "➕ <b>Назначение Админа</b>\nПришлите Telegram ID пользователя:")
    await state.set_state(AdminState.add_admin)
    await callback.answer()

@dp.message(AdminState.add_admin)
async def admin_add_finish(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        new_adm = int(message.text)
        await execute_db("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_adm,))
        await message.answer(f"✅ Пользователь <code>{new_adm}</code> назначен администратором!")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
    await state.clear()

@dp.callback_query(F.data == "admin_rem_admin")
async def admin_rem_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await safe_edit(callback.message, "➖ <b>Снятие Админа</b>\nПришлите Telegram ID пользователя:")
    await state.set_state(AdminState.rem_admin)
    await callback.answer()

@dp.message(AdminState.rem_admin)
async def admin_rem_finish(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        rem_adm = int(message.text)
        if rem_adm == SUPER_ADMIN_ID:
            return await message.answer("❌ Вы не можете снять Главного Администратора (Создателя)!")
        await execute_db("DELETE FROM admins WHERE user_id = ?", (rem_adm,))
        await message.answer(f"✅ Пользователь <code>{rem_adm}</code> больше не администратор.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
    await state.clear()

# ========================================================================
# ЗАПУСК БОТА
# ========================================================================
async def main():
    await init_db()
    asyncio.create_task(economy_tick())
    
    # Установка меню команд
    commands = [
        BotCommand(command="start", description="Главное меню / Старт"),
        BotCommand(command="trade", description="Торговля с игроком (/trade ID)"),
        BotCommand(command="admin", description="Админ-панель (только для админов)"),
        BotCommand(command="announce", description="Объявление (для админов)")
    ]
    await bot.set_my_commands(commands)
    
    logging.info("Бот запущен. Мир начал свое существование...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
