import fs from 'fs';
import os from 'os';
import path from 'path';
import { decryptStoredValue, encryptStoredValue } from '../../../src/helpers/token-encryption';

describe('token encryption', () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qbo-token-encryption-'));
  const hexKeyFile = path.join(tempDir, 'hex.key');
  const base64KeyFile = path.join(tempDir, 'base64.key');
  const invalidKeyFile = path.join(tempDir, 'invalid.key');
  const key = Buffer.alloc(32, 7);

  beforeAll(() => {
    fs.writeFileSync(hexKeyFile, `${key.toString('hex')}\n`);
    fs.writeFileSync(base64KeyFile, key.toString('base64'));
    fs.writeFileSync(invalidKeyFile, 'too-short');
  });

  afterAll(() => fs.rmSync(tempDir, { recursive: true, force: true }));

  it.each([hexKeyFile, base64KeyFile])('round-trips with the supported key encoding: %s', (keyFile) => {
    const encrypted = encryptStoredValue('refresh-token-value', keyFile);
    expect(encrypted).toMatch(/^v1:/);
    expect(encrypted).not.toContain('refresh-token-value');
    expect(decryptStoredValue(encrypted, keyFile)).toBe('refresh-token-value');
  });

  it('requires a configured key file', () => {
    expect(() => encryptStoredValue('secret', undefined)).toThrow('is not configured');
  });

  it('rejects keys that are not 32 bytes', () => {
    expect(() => encryptStoredValue('secret', invalidKeyFile)).toThrow('exactly 32 bytes');
  });

  it.each(['', 'v2:a:b:c', 'v1::b:c', 'v1:a::c', 'v1:a:b:', 'v1:a:b:c:extra'])(
    'rejects malformed ciphertext: %s',
    (encrypted) => expect(() => decryptStoredValue(encrypted, hexKeyFile)).toThrow('Unsupported encrypted'),
  );

  it('authenticates ciphertext before decrypting it', () => {
    const encrypted = encryptStoredValue('secret', hexKeyFile);
    const pieces = encrypted.split(':');
    pieces[3] = Buffer.from('tampered').toString('base64');
    expect(() => decryptStoredValue(pieces.join(':'), hexKeyFile)).toThrow();
  });
});
