"""Navbatdagi quizni Telegram guruhiga yuboradi va state.json dagi hisoblagichni oshiradi."""
import datetime, json, os, random, sys, urllib.error, urllib.parse, urllib.request

TOKEN = os.environ["TELEGRAM_TOKEN"]
try:
    CHAT = str(json.load(open("config.json", encoding="utf-8"))["chat_id"])
except (OSError, KeyError, ValueError):
    CHAT = os.environ["TELEGRAM_CHAT_ID"]
if CHAT == "pending":
    print("Faol guruh hali tanlanmagan (config.json) — yuborilmadi")
    sys.exit(0)

now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5)))
# Vaqtinchalik to'xtatish: state.json dagi "pause_until" vaqtigacha savol yuborilmaydi
try:
    _pause = json.load(open("state.json", encoding="utf-8")).get("pause_until")
    if _pause and now < datetime.datetime.fromisoformat(_pause) and not os.environ.get("FORCE"):
        print("to'xtatilgan:", _pause)
        sys.exit(0)
except (OSError, ValueError):
    pass
if (now.hour < 9 or now.hour >= 23) and not os.environ.get("FORCE"):
    print("Tungi vaqt (Toshkent", now.strftime("%H:%M"), ") — yuborilmadi")
    sys.exit(0)

bank = json.load(open("quizzes.json", encoding="utf-8"))
MAIN_NOW = set()  # shu ishga tushishda asosiy guruhga yuborilgan savollar
state = json.load(open("state.json", encoding="utf-8"))

# GitHub jadvali ba'zan kechikadi yoki o'tkazib yuboradi: oxirgi yuborilganidan
# 15 daqiqadan ko'p o'tgan bo'lsa (o'sha kunning o'zida), 2 ta savol yuboriladi.
count = 1
try:
    last = datetime.datetime.fromisoformat(state["last_sent"])
    gap = (now - last).total_seconds() / 60
    if last.date() == now.date() and gap > 15:
        count = 2
except (KeyError, ValueError):
    pass


def make_options(q, n, bank_len):
    """Variantlarni har safar yangidan tuzadi: asosan yangi (to'g'riga yaqin) chalg'ituvchilar,
    toq aylanishlarda bittasi eskisidan; to'g'ri javob eng uzun variant bo'lib qolmasligi va
    o'rni har safar tasodifiy bo'lishi ta'minlanadi."""
    if "options" in q:  # eski format
        return q["options"], q["correct_option_id"]
    rnd = random.Random(n * 7919 + 17)
    cycle = n // bank_len
    wrong = list(q["wrong"])
    extra = [w for w in q.get("wrong_old", []) if w not in wrong and w != q["answer"]]
    if cycle % 2 == 1 and extra:
        wrong[rnd.randrange(3)] = rnd.choice(extra)
    ans = q["answer"]
    if max(len(w) for w in wrong) < 0.9 * len(ans):
        pool = sorted((set(q["wrong"]) | set(q.get("wrong_old", []))) - {ans}, key=len, reverse=True)
        if pool and pool[0] not in wrong:
            wrong[min(range(3), key=lambda k: len(wrong[k]))] = pool[0]
    opts = wrong + [ans]
    rnd.shuffle(opts)
    return opts, opts.index(ans)


def send_one(chat, bank, idx, n):
    q = bank[idx]
    options, correct = make_options(q, n, len(bank))

    data = {
        "chat_id": chat,
        "question": q["question"],
        "options": json.dumps([{"text": o} for o in options], ensure_ascii=False),
        "type": "quiz",
        "is_anonymous": "false",
        "correct_option_id": correct,
        "explanation": q["explanation"],
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendPoll",
        data=urllib.parse.urlencode(data).encode(),
    )
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        res = json.load(e)

    print(f"[{chat}] #{idx + 1}/{len(bank)}:", res.get("ok"), res.get("description") or "")
    if res.get("ok"):
        f = f"stats/sent_{chat.lstrip('-')}.json"
        ids = json.load(open(f, encoding="utf-8")) if os.path.exists(f) else []
        ids.append(res["result"]["poll"]["id"])
        os.makedirs("stats", exist_ok=True)
        json.dump(ids, open(f, "w", encoding="utf-8"))
    return q["question"] if res.get("ok") else None


# Yuboriladigan guruhlar: asosiy guruh (config.json "chat_id", quizzes.json, state["next"])
# va config.json "extra" dagi qo'shimcha guruhlar — har birining o'z savollar banki va hisoblagichi bor.
targets = [{"chat_id": CHAT, "bank": "quizzes.json", "key": "next", "main": True}]
try:
    targets += json.load(open("config.json", encoding="utf-8")).get("extra", [])
except (OSError, ValueError):
    pass

main_sent = 0
for t in targets:
    tbank = bank if t["bank"] == "quizzes.json" else json.load(open(t["bank"], encoding="utf-8"))
    key = t["key"]
    state.setdefault(key, 0)
    sent_now = []  # shu ishga tushishda asosiy guruhga ketgan savollar (takrorlanmasin)
    for _ in range(count):
        idx = state[key] % len(tbank)
        # qo'shimcha guruhga ayni paytda asosiy guruhdagi savolning o'zi ketmasin
        if not t.get("main") and tbank[idx]["question"] in MAIN_NOW:
            idx = (idx + 1) % len(tbank)
        sent_q = send_one(str(t["chat_id"]), tbank, idx, state[key])
        if not sent_q:
            break
        state[key] = idx + 1
        if t.get("main"):
            MAIN_NOW.add(sent_q)
            main_sent += 1
        sent_now.append(sent_q)
    if sent_now:
        state["last_sent"] = now.isoformat(timespec="minutes")
        json.dump(state, open("state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if main_sent == 0:
    sys.exit(1)
