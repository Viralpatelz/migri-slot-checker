# Migri slot checker

Checks Migri's booking system (migri.vihta.com) every 15 minutes for free appointment slots
for **Residence permit: Work** and **Permanent residence permit**, at every office, and sends
new slots to Telegram.

- Runs on GitHub Actions (`.github/workflows/check.yml`), no PC needed.
- Gentle: one request at a time (~40 per check). If Migri answers 403, it pauses 6 hours and says so on Telegram.
- Sends a daily status message after 09:00 Helsinki time.
- `state.json` remembers already-reported slots (committed by the workflow).

Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
Change services: edit `ONLY_SERVICES` in the workflow (service-id prefixes, see `SERVICE_EN` in `migri_checker.py`).
Manual test: Actions tab → "Migri slot check" → Run workflow → tick "force".
