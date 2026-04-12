const { Client } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');

const to = process.env.WA_TO || '919769115870@c.us';
const body = process.env.WA_BODY || 'Hello from Node.js!';

const client = new Client();

client.on('qr', (qr) => {
  console.log('Scan the QR code below');
  qrcode.generate(qr, { small: true });
});

client.on('ready', async () => {
  console.log('WhatsApp is ready!');
  try {
    await client.sendMessage(to, body);
    console.log('Message sent to:', to);
  } catch (e) {
    console.error('Failed to send message:', e);
  }
});

client.initialize();
