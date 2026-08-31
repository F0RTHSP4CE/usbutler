# usbutler — usb butler / F0 door ACS (access control system)
hardware:
- raspberry pi
- nfc reader ACR122U
- relay hat
- push button

optional:
- dc-dc converter for lock solenoid

## run
1. install docker and docker compose
2. connect usb nfc reader
3. 
    ```
    cp .env.example .env
    cp .env.secrets.example .env.secrets
    nano .env
    nano .env.secrets

    docker compose up --build -d
    ```
4. api docs: http://ip:8000/docs
5. web ui: http://ip:8000/login

## supported cards
- mifare
- emv (bank, apple pay)
- ntag

## rotating mifare data credentials

Opted-in MIFARE Classic fobs store a UUIDv4 in a dedicated 16-byte data block.
The immutable card UID bootstraps old fobs, but is no longer accepted after the
first data UUID has been verified. Current and recent UUIDs remain valid so an
uncertain write cannot lock out a user.

- Rotation is disabled by default for every user and can be enabled in the
  admin UI.
- `MIFARE_DATA_ROTATION_ENABLED` is the global write kill switch. Disabling it
  does not restore UID fallback for already enrolled cards.
- `MIFARE_DATA_BLOCK` selects the dedicated data block (default `4`). Never use
  block 0 or a sector trailer, and reserve the selected block for USButler.
- `MIFARE_UUID_HISTORY_LIMIT` controls confirmed UUID retention (default `3`).
- Successful, read-back-verified rotation is limited to once per rolling 24
  hours. An unconfirmed pending target is retried on later presentations.
- `MIFARE_WRITE_MAX_ATTEMPTS` and `MIFARE_WRITE_RETRY_DELAY_SECONDS` bound
  same-presentation retries (defaults `3` and `0.15`).
- `MIFARE_CLASSIC_KEY_A` configures data-sector Key A (factory default
  `FFFFFFFFFFFF`) and belongs in `.env.secrets`.

This invalidates stale UID-only copies; it is not cryptographic proof of card
authenticity. A readable MIFARE Classic data block can itself be copied.

## unsupported (!) cards
- google pay (work in progress (actually no))
- 125khz (em4100) — nfc reader limitation

## credits
- backend, frontend and gpio stack — @mike_went
- emv reader stack — @rozetkinrobot, @mike_went
- emv nfc protocol — inspired by @flipperzero source code
