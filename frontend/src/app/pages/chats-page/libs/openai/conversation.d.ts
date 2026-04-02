/**
 * Contains text and audio information about a item
 * Can also be used as a delta
 * @typedef {Object} ItemContentDeltaType
 * @property {string} [text]
 * @property {Int16Array} [audio]
 * @property {string} [arguments]
 * @property {string} [transcript]
 */
/**
 * RealtimeConversation holds conversation history
 * and performs event validation for RealtimeAPI
 * @class
 */
export class RealtimeConversation {
    defaultFrequency: number;
    EventProcessors: {
        'conversation.item.created': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'conversation.item.truncated': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'conversation.item.deleted': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'conversation.item.input_audio_transcription.completed': (event: unknown) => {
            item: unknown;
            delta: {
                transcript: unknown;
            };
        };
        'input_audio_buffer.speech_started': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'input_audio_buffer.speech_stopped': (
            event: unknown,
            inputAudioBuffer: unknown
        ) => {
            item: unknown;
            delta: unknown;
        };
        'response.created': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'response.output_item.added': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'response.output_item.done': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'response.content_part.added': (event: unknown) => {
            item: unknown;
            delta: unknown;
        };
        'response.audio_transcript.delta': (event: unknown) => {
            item: unknown;
            delta: {
                transcript: unknown;
            };
        };
        'response.audio.delta': (event: unknown) => {
            item: unknown;
            delta: {
                audio: Int16Array;
            };
        };
        'response.text.delta': (event: unknown) => {
            item: unknown;
            delta: {
                text: unknown;
            };
        };
        'response.function_call_arguments.delta': (event: unknown) => {
            item: unknown;
            delta: {
                arguments: unknown;
            };
        };
    };
    queuedInputAudio: Int16Array;
    /**
     * Clears the conversation history and resets to default
     * @returns {true}
     */
    clear(): true;
    itemLookup: {};
    items: unknown[];
    responseLookup: {};
    responses: unknown[];
    queuedSpeechItems: {};
    queuedTranscriptItems: {};
    /**
     * Queue input audio for manual speech event
     * @param {Int16Array} inputAudio
     * @returns {Int16Array}
     */
    queueInputAudio(inputAudio: Int16Array): Int16Array;
    /**
     * Process an event from the WebSocket server and compose items
     * @param {Object} event
     * @param  {...any} args
     * @returns {item: import('./client.js').ItemType | null, delta: ItemContentDeltaType | null}
     */
    processEvent(event: unknown, ...args: unknown[]): item;
    /**
     * Retrieves a item by id
     * @param {string} id
     * @returns {import('./client.js').ItemType}
     */
    getItem(id: string): import('./client.js').ItemType;
    /**
     * Retrieves all items in the conversation
     * @returns {import('./client.js').ItemType[]}
     */
    getItems(): import('./client.js').ItemType[];
}
/**
 * Contains text and audio information about a item
 * Can also be used as a delta
 */
export type ItemContentDeltaType = {
    text?: string;
    audio?: Int16Array;
    arguments?: string;
    transcript?: string;
};
//# sourceMappingURL=conversation.d.ts.map
