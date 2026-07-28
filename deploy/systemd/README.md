# systemd units

See [`../README.md`](../README.md) for the full prototype deploy path.

```bash
sudo cp tt-api.service tt-eod.service tt-eod.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tt-api.service
sudo systemctl enable --now tt-eod.timer
```

| Unit | Role |
|------|------|
| `tt-api.service` | gunicorn API on `:8000` |
| `tt-eod.service` | oneshot `sync_eod` |
| `tt-eod.timer` | weekdays 18:30 IST |

Fix `User`, `WorkingDirectory`, and the Poetry path (`which poetry`) before enabling.
