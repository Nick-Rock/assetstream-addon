# AssetStream

Claude-powered inventory capture. Snap two photos of an item (front + serial
plate), Claude extracts the name, brand, model, and serial number, you confirm
on screen, and it writes the item — with both photos attached — straight into
HomeBox. No spreadsheet, no manual import.

## Why this works over plain HTTP (no certificate needed)

The capture tiles use your phone's **native camera** via a standard file input,
not the browser's live-camera API. That means it works on plain `http://` with
no HTTPS and no certificate — the exact wall that blocks the in-browser QR
scanner does not apply here.

The only outbound internet call is from this add-on to `api.anthropic.com` for
the extraction step. HomeBox is reached over your LAN and never touches the
internet.

## Setup

1. Install the add-on, then open its **Configuration** tab and set:
   - `anthropic_api_key` — from console.anthropic.com (this is API billing,
     separate from a Claude.ai subscription; vision calls are a few tokens each)
   - `anthropic_model` — default `claude-sonnet-4-6` is a good balance; you can
     use a cheaper model for simple labels
   - `homebox_url` — usually `http://homebox:7745` if HomeBox runs as an add-on
     on the same machine; otherwise `http://<NUC_IP>:7745`
   - `homebox_token` — in HomeBox, create a user API key
     (Profile → API keys) and paste it here. Use the form `Bearer xxxxx` if a
     bare token is rejected.
   - `homebox_location_id` — optional. The default storage location for new
     items. Leave blank to pick a location in the app each time.
2. Start the add-on and open the Web UI.
3. On your phone, open the same URL and **Add to Home Screen** for an app icon.

## Finding a HomeBox location ID

Open a location in HomeBox; the ID is the UUID in the browser URL. Or leave
`homebox_location_id` blank — the app loads your locations into a dropdown.

## Using it

1. Tap **Front view**, snap the product. Tap **Serial view**, snap the label.
2. Tap **Analyze with Claude** — fields populate in a couple of seconds.
3. Correct anything (OCR on a worn serial plate is never perfect), pick the
   destination location, then **Save to HomeBox**.

## Linking it from HomeBox

HomeBox has no plugin slot, but you can drop this add-on's URL into a HomeBox
item's URL field or a location's notes for a quick jump. Simplest of all: keep
both as home-screen icons and bounce between them.

## Security notes

- Both API keys live only in this add-on's config on your NUC, never in the
  browser.
- The HomeBox token authenticates as you — treat it like a password and rotate
  it if a device is lost.
- A serial-number photo is mild PII; it is sent to Anthropic only for the
  extraction call. Choose a model/account with a no-training data policy if
  that matters to you.

## Updating

Bump `version` in `config.yaml`, push, and update from the HA App Store. To move
to a newer Claude model later, just change `anthropic_model` in Configuration —
no rebuild needed.
