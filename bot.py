import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update, ChatMemberUpdated, ChatMember, ChatInviteLink
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    filters,
)

# ==================== تنظیمات ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")            # آیدی عددی گروه
CHANNEL_ID = os.getenv("CHANNEL_ID")        # آیدی عددی کانال
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
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    if fetch:
        row = c.fetchone()
        conn.close()
        return row
    conn.commit()
    conn.close()

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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, full_name, username, points, invites FROM users ORDER BY points DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def find_inviter_by_link_name(link_name: str):
    try:
        return int(link_name)
    except (ValueError, TypeError):
        return None

# ==================== ابزار کمکی ====================
async def create_invite_link(context, chat_id: int, user_id: int, chat_type: str):
    """ساخت لینک دعوت مناسب بر اساس نوع چت"""
    kwargs = {
        "chat_id": int(chat_id),
        "name": str(user_id),
    }
    if chat_type == "channel":
        # کانال: هر لینک فقط یه نفر
        kwargs["creates_join_request"] = True
        kwargs["member_limit"] = 1
    else:
        # گروه: لینک دائمی
        kwargs["creates_join_request"] = False

    invite = await context.bot.create_chat_invite_link(**kwargs)
    save_link(user_id, invite.invite_link, chat_type)
    return invite.invite_link

# ==================== دستورات ====================
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
    "🔗 /mylink — لینک دعوت گروه\n"
    "🔗 /mylink_channel — لینک دعوت کانال\n"
    "📊 /stats — امتیاز و دعوت‌هات\n"
    "🏆 /top — رتبه‌بندی برترین‌ها\n"
    "📖 /help — راهنما"
)
    await update.message.reply_text(text)


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لینک اختصاصی گروه"""
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    if not GROUP_ID:
        await update.message.reply_text("❌ گروه تنظیم نشده.")
        return

    existing = get_user(user.id)
    if existing and existing[5]:  # invite_link_group
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
    """لینک اختصاصی کانال (هر لینک فقط یه نفر)"""
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.full_name)

    if not CHANNEL_ID:
        await update.message.reply_text("❌ کانال تنظیم نشده.")
        return

    existing = get_user(user.id)
    if existing and existing[6]:  # invite_link_channel
        await update.message.reply_text(
            f"🔗 لینک اختصاصی کانال تو:\n\n{existing[6]}\n\n"
            "⚠️ این لینک فقط برای یه نفره. بعد از اینکه یکی عضو شد، /newlink_channel بزن تا لینک جدید بگیری."
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
    """ساخت لینک جدید کانال (لغو قبلی)"""
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
        "📖 راهنمای ربات:\n\n"
        "/start — شروع\n"
        "/mylink — لینک دعوت گروه\n"
        "/mylink_channel — لینک دعوت کانال\n"
        "/newlink_channel — لینک جدید کانال\n"
        "/stats — آمار تو\n"
        "/top — برترین‌ها\n"
        "/help — راهنما"
    )
    await update.message.reply_text(text)


# ==================== ادمین ====================
async def give_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور ادمین: /givepoints user_id points"""
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


# ==================== تشخیص ورود (گروه) ====================
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
    """ورود عضو جدید به گروه"""
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

                # پیام به دعوت‌کننده
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

                # پیام خوش‌آمد توی گروه (اختیاری)
                if WELCOME_IN_GROUP:
                    try:
                        await context.bot.send_message(
                            chat_id=chat.id,
                            text=f"👋 {new_member.full_name} به جمع ما پیوست!"
                        )
                    except Exception:
                        pass


# ==================== تشخیص درخواست عضویت (کانال) ====================
async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی کسی درخواست عضویت کانال می‌ده"""
    join_request = update.chat_join_request
    chat = update.effective_chat
    new_user = join_request.from_user
    invite_link: ChatInviteLink | None = join_request.invite_link

    # تأیید خودکار
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

                # پیام به دعوت‌کننده
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
