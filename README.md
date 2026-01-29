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

## unsupported (!) cards
- google pay (work in progress (actually no))
- 125khz (em4100) — nfc reader limitation

## credits
- backend, frontend and gpio stack — @mike_went
- emv reader stack — @rozetkinrobot, @mike_went
- emv nfc protocol — inspired by @flipperzero source code

