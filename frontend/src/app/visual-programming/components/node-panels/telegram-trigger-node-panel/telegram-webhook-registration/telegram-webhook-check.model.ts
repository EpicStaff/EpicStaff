import { TelegramWebhookInfo } from '../../../../core/models/telegram-trigger.model';

/** Result of asking the backend which webhook Telegram has registered for the node's bot key. */
export type TelegramWebhookCheck =
    | { state: 'not-saved' }
    | { state: 'no-bot-key' }
    | { state: 'loading' }
    | { state: 'loaded'; info: TelegramWebhookInfo }
    /** The backend could not read Telegram's getWebhookInfo (502). */
    | { state: 'telegram-unreachable' }
    /** Any other failure (permissions, missing node, server error). */
    | { state: 'error' };

/** `code` of the backend's 400 error envelope when the saved node has no bot key. */
export const TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE = 'telegram_bot_key_not_configured';
