'use strict';
const process = require('node:process');
const console = require('node:console');
const { setTimeout } = require('node:timers');
const assert = require('node:assert');
const http2 = require('node:http2');
const fs = require('node:fs');
const root = require('node:path').join(process.env.NODE_SOURCE_DIR, 'test/fixtures/keys/');
const deadline = setTimeout(() => { throw new Error('GOAWAY timeout'); }, 5000); deadline.unref();
(async () => {
  for (const secure of [false, true]) for (const code of [0, 7]) {
    await new Promise((resolve, reject) => {
      const server = secure ? http2.createSecureServer({ key: fs.readFileSync(root + 'agent1-key.pem'),
                                                         cert: fs.readFileSync(root + 'agent1-cert.pem') }) :
        http2.createServer();
      server.on('session', (s) => s.on('error', (e) => { assert.strictEqual(code, 7); }));
      server.on('stream', (stream) => {
        const s = stream.session;
        stream.on('error', () => {}); stream.respond(); stream.end('ok');
        stream.on('close', () => { if (code === 0)s.close(); else s.destroy(code); });
      });
      server.listen(0, '127.0.0.1', () => {
        const c = http2.connect(`${secure ? 'https' : 'http'}://127.0.0.1:${server.address().port}`,
                                { servername: 'localhost',
                                  rejectUnauthorized: false });
        let goaway = false;
        c.on('error', (e) => { assert.strictEqual(code, 7); assert.strictEqual(e.code, 'ERR_HTTP2_SESSION_ERROR'); });
        c.on('goaway', (value) => { assert.strictEqual(value, code); goaway = true; c.close(); });
        c.on('close', () => { assert(goaway); server.close(resolve); });
        const req = c.request(); req.on('error', () => {}); req.resume(); req.end();
      });
    });
    console.log(JSON.stringify({ secure, code, goaway: true }));
  }
})();
