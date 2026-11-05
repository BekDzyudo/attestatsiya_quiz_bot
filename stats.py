"""Guruhdagi quiz javoblarini yig'adi, statistika tuzadi va bot buyruqlariga javob beradi.

Telegram bot yuborgan anonim bo'lmagan quizlar bo'yicha:
  - `poll` yangilanishi: savol va to'g'ri javob (correct_option_id)
  - `poll_answer` yangilanishi: kim qaysi variantni tanladi
  - `message`: /stat va /men buyruqlari
getUpdates yangilanishlarni faqat 24 soat saqlaydi, shuning uchun skript
muntazam ishga tushadi va hammasini stats/ papkasiga yozadi.

Ishlatish:
  python3 stats.py               # bir marta yig'ish va STATS.md yozish
  python3 stats.py --listen 290  # 290 soniya davomida buyruqlarni kutib, darhol javob berish
"""
import datetime, html, json, os, sys, time, urllib.parse, urllib.request

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "-1003982072134")
os.makedirs("stats", exist_ok=True)
DB = "stats/data.json"
db = json.load(open(DB, encoding="utf-8")) if os.path.exists(DB) else {"offset": 0, "polls": {}, "answers": {}, "users": {}}

# Statistikadan chiqarilgan foydalanuvchilar (javoblari saqlanmaydi va hisoblanmaydi)
EXCLUDE = {"7149515601"}  # Дилчехра — 2026-11-04 da egasining so'rovi bilan chiqarildi
TZ = datetime.timezone(datetime.timedelta(hours=5))


def api(method, timeout=60, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data)
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return json.load(e)


def full_name(u):
    return " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x) or str(u.get("id"))


def compute():
    rows = {}
    for key, opt in db["answers"].items():
        pid, uid = key.split(":")
        poll = db["polls"].get(pid)
        if poll is None or uid in EXCLUDE:
            continue
        r = rows.setdefault(uid, [0, 0])
        r[0 if opt == poll["correct"] else 1] += 1
    return sorted(rows.items(), key=lambda kv: (-kv[1][0], kv[1][1]))


def label(uid):
    u = db["users"].get(uid, {})
    return u.get("name") or uid


def stat_text():
    table = compute()
    now = datetime.datetime.now(TZ).strftime("%d.%m %H:%M")
    out = [f"📊 <b>Quiz reytingi</b> ({now})", f"Quizlar: {len(db['polls'])}, ishtirokchilar: {len(table)}", ""]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (uid, (ok, bad)) in enumerate(table, 1):
        tot = ok + bad
        out.append(f"{medals.get(i, f'{i}.')} {html.escape(label(uid), quote=False)} — ✅ {ok}  ❌ {bad}  ({round(100 * ok / tot)}%)")
    out += ["", "Tartib: to'g'ri javoblar soni bo'yicha. Foiz = to'g'ri ÷ javob berilgan savollar."]
    return "\n".join(out)


def me_text(user):
    uid = str(user["id"])
    table = compute()
    for i, (u, (ok, bad)) in enumerate(table, 1):
        if u == uid:
            tot = ok + bad
            return (f"👤 <b>{html.escape(full_name(user), quote=False)}</b>\n"
                    f"O'rin: {i} / {len(table)}\n✅ To'g'ri: {ok}\n❌ Xato: {bad}\n"
                    f"Javob berilgan: {tot} / {len(db['polls'])}\nNatija: {round(100 * ok / tot)}%")
    return f"{html.escape(full_name(user), quote=False)}, sizda hali hisobga olingan javob yo'q."


def handle_message(m):
    text = (m.get("text") or "").strip()
    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0].lower()
    if cmd in ("/stat", "/statistika", "/reyting"):
        reply = stat_text()
    elif cmd in ("/men", "/natijam"):
        reply = me_text(m["from"])
    else:
        return
    api("sendMessage", chat_id=m["chat"]["id"], text=reply, parse_mode="HTML",
        reply_parameters=json.dumps({"message_id": m["message_id"], "allow_sending_without_reply": True}))


def process(u):
    db["offset"] = u["update_id"] + 1
    if "poll" in u:
        p = u["poll"]
        if p.get("type") == "quiz" and p.get("correct_option_id") is not None:
            db["polls"][p["id"]] = {"q": p["question"][:120], "correct": p["correct_option_id"]}
    if "poll_answer" in u:
        a = u["poll_answer"]
        user = a.get("user")
        if not user:
            return  # anonim admin nomidan berilgan ovoz
        uid = str(user["id"])
        if uid in EXCLUDE:
            return
        db["users"][uid] = {"name": full_name(user), "username": user.get("username", "")}
        key = f'{a["poll_id"]}:{uid}'
        if a.get("option_ids"):
            db["answers"][key] = a["option_ids"][0]
        else:
            db["answers"].pop(key, None)  # ovozini qaytarib olgan
    if "message" in u:
        try:
            handle_message(u["message"])
        except Exception as e:
            print("buyruqqa javobda xato:", e)


ALLOWED = json.dumps(["poll", "poll_answer", "message"])


LIVE = os.environ.get("LIVE_RATING", "1") == "1"
last_live = 0.0


def fetch(long_poll=0):
    params = dict(offset=db["offset"], limit=100, allowed_updates=ALLOWED)
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params["timeout"] = long_poll
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode())
    try:
        res = json.load(urllib.request.urlopen(req, timeout=long_poll + 30))
    except Exception as e:
        print("getUpdates xato:", e)
        time.sleep(3)
        return 0
    ups = res.get("result", [])
    for u in ups:
        process(u)
    if LIVE and any("poll_answer" in u for u in ups):
        global last_live
        # Telegram cheklovlari uchun: tahrirlar orasida kamida 3 soniya
        if time.time() - last_live < 3:
            time.sleep(3 - (time.time() - last_live))
        try:
            update_live()
        except Exception as e:
            print("jonli reytingda xato:", e)
        last_live = time.time()
    return len(ups)


def write_report():
    for k in [k for k in db["answers"] if k.split(":")[1] in EXCLUDE]:
        del db["answers"][k]
    for uid in EXCLUDE:
        db["users"].pop(uid, None)
    table = compute()
    members = None
    try:
        members = api("getChatMemberCount", chat_id=CHAT)["result"]
    except Exception as e:
        print("a'zolar sonini olishda xato:", e)
    now = datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"# Quiz statistikasi ({now}, Toshkent)", "",
             f"Hisobga olingan quizlar: {len(db['polls'])}, ishtirokchilar: {len(table)}", "",
             "| # | Ishtirokchi | To'g'ri | Noto'g'ri | Jami | Natija |", "|---|---|---|---|---|---|"]
    for i, (uid, (ok, bad)) in enumerate(table, 1):
        u = db["users"].get(uid, {})
        nm = label(uid) + (f" (@{u['username']})" if u.get("username") else "")
        tot = ok + bad
        lines.append(f"| {i} | {nm} | {ok} | {bad} | {tot} | {round(100 * ok / tot)}% |")
    if members is not None:
        lines += ["", f"Guruh a'zolari (bot bilan): {members}. Javob bergan: {len(table)}. "
                  f"Javob bermagan: taxminan {max(members - 1 - len(EXCLUDE) - len(table), 0)}."]
    open("stats/STATS.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return lines


def update_live():
    """Guruhdagi qadalgan jonli reyting xabarini yangilaydi (yo'q bo'lsa yuborib, qadaydi)."""
    text = stat_text().replace("📊 <b>Quiz reytingi</b>", "📌 <b>Jonli reyting</b> (har javobda yangilanadi)\n🕒", 1)
    mid = db.get("live_msg")
    if mid:
        r = api("editMessageText", chat_id=CHAT, message_id=mid, text=text, parse_mode="HTML")
        if r.get("ok") or "not modified" in (r.get("description") or ""):
            return
        print("jonli reytingni tahrirlab bo'lmadi:", r.get("description"))
    r = api("sendMessage", chat_id=CHAT, text=text, parse_mode="HTML", disable_notification="true")
    if not r.get("ok"):
        print("jonli reyting yuborilmadi:", r.get("description"))
        return
    db["live_msg"] = r["result"]["message_id"]
    p = api("pinChatMessage", chat_id=CHAT, message_id=db["live_msg"], disable_notification="true")
    if not p.get("ok"):
        print("qadab bo'lmadi:", p.get("description"))
    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        cmds = [{"command": "stat", "description": "Guruh reytingi: to'g'ri va xato javoblar"},
                {"command": "men", "description": "Mening natijam"}]
        for scope in ({"type": "default"}, {"type": "all_group_chats"}):
            print(api("setMyCommands", commands=json.dumps(cmds, ensure_ascii=False), scope=json.dumps(scope)))
    elif len(sys.argv) > 2 and sys.argv[1] == "--listen":
        deadline = time.time() + int(sys.argv[2])
        while True:
            left = int(deadline - time.time())
            if left <= 1:
                break
            fetch(long_poll=min(25, left - 1))
        write_report()
    else:
        while fetch(0):
            pass
        print("\n".join(write_report()))
        if os.environ.get("LIVE_RATING", "1") == "1":
            try:
                update_live()
            except Exception as e:
                print("jonli reytingda xato:", e)
