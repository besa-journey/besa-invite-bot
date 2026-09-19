import os
import logging
import sqlite3
from datetime import datetime
from telegram import (
    Update, ChatMemberUpdated, ChatMember, ChatInviteLink,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, ChatMemberHandler,
    ChatJoinRequestHandler, ContextTypes, filters,
    CallbackQueryHandler, MessageHandler, ConversationHandler
)

# ==================== تنظیمات ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
POINTS_PER_INVITE = int(os.getenv("POINTS_PER_INVITE", "10"))
WELCOME_IN_GROUP = os.getenv("WELCOME_IN_GROUP", "true").lower() == "true"
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# ==================== لاگ ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = "bot_data.db"

# ==================== دیتابیس ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # جدول کاربران
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            points INTEGER DEFAULT 0,
            invites INTEGER DEFAULT 0,
            invite_link_group TEXT,
            invite_link_channel TEXT,
            created_at TEXT
        )
    """)
    
    # جدول دعوت‌ها
    c.execute("""
        CREATE TABLE IF NOT EXISTS joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            joined_user_id INTEGER,
            chat_id INTEGER,
            chat_type TEXT,
            joined_at TEXT,
            UNIQUE(joined_user_id, chat_id)
        )
    """)
    
    # جدول تورها
    c.execute("""
        CREATE TABLE IF NOT EXISTS tours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            location TEXT,
            date TEXT,
            capacity INTEGER DEFAULT 0,
            price INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TEXT
        )
    """)
    
    # جدول ثبت‌نام‌ها
    c.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tour_id INTEGER,
            user_id INTEGER,
            full_name TEXT,
            age INTEGER,
            city TEXT,
            phone TEXT,
            national_id TEXT,
            gender TEXT,
            email TEXT,
            payment_status TEXT DEFAULT 'pending',
            payment_receipt TEXT,
            registered_at TEXT,
            UNIQUE(tour_id, user_id)
        )
    """)
    
    # جدول نظرسنجی‌ها
    c.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TEXT
        )
    """)
    
    # جدول رأی‌ها
    c.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER,
            user_id INTEGER,
            option_index INTEGER,
            voted_at TEXT,
            UNIQUE(poll_id, user_id)
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("دیتابیس آماده شد.")


def db_execute(query, params=(), fetch=False, fetchall=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    result = None
    if fetch:
        result = c.fetchone()
    elif fetchall:
        result = c.fetchall()
    else:
        conn.commit()
    conn.close()
    return result


# ==================== توابع کاربر ====================
def get_user(user_id: int):
    return db_execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetch=True)


def create_or_update_user(user_id: int, username: str, full_name: str):
    existing = get_user(user_id)
    if not existing:
        db_execute(
            "INSERT INTO users (user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, datetime.now().isoformat())
        )
    else:
        db_execute(
            "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
            (username, full_name, user_id)
        )


def save_link(user_id: int, link: str, chat_type: str):
    col = "invite_link_group" if chat_type == "group" else "invite_link_channel"
    db_execute(f"UPDATE users SET {col} = ? WHERE user_id = ?", (link, user_id))


def add_points(user_id: int, points: int = POINTS_PER_INVITE):
    db_execute(
        "UPDATE users SET points = points + ?, invites = invites + 1 WHERE user_id = ?",
        (points, user_id)
    )


def record_join(inviter_id: int, joined_user_id: int, chat_id: int, chat_type: str) -> bool:
    try:
        db_execute(
            "INSERT INTO joins (inviter_id, joined_user_id, chat_id, chat_type, joined_at) VALUES (?, ?, ?, ?, ?)",
            (inviter_id, joined_user_id, chat_id, chat_type, datetime.now().isoformat())
        )
        return True
    except sqlite3.IntegrityError:
        return False


def get_top_users(limit: int = 10):
    return db_execute(
        "SELECT user_id, full_name, username, points, invites FROM users ORDER BY points DESC LIMIT ?",
        (limit,), fetchall=True
    )


def find_inviter_by_link_name(link_name: str):
    try:
        return int(link_name)
    except (ValueError, TypeError):
        return None


# ==================== توابع تور ====================
def create_tour(title, description, location, date, capacity, price, created_by):
    db_execute(
        """INSERT INTO tours (title, description, location, date, capacity, price, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, location, date, capacity, price, created_by, datetime.now().isoformat())
    )


def get_active_tours():
    return db_execute(
        "SELECT * FROM tours WHERE is_active = 1 ORDER BY date ASC",
        fetchall=True
    )


def get_tour(tour_id):
    return db_execute("SELECT * FROM tours WHERE id = ?", (tour_id,), fetch=True)


def get_tour_registrations(tour_id):
    return db_execute(
        """SELECT r.*, u.username FROM registrations r
           LEFT JOIN users u ON r.user_id = u.user_id
           WHERE r.tour_id = ? ORDER BY r.registered_at ASC""",
        (tour_id,), fetchall=True
    )


def get_user_registrations(user_id):
    return db_execute(
        """SELECT r.*, t.title, t.date, t.location FROM registrations r
           JOIN tours t ON r.tour_id = t.id
           WHERE r.user_id = ? ORDER BY t.date ASC""",
        (user_id,), fetchall=True
    )


def is_registered(tour_id, user_id):
    result = db_execute(
        "SELECT id FROM registrations WHERE tour_id = ? AND user_id = ?",
        (tour_id, user_id), fetch=True
    )
    return result is not None


# ==================== توابع نظرسنجی ====================
def create_poll(question, options, created_by):
    import json
    db_execute(
        "INSERT INTO polls (question, options, created_by, created_at) VALUES (?, ?, ?, ?)",
        (question, json.dumps(options, ensure_ascii=False), created_by, datetime.now().isoformat())
    )


def get_active_polls():
    return db_execute("SELECT * FROM polls WHERE is_active = 1 ORDER BY id DESC", fetchall=True)


def get_poll(poll_id):
    return db_execute("SELECT * FROM polls WHERE id = ?", (poll_id,), fetch=True)


def has_voted(poll_id, user_id):
    result = db_execute(
        "SELECT id FROM poll_votes WHERE poll_id = ? AND user_id = ?",
        (poll_id, user_id), fetch=True
    )
    return result is not None


def save_vote(poll_id, user_id, option_index):
    try:
        db_execute(
            "INSERT INTO poll_votes (poll_id, user_id, option_index, voted_at) VALUES (?, ?, ?, ?)",
            (poll_id, user_id, option_index, datetime.now().isoformat())
        )
        return True
    except sqlite3.IntegrityError:
        return False


def get_poll_results(poll_id):
    return db_execute(
        "SELECT option_index, COUNT(*) FROM poll_votes WHERE poll_id = ? GROUP BY option_index",
        (poll_id,), fetchall=True
    )
# ==================== توابع کمکی ====================
async def create_invite_link(context, chat_id: int, user_id: int, chat_type: str):
    kwargs = {
        "chat_id": int(chat_id),
        "name": str(user_id),
    }
    if chat_type == "channel":
        kwargs["creates_join_request"] = True
        kwargs["member_limit"] = 1
    else:
        kwargs["creates_join_request"] = False

    invite = await context.bot.create_chat_invite_link(**kwargs)
    save_link(user_id, invite.invite_link, chat_type)
    return invite.invite_link


# ==================== دستورات پایه ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    text = (
        f"🌿 به BESA خوش اومدی، {user.first_name}!\n\n"
        "اینجا قراره طبیعت، هنر، تجربه و آدم‌های خوب رو کنار هم ببینیم.\n"
        "تورهای طبیعت‌گردی، برنامه‌های هنری و آموزش مهارت‌های اجتماعی و تجربه‌های متفاوت؛\n\n"
        "نزدیک به طبیعت، نزدیک به خودت. ✨\n\n"
        "با ما همراه باش؛ تازه شروعشه...\n\n"
        "📱 اینستاگرام: Besa.tabiatgardi\n"
        "🎬 یوتیوب: https://youtube.com/@besajourney\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 دستورات اصلی:\n"
        "🔗 /mylink — لینک دعوت گروه\n"
        "🔗 /mylink_channel — لینک دعوت کانال\n"
        "📊 /stats — امتیاز و دعوت‌هات\n"
        "🏆 /top — رتبه‌بندی برترین‌ها\n"
        "🎒 /tours — لیست تورها\n"
        "📝 /myregistrations — تورهای من\n"
        "📊 /polls — نظرسنجی‌ها\n"
        "📖 /help — راهنما"
    )
    await update.message.reply_text(text)


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    if not GROUP_ID:
        await update.message.reply_text("❌ گروه تنظیم نشده.")
        return

    existing = get_user(user.id)
    if existing and existing[5]:
        await update.message.reply_text(
            f"🔗 لینک اختصاصی گروه تو:\n\n{existing[5]}\n\n"
            "با این لینک دوستات رو به گروه دعوت کن! 🎯"
        )
        return

    try:
        link = await create_invite_link(context, GROUP_ID, user.id, "group")
        await update.message.reply_text(
            f"✅ لینک اختصاصی گروه تو:\n\n{link}\n\n"
            "هر کی با این لینک بیاد، امتیاز می‌گیری! 🎯"
        )
    except Exception as e:
        logger.error(f"Error creating group link: {e}")
        await update.message.reply_text(
            "❌ نتونستم لینک بسازم.\n"
            "مطمئن شو ربات ادمین گروهه و دسترسی «دعوت کاربران» داره."
        )


async def mylink_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    if not CHANNEL_ID:
        await update.message.reply_text("❌ کانال تنظیم نشده.")
        return

    existing = get_user(user.id)
    if existing and existing[6]:
        await update.message.reply_text(
            f"🔗 لینک اختصاصی کانال تو:\n\n{existing[6]}\n\n"
            "⚠️ این لینک فقط برای یه نفره. بعد از اینکه یکی عضو شد، /newlink_channel بزن."
        )
        return

    try:
        link = await create_invite_link(context, CHANNEL_ID, user.id, "channel")
        await update.message.reply_text(
            f"✅ لینک اختصاصی کانال تو:\n\n{link}\n\n"
            "⚠️ این لینک فقط یه نفر رو می‌تونه بیاره.\n"
            "بعد از هر دعوت موفق، /newlink_channel بزن."
        )
    except Exception as e:
        logger.error(f"Error creating channel link: {e}")
        await update.message.reply_text(
            "❌ نتونستم لینک کانال بسازم.\n"
            "مطمئن شو ربات ادمین کاناله و دسترسی «دعوت کاربران» داره."
        )


async def newlink_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    if not CHANNEL_ID:
        await update.message.reply_text("❌ کانال تنظیم نشده.")
        return

    try:
        link = await create_invite_link(context, CHANNEL_ID, user.id, "channel")
        await update.message.reply_text(
            f"✅ لینک جدید کانال:\n\n{link}\n\n"
            "این لینک فقط یه نفر رو میاره."
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ خطا در ساخت لینک جدید.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)
    data = get_user(user.id)

    if not data:
        await update.message.reply_text("هنوز اطلاعاتی نداری. اول /start بزن.")
        return

    text = (
        f"📊 آمار تو:\n\n"
        f"👤 نام: {data[2]}\n"
        f"⭐ امتیاز: {data[3]}\n"
        f"👥 تعداد دعوت موفق: {data[4]}\n\n"
        f"🔗 لینک گروه:\n{data[5] or 'نداری'}\n\n"
        f"🔗 لینک کانال:\n{data[6] or 'نداری'}"
    )
    await update.message.reply_text(text)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_top_users(10)
    if not rows:
        await update.message.reply_text("هنوز کسی دعوت نکرده!")
        return

    text = "🏆 رتبه‌بندی برترین دعوت‌کننده‌ها:\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows, 1):
        user_id, full_name, username, points, invites = row
        name = full_name or (f"@{username}" if username else f"User {user_id}")
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {name} — {points} امتیاز ({invites} دعوت)\n"

    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 راهنمای ربات BESA:\n\n"
        "🎯 *دعوت و امتیاز:*\n"
        "/mylink — لینک دعوت گروه\n"
        "/mylink_channel — لینک دعوت کانال\n"
        "/newlink_channel — لینک جدید کانال\n"
        "/stats — آمار تو\n"
        "/top — برترین‌ها\n\n"
        "🎒 *تورها:*\n"
        "/tours — لیست تورهای فعال\n"
        "/myregistrations — تورهای من\n"
        "/cancelreg — لغو ثبت‌نام\n\n"
        "📊 *نظرسنجی:*\n"
        "/polls — لیست نظرسنجی‌ها\n\n"
        "📖 /help — همین پیام"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
