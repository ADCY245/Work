# PhysiHome Video Calling

This feature uses three separate responsibilities:

- Zoom app credentials: creates instant meetings and signs users into the in-page Zoom meeting UI.
- Socket.IO gateway: sends real-time `incoming-call` and `call-ended` events to logged-in users.

There is no `ZOOM_API` value to copy from Zoom. Use the values shown under **App Credentials** in the Zoom dashboard.

## Environment

FastAPI app:

```env
JWT_SECRET=replace-with-shared-video-jwt-secret
VIDEO_CALL_API_URL=http://localhost:4000
```

For production, `VIDEO_CALL_API_URL` must be a public HTTPS URL that browsers can reach, for example:

```env
VIDEO_CALL_API_URL=https://video.physihome.shop
```

Do not deploy `VIDEO_CALL_API_URL=http://localhost:4000` on `physihome.shop`; in a browser, `localhost` means the visitor's own device.

Node video service:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=physihome
VIDEO_CALL_PORT=4000
VIDEO_CALL_ORIGIN=http://localhost:8000

ZOOM_ACCOUNT_ID=account-id-from-zoom-app-credentials
ZOOM_CLIENT_ID=client-id-from-zoom-app-credentials
ZOOM_CLIENT_SECRET=client-secret-from-zoom-app-credentials

ZOOM_SDK_KEY=meeting-sdk-key-or-client-id
ZOOM_SDK_SECRET=meeting-sdk-secret-or-client-secret
# Or use these clearer aliases instead:
# ZOOM_MEETING_SDK_KEY=meeting-sdk-key-or-client-id
# ZOOM_MEETING_SDK_SECRET=meeting-sdk-secret-or-client-secret
ZOOM_WEB_SDK_VERSION=3.13.2

JWT_SECRET=replace-with-shared-video-jwt-secret
```

Production Node video service:

```env
MONGODB_URI=same-mongodb-uri-used-by-fastapi
# Or use MONGO_URI if that is the existing key in your host.
MONGODB_DB_NAME=physihome
VIDEO_CALL_ORIGIN=https://physihome.shop

ZOOM_ACCOUNT_ID=account-id-from-zoom-app-credentials
ZOOM_CLIENT_ID=client-id-from-zoom-app-credentials
ZOOM_CLIENT_SECRET=client-secret-from-zoom-app-credentials
ZOOM_SDK_KEY=meeting-sdk-key-or-client-id
ZOOM_SDK_SECRET=meeting-sdk-secret-or-client-secret
# Or use ZOOM_MEETING_SDK_KEY and ZOOM_MEETING_SDK_SECRET instead.

JWT_SECRET=same-jwt-secret-used-by-fastapi
```

Most hosts set `PORT` automatically. The Node video service uses `PORT` when it is present, otherwise `VIDEO_CALL_PORT`, otherwise `4000`.

On Render, do not leave `MONGODB_URI`/`MONGO_URI` unset. If both are missing, the service tries local MongoDB during development (`mongodb://localhost:27017`), which does not exist inside Render.

Do not put Zoom's **Secret token** in `ZOOM_SDK_SECRET`. That token is for webhook/event verification. The Meeting SDK signature must use the Meeting SDK secret/client secret that matches `ZOOM_SDK_KEY`.

## MongoDB Schema

Collection: `meetings`

```js
{
  _id: ObjectId,
  meetingId: String,
  uuid: String,
  joinUrl: String,
  startUrl: String,
  password: String,
  conversationId: String,
  doctorId: String,
  patientId: String,
  adminId: String,
  createdBy: String,
  status: "live" | "completed" | "scheduled",
  createdAt: Date,
  updatedAt: Date,
  endedAt: Date | null
}
```

Indexes:

```js
db.meetings.createIndex({ meetingId: 1 }, { unique: true })
db.meetings.createIndex({ doctorId: 1, status: 1, createdAt: -1 })
db.meetings.createIndex({ patientId: 1, status: 1, createdAt: -1 })
db.meetings.createIndex({ adminId: 1, status: 1, createdAt: -1 })
db.meetings.createIndex({ conversationId: 1, createdAt: -1 })
```

## Run

```bash
npm install
npm run start:video
```

Start the existing FastAPI application as usual. The chat UI will request `/api/video/token` from FastAPI, then use that JWT to call the Node service.
