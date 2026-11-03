'use strict';
const common = require('../common');
if (!common.hasCrypto)
  common.skip('missing crypto');
const assert = require('assert');
const http2 = require('http2');
const tls = require('tls');
const fixtures = require('../common/fixtures');

const server = http2.createSecureServer({
  key: fixtures.readKey('agent1-key.pem'),
  cert: fixtures.readKey('agent1-cert.pem'),
  requestCert: true,
  rejectUnauthorized: true,
  minVersion: 'TLSv1.3',
  maxVersion: 'TLSv1.3',
});
server.on('tlsClientError', common.mustCall((err) => {
  assert.strictEqual(err.code, 'ERR_SSL_PEER_DID_NOT_RETURN_A_CERTIFICATE');
}));
server.listen(0, '127.0.0.1', common.mustCall(() => {
  const socket = tls.connect({
    host: '127.0.0.1',
    port: server.address().port,
    servername: 'localhost',
    rejectUnauthorized: false,
    ALPNProtocols: ['h2'],
    minVersion: 'TLSv1.3',
    maxVersion: 'TLSv1.3',
  });
  const session = http2.connect('https://localhost', {
    createConnection: () => socket,
  });
  let errorEmitted = false;
  session.on('connect', common.mustCall(() => {
    assert.strictEqual(socket.getProtocol(), 'TLSv1.3');
  }));
  session.on('error', common.mustCall((err) => {
    assert.strictEqual(err.code, 'ERR_SSL_TLSV13_ALERT_CERTIFICATE_REQUIRED');
    errorEmitted = true;
  }));
  socket.on('close', common.mustCall());
  session.on('close', common.mustCall(() => {
    assert(errorEmitted);
    assert(session.destroyed);
    assert(socket.destroyed);
    server.close(common.mustCall());
  }));
}));
