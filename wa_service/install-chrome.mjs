// Install Chrome to project-relative cache directory
import { execSync } from 'child_process';
import { mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const cacheDir = join(__dirname, '.cache', 'puppeteer');

// Ensure cache directory exists
if (!existsSync(cacheDir)) {
  mkdirSync(cacheDir, { recursive: true });
}

console.log('Installing Chrome to:', cacheDir);

// Run puppeteer install with explicit cache directory
process.env.PUPPETEER_CACHE_DIR = cacheDir;
execSync('node node_modules/puppeteer/install.mjs', { 
  stdio: 'inherit',
  env: { ...process.env, PUPPETEER_CACHE_DIR: cacheDir }
});
