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
# Faol guruh config.json dan olinadi ("pending" — yangi guruh ID'si hali kiritilmagan)
LEGACY = "-1003982072134"  # birinchi ("Test") guruh — 2026-11-23 dan yana faol (config.json "extra")
try:
    _cfg = json.load(open("config.json", encoding="utf-8"))
    CHAT = str(_cfg["chat_id"])
    EXTRA = [str(e["chat_id"]) for e in _cfg.get("extra", [])]
except (OSError, KeyError, ValueError):
    CHAT, EXTRA = os.environ.get("TELEGRAM_CHAT_ID", LEGACY), []
PENDING = CHAT == "pending"
os.makedirs("stats", exist_ok=True)
CHATS = "stats/chats.json"       # bot qo'shilgan guruhlar ro'yxati
MAIN = CHAT


def _paths(chat):
    tag = chat.lstrip("-")
    db_f = "stats/data.json" if chat == LEGACY else f"stats/data_{tag}.json"
    rep = "stats/STATS.md" if chat == LEGACY else f"stats/STATS_{tag}.md"
    return tag, db_f, rep, f"stats/sent_{tag}.json"


def _load(chat):
    tag, db_f, rep, sent_f = _paths(chat)
    if os.path.exists(db_f):
        d = json.load(open(db_f, encoding="utf-8"))
    else:
        # yangi guruh: eski bazadagi getUpdates offsetidan davom etiladi, reyting noldan
        off = 0
        for f in ("stats/data.json", "stats/data_pending.json"):
            if os.path.exists(f):
                off = max(off, json.load(open(f, encoding="utf-8")).get("offset", 0))
        d = {"offset": off, "polls": {}, "answers": {}, "users": {}}
    return {"CHAT": chat, "TAG": tag, "DB": db_f, "REPORT": rep, "SENT": sent_f, "db": d,
            "admins": {"t": 0, "ids": set()}, "last_live": 0.0}


CTX = {c: _load(c) for c in [MAIN] + [e for e in EXTRA if e != MAIN]}
GROUPS = list(CTX)
CUR = None


def use(chat):
    """Ish olib boriladigan guruhni almashtiradi (CHAT, DB, REPORT, SENT, db globallari)."""
    global CHAT, TAG, DB, REPORT, SENT, db, _admins, CUR
    c = CTX[chat]
    CUR = c
    CHAT, TAG, DB, REPORT, SENT, db, _admins = c["CHAT"], c["TAG"], c["DB"], c["REPORT"], c["SENT"], c["db"], c["admins"]


use(MAIN)
chats = json.load(open(CHATS, encoding="utf-8")) if os.path.exists(CHATS) else {}


def migrate():
    """Bir martalik: 2026-11-23 gacha asosiy bazaga yozilib qolgan Test guruhi javoblarini o'z bazasiga ko'chiradi."""
    if LEGACY not in CTX or LEGACY == MAIN or CTX[LEGACY]["db"].get("mig_1123"):
        return
    m, t = CTX[MAIN]["db"], CTX[LEGACY]["db"]
    sent = sent_ids(LEGACY)
    for k in [k for k in m["answers"] if k.split(":")[0] in sent]:
        t["answers"][k] = m["answers"].pop(k)
        uid = k.split(":")[1]
        if uid in m["users"]:
            t["users"].setdefault(uid, m["users"][uid])
    t["mig_1123"] = 1


def save_db():
    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def sent_ids(chat=None):
    f = CTX[chat]["SENT"] if chat else SENT
    return set(json.load(open(f, encoding="utf-8"))) if os.path.exists(f) else set()


def known_polls(chat):
    f = f"stats/polls_{CTX[chat]['TAG']}.json"
    return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {}


def merge_known():
    """send.py yozib qo'ygan (yuborish paytidagi) to'g'ri javoblarni bazaga qo'shadi."""
    for c in GROUPS:
        for pid, p in known_polls(c).items():
            CTX[c]["db"]["polls"].setdefault(pid, p)


def owner_of_poll(pid):
    """Poll qaysi guruhga yuborilganini aniqlaydi (yuborilgan ID'lar yoki saqlangan polllar bo'yicha)."""
    for c in GROUPS:
        if pid in CTX[c]["db"]["polls"] or pid in sent_ids(c):
            return c
    return None


def note_chat(c, status=None):
    if c.get("type") not in ("group", "supergroup"):
        return
    e = chats.setdefault(str(c["id"]), {})
    e["title"] = c.get("title", "")
    if status:
        e["status"] = status
    e["seen"] = datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    json.dump(chats, open(CHATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

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


def is_admin(m):
    """Xabar yuboruvchi guruh admini (yoki guruh nomidan yozgan anonim admin) ekanini tekshiradi."""
    sc = m.get("sender_chat")
    if sc and str(sc.get("id")) == CHAT:
        return True
    if time.time() - _admins["t"] > 300:
        r = api("getChatAdministrators", chat_id=CHAT)
        if r.get("ok"):
            _admins["ids"] = {str(a["user"]["id"]) for a in r["result"]}
            _admins["t"] = time.time()
    return str(m.get("from", {}).get("id")) in _admins["ids"]


def setup_menu():
    """Buyruqlar menyusi: oddiy a'zolarga faqat /men, adminlarga /stat ham."""
    men = {"command": "men", "description": "Mening natijam"}
    stat = {"command": "stat", "description": "Guruh reytingi (faqat adminlar)"}
    out = []
    for scope in ({"type": "default"}, {"type": "all_group_chats"}):
        out.append(api("setMyCommands", commands=json.dumps([men], ensure_ascii=False), scope=json.dumps(scope)))
    if not PENDING:
        for c in GROUPS:
            out.append(api("setMyCommands", commands=json.dumps([stat, men], ensure_ascii=False),
                           scope=json.dumps({"type": "chat_administrators", "chat_id": int(c)})))
    return out


def handle_message(m):
    note_chat(m["chat"])
    if str(m["chat"]["id"]) not in CTX:
        return  # buyruqlarga faqat faol guruhlarda javob beriladi
    use(str(m["chat"]["id"]))
    text = (m.get("text") or "").strip()
    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0].lower()
    if cmd in ("/stat", "/statistika", "/reyting"):
        if not is_admin(m):
            return  # /stat faqat adminlar uchun; boshqalar qadalgan jonli reytingni ko'radi
        reply = stat_text()
    elif cmd in ("/men", "/natijam"):
        reply = me_text(m["from"])
    else:
        return
    api("sendMessage", chat_id=m["chat"]["id"], text=reply, parse_mode="HTML",
        reply_parameters=json.dumps({"message_id": m["message_id"], "allow_sending_without_reply": True}))


def process(u):
    CTX[MAIN]["db"]["offset"] = u["update_id"] + 1
    if "poll" in u:
        p = u["poll"]
        owner = owner_of_poll(p["id"])
        if owner and p.get("type") == "quiz" and p.get("correct_option_id") is not None:
            CTX[owner]["db"]["polls"][p["id"]] = {"q": p["question"][:120], "correct": p["correct_option_id"]}
    if "poll_answer" in u:
        a = u["poll_answer"]
        user = a.get("user")
        if not user:
            return  # anonim admin nomidan berilgan ovoz
        uid = str(user["id"])
        if uid in EXCLUDE:
            return
        owner = owner_of_poll(a["poll_id"]) or MAIN
        d = CTX[owner]["db"]
        d["users"][uid] = {"name": full_name(user), "username": user.get("username", "")}
        key = f'{a["poll_id"]}:{uid}'
        if a.get("option_ids"):
            d["answers"][key] = a["option_ids"][0]
        else:
            d["answers"].pop(key, None)  # ovozini qaytarib olgan
        TOUCHED.add(owner)
    if "my_chat_member" in u:
        cm = u["my_chat_member"]
        note_chat(cm["chat"], cm.get("new_chat_member", {}).get("status"))
    if "message" in u:
        try:
            handle_message(u["message"])
        except Exception as e:
            print("buyruqqa javobda xato:", e)
        finally:
            use(MAIN)


TOUCHED = set()  # yangi javob kelgan guruhlar (jonli reyting yangilanadi)


ALLOWED = json.dumps(["poll", "poll_answer", "message", "my_chat_member"])


LIVE = os.environ.get("LIVE_RATING", "1") == "1" and not PENDING
last_live = 0.0


def fetch(long_poll=0):
    merge_known()
    migrate()
    params = dict(offset=CTX[MAIN]["db"]["offset"], limit=100, allowed_updates=ALLOWED)
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
    TOUCHED.clear()
    for u in ups:
        try:
            process(u)
        except Exception as e:
            print("yangilanishni qayta ishlashda xato:", e)
    use(MAIN)
    if ups:
        # har bir qabul qilingan to'plam darhol diskka yoziladi (jarayon uzilsa ham yo'qolmaydi)
        for c in GROUPS:
            use(c)
            save_db()
        use(MAIN)
    if LIVE:
        for c in [c for c in GROUPS if c in TOUCHED]:
            use(c)
            # Telegram cheklovlari uchun: tahrirlar orasida kamida 3 soniya
            if time.time() - CUR["last_live"] < 3:
                time.sleep(3 - (time.time() - CUR["last_live"]))
            try:
                update_live()
            except Exception as e:
                print("jonli reytingda xato:", e)
            CUR["last_live"] = time.time()
        use(MAIN)
    return len(ups)


def write_report():
    merge_known()
    migrate()
    if PENDING:
        json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return ["Faol guruh hali tanlanmagan (config.json: pending)"]
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
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
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
        print(setup_menu())
    elif len(sys.argv) > 2 and sys.argv[1] == "--listen":
        deadline = time.time() + int(sys.argv[2])
        try:
            while True:
                left = int(deadline - time.time())
                if left <= 1:
                    break
                fetch(long_poll=min(25, left - 1))
        finally:
            for c in GROUPS:
                use(c)
                write_report()
    else:
        if db.get("menu_v") != 2:
            try:
                if all(r.get("ok") for r in setup_menu()):
                    db["menu_v"] = 2
            except Exception as e:
                print("menyuni yangilashda xato:", e)
        while fetch(0):
            pass
        for c in GROUPS:
            use(c)
            print("\n".join(write_report()))
        use(MAIN)
