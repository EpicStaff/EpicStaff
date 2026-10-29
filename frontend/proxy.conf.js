const target = process.env.PROXY_TARGET || 'http://localhost';

module.exports = [
  {
    // '/chat/' with the slash: the SPA route '/chat' and the EpicChat route '/chats' stay with the dev server.
    context: ['/api', '/auditor', '/webhooks', '/static', '/media', '/chat/'],
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
