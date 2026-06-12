# AssetStream

Claude-powered inventory capture. Snap two photos of an item (front + serial
plate), Claude extracts the name, brand, model, and serial number, you confirm
on screen, and it writes the item - with both photos attached - straight into
HomeBox. No spreadsheet, no manual import.

Built and verified against HomeBox **v0.25.0**.

## Why this works over plain HTTP (no certificate needed)

The capture tiles use your phone's native camera via a standard file input, not
the browser's live-camera API. That works on plain http:// with no HTTPS and no
certificate - the same wall that blocks HomeBox's in-browser QR scanner does not
apply here.

The only outbound internet call is from this add-on to api.anthropic.com for the
extraction step. HomeBox is reached over your LAN and never touches the internet.

## Setup

Open the add-on's Configuration tab and set:

- `anthropic_api_key` - from console.anthropic.com. This is API billing,
  separate from a Claude.ai subscription; vision calls cost a few tokens each.
- `anthropic_model` - default `claude-sonnet-4-6` is a good balance.
- `homebox_url` - `http://homebox:7745` if HomeBox runs as an add-on on the same
  machine, otherwise `http://<NUC_IP>:7745`.
- `homebox_username` - your HomeBox login email.
- `homebox_password` - your HomeBox password.
- `homebox_location_id` - optional default location. Leave blank to choose in
  the app each time (it loads your locations into a dropdown).

Note on auth: HomeBox v0.25.0 does not yet have per-user API keys (that feature
is on the development branch, not in this release). AssetStream therefore logs in
with your username/password via HomeBox's login endpoint and manages the session
token automatically, re-logging-in when it expires. Credentials are stored only
in this add-on's config on your NUC, never in the browser.

## Using it

1. Tap Front view, snap the product. Tap Serial view, snap the label.
2. Tap Analyze with Claude - fields populate in a couple of seconds.
3. Correct anything (OCR on a worn serial plate is never perfect), pick the
   destination location, then Save to HomeBox.

On your phone, open the URL and Add to Home Screen for an app icon.

## Security notes

- Both the Anthropic key and your HomeBox credentials live only in this add-on's
  config, never in the browser.
- A serial-number photo is mild PII; it is sent to Anthropic only for the
  extraction call.

## Updating

Bump `version` in `config.yaml`, push, and update from the HA App Store. When
HomeBox ships per-user API keys in a later release, this can be switched back to
key-based auth - ask Claude for the updated backend at that point.
