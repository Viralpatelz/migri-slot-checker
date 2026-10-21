# Migri slot checker

Checks Migri's booking system (migri.vihta.com) every hour for free appointment slots
for **Residence permit: Work** and **Permanent residence permit**, at every office, and sends
new slots to Telegram.

- **Checking** runs hourly as a Claude scheduled task in Anthropic's cloud (`OUTBOX=1 python3 migri_checker.py`).
  GitHub can't check Migri itself: Migri's firewall blocks GitHub's servers (403).
- **Sending**: each alert is committed as a file in `outbox/`; the `Send Telegram alerts` workflow
  (`.github/workflows/notify.yml`) sends new ones to Telegram with the repo secrets. The token never leaves GitHub.
- Gentle: one request at a time (~40 per check). If Migri answers 403, it pauses 6 hours and says so on Telegram.
- Sends a daily status message after 09:00 Helsinki time.
- `state.json` remembers already-reported slots (committed by the workflow).

Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
Change services: edit `ONLY_SERVICES` in the workflow (service-id prefixes, see `SERVICE_EN` in `migri_checker.py`).
Manual test: run `OUTBOX=1 FORCE=1 python3 migri_checker.py`, commit `state.json` + `outbox/`, push.
