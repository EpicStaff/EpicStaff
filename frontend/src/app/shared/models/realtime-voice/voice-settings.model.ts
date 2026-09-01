export interface VoiceSettings {
    twilio_account_sid: string;
    twilio_auth_token: string;
    /** Agent definition that answers Twilio calls. The only writable voice-agent FK. */
    voice_agent_definition: number | null;
    ngrok_config: number | null;
    voice_stream_url: string | null;
}
