export const environment = {
    production: false,
    apiUrl: '/api/',
    realtimeApiUrl: '/realtime/',
    auditorUrl: '/auditor/',
    isEpicChatEnabled: true,
    // Needs a running chat-service: set to true locally (ng serve proxies /chat/) to work on the chat pages.
    isChatEnabled: false,
    chatApiUrl: '/chat/',
};
