// Adds an `error` log level to Supergateway 3.4.3.
//
// Stock levels are debug / info / none. `info` logs every MCP message body
// (financial data for this deployment), and `none` also swallows the child's
// stderr and exit notices, which is exactly what an operator needs when a
// container misbehaves. `error` keeps logger.info silent and routes
// logger.error (child stderr, child exit, transport failures) to stderr.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const globalRoot = execFileSync('npm', ['root', '--global'], {
  encoding: 'utf8',
}).trim();
const distDir = path.join(globalRoot, 'supergateway', 'dist');

function patch(file, replacements) {
  let source = fs.readFileSync(file, 'utf8');
  for (const [before, after, label] of replacements) {
    if (!source.includes(before)) {
      throw new Error(`Unable to patch Supergateway ${label} in ${file}`);
    }
    source = source.replace(before, after);
  }
  fs.writeFileSync(file, source);
}

patch(path.join(distDir, 'lib', 'getLogger.js'), [
  [
    `const infoLogger = {`,
    `const errorLogger = {
    info: () => { },
    error: logStderr(),
};
const infoLogger = {`,
    'errorLogger definition',
  ],
  [
    `    if (logLevel === 'debug') {`,
    `    if (logLevel === 'error') {
        return errorLogger;
    }
    if (logLevel === 'debug') {`,
    'errorLogger selection',
  ],
]);

patch(path.join(distDir, 'index.js'), [
  [
    `choices: ['debug', 'info', 'none']`,
    `choices: ['debug', 'info', 'error', 'none']`,
    'logLevel choices',
  ],
]);
