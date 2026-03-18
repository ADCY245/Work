import "dotenv/config";

import express from "express";
import qrcode from "qrcode";
import { MongoClient } from "mongodb";
import { readdirSync, existsSync } from "fs";
import { join } from "path";
import { computeExecutablePath, Browser, BrowserPlatform, install } from '@puppeteer/browsers';
import whatsappPkg from "whatsapp-web.js";

const { Client, RemoteAuth, LocalAuth } = whatsappPkg;

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

let authStrategy;

if (MONGODB_URI) {
  console.log("Using RemoteAuth with MongoDB");
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

  authStrategy = new RemoteAuth({
    clientId: process.env.WA_CLIENT_ID || "physihome",
    store,
    backupSyncIntervalMs: 300000,
  });
} else {
  console.log("Using LocalAuth (local session storage)");
  authStrategy = new LocalAuth({
    clientId: process.env.WA_CLIENT_ID || "physihome",
  });
}

// Download and find Chrome executable at runtime using @puppeteer/browsers
async function ensureChrome() {
  // Allow override via env
  if (process.env.PUPPETEER_EXECUTABLE_PATH) {
    console.log("Using PUPPETEER_EXECUTABLE_PATH:", process.env.PUPPETEER_EXECUTABLE_PATH);
    return process.env.PUPPETEER_EXECUTABLE_PATH;
  }
  if (process.env.CHROME_PATH) {
    console.log("Using CHROME_PATH:", process.env.CHROME_PATH);
    return process.env.CHROME_PATH;
  }

  const cacheDir = join(process.cwd(), '.cache', 'puppeteer');
  const buildId = '131.0.6778.204'; // Match puppeteer version
  
  // Check if already downloaded
  let executablePath = computeExecutablePath({
    browser: Browser.CHROME,
    platform: BrowserPlatform.LINUX,
    buildId,
    cacheDir,
  });
  
  if (existsSync(executablePath)) {
    console.log("Found Chrome at:", executablePath);
    return executablePath;
  }

  // Download Chrome at runtime
  console.log("Downloading Chrome", buildId, "to", cacheDir);
  
  await install({
    browser: Browser.CHROME,
    platform: BrowserPlatform.LINUX,
    buildId,
    cacheDir,
  });
  
  executablePath = computeExecutablePath({
    browser: Browser.CHROME,
    platform: BrowserPlatform.LINUX,
    buildId,
    cacheDir,
  });
  
  if (existsSync(executablePath)) {
    console.log("Chrome downloaded to:", executablePath);
    return executablePath;
  }

  console.warn("Failed to download Chrome");
  return null;
}

// Initialize Chrome and WhatsApp client (lazy - only when needed)
let CHROME_EXECUTABLE = null;
let waClient = null;
let latestQrDataUrl = null;
let isReady = false;
let lastError = null;
let isInitializing = false;
let idleTimer = null;

function _clearIdleTimer() {
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
  }
}

async function _resetClient(reason) {
  _clearIdleTimer();
  latestQrDataUrl = null;
  isReady = false;
  if (reason) lastError = String(reason);
  if (waClient) {
    try {
      await waClient.destroy();
    } catch (e) {
      // ignore
    }
  }
  waClient = null;
}

function _touchIdleShutdown() {
  const ms = Number(process.env.WA_IDLE_SHUTDOWN_MS || 300000);
  if (!Number.isFinite(ms) || ms <= 0) return;
  _clearIdleTimer();
  idleTimer = setTimeout(() => {
    _resetClient("idle_shutdown").catch(() => {});
  }, ms);
}

// Lazy initialization - only start WhatsApp when QR is requested
async function ensureWhatsApp() {
  if (waClient) return waClient;
  if (isInitializing) throw new Error("Initializing, try again later");
  
  isInitializing = true;
  try {
    CHROME_EXECUTABLE = await ensureChrome();
    if (!CHROME_EXECUTABLE) {
      throw new Error("Failed to get Chrome executable");
    }

    waClient = new Client({
      authStrategy,
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
          "--disable-background-timer-throttling",
          "--disable-backgrounding-occluded-windows",
          "--disable-renderer-backgrounding",
          "--memory-pressure-off",
          "--max-old-space-size=256",
        ],
      },
    });

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
      _touchIdleShutdown();
    });

    waClient.on("auth_failure", (msg) => {
      _resetClient(msg).catch(() => {});
    });

    waClient.on("disconnected", (reason) => {
      _resetClient(reason).catch(() => {});
    });

    await waClient.initialize();
    _touchIdleShutdown();
    return waClient;
  } finally {
    isInitializing = false;
  }
}

// Remove immediate init
// await initWhatsApp();

const app = express();
app.use(express.json({ limit: "1mb" }));

app.get("/health", (req, res) => {
  res.json({ ok: true, ready: isReady, hasQr: Boolean(latestQrDataUrl), lastError });
});

app.get("/qr", requireAuth, async (req, res) => {
  try {
    console.log("QR endpoint: client=", !!waClient, "qr=", !!latestQrDataUrl, "ready=", isReady, "init=", isInitializing);
    // Trigger initialization if not started
    if (!waClient) {
      // Start init in background, don't wait
      ensureWhatsApp().catch(e => {
        console.error("Failed to initialize WhatsApp:", e);
        lastError = String(e);
      });
      // Return waiting response
      return res.status(202).json({ ok: false, error: "initializing", message: "WhatsApp client starting, try again in 30-60 seconds" });
    }

    _touchIdleShutdown();
    
    if (!latestQrDataUrl) {
      // Client exists but QR not generated yet
      return res.status(202).json({ ok: false, error: "waiting_for_qr", message: "QR being generated, try again in 10-20 seconds" });
    }
    return res.json({ ok: true, qrDataUrl: latestQrDataUrl });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e) });
  }
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
    // Ensure WhatsApp is initialized
    if (!waClient) {
      await ensureWhatsApp();
    }

    _touchIdleShutdown();
    
    const toPhone = normalizeE164(req.body?.to);
    const body = String(req.body?.body || "").trim();
    if (!toPhone) return res.status(400).json({ ok: false, error: "invalid_phone" });
    if (!body) return res.status(400).json({ ok: false, error: "empty_body" });
    if (!isReady) return res.status(503).json({ ok: false, error: "not_ready" });

    const chatId = `${toPhone.slice(1)}@c.us`;
    await waClient.sendMessage(chatId, body);

    _touchIdleShutdown();

    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e) });
  }
});

app.listen(PORT, () => {
  console.log(`WhatsApp web service listening on :${PORT}`);
});
