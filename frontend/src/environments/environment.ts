export const environment = {
    production: false,
    apiUrl: '/api/',
    realtimeApiUrl: '/realtime/',
    auditorUrl: '/auditor/',
    // On by default so `ng serve` shows the Chats and Audit pages; they need the chat and auditor compose profiles running.
    isChatEnabled: true,
    chatApiUrl: '/chat/',
    isAuditTrailEnabled: true,
    // Needs PLUGINS_ENABLED on the backend and nginx (plugin hosts under PLUGINS_BASE_DOMAIN).
    isPluginsEnabled: false,
};
