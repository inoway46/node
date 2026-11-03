'use strict';

const net = require('node:net');
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function(...args) {
  if (typeof args[0] === 'number' && typeof args[1] !== 'string')
    args.splice(1, 0, '127.0.0.1');
  return listen.apply(this, args);
};
