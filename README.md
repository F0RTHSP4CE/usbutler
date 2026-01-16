# usbutler

door access control system.
- uses **usb acs** nfc card reader
- has http rest api
- access logs stored in sqlite 
- browser-based management ui for user enrollment

## supported cards

### nfc
- mifare
- iso14443

### emv
- Visa, MasterCard
- Apple Pay

## deploy

```
cp .env.example .env
nano .env

docker compose up --build -d
```

This brings up a single container named `usbutler` that runs both the door controller and the web UI. It mounts the `usbutler-data` volume for the shared user database and exposes port 8000 for the browser dashboard.

### Physical door relay via libgpiod

The controller can drive a single-pin relay on a Raspberry Pi using libgpiod, the modern Linux GPIO interface. The container directly accesses the GPIO device, so ensure these steps are in place on the Pi:

1. Ensure libgpiod is installed (usually already present on recent Raspberry Pi OS):
	```bash
	sudo apt update
	sudo apt install libgpiod2 gpiod
	```
2. Verify your user has GPIO access permissions. The container runs with privileged access to `/dev/gpiochip0`.
3. Update `.env` (or the `docker-compose.yml`) with the GPIO wiring details:
	- `USBUTLER_DOOR_GPIO` — BCM pin number driving your relay (default `17`).
	- `USBUTLER_DOOR_ACTIVE_HIGH` — set to `1` if the relay energises on a high output (default), or `0` for active-low boards.
	- `USBUTLER_GPIO_CHIP` — GPIO chip device path (default `/dev/gpiochip0`).
	- `USBUTLER_DOOR_REOPEN_DELAY` — minimum seconds to wait before unlocking again with the same card (default `5`). Attempts during this cooldown are ignored.

With these values configured the service will toggle the relay when a user is authenticated and re-lock automatically after the configured delay.

### Unlock notifications (LED wall + Telegram)

The door daemon can emit a welcome message to an LED wall and log unlock events to a Telegram thread every time the door opens. Configure the targets via environment variables (for example inside `.env`):

| Variable | Required | Description |
| --- | --- | --- |
| `USBUTLER_LED_ENDPOINT` | ✅ | Base URL for the LED text endpoint, e.g. `http://ledka.lo.f0rth.space/text`. If unset, LED notifications are skipped. |
| `USBUTLER_LED_FONT` | | LED font name (default: `BMplain`). |
| `USBUTLER_LED_TIMEOUT` | | Display timeout in ms (default: `500`). |
| `USBUTLER_LED_POSITION_X` / `USBUTLER_LED_POSITION_Y` | | Coordinates for the rendered text (defaults: `10`, `5`). |
| `USBUTLER_LED_MESSAGE_TEMPLATE` | | Python format template for the welcome text (default: `Welcome {name}!`). |
| `USBUTLER_LED_REQUEST_TIMEOUT` | | HTTP timeout in seconds (default: `5`). |
| `USBUTLER_TG_BASE_URL` | | Full Telegram sendMessage URL (e.g. `https://api.telegram.org/bot<token>/sendMessage`). Omit if you prefer to supply `USBUTLER_TG_BOT_TOKEN`. |
| `USBUTLER_TG_BOT_TOKEN` | ◻️ | Bot token used when `USBUTLER_TG_BASE_URL` is not provided. |
| `USBUTLER_TG_CHAT_ID` | ✅ | Destination chat or channel ID (negative for channels). |
| `USBUTLER_TG_THREAD_ID` | | Optional thread/topic ID for forum-style chats. |
| `USBUTLER_TG_MESSAGE_TEMPLATE` | | Python format template for the log message (default: `Door unlocked at {time} by {name} [{identifier_type}: {identifier}]`). |
| `USBUTLER_TG_REQUEST_TIMEOUT` | | HTTP timeout in seconds (default: `5`). |

The Telegram log automatically censors the card identifier (PAN/UID) to its last four characters. To reproduce the shell script snippet you can set:

```
USBUTLER_LED_ENDPOINT=http://ledka.lo.f0rth.space/text
USBUTLER_LED_FONT=BMplain
USBUTLER_LED_TIMEOUT=500
USBUTLER_LED_POSITION_X=10
USBUTLER_LED_POSITION_Y=5
USBUTLER_TG_BASE_URL=https://api.telegram.org/bot<token>/sendMessage
USBUTLER_TG_CHAT_ID=-1002070662990
USBUTLER_TG_THREAD_ID=3
```

After configuring these variables, rebuild or restart the container so the door service picks up the changes.

### NFC reader access from the web container

By default the web UI does **not** open the USB reader. The door daemon owns the reader exclusively so it can continuously poll for cards. If you want to allow the web container to perform live scans (for example on a standalone workstation), set:

```
USBUTLER_WEB_ENABLE_READER=1
```

With this flag enabled the UI exposes **Unlock reader** / **Return reader** buttons in the sidebar. Clicking **Unlock reader** pauses the door service by switching ownership via the shared `ReaderControl` state file, allowing the web UI to talk to the reader safely. When you're done scanning, click **Return reader** (or wait for the door service to reclaim it on restart) so the background daemon resumes control.

## web management ui

Run the unified controller (door daemon + web UI) from a single process:

```powershell
cd usbutler
python -m app.cli
```

This starts the background door loop and serves the web UI on <http://localhost:8000>. Use the **Unlock reader** button in the sidebar to switch the hardware from the door loop to the web view when you need to enrol cards, then click **Return reader** so the door daemon resumes ownership.

The UI uses Bootstrap 5 and offers card scanning, user enrollment, pause/resume controls, and removal actions. Ensure the NFC reader is connected to the host before starting the server.

## REST API

Automate management through HTTP requests. The Flask service exposes endpoints for creating, deleting, pausing, resuming, and looking up users by card identifier. See [documentation/API.md](documentation/API.md) for detailed request/response examples.
