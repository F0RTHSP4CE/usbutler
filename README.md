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

## rotating mifare uids

UID rotation is available for 4-byte Gen1A and Gen2/CUID ("magic") MIFARE
Classic cards. Genuine MIFARE manufacturer blocks are read-only; those cards
continue to open the door with their confirmed UID while daily write attempts
fail safely.

- Existing users start with rotation disabled after migration.
- New users start with rotation enabled and can be changed in the admin UI.
- `UID_ROTATION_ENABLED` is the global kill switch.
- `MIFARE_CLASSIC_KEY_A` configures the Gen2 sector-0 key (default
  `FFFFFFFFFFFF`) and belongs in `.env.secrets`.

## unsupported (!) cards
- google pay (work in progress (actually no))
- 125khz (em4100) — nfc reader limitation

## credits
- backend, frontend and gpio stack — @mike_went
- emv reader stack — @rozetkinrobot, @mike_went
- emv nfc protocol — inspired by @flipperzero source code
