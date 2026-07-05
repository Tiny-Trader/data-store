# EOD sync (systemd)

Daily end-of-day candle sync for the watchlist. The job is idempotent and
resumable (already-stored instrument-days are skipped), so a missed or crashed
run is safe to re-run — `Persistent=true` + `Restart=on-failure` handle that.

## Install (on the VPS)

Adjust `User` and `WorkingDirectory` in `tt-eod.service`, then:

```bash
sudo cp tt-eod.service tt-eod.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tt-eod.timer
```

## Operate

```bash
systemctl list-timers tt-eod.timer      # next run
systemctl start tt-eod.service          # run now (manual)
journalctl -u tt-eod.service -f         # live logs
```

Failures are also logged to `logs/eod.log` in the working directory. To re-run a
specific day: `poetry run python manage.py sync_eod --date YYYY-MM-DD`.
