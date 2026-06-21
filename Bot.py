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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
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

# Настройки времени кулдаунов (в секундах)
BUTTON_COOLDOWN = 1.0  # Задержка между любыми нажатиями кнопок (от кликеров)
ATTACK_COOLDOWN = 300  # Задержка между атаками/шпионажем (5 минут)

def is_spam(user_id: int) -> bool:
    """Проверяет, спамит ли пользователь кнопками"""
    now = time.time()
    if now - user_last_action.get(user_id, 0) < BUTTON_COOLDOWN:
        return True
    user_last_action[user_id] = now
    return False

def get_attack_cooldown(user_id: int) -> int:
    """Возвращает оставшееся время до следующей атаки в секундах, или 0"""
    now = time.time()
    passed = now - user_attack_cooldown.get(user_id, 0)
    if passed < ATTACK_COOLDOWN:
        return int(ATTACK_COOLDOWN - passed)
    return 0

def set_attack_cooldown(user_id: int):
    """Обновляет таймер последней атаки"""
    user_attack_cooldown[user_id] = time.time()

# Безопасное редактирование сообщений (чтобы избежать ошибки "Message is not modified")
async def safe_edit(message: types.Message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        pass

# ========================================================================
# БАЗА ДАННЫХ И МИГРАЦИИ
# ========================================================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER UNIQUE,
                name TEXT,
                flag TEXT,
                budget INTEGER DEFAULT 10000,
                gdp INTEGER DEFAULT 100,
                territory INTEGER DEFAULT 10,
                settlements INTEGER DEFAULT 1,
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
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        
        new_columns = [
            ("bunkers", "INTEGER DEFAULT 0"), ("spies", "INTEGER DEFAULT 0"),
            ("war_wins", "INTEGER DEFAULT 0"), ("alliance_id", "INTEGER DEFAULT 0"),
            ("ships", "INTEGER DEFAULT 0"), ("destroyers", "INTEGER DEFAULT 0"),
            ("cruisers", "INTEGER DEFAULT 0"), ("battleships", "INTEGER DEFAULT 0"),
            ("materials", "INTEGER DEFAULT 1000"), ("oil", "INTEGER DEFAULT 500"), 
            ("food", "INTEGER DEFAULT 2000"), ("factories", "INTEGER DEFAULT 1"), 
            ("oil_rigs", "INTEGER DEFAULT 1"), ("farms", "INTEGER DEFAULT 2"), 
            ("bridges", "INTEGER DEFAULT 0"), ("rivers", "INTEGER DEFAULT 0"), 
            ("seas", "INTEGER DEFAULT 0")
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

# ========================================================================
# ФОНОВЫЕ ЗАДАЧИ (ПРОДВИНУТАЯ ЭКОНОМИКА)
# ========================================================================
async def economy_tick():
    while True:
        await asyncio.sleep(900) # 15 минут
        db = await get_db_connection()
        try:
            async with db.execute("SELECT * FROM countries") as cursor:
                countries = await cursor.fetchall()
            
            for c in countries:
                prod_money = (c['settlements'] * 500) + c['gdp']
                prod_materials = c['factories'] * 50
                prod_oil = c['oil_rigs'] * 20
                prod_food = c['farms'] * 100
                
                cons_food = int(c['infantry'] * 1.5) + (c['spies'] * 5)
                cons_oil = int(c['cars'] * 1 + c['trucks'] * 2 + c['tanks'] * 5 + 
                               c['destroyers'] * 10 + c['cruisers'] * 25 + c['battleships'] * 50)
                
                new_budget = c['budget'] + prod_money
                new_materials = c['materials'] + prod_materials
                
                new_food = c['food'] + prod_food - cons_food
                new_oil = c['oil'] + prod_oil - cons_oil
                
                infantry_penalty = 0
                vehicle_penalty = 0
                
                if new_food < 0:
                    infantry_penalty = abs(new_food) // 2 
                    new_food = 0
                if new_oil < 0:
                    vehicle_penalty = abs(new_oil) // 5 
                    new_oil = 0
                
                final_infantry = max(0, c['infantry'] - infantry_penalty)
                final_cars = max(0, c['cars'] - vehicle_penalty)
                final_tanks = max(0, c['tanks'] - (vehicle_penalty // 2))
                
                await db.execute("""
                    UPDATE countries 
                    SET budget = ?, materials = ?, food = ?, oil = ?,
                        infantry = ?, cars = ?, tanks = ?
                    WHERE id = ?
                """, (new_budget, new_materials, new_food, new_oil, 
                      final_infantry, final_cars, final_tanks, c['id']))
                
            await db.commit()
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Экономика: Тик 15 минут прошел! Ресурсы обновлены.")
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

def army_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 10 Пехоты (100$)", callback_data="buy_infantry"),
         InlineKeyboardButton(text="🚙 1 Авто (300$)", callback_data="buy_cars")],
        [InlineKeyboardButton(text="🚛 1 Груз. (500$)", callback_data="buy_trucks"),
         InlineKeyboardButton(text="🚜 1 Танк (2000$)", callback_data="buy_tanks")],
        [InlineKeyboardButton(text="🚤 Эсминец (5k$)", callback_data="buy_destroyers"),
         InlineKeyboardButton(text="🛳 Крейсер (15k$)", callback_data="buy_cruisers")],
        [InlineKeyboardButton(text="⛴ Линкор (40k$)", callback_data="buy_battleships"),
         InlineKeyboardButton(text="🛡 Бункер (3000$)", callback_data="buy_bunkers")],
        [InlineKeyboardButton(text="🕵️‍♂️ 1 Шпион (1000$)", callback_data="buy_spies"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
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
        kb.append([InlineKeyboardButton(text=f"{t['flag']} {t['name']} {type_str} {geo}", callback_data=f"prepwar_{t['id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def alliance_none_kb(alliances):
    kb = [[InlineKeyboardButton(text="➕ Создать Альянс (10,000$)", callback_data="aly_create")]]
    for aly in alliances:
        kb.append([InlineKeyboardButton(text=f"Вступить в {aly['flag']} {aly['name']}", callback_data=f"aly_join_{aly['id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def alliance_member_kb(is_leader):
    kb = []
    if is_leader:
        kb.append([InlineKeyboardButton(text="❌ Распустить Альянс", callback_data="aly_disband")])
    else:
        kb.append([InlineKeyboardButton(text="🚪 Покинуть Альянс", callback_data="aly_leave")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Бэкапы и Откаты", callback_data="adm_backups")],
        [InlineKeyboardButton(text="🌍 Управление Странами", callback_data="adm_countries")],
        [InlineKeyboardButton(text="🤝 Управление Альянсами", callback_data="adm_alliances")],
        [InlineKeyboardButton(text="👮‍♂️ Администраторы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="❌ Закрыть панель", callback_data="menu_main")]
    ])

def admin_backups_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать базу (Бэкап)", callback_data="admin_download_db")],
        [InlineKeyboardButton(text="📤 Загрузить базу (Откат)", callback_data="admin_upload_db")],
        [InlineKeyboardButton(text="◀️ В админ-меню", callback_data="adm_main")]
    ])

def admin_countries_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Создать NPC-страну", callback_data="admin_create_npc")],
        [InlineKeyboardButton(text="🗑 Удалить страну", callback_data="admin_del_country")],
        [InlineKeyboardButton(text="📋 Список стран (ID)", callback_data="admin_list_countries")],
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
# ХЭНДЛЕРЫ: СТАРТ И РЕГИСТРАЦИЯ СТРАНЫ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (message.from_user.id,))
    
    if country:
        await message.answer(
            f"С возвращением, Правитель!\nТвоя страна: <b>{country['flag']} {country['name']}</b>", 
            reply_markup=main_menu_kb()
        )
    else:
        await message.answer(
            "🌍 <b>Добро пожаловать в 'Войну Стран' (Advanced Edition)!</b>\n\n"
            "Тебе предстоит управлять экономикой, добывать ресурсы, форсировать реки и строить великую империю.\n\n"
            "Для начала, придумай <b>Название</b> для своей страны:"
        )
        await state.set_state(CreateCountry.name)

@dp.message(CreateCountry.name)
async def process_country_name(message: types.Message, state: FSMContext):
    if len(message.text) > 30:
        return await message.answer("Название слишком длинное! Максимум 30 символов. Попробуй еще раз:")
    
    await state.update_data(name=message.text)
    await message.answer("Отличное название! Теперь отправь <b>Эмодзи</b>, который будет флагом твоей страны:")
    await state.set_state(CreateCountry.flag)

@dp.message(CreateCountry.flag)
async def process_country_flag(message: types.Message, state: FSMContext):
    flag = message.text[:2] 
    data = await state.get_data()
    
    rivers = random.randint(0, 3)
    seas = random.randint(0, 1)
    
    await execute_db(
        "INSERT INTO countries (owner_id, name, flag, rivers, seas) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, data['name'], flag, rivers, seas)
    )
    
    geo_text = f"География региона: Реки ({rivers}), Выход к морю ({'Да' if seas else 'Нет'})"
    
    await message.answer(
        f"🎉 Ура! Страна <b>{flag} {data['name']}</b> успешно основана!\n\n"
        f"🗺 {geo_text}\n"
        f"Тебе выдано пособие и стартовые ресурсы. Развивай экономику, иначе войска начнут голодать!",
        reply_markup=main_menu_kb()
    )
    await state.clear()

# ========================================================================
# ХЭНДЛЕРЫ: МЕНЮ ИГРОКА
# ========================================================================
async def get_country_text(country):
    aly_text = "Нет"
    if country['alliance_id']:
        aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
        if aly: aly_text = f"{aly['flag']} {aly['name']}"

    geo = f"🏞 Рек: {country['rivers']} | 🌊 Море: {'Есть' if country['seas'] else 'Нет'}"

    return (
        f"🌍 <b>Страна:</b> {country['flag']} {country['name']} (Побед: {country['war_wins']} 🏅)\n"
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
        f"⚔️ <b>Армия и Флот:</b>\n"
        f"🪖 Пехота: {country['infantry']} | 🚙 Авто: {country['cars']} | 🚛 Груз: {country['trucks']}\n"
        f"🚜 Танки: {country['tanks']}\n"
        f"🚤 Эсминцы: {country['destroyers']} | 🛳 Крейсеры: {country['cruisers']} | ⛴ Линкоры: {country['battleships']}\n"
        f"🛡 Бункеры: {country['bunkers']} | 🕵️‍♂️ Шпионы: {country['spies']}"
    )

@dp.callback_query(F.data.startswith("menu_"))
async def process_menus(callback: types.CallbackQuery, state: FSMContext):
    if is_spam(callback.from_user.id): 
        return await callback.answer("⏳ Не так быстро!", show_alert=False)
        
    await state.clear()
    action = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if not country:
        return await callback.answer("У вас нет страны! Напишите /start", show_alert=True)

    if action == "profile":
        text = await get_country_text(country)
        await safe_edit(callback.message, text, reply_markup=main_menu_kb())
        
    elif action == "main":
        await safe_edit(callback.message, "Вы в главном штабе. Ждем указаний.", reply_markup=main_menu_kb())
        
    elif action == "economy":
        prod_money = (country['settlements'] * 500) + country['gdp']
        prod_materials = country['factories'] * 50
        prod_oil = country['oil_rigs'] * 20
        prod_food = country['farms'] * 100
        
        cons_food = int(country['infantry'] * 1.5) + (country['spies'] * 5)
        cons_oil = int(country['cars'] * 1 + country['trucks'] * 2 + country['tanks'] * 5 + 
                       country['destroyers'] * 10 + country['cruisers'] * 25 + country['battleships'] * 50)
        
        text = (
            f"🏭 <b>Министерство Экономики</b>\n"
            f"<i>Тик происходит каждые 15 минут</i>\n\n"
            f"<b>Ваши запасы:</b>\n"
            f"💵 Бюджет: {country['budget']:,}$\n"
            f"🧱 Материалы: {country['materials']:,}\n"
            f"🛢 Нефть: {country['oil']:,}\n"
            f"🥩 Еда: {country['food']:,}\n\n"
            f"<b>Прогноз на следующий тик:</b>\n"
            f"💵 Деньги: +{prod_money}$\n"
            f"🧱 Материалы: +{prod_materials}\n"
            f"🛢 Нефть: +{prod_oil} / -{cons_oil} (Итог: {prod_oil - cons_oil})\n"
            f"🥩 Еда: +{prod_food} / -{cons_food} (Итог: {prod_food - cons_food})\n\n"
            f"<i>⚠️ Новые поселения значительно увеличивают приток денег (+500$ и +200 ВВП).</i>"
        )
        await safe_edit(callback.message, text, reply_markup=economy_build_kb())

    elif action == "army":
        await safe_edit(callback.message, 
            f"🪖 <b>Военкомат и Верфи</b>\n\nДоступно:\n💵 {country['budget']}$ | 🧱 {country['materials']} мат. | 🥩 {country['food']} еды", 
            reply_markup=army_kb()
        )
        
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
            
            text = f"🤝 <b>Альянс:</b> {aly['flag']} {aly['name']}\n\n"
            text += f"Участников: {len(members)}\n"
            text += f"Суммарная мощь войск альянса: ⚔️ {total_power}\n\n<b>Список стран:</b>\n"
            for m in members:
                role = "👑 Лидер" if m['owner_id'] == aly['leader_id'] else "👤 Участник"
                text += f"- {m['flag']} {m['name']} ({role})\n"
                
            is_leader = (country['owner_id'] == aly['leader_id'])
            await safe_edit(callback.message, text, reply_markup=alliance_member_kb(is_leader))

    elif action == "war":
        targets = await fetch_all("SELECT * FROM countries WHERE id != ? LIMIT 10", (country['id'],))
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
# ХЭНДЛЕРЫ: СТРОИТЕЛЬСТВО, АЛЬЯНСЫ, ПОКУПКА
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
    await callback.message.edit_text("Введите <b>Название</b> вашего нового Альянса (до 30 символов):")
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

@dp.callback_query(F.data.startswith("aly_join_"))
async def cmd_aly_join(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): return await callback.answer("⏳ Подождите...")
    
    aly_id = int(callback.data.split("_")[2])
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    await execute_db("UPDATE countries SET alliance_id = ? WHERE id = ?", (aly_id, country['id']))
    
    await callback.answer("Вы успешно вступили в Альянс!", show_alert=True)
    await safe_edit(callback.message, "✅ Успешное вступление! Возврат в штаб...", reply_markup=main_menu_kb())

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
    await callback.answer("Альянс распущен!", show_alert=True)
    await safe_edit(callback.message, "Ваш Альянс был навсегда распущен.", reply_markup=main_menu_kb())

@dp.callback_query(F.data.startswith("buy_"))
async def process_army_buy(callback: types.CallbackQuery):
    if is_spam(callback.from_user.id): return await callback.answer("⏳ Не закупайте так быстро!")
    
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    costs = {
        "infantry": {"money": 100, "food": 50, "materials": 0, "amount": 10, "name": "Пехоты"},
        "cars": {"money": 300, "food": 0, "materials": 100, "amount": 1, "name": "Авто"},
        "trucks": {"money": 500, "food": 0, "materials": 200, "amount": 1, "name": "Грузовик"},
        "tanks": {"money": 2000, "food": 0, "materials": 1000, "amount": 1, "name": "Танк"},
        "destroyers": {"money": 5000, "food": 0, "materials": 2000, "amount": 1, "name": "Эсминец"},
        "cruisers": {"money": 15000, "food": 0, "materials": 5000, "amount": 1, "name": "Крейсер"},
        "battleships": {"money": 40000, "food": 0, "materials": 15000, "amount": 1, "name": "Линкор"},
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
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    await safe_edit(callback.message, 
        f"🪖 <b>Военкомат и Верфи</b>\nДоступно:\n💵 {new_country['budget']}$ | 🧱 {new_country['materials']} мат. | 🥩 {new_country['food']} еды", 
        reply_markup=army_kb()
    )

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
        f"⚔️ <b>Подготовка к вторжению в {defender['flag']} {defender['name']}</b>\n{geo_info}\n",
        reply_markup=tactics_kb(target_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("spy_"))
async def process_spy(callback: types.CallbackQuery):
    # ПРОВЕРКА КУЛДАУНА
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        return await callback.answer(f"⏳ Шпионы еще в пути! Доступно через {cd} сек.", show_alert=True)
        
    target_id = int(callback.data.split("_")[1])
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if attacker['spies'] < 1:
        return await callback.answer("Нет шпионов!", show_alert=True)
        
    await execute_db("UPDATE countries SET spies = spies - 1 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id) # Ставим таймер КД
    
    if random.random() < 0.2:
        await callback.answer("Операция провалена!", show_alert=True)
        return await safe_edit(callback.message, "💥 <b>Провал операции!</b>\nШпион раскрыт.", reply_markup=tactics_kb(target_id))
        
    def_power_est = get_base_power(defender)
    text = (
        f"🕵️‍♂️ <b>Секретный рапорт по {defender['flag']} {defender['name']}</b>:\n\n"
        f"💰 Бюджет: ~{defender['budget']}$ | 🛢 Нефть: {defender['oil']}\n"
        f"🪖 Наземные: {defender['infantry']} пехоты, {defender['tanks']} танков\n"
        f"⛴ Флот: {defender['destroyers']} Эсминцев | {defender['cruisers']} Крейсеров | {defender['battleships']} Линкоров\n"
        f"🛡 Укрепления: {defender['bunkers']} бункеров\n\n"
        f"📊 Оценочная базовая мощь: <b>{def_power_est}</b>\n"
    )
    await safe_edit(callback.message, text, reply_markup=tactics_kb(target_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("tactic_"))
async def process_attack(callback: types.CallbackQuery):
    # ПРОВЕРКА КУЛДАУНА
    cd = get_attack_cooldown(callback.from_user.id)
    if cd > 0:
        return await callback.answer(f"⏳ Войска на перегруппировке! Атака доступна через {cd} сек.", show_alert=True)

    parts = callback.data.split("_")
    tactic, target_id = parts[1], int(parts[2])
    
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if not attacker or not defender: return await callback.answer("Ошибка данных.", show_alert=True)
    if attacker['id'] == defender['id']: return await callback.answer("Нельзя напасть на себя!", show_alert=True)
    
    if attacker['food'] < 200 or attacker['oil'] < 100:
        return await callback.answer("❌ Для мобилизации армии нужно 200 Еды и 100 Нефти!", show_alert=True)
        
    await execute_db("UPDATE countries SET food = food - 200, oil = oil - 100 WHERE id = ?", (attacker['id'],))
    set_attack_cooldown(callback.from_user.id) # Ставим таймер КД
    
    await safe_edit(callback.message, "🚀 <b>Войска пересекают границу...</b>\n\n🛰 Идет оценка обстановки...")
    await asyncio.sleep(2)

    att_base = get_base_power(attacker)
    def_base = get_base_power(defender)
    
    att_ally_support, att_ally_count = await get_alliance_support(attacker['alliance_id'], attacker['id'])
    def_ally_support, def_ally_count = await get_alliance_support(defender['alliance_id'], defender['id'])

    report = [f"🌍 <b>БОЕВОЙ РАПОРТ: {attacker['flag']} против {defender['flag']}</b>"]
    if att_ally_count > 0: report.append(f"🤝 Ваш Альянс помог! (+{att_ally_support} мощи)")
    if def_ally_count > 0: report.append(f"⚠️ Альянс врага защищает его! (+{def_ally_support} мощи)")

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
        has_navy = (attacker['destroyers'] > 0 or attacker['cruisers'] > 0 or attacker['battleships'] > 0 or attacker.get('ships', 0) > 0)
        if has_navy:
            report.append(f"⛴ Ваш флот успешно прикрыл десант и подавил береговую оборону врага!")
        else:
            att_total = int(att_total * 0.50)
            report.append(f"🌊 <b>Смертельный десант!</b> У вас нет флота. Вражеская береговая охрана уничтожила половину десанта. Штраф атаки: -50%!")

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

    report.append(f"⚔️ Итоговая мощь атаки: {att_power}")
    report.append(f"🛡 Итоговая мощь защиты: {def_power}")

    if att_power > def_power:
        stolen_money = int(defender['budget'] * random.uniform(0.2, 0.4))
        stolen_materials = int(defender['materials'] * random.uniform(0.2, 0.4))
        stolen_oil = int(defender['oil'] * random.uniform(0.2, 0.4))
        stolen_territory = random.randint(1, 3)
        
        await execute_db("""
            UPDATE countries 
            SET budget = budget + ?, materials = materials + ?, oil = oil + ?,
                territory = territory + ?, war_wins = war_wins + 1,
                infantry = CAST(infantry * 0.85 AS INT), tanks = CAST(tanks * 0.9 AS INT),
                bridges = bridges - ? WHERE id = ?
        """, (stolen_money, stolen_materials, stolen_oil, stolen_territory, bridges_used, attacker['id']))
        
        await execute_db("""
            UPDATE countries 
            SET budget = MAX(0, budget - ?), materials = MAX(0, materials - ?), oil = MAX(0, oil - ?),
                territory = MAX(1, territory - ?), gdp = MAX(10, gdp - ?),
                infantry = CAST(infantry * ? AS INT), tanks = CAST(tanks * ? AS INT), bunkers = MAX(0, bunkers - 1)
            WHERE id = ?
        """, (stolen_money, stolen_materials, stolen_oil, stolen_territory, stolen_territory * 5, 
              1.0 - def_casualty_rate, 1.0 - (def_casualty_rate/2), defender['id']))
        
        report.append(f"\n🎉 <b>ПОБЕДА! Оборона прорвана!</b>")
        report.append(f"💰 Захвачено: {stolen_money}$, {stolen_materials} Мат., {stolen_oil} Нефти")
    else:
        await execute_db("UPDATE countries SET infantry = CAST(infantry * ? AS INT), cars = CAST(cars * ? AS INT), tanks = CAST(tanks * ? AS INT), bridges = bridges - ? WHERE id = ?", 
                         (1.0 - att_casualty_rate, 1.0 - att_casualty_rate, 1.0 - att_casualty_rate, bridges_used, attacker['id']))
        await execute_db("UPDATE countries SET infantry = CAST(infantry * ? AS INT) WHERE id = ?", 
                         (1.0 - (def_casualty_rate / 2), defender['id']))

        report.append(f"\n☠️ <b>ПОРАЖЕНИЕ!</b> Наступление захлебнулось.")

    await safe_edit(callback.message, "\n".join(report), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В штаб", callback_data="menu_war")]]))
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
    action = callback.data.split("_")[1]
    
    if action == "main":
        await safe_edit(callback.message, "🔧 <b>Главная Панель Администратора</b>\nВыберите раздел:", reply_markup=admin_main_kb())
    elif action == "backups":
        await safe_edit(callback.message, "📦 <b>Бэкапы и Откаты</b>\nЗдесь можно сохранить базу данных или полностью откатить мир (сброс даты).", reply_markup=admin_backups_kb())
    elif action == "countries":
        await safe_edit(callback.message, "🌍 <b>Управление Странами</b>\nСоздавайте NPC или удаляйте любые страны с карты.", reply_markup=admin_countries_kb())
    elif action == "alliances":
        await safe_edit(callback.message, "🤝 <b>Управление Альянсами</b>\nПринудительно удаляйте любые объединения.", reply_markup=admin_alliances_kb())
    elif action == "admins":
        await safe_edit(callback.message, "👮‍♂️ <b>Администраторы сервера</b>\nДобавляйте или снимайте полномочия с пользователей.", reply_markup=admin_admins_kb())
    await callback.answer()

@dp.callback_query(F.data == "admin_download_db")
async def admin_download_db(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("📦 Формирую файл сохранения (БД)...")
    await bot.send_document(chat_id=callback.message.chat.id, document=FSInputFile(DB_NAME), caption="Текущий бэкап мира.")
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

@dp.callback_query(F.data == "admin_create_npc")
async def admin_npc_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите название NPC-страны:")
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
    for c in countries: text += f"ID: <code>{c['id']}</code> | {c['flag']} {c['name']}\n"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_del_country")
async def admin_del_country_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("🗑 <b>Удаление Страны</b>\n\nОтправьте мне <b>ID страны</b> для её полного удаления с сервера (узнать ID можно в списке стран):")
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
        await message.answer(f"✅ Страна <b>{country['flag']} {country['name']}</b> была стёрта с лица Земли!")
    except ValueError:
        await message.answer("❌ Пожалуйста, отправьте только число (ID).")
    await state.clear()

@dp.callback_query(F.data == "admin_list_alliances")
async def admin_list_all(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    alliances = await fetch_all("SELECT id, flag, name FROM alliances")
    if not alliances: return await callback.message.answer("Альянсов нет.")
    text = "📋 <b>Список Альянсов (ID):</b>\n\n"
    for a in alliances: text += f"ID: <code>{a['id']}</code> | {a['flag']} {a['name']}\n"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_del_alliance")
async def admin_del_aly_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("🗑 <b>Удаление Альянса</b>\nОтправьте <b>ID альянса</b>:")
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
        await message.answer(f"✅ Альянс <b>{aly['flag']} {aly['name']}</b> был принудительно распущен администрацией!")
    except ValueError:
        await message.answer("❌ Нужно число (ID).")
    await state.clear()

@dp.callback_query(F.data == "admin_list_admins")
async def admin_list_adm(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    admins = await fetch_all("SELECT user_id FROM admins")
    text = "👮‍♂️ <b>Администраторы:</b>\n"
    for a in admins: 
        role = " (Главный)" if a['user_id'] == SUPER_ADMIN_ID else ""
        text += f"- <code>{a['user_id']}</code>{role}\n"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_add_admin")
async def admin_add_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("➕ <b>Назначение Админа</b>\nПришлите Telegram ID пользователя:")
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
    await callback.message.answer("➖ <b>Снятие Админа</b>\nПришлите Telegram ID пользователя:")
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
