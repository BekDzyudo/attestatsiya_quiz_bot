"""Navbatdagi quizni Telegram guruhiga yuboradi va state.json dagi hisoblagichni oshiradi."""
import datetime, json, os, sys, urllib.error, urllib.parse, urllib.request

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]

now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5)))
if now.hour < 9 and not os.environ.get("FORCE"):
    print("Tungi vaqt (Toshkent", now.strftime("%H:%M"), ") — yuborilmadi")
    sys.exit(0)

bank = json.load(open("quizzes.json", encoding="utf-8"))
state = json.load(open("state.json", encoding="utf-8"))

# GitHub jadvali ba'zan kechikadi yoki o'tkazib yuboradi: oxirgi yuborilganidan
# 12 daqiqadan ko'p o'tgan bo'lsa (o'sha kunning o'zida), 2 ta savol yuboriladi.
count = 1
try:
    last = datetime.datetime.fromisoformat(state["last_sent"])
    gap = (now - last).total_seconds() / 60
    if last.date() == now.date() and gap > 12:
        count = 2
except (KeyError, ValueError):
    pass


def send_one(idx):
    q = bank[idx]

    data = {
        "chat_id": CHAT,
        "question": q["question"],
        "options": json.dumps([{"text": o} for o in q["options"]], ensure_ascii=False),
        "type": "quiz",
        "is_anonymous": "false",
        "correct_option_id": q["correct_option_id"],
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

    print(f"#{idx + 1}/{len(bank)}:", res.get("ok"), res.get("description") or "")
    return res.get("ok")


sent = 0
for _ in range(count):
    idx = state["next"] % len(bank)
    if not send_one(idx):
        break
    state["next"] = idx + 1
    sent += 1

if sent:
    state["last_sent"] = now.isoformat(timespec="minutes")
    json.dump(state, open("state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
if sent < count and sent == 0:
    sys.exit(1)
