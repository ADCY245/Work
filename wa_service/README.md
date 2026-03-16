# physiHome WhatsApp Web Service

This is a separate Node.js service using `whatsapp-web.js` to send WhatsApp messages.

## Environment variables

- `PORT` (Render sets this automatically)
- `MONGODB_URI` (required)
- `WA_SERVICE_AUTH_TOKEN` (required) - shared secret. FastAPI will call this service with `Authorization: Bearer <token>`.
- `WA_CLIENT_ID` (optional) - useful if you run multiple clients.
- `WA_MONGO_DB` (optional, default `physihome`)
- `WA_MONGO_COLLECTION` (optional, default `wa_sessions`)

## Endpoints

- `GET /health`
- `GET /qr` (auth) -> returns `qrDataUrl` to scan
- `POST /send` (auth) -> `{ "to": "+91...", "body": "..." }`

## First time login

1. Deploy on Render.
2. Open `GET /qr` to retrieve the QR image data URL.
3. Scan with WhatsApp mobile app.
4. After ready, `/health` will show `ready: true`.

## Notes

- This is **unofficial** and may break.
- Use at your own risk.
