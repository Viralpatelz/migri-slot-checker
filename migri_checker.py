#!/usr/bin/env python3
"""Migri appointment checker for GitHub Actions.

Checks Migri's booking system for free slots and sends NEW ones to Telegram.
Settings come from environment variables (set as GitHub secrets / workflow env):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   required for alerts
  ONLY_SERVICES   comma list of service-id prefixes (default: Work permit + Permanent residence permit)
  DAYS_AHEAD      scan this many days ahead (default: rest of the current month)
  FORCE=1         send the current slot list even if nothing is new (manual test)
State (already-reported slots, heartbeat, block info) is kept in state.json, committed back by the workflow.
"""
import json, os, sys, time, datetime, urllib.request, urllib.error, urllib.parse, pathlib

HERE = pathlib.Path(__file__).resolve().parent
STATE = HERE / "state.json"
B = "https://migri.vihta.com/public/migri/api"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
BOOK_URL = "https://migri.vihta.com/public/migri/#/reservation"
DELAY = 0.6          # seconds between requests: one at a time, gentle
BLOCK_PAUSE_H = 6    # if Migri answers 403, pause this many hours

SERVICE_EN = {
    "2906a690": "Residence permit: Work", "a87390ae": "Residence permit: Family",
    "d9638dd8": "Residence permit: Study", "f2a99365": "Residence permit: Other grounds",
    "3e03034d": "Permanent residence permit", "f5daa984": "Renew permanent permit card",
    "4f53e3ce": "Renew residence permit card", "e5e795f2": "EU citizen registration",
    "a10919dc": "EU family member card", "5ed69359": "Brexit",
    "000564ce": "Citizenship", "fb27b72c": "Temporary protection card",
    "b8daed03": "Refugee travel document", "28af9eb7": "Alien's passport",
}
ONLY = [x.strip() for x in os.environ.get("ONLY_SERVICES", "2906a690,3e03034d").split(",") if x.strip()]


class Blocked(Exception):
    pass


def log(msg):
    print(f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}", flush=True)


def helsinki(dt_utc):
    """UTC -> Helsinki time (EU DST: last Sun Mar..last Sun Oct, 01:00 UTC)."""
    y = dt_utc.year
    def last_sun(m):
        d = datetime.datetime(y, m, 31, 1, tzinfo=datetime.timezone.utc)
        return d - datetime.timedelta(days=(d.weekday() + 1) % 7)
    off = 3 if last_sun(3) <= dt_utc < last_sun(10) else 2
    return dt_utc.astimezone(datetime.timezone(datetime.timedelta(hours=off)))


def now_hki():
    return helsinki(datetime.datetime.now(datetime.timezone.utc))


def http_json(url, body=None, s=None):
    h = {"content-type": "application/json;charset=UTF-8", "accept": "application/json",
         "user-agent": UA, "referer": "https://migri.vihta.com/public/migri/"}
    if s:
        h["vihta-session"] = s
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        r = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code}")
        raise
    time.sleep(DELAY)
    return r


def notify(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        log("No Telegram secrets; message would be:\n" + text)
        return
    for i in range(0, len(text), 3800):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 3800],
                                       "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=30)


def scan():
    today = now_hki().date()
    if os.environ.get("DAYS_AHEAD"):
        end = today + datetime.timedelta(days=int(os.environ["DAYS_AHEAD"]))
    else:  # rest of this month
        end = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    weeks, d = [], today
    while d <= end:
        if d.isocalendar()[:2] not in weeks:
            weeks.append(d.isocalendar()[:2])
        d += datetime.timedelta(days=1)

    s = http_json(B + "/sessions")["id"]
    services = http_json(B + "/services", s=s)["services"]
    slots, errors, calls = [], 0, 0
    for svc in services:
        if ONLY and not any(svc["id"].startswith(p) for p in ONLY):
            continue
        sname = SERVICE_EN.get(svc["id"][:8], svc["name"])
        body = {"serviceSelections": [{"values": [svc["id"]]}], "extraServices": []}
        loc = http_json(B + "/services/localities", body, s)
        for l in loc.get("localities", []):
            for o in l["offices"]:
                for y, w in weeks:
                    calls += 1
                    try:
                        r = http_json(f"{B}/scheduling/offices/{o['id']}/{y}/w{w}?end_hours=24&start_hours=0", body, s)
                    except Blocked:
                        raise
                    except Exception as e:
                        errors += 1; log(f"fail {sname}/{o['name']}/w{w}: {e}"); continue
                    for day in r.get("dailyTimesByOffice", []):
                        for t in day:
                            st = t.get("startTimestamp") or t.get("start")
                            if not st:
                                continue
                            dt = datetime.datetime.fromisoformat(st.replace("Z", "+00:00"))
                            if today <= helsinki(dt).date() <= end:
                                slots.append({"service": sname, "office": o["name"], "city": l["name"], "start": st})
    if calls and errors > calls / 2:
        raise RuntimeError(f"{errors}/{calls} requests failed")
    log(f"{calls} schedule requests, {len(slots)} slots")
    return slots, today, end


def build_message(items, today, end, title):
    by_office = {}
    for x in items:
        by_office.setdefault(f'{x["office"]} ({x["city"]})', {}).setdefault(x["start"], set()).add(x["service"])
    n = sum(len(v) for v in by_office.values())
    lines = [f"🇫🇮 Migri: {n} {title} ({today:%d.%m}–{end:%d.%m})"]
    for off, times in sorted(by_office.items()):
        lines.append(f"\n📍 {off}")
        for st in sorted(times):
            t = helsinki(datetime.datetime.fromisoformat(st.replace("Z", "+00:00")))
            lines.append(f"🕒 {t:%a %d.%m %H:%M} → {', '.join(sorted(times[st]))}")
    lines.append(f"\nBook fast: {BOOK_URL}")
    return "\n".join(lines)


def main():
    force = os.environ.get("FORCE") == "1"
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = datetime.datetime.now(datetime.timezone.utc)
    today = str(now_hki().date())

    # Paused after a block? Skip quietly (keeps Migri happy).
    bu = state.get("blocked_until")
    if bu and now < datetime.datetime.fromisoformat(bu) and not force:
        log(f"paused until {bu} after Migri block")
        STATE.write_text(json.dumps(state, indent=1)); return

    status = "ok"
    try:
        slots, d0, d1 = scan()
        state["fails"] = 0
        state.pop("blocked_until", None)
        key = lambda x: f'{x["service"]}|{x["office"]}|{x["start"]}'
        seen = set(state.get("seen", []))
        new = slots if force else [x for x in slots if key(x) not in seen]
        if new:
            notify(build_message(new, d0, d1, "free slots now" if force else "NEW free slots"))
        elif force:
            notify(f"🇫🇮 Migri checker test (GitHub): no free Work/PR slots right now ({d0:%d.%m}–{d1:%d.%m}). I'll message you when one appears.")
        state["seen"] = sorted(key(x) for x in slots)
        state["last_ok"] = today  # date only, avoids a commit every run
        log(f"{len(new)} new")
    except Blocked as e:
        status = "blocked"
        until = now + datetime.timedelta(hours=BLOCK_PAUSE_H)
        state["blocked_until"] = until.isoformat(timespec="seconds")
        state["fails"] = state.get("fails", 0) + 1
        log(f"BLOCKED by Migri ({e}); pausing {BLOCK_PAUSE_H}h")
        notify(f"⛔ Migri checker: Migri's firewall blocked the check ({e}). Pausing {BLOCK_PAUSE_H} hours, then retrying automatically.")
    except Exception as e:
        status = "error"
        state["fails"] = state.get("fails", 0) + 1
        log(f"scan failed ({state['fails']} in a row): {e}")
        if state["fails"] == 4:  # ~1 hour of failures
            notify(f"⚠️ Migri checker: checks failing for ~1 hour.\nLast error: {e}\nStill retrying.")

    # Daily status after 9:00 Helsinki, whether things work or not.
    if now_hki().hour >= 9 and state.get("heartbeat") != today and not force:
        last = state.get("last_ok", "never")
        msg = ("✅ Migri checker running fine (Work permit + PR)."
               if status == "ok" else
               f"⚠️ Migri checker daily status: NOT working ({status}). Last successful check: {last}")
        notify(msg)
        state["heartbeat"] = today
    STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
