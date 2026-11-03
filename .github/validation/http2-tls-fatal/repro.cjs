'use strict';
const process = require('node:process');
const console = require('node:console');
const { setTimeout } = require('node:timers');
const fs = require('node:fs');
const http2 = require('node:http2');
const { execFileSync } = require('node:child_process');
const { setTimeout: delay, setImmediate: immediate } = require('node:timers/promises');
const mode = process.argv[2] || 'fatal';
const records = [];
const peers = new Set();
const start = Date.now();
function log(event, data = {}) { console.log(JSON.stringify({ ms: Date.now() - start, event, ...data })); }

function fdInfo() {
  try {
    if (process.platform === 'linux') return { count: fs.readdirSync('/proc/self/fd').length };
    const lines = execFileSync('/usr/sbin/lsof',
                               ['-nP',
                                '-a',
                                '-p',
                                String(process.pid),
                                '-Ffn'],
                               { encoding: 'utf8',
                                 timeout: 2000 }).split('\n');
    return { count: lines.filter((x) => /^f\d/.test(x)).length, tcp: lines.filter((x) => x.startsWith('n127.0.0.1:')) };
  } catch (e) { return { error: e.message }; }
}

function snapshot(label) {
  log(label,
      { fds: fdInfo(),
        handles: process._getActiveHandles().map((h) => ({ type: h.constructor.name,
                                                           destroyed: h.destroyed,
                                                           fd: h._handle?.fd })),
        sessions: records.map((r) => {
          const s = r.ref.deref();
          let socketDestroyed;
          try {
            socketDestroyed = s?.socket?.destroyed;
          } catch { /* The session may already have detached its socket. */ }
          return { alive: !!s,
                   destroyed: s?.destroyed,
                   closed: s?.closed,
                   socketDestroyed,
                   socketDestroyedAtClose: r.socketDestroyedAtClose,
                   events: r.events };
        }) });
}
const root = require('node:path').join(process.env.NODE_SOURCE_DIR, 'test/fixtures/keys/');
const server = http2.createSecureServer({ key: fs.readFileSync(root + 'agent1-key.pem'),
                                          cert: fs.readFileSync(root + 'agent1-cert.pem'),
                                          minVersion: 'TLSv1.3',
                                          maxVersion: 'TLSv1.3',
                                          requestCert: mode !== 'control',
                                          rejectUnauthorized: mode !== 'control' });
server.on('connection', (s) => { peers.add(s); s.on('close', () => peers.delete(s)); });
server.on('tlsClientError', (e) => log('server-tls-error', { code: e.code }));
server.on('session', (s) => s.on('error', () => {}));
server.on('error', (e) => { log('server-error', { code: e.code }); process.exitCode = 1; });
const hard = setTimeout(() => { log('hard-deadline'); process.exit(2); }, 12000); hard.unref();
async function connectOne(i) {
  let s = http2.connect(`https://127.0.0.1:${server.address().port}`,
                        { servername: 'localhost',
                          rejectUnauthorized: false,
                          minVersion: 'TLSv1.3',
                          maxVersion: 'TLSv1.3' });
  const r = { ref: new WeakRef(s), events: [] }; records.push(r);
  // Retain the actual socket only weakly, for explicit cleanup after measurement.
  const sym = Object.getOwnPropertySymbols(s).find((k) => k.description === 'socket');
  const raw = s[sym]; r.socket = new WeakRef(raw);
  if (mode !== 'plain') raw.on('error',
                               (e) => {
                                 r.events.push('socket-error:' + e.code);
                                 log('socket-error',
                                     { i,
                                       code: e.code });
                                 if (mode === 'abort')raw.destroy();
                               });
  raw.on('close', () => { r.socketDestroyedAtClose = raw.destroyed; r.events.push('socket-close'); });
  s.on('error', (e) => { r.events.push('session-error:' + e.code); log('session-error', { i, code: e.code }); });
  s.on('close', () => { r.events.push('session-close'); log('session-close', { i }); });
  s.on('connect',
       () => {
         log('connect',
             { i,
               protocol: raw.getProtocol() });
         if (mode === 'control')r.ref.deref().close();
       });
  s = null;
}
server.listen(0, '127.0.0.1', async () => {
  try {
    log('environment',
        { mode,
          node: process.version,
          openssl: process.versions.openssl,
          platform: process.platform,
          arch: process.arch });
    snapshot('baseline');
    for (let i = 0; i < 3; i++) { await connectOne(i); await delay(100); }
    await delay(700); snapshot('observed-1s');
    for (let i = 0; i < 5; i++) { global.gc(); await immediate(); }
    snapshot('after-gc'); await delay(2000); snapshot('observed-3s');
  } finally {
    log('cleanup-start');
    for (const r of records)r.socket.deref()?.destroy();
    for (const s of peers)s.destroy();
    server.close();
    await delay(200); for (let i = 0; i < 5; i++) { global.gc(); await immediate(); }snapshot('cleanup-complete');
  }
});
