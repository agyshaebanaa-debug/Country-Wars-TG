import asyncio
import logging
import random
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
# ========================================================================
BOT_TOKEN = "8596473788:AAGrGjeH2Dq_PHJQdmnUcE8OV-xt6t1cEIs"
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
    now = time.time()
    if now - user_last_action.get(user_id, 0) < BUTTON_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def get_attack_cooldown(user_id: int) -> int:
    now = time.time()
    passed = now - user_attack_cooldown.get(user_id, 0)
    if passed < ATTACK_COOLDOWN:
        return int(ATTACK_COOLDOWN - passed)
    return 0

def set_attack_cooldown(user_id: int):
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
    except TelegramBadRequest:
        pass

def df(flag: str) -> str:
    """Отображает иконку картинки, если флаг - это фото, иначе сам эмодзи-флаг"""
    return "🖼" if flag.startswith("photo:") else flag

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
                alliance_id INTEGER DEFAULT 0
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
        
        # Миграция для обновления старых БД
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
            ("is_unclaimed", "INTEGER DEFAULT 0"), ("citizens", "INTEGER DEFAULT 10000")
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
    async with db.execute(query, params) as cursor:
        result = await cursor.fetchone()
    await db.close()
    return result

async def fetch_all(query, params=()):
    db = await get_db_connection()
    async with db.execute(query, params) as cursor:
        result = await cursor.fetchall()
    await db.close()
    return result

async def execute_db(query, params=()):
    db = await get_db_connection()
    await db.execute(query, params)
    await db.commit()
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
async def economy_tick():
    while True:
        await asyncio.sleep(180)
        db = await get_db_connection()
        try:
            async with db.execute("SELECT * FROM countries WHERE owner_id IS NOT NULL AND is_unclaimed = 0") as cursor:
                countries = await cursor.fetchall()
            
            for c in countries:
                prod_money = (c['settlements'] * 500) + c['gdp']
                prod_materials = c['factories'] * 150
                prod_oil = c['oil_rigs'] * 100
                prod_food = c['farms'] * 300
                
                cons_food = int(c['infantry'] * 1.5) + (c['spies'] * 5) + int(c['citizens'] * 0.05)
                cons_oil = int(c['cars'] * 0.5 + c['trucks'] * 1 + c['tanks'] * 2 + 
                               c['destroyers'] * 5 + c['cruisers'] * 10 + c['battleships'] * 20)
                
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
                
                new_citizens = max(0, c['citizens'] + int(c['citizens'] * 0.01) + (c['settlements'] * 50) - citizens_penalty)
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
         InlineKeyboardButton(text="📜 Законы", callback_data="menu_laws")]
    ])

def economy_build_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏭 Завод (5k$, 500 Мат.)", callback_data="build_factory"),
         InlineKeyboardButton(text="🛢 Вышка (8k$, 1k Мат.)", callback_data="build_rig")],
        [InlineKeyboardButton(text="🌾 Ферма (3k$, 200 Мат.)", callback_data="build_farm"),
         InlineKeyboardButton(text="🌉 Мост (2k$, 800 Мат.)", callback_data="build_bridge")],
        [InlineKeyboardButton(text="🏘 Основать Поселение (15k$, 2k Мат., 2k Еды)", callback_data="build_settlement")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def army_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 Наземные войска", callback_data="menu_army_ground")],
        [InlineKeyboardButton(text="⚓️ Военно-морской флот", callback_data="menu_army_naval")],
        [InlineKeyboardButton(text="✈️ Воздушные силы", callback_data="menu_army_air")],
        [InlineKeyboardButton(text="◀️ Назад в штаб", callback_data="menu_main")]
    ])

def army_ground_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 10 Пехоты (100$)", callback_data="buy_infantry"),
         InlineKeyboardButton(text="🚙 1 Авто (300$)", callback_data="buy_cars")],
        [InlineKeyboardButton(text="🚛 1 Груз. (500$)", callback_data="buy_trucks"),
         InlineKeyboardButton(text="🚜 1 Танк (2k$)", callback_data="buy_tanks")],
        [InlineKeyboardButton(text="🛡 Бункер (3k$)", callback_data="buy_bunkers"),
         InlineKeyboardButton(text="🕵️‍♂️ 1 Шпион (1k$)", callback_data="buy_spies")],
        [InlineKeyboardButton(text="◀️ Назад в Военкомат", callback_data="menu_army")]
    ])

def army_naval_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚤 Эсминец (3k$)", callback_data="buy_destroyers"),
         InlineKeyboardButton(text="🛳 Крейсер (7k$)", callback_data="buy_cruisers")],
        [InlineKeyboardButton(text="⛴ Линкор (15k$)", callback_data="buy_battleships")],
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
        type_str = "👤" if t['owner_id'] else "🤖"
        geo = ""
        if t['rivers'] > 0: geo += "🏞"
        if t['seas'] > 0: geo += "🌊"
        kb.append([InlineKeyboardButton(text=f"{df(t['flag'])} {t['name']} {type_str} {geo}", callback_data=f"prepwar_{t['id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def alliance_none_kb(alliances):
    kb = [[InlineKeyboardButton(text="➕ Создать Альянс (10,000$)", callback_data="aly_create")]]
    for aly in alliances:
        kb.append([InlineKeyboardButton(text=f"Подать заявку в {aly['flag']} {aly['name']}", callback_data=f"aly_join_{aly['id']}")])
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

# ========================================================================
# КЛАВИАТУРЫ АДМИН-ПАНЕЛИ
# ========================================================================
def admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Запустить Случайный Ивент", callback_data="adm_event")],
        [InlineKeyboardButton(text="💰 Выдать/Забрать Ресурсы", callback_data="adm_resources")],
        [InlineKeyboardButton(text="🌍 Управление Стран.", callback_data="adm_countries"),
         InlineKeyboardButton(text="🤝 Альянсы", callback_data="adm_alliances")],
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

# ========================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (СИЛА АРМИИ)
# ========================================================================
def get_base_power(country):
    power = (country['infantry'] * 1) + \
            (country['cars'] * 3) + \
            (country['trucks'] * 5) + \
            (country['tanks'] * 20) + \
            (country['destroyers'] * 50) + \
            (country['cruisers'] * 150) + \
            (country['battleships'] * 500) + \
            (country['bunkers'] * 50)
    if 'ships' in country and country['ships'] > 0:
        power += country['ships'] * 50
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
# ТОРГОВЛЯ МЕЖДУ ИГРОКАМИ (/send)
# ========================================================================
@dp.message(Command("send"))
async def cmd_send(message: types.Message):
    args = message.text.split()
    if len(args) != 4:
        return await message.answer(
            "📦 <b>Рынок и Торговля</b>\n\n"
            "Использование: <code>/send [ID или @юзернейм] [Ресурс] [Количество]</code>\n\n"
            "<b>Доступные ресурсы:</b> <code>budget</code> (деньги), <code>materials</code> (материалы), <code>oil</code> (нефть), <code>food</code> (еда)\n\n"
            "<i>Пример:</i> <code>/send @alex budget 5000</code>"
        )
    
    target_str, res_type, amount_str = args[1], args[2].lower(), args[3]
    valid_res = {"budget": "Бюджет", "materials": "Материалы", "oil": "Нефть", "food": "Еда"}
    
    if res_type not in valid_res:
        return await message.answer(f"❌ Неверный тип ресурса. Доступно: {', '.join(valid_res.keys())}")
        
    try:
        amount = int(amount_str)
        if amount <= 0: raise ValueError
    except ValueError:
        return await message.answer("❌ Количество должно быть положительным числом.")
        
    sender = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    if not sender: return await message.answer("❌ У вас нет страны!")
    
    if sender[res_type] < amount:
        return await message.answer(f"❌ Недостаточно ресурса {valid_res[res_type]}! У вас только {sender[res_type]}.")

    target_country = None
    if target_str.startswith("@"):
        target_username = target_str[1:]
        target_country = await fetch_one("SELECT * FROM countries WHERE username = ? COLLATE NOCASE AND owner_id IS NOT NULL", (target_username,))
    elif target_str.isdigit():
        target_country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (int(target_str),))
        
    if not target_country:
        return await message.answer("❌ Страна получателя не найдена. Убедитесь, что игрок запустил бота и создал страну.")
        
    if sender['id'] == target_country['id']:
        return await message.answer("❌ Нельзя отправить ресурсы самому себе.")

    await execute_db(f"UPDATE countries SET {res_type} = {res_type} - ? WHERE id = ?", (amount, sender['id']))
    await execute_db(f"UPDATE countries SET {res_type} = {res_type} + ? WHERE id = ?", (amount, target_country['id']))
    
    await message.answer(f"✅ Успешный перевод!\nОтправлено <b>{amount} {valid_res[res_type]}</b> в страну {df(target_country['flag'])} {target_country['name']}.")
    
    try:
        await bot.send_message(
            target_country['owner_id'], 
            f"📦 <b>Гуманитарная помощь!</b>\nСтрана {df(sender['flag'])} {sender['name']} перевела вам <b>{amount} {valid_res[res_type]}</b>."
        )
    except: pass

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
            f"С возвращением, Правитель!\nТвоя страна: <b>{df(country['flag'])} {country['name']}</b>", 
            reply_markup=main_menu_kb()
        )
        
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
async def start_create_btn(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit(callback.message, "Придумай <b>Название</b> для своей новой страны:")
    await state.set_state(CreateCountry.name)
    await callback.answer()

@dp.callback_query(F.data.startswith("claim_free_"))
async def claim_free_country(callback: types.CallbackQuery):
    c_id = int(callback.data.split("_")[2])
    country = await fetch_one("SELECT * FROM countries WHERE id = ? AND is_unclaimed = 1", (c_id,))
    
    if not country:
        return await callback.answer("Эта страна уже занята!", show_alert=True)
        
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
    
    await execute_db(
        "INSERT INTO countries (owner_id, username, name, flag, rivers, seas) VALUES (?, ?, ?, ?, ?, ?)",
        (message.from_user.id, message.from_user.username or "", data['name'], flag, rivers, seas)
    )
    
    await message.answer(
        f"🎉 Страна <b>{df(flag)} {data['name']}</b> основана!\n"
        f"Реки: {rivers}, Выход к морю: {'Да' if seas else 'Нет'}",
        reply_markup=main_menu_kb()
    )
    await state.clear()

# ========================================================================
# ХЭНДЛЕРЫ МЕНЮ
# ========================================================================
@dp.callback_query(F.data.startswith("menu_"))
async def process_menus(callback: types.CallbackQuery, state: FSMContext):
    if is_spam(callback.from_user.id): 
        return await callback.answer("⏳ Не так быстро!", show_alert=False)
        
    await state.clear()
    await update_username(callback.from_user.id, callback.from_user.username)
    
    action = callback.data.split("_", 1)[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if not country:
        return await callback.answer("У вас нет страны! Напишите /start", show_alert=True)

    if action == "profile":
        aly_text = "Нет"
        if country['alliance_id']:
            aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
            if aly: aly_text = f"{df(aly['flag'])} {aly['name']}"

        geo = f"🏞 Рек: {country['rivers']} | 🌊 Море: {'Есть' if country['seas'] else 'Нет'}"
        
        photo_id = country['flag'].split(":")[1] if country['flag'].startswith("photo:") else None

        text = (
            f"🌍 <b>Страна:</b> {df(country['flag'])} {country['name']} (Побед: {country['war_wins']} 🏅)\n"
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
            f"🌉 Понтонные мосты (для атак): {country['bridges']}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"⚔️ <b>Наземные:</b> {country['infantry']} Пех. | {country['cars']} Авто | {country['trucks']} Груз | {country['tanks']} Танков\n"
            f"⚓️ <b>Флот:</b> {country['destroyers']} Эсминцев | {country['cruisers']} Крейсеров | {country['battleships']} Линкоров\n"
            f"🛡 <b>Защита:</b> {country['bunkers']} Бункеры | 🕵️‍♂️ Шпионы: {country['spies']}"
        )
        await safe_edit(callback.message, text, reply_markup=main_menu_kb(), photo_id=photo_id)
        
    elif action == "main":
        await safe_edit(callback.message, "Штаб Главнокомандующего. Ожидаю приказов:", reply_markup=main_menu_kb())
        
    elif action == "economy":
        prod_money = (country['settlements'] * 500) + country['gdp']
        prod_materials = country['factories'] * 150
        prod_oil = country['oil_rigs'] * 100
        prod_food = country['farms'] * 300
        
        cons_food = int(country['infantry'] * 1.5) + (country['spies'] * 5) + int(country['citizens'] * 0.05)
        cons_oil = int(country['cars'] * 0.5 + country['trucks'] * 1 + country['tanks'] * 2 + 
                       country['destroyers'] * 5 + country['cruisers'] * 10 + country['battleships'] * 20)
        
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
        await safe_edit(callback.message, "🪖 <b>Наземные войска и укрепления:</b>", reply_markup=army_ground_kb())
    elif action == "army_naval":
        await safe_edit(callback.message, "⚓️ <b>Военно-морские верфи:</b>", reply_markup=army_naval_kb())
    elif action == "army_air":
        await callback.answer("✈️ Воздушные силы находятся в разработке! 🛠", show_alert=True)
        
    elif action == "laws":
        await callback.answer("Система законов находится в разработке! 🛠", show_alert=True)

    elif action == "alliance":
        if country['alliance_id'] == 0:
            top_alliances = await fetch_all("SELECT * FROM alliances LIMIT 5")
            await safe_edit(callback.message, "🤝 <b>Дипломатия Альянсов</b>\n\nВы не состоите в альянсе.", reply_markup=alliance_none_kb(top_alliances))
        else:
            aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
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
            return await callback.answer("В мире пока нет других стран для атаки!", show_alert=True)
            
        await safe_edit(callback.message, 
            "⚔️ <b>Командование: Выбор цели</b>\n"
            "👤 Игроки | 🤖 NPC | 🏞 Реки | 🌊 Море\n\n"
            "<i>Для атаки требуется 200 Еды и 100 Нефти на мобилизацию!</i>",
            reply_markup=war_targets_kb(targets)
        )
    await callback.answer()

# ========================================================================
# АЛЬЯНСЫ: ЗАЯВКИ И УПРАВЛЕНИЕ
# ========================================================================
@dp.callback_query(F.data.startswith("aly_join_"))
async def cmd_aly_join_req(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): return await callback.answer("⏳", show_alert=False)
    
    aly_id = int(callback.data.split("_")[2])
    exists = await fetch_one("SELECT id FROM alliance_requests WHERE user_id = ? AND alliance_id = ?", (callback.from_user.id, aly_id))
    if exists:
        return await callback.answer("Вы уже подали заявку в этот альянс!", show_alert=True)
        
    await execute_db("INSERT INTO alliance_requests (alliance_id, user_id) VALUES (?, ?)", (aly_id, callback.from_user.id))
    await callback.answer("✅ Заявка отправлена лидеру альянса!", show_alert=True)

@dp.callback_query(F.data == "aly_reqs")
async def cmd_aly_reqs(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    reqs = await fetch_all("SELECT * FROM alliance_requests WHERE alliance_id = ?", (country['alliance_id'],))
    
    if not reqs:
        return await callback.answer("Заявок на вступление пока нет.", show_alert=True)
        
    kb = []
    for r in reqs:
        user_c = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (r['user_id'],))
        if user_c:
            kb.append([InlineKeyboardButton(text=f"✅ Принять {df(user_c['flag'])} {user_c['name']}", callback_data=f"aly_acc_{r['id']}_{user_c['owner_id']}")])
            kb.append([InlineKeyboardButton(text=f"❌ Отклонить {df(user_c['flag'])} {user_c['name']}", callback_data=f"aly_rej_{r['id']}")])
            
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_alliance")])
    await safe_edit(callback.message, "📥 <b>Заявки на вступление:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("aly_acc_"))
async def aly_accept(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    req_id, user_id = int(parts[2]), int(parts[3])
    
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    await execute_db("UPDATE countries SET alliance_id = ? WHERE owner_id = ?", (country['alliance_id'], user_id))
    await execute_db("DELETE FROM alliance_requests WHERE user_id = ?", (user_id,))
    
    await callback.answer("Игрок принят в альянс!", show_alert=True)
    await cmd_aly_reqs(callback)

@dp.callback_query(F.data.startswith("aly_rej_"))
async def aly_reject(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[2])
    await execute_db("DELETE FROM alliance_requests WHERE id = ?", (req_id,))
    await callback.answer("Заявка успешно отклонена.", show_alert=True)
    await cmd_aly_reqs(callback)

# ========================================================================
# ХЭНДЛЕРЫ: СТРОИТЕЛЬСТВО И ПОКУПКА
# ========================================================================
@dp.callback_query(F.data.startswith("build_"))
async def process_economy_build(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): return await callback.answer("⏳ Подождите...")
    
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if item == "settlement":
        if country['budget'] < 15000 or country['materials'] < 2000 or country['food'] < 2000:
            return await callback.answer("❌ Нужно 15000$, 2000 Мат., 2000 Еды.", show_alert=True)
        await execute_db(
            "UPDATE countries SET budget = budget - 15000, materials = materials - 2000, food = food - 2000, settlements = settlements + 1, gdp = gdp + 200 WHERE id = ?", 
            (country['id'],)
        )
        await callback.answer("✅ Основано новое Поселение!", show_alert=True)
    else:
        costs = {
            "factory": (5000, 500, "factories", "Завод"),
            "rig": (8000, 1000, "oil_rigs", "Нефтевышка"),
            "farm": (3000, 200, "farms", "Ферма"),
            "bridge": (2000, 800, "bridges", "Понтонный мост")
        }
        price_money, price_mat, db_field, name = costs[item]
        
        if country['budget'] < price_money or country['materials'] < price_mat:
            return await callback.answer(f"❌ Нужно {price_money}$ и {price_mat} матер.", show_alert=True)
            
        await execute_db(
            f"UPDATE countries SET budget = budget - ?, materials = materials - ?, {db_field} = {db_field} + 1 WHERE id = ?",
            (price_money, price_mat, country['id'])
        )
        await callback.answer(f"✅ Успешно построено: {name}!", show_alert=True)
    
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    text = (
        f"🏭 <b>Министерство Экономики</b>\n"
        f"💵 Бюджет: {new_country['budget']:,}$ | 🧱 Матер.: {new_country['materials']:,} | 🥩 Еда: {new_country['food']:,}\n"
        f"🏘 Поселения: {new_country['settlements']}\n"
        f"🏭 Заводы: {new_country['factories']} | 🛢 Вышки: {new_country['oil_rigs']} | 🌾 Фермы: {new_country['farms']}\n"
        f"🌉 Мосты: {new_country['bridges']}"
    )
    await safe_edit(callback.message, text, reply_markup=economy_build_kb())

@dp.callback_query(F.data == "aly_create")
async def cmd_aly_create(callback: types.CallbackQuery, state: FSMContext):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    if country['budget'] < 10000:
        return await callback.answer("Недостаточно средств! Нужно 10,000$", show_alert=True)
    await safe_edit(callback.message, "Введите <b>Название</b> вашего нового Альянса (до 30 символов):")
    await state.set_state(CreateAlliance.name)

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
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE id = ?", (country['id'],))
    await callback.answer("Вы покинули Альянс.", show_alert=True)
    await safe_edit(callback.message, "Вы покинули Альянс.", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "aly_disband")
async def cmd_aly_disband(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    aly_id = country['alliance_id']
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly_id,))
    await execute_db("DELETE FROM alliances WHERE id = ?", (aly_id,))
    await execute_db("DELETE FROM alliance_requests WHERE alliance_id = ?", (aly_id,))
    await callback.answer("Альянс распущен!", show_alert=True)
    await safe_edit(callback.message, "Ваш Альянс был навсегда распущен.", reply_markup=main_menu_kb())

@dp.callback_query(F.data.startswith("buy_"))
async def process_army_buy(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): return await callback.answer("⏳ Не закупайте так быстро!")
    
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    # Обновленные и сниженные цены
    costs = {
        "infantry": {"money": 100, "food": 50, "materials": 0, "amount": 10, "name": "Пехоты"},
        "cars": {"money": 300, "food": 0, "materials": 100, "amount": 1, "name": "Авто"},
        "trucks": {"money": 500, "food": 0, "materials": 200, "amount": 1, "name": "Грузовик"},
        "tanks": {"money": 2000, "food": 0, "materials": 1000, "amount": 1, "name": "Танк"},
        "destroyers": {"money": 3000, "food": 0, "materials": 1000, "amount": 1, "name": "Эсминец"},
        "cruisers": {"money": 7000, "food": 0, "materials": 2500, "amount": 1, "name": "Крейсер"},
        "battleships": {"money": 15000, "food": 0, "materials": 5000, "amount": 1, "name": "Линкор"},
        "bunkers": {"money": 3000, "food": 0, "materials": 1500, "amount": 1, "name": "Бункер"},
        "spies": {"money": 1000, "food": 0, "materials": 0, "amount": 1, "name": "Шпион"}
    }
    req = costs[item]
    
    if country['budget'] < req["money"] or country['food'] < req["food"] or country['materials'] < req["materials"]:
        return await callback.answer(f"❌ Не хватает ресурсов!", show_alert=True)
        
    await execute_db(
        f"UPDATE countries SET budget = budget - ?, food = food - ?, materials = materials - ?, {item} = {item} + ? WHERE id = ?",
        (req["money"], req["food"], req["materials"], req["amount"], country['id'])
    )
    await callback.answer(f"✅ Успешно куплено: {req['amount']} {req['name']}!", show_alert=False)
    
    # Возвращаем пользователя в ту же клавиатуру, из которой он покупал
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    if item in ["destroyers", "cruisers", "battleships"]:
        await safe_edit(callback.message, "⚓️ <b>Военно-морские верфи:</b>", reply_markup=army_naval_kb())
    else:
        await safe_edit(callback.message, "🪖 <b>Наземные войска и укрепления:</b>", reply_markup=army_ground_kb())

# ========================================================================
# ХЭНДЛЕРЫ: БОЕВАЯ СИСТЕМА
# ========================================================================
@dp.callback_query(F.data.startswith("prepwar_"))
async def process_prepwar(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): return await callback.answer("⏳")
    target_id = int(callback.data.split("_")[1])
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
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
async def process_spy(callback: types.CallbackQuery):
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        return await callback.answer(f"⏳ Шпионы еще в пути! Доступно через {cd} сек.", show_alert=True)
        
    target_id = int(callback.data.split("_")[1])
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if attacker['spies'] < 1:
        return await callback.answer("Нет шпионов!", show_alert=True)
        
    await execute_db("UPDATE countries SET spies = spies - 1 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id)
    
    if random.random() < 0.2:
        await callback.answer("Операция провалена!", show_alert=True)
        return await safe_edit(callback.message, "💥 <b>Провал операции!</b>\nШпион раскрыт.", reply_markup=tactics_kb(target_id))
        
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
async def process_attack(callback: types.CallbackQuery):
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
    
    if attacker['food'] < 200 or attacker['oil'] < 100:
        return await callback.answer("❌ Для мобилизации армии нужно 200 Еды и 100 Нефти!", show_alert=True)
        
    await execute_db("UPDATE countries SET food = food - 200, oil = oil - 100 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id)
    
    await safe_edit(callback.message, "🚀 <b>Войска пересекают границу...</b>\n\n🛰 Идет оценка обстановки...")
    await asyncio.sleep(2)

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

        att_total = att_base + att_ally_support
        
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

        def_total = def_base + def_ally_support
        att_mult = 1.0 + (min(attacker['war_wins'], 50) * 0.01)
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
            stolen_money = int(defender['budget'] * random.uniform(0.2, 0.4))
            stolen_materials = int(defender['materials'] * random.uniform(0.2, 0.4))
            stolen_oil = int(defender['oil'] * random.uniform(0.2, 0.4))
            stolen_territory = random.randint(1, 3)
            
            att_inf_lost = int(attacker['infantry'] * 0.15)
            att_tanks_lost = int(attacker['tanks'] * 0.10)
            
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
        logging.exception("Error during battle simulation")
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
        await safe_edit(callback.message, "Введите ID или @username игрока, которому нужно изменить ресурсы:")
        await state.set_state(AdminState.give_target)
    
    await callback.answer()

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
        [InlineKeyboardButton(text="🛢 Нефть", callback_data="res_oil"), InlineKeyboardButton(text="🥩 Еда", callback_data="res_food")],
    ])
    await message.answer(f"Выбрана страна: {df(target_country['flag'])} {target_country['name']}\nКакой ресурс изменить?", reply_markup=kb)
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
    for c in countries: text += f"ID: <code>{c['id']}</code> | {df(c['flag'])} {c['name']}\n"
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
        await message.answer(f"✅ Страна <b>{df(country['flag'])} {country['name']}</b> была стёрта с лица Земли!")
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
    for a in alliances: text += f"ID: <code>{a['id']}</code> | {df(a['flag'])} {a['name']}\n"
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
        await message.answer(f"✅ Альянс <b>{df(aly['flag'])} {aly['name']}</b> был принудительно распущен администрацией!")
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
    
    logging.info("Бот запущен. Мир начал свое существование...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
