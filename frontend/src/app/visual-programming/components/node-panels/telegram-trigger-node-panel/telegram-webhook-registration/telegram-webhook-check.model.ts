import { TelegramWebhookInfo } from '../../../../core/models/telegram-trigger.model';

/** Where the last Register press stands. */
export type TelegramRegisterAttempt =
    | 'idle'
    | 'in-progress'
    /** The backend answered 409: the blocker is then in `info.registration_blocker`. */
    | 'blocked'
    /** Telegram failed or rejected the `setWebhook` call (502 `telegram_registration_failed`). */
    | 'failed-telegram'
    /** The trigger's tunnel is not up, so Telegram was never called (503 `telegram_tunnel_unavailable`). */
    | 'failed-tunnel'
    /** Telegram does not accept the saved bot key (422 `telegram_bot_key_rejected`). */
    | 'failed-bot-key-rejected'
    /** Registered, but reading the status back failed (502 `telegram_webhook_info_unavailable`). */
    | 'registered-unread'
    /** Any other failure (permissions, missing node, server error, network). */
    | 'failed-other';

/** Result of asking the backend which webhook Telegram has registered for the node's bot key. */
export type TelegramWebhookCheck =
    | { state: 'not-saved' }
    | { state: 'no-bot-key' }
    /** `requestedByUser`: Check was pressed, so the live region says a check is running. */
    | { state: 'loading'; requestedByUser: boolean }
    | { state: 'loaded'; info: TelegramWebhookInfo; registerAttempt: TelegramRegisterAttempt }
    /** The backend could not read Telegram's getWebhookInfo (502). */
    | { state: 'telegram-unreachable' }
    /** Telegram answered 401/404 for the saved bot key: malformed, unknown or revoked (422). */
    | { state: 'bot-key-rejected' }
    /** Any other failure (permissions, missing node, server error). */
    | { state: 'error' };

/** `code` of the backend's 400 error envelope when the saved node has no bot key. */
export const TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE = 'telegram_bot_key_not_configured';
/** `code` of the 422 envelope (webhook-info and register-webhook) when Telegram rejects the bot key. */
export const TELEGRAM_BOT_KEY_REJECTED_CODE = 'telegram_bot_key_rejected';
/** `code` of the 409 error envelope when a registration blocker stops `register-webhook`. */
export const TELEGRAM_REGISTRATION_BLOCKED_CODE = 'telegram_registration_blocked';
/** `code` of the 502 envelope when Telegram failed or rejected `setWebhook`. */
export const TELEGRAM_REGISTRATION_FAILED_CODE = 'telegram_registration_failed';
/** `code` of the 503 envelope when the trigger's tunnel is unavailable. */
export const TELEGRAM_TUNNEL_UNAVAILABLE_CODE = 'telegram_tunnel_unavailable';
/** `code` of the 502 envelope when Telegram's getWebhookInfo could not be read. */
export const TELEGRAM_WEBHOOK_INFO_UNAVAILABLE_CODE = 'telegram_webhook_info_unavailable';
