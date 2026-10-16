export const environment = {
    production: false,
    apiUrl: '/api/',
    realtimeApiUrl: '/realtime/',
    auditorUrl: '/auditor/',
    // Needs the chat service running (chat compose profile): set to true locally (ng serve proxies /chat/) to work on the chat pages.
    isChatEnabled: false,
    chatApiUrl: '/chat/',
    isAuditTrailEnabled: false,
};
