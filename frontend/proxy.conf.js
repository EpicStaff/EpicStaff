const target = process.env.PROXY_TARGET || 'http://localhost';

module.exports = [
  {
    context: ['/api', '/auditor', '/webhooks', '/static', '/media'],
    target,
    changeOrigin: true,
    secure: false,
  },
  {
    context: ['/ws', '/realtime', '/voice'],
    target,
    changeOrigin: true,
    secure: false,
    ws: true,
  },
];
