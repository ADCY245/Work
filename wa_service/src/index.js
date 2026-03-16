import "dotenv/config";

import express from "express";
import qrcode from "qrcode";
import { MongoClient } from "mongodb";
import whatsappPkg from "whatsapp-web.js";

const { Client, RemoteAuth } = whatsappPkg;

const PORT = Number(process.env.PORT || 3001);
const MONGODB_URI = process.env.MONGODB_URI;
const SESSION_DB_NAME = process.env.WA_MONGO_DB || "physihome";
const SESSION_COLLECTION = process.env.WA_MONGO_COLLECTION || "wa_sessions";

const AUTH_TOKEN = (process.env.WA_SERVICE_AUTH_TOKEN || "").trim();
if (!AUTH_TOKEN) {
  console.warn("WA_SERVICE_AUTH_TOKEN is not set. Requests will be rejected.");
}

function requireAuth(req, res, next) {
  const header = String(req.headers["authorization"] || "");
  const token = header.startsWith("Bearer ") ? header.slice("Bearer ".length) : "";
  if (!AUTH_TOKEN || token !== AUTH_TOKEN) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  return next();
}

if (!MONGODB_URI) {
  throw new Error("MONGODB_URI is required for whatsapp-web.js RemoteAuth");
}

const mongo = new MongoClient(MONGODB_URI);
await mongo.connect();

const sessionCollection = mongo.db(SESSION_DB_NAME).collection(SESSION_COLLECTION);

const store = {
  async save({ session, clientId }) {
    await sessionCollection.updateOne(
      { clientId },
      { $set: { clientId, session, updatedAt: new Date() } },
      { upsert: true }
    );
  },
  async extract({ clientId }) {
    const doc = await sessionCollection.findOne({ clientId });
    return doc?.session || null;
  },
  async delete({ clientId }) {
    await sessionCollection.deleteOne({ clientId });
  },
};

const waClient = new Client({
  authStrategy: new RemoteAuth({
    clientId: process.env.WA_CLIENT_ID || "physihome",
    store,
    backupSyncIntervalMs: 300000,
  }),
  puppeteer: {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-accelerated-2d-canvas",
      "--no-first-run",
      "--no-zygote",
      "--single-process",
      "--disable-gpu",
    ],
  },
});

let latestQrDataUrl = null;
let isReady = false;
let lastError = null;

waClient.on("qr", async (qr) => {
  try {
    latestQrDataUrl = await qrcode.toDataURL(qr);
    isReady = false;
  } catch (e) {
    lastError = String(e);
  }
});

waClient.on("ready", () => {
  isReady = true;
  latestQrDataUrl = null;
  lastError = null;
});

waClient.on("auth_failure", (msg) => {
  isReady = false;
  lastError = String(msg);
});

waClient.on("disconnected", (reason) => {
  isReady = false;
  lastError = String(reason);
});

await waClient.initialize();

const app = express();
app.use(express.json({ limit: "1mb" }));

app.get("/health", (req, res) => {
  res.json({ ok: true, ready: isReady, hasQr: Boolean(latestQrDataUrl), lastError });
});

app.get("/qr", requireAuth, (req, res) => {
  if (!latestQrDataUrl) {
    return res.status(404).json({ ok: false, error: "no_qr" });
  }
  return res.json({ ok: true, qrDataUrl: latestQrDataUrl });
});

function normalizeE164(raw) {
  const s = String(raw || "").trim();
  if (!s) return null;
  if (s.startsWith("+")) {
    const digits = s.replace(/\D/g, "");
    return digits ? `+${digits}` : null;
  }
  const digits = s.replace(/\D/g, "");
  if (digits.length === 10) return `+91${digits}`;
  if (digits.length >= 11 && digits.startsWith("91")) return `+${digits}`;
  return null;
}

app.post("/send", requireAuth, async (req, res) => {
  try {
    const toPhone = normalizeE164(req.body?.to);
    const body = String(req.body?.body || "").trim();
    if (!toPhone) return res.status(400).json({ ok: false, error: "invalid_phone" });
    if (!body) return res.status(400).json({ ok: false, error: "empty_body" });
    if (!isReady) return res.status(503).json({ ok: false, error: "not_ready" });

    const chatId = `${toPhone.slice(1)}@c.us`;
    await waClient.sendMessage(chatId, body);

    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e) });
  }
});

app.listen(PORT, () => {
  console.log(`WhatsApp web service listening on :${PORT}`);
});
