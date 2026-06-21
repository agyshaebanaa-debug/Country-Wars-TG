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
BOT_TOKEN = "8596473788:AAGrGjeH2Dq_PHJQdmnUcE8OV-xt6t1cEIs" # ВАЖНО: В реальном проекте прячь токен в .env
ADMIN_IDS = [5341904332] # Твой Telegram ID
DB_NAME = "database.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ========================================================================
# БАЗА ДАННЫХ И МИГРАЦИИ
# ========================================================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Основная таблица стран
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
                
                -- Войска
                infantry INTEGER DEFAULT 100,
                cars INTEGER DEFAULT 5,
                trucks INTEGER DEFAULT 2,
                tanks INTEGER DEFAULT 0,
                ships INTEGER DEFAULT 0,
                
                -- Ресурсы
                materials INTEGER DEFAULT 1000,
                oil INTEGER DEFAULT 500,
                food INTEGER DEFAULT 2000,
                
                -- Здания
                factories INTEGER DEFAULT 1,
                oil_rigs INTEGER DEFAULT 1,
                farms INTEGER DEFAULT 2,
                bridges INTEGER DEFAULT 0,
                
                -- География
                rivers INTEGER DEFAULT 0,
                seas INTEGER DEFAULT 0,
                
                -- Прочее
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
        
        # Миграция для обновления старых сохранений
        new_columns = [
            ("bunkers", "INTEGER DEFAULT 0"),
            ("spies", "INTEGER DEFAULT 0"),
            ("war_wins", "INTEGER DEFAULT 0"),
            ("alliance_id", "INTEGER DEFAULT 0"),
            ("ships", "INTEGER DEFAULT 0"),
            ("materials", "INTEGER DEFAULT 1000"),
            ("oil", "INTEGER DEFAULT 500"),
            ("food", "INTEGER DEFAULT 2000"),
            ("factories", "INTEGER DEFAULT 1"),
            ("oil_rigs", "INTEGER DEFAULT 1"),
            ("farms", "INTEGER DEFAULT 2"),
            ("bridges", "INTEGER DEFAULT 0"),
            ("rivers", "INTEGER DEFAULT 0"),
            ("seas", "INTEGER DEFAULT 0")
        ]
        for col, col_type in new_columns:
            try:
                await db.execute(f"ALTER TABLE countries ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError:
                pass # Колонка уже существует
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

# ========================================================================
# ФОНОВЫЕ ЗАДАЧИ (ПРОДВИНУТАЯ ЭКОНОМИКА)
# ========================================================================
async def economy_tick():
    """Каждые 15 минут обновляет экономику и рассчитывает потребление/голод"""
    while True:
        await asyncio.sleep(900) # 900 секунд = 15 минут
        db = await get_db_connection()
        try:
            async with db.execute("SELECT * FROM countries") as cursor:
                countries = await cursor.fetchall()
            
            for c in countries:
                # 1. Производство
                prod_money = (c['settlements'] * 100) + c['gdp']
                prod_materials = c['factories'] * 50
                prod_oil = c['oil_rigs'] * 20
                prod_food = c['farms'] * 100
                
                # 2. Потребление армией
                cons_food = int(c['infantry'] * 1.5) + (c['spies'] * 5)
                cons_oil = int(c['cars'] * 1 + c['trucks'] * 2 + c['tanks'] * 5 + c['ships'] * 15)
                
                # 3. Баланс
                new_budget = c['budget'] + prod_money
                new_materials = c['materials'] + prod_materials
                
                new_food = c['food'] + prod_food - cons_food
                new_oil = c['oil'] + prod_oil - cons_oil
                
                infantry_penalty = 0
                vehicle_penalty = 0
                
                # 4. Штрафы за нехватку (Голод и поломки)
                if new_food < 0:
                    infantry_penalty = abs(new_food) // 2 # За каждую единицу нехватки еды умирает 0.5 пехотинца
                    new_food = 0
                
                if new_oil < 0:
                    vehicle_penalty = abs(new_oil) // 5 # Ломаются машины/танки
                    new_oil = 0
                
                # Применяем штрафы к войскам
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
         InlineKeyboardButton(text="🪖 Военкомат", callback_data="menu_army")],
        [InlineKeyboardButton(text="🤝 Альянс", callback_data="menu_alliance"),
         InlineKeyboardButton(text="📜 Законы", callback_data="menu_laws")]
    ])

def economy_build_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏭 Завод (5000$, 500 Матер.)", callback_data="build_factory")],
        [InlineKeyboardButton(text="🛢 Вышка (8000$, 1000 Матер.)", callback_data="build_rig")],
        [InlineKeyboardButton(text="🌾 Ферма (3000$, 200 Матер.)", callback_data="build_farm")],
        [InlineKeyboardButton(text="🌉 Понтонный мост (2000$, 800 Матер.)", callback_data="build_bridge")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")]
    ])

def army_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪖 10 Пехоты (100$, 50 Еды)", callback_data="buy_infantry"),
         InlineKeyboardButton(text="🚙 1 Авто (300$, 100 Матер.)", callback_data="buy_cars")],
        [InlineKeyboardButton(text="🚛 1 Груз. (500$, 200 Матер.)", callback_data="buy_trucks"),
         InlineKeyboardButton(text="🚜 1 Танк (2000$, 1000 Матер.)", callback_data="buy_tanks")],
        [InlineKeyboardButton(text="⛴ 1 Корабль (5000$, 2000 Матер.)", callback_data="buy_ships"),
         InlineKeyboardButton(text="🛡 1 Бункер (3000$, 1500 Матер.)", callback_data="buy_bunkers")],
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

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Создать NPC-страну", callback_data="admin_create_npc")],
        [InlineKeyboardButton(text="📥 Скачать базу данных", callback_data="admin_download_db")],
        [InlineKeyboardButton(text="📤 Загрузить базу данных", callback_data="admin_upload_db")]
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

# ========================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (СИЛА АРМИИ)
# ========================================================================
def get_base_power(country):
    """Рассчитывает базовую мощь страны"""
    power = (country['infantry'] * 1) + \
            (country['cars'] * 3) + \
            (country['trucks'] * 5) + \
            (country['tanks'] * 20) + \
            (country['ships'] * 50) + \
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
    support_power = int(total_power * 0.25) # Союзники дают 25% своей силы дистанционно
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
    
    # Генерация случайной географии
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
# ХЭНДЛЕРЫ: МЕНЮ ПРОФИЛЯ, ЭКОНОМИКИ
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
        f"🏘 <b>Поселения:</b> {country['settlements']}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🏭 Заводы: {country['factories']} | 🛢 Вышки: {country['oil_rigs']} | 🌾 Фермы: {country['farms']}\n"
        f"🌉 Понтонные мосты (для атак): {country['bridges']}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"⚔️ <b>Армия:</b>\n"
        f"🪖 Пехота: {country['infantry']} | 🚙 Авто: {country['cars']} | 🚛 Груз: {country['trucks']}\n"
        f"🚜 Танки: {country['tanks']} | ⛴ Корабли: {country['ships']}\n"
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
        await callback.message.edit_text("Вы в главном штабе. Ждем указаний.", reply_markup=main_menu_kb())
        
    elif action == "economy":
        prod_money = (country['settlements'] * 100) + country['gdp']
        prod_materials = country['factories'] * 50
        prod_oil = country['oil_rigs'] * 20
        prod_food = country['farms'] * 100
        
        cons_food = int(country['infantry'] * 1.5) + (country['spies'] * 5)
        cons_oil = int(country['cars'] * 1 + country['trucks'] * 2 + country['tanks'] * 5 + country['ships'] * 15)
        
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
            f"<i>⚠️ Держите баланс еды и нефти положительным, иначе армия начнет вымирать и техника сломается!</i>"
        )
        await callback.message.edit_text(text, reply_markup=economy_build_kb())

    elif action == "army":
        await callback.message.edit_text(
            f"🪖 <b>Военкомат и Верфи</b>\n\n"
            f"Доступно:\n💵 {country['budget']}$ | 🧱 {country['materials']} мат. | 🥩 {country['food']} еды", 
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
            "👤 Игроки | 🤖 NPC | 🏞 Реки | 🌊 Море\n\n"
            "<i>Для атаки требуется 200 Еды и 100 Нефти на мобилизацию!</i>",
            reply_markup=war_targets_kb(targets)
        )

# ========================================================================
# ХЭНДЛЕРЫ: СТРОИТЕЛЬСТВО ЭКОНОМИКИ
# ========================================================================
@dp.callback_query(F.data.startswith("build_"))
async def process_economy_build(callback: types.CallbackQuery):
    item = callback.data.split("_")[1]
    country = await fetch_one("SELECT * FROM countries WHERE owner_id = ?", (callback.from_user.id,))
    
    # dict: [цена_$, цена_материалы, поле_в_бд, название]
    costs = {
        "factory": (5000, 500, "factories", "Завод"),
        "rig": (8000, 1000, "oil_rigs", "Нефтевышка"),
        "farm": (3000, 200, "farms", "Ферма"),
        "bridge": (2000, 800, "bridges", "Понтонный мост")
    }
    price_money, price_mat, db_field, name = costs[item]
    
    if country['budget'] < price_money or country['materials'] < price_mat:
        return await callback.answer(f"❌ Недостаточно ресурсов! Нужно {price_money}$ и {price_mat} матер.", show_alert=True)
        
    await execute_db(
        f"UPDATE countries SET budget = budget - ?, materials = materials - ?, {db_field} = {db_field} + 1 WHERE id = ?",
        (price_money, price_mat, country['id'])
    )
    
    await callback.answer(f"✅ Успешно построено: {name}!", show_alert=True)
    
    # Обновляем меню
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    prod_materials = new_country['factories'] * 50
    text = (
        f"🏭 <b>Министерство Экономики</b>\n"
        f"💵 Бюджет: {new_country['budget']:,}$ | 🧱 Матер.: {new_country['materials']:,}\n"
        f"🏭 Заводы: {new_country['factories']} | 🛢 Вышки: {new_country['oil_rigs']} | 🌾 Фермы: {new_country['farms']}\n"
        f"🌉 Мосты: {new_country['bridges']}"
    )
    await callback.message.edit_text(text, reply_markup=economy_build_kb())


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
    await process_menus(callback, FSMContext(storage=dp.storage, key=callback.from_user.id))

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
        "infantry": {"money": 100, "food": 50, "materials": 0, "amount": 10, "name": "Пехоты"},
        "cars": {"money": 300, "food": 0, "materials": 100, "amount": 1, "name": "Авто"},
        "trucks": {"money": 500, "food": 0, "materials": 200, "amount": 1, "name": "Грузовик"},
        "tanks": {"money": 2000, "food": 0, "materials": 1000, "amount": 1, "name": "Танк"},
        "ships": {"money": 5000, "food": 0, "materials": 2000, "amount": 1, "name": "Корабль"},
        "bunkers": {"money": 3000, "food": 0, "materials": 1500, "amount": 1, "name": "Бункер"},
        "spies": {"money": 1000, "food": 0, "materials": 0, "amount": 1, "name": "Шпион"}
    }
    req = costs[item]
    
    if country['budget'] < req["money"] or country['food'] < req["food"] or country['materials'] < req["materials"]:
        return await callback.answer(f"❌ Не хватает ресурсов! Нужно {req['money']}$, {req['materials']} мат., {req['food']} еды.", show_alert=True)
        
    await execute_db(
        f"UPDATE countries SET budget = budget - ?, food = food - ?, materials = materials - ?, {item} = {item} + ? WHERE id = ?",
        (req["money"], req["food"], req["materials"], req["amount"], country['id'])
    )
    
    await callback.answer(f"✅ Успешно куплено: {req['amount']} {req['name']}!", show_alert=True)
    
    new_country = await fetch_one("SELECT * FROM countries WHERE id = ?", (country['id'],))
    await callback.message.edit_text(
        f"🪖 <b>Военкомат</b>\nДоступно:\n💵 {new_country['budget']}$ | 🧱 {new_country['materials']} мат. | 🥩 {new_country['food']} еды", 
        reply_markup=army_kb()
    )

# ========================================================================
# ХЭНДЛЕРЫ: БОЕВАЯ СИСТЕМА И ГЕОГРАФИЯ
# ========================================================================
@dp.callback_query(F.data.startswith("prepwar_"))
async def process_prepwar(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    defender = await fetch_one("SELECT * FROM countries WHERE id = ?", (target_id,))
    
    geo_info = "\n<b>Ландшафт врага:</b>\n"
    if defender['rivers'] > 0:
        geo_info += f"🏞 Реки ({defender['rivers']}). Потребуется столько же понтонных мостов для форсирования, иначе техника увязнет.\n"
    if defender['seas'] > 0:
        geo_info += f"🌊 Выход к морю. Десантироваться тяжело! Без поддержки Кораблей наземные силы потеряют 50% мощи.\n"
    if defender['rivers'] == 0 and defender['seas'] == 0:
        geo_info += "Равнина. Идеально для танковых клиньев!\n"

    await callback.message.edit_text(
        f"⚔️ <b>Подготовка к вторжению в {defender['flag']} {defender['name']}</b>\n"
        f"{geo_info}\n"
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
        f"💰 Бюджет: ~{defender['budget']}$ | 🛢 Нефть: {defender['oil']}\n"
        f"🪖 Наземные: {defender['infantry']} пехоты, {defender['tanks']} танков\n"
        f"⛴ Флот: {defender['ships']} кораблей\n"
        f"🛡 Укрепления: {defender['bunkers']} бункеров\n\n"
        f"📊 Оценочная базовая мощь: <b>{def_power_est}</b>\n"
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
    
    # Требования мобилизации
    if attacker['food'] < 200 or attacker['oil'] < 100:
        return await callback.answer("❌ Для мобилизации армии нужно минимум 200 Еды и 100 Нефти!", show_alert=True)
        
    # Списываем ресурсы за атаку
    await execute_db("UPDATE countries SET food = food - 200, oil = oil - 100 WHERE id = ?", (attacker['id'],))

    await callback.message.edit_text("🚀 <b>Генералы отдали приказ! Войска пересекают границу...</b>\n\n🛰 Идет оценка обстановки...")
    await asyncio.sleep(2)

    att_base = get_base_power(attacker)
    def_base = get_base_power(defender)
    
    att_ally_support, att_ally_count = await get_alliance_support(attacker['alliance_id'], attacker['id'])
    def_ally_support, def_ally_count = await get_alliance_support(defender['alliance_id'], defender['id'])

    report = [f"🌍 <b>БОЕВОЙ РАПОРТ: {attacker['flag']} против {defender['flag']}</b>"]
    
    if att_ally_count > 0:
        report.append(f"🤝 Ваш Альянс оказал поддержку! (+{att_ally_support} мощи)")
    if def_ally_count > 0:
        report.append(f"⚠️ Альянс врага встал на его защиту! (+{def_ally_support} мощи защиты)")

    att_total = att_base + att_ally_support
    
    # ------------------ ГЕОГРАФИЯ И ШТРАФЫ ------------------
    bridges_used = 0
    if defender['rivers'] > 0:
        if attacker['bridges'] >= defender['rivers']:
            bridges_used = defender['rivers']
            report.append(f"🌉 Ваши инженерные войска навели понтонные мосты через реки (потрачено мостов: {bridges_used}).")
        else:
            penalty = 0.30  # Штраф 30%
            att_total = int(att_total * (1 - penalty))
            report.append(f"🏞 <b>Катастрофа на переправе!</b> Из-за нехватки мостов техника застряла в реках. Штраф атаки: -30%!")
            
    if defender['seas'] > 0:
        if attacker['ships'] > 0:
            report.append(f"⛴ Ваш флот успешно прикрыл десантную операцию с моря!")
        else:
            penalty = 0.50 # Огромный штраф без флота
            att_total = int(att_total * (1 - penalty))
            report.append(f"🌊 <b>Смертельный десант!</b> У вас нет флота. Вражеская береговая охрана уничтожает половину ваших сил. Штраф атаки: -50%!")

    def_total = def_base + def_ally_support
    
    # Тактики и опыт
    att_mult = 1.0 + (min(attacker['war_wins'], 50) * 0.01)
    att_casualty_rate, def_casualty_rate = 0.5, 0.4
    
    if tactic == "blitz":
        att_mult *= 1.3
        att_casualty_rate = 0.7
        report.append("\n⚡️ <b>Тактика: Блицкриг.</b> Мощный, но рискованный удар.")
    elif tactic == "siege":
        att_mult *= 0.9
        att_casualty_rate = 0.2
        report.append("\n🛡 <b>Тактика: Осада.</b> Осторожное продвижение.")
    else:
        report.append("\n⚖️ <b>Тактика: Сбалансированная.</b>")

    att_power = int(att_total * att_mult * random.uniform(0.9, 1.2))
    def_power = int(def_total * random.uniform(0.9, 1.2))

    report.append(f"⚔️ Итоговая мощь атаки: {att_power}")
    report.append(f"🛡 Итоговая мощь защиты: {def_power}")

    # Итоги Битвы
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
                bridges = bridges - ?
            WHERE id = ?
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
        report.append(f"💰 Захвачено: {stolen_money}$")
        report.append(f"📦 Ресурсы: +{stolen_materials} Матер., +{stolen_oil} Нефти")
        report.append(f"🗺 Аннексировано: {stolen_territory} км²")
        report.append(f"🏅 Получен военный опыт (+1 к победам)!")
    else:
        await execute_db("""
            UPDATE countries 
            SET infantry = CAST(infantry * ? AS INT), cars = CAST(cars * ? AS INT), tanks = CAST(tanks * ? AS INT),
                bridges = bridges - ?
            WHERE id = ?
        """, (1.0 - att_casualty_rate, 1.0 - att_casualty_rate, 1.0 - att_casualty_rate, bridges_used, attacker['id']))
        
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
# ХЭНДЛЕРЫ: АДМИН ПАНЕЛЬ
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
    
    rivers = random.randint(0, 3)
    seas = random.randint(0, 1)
    
    await execute_db(
        """INSERT INTO countries (name, flag, budget, gdp, territory, infantry, cars, trucks, tanks, bunkers, materials, oil, food, rivers, seas) 
           VALUES (?, ?, 15000, 500, 50, 1000, 100, 50, 25, 5, 5000, 5000, 5000, ?, ?)""",
        (data['name'], flag, rivers, seas)
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
