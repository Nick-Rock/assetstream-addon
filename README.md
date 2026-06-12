# AssetStream — Home Assistant Add-on

Claude-powered inventory capture that syncs directly to HomeBox. Take two photos
of an item, Claude extracts name/brand/model/serial, you confirm, and it creates
the item with both photos attached in HomeBox — no Google Sheet, no manual import.

## Quick start

1. Create a **public** GitHub repo (e.g. `assetstream-addon`) and push these
   files preserving structure.
2. Replace `YOUR_GITHUB_USERNAME` in `repository.yaml` and `assetstream/DOCS.md`.
3. In Home Assistant: Settings -> Apps -> App Store -> menu -> Repositories ->
   add your repo URL.
4. Install AssetStream, fill in the config (Anthropic key, HomeBox URL + token),
   start it, open the Web UI.

## Structure

```
assetstream-addon/
├── repository.yaml
├── README.md
└── assetstream/
    ├── config.yaml        # add-on manifest + config schema
    ├── build.yaml         # HA python base image per-arch
    ├── Dockerfile
    ├── run.sh             # reads config via bashio, launches gunicorn
    ├── requirements.txt
    ├── DOCS.md
    └── app/
        ├── server.py      # Flask: /api/analyze (Claude) + /api/save (HomeBox)
        └── static/
            └── index.html # native-camera capture UI
```

## How it works

- Camera capture uses a native file input (`capture="environment"`) so it works
  over plain HTTP — no certificate required.
- `server.py` holds both API keys server-side. `/api/analyze` calls Claude
  vision and returns structured JSON; `/api/save` creates the HomeBox entity,
  sets serial/model/manufacturer, and uploads both photos as attachments.
- Only outbound internet call: this add-on -> api.anthropic.com. HomeBox stays
  on the LAN.

See `assetstream/DOCS.md` for full setup and security notes.
