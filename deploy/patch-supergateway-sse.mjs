import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const globalRoot = execFileSync('npm', ['root', '--global'], {
  encoding: 'utf8',
}).trim();
const gatewayPath = path.join(
  globalRoot,
  'supergateway',
  'dist',
  'gateways',
  'stdioToSse.js',
);

let source = fs.readFileSync(gatewayPath, 'utf8');

const connectBefore = `        const sseTransport = new SSEServerTransport(\`\${baseUrl}\${messagePath}\`, res);
        await server.connect(sseTransport);`;
const connectAfter = `        const sseTransport = new SSEServerTransport(\`\${baseUrl}\${messagePath}\`, res);
        // Supergateway 3.4.3 otherwise throws on every client reconnect. Keep
        // exactly one SSE session attached to the single long-lived stdio child.
        if (server.transport) {
            await server.close();
        }
        await server.connect(sseTransport);
        const protocolOnClose = sseTransport.onclose;
        const protocolOnError = sseTransport.onerror;`;

const closeBefore = `        sseTransport.onclose = () => {
            logger.info(\`SSE connection closed (session \${sessionId})\`);`;
const closeAfter = `        sseTransport.onclose = () => {
            protocolOnClose?.();
            logger.info(\`SSE connection closed (session \${sessionId})\`);`;

const errorBefore = `        sseTransport.onerror = (err) => {
            logger.error(\`SSE error (session \${sessionId}):\`, err);`;
const errorAfter = `        sseTransport.onerror = (err) => {
            protocolOnError?.(err);
            logger.error(\`SSE error (session \${sessionId}):\`, err);`;

for (const [before, after, label] of [
  [connectBefore, connectAfter, 'connect'],
  [closeBefore, closeAfter, 'close'],
  [errorBefore, errorAfter, 'error'],
]) {
  if (!source.includes(before)) {
    throw new Error(`Unable to patch Supergateway SSE ${label} behavior`);
  }
  source = source.replace(before, after);
}

fs.writeFileSync(gatewayPath, source);
