import json
from datetime import datetime, timedelta
import telebot
from telebot.apihelper import ApiException
import sqlite3
from openpyxl import Workbook
from telebot import TeleBot, types
import threading
import time

# BotFather'dan olgan API tokeningizni bu yerga qo'ying
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("TOKEN") 

bot = TeleBot(TOKEN)

# Majburiy obuna bo'lish kerak bo'lgan kanallar ro'yxati
REQUIRED_CHANNELS = [
    {"username": "toshkent_vohasi", "link": "https://t.me/toshkent_vohasi"}
    # Boshqa kanallarni qo'shishingiz mumkin , bilan
]

# Ma'lumotlar bazasini yaratish yoki ulanish
conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()

# Bosqichlarning boshlanish sanalari
START_DATE = datetime(2025, 11, 5)  # 1-bosqich boshlanish sanasi
STAGES = {
    1: START_DATE,
    2: START_DATE + timedelta(days=20),
    3: START_DATE + timedelta(days=40),
    4: START_DATE + timedelta(days=60)
}

# Test sanalari
TEST_DATES = {
    1: datetime(2025, 11, 25),  # 1-bosqich test sanasi
    2: datetime(2025, 12, 15),  # 2-bosqich test sanasi
    3: datetime(2026, 1, 5),    # 3-bosqich test sanasi
    4: datetime(2026, 1, 30)    # 4-bosqich test sanasi
}

# Eslatma yuborish uchun kunlar
NOTIFICATION_DAYS = [3, 2, 1]  # Testdan 3, 2, 1 kun oldin eslatma yuborish

# Test davomiyligi (kunlarda)
TEST_DURATION = 1  # Test bir kun davom etadi

# Jadval yaratish (agar mavjud bo'lmasa)
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    phone_number TEXT,
    status TEXT,
    region TEXT,
    stage_1_score INTEGER DEFAULT 0,
    stage_2_score INTEGER DEFAULT 0,
    stage_3_score INTEGER DEFAULT 0,
    stage_4_score INTEGER DEFAULT 0,
    total_score INTEGER DEFAULT 0,
    completed_stages TEXT DEFAULT '',
    notification_sent TEXT DEFAULT ''
)''')
conn.commit()

# Web App URL (HTML sahifangiz manzili)
registration_url = "https://incredible-sawine-147c55.netlify.app/"  # Registratsiya URL manzili
test_url_base = "https://delicate-gumdrop-54903c.netlify.app/"  # Asosiy test URL manzili
test_url_finished = "https://delicate-gumdrop-54903c.netlify.app/"  # Test tugagandan so'ng ko'rsatiladigan URL

# Foydalanuvchi ma'lumotlarini saqlash uchun lug'at
user_data = {}

# --- Asosiy funksiyalar ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    user_exists = cursor.fetchone()

    if user_exists:
        # Kanallarga obuna bo'lganlikni tekshirish
        not_subscribed_channels = check_subscription(user_id)
        
        if not_subscribed_channels:
            # Agar foydalanuvchi barcha kanallarga obuna bo'lmagan bo'lsa
            show_subscription_message(user_id, not_subscribed_channels)
        else:
            # Agar foydalanuvchi barcha kanallarga obuna bo'lgan bo'lsa
            show_main_menu(message)
    else:
        web_app = types.WebAppInfo(registration_url)  # Registratsiya URL'ini ishlatish
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("📝 Ro'yxatdan o'tish", web_app=web_app))
        bot.send_message(message.chat.id, "Ro'yxatdan o'tish uchun quyidagi tugmani bosing:", reply_markup=markup)

# Foydalanuvchini ro'yxatdan o'tkazish (ism-familiya)
@bot.message_handler(content_types=['web_app_data'])
def process_web_app_data(message):
    user_id = message.from_user.id
    try:
        data = json.loads(message.web_app_data.data)

        # Agar 'score' kaliti mavjud bo'lsa, bu test natijasi
        if 'score' in data:
            process_test_result(message, data)
        else:
            # Foydalanuvchi ma'lumotlarini tekshirish (ism-familiya, status, region)
            if not data.get('full_name') or not data.get('status') or not data.get('region'):
                bot.send_message(user_id, "Iltimos, barcha maydonlarni to'ldiring.")
                return

            # Ma'lumotlarni `user_data` lug'atiga saqlash
            user_data[user_id] = data

            # Foydalanuvchidan telefon raqamini so'rash
            request_phone_number(message)
    except Exception as e:
        print(f"Web app ma'lumotlarini qayta ishlashda xatolik: {e}")
        bot.send_message(user_id, "Kechirasiz, web app ma'lumotlarini qayta ishlashda xatolik yuz berdi.")


def process_test_result(message, data):
    user_id = message.from_user.id
    score = data.get('score', 0)

    # Hozirgi bosqichni aniqlash
    current_date = datetime.now()
    current_stage = None
    for stage, date in STAGES.items():
        if date <= current_date < date + timedelta(days=20):
            current_stage = stage
            break

    if not current_stage:
        bot.send_message(user_id, "Hozirda test topshirish vaqti emas.")
        return

    # Foydalanuvchi ushbu bosqichni allaqachon topshirganligini tekshirish
    cursor.execute("SELECT completed_stages FROM users WHERE user_id=?", (user_id,))
    completed_stages = cursor.fetchone()[0]

    if str(current_stage) in (completed_stages or ''):
        bot.send_message(user_id, f"Siz {current_stage}-bosqichni allaqachon tugatgansiz va unga qayta kirish mumkin emas. \n \"⬅️ Orqaga\" tugmasi orqali asosiy menyuga qayting!")
    else:
        # Natijalarni yangilash va bosqichni "yopilgan" deb belgilash
        column_name = f"stage_{current_stage}_score"
        updated_stages = (completed_stages or '') + f",{current_stage}" if completed_stages else str(current_stage)
        cursor.execute(f"UPDATE users SET {column_name}=?, total_score=total_score + ?, completed_stages=? WHERE user_id=?",
                       (score, score, updated_stages, user_id))
        conn.commit()
        bot.send_message(user_id, f"Tabriklaymiz! {current_stage}-bosqichda {score} ball to'pladingiz. \n \"⬅️ Orqaga\" tugmasi orqali asosiy menyuga qayting!")

# Foydalanuvchidan telefon raqamini so'rash
def request_phone_number(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    button = types.KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)
    markup.add(button)
    bot.send_message(user_id, "Iltimos, telefon raqamingizni yuboring:", reply_markup=markup)

# Foydalanuvchining kanallarga obuna bo'lganligini tekshirish
def check_subscription(user_id):
    not_subscribed = []
    
    for channel in REQUIRED_CHANNELS:
        try:
            chat_member = bot.get_chat_member(f"@{channel['username']}", user_id)
            # Foydalanuvchi kanalga obuna bo'lmagan bo'lsa
            if chat_member.status in ['left', 'kicked', 'restricted']:
                not_subscribed.append(channel)
        except ApiException as e:
            print(f"Kanal tekshirishda xatolik: {e}")
            # Xatolik yuz berganda, foydalanuvchi obuna bo'lmagan deb hisoblaymiz
            not_subscribed.append(channel)
    
    return not_subscribed

# Obuna bo'lmagan kanallar uchun xabar va tugmalar ko'rsatish
def show_subscription_message(user_id, not_subscribed_channels):
    message_text = "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:\n\n"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Har bir kanal uchun tugma qo'shish
    for channel in not_subscribed_channels:
        message_text += f"• @{channel['username']}\n"
        markup.add(types.InlineKeyboardButton(f"➡️ @{channel['username']}", url=channel['link']))
    
    # Tekshirish tugmasini qo'shish
    markup.add(types.InlineKeyboardButton("✅ Men obuna bo'ldim", callback_data="check_subscription"))
    
    bot.send_message(user_id, message_text, reply_markup=markup)

# Foydalanuvchi telefon raqamini qabul qilish
@bot.message_handler(content_types=['contact'])
def process_phone_number(message):
    user_id = message.from_user.id
    phone_number = message.contact.phone_number
    # Foydalanuvchi ma'lumotlarini tekshirish
    if not user_data.get(user_id):
        bot.send_message(user_id, "Iltimos, avval ro'yxatdan o'ting.")
        return
    
    # Ma'lumotlarni SQLite ma'lumotlar bazasiga saqlash
    try:
        cursor.execute("INSERT INTO users (user_id, full_name, phone_number, status, region) VALUES (?, ?, ?, ?, ?)",
                       (user_id, user_data[user_id]['full_name'], phone_number, user_data[user_id]['status'], user_data[user_id]['region']))
        conn.commit()
        bot.send_message(user_id, "Tabriklaymiz! Siz muvaffaqiyatli ro'yxatdan o'tdingiz.")
        
        # Kanallarga obuna bo'lganlikni tekshirish
        not_subscribed_channels = check_subscription(user_id)
        
        if not_subscribed_channels:
            # Agar foydalanuvchi barcha kanallarga obuna bo'lmagan bo'lsa
            show_subscription_message(user_id, not_subscribed_channels)
        else:
            # Agar foydalanuvchi barcha kanallarga obuna bo'lgan bo'lsa
            show_main_menu(message)
    except sqlite3.IntegrityError:
        bot.send_message(user_id, "Siz allaqachon ro'yxatdan o'tgansiz.")
        
        # Kanallarga obuna bo'lganlikni tekshirish
        not_subscribed_channels = check_subscription(user_id)
        
        if not_subscribed_channels:
            # Agar foydalanuvchi barcha kanallarga obuna bo'lmagan bo'lsa
            show_subscription_message(user_id, not_subscribed_channels)
        else:
            # Agar foydalanuvchi barcha kanallarga obuna bo'lgan bo'lsa
            show_main_menu(message)
    except KeyError:
        bot.send_message(user_id, "Kechirasiz, xatolik yuz berdi. Iltimos, qaytadan ro'yxatdan o'ting.")
    except Exception as e:
        print(f"Telefon raqamini qayta ishlashda xatolik: {e}")
        bot.send_message(user_id, "Kechirasiz, telefon raqamini qayta ishlashda xatolik yuz berdi.")


# Asosiy menyu
def show_main_menu(message):
    user_id = message.chat.id

    # Foydalanuvchining tugallangan bosqichlarini tekshirish
    cursor.execute("SELECT completed_stages FROM users WHERE user_id=?", (user_id,))
    completed_stages = cursor.fetchone()[0] or ''

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📚 Test savollarini ishlash"))
    markup.add(types.KeyboardButton("🏆 Ballar"), types.KeyboardButton("📜 Tanlov nizomi"))
    markup.add(types.KeyboardButton("📢 Tanlovga taklif qilish"), types.KeyboardButton("📖 Tanlov kitoblari"))
    bot.send_message(message.chat.id, "Asosiy menyu:", reply_markup=markup)


# "Test savollarini ishlash" tugmasi uchun funksiya
@bot.message_handler(func=lambda message: message.text == "📚 Test savollarini ishlash")
def handle_test_button(message):
    user_id = message.chat.id

    # Hozirgi bosqichni aniqlash
    current_date = datetime.now()
    current_stage = None
    for stage, date in STAGES.items():
        if date <= current_date < date + timedelta(days=20):  # Har bir bosqich muddati 20 kun
            current_stage = stage
            break

    if not current_stage:
        bot.send_message(user_id, "Hozirda test topshirish vaqti emas.")
        return

    # Foydalanuvchi ushbu bosqichni allaqachon topshirganligini tekshirish
    cursor.execute("SELECT completed_stages FROM users WHERE user_id=?", (user_id,))
    completed_stages = cursor.fetchone()[0]
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    for stage in STAGES:
        # Test sanasini tekshirish
        test_date = TEST_DATES.get(stage)
        test_end_date = test_date + timedelta(days=TEST_DURATION) if test_date else None
        
        if str(stage) in (completed_stages or ''):
            markup.add(types.KeyboardButton(f"{stage}-bosqich (tugatilgan)"))  # Tugallangan bosqichlar uchun tugma
        elif stage == current_stage and test_date and current_date >= test_date and current_date < test_end_date:
            markup.add(types.KeyboardButton(f"{stage}-bosqichni boshlash"))  # Joriy bosqich uchun tugma (test vaqti kelgan)
        elif stage == current_stage and test_date and current_date >= test_end_date:
            markup.add(types.KeyboardButton(f"{stage}-bosqich (test tugagan)"))  # Test muddati tugagan
        else:
            markup.add(types.KeyboardButton(f"{stage}-bosqich"))  # Boshqa bosqichlar uchun tugma
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    bot.send_message(user_id, "Bosqichni tanlang:", reply_markup=markup)
   

# Bosqichlarni boshlash uchun message handlerlar
@bot.message_handler(func=lambda message: message.text.endswith("-bosqichni boshlash"))
def handle_start_stage(message):
    user_id = message.chat.id
    stage = int(message.text.split("-")[0])  # Bosqich raqamini olish
    
    # Test sanasini tekshirish
    current_date = datetime.now()
    test_date = TEST_DATES.get(stage)
    test_end_date = test_date + timedelta(days=TEST_DURATION) if test_date else None
    
    # Test vaqti kelgan va tugamaganligini tekshirish
    if not test_date or current_date < test_date or current_date >= test_end_date:
        bot.send_message(user_id, f"{stage}-bosqich testi hozirda mavjud emas.")
        return
    
    # Test URL manzilini belgilash
    web_app = types.WebAppInfo(test_url_base)

    # InlineKeyboardMarkup o'rniga ReplyKeyboardMarkup ishlatamiz
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Testni boshlash", web_app=web_app))  # KeyboardButton ishlatamiz
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    bot.send_message(user_id, f"{stage}-bosqich testini boshlash uchun quyidagi tugmani bosing:", reply_markup=markup)

# Tugallangan bosqichlar uchun message handler
@bot.message_handler(func=lambda message: message.text.endswith("(tugatilgan)"))
def handle_completed_stage(message):
    user_id = message.chat.id
    stage = int(message.text.split("-")[0])  # Bosqich raqamini olish
    bot.send_message(user_id, f"Siz {stage}-bosqichni allaqachon tugatgansiz.")

# Test tugagan bosqichlar uchun message handler
@bot.message_handler(func=lambda message: message.text.endswith("(test tugagan)"))
def handle_expired_test(message):
    user_id = message.chat.id
    stage = int(message.text.split("-")[0])  # Bosqich raqamini olish
    bot.send_message(user_id, f"{stage}-bosqich test sinovi tugagan.")

# Boshqa bosqichlar uchun message handler
@bot.message_handler(func=lambda message: message.text.endswith("-bosqich") and not message.text.endswith("(tugatilgan)") and not message.text.endswith("-bosqichni boshlash") and not message.text.endswith("(test tugagan)"))
def handle_other_stage(message):
    user_id = message.chat.id
    stage = int(message.text.split("-")[0])  # Bosqich raqamini olish
    
    # Test sanasini tekshirish
    current_date = datetime.now()
    test_date = TEST_DATES.get(stage)
    
    if test_date and current_date < test_date:
        # Test sanasiga qancha vaqt qolganini hisoblash
        days_left = (test_date - current_date).days
        bot.send_message(user_id, f"{stage}-bosqich test sinoviga {days_left} kun qoldi.")
    else:
        bot.send_message(user_id, f"{stage}-bosqich hali boshlanmagan yoki muddati tugagan.")


# Foydalanuvchining ballarini ko'rsatish
@bot.message_handler(func=lambda message: message.text == "🏆 Ballar")
def handle_score_button(message):
    user_id = message.chat.id

    cursor.execute("SELECT full_name, total_score FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        full_name, total_score = user_data
        bot.send_message(user_id, f"{full_name}\nSizning jami ballaringiz: {total_score}")
    else:
        bot.send_message(user_id, "Siz hali ro'yxatdan o'tmagansiz.")


# "Tanlov nizomi" tugmasi uchun funksiya
@bot.message_handler(func=lambda message: message.text == "📜 Tanlov nizomi")
def handle_rules_button(message):
    # Inline keyboard yaratish
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(
        types.InlineKeyboardButton("🌐 Tanlov nizomi (online)", url="https://docs.google.com/document/d/1jfQ9GCqkRXm5pQ3wHzoIH2tSY2DCtj_I/edit?usp=sharing&ouid=106866327278894716768&rtpof=true&sd=true"),
        types.InlineKeyboardButton("📄 Tanlov nizomi (fayl)", callback_data="rules_file")
    )
    bot.send_message(message.chat.id, "Tanlov nizomi bilan tanishish uchun quyidagi tugmalardan birini bosing:", reply_markup=inline_markup)


# "Tanlov nizomi (fayl)" tugmasi uchun funksiya (inline)
@bot.callback_query_handler(func=lambda call: call.data == "rules_file")
def handle_rules_file_callback(call):
    # Faylni yuborish
    try:
        with open("tanlov_nizomi.pdf", "rb") as rules_file:  # Fayl nomini o'zgartiring
            bot.send_document(call.message.chat.id, rules_file)
    except FileNotFoundError:
        bot.send_message(call.message.chat.id, "Kechirasiz, fayl topilmadi.")
    bot.answer_callback_query(call.id)

# "Men obuna bo'ldim" tugmasi uchun funksiya
@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def handle_check_subscription(call):
    user_id = call.from_user.id
    
    # Kanallarga obuna bo'lganlikni qayta tekshirish
    not_subscribed_channels = check_subscription(user_id)
    
    if not_subscribed_channels:
        # Agar foydalanuvchi hali ham barcha kanallarga obuna bo'lmagan bo'lsa
        bot.answer_callback_query(call.id, "Siz hali barcha kanallarga obuna bo'lmagansiz!")
        # Xabarni yangilash
        show_subscription_message(user_id, not_subscribed_channels)
    else:
        # Agar foydalanuvchi barcha kanallarga obuna bo'lgan bo'lsa
        bot.answer_callback_query(call.id, "Tabriklaymiz! Siz barcha kanallarga obuna bo'ldingiz!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        # Asosiy menyuni ko'rsatish
        show_main_menu(call.message)


# "Tanlovga taklif qilish" tugmasi uchun funksiya
@bot.message_handler(func=lambda message: message.text == "📢 Tanlovga taklif qilish")
def handle_invite_button(message):
    # Online linkni yaratish
    invite_link = f"https://t.me/{bot.get_me().username}?start=referral_{message.chat.id}"

    # Linkni yuborish
    bot.send_message(message.chat.id, f"Do'stlaringizni tanlovga taklif qilish uchun quyidagi linkni ulashing:\n{invite_link}")


# "Tanlov kitoblari" tugmasi uchun funksiya
@bot.message_handler(func=lambda message: message.text == "📖 Tanlov kitoblari")
def handle_books_button(message):
    # Kitoblar ro'yxati va ularning fayllarini bu yerga qo'ying
    books = {
        "1-bosqich": [
            ("1.Said Ahmad  “Ufq” romani.pdf", "Said Ahmad  “Ufq” romani"),
            ("2.Oybek “Qutlug' qon” romani.pdf", "Oybek “Qutlug' qon” romani")
        ],
        "2-bosqich": [
            ("3.Cho'lpon  “Kecha va kunduz” romani.pdf", "Cho'lpon  “Kecha va kunduz” romani"),
            ("4.Ernest Seton Tompson. Yovvoyi yo'rg'a (hikoyalar).PDF", "Ernest Seton Tompson. Yovvoyi yo'rg'a (hikoyalar)")
        ],
        "3-bosqich": [
            ("5.Azamat KORJOVOV “Musofir go'dak qismati”.pdf", "Azamat KORJOVOV “Musofir go'dak qismati”"),
            ("6.YASHAMOQ (Yuy Xua).pdf", "YASHAMOQ (Yuy Xua)")
        ],
        "4-bosqich": [
            ("7.Ernest Xeminguey. Chol va dengiz (qissa).pdf", "Ernest Xeminguey. Chol va dengiz (qissa)"),
            ("8.Azamat KORJOVOV “Musofir go'dak qismati” 2-qism.pdf", "Azamat KORJOVOV “Musofir go'dak qismati” 2-qism")
        ]
    }

    for stage, books_in_stage in books.items():
        books_text = f"{stage}:\n"
        for filename, book_name in books_in_stage:
            try:
                with open(filename, "rb") as book_file:
                    bot.send_document(message.chat.id, book_file, caption=book_name)
            except FileNotFoundError:
                bot.send_message(message.chat.id, f"Kechirasiz, {book_name} fayli topilmadi.")
            books_text += f"- {book_name}\n"
        bot.send_message(message.chat.id, books_text)


@bot.message_handler(commands=['admin2308'])
def show_admin_panel(message):
    # Admin panelini ko'rsatish
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🗂 Ma'lumotlarni export qilish"))
    markup.add(types.KeyboardButton("👤 Foydalanuvchilar ma'lumotlari"))
    markup.add(types.KeyboardButton("🔎 Qidirish"))
    markup.add(types.KeyboardButton("⬅️ Orqaga"))
    bot.send_message(message.chat.id, "Admin paneli:", reply_markup=markup)


# Foydalanuvchi ma'lumotlarini ko'rsatish
def show_user_data(message, index, users):
    try:
        user = users[index]
        # Foydalanuvchi ma'lumotlarini formatlash
        user_info = f"ID: {user[0]}\nIsm-familiya: {user[1]}\nHolati: {user[2]}\nHududi: {user[3]}\nTelefon raqami: {user[4]}\nBallar: {user[5]}"

        # Inline tugmalar yaratish
        markup = types.InlineKeyboardMarkup()
        if index > 0:
            markup.add(types.InlineKeyboardButton("⬅️ Oldingi", callback_data=f"prev_{index}"))
        if index < len(users) - 1:
            markup.add(types.InlineKeyboardButton("Keyingi ➡️", callback_data=f"next_{index}"))
        markup.add(types.InlineKeyboardButton("Tahrirlash ✏️", callback_data=f"edit_{user[0]}"))

        bot.send_message(message.chat.id, user_info, reply_markup=markup)
    except Exception as e:
        print(f"Foydalanuvchi ma'lumotlarini ko'rsatishda xatolik: {e}")
        bot.send_message(message.chat.id, "Kechirasiz, foydalanuvchi ma'lumotlarini ko'rsatishda xatolik yuz berdi.")


@bot.message_handler(func=lambda message: message.text == "👤 Foydalanuvchilar ma'lumotlari")
def show_users_data(message):
    try:
        # Foydalanuvchilar ro'yxatini ma'lumotlar bazasidan olish
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()

        if users:
            # Birinchi foydalanuvchi ma'lumotlarini ko'rsatish
            show_user_data(message, 0, users)

            # Inline tugmalar uchun callback query
            @bot.callback_query_handler(func=lambda call: call.data.startswith("next_") or call.data.startswith("prev_") or call.data.startswith("edit_"))
            def handle_user_data_callback(call):
                try:
                    data = call.data.split("_")
                    action = data[0]  # "next", "prev", "edit"
                    index = int(data[1]) if action != "edit" else None
                    user_id = int(data[1]) if action == "edit" else None

                    if action == "next":
                        show_user_data(call.message, index + 1, users)
                    elif action == "prev":
                        show_user_data(call.message, index - 1, users)
                    elif action == "edit":
                        # Foydalanuvchi ma'lumotlarini olish
                        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
                        user = cursor.fetchone()

                        # Tahrirlash tugmalari bilan yangi xabar yuborish
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("Ism-familiya", callback_data=f"edit_name_{user_id}"))
                        markup.add(types.InlineKeyboardButton("Holati", callback_data=f"edit_status_{user_id}"))
                        markup.add(types.InlineKeyboardButton("Hududi", callback_data=f"edit_region_{user_id}"))
                        markup.add(types.InlineKeyboardButton("Telefon raqami", callback_data=f"edit_phone_{user_id}"))
                        bot.send_message(call.message.chat.id, "Tahrirlamoqchi bo'lgan maydonni tanlang:", reply_markup=markup)
                except Exception as e:
                    print(f"Foydalanuvchi ma'lumotlarini qayta ishlashda xatolik: {e}")
                    bot.send_message(call.message.chat.id, "Kechirasiz, foydalanuvchi ma'lumotlarini qayta ishlashda xatolik yuz berdi.")
                finally:
                    bot.answer_callback_query(call.id)
        else:
            bot.send_message(message.chat.id, "Hali ro'yxatdan o'tgan foydalanuvchilar yo'q.")
    except Exception as e:
        print(f"Foydalanuvchilar ma'lumotlarini ko'rsatishda xatolik: {e}")
        bot.send_message(message.chat.id, "Kechirasiz, foydalanuvchilar ma'lumotlarini ko'rsatishda xatolik yuz berdi.")


# Tahrirlash tugmalari uchun callback query
@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_name_") or call.data.startswith("edit_status_") or call.data.startswith("edit_region_") or call.data.startswith("edit_phone_"))
def handle_edit_callback(call):
    try:
        action, field, user_id = call.data.split("_")
        user_id = int(user_id)

        msg = bot.send_message(call.message.chat.id, f"Yangi qiymatni kiriting:")
        bot.register_next_step_handler(msg, save_edited_user_data, user_id, field)
    except Exception as e:
        print(f"Tahrirlash tugmalarini qayta ishlashda xatolik: {e}")
        bot.send_message(call.message.chat.id, "Kechirasiz, tahrirlash tugmalarini qayta ishlashda xatolik yuz berdi.")
    finally:
        bot.answer_callback_query(call.id)


def save_edited_user_data(message, user_id, field):
    new_value = message.text

    try:
        if field == "name":
            cursor.execute("UPDATE users SET full_name=? WHERE user_id=?", (new_value, user_id))
        elif field == "status":
            cursor.execute("UPDATE users SET status=? WHERE user_id=?", (new_value, user_id))
        elif field == "region":
            cursor.execute("UPDATE users SET region=? WHERE user_id=?", (new_value, user_id))
        elif field == "phone":
            # Telefon raqamini tekshirish (soddalashtirilgan tekshirish)
            if len(new_value) != 13 or not new_value.startswith('+998'):
                bot.send_message(message.chat.id, "Telefon raqami noto'g'ri formatda. Iltimos, +998 bilan boshlanuvchi 13 ta belgidan iborat raqamni kiriting.")
                return
            cursor.execute("UPDATE users SET phone_number=? WHERE user_id=?", (new_value, user_id))
        conn.commit()
        bot.send_message(message.chat.id, "Ma'lumotlar muvaffaqiyatli yangilandi!")
    except Exception as e:
        print(f"Ma'lumotlarni yangilashda xatolik: {e}")
        bot.send_message(message.chat.id, "Ma'lumotlarni yangilashda xatolik yuz berdi.")


@bot.message_handler(func=lambda message: message.text == "🗂 Ma'lumotlarni export qilish")
def export_data(message):
    try:
        # Excel faylini yaratish
        wb = Workbook()
        ws = wb.active
        ws.title = "Foydalanuvchilar"

        # Ustun nomlarini yozish
        ws.append(["ID", "Ism-familiya", "Holati", "Hududi", "Telefon raqami", "1-bosqich", "2-bosqich", "3-bosqich", "4-bosqich", "Jami ball", "Tugallangan bosqichlar"])

        # Ma'lumotlarni ma'lumotlar bazasidan olish
        cursor.execute("SELECT user_id, full_name, status, region, phone_number, stage_1_score, stage_2_score, stage_3_score, stage_4_score, total_score, completed_stages FROM users")
        users = cursor.fetchall()

        # Ma'lumotlarni Excel fayliga yozish
        for user in users:
            ws.append(user)

        # Faylni saqlash
        wb.save("foydalanuvchilar.xlsx")

        # Faylni foydalanuvchiga yuborish
        with open("foydalanuvchilar.xlsx", "rb") as excel_file:
            bot.send_document(message.chat.id, excel_file)
    except Exception as e:
        print(f"Ma'lumotlarni export qilishda xatolik: {e}")
        bot.send_message(message.chat.id, "Ma'lumotlarni export qilishda xatolik yuz berdi.")


@bot.message_handler(commands=['people'])
def send_people_count(message):
    try:
        # Foydalanuvchilar sonini ma'lumotlar bazasidan olish
        cursor.execute("SELECT COUNT(*) FROM users")
        people_count = cursor.fetchone()[0]

        bot.reply_to(message, f"Botdan jami {people_count} ta foydalanuvchi ro'yxatdan o'tgan.")
    except Exception as e:
        print(f"Foydalanuvchilar sonini olishda xatolik: {e}")
        bot.send_message(message.chat.id, "Kechirasiz, foydalanuvchilar sonini olishda xatolik yuz berdi.")


@bot.message_handler(func=lambda message: message.text == "🔎 Qidirish")
def search_user(message):
    msg = bot.send_message(message.chat.id, "Qidirmoqchi bo'lgan foydalanuvchining ism-familiyasini yoki Telegram ID'sini kiriting:")
    bot.register_next_step_handler(msg, process_search_query)


def process_search_query(message):
    search_query = message.text
    try:
        # Foydalanuvchini ism-familiya yoki ID bo'yicha qidirish
        cursor.execute("SELECT * FROM users WHERE full_name LIKE ? OR user_id=?", (f"%{search_query}%", search_query))
        user = cursor.fetchone()

        if user:
            # Foydalanuvchi ma'lumotlarini formatlash
            user_info = f"ID: {user[0]}\nIsm-familiya: {user[1]}\nHolati: {user[2]}\nHududi: {user[3]}\nTelefon raqami: {user[4]}\nBallar: {user[5]}"
            bot.send_message(message.chat.id, user_info)
        else:
            bot.send_message(message.chat.id, "Foydalanuvchi topilmadi.")
    except Exception as e:
        print(f"Foydalanuvchini qidirishda xatolik: {e}")
        bot.send_message(message.chat.id, "Kechirasiz, foydalanuvchini qidirishda xatolik yuz berdi.")


# Orqaga qaytish tugmasi uchun message handler
@bot.message_handler(func=lambda message: message.text == "⬅️ Orqaga")
def back_to_main_handler(message):
    show_main_menu(message)


# Testdan oldin eslatma yuborish funksiyasi
def send_test_notifications():
    current_date = datetime.now()
    
    # Barcha bosqichlar uchun tekshirish
    for stage, test_date in TEST_DATES.items():
        # Testga 3 kun yoki undan kam qolgan bo'lsa
        days_left = (test_date - current_date).days
        if days_left in NOTIFICATION_DAYS:
            # Foydalanuvchilarni olish
            cursor.execute("SELECT user_id, notification_sent FROM users")
            users = cursor.fetchall()
            
            for user in users:
                user_id = user[0]
                notification_sent = user[1] or ''
                
                # Bugungi sana uchun eslatma yuborilmaganligini tekshirish
                notification_key = f"{stage}_{days_left}"
                if notification_key not in notification_sent:
                    # Eslatma yuborish
                    bot.send_message(user_id, f"⚠️ Eslatma: {stage}-bosqich test sinoviga {days_left} kun qoldi! Test sanasi: {test_date.strftime('%d.%m.%Y')}")
                    
                    # Eslatma yuborilganligini qayd etish
                    new_notification_sent = notification_sent + f",{notification_key}" if notification_sent else notification_key
                    cursor.execute("UPDATE users SET notification_sent=? WHERE user_id=?", (new_notification_sent, user_id))
                    conn.commit()

# Eslatmalarni yuborish uchun scheduler
def notification_scheduler():
    while True:
        try:
            send_test_notifications()
            print(f"Eslatmalar tekshirildi: {datetime.now()}")
        except Exception as e:
            print(f"Eslatma yuborishda xatolik: {e}")
        
        # Har 12 soatda bir marta tekshirish (43200 sekund = 12 soat)
        time.sleep(43200)

# Notification scheduler-ni alohida thread sifatida ishga tushirish
notification_thread = threading.Thread(target=notification_scheduler)
notification_thread.daemon = True  # Asosiy dastur tugaganda thread ham tugaydi
notification_thread.start()

bot.polling()