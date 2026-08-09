# AutoBrain Backup Agent

The agent side of the AutoBrain backup system. Connects to an AutoBrain
instance with its **admin API key**, downloads a full-database snapshot, keeps
local copies, and hands the file to `autobrain-backup` for off-box storage.

Deterministic, stdlib-only, no AI dependency. Failed attempts are logged and
retried on the next interval; a corrupt or non-AutoBrain payload is never
saved.

## How it works

1. Every hour (default), `GET {AUTOBRAIN_URL}/admin-api/backup` with header
   `X-Admin-API-Key: {AUTOBRAIN_API_KEY}`.
2. Validates the payload is a real AutoBrain backup (`app=autobrain`,
   `kind=backup`, non-empty `data`).
3. Saves `autobrain-backup-<created_at>.json` to `OUT_DIR`, pruning to `KEEP`
   latest copies.
4. If `TARGET_URL` is set, POSTs the file to `autobrain-backup`'s ingest
   endpoint for off-box retention.

## Usage

```bash
export AUTOBRAIN_URL=https://app.autobrainservice.app
export AUTOBRAIN_API_KEY=xxxxxxxx
export TARGET_URL=https://backup.example.com/ingest

python3 agent.py          # run forever, hourly
python3 agent.py --once   # single backup, then exit
```

Systemd timer (recommended over the loop): run `--once` hourly via
`systemd.timer`, or use cron `0 * * * *`.

## Configuration

| Env            | Default            | Purpose                                  |
| -------------- | ------------------ | ---------------------------------------- |
| `AUTOBRAIN_URL`| *(required)*       | Base URL of the AutoBrain instance.      |
| `AUTOBRAIN_API_KEY` | *(required)*  | Admin API key (`X-Admin-API-Key`).       |
| `BACKUP_ENDPOINT` | `/admin-api/backup` | Snapshot path.                          |
| `OUT_DIR`      | `./backups`        | Local copy directory.                    |
| `KEEP`         | `30`               | Local copies retained (0 = keep all).    |
| `TARGET_URL`   | *(unset)*          | `autobrain-backup` ingest URL (POST).    |
| `TARGET_KEY`   | *(unset)*          | API key for the ingest target.           |
| `TARGET_INSTANCE` | *(unset)*       | Target instance id; appends `?instance=` to `TARGET_URL` (multi-tenant). |
| `CA_BUNDLE`    | *(unset)*          | Custom CA bundle for TLS.                |

## Run

```bash
python3 test_agent.py
```

## License

MIT — see [LICENSE](LICENSE).
