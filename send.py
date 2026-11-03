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
idx = state["next"] % len(bank)
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
if not res.get("ok"):
    sys.exit(1)

state["next"] = idx + 1
state["last_sent"] = now.isoformat(timespec="minutes")
json.dump(state, open("state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
