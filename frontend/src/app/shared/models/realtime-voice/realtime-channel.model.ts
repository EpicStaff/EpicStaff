import { WebhookTriggerModel } from '../../../visual-programming/core/models/webhook-trigger.model';

export interface TwilioChannel {
    channel: number;
    account_sid: string;
    auth_token_secret_id: number | null;
    phone_number: string | null;
    webhook_trigger: WebhookTriggerModel | null;
}

export interface RealtimeChannel {
    id: number;
    name: string;
    channel_type: 'twilio';
    token: string;
    /** Legacy staff destination. Read-only here — the UI writes realtime_agent_definition. */
    realtime_agent: number | null;
    realtime_agent_definition: number | null;
    is_active: boolean;
    twilio?: TwilioChannel;
}

export interface CreateRealtimeChannelRequest {
    name: string;
    channel_type: 'twilio';
    realtime_agent_definition?: number | null;
    is_active?: boolean;
}

export interface UpdateRealtimeChannelRequest {
    id: number;
    name?: string;
    realtime_agent_definition?: number | null;
    is_active?: boolean;
}

export interface CreateTwilioChannelRequest {
    channel: number;
    account_sid: string;
    auth_token_secret_id: number | null;
    phone_number?: string | null;
    webhook_trigger?: number | null;
}

export interface UpdateTwilioChannelRequest {
    channel: number;
    account_sid?: string;
    auth_token_secret_id?: number | null;
    phone_number?: string | null;
    webhook_trigger?: number | null;
}
