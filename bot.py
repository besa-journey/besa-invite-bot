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
# ==================== ساخت لینک و خوش‌آمد ====================
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


# ==================== تشخیص ورود عضو ====================
def extract_status_change(chat_member_update: ChatMemberUpdated):
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [ChatMember.MEMBER, ChatMember.OWNER, ChatMember.ADMINISTRATOR] \
                 or (old_status == ChatMember.RESTRICTED and old_is_member)
    is_member = new_status in [ChatMember.MEMBER, ChatMember.OWNER, ChatMember.ADMINISTRATOR] \
                or (new_status == ChatMember.RESTRICTED and new_is_member)

    return was_member, is_member


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    if was_member or not is_member:
        return

    chat = update.effective_chat
    new_member = update.chat_member.new_chat_member.user
    invite_link: ChatInviteLink | None = update.chat_member.invite_link

    if invite_link and invite_link.name:
        inviter_id = find_inviter_by_link_name(invite_link.name)
        if inviter_id and inviter_id != new_member.id:
            if record_join(inviter_id, new_member.id, chat.id, "group"):
                add_points(inviter_id)

                try:
                    await context.bot.send_message(
                        chat_id=inviter_id,
                        text=(
                            f"🎉 کسی با لینک تو وارد گروه شد!\n\n"
                            f"👤 {new_member.full_name}\n"
                            f"⭐ +{POINTS_PER_INVITE} امتیاز"
                        )
                    )
                except Exception:
                    pass

                if WELCOME_IN_GROUP:
                    try:
                        await context.bot.send_message(
                            chat_id=chat.id,
                            text=f"👋 {new_member.full_name} به جمع ما پیوست!"
                        )
                    except Exception:
                        pass


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    join_request = update.chat_join_request
    chat = update.effective_chat
    new_user = join_request.from_user
    invite_link: ChatInviteLink | None = join_request.invite_link

    try:
        await context.bot.approve_chat_join_request(chat_id=chat.id, user_id=new_user.id)
    except Exception as e:
        logger.error(f"Error approving: {e}")
        return

    if invite_link and invite_link.name:
        inviter_id = find_inviter_by_link_name(invite_link.name)
        if inviter_id and inviter_id != new_user.id:
            if record_join(inviter_id, new_user.id, chat.id, "channel"):
                add_points(inviter_id)

                try:
                    await context.bot.send_message(
                        chat_id=inviter_id,
                        text=(
                            f"🎉 کسی با لینک تو وارد کانال شد!\n\n"
                            f"👤 {new_user.full_name}\n"
                            f"⭐ +{POINTS_PER_INVITE} امتیاز\n\n"
                            f"برای لینک جدید: /newlink_channel"
                        )
                    )
                except Exception:
                    pass


# ==================== دستور ادمین ====================
async def give_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ دسترسی نداری.")
        return

    try:
        target_id = int(context.args[0])
        points = int(context.args[1])
        add_points(target_id, points)
        await update.message.reply_text(f"✅ {points} امتیاز به {target_id} داده شد.")
    except (IndexError, ValueError):
        await update.message.reply_text("استفاده: /givepoints user_id points")
# ==================== اصلی ====================
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN تنظیم نشده!")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mylink", mylink))
    app.add_handler(CommandHandler("mylink_channel", mylink_channel))
    app.add_handler(CommandHandler("newlink_channel", newlink_channel))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("givepoints", give_points))

    # تشخیص ورود
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(on_join_request))

    logger.info("ربات شروع به کار کرد...")
    app.run_polling(allowed_updates=["message", "chat_member", "chat_join_request"])


if __name__ == "__main__":
    main()
# ==================== دستورات تور ====================
async def tours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست تورهای فعال"""
    all_tours = get_active_tours()
    if not all_tours:
        await update.message.reply_text("🎒 هنوز توری ساخته نشده!\n\nمنتظر تورهای جدید باش...")
        return

    text = "🎒 *تورهای فعال BESA:*\n\n"
    for tour in all_tours:
        tour_id, title, desc, location, date, capacity, price, is_active, created_by, created_at = tour
        text += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *{title}*\n"
            f"📍 مکان: {location or 'نامشخص'}\n"
            f"📅 تاریخ: {date or 'نامشخص'}\n"
            f"👥 ظرفیت: {capacity} نفر\n"
            f"📝 توضیحات: {desc or 'ندارد'}\n"
            f"🆔 کد تور: `{tour_id}`\n"
        )
    text += "\n━━━━━━━━━━━━━━━━━━━━\n"
    text += "برای ثبت‌نام: `/register <کد تور>`"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def newtour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت تور جدید (ادمین)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ دسترسی نداری.")
        return

    if len(context.args) < 5:
        await update.message.reply_text(
            "📝 استفاده:\n"
            "`/newtour عنوان | مکان | تاریخ | ظرفیت | توضیحات`\n\n"
            "مثال:\n"
            "`/newtour تور جنگل | مازندران | 1404/10/15 | 20 | یه روز طبیعت‌گردی`",
            parse_mode="Markdown"
        )
        return

    full_text = " ".join(context.args)
    parts = [p.strip() for p in full_text.split("|")]
    
    if len(parts) < 4:
        await update.message.reply_text("❌ فرمت اشتباهه. از `|` برای جدا کردن استفاده کن.")
        return

    title = parts[0]
    location = parts[1]
    date = parts[2]
    capacity = int(parts[3]) if parts[3].isdigit() else 0
    description = parts[4] if len(parts) > 4 else ""

    create_tour(title, description, location, date, capacity, 0, update.effective_user.id)
    await update.message.reply_text(f"✅ تور «{title}» با موفقیت ساخته شد!\n\nبرای دیدن: /tours")


async def polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست نظرسنجی‌های فعال"""
    import json
    active_polls = get_active_polls()
    if not active_polls:
        await update.message.reply_text("📊 هنوز نظرسنجی ساخته نشده!")
        return

    text = "📊 *نظرسنجی‌های فعال:*\n\n"
    for poll in active_polls:
        poll_id, question, options_json, is_active, created_by, created_at = poll
        options = json.loads(options_json)
        text += f"━━━━━━━━━━━━━━━━━━━━\n🆔 `{poll_id}` — *{question}*\n"
        for i, opt in enumerate(options, 1):
            text += f"  {i}. {opt}\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━━━\n"
    text += "برای رأی دادن: `/vote <شماره نظرسنجی> <شماره گزینه>`"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def newpoll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت نظرسنجی جدید (ادمین)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ دسترسی نداری.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "📝 استفاده:\n"
            "`/newpoll سوال | گزینه1 | گزینه2 | گزینه3`\n\n"
            "مثال:\n"
            "`/newpoll کدوم تور رو می‌خوای؟ | جنگل | کوه | دریا`",
            parse_mode="Markdown"
        )
        return

    full_text = " ".join(context.args)
    parts = [p.strip() for p in full_text.split("|")]
    
    if len(parts) < 3:
        await update.message.reply_text("❌ حداقل باید سوال + ۲ گزینه باشه.")
        return

    question = parts[0]
    options = parts[1:]

    create_poll(question, options, update.effective_user.id)
    await update.message.reply_text(f"✅ نظرسنجی «{question}» ساخته شد!\n\nبرای دیدن: /polls")


async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رأی دادن به نظرسنجی"""
    import json
    if len(context.args) < 2:
        await update.message.reply_text("استفاده: `/vote <شماره نظرسنجی> <شماره گزینه>`", parse_mode="Markdown")
        return

    try:
        poll_id = int(context.args[0])
        option_num = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ شماره‌ها باید عدد باشن.")
        return

    poll = get_poll(poll_id)
    if not poll:
        await update.message.reply_text("❌ نظرسنجی پیدا نشد.")
        return

    options = json.loads(poll[2])
    if option_num < 1 or option_num > len(options):
        await update.message.reply_text(f"❌ گزینه باید بین ۱ تا {len(options)} باشه.")
        return

    user = update.effective_user
    if has_voted(poll_id, user.id):
        await update.message.reply_text("❌ قبلاً رأی دادی!")
        return

    if save_vote(poll_id, user.id, option_num - 1):
        await update.message.reply_text(f"✅ رأیت ثبت شد: {options[option_num-1]}")
    else:
        await update.message.reply_text("❌ خطا در ثبت رأی.")


async def poll_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نتیجه نظرسنجی"""
    import json
    if not context.args:
        await update.message.reply_text("استفاده: `/pollresults <شماره نظرسنجی>`", parse_mode="Markdown")
        return

    try:
        poll_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ شماره باید عدد باشه.")
        return

    poll = get_poll(poll_id)
    if not poll:
        await update.message.reply_text("❌ نظرسنجی پیدا نشد.")
        return

    options = json.loads(poll[2])
    results = get_poll_results(poll_id)
    results_dict = {r[0]: r[1] for r in results}
    total = sum(results_dict.values()) or 1

    text = f"📊 *نتیجه نظرسنجی:*\n{poll[1]}\n\n"
    for i, opt in enumerate(options):
        count = results_dict.get(i, 0)
        percent = (count / total) * 100
        bar = "█" * int(percent / 5) + "░" * (20 - int(percent / 5))
        text += f"*{opt}*\n{bar} {count} رأی ({percent:.1f}%)\n\n"

    text += f"👥 مجموع آرا: {total}"
    await update.message.reply_text(text, parse_mode="Markdown")


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت‌نام توی تور"""
    if not context.args:
        await update.message.reply_text(
            "📝 استفاده: `/register <کد تور>`\n\n"
            "برای دیدن کد تورها: /tours",
            parse_mode="Markdown"
        )
        return

    try:
        tour_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ کد تور باید عدد باشه.")
        return

    tour = get_tour(tour_id)
    if not tour or not tour[7]:
        await update.message.reply_text("❌ تور پیدا نشد یا غیرفعاله.")
        return

    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    if is_registered(tour_id, user.id):
        await update.message.reply_text("❌ قبلاً توی این تور ثبت‌نام کردی!")
        return

    # ذخیره‌ی اطلاعات پایه
    db_execute(
        """INSERT INTO registrations 
           (tour_id, user_id, full_name, age, city, registered_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tour_id, user.id, user.full_name, 0, "", datetime.now().isoformat())
    )

    await update.message.reply_text(
        f"✅ توی تور «{tour[1]}» ثبت‌نام شدی!\n\n"
        f"📅 تاریخ: {tour[4]}\n"
        f"📍 مکان: {tour[3]}\n\n"
        f"برای تکمیل اطلاعات: /myregistrations"
    )


async def myregistrations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تورهای من"""
    user = update.effective_user
    regs = get_user_registrations(user.id)
    
    if not regs:
        await update.message.reply_text("📝 هنوز توی هیچ توری ثبت‌نام نکردی.\n\nبرای دیدن تورها: /tours")
        return

    text = "📝 *تورهای من:*\n\n"
    for reg in regs:
        text += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 {reg[5]}\n"
            f"📅 تاریخ: {reg[6]}\n"
            f"📍 مکان: {reg[7]}\n"
            f"✅ وضعیت: {reg[10]}\n"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def cancelreg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو ثبت‌نام"""
    if not context.args:
        await update.message.reply_text("استفاده: `/cancelreg <کد تور>`", parse_mode="Markdown")
        return

    try:
        tour_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ کد تور باید عدد باشه.")
        return

    user = update.effective_user
    if not is_registered(tour_id, user.id):        return

    db_execute("DELETE FROM registrations WHERE tour_id = ? AND user_id = ?", (tour_id, user.id))
    await update.message.reply_text("✅ ثبت‌نامت لغو شد.")


# ==================== اصلی ====================
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN تنظیم نشده!")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mylink", mylink))
    app.add_handler(CommandHandler("mylink_channel", mylink_channel))
    app.add_handler(CommandHandler("newlink_channel", newlink_channel))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("givepoints", give_points))

    app.add_handler(CommandHandler("tours", tours))
    app.add_handler(CommandHandler("newtour", newtour))
    app.add_handler(CommandHandler("polls", polls))
    app.add_handler(CommandHandler("newpoll", newpoll))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("pollresults", poll_results))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("myregistrations", myregistrations))
    app.add_handler(CommandHandler("cancelreg", cancelreg))

    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(on_join_request))

    logger.info("ربات شروع به کار کرد...")
    app.run_polling(allowed_updates=["message", "chat_member", "chat_join_request"])


if __name__ == "__main__":
    main()
        await update.message.reply_text("❌ توی این تور ثبت‌نام نکردی.")
