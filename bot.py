import asyncio
import logging
import random
import string
import time
import re
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN        = "8446272435:AAH18fvcHjo5w92_zFZdkRY9_KkF9Kvcq2o"
CHANNEL_USERNAME = "SPEED_X_OFFICIAL1"
CHANNEL_LINK     = "https://t.me/SPEED_X_OFFICIAL1"
MAIL_EXPIRE_MIN  = 10
BASE_URL         = "https://api.mail.tm"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s — %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions: dict = {}

# ══════════════════════════════════════════════════════════════════════════════
#  MAIL.TM API
# ══════════════════════════════════════════════════════════════════════════════

async def api_get_domains() -> list:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{BASE_URL}/domains"); r.raise_for_status()
        return [d["domain"] for d in r.json().get("hydra:member", [])]

async def api_create_account(email: str, pw: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{BASE_URL}/accounts", json={"address": email, "password": pw})
        r.raise_for_status(); return r.json()

async def api_get_token(email: str, pw: str) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{BASE_URL}/token", json={"address": email, "password": pw})
        r.raise_for_status(); return r.json()["token"]

async def api_get_messages(token: str) -> list:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{BASE_URL}/messages", headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status(); return r.json().get("hydra:member", [])

async def api_get_message(token: str, mid: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{BASE_URL}/messages/{mid}", headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status(); return r.json()

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def gen_password(length: int = 14) -> str:
    pool = string.ascii_letters + string.digits + "!@#$%^&*"
    return "speedx" + "".join(random.choices(pool, k=length - 6))

def gen_username(length: int = 9) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

def time_left(created_at: float) -> str:
    rem = MAIL_EXPIRE_MIN * 60 - (time.time() - created_at)
    if rem <= 0: return "⛔  Expired"
    m, s = divmod(int(rem), 60)
    filled = int((rem / (MAIL_EXPIRE_MIN * 60)) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}]  {m}m {s}s remaining"

def is_expired(created_at: float) -> bool:
    return (time.time() - created_at) >= MAIL_EXPIRE_MIN * 60

async def is_member(bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_home(user_id: int) -> InlineKeyboardMarkup:
    has = user_id in user_sessions
    rows = []
    if has:
        rows += [
            [InlineKeyboardButton("📋  View My Email",      callback_data="show_email")],
            [InlineKeyboardButton("📬  Check Inbox",        callback_data="inbox"),
             InlineKeyboardButton("🔄  New Email",          callback_data="new_email")],
        ]
    else:
        rows += [[InlineKeyboardButton("✨  Generate New Email", callback_data="new_email")]]
    rows += [[InlineKeyboardButton("📢  Our Channel", url=CHANNEL_LINK),
              InlineKeyboardButton("❓  Help",         callback_data="help")]]
    return InlineKeyboardMarkup(rows)

def kb_email_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📬  Check Inbox",  callback_data="inbox"),
         InlineKeyboardButton("🔄  New Email",    callback_data="new_email")],
        [InlineKeyboardButton("🏠  Home",         callback_data="home")],
    ])

def kb_inbox(messages: list) -> InlineKeyboardMarkup:
    rows = []
    for msg in messages[:8]:
        subj   = (msg.get("subject") or "No Subject")[:32]
        sender = msg.get("from", {}).get("address", "unknown")[:22]
        rows.append([InlineKeyboardButton(
            f"✉️  {subj}  ·  {sender}", callback_data=f"msg_{msg['id']}"
        )])
    rows += [[InlineKeyboardButton("🔄  Refresh", callback_data="inbox"),
              InlineKeyboardButton("🏠  Home",    callback_data="home")]]
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_member(ctx.bot, user.id):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢  Join Channel",  url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅  I've Joined",   callback_data="verify_join")],
        ])
        await update.message.reply_text(
            f"👋  *Welcome, {user.first_name}!*\n\n"
            "🔒  To use this bot you must join our official channel first.\n\n"
            f"➡️  {CHANNEL_LINK}\n\n"
            "After joining, tap *\"I've Joined\"* below.",
            parse_mode="Markdown", reply_markup=kb
        )
        return
    await _send_home(update.message, user.id)

async def _send_home(message, user_id: int, edit: bool = False):
    sess = user_sessions.get(user_id)
    if sess and is_expired(sess["created_at"]):
        del user_sessions[user_id]; sess = None

    status_line = ""
    if sess:
        tl = time_left(sess["created_at"])
        status_line = (
            f"\n┌─────────────────────────\n"
            f"│  📧  `{sess['email']}`\n"
            f"│  ⏱️  {tl}\n"
            f"└─────────────────────────\n"
        )

    text = (
        "⚡  *SPEED X TempMail Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_line}"
        "Generate disposable email addresses instantly.\n"
        "Receive emails & copy OTP codes with one tap.\n\n"
        "Use the buttons below to get started 👇"
    )
    if edit:
        return text, kb_home(user_id)
    await message.reply_text(text, parse_mode="Markdown", reply_markup=kb_home(user_id))

# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════════════════════

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    user = q.from_user
    data = q.data

    # ── Verify join ──────────────────────────────────────────────────────────
    if data == "verify_join":
        if not await is_member(ctx.bot, user.id):
            await q.answer("⚠️  You haven't joined yet!", show_alert=True); return
        await q.message.delete()
        await _send_home(q.message, user.id)
        return

    # ── Member gate ──────────────────────────────────────────────────────────
    if not await is_member(ctx.bot, user.id):
        await q.answer("🔒  Please join our channel first!", show_alert=True); return

    # ── Home ─────────────────────────────────────────────────────────────────
    if data == "home":
        txt, kb = await _send_home(q.message, user.id, edit=True)
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb); return

    # ── Generate new email ───────────────────────────────────────────────────
    if data == "new_email":
        await q.edit_message_text("⏳  *Generating your temporary email…*", parse_mode="Markdown")
        try:
            domains = await api_get_domains()
            if not domains: raise RuntimeError("No domains available")
            email    = f"{gen_username()}@{random.choice(domains)}"
            password = gen_password()
            await api_create_account(email, password)
            token = await api_get_token(email, password)
            user_sessions[user.id] = {
                "email": email, "password": password,
                "token": token, "created_at": time.time()
            }
            asyncio.create_task(_expiry_watcher(ctx.bot, user.id, email))
            tl = time_left(user_sessions[user.id]["created_at"])
            await q.edit_message_text(
                "✅  *New Email Created Successfully!*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📧  *Email Address*\n"
                f"`{email}`\n\n"
                "🔑  *Password*\n"
                f"`{password}`\n\n"
                f"⏱️  {tl}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "_Tap email or password to copy_",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📬  Check Inbox",  callback_data="inbox")],
                    [InlineKeyboardButton("🔄  Regenerate",   callback_data="new_email"),
                     InlineKeyboardButton("🏠  Home",         callback_data="home")],
                ])
            )
        except Exception as e:
            logger.error(f"Email creation error: {e}")
            await q.edit_message_text(
                "❌  *Failed to create email.*\nPlease try again in a moment.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄  Retry", callback_data="new_email")
                ]])
            )
        return

    # ── Show current email ───────────────────────────────────────────────────
    if data == "show_email":
        sess = user_sessions.get(user.id)
        if not sess:
            await q.answer("❌  No active email. Generate one first!", show_alert=True); return
        if is_expired(sess["created_at"]):
            del user_sessions[user.id]
            await q.answer("⛔  Your email expired. Generate a new one.", show_alert=True); return
        tl = time_left(sess["created_at"])
        await q.edit_message_text(
            "📧  *Your Active Email*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📬  *Address*\n"
            f"`{sess['email']}`\n\n"
            "🔑  *Password*\n"
            f"`{sess['password']}`\n\n"
            f"⏱️  {tl}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Tap any value to copy_",
            parse_mode="Markdown",
            reply_markup=kb_email_actions()
        )
        return

    # ── Inbox ────────────────────────────────────────────────────────────────
    if data == "inbox":
        sess = user_sessions.get(user.id)
        if not sess:
            await q.answer("❌  Generate an email first!", show_alert=True); return
        if is_expired(sess["created_at"]):
            del user_sessions[user.id]
            await q.answer("⛔  Email expired. Generate a new one.", show_alert=True); return
        await q.edit_message_text("📬  *Loading inbox…*", parse_mode="Markdown")
        try:
            msgs = await api_get_messages(sess["token"])
            tl   = time_left(sess["created_at"])
            if not msgs:
                await q.edit_message_text(
                    "📭  *Inbox is Empty*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📧  `{sess['email']}`\n"
                    f"⏱️  {tl}\n\n"
                    "_No messages yet. Emails usually arrive within seconds._",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄  Refresh", callback_data="inbox"),
                         InlineKeyboardButton("🏠  Home",    callback_data="home")],
                    ])
                )
            else:
                await q.edit_message_text(
                    f"📬  *Inbox  ·  {len(msgs)} message{'s' if len(msgs)>1 else ''}*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📧  `{sess['email']}`\n"
                    f"⏱️  {tl}\n\n"
                    "Tap a message to read it 👇",
                    parse_mode="Markdown",
                    reply_markup=kb_inbox(msgs)
                )
        except Exception as e:
            logger.error(f"Inbox error: {e}")
            await q.edit_message_text(
                "❌  *Failed to load inbox.*", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄  Retry", callback_data="inbox")
                ]])
            )
        return

    # ── Message detail ───────────────────────────────────────────────────────
    if data.startswith("msg_"):
        mid  = data[4:]
        sess = user_sessions.get(user.id)
        if not sess: await q.answer("⛔  Session expired!", show_alert=True); return
        await q.edit_message_text("📩  *Opening message…*", parse_mode="Markdown")
        try:
            detail  = await api_get_message(sess["token"], mid)
            sender  = detail.get("from", {}).get("address", "unknown")
            subject = detail.get("subject", "No Subject")
            body    = detail.get("text") or ""
            if isinstance(body, list): body = "\n".join(body)
            body = body.strip()[:1800] + ("…" if len(body) > 1800 else "")
            codes = list(dict.fromkeys(re.findall(r'\b\d{4,8}\b', body)))
            text = (
                "📩  *Message*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤  *From:*  `{sender}`\n"
                f"📌  *Subject:*  {subject}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{body or '_No text content_'}"
            )
            if codes:
                text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🔢  *Detected Codes / OTPs:*"
            buttons = []
            for code in codes[:6]:
                buttons.append([InlineKeyboardButton(
                    f"📋  Copy Code: {code}", callback_data=f"copy_{code}"
                )])
            buttons.append([
                InlineKeyboardButton("◀️  Inbox", callback_data="inbox"),
                InlineKeyboardButton("🏠  Home",  callback_data="home"),
            ])
            await q.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(buttons))
        except Exception as e:
            logger.error(f"Message detail error: {e}")
            await q.edit_message_text(
                "❌  *Failed to load message.*", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️  Inbox", callback_data="inbox"),
                    InlineKeyboardButton("🏠  Home",  callback_data="home"),
                ]])
            )
        return

    # ── Copy code ────────────────────────────────────────────────────────────
    if data.startswith("copy_"):
        code = data[5:]
        await q.answer(f"✅  Copied: {code}", show_alert=False)
        await ctx.bot.send_message(
            user.id,
            f"📋  *Copied Code*\n\n`{code}`\n\n_Tap the code above to copy it._",
            parse_mode="Markdown"
        )
        return

    # ── Help ─────────────────────────────────────────────────────────────────
    if data == "help":
        await q.edit_message_text(
            "❓  *Help & Guide*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "✨  *Generate New Email*\n"
            "Creates a disposable email + password instantly.\n\n"
            "📬  *Check Inbox*\n"
            "View incoming emails in real-time.\n\n"
            "📋  *Copy Code*\n"
            "OTP / verification codes are auto-detected and copyable.\n\n"
            f"⏱️  *Expiry*\n"
            f"Each email is active for {MAIL_EXPIRE_MIN} minutes.\n"
            "You'll get a warning 1 minute before it expires.\n\n"
            "🔑  *Password Format*\n"
            "All passwords begin with `speedx` followed by random characters.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠  Home", callback_data="home")
            ]])
        )
        return

# ══════════════════════════════════════════════════════════════════════════════
#  EXPIRY WATCHER
# ══════════════════════════════════════════════════════════════════════════════

async def _expiry_watcher(bot, user_id: int, email: str):
    await asyncio.sleep(MAIL_EXPIRE_MIN * 60 - 60)
    sess = user_sessions.get(user_id)
    if sess and sess["email"] == email:
        try:
            await bot.send_message(
                user_id,
                f"⚠️  *Expiry Warning*\n\n"
                f"Your email `{email}` expires in *1 minute*.\n"
                "Generate a new one to stay active.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄  Generate New", callback_data="new_email")
                ]])
            )
        except Exception: pass
    await asyncio.sleep(60)
    sess = user_sessions.get(user_id)
    if sess and sess["email"] == email:
        del user_sessions[user_id]
        try:
            await bot.send_message(
                user_id,
                f"⛔  *Email Expired*\n\n`{email}` has been deleted.\n\n"
                "Generate a new disposable email anytime.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✨  Generate New Email", callback_data="new_email")
                ]])
            )
        except Exception: pass

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    logger.info("⚡ SPEED X TempMail Bot is running…")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
