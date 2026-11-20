'use strict';
// Preload: route every http2.connect() through a TCP proxy that holds
// server->client bytes for COALESCE_MS and forwards them in one write.
const http2 = require('http2');
const net = require('net');
const ms = Number(process.env.COALESCE_MS || 100);
const origConnect = http2.connect;
http2.connect = function(authority, options, listener) {
  const url = new URL(authority);
  const proxy = net.createServer((c) => {
    const s = net.connect(Number(url.port), '127.0.0.1');
    c.pipe(s);
    let buf = [];
    let timer = null;
    s.on('data', (d) => {
      buf.push(d);
      timer ??= setTimeout(() => {
        timer = null;
        if (!c.destroyed) c.write(Buffer.concat(buf));
        buf = [];
      }, ms);
    });
    c.on('error', () => {});
    s.on('error', () => {});
    c.on('close', () => s.destroy());
    s.on('close', () => c.destroy());
    proxy.close();
  });
  proxy.listen(0, '127.0.0.1');
  proxy.unref();
  return origConnect.call(this, authority, {
    ...options,
    createConnection: () => {
      const sock = new net.Socket();
      proxy.once('listening',
                 () => sock.connect(proxy.address().port, '127.0.0.1'));
      return sock;
    },
  }, listener);
};
