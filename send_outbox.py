#!/usr/bin/env python3
"""Run by the "Send Telegram alerts" workflow: sends every outbox/*.txt file added by the pushed commits."""
import os, subprocess, sys, urllib.parse, urllib.request

tok, chat = os.environ["TOKEN"], os.environ["CHAT"]
before, after = os.environ.get("BEFORE", ""), os.environ["AFTER"]
if not before or set(before) == {"0"}:
    rng = [f"{after}~1", after]
else:
    rng = [before, after]
files = subprocess.run(["git", "diff", "--name-only", "--diff-filter=A", *rng, "--", "outbox/"],
                       capture_output=True, text=True, check=True).stdout.split()
print(f"{len(files)} new message(s)")
if not files:
    sys.exit("No new outbox files found in this push (unexpected)")
failed = 0
for f in sorted(files):
    text = open(f, encoding="utf-8").read()
    for i in range(0, len(text), 3800):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[i:i + 3800],
                                       "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=30)
            print(f"sent {f}")
        except Exception as e:
            failed += 1
            print(f"FAILED {f}: {e}")
sys.exit(1 if failed else 0)
