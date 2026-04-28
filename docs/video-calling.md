# PhysiHome Video Calling

This feature uses three separate responsibilities:

- Zoom Server-to-Server OAuth app: creates instant meetings through the Zoom REST API.
- Zoom Meeting SDK app: signs users into the in-page Zoom meeting UI.
- Socket.IO gateway: sends real-time `incoming-call` and `call-ended` events to logged-in users.

Do not reuse the Server-to-Server OAuth client credentials as Meeting SDK credentials.

## Environment

FastAPI app:

```env
JWT_SECRET=replace-with-shared-video-jwt-secret
VIDEO_CALL_API_URL=http://localhost:4000
```

Node video service:

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=physihome
VIDEO_CALL_PORT=4000
VIDEO_CALL_ORIGIN=http://localhost:8000

ZOOM_ACCOUNT_ID=server-to-server-oauth-account-id
ZOOM_CLIENT_ID=server-to-server-oauth-client-id
ZOOM_CLIENT_SECRET=server-to-server-oauth-client-secret

ZOOM_SDK_KEY=meeting-sdk-key-or-client-id
ZOOM_SDK_SECRET=meeting-sdk-secret
ZOOM_WEB_SDK_VERSION=3.13.2

JWT_SECRET=replace-with-shared-video-jwt-secret
```

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
