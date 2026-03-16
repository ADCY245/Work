import "dotenv/config";

import express from "express";
import qrcode from "qrcode";
import { MongoClient } from "mongodb";
import { readdirSync, existsSync } from "fs";
import { join } from "path";
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
  async sessionExists({ session }) {
    const name = String(session || "").trim();
    if (!name) return false;
    const doc = await sessionCollection.findOne({ sessionName: name }, { projection: { _id: 1 } });
    return Boolean(doc);
  },
  async save({ session, data }) {
    const name = String(session || "").trim();
    if (!name) return;
    await sessionCollection.updateOne(
      { sessionName: name },
      { $set: { sessionName: name, data, updatedAt: new Date() } },
      { upsert: true }
    );
  },
  async extract({ session }) {
    const name = String(session || "").trim();
    if (!name) return null;
    const doc = await sessionCollection.findOne({ sessionName: name });
    return doc?.data || null;
  },
  async delete({ session }) {
    const name = String(session || "").trim();
    if (!name) return;
    await sessionCollection.deleteOne({ sessionName: name });
  },
};

// Resolve Chrome executable from puppeteer cache (whatsapp-web.js bundles puppeteer-core with different version)
function findChromeExecutable() {
  // Allow override via env
  if (process.env.PUPPETEER_EXECUTABLE_PATH) return process.env.PUPPETEER_EXECUTABLE_PATH;
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;

  const cacheDir = process.env.PUPPETEER_CACHE_DIR || "/opt/render/.cache/puppeteer";
  const chromeRoot = join(cacheDir, "chrome");

  if (!existsSync(chromeRoot)) return null;

  // Find the versioned directory (e.g., linux-131.0.6778.204)
  const dirs = readdirSync(chromeRoot).filter(d => d.startsWith("linux-"));
  if (!dirs.length) return null;

  // Use the first available version
  const versionDir = dirs[0];
  const chromePath = join(chromeRoot, versionDir, "chrome", "chrome");
  if (existsSync(chromePath)) return chromePath;

  // Fallback: check for chrome-headless-shell
  const headlessPath = join(cacheDir, "chrome-headless-shell", versionDir, "chrome-headless-shell");
  if (existsSync(headlessPath)) return headlessPath;

  return null;
}

const CHROME_EXECUTABLE = findChromeExecutable();
if (CHROME_EXECUTABLE) {
  console.log("Using Chrome at:", CHROME_EXECUTABLE);
} else {
  console.warn("Chrome executable not found in puppeteer cache");
}

const waClient = new Client({
  authStrategy: new RemoteAuth({
    clientId: process.env.WA_CLIENT_ID || "physihome",
    store,
    backupSyncIntervalMs: 300000,
  }),
  puppeteer: {
    headless: true,
    executablePath: CHROME_EXECUTABLE,
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
