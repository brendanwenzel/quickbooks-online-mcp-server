import crypto from 'crypto';
import fs from 'fs';

function encryptionKey(keyFile: string | undefined): Buffer {
  if (!keyFile) {
    throw new Error('QUICKBOOKS_TOKEN_ENCRYPTION_KEY_FILE is not configured');
  }

  const encoded = fs.readFileSync(keyFile, 'utf8').trim();
  const key = /^[0-9a-fA-F]{64}$/.test(encoded)
    ? Buffer.from(encoded, 'hex')
    : Buffer.from(encoded, 'base64');
  if (key.length !== 32) {
    throw new Error('QuickBooks token encryption key must contain exactly 32 bytes');
  }
  return key;
}

export function encryptStoredValue(value: string, keyFile: string | undefined): string {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', encryptionKey(keyFile), iv);
  const ciphertext = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  return ['v1', iv.toString('base64'), cipher.getAuthTag().toString('base64'), ciphertext.toString('base64')].join(':');
}

export function decryptStoredValue(value: string, keyFile: string | undefined): string {
  const [version, iv, authTag, ciphertext, ...extra] = value.split(':');
  if (version !== 'v1' || !iv || !authTag || !ciphertext || extra.length) {
    throw new Error('Unsupported encrypted QuickBooks credential format');
  }
  const decipher = crypto.createDecipheriv('aes-256-gcm', encryptionKey(keyFile), Buffer.from(iv, 'base64'));
  decipher.setAuthTag(Buffer.from(authTag, 'base64'));
  return Buffer.concat([
    decipher.update(Buffer.from(ciphertext, 'base64')),
    decipher.final(),
  ]).toString('utf8');
}
