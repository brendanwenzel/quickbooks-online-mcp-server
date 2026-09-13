// Makes Supergateway 3.4.3's stdio→SSE gateway safe for several concurrent
// clients sharing one long-lived stdio child.
//
// Stock 3.4.3 binds every SSE connection to ONE shared `Server` instance, and
// the bundled MCP SDK throws "Already connected to a transport" on the second
// client. An earlier version of this patch "fixed" that by closing the previous
// session on every new connection — so with more than one client attached
// (Claude Code, Claude Desktop, the keep-alive) each new connection killed the
// others, clients reconnected in a ~1 s storm, and tool responses were
// delivered to nobody (the keep-alive saw "no response within 60s" and 503
// "No active SSE connection").
//
// This version:
//   * starts each SSEServerTransport directly (no shared Server object), so any
//     number of sessions can be attached at once;
//   * rewrites the JSON-RPC id of every client request to a gateway-wide unique
//     id before it reaches the child, remembers which session asked, and routes
//     the child's response back to that session only, with the original id
//     restored (clients all start numbering at 0/1, so ids collide across
//     sessions and the stock "broadcast to everyone" would misdeliver);
//   * still broadcasts child notifications (no id) to every session.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const globalRoot =
  process.env.SUPERGATEWAY_ROOT ??
  execFileSync('npm', ['root', '--global'], { encoding: 'utf8' }).trim();
const gatewayPath = path.join(
  globalRoot,
  'supergateway',
  'dist',
  'gateways',
  'stdioToSse.js',
);

let source = fs.readFileSync(gatewayPath, 'utf8');

const stateBefore = `    const server = new Server({ name: 'supergateway', version: getVersion() }, { capabilities: {} });
    const sessions = {};`;
const stateAfter = `    // Patched (deploy/patch-supergateway-sse.mjs): multi-session routing.
    const sessions = {};
    // gateway request id -> { sessionId, id: the client's original id }
    const pending = new Map();
    let nextGatewayId = 1;
    const dropSession = (sid) => {
        delete sessions[sid];
        for (const [gid, target] of pending) {
            if (target.sessionId === sid)
                pending.delete(gid);
        }
    };
    const sendTo = (sid, msg) => {
        const session = sessions[sid];
        if (!session)
            return;
        try {
            session.transport.send(msg);
        }
        catch (err) {
            logger.error(\`Failed to send to session \${sid}:\`, err);
            dropSession(sid);
        }
    };
    const isRequest = (msg) => msg && typeof msg === 'object' && msg.id !== undefined && msg.id !== null && typeof msg.method === 'string';
    const isResponse = (msg) => msg && typeof msg === 'object' && msg.id !== undefined && msg.id !== null && typeof msg.method !== 'string';
    const routeChildMessage = (msg) => {
        if (isResponse(msg)) {
            const target = pending.get(msg.id);
            if (!target) {
                logger.error(\`Child response for unknown request id \${String(msg.id)}; dropped\`);
                return;
            }
            pending.delete(msg.id);
            sendTo(target.sessionId, { ...msg, id: target.id });
            return;
        }
        for (const sid of Object.keys(sessions))
            sendTo(sid, msg);
    };`;

const connectBefore = `        const sseTransport = new SSEServerTransport(\`\${baseUrl}\${messagePath}\`, res);
        await server.connect(sseTransport);`;
const connectAfter = `        const sseTransport = new SSEServerTransport(\`\${baseUrl}\${messagePath}\`, res);
        // Start the transport directly: no shared Server, so concurrent
        // sessions never trip "Already connected to a transport".
        await sseTransport.start();`;

const onMessageBefore = `        sseTransport.onmessage = (msg) => {
            logger.info(\`SSE → Child (session \${sessionId}): \${JSON.stringify(msg)}\`);
            child.stdin.write(JSON.stringify(msg) + '\\n');
        };`;
const onMessageAfter = `        sseTransport.onmessage = (msg) => {
            logger.info(\`SSE → Child (session \${sessionId}): \${JSON.stringify(msg)}\`);
            let outbound = msg;
            if (isRequest(msg)) {
                const gatewayId = nextGatewayId++;
                pending.set(gatewayId, { sessionId, id: msg.id });
                outbound = { ...msg, id: gatewayId };
            }
            child.stdin.write(JSON.stringify(outbound) + '\\n');
        };`;

const forwardBefore = `                logger.info('Child → SSE:', jsonMsg);
                for (const [sid, session] of Object.entries(sessions)) {
                    try {
                        session.transport.send(jsonMsg);
                    }
                    catch (err) {
                        logger.error(\`Failed to send to session \${sid}:\`, err);
                        delete sessions[sid];
                    }
                }`;
const forwardAfter = `                logger.info('Child → SSE:', jsonMsg);
                routeChildMessage(jsonMsg);`;

for (const [before, after, label] of [
  [stateBefore, stateAfter, 'session state'],
  [connectBefore, connectAfter, 'connect'],
  [onMessageBefore, onMessageAfter, 'onmessage'],
  [forwardBefore, forwardAfter, 'child forwarding'],
]) {
  if (!source.includes(before)) {
    throw new Error(`Unable to patch Supergateway SSE ${label} behavior`);
  }
  source = source.replace(before, after);
}

// The three per-session cleanup hooks (onclose, onerror, req 'close') must also
// forget that session's in-flight requests.
const cleanupBefore = `            delete sessions[sessionId];`;
const cleanupCount = source.split(cleanupBefore).length - 1;
if (cleanupCount !== 3) {
  throw new Error(
    `Expected 3 per-session cleanup sites in Supergateway SSE gateway, found ${cleanupCount}`,
  );
}
source = source.replaceAll(cleanupBefore, `            dropSession(sessionId);`);

fs.writeFileSync(gatewayPath, source);
