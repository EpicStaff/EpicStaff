import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import type { Mock } from 'vitest';

import { AgentDefinition } from '../../../features/agent-definitions/models/agent-definition.model';
import { AuthService } from '../../../services/auth/auth.service';
import { ConfigService } from '../../../services/config';
import { ToastService } from '../../../services/notifications';
import { ChatAgent } from '../models/chat-agent.model';
import { ChatsService } from './chats.service';
import { ConnectionResult, ConsoleService } from './console.service';
import { WavStreamPlayerService } from './wav-player.service';
import { WavRecorderService } from './wav-recorder.service';

/** An agent with a realtime config; the console reads only its id and its realtime configs. */
const AGENT: ChatAgent = {
    agent: { id: 7, name: 'Concierge' } as AgentDefinition,
    realtime: {
        agent_definition: 7,
        openai_config: 4,
        elevenlabs_config: null,
        gemini_config: null,
        voice: 'verse',
        wake_word: null,
        stop_prompt: null,
        language: null,
        voice_recognition_prompt: null,
    },
};

describe('ConsoleService', () => {
    let http: HttpTestingController;
    let service: ConsoleService;
    let toast: { error: Mock; warning: Mock };

    beforeEach(() => {
        toast = { error: vi.fn(), warning: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/', realtimeApiUrl: 'ws://realtime' } },
                { provide: ChatsService, useValue: { selectedChatAgent$: signal<ChatAgent | null>(AGENT) } },
                { provide: ToastService, useValue: toast },
                { provide: AuthService, useValue: { getAccessToken: () => null } },
                { provide: WavRecorderService, useValue: { stopRecording: vi.fn(() => Promise.resolve()) } },
                { provide: WavStreamPlayerService, useValue: {} },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        service = TestBed.inject(ConsoleService);
        // The service logs every failed connection; keep the test output clean.
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
    });

    afterEach(() => {
        http.verify();
        vi.restoreAllMocks();
    });

    function startAndFail(status: number, body: string | object): ConnectionResult | undefined {
        let result: ConnectionResult | undefined;
        service.connectConversation().subscribe((answer) => (result = answer));
        const request = http.expectOne('/api/init-realtime/');
        expect(request.request.body).toEqual({ agent_definition_id: 7 });
        request.flush(body, { status, statusText: 'Error' });
        return result;
    }

    function envelope(detail: string): object {
        return { type: 'client_error', errors: [{ code: 'invalid', detail, attr: null, context: null }] };
    }

    const SUSPENDED_PLUGIN =
        'This run uses resources of the plugin "Weather", which is suspended in this organization.';

    it("shows the server's message of a refused start", () => {
        const result = startAndFail(409, {
            type: 'client_error',
            errors: [
                {
                    code: 'plugin_suspended',
                    detail: SUSPENDED_PLUGIN,
                    attr: null,
                    context: { plugin: { identifier: 'weather', name: 'Weather' }, organization: { id: 3 } },
                },
            ],
        });

        expect(toast.error).toHaveBeenCalledWith(SUSPENDED_PLUGIN);
        expect(result?.success).toBe(false);
    });

    it('shows the error text the realtime start answers with', () => {
        startAndFail(400, envelope('The agent has no realtime config.'));

        expect(toast.error).toHaveBeenCalledWith('The agent has no realtime config.');
    });

    it('explains conflicting RAG settings', () => {
        startAndFail(400, envelope('The surfaces have conflicting RAG configs for collection 3.'));

        expect(toast.error).toHaveBeenCalledWith(
            "Conflict: the agent's surfaces use the same collection with different RAG settings."
        );
    });

    it('falls back to a generic message without a server message', () => {
        startAndFail(502, 'Bad gateway');

        expect(toast.error).toHaveBeenCalledWith('Failed to start the realtime conversation');
    });
});
