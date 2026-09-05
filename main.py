"""
TaskLedger — Combined Telegram Bot + Flask Web App (Mini App backend)
----------------------------------------------------------------------
এই একটা ফাইলেই আছে:
1. Telegram বট (force-subscribe + Open App বাটন)
2. Flask ওয়েব সার্ভার (Mini App এর সব পেজ ও API)
3. SQLite ডাটাবেস (ইউজার, টাস্ক, সাবমিশন, উইথড্র, রেফারেল)

আপনাকে যা বদলাতে হবে (নিচে খুঁজুন):
- BOT_TOKEN
- CHANNEL_USERNAME
- ADMIN_TELEGRAM_ID   (আপনার নিজের টেলিগ্রাম নাম্বার আইডি — @userinfobot দিয়ে বের করুন)
- ADMIN_SECRET_PATH   (এডমিন প্যানেলের গোপন লিংক — যা খুশি একটা কঠিন শব্দ দিন)
"""

import sqlite3
import hmac
import hashlib
import json
import time
import threading
import urllib.parse
from datetime import datetime

from flask import Flask, request, jsonify, render_template, g, send_file

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ========================================================
# এই জায়গাগুলো আপনার নিজের তথ্য দিয়ে বদলে দিন
# ========================================================
BOT_TOKEN = "8996627149:AAH0uejnG9e8_RJDRcTzsNN_9erLGEiqK6c"
CHANNEL_USERNAME = "@task_pay_660"
ADMIN_TELEGRAM_ID = 1725125622          # আপনার নিজের Telegram numeric ID (@userinfobot দিয়ে বের করুন)
ADMIN_SECRET_PATH = "taskpay-admin-panel-fahim660"  # এডমিন প্যানেলের গোপন অংশ, url এ থাকবে
WEBAPP_URL = "https://taskpay660-bot.onrender.com"     # Replit Run করার পর যে ওয়েব লিংক পাবেন সেটা এখানে বসাবেন
# ========================================================

PLATFORM_MARGIN_PERCENT = 25   # employer rate থেকে worker rate কত % কম হবে (আপনি বদলাতে পারেন)
REFERRAL_PERCENT = 5           # রেফারেল কমিশন %
MIN_WITHDRAW = 2.0             # মিনিমাম উইথড্র (USDT)

DB_PATH = "taskledger.db"

app = Flask(__name__)


# ---------------------------------------------------------
# ডাটাবেস সেটআপ
# ---------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 0,
        referred_by INTEGER,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employer_id INTEGER,
        title TEXT,
        category TEXT,
        instructions TEXT,
        link TEXT,
        proof_type TEXT,
        employer_rate REAL,
        worker_rate REAL,
        total_slots INTEGER,
        filled_slots INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        worker_id INTEGER,
        proof_text TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        reviewed_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        method TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS referral_earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        amount REAL,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()


def now():
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------
# Telegram initData ভেরিফিকেশন (নিরাপত্তার জন্য)
# ---------------------------------------------------------
def validate_init_data(init_data: str):
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data))
        received_hash = parsed.pop("hash", None)
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash != received_hash:
            return None
        user_data = json.loads(parsed.get("user", "{}"))
        return user_data
    except Exception as e:
        print(f"initData validation error: {e}")
        return None


def get_authenticated_user():
    """রিকোয়েস্ট থেকে ইউজার ভেরিফাই করে, ডাটাবেসে থাকলে তার তথ্য রিটার্ন করে"""
    init_data = request.headers.get("X-Init-Data", "")
    user_data = validate_init_data(init_data)
    if not user_data:
        return None
    telegram_id = user_data.get("id")
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not row:
        return None
    return dict(row), user_data


# ---------------------------------------------------------
# Flask রুট: পেজ
# ---------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html", bot_username=BOT_USERNAME_CACHE.get("value", ""))


@app.route(f"/admin/{ADMIN_SECRET_PATH}")
def admin_panel():
    db = get_db()
    withdrawals = db.execute(
        "SELECT w.*, u.username, u.first_name FROM withdrawals w JOIN users u ON u.telegram_id=w.user_id "
        "WHERE w.status='pending' ORDER BY w.created_at DESC"
    ).fetchall()
    revenue_row = db.execute(
        "SELECT COALESCE(SUM(t.employer_rate - t.worker_rate),0) as rev FROM submissions s "
        "JOIN tasks t ON t.id=s.task_id WHERE s.status='approved'"
    ).fetchone()
    users = db.execute("SELECT telegram_id, username, first_name, balance FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
    return render_template(
        "admin.html",
        withdrawals=withdrawals,
        revenue=round(revenue_row["rev"], 4),
        users=users,
        secret=ADMIN_SECRET_PATH,
    )


@app.route(f"/admin/{ADMIN_SECRET_PATH}/withdraw/<int:wid>/<action>")
def admin_withdraw_action(wid, action):
    db = get_db()
    w = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if w and w["status"] == "pending":
        if action == "paid":
            db.execute("UPDATE withdrawals SET status='paid' WHERE id=?", (wid,))
        elif action == "reject":
            db.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
            db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id=?", (w["amount"], w["user_id"]))
        db.commit()
    return admin_panel()


@app.route(f"/admin/{ADMIN_SECRET_PATH}/credit", methods=["POST"])
def admin_credit():
    telegram_id = int(request.form.get("telegram_id"))
    amount = float(request.form.get("amount"))
    db = get_db()
    db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id=?", (amount, telegram_id))
    db.commit()
    return admin_panel()


@app.route(f"/admin/{ADMIN_SECRET_PATH}/backup")
def admin_backup():
    """পুরো ডাটাবেস ফাইল ডাউনলোড করার জন্য - নিয়মিত ব্যাকআপ নিতে ব্যবহার করুন"""
    backup_name = f"taskledger-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=backup_name)


# ---------------------------------------------------------
# API: ইউজার init / লগইন
# ---------------------------------------------------------
@app.route("/api/init", methods=["POST"])
def api_init():
    body = request.get_json(force=True)
    init_data = body.get("initData", "")
    ref = body.get("ref")

    user_data = validate_init_data(init_data)
    if not user_data:
        return jsonify({"error": "invalid init data"}), 401

    telegram_id = user_data.get("id")
    username = user_data.get("username", "")
    first_name = user_data.get("first_name", "user")

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not row:
        referred_by = None
        if ref:
            try:
                ref_id = int(ref)
                if ref_id != telegram_id:
                    exists = db.execute("SELECT 1 FROM users WHERE telegram_id=?", (ref_id,)).fetchone()
                    if exists:
                        referred_by = ref_id
            except ValueError:
                pass
        db.execute(
            "INSERT INTO users (telegram_id, username, first_name, balance, referred_by, created_at) VALUES (?,?,?,?,?,?)",
            (telegram_id, username, first_name, 0, referred_by, now()),
        )
        db.commit()
        row = db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()

    return jsonify(dict(row))


# ---------------------------------------------------------
# API: হোম / ড্যাশবোর্ড সামারি
# ---------------------------------------------------------
@app.route("/api/dashboard")
def api_dashboard():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    db = get_db()

    tasks_done = db.execute(
        "SELECT COUNT(*) c FROM submissions WHERE worker_id=? AND status='approved'", (user["telegram_id"],)
    ).fetchone()["c"]
    referrals = db.execute(
        "SELECT COUNT(*) c FROM users WHERE referred_by=?", (user["telegram_id"],)
    ).fetchone()["c"]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_earn_row = db.execute(
        "SELECT COALESCE(SUM(t.worker_rate),0) e FROM submissions s JOIN tasks t ON t.id=s.task_id "
        "WHERE s.worker_id=? AND s.status='approved' AND s.reviewed_at LIKE ?",
        (user["telegram_id"], today + "%"),
    ).fetchone()["e"]

    tasks = db.execute(
        "SELECT * FROM tasks WHERE status='active' AND filled_slots < total_slots ORDER BY created_at DESC LIMIT 6"
    ).fetchall()
    task_list = [dict(t) for t in tasks]

    return jsonify({
        "user": user,
        "tasks_done": tasks_done,
        "referrals": referrals,
        "today_earning": round(today_earn_row, 4),
        "tasks": task_list,
    })


# ---------------------------------------------------------
# API: টাস্ক লিস্ট (ফুল ব্রাউজ)
# ---------------------------------------------------------
@app.route("/api/tasks")
def api_tasks():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    db = get_db()
    category = request.args.get("category", "all")
    if category == "all":
        tasks = db.execute("SELECT * FROM tasks WHERE status='active' ORDER BY created_at DESC").fetchall()
    else:
        tasks = db.execute(
            "SELECT * FROM tasks WHERE status='active' AND category=? ORDER BY created_at DESC", (category,)
        ).fetchall()

    result = []
    for t in tasks:
        t = dict(t)
        already = db.execute(
            "SELECT status FROM submissions WHERE task_id=? AND worker_id=?", (t["id"], user["telegram_id"])
        ).fetchone()
        t["already_submitted"] = already["status"] if already else None
        result.append(t)
    return jsonify(result)


@app.route("/api/tasks/<int:task_id>/submit", methods=["POST"])
def api_submit_task(task_id):
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    body = request.get_json(force=True)
    proof_text = body.get("proof_text", "").strip()
    if not proof_text:
        return jsonify({"error": "প্রুফ দেওয়া আবশ্যক"}), 400

    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task or task["status"] != "active" or task["filled_slots"] >= task["total_slots"]:
        return jsonify({"error": "এই টাস্কটি আর available নেই"}), 400

    existing = db.execute(
        "SELECT 1 FROM submissions WHERE task_id=? AND worker_id=?", (task_id, user["telegram_id"])
    ).fetchone()
    if existing:
        return jsonify({"error": "আপনি ইতিমধ্যে এই টাস্কে প্রুফ জমা দিয়েছেন"}), 400

    db.execute(
        "INSERT INTO submissions (task_id, worker_id, proof_text, status, created_at) VALUES (?,?,?,?,?)",
        (task_id, user["telegram_id"], proof_text, "pending", now()),
    )
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------
# API: ওয়ালেট
# ---------------------------------------------------------
@app.route("/api/wallet")
def api_wallet():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    db = get_db()

    pending = db.execute(
        "SELECT COALESCE(SUM(amount),0) p FROM withdrawals WHERE user_id=? AND status='pending'",
        (user["telegram_id"],),
    ).fetchone()["p"]
    withdrawn_total = db.execute(
        "SELECT COALESCE(SUM(amount),0) p FROM withdrawals WHERE user_id=? AND status='paid'",
        (user["telegram_id"],),
    ).fetchone()["p"]

    activity = []
    subs = db.execute(
        "SELECT s.reviewed_at as date, t.worker_rate as amount, t.title FROM submissions s "
        "JOIN tasks t ON t.id=s.task_id WHERE s.worker_id=? AND s.status='approved' ORDER BY s.reviewed_at DESC LIMIT 10",
        (user["telegram_id"],),
    ).fetchall()
    for s in subs:
        activity.append({"type": "earning", "title": f"Task earning — {s['title']}", "amount": s["amount"], "date": s["date"]})

    refs = db.execute(
        "SELECT amount, created_at FROM referral_earnings WHERE referrer_id=? ORDER BY created_at DESC LIMIT 10",
        (user["telegram_id"],),
    ).fetchall()
    for r in refs:
        activity.append({"type": "referral", "title": "Referral commission", "amount": r["amount"], "date": r["created_at"]})

    withs = db.execute(
        "SELECT amount, status, created_at FROM withdrawals WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
        (user["telegram_id"],),
    ).fetchall()
    for w in withs:
        activity.append({"type": "withdraw", "title": f"Withdraw ({w['status']})", "amount": -w["amount"], "date": w["created_at"]})

    activity.sort(key=lambda x: x["date"] or "", reverse=True)

    return jsonify({
        "balance": user["balance"],
        "pending": pending,
        "withdrawn_total": withdrawn_total,
        "min_withdraw": MIN_WITHDRAW,
        "activity": activity[:15],
    })


@app.route("/api/withdraw", methods=["POST"])
def api_withdraw():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    body = request.get_json(force=True)
    amount = float(body.get("amount", 0))
    method = body.get("method", "USDT")

    if amount < MIN_WITHDRAW:
        return jsonify({"error": f"মিনিমাম উইথড্র {MIN_WITHDRAW} USDT"}), 400
    if amount > user["balance"]:
        return jsonify({"error": "ব্যালেন্স যথেষ্ট নেই"}), 400

    db = get_db()
    db.execute("UPDATE users SET balance = balance - ? WHERE telegram_id=?", (amount, user["telegram_id"]))
    db.execute(
        "INSERT INTO withdrawals (user_id, amount, method, status, created_at) VALUES (?,?,?,?,?)",
        (user["telegram_id"], amount, method, "pending", now()),
    )
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------
# API: রেফারেল
# ---------------------------------------------------------
@app.route("/api/referral")
def api_referral():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    db = get_db()

    referred = db.execute(
        "SELECT telegram_id, username, first_name, created_at FROM users WHERE referred_by=? ORDER BY created_at DESC",
        (user["telegram_id"],),
    ).fetchall()

    total_earned = db.execute(
        "SELECT COALESCE(SUM(amount),0) t FROM referral_earnings WHERE referrer_id=?", (user["telegram_id"],)
    ).fetchone()["t"]

    result = []
    for r in referred:
        earned = db.execute(
            "SELECT COALESCE(SUM(amount),0) e FROM referral_earnings WHERE referrer_id=? AND referred_id=?",
            (user["telegram_id"], r["telegram_id"]),
        ).fetchone()["e"]
        result.append({**dict(r), "earned": earned})

    bot_username = BOT_USERNAME_CACHE.get("value", "")
    link = f"https://t.me/{bot_username}?start=ref_{user['telegram_id']}" if bot_username else ""

    return jsonify({
        "link": link,
        "count": len(result),
        "total_earned": total_earned,
        "percent": REFERRAL_PERCENT,
        "referrals": result,
    })


# ---------------------------------------------------------
# API: টাস্ক পোস্ট করা (employer)
# ---------------------------------------------------------
@app.route("/api/post-task", methods=["POST"])
def api_post_task():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    body = request.get_json(force=True)

    title = body.get("title", "").strip()
    category = body.get("category", "social")
    instructions = body.get("instructions", "").strip()
    link = body.get("link", "").strip()
    proof_type = body.get("proof_type", "Screenshot")
    employer_rate = float(body.get("employer_rate", 0))
    total_slots = int(body.get("total_slots", 0))

    if not title or employer_rate <= 0 or total_slots <= 0:
        return jsonify({"error": "সব ঘর সঠিকভাবে পূরণ করুন"}), 400

    worker_rate = round(employer_rate * (1 - PLATFORM_MARGIN_PERCENT / 100), 4)
    total_cost = round(employer_rate * total_slots, 4)

    db = get_db()
    if user["balance"] < total_cost:
        return jsonify({"error": f"ব্যালেন্স যথেষ্ট নেই। প্রয়োজন ${total_cost}, আপনার আছে ${user['balance']}"}), 400

    db.execute("UPDATE users SET balance = balance - ? WHERE telegram_id=?", (total_cost, user["telegram_id"]))
    db.execute(
        "INSERT INTO tasks (employer_id, title, category, instructions, link, proof_type, employer_rate, worker_rate, total_slots, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user["telegram_id"], title, category, instructions, link, proof_type, employer_rate, worker_rate, total_slots, "active", now()),
    )
    db.commit()
    return jsonify({"ok": True, "worker_rate": worker_rate, "total_cost": total_cost})


@app.route("/api/my-tasks")
def api_my_tasks():
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    db = get_db()

    tasks = db.execute(
        "SELECT * FROM tasks WHERE employer_id=? ORDER BY created_at DESC", (user["telegram_id"],)
    ).fetchall()
    result = []
    for t in tasks:
        t = dict(t)
        subs = db.execute(
            "SELECT s.id, s.proof_text, s.status, s.created_at, u.username, u.first_name "
            "FROM submissions s JOIN users u ON u.telegram_id=s.worker_id "
            "WHERE s.task_id=? AND s.status='pending' ORDER BY s.created_at ASC",
            (t["id"],),
        ).fetchall()
        t["pending_submissions"] = [dict(s) for s in subs]
        result.append(t)
    return jsonify(result)


@app.route("/api/submissions/<int:sub_id>/review", methods=["POST"])
def api_review_submission(sub_id):
    auth = get_authenticated_user()
    if not auth:
        return jsonify({"error": "unauthorized"}), 401
    user, _ = auth
    body = request.get_json(force=True)
    action = body.get("action")  # approve / reject

    db = get_db()
    sub = db.execute(
        "SELECT s.*, t.employer_id, t.worker_rate, t.id as tid FROM submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=?",
        (sub_id,),
    ).fetchone()
    if not sub or sub["employer_id"] != user["telegram_id"] or sub["status"] != "pending":
        return jsonify({"error": "অনুমতি নেই বা ইতিমধ্যে রিভিউ করা হয়েছে"}), 400

    if action == "approve":
        db.execute("UPDATE submissions SET status='approved', reviewed_at=? WHERE id=?", (now(), sub_id))
        db.execute("UPDATE tasks SET filled_slots = filled_slots + 1 WHERE id=?", (sub["tid"],))
        db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id=?", (sub["worker_rate"], sub["worker_id"]))

        worker = db.execute("SELECT referred_by FROM users WHERE telegram_id=?", (sub["worker_id"],)).fetchone()
        if worker and worker["referred_by"]:
            commission = round(sub["worker_rate"] * (REFERRAL_PERCENT / 100), 4)
            db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id=?", (commission, worker["referred_by"]))
            db.execute(
                "INSERT INTO referral_earnings (referrer_id, referred_id, amount, created_at) VALUES (?,?,?,?)",
                (worker["referred_by"], sub["worker_id"], commission, now()),
            )
    elif action == "reject":
        db.execute("UPDATE submissions SET status='rejected', reviewed_at=? WHERE id=?", (now(), sub_id))

    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------
# Telegram বট অংশ
# ---------------------------------------------------------
BOT_USERNAME_CACHE = {}


async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception as e:
        print(f"Membership check error: {e}")
        return False


def join_keyboard():
    channel_link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=channel_link)],
        [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")],
    ]
    return InlineKeyboardMarkup(keyboard)


def open_app_keyboard(ref=None):
    url = WEBAPP_URL
    if ref:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}ref={ref}"
    keyboard = [[InlineKeyboardButton("🚀 Open App", web_app=WebAppInfo(url=url))]]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ref = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            ref = int(context.args[0].replace("ref_", ""))
        except ValueError:
            ref = None

    is_member = await check_membership(user_id, context)
    if is_member:
        await update.message.reply_text(
            "স্বাগতম! 🎉 নিচের বাটনে চাপুন কাজ শুরু করতে।", reply_markup=open_app_keyboard(ref)
        )
    else:
        context.user_data["pending_ref"] = ref
        await update.message.reply_text(
            "শুরু করার আগে আমাদের চ্যানেলে জয়েন করুন 👇", reply_markup=join_keyboard()
        )


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_member = await check_membership(user_id, context)
    if is_member:
        ref = context.user_data.get("pending_ref")
        await query.answer("ধন্যবাদ! ✅")
        await query.edit_message_text(
            "স্বাগতম! 🎉 নিচের বাটনে চাপুন কাজ শুরু করতে।", reply_markup=open_app_keyboard(ref)
        )
    else:
        await query.answer("আপনি এখনো চ্যানেলে জয়েন করেননি! আগে জয়েন করুন।", show_alert=True)


def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


def run_bot():
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))

    # বটের username জেনে নিয়ে ক্যাশে রাখা (রেফারেল লিংক বানাতে লাগবে)
    async def cache_username(app_):
        me = await app_.bot.get_me()
        BOT_USERNAME_CACHE["value"] = me.username
        print(f"বট চালু: @{me.username}")

    bot_app.post_init = cache_username
    print("Bot চালু হচ্ছে...")
    bot_app.run_polling()


if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)
    run_bot()
