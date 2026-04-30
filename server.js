import "dotenv/config";
import axios from "axios";
import cors from "cors";
import express from "express";
import http from "http";
import jwt from "jsonwebtoken";
import { MongoClient, ObjectId } from "mongodb";
import { Server } from "socket.io";

const {
  MONGO_URI,
  MONGODB_URI = MONGO_URI || "mongodb://localhost:27017",
  MONGODB_DB_NAME = "physihome",
  VIDEO_CALL_ORIGIN = "*",
  PORT,
  VIDEO_CALL_PORT = PORT || "4000",
  ZOOM_ACCOUNT_ID,
  ZOOM_CLIENT_ID,
  ZOOM_CLIENT_SECRET,
  ZOOM_MEETING_SDK_KEY,
  ZOOM_MEETING_SDK_SECRET,
  ZOOM_SDK_KEY = ZOOM_MEETING_SDK_KEY,
  ZOOM_SDK_SECRET = ZOOM_MEETING_SDK_SECRET,
  ZOOM_WEB_SDK_VERSION = "3.13.2",
  JWT_SECRET,
} = process.env;

const requiredEnv = {
  ZOOM_ACCOUNT_ID,
  ZOOM_CLIENT_ID,
  ZOOM_CLIENT_SECRET,
  ZOOM_SDK_KEY,
  ZOOM_SDK_SECRET,
  JWT_SECRET,
};

if (process.env.RENDER && !process.env.MONGODB_URI && !process.env.MONGO_URI) {
  throw new Error("MONGODB_URI or MONGO_URI is required on Render. Use the same MongoDB connection string as the FastAPI app.");
}

for (const [key, value] of Object.entries(requiredEnv)) {
  if (!value) {
    if (key === "ZOOM_SDK_KEY") {
      throw new Error("ZOOM_SDK_KEY is required. Use the Meeting SDK key/client id, or set ZOOM_MEETING_SDK_KEY.");
    }
    if (key === "ZOOM_SDK_SECRET") {
      throw new Error("ZOOM_SDK_SECRET is required. Use the Meeting SDK secret/client secret, not Zoom's webhook Secret token. You can also set ZOOM_MEETING_SDK_SECRET.");
    }
    throw new Error(`${key} is required for the video calling service`);
  }
}

const app = express();
const server = http.createServer(app);
const corsCredentials = VIDEO_CALL_ORIGIN !== "*";
const io = new Server(server, {
  cors: {
    origin: VIDEO_CALL_ORIGIN,
    credentials: corsCredentials,
  },
});

app.use(cors({ origin: VIDEO_CALL_ORIGIN, credentials: corsCredentials }));
app.use(express.json({ limit: "1mb" }));

const mongo = new MongoClient(MONGODB_URI);
await mongo.connect();
const db = mongo.db(MONGODB_DB_NAME);

let zoomToken = null;
let zoomTokenExpiresAt = 0;

const userRoom = (userId) => `user:${userId}`;

const verifyVideoToken = (token) => jwt.verify(token, JWT_SECRET, { algorithms: ["HS256"] });

const authMiddleware = (req, res, next) => {
  const header = req.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  try {
    req.user = verifyVideoToken(token);
    return next();
  } catch {
    return res.status(401).json({ error: "Invalid or expired token" });
  }
};

const asObjectId = (value) => {
  try {
    return new ObjectId(String(value));
  } catch {
    return null;
  }
};

const displayName = (user) => {
  const name = `${user?.first_name || ""} ${user?.last_name || ""}`.trim();
  if ((user?.role || "").toLowerCase() === "doctor") return `Dr. ${name}`.trim();
  return name || user?.email || "PhysiHome User";
};

const isAdmin = (user) => {
  const role = String(user?.role || "").toLowerCase();
  return Boolean(user?.is_admin) || role === "admin";
};

const getUser = async (userId) => {
  const oid = asObjectId(userId);
  if (!oid) return null;
  return db.collection("users").findOne({ _id: oid });
};

const getConversation = async (conversationId, userId) => {
  const oid = asObjectId(conversationId);
  if (!oid) return null;
  return db.collection("conversations").findOne({ _id: oid, participants: String(userId) });
};

const getDoctorPatient = async (conversation) => {
  const participantIds = (conversation?.participants || []).map(String);
  const objectIds = participantIds.map(asObjectId).filter(Boolean);
  const users = await db.collection("users").find({ _id: { $in: objectIds } }).toArray();
  const doctor = users.find((u) => String(u.role || "").toLowerCase() === "doctor");
  const patient = users.find((u) => String(u._id) !== String(doctor?._id));
  return { doctor, patient };
};

const assertMeetingAccess = async (meeting, userId) => {
  const uid = String(userId);
  if ([meeting.doctorId, meeting.patientId, meeting.adminId].map(String).includes(uid)) {
    return true;
  }
  const user = await getUser(uid);
  if (isAdmin(user)) {
    const doctor = await getUser(meeting.doctorId);
    return String(doctor?.assigned_admin_id || "") === uid;
  }
  return false;
};

const getZoomAccessToken = async () => {
  const now = Date.now();
  if (zoomToken && zoomTokenExpiresAt - 60_000 > now) {
    return zoomToken;
  }

  const basic = Buffer.from(`${ZOOM_CLIENT_ID}:${ZOOM_CLIENT_SECRET}`).toString("base64");
  const url = `https://zoom.us/oauth/token?grant_type=account_credentials&account_id=${encodeURIComponent(ZOOM_ACCOUNT_ID)}`;
  const response = await axios.post(url, null, {
    headers: {
      Authorization: `Basic ${basic}`,
    },
  });

  zoomToken = response.data.access_token;
  zoomTokenExpiresAt = now + Number(response.data.expires_in || 3600) * 1000;
  return zoomToken;
};

const createZoomMeeting = async () => {
  const accessToken = await getZoomAccessToken();
  const response = await axios.post(
    "https://api.zoom.us/v2/users/me/meetings",
    {
      topic: "PhysiHome Video Call",
      type: 1,
      settings: {
        join_before_host: true,
        waiting_room: false,
      },
    },
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
    },
  );
  return response.data;
};

const normalizeZoomMeetingNumber = (value) => String(value || "").replace(/\D/g, "");

const normalizeZoomRole = (value) => {
  const role = Number(value);
  return role === 1 ? 1 : 0;
};

const generateSdkSignature = ({ meetingNumber, role }) => {
  const iat = Math.floor(Date.now() / 1000) - 30;
  const exp = iat + 60 * 60 * 2;
  const normalizedMeetingNumber = normalizeZoomMeetingNumber(meetingNumber);
  const normalizedRole = normalizeZoomRole(role);
  return jwt.sign(
    {
      appKey: ZOOM_SDK_KEY,
      sdkKey: ZOOM_SDK_KEY,
      mn: normalizedMeetingNumber,
      role: normalizedRole,
      iat,
      exp,
      tokenExp: exp,
    },
    ZOOM_SDK_SECRET,
    { algorithm: "HS256", header: { alg: "HS256", typ: "JWT" } },
  );
};

const meetingPayload = (meeting) => ({
  meetingId: String(meeting.meetingId),
  meetingNumber: String(meeting.meetingId),
  password: meeting.password || "",
  doctorId: String(meeting.doctorId),
  patientId: String(meeting.patientId),
  adminId: String(meeting.adminId || ""),
  conversationId: String(meeting.conversationId || ""),
  status: meeting.status,
  createdAt: meeting.createdAt,
  endedAt: meeting.endedAt || null,
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "physihome-video-calling" });
});

app.post("/api/meetings/create", authMiddleware, async (req, res) => {
  try {
    const conversationId = String(req.body?.conversationId || "").trim();
    const conversation = await getConversation(conversationId, req.user.sub);
    if (!conversation) {
      return res.status(403).json({ error: "Forbidden" });
    }

    const { doctor, patient } = await getDoctorPatient(conversation);
    if (!doctor || !patient) {
      return res.status(400).json({ error: "Video calls are available for doctor-patient chats only" });
    }

    const callerId = String(req.user.sub);
    const allowedCaller = [String(doctor._id), String(patient._id)].includes(callerId);
    if (!allowedCaller) {
      return res.status(403).json({ error: "Only the doctor or patient can start this call" });
    }

    const zoomMeeting = await createZoomMeeting();
    const now = new Date();
    const meeting = {
      meetingId: String(zoomMeeting.id),
      uuid: zoomMeeting.uuid,
      joinUrl: zoomMeeting.join_url,
      startUrl: zoomMeeting.start_url,
      password: zoomMeeting.password || "",
      conversationId,
      doctorId: String(doctor._id),
      patientId: String(patient._id),
      adminId: String(doctor.assigned_admin_id || ""),
      createdBy: callerId,
      status: "live",
      createdAt: now,
      updatedAt: now,
    };

    const result = await db.collection("meetings").insertOne(meeting);
    meeting._id = result.insertedId;

    const payload = {
      ...meetingPayload(meeting),
      callerId,
      callerName: displayName(await getUser(callerId)),
    };

    [meeting.doctorId, meeting.patientId, meeting.adminId]
      .filter(Boolean)
      .forEach((userId) => io.to(userRoom(userId)).emit("incoming-call", payload));

    return res.status(201).json({ meeting: payload });
  } catch (error) {
    const message = error?.response?.data?.message || error?.message || "Could not create meeting";
    return res.status(500).json({ error: message });
  }
});

app.post("/api/zoom/signature", authMiddleware, async (req, res) => {
  const meetingNumber = normalizeZoomMeetingNumber(req.body?.meetingNumber);
  if (!meetingNumber) {
    return res.status(400).json({ error: "meetingNumber is required" });
  }
  if (!/^\d{9,12}$/.test(meetingNumber)) {
    return res.status(400).json({ error: "meetingNumber must be a valid Zoom meeting number" });
  }

  const meeting = await db.collection("meetings").findOne({ meetingId: meetingNumber });
  if (!meeting) {
    return res.status(404).json({ error: "Meeting not found" });
  }
  if (!(await assertMeetingAccess(meeting, req.user.sub))) {
    return res.status(403).json({ error: "Forbidden" });
  }

  const role = 0;
  const signature = generateSdkSignature({ meetingNumber, role });
  res.json({
    signature,
    sdkKey: ZOOM_SDK_KEY,
    sdkVersion: ZOOM_WEB_SDK_VERSION,
    meetingNumber,
    passWord: meeting.password || "",
    role,
    userName: req.user.name || "PhysiHome User",
    userEmail: req.user.email || "",
    leaveUrl: "/messages",
  });
});

app.get("/api/meetings", authMiddleware, async (req, res) => {
  const user = await getUser(req.user.sub);
  if (!user) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const query = {};
  const role = String(user.role || "").toLowerCase();
  if (isAdmin(user)) {
    const doctorQuery = { role: "doctor", assigned_admin_id: String(user._id) };
    if (req.query.doctorId) doctorQuery._id = asObjectId(req.query.doctorId);
    const doctors = await db.collection("users").find(doctorQuery, { projection: { _id: 1 } }).toArray();
    query.doctorId = { $in: doctors.map((doctor) => String(doctor._id)) };
  } else if (role === "doctor") {
    query.doctorId = String(user._id);
  } else {
    query.patientId = String(user._id);
  }

  if (req.query.doctorId && !isAdmin(user)) {
    query.doctorId = String(req.query.doctorId);
  }

  if (req.query.date) {
    const start = new Date(`${req.query.date}T00:00:00.000Z`);
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + 1);
    query.createdAt = { $gte: start, $lt: end };
  }

  const meetings = await db.collection("meetings").find(query).sort({ createdAt: -1 }).limit(200).toArray();
  res.json({
    live: meetings.filter((m) => m.status === "live").map(meetingPayload),
    scheduled: meetings.filter((m) => m.status === "scheduled").map(meetingPayload),
    past: meetings.filter((m) => m.status === "completed").map(meetingPayload),
  });
});

app.post("/api/meetings/:meetingId/end", authMiddleware, async (req, res) => {
  const meeting = await db.collection("meetings").findOne({ meetingId: String(req.params.meetingId) });
  if (!meeting) {
    return res.status(404).json({ error: "Meeting not found" });
  }
  if (!(await assertMeetingAccess(meeting, req.user.sub))) {
    return res.status(403).json({ error: "Forbidden" });
  }

  const endedAt = new Date();
  await db.collection("meetings").updateOne(
    { _id: meeting._id },
    { $set: { status: "completed", endedAt, updatedAt: endedAt } },
  );

  const payload = { meetingId: String(meeting.meetingId), endedAt };
  [meeting.doctorId, meeting.patientId, meeting.adminId]
    .filter(Boolean)
    .forEach((userId) => io.to(userRoom(userId)).emit("call-ended", payload));

  res.json({ ok: true });
});

io.use((socket, next) => {
  try {
    const token = socket.handshake.auth?.token;
    socket.user = verifyVideoToken(token);
    next();
  } catch {
    next(new Error("Unauthorized"));
  }
});

io.on("connection", (socket) => {
  socket.join(userRoom(socket.user.sub));
  socket.on("subscribe", ({ userId } = {}) => {
    if (String(userId || "") === String(socket.user.sub)) {
      socket.join(userRoom(socket.user.sub));
    }
  });
});

await db.collection("meetings").createIndexes([
  { key: { meetingId: 1 }, unique: true },
  { key: { doctorId: 1, status: 1, createdAt: -1 } },
  { key: { patientId: 1, status: 1, createdAt: -1 } },
  { key: { adminId: 1, status: 1, createdAt: -1 } },
  { key: { conversationId: 1, createdAt: -1 } },
]);

server.listen(Number(VIDEO_CALL_PORT), () => {
  console.log(`PhysiHome video calling service listening on :${VIDEO_CALL_PORT}`);
});
