"""Guruhdagi quiz javoblarini yig'adi va statistika tuzadi.

Telegram bot yuborgan anonim bo'lmagan quizlar bo'yicha:
  - `poll` yangilanishi: savol va to'g'ri javob (correct_option_id)
  - `poll_answer` yangilanishi: kim qaysi variantni tanladi
getUpdates yangilanishlarni faqat 24 soat saqlaydi, shuning uchun bu skript
muntazam (har yuborishda) ishga tushadi va hammasini stats/ papkasiga yozadi.
"""
import datetime, json, os, urllib.parse, urllib.request

TOKEN = os.environ["TELEGRAM_TOKEN"]
os.makedirs("stats", exist_ok=True)
DB = "stats/data.json"
db = json.load(open(DB, encoding="utf-8")) if os.path.exists(DB) else {"offset": 0, "polls": {}, "answers": {}, "users": {}}


def api(method, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}?" + urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(url, timeout=60))


while True:
    res = api("getUpdates", offset=db["offset"], timeout=0, limit=100,
              allowed_updates=json.dumps(["poll", "poll_answer"]))
    ups = res.get("result", [])
    if not ups:
        break
    for u in ups:
        db["offset"] = u["update_id"] + 1
        if "poll" in u:
            p = u["poll"]
            if p.get("type") == "quiz" and p.get("correct_option_id") is not None:
                db["polls"][p["id"]] = {"q": p["question"][:120], "correct": p["correct_option_id"]}
        if "poll_answer" in u:
            a = u["poll_answer"]
            user = a.get("user")
            if not user:
                continue  # anonim admin nomidan berilgan ovoz
            uid = str(user["id"])
            name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)
            db["users"][uid] = {"name": name, "username": user.get("username", "")}
            key = f'{a["poll_id"]}:{uid}'
            if a.get("option_ids"):
                db["answers"][key] = a["option_ids"][0]
            else:
                db["answers"].pop(key, None)  # ovozini qaytarib olgan

# Statistika
rows = {}
for key, opt in db["answers"].items():
    pid, uid = key.split(":")
    poll = db["polls"].get(pid)
    if poll is None:
        continue
    r = rows.setdefault(uid, [0, 0])
    r[0 if opt == poll["correct"] else 1] += 1

table = sorted(rows.items(), key=lambda kv: (-kv[1][0], kv[1][1]))
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5))).strftime("%Y-%m-%d %H:%M")
lines = [f"# Quiz statistikasi ({now}, Toshkent)", "",
         f"Hisobga olingan quizlar: {len(db['polls'])}, ishtirokchilar: {len(table)}", "",
         "| # | Ishtirokchi | To'g'ri | Noto'g'ri | Jami | Natija |", "|---|---|---|---|---|---|"]
for i, (uid, (ok, bad)) in enumerate(table, 1):
    u = db["users"].get(uid, {})
    nm = u.get("name") or uid
    if u.get("username"):
        nm += f" (@{u['username']})"
    tot = ok + bad
    lines.append(f"| {i} | {nm} | {ok} | {bad} | {tot} | {round(100 * ok / tot)}% |")
open("stats/STATS.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n".join(lines))
