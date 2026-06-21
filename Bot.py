import asyncio
import logging
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
# ========================================================================
BOT_TOKEN = "8596473788:AAGrGjeH2Dq_PHJQdmnUcE8OV-xt6t1cEIs" 
ADMIN_IDS = [5341904332] # Замени на свой Telegram ID
DB_NAME = "database.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ========================================================================
# БАЗА ДАННЫХ И ОПТИМИЗАЦИЯ
# ========================================================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица стран
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER UNIQUE,
                name TEXT,
                flag TEXT,
                budget INTEGER DEFAULT 5000,
                gdp INTEGER DEFAULT 100,
                territory INTEGER DEFAULT 10,
                settlements INTEGER DEFAULT 1,
                infantry INTEGER DEFAULT 50,
                cars INTEGER DEFAULT 5,
                trucks INTEGER DEFAULT 2,
                tanks INTEGER DEFAULT 0,
                laws TEXT DEFAULT 'Нет законов',
                bunkers INTEGER DEFAULT 0,
                spies INTEGER DEFAULT 0,
                war_wins INTEGER DEFAULT 0,
                alliance_id INTEGER DEFAULT 0
            )
        """)
        
        # Таблица альянсов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alliances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                flag TEXT,
                leader_id INTEGER
            )
        """)
        
        # Миграция для старых сохранений (на случай, если таблица стран уже есть)
        new_columns = [
            ("bunkers", "INTEGER DEFAULT 0"),
            ("spies", "INTEGER DEFAULT 0"),
            ("war_wins", "INTEGER DEFAULT 0"),
            ("alliance_id", "INTEGER DEFAULT 0")
        ]
        for col, col_type in new_columns:
            try:
                await db.execute(f"ALTER TABLE countries ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError:
                pass # Колонка уже существует
        await db.commit()

async def get_db_connection():
    db = await aiosqlite.connect(DB_NAME)
    db.row_factory = aiosqlite.Row # Возвращаем данные как словари (очень удобно!)
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

# ========================================================================
# ФОНОВЫЕ ЗАДАЧИ (ЭКОНОМИКА)
# ========================================================================
async def economy_tick():
    """Каждую минуту прибавляет бюджет странам на основе их ВВП"""
    while True:
        await asyncio.sleep(60)
        try:
            await execute_db("UPDATE countries SET budget = budget + gdp")
            logging.info("Экономика: Налоги собраны со всех стран!")
        except Exception as e:
            logging.error(f"Ошибка экономики: {e}")

# ========================================================================
# МАШИНА СОСТОЯНИЙ (FSM)
# ========================================================================
class CreateCountry(StatesGroup):
    name = State()
    flag = State()

class AdminNPC(StatesGroup):
    name = State()
    flag = State()

class AdminRestore(StatesGroup):
    waiting_for_db = State()

class CreateAlliance(StatesGroup):
    name = State()
    flag = State()

# ========================================================================
# КЛАВИАТУРЫ
# ========================================================================
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Моя Страна", callback_data="menu_profile"),
         InlineKeyboardButton(text="⚔️ Война", callback_data="menu_war")],
        [InlineKeyboardButton(text="🏭 Экономика", callback_data="menu_economy"),
         InlineKeyboardButton(text="🪖 Армия", callback_data="menu_army")],
        [InlineKeyboardButton(text="🤝 Альянс", callback_data="menu_alliance"),
         InlineKeyboardButton(text="📜 Законы", callback_data="menu_laws")]
    ])

def army_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 10 Пехоты (100$)", callback_data="buy_infantry"),
         InlineKeyboardButton(text="🚙 1 Авто (300$)", callback_data="buy_cars")],
        [InlineKeyboardButton(text="🚛 1 Груз. (500$)", callback_data="buy_trucks"),
         InlineKeyboardButton(text="🚜 1 Танк (2000$)", callback_data="buy_tanks")],
        [InlineKeyboardButton(text="🛡 1 Бункер (3000$)", callback_data="buy_bunkers"),
         InlineKeyboardButton(text="🕵️‍♂️ 1 Шпион (1000$)", callback_data="buy_spies")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def tactics_kb(target_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Блицкриг (Атака +30%, Риск потерь)", callback_data=f"tactic_blitz_{target_id}")],
        [InlineKeyboardButton(text="🛡 Осада (Защита войск, Атака -10%)", callback_data=f"tactic_siege_{target_id}")],
        [InlineKeyboardButton(text="⚖️ Стандартный бой", callback_data=f"tactic_balance_{target_id}")],
        [InlineKeyboardButton(text="🕵️‍♂️ Отправить шпиона (1 Шпион)", callback_data=f"spy_{target_id}")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu_war")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Создать NPC-страну", callback_data="admin_create_npc")],
        [InlineKeyboardButton(text="📥 Скачать сохранение (DB)", callback_data="admin_download_db")],
        [InlineKeyboardButton(text="📤 Загрузить сохранение (DB)", callback_data="admin_upload_db")]
    ])

def war_targets_kb(targets):
    kb = []
    for t in targets:
        type_str = "👤" if t['owner_id'] else "🤖"
        kb.append([InlineKeyboardButton(text=f"{t['flag']} {t['name']} {type_str}", callback_data=f"prepwar_{t['id']}")])
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

# ========================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (СИЛА АРМИИ)
# ========================================================================
def get_base_power(country):
    """Рассчитывает базовую мощь страны без модификаторов"""
    power = (country['infantry'] * 1) + \
            (country['cars'] * 3) + \
            (country['trucks'] * 5) + \
            (country['tanks'] * 20) + \
            (country['bunkers'] * 50)
    return power

async def get_alliance_support(alliance_id, exclude_country_id):
    """Рассчитывает бонусную поддержку от союзников"""
    if not alliance_id:
        return 0, 0
    allies = await fetch_all("SELECT * FROM countries WHERE alliance_id = ? AND id != ?", (alliance_id, exclude_country_id))
    if not allies:
        return 0, 0
    
    total_power = sum(get_base_power(ally) for ally in allies)
    support_power = int(total_power * 0.25) # Союзники дают 25% своей силы
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
            "🌍 <b>Добро пожаловать в 'Войну Стран'!</b>\n\n"
            "Здесь ты можешь построить свою империю, развивать экономику и объединяться в альянсы.\n\n"
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
    
    await execute_db(
        "INSERT INTO countries (owner_id, name, flag) VALUES (?, ?, ?)",
        (message.from_user.id, data['name'], flag)
    )
    
    await message.answer(
        f"🎉 Ура! Страна <b>{flag} {data['name']}</b> успешно основана!\n\n"
        f"Тебе выдано стартовое пособие. Развивай ВВП, строй армию и захватывай соседей!",
        reply_markup=main_menu_kb()
    )
    await state.clear()

# ========================================================================
# ХЭНДЛЕРЫ: МЕНЮ ПРОФИЛЯ, ЭКОНОМИКИ
# ========================================================================
async def get_country_text(country):
    aly_text = "Нет"
    if country['alliance_id']:
        aly = await fetch_one("SELECT * FROM alliances WHERE id = ?", (country['alliance_id'],))
        if aly: aly_text = f"{aly['flag']} {aly['name']}"

    return (
        f"🌍 <b>Страна:</b> {country['flag']} {country['name']} (Побед: {country['war_wins']} 🏅)\n"
        f"🤝 <b>Альянс:</b> {aly_text}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"💰 <b>Бюджет:</b> {country['budget']:,}$ 💵\n"
        f"📈 <b>ВВП:</b> {country['gdp']:,}$/мин\n"
        f"🗺 <b>Территория:</b> {country['territory']:,} км²\n"
        f"🏘 <b>Поселения:</b> {country['settlements']}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⚔️ <b>Армия и База:</b>\n"
        f"🪖 Пехота: {country['infantry']} | 🚙 Авто: {country['cars']}\n"
        f"🚛 Грузовики: {country['trucks']} | 🚜 Танки: {country['tanks']}\n"
        f"🛡 Бункеры: {country['bunkers']} | 🕵️‍♂️ Шпионы: {country['spies']}"
    )

@dp.callback_query(F.data.startswith("menu_"))
async def process_menus(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    action = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    if not country:
        return await callback.answer("У вас нет страны! Напишите /start", show_alert=True)

    if action == "profile":
        text = await get_country_text(country)
        await callback.message.edit_text(text, reply_markup=main_menu_kb())
        
    elif action == "main":
        await callback.message.edit_text("Вы в главном меню. Что прикажете, правитель?", reply_markup=main_menu_kb())
        
    elif action == "economy":
        text = (
            f"🏭 <b>Экономика {country['flag']} {country['name']}</b>\n\n"
            f"Территория и поселения увеличивают ваш ВВП.\n"
            f"Текущий прирост: <b>+{country['gdp']}$ каждую минуту!</b>"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]]))

    elif action == "army":
        await callback.message.edit_text(
            f"🪖 <b>Военкомат</b>\nБюджет: {country['budget']}$", 
            reply_markup=army_kb()
        )
        
    elif action == "laws":
        await callback.answer("Система законов находится в разработке! 🛠", show_alert=True)

    elif action == "alliance":
        if country['alliance_id'] == 0:
            top_alliances = await fetch_all("SELECT * FROM alliances LIMIT 5")
            await callback.message.edit_text(
                "🤝 <b>Дипломатия Альянсов</b>\n\nВы не состоите в альянсе. Альянсы позволяют странам оказывать военную поддержку друг другу в битвах.",
                reply_markup=alliance_none_kb(top_alliances)
            )
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
            await callback.message.edit_text(text, reply_markup=alliance_member_kb(is_leader))

    elif action == "war":
        targets = await fetch_all("SELECT * FROM countries WHERE id != ? LIMIT 10", (country['id'],))
        if not targets:
            return await callback.answer("В мире пока нет других стран для атаки!", show_alert=True)
            
        await callback.message.edit_text(
            "⚔️ <b>Командование: Выбор цели</b>\n"
            "👤 - Игроки | 🤖 - NPC",
            reply_markup=war_targets_kb(targets)
        )

# ========================================================================
# ХЭНДЛЕРЫ: АЛЬЯНСЫ
# ========================================================================
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
    await execute_db(
        "INSERT INTO alliances (name, flag, leader_id) VALUES (?, ?, ?)",
        (data['name'], flag, country['owner_id'])
    )
    
    # Узнаем ID нового альянса и добавляем туда создателя
    new_aly = await fetch_one("SELECT id FROM alliances WHERE leader_id = ?", (country['owner_id'],))
    await execute_db("UPDATE countries SET alliance_id = ? WHERE id = ?", (new_aly['id'], country['id']))
    
    await message.answer(f"✅ Альянс <b>{flag} {data['name']}</b> успешно создан!", reply_markup=main_menu_kb())
    await state.clear()

@dp.callback_query(F.data.startswith("aly_join_"))
async def cmd_aly_join(callback: types.CallbackQuery):
    aly_id = int(callback.data.split("_")[2])
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    await execute_db("UPDATE countries SET alliance_id = ? WHERE id = ?", (aly_id, country['id']))
    await callback.answer("Вы успешно вступили в Альянс!", show_alert=True)
    await process_menus(callback, FSMContext(storage=dp.storage, key=callback.from_user.id)) # Возврат в меню

@dp.callback_query(F.data == "aly_leave")
async def cmd_aly_leave(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE id = ?", (country['id'],))
    await callback.answer("Вы покинули Альянс.", show_alert=True)
    await callback.message.edit_text("Вы покинули Альянс.", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "aly_disband")
async def cmd_aly_disband(callback: types.CallbackQuery):
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    aly_id = country['alliance_id']
    
    await execute_db("UPDATE countries SET alliance_id = 0 WHERE alliance_id = ?", (aly_id,))
    await execute_db("DELETE FROM alliances WHERE id = ?", (aly_id,))
    
    await callback.answer("Альянс распущен!", show_alert=True)
    await callback.message.edit_text("Ваш Альянс был навсегда распущен.", reply_markup=main_menu_kb())


# ========================================================================
# ХЭНДЛЕРЫ: ПОКУПКА АРМИИ
# ========================================================================
@dp.callback_query(F.data.startswith("buy_"))
async def process_army_buy(callback: types.CallbackQuery):
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    costs = {
        "infantry": (100, 10, "Пехоты"), "cars": (300, 1, "Автомобиль"), 
        "trucks": (500, 1, "Грузовик"), "tanks": (2000, 1, "Танк"),
        "bunkers": (3000, 1, "Бункер"), "spies": (1000, 1, "Шпион")
    }
    price, amount, name = costs[item]
    
    if country['budget'] < price:
        return await callback.answer(f"❌ Недостаточно средств! Нужно {price}$", show_alert=True)
        
    await execute_db(
        f"UPDATE countries SET budget = budget - ?, {item} = {item} + ? WHERE id = ?",
        (price, amount, country['id'])
    )
    
    await callback.answer(f"✅ Успешно куплено: {amount} {name}!", show_alert=True)
    
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    await callback.message.edit_text(
        f"🪖 <b>Военкомат</b>\nБюджет: {new_country['budget']}$", 
        reply_markup=army_kb()
    )

# ========================================================================
# ХЭНДЛЕРЫ: БОЕВАЯ СИСТЕМА И РАЗВЕДКА
# ========================================================================
@dp.callback_query(F.data.startswith("prepwar_"))
async def process_prepwar(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    await callback.message.edit_text(
        "⚔️ <b>Подготовка к вторжению</b>\n\n"
        "Выберите тактику ведения боя или отправьте шпиона:",
        reply_markup=tactics_kb(target_id)
    )

@dp.callback_query(F.data.startswith("spy_"))
async def process_spy(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if attacker['spies'] < 1:
        return await callback.answer("У вас нет шпионов! Наймите их в Военкомате.", show_alert=True)
        
    await execute_db("UPDATE countries SET spies = spies - 1 WHERE id = ?", (attacker['id'],))
    
    if random.random() < 0.2:
        return await callback.message.edit_text(
            "💥 <b>Провал операции!</b>\nВаш шпион был раскрыт и ликвидирован вражеской контрразведкой.",
            reply_markup=tactics_kb(target_id)
        )
        
    def_power_est = get_base_power(defender)
    text = (
        f"🕵️‍♂️ <b>Секретный рапорт по {defender['flag']} {defender['name']}</b>:\n\n"
        f"💰 Бюджет: ~{defender['budget']}$ | ВВП: {defender['gdp']}\n"
        f"🪖 Наземные: {defender['infantry']} пехоты, {defender['tanks']} танков\n"
        f"🛡 Укрепления: {defender['bunkers']} бункеров\n\n"
        f"📊 Оценочная базовая мощь: <b>{def_power_est}</b>\n"
        f"<i>(Шпион не учитывает возможную поддержку Альянса врага)</i>"
    )
    await callback.message.edit_text(text, reply_markup=tactics_kb(target_id))

@dp.callback_query(F.data.startswith("tactic_"))
async def process_attack(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    tactic, target_id = parts[1], int(parts[2])
    
    attacker = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    if not attacker or not defender: return await callback.answer("Ошибка данных стран.", show_alert=True)
    if attacker['id'] == defender['id']: return await callback.answer("Нельзя напасть на себя!", show_alert=True)

    await callback.message.edit_text("🚀 <b>Генералы отдали приказ! Войска пересекают границу...</b>\n\n🛰 Идет оценка обстановки...")
    await asyncio.sleep(2)

    # Базовая мощь сторон
    att_base = get_base_power(attacker)
    def_base = get_base_power(defender)
    
    # Поддержка альянсов
    att_ally_support, att_ally_count = await get_alliance_support(attacker['alliance_id'], attacker['id'])
    def_ally_support, def_ally_count = await get_alliance_support(defender['alliance_id'], defender['id'])

    report = ["🌍 <b>БОЕВОЙ РАПОРТ</b>"]
    
    if att_ally_count > 0:
        report.append(f"🤝 Ваш Альянс оказал артиллерийскую поддержку! (+{att_ally_support} мощи)")
    if def_ally_count > 0:
        report.append(f"⚠️ Внимание! Альянс врага встал на его защиту! (+{def_ally_support} мощи защиты врагу)")

    att_total = att_base + att_ally_support
    def_total = def_base + def_ally_support
    
    # Тактики и опыт
    att_mult = 1.0 + (min(attacker['war_wins'], 50) * 0.01) # Опыт
    att_casualty_rate, def_casualty_rate = 0.5, 0.4
    
    if tactic == "blitz":
        att_mult *= 1.3
        att_casualty_rate = 0.7
        report.append("\n⚡️ <b>Тактика: Блицкриг.</b> Мощный, но рискованный удар.")
    elif tactic == "siege":
        att_mult *= 0.9
        att_casualty_rate = 0.2
        report.append("\n🛡 <b>Тактика: Осада.</b> Осторожное продвижение с минимумом потерь.")
    else:
        report.append("\n⚖️ <b>Тактика: Сбалансированная.</b>")

    att_power = int(att_total * att_mult * random.uniform(0.9, 1.2))
    def_power = int(def_total * random.uniform(0.9, 1.2))

    report.append(f"⚔️ Итоговая мощь атаки: {att_power}")
    report.append(f"🛡 Итоговая мощь защиты: {def_power}")

    # Итоги
    if att_power > def_power:
        stolen_money = int(defender['budget'] * random.uniform(0.2, 0.4))
        stolen_territory = random.randint(1, 3)
        
        await execute_db("""
            UPDATE countries 
            SET budget = budget + ?, territory = territory + ?, gdp = gdp + ?, war_wins = war_wins + 1,
                infantry = CAST(infantry * 0.85 AS INT), tanks = CAST(tanks * 0.9 AS INT)
            WHERE id = ?
        """, (stolen_money, stolen_territory, stolen_territory * 5, attacker['id']))
        
        await execute_db("""
            UPDATE countries 
            SET budget = MAX(0, budget - ?), territory = MAX(1, territory - ?), gdp = MAX(10, gdp - ?),
                infantry = CAST(infantry * ? AS INT), tanks = ?, bunkers = MAX(0, bunkers - 1)
            WHERE id = ?
        """, (stolen_money, stolen_territory, stolen_territory * 5, 1.0 - def_casualty_rate, defender['tanks'], defender['id']))
        
        report.append(f"\n🎉 <b>ПОБЕДА! Оборона прорвана!</b>")
        report.append(f"💰 Захвачено: {stolen_money}$")
        report.append(f"🗺 Аннексировано: {stolen_territory} км² (+{stolen_territory*5} к ВВП)")
        report.append(f"🏅 Получен военный опыт (+1 к победам)!")
    else:
        await execute_db("""
            UPDATE countries 
            SET infantry = CAST(infantry * ? AS INT), cars = CAST(cars * ? AS INT), tanks = CAST(tanks * ? AS INT)
            WHERE id = ?
        """, (1.0 - att_casualty_rate, 1.0 - att_casualty_rate, 1.0 - att_casualty_rate, attacker['id']))
        
        # Защитник тоже теряет войска
        await execute_db("""
            UPDATE countries 
            SET infantry = CAST(infantry * ? AS INT)
            WHERE id = ?
        """, (1.0 - (def_casualty_rate / 2), defender['id']))

        report.append(f"\n☠️ <b>ПОРАЖЕНИЕ!</b> Наступление захлебнулось.")
        report.append(f"🩸 Вы потеряли {int(att_casualty_rate * 100)}% техники и солдат при отступлении.")

    final_text = "\n".join(report)
    await callback.message.edit_text(final_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В штаб", callback_data="menu_war")]]))

# ========================================================================
# ХЭНДЛЕРЫ: АДМИН ПАНЕЛЬ И СОХРАНЕНИЯ (БЕКАПЫ)
# ========================================================================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("У вас нет доступа к этой команде.")
    
    await message.answer("🔧 <b>Панель Администратора</b>\n\nЧто будем делать, создатель?", reply_markup=admin_kb())

@dp.callback_query(F.data == "admin_create_npc")
async def admin_npc_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await callback.message.answer("Введите название NPC-страны:")
    await state.set_state(AdminNPC.name)

@dp.message(AdminNPC.name)
async def admin_npc_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отправьте эмодзи-флаг для NPC:")
    await state.set_state(AdminNPC.flag)

@dp.message(AdminNPC.flag)
async def admin_npc_flag(message: types.Message, state: FSMContext):
    flag = message.text[:2]
    data = await state.get_data()
    
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, infantry, cars, trucks, tanks, bunkers) 
           VALUES (?, ?, 10000, 500, 50, 500, 100, 50, 15, 3)""",
        (data['name'], flag)
    )
    
    await message.answer(f"✅ NPC-страна <b>{flag} {data['name']}</b> создана и добавлена на карту!")
    await state.clear()

@dp.callback_query(F.data == "admin_download_db")
async def admin_download_db(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    
    await callback.message.answer("📦 Формирую файл сохранения (БД)...")
    db_file = FSInputFile(DB_NAME)
    await bot.send_document(
        chat_id=callback.message.chat.id, 
        document=db_file, 
        caption="Вот текущее сохранение мира. Храни его в надежном месте."
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_upload_db")
async def admin_upload_db_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    
    await callback.message.answer(
        "⚠️ <b>ВНИМАНИЕ!</b> Загрузка нового файла сотрет текущий мир!\n\n"
        "Отправьте мне файл <code>database.db</code> в этот чат, чтобы восстановить сохранения."
    )
    await state.set_state(AdminRestore.waiting_for_db)
    await callback.answer()

@dp.message(AdminRestore.waiting_for_db, F.document)
async def admin_upload_db_finish(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    
    await bot.download_file(file_path, DB_NAME)
    
    await message.answer("✅ <b>Мир успешно восстановлен из сохранения!</b>\nБаза данных обновлена. Новые параметры применены.")
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
