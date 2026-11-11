import { ComponentFixture, TestBed } from '@angular/core/testing';

import {
    GraphMessage,
    MessageData,
    MessageType,
    NodeStreamLlmFallbackData,
    NodeStreamLlmFallbackSkippedData,
} from '../../../../models/graph-session-message.model';
import { NodeStreamMessageComponent } from './node-stream-message.component';

const NODE_NAME = 'Agent One';

function streamMessage(
    id: number,
    event: 'llm_fallback' | 'llm_fallback_skipped',
    data: NodeStreamLlmFallbackData | NodeStreamLlmFallbackSkippedData
): GraphMessage {
    return {
        id,
        session: 1,
        name: NODE_NAME,
        execution_order: id,
        created_at: '2026-10-27T10:00:00Z',
        message_data: {
            message_type: MessageType.AGENT_NODE_STREAM,
            event,
            step_id: id,
            is_final: false,
            data,
        } as MessageData,
        metadata: {},
    };
}

function fallbackData(overrides: Partial<NodeStreamLlmFallbackData> = {}): NodeStreamLlmFallbackData {
    return {
        task: null,
        primary: { config_name: 'Key A', model: 'gpt-4o' },
        fallback: { config_name: 'Key B', model: 'claude-sonnet-4-5' },
        error_type: 'RateLimitError',
        ...overrides,
    };
}

describe('NodeStreamMessageComponent LLM fallback notices', () => {
    let fixture: ComponentFixture<NodeStreamMessageComponent>;

    function render(messages: GraphMessage[]): NodeStreamMessageComponent {
        fixture = TestBed.createComponent(NodeStreamMessageComponent);
        fixture.componentRef.setInput('message', messages[0]);
        fixture.componentRef.setInput('allMessages', messages);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    function noticeTexts(): string[] {
        const elements: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('.llm-notice'));
        return elements.map((element) => element.textContent?.trim() ?? '');
    }

    beforeEach(() => TestBed.configureTestingModule({ imports: [NodeStreamMessageComponent] }));

    it('puts a fallback notice with a task into that task group', () => {
        const component = render([
            streamMessage(1, 'llm_fallback', fallbackData({ task: { name: 'Research', order: 1 } })),
        ]);

        const [group] = component.taskGroups();
        expect(group.taskName).toBe('Research');
        expect(group.notices).toEqual([
            'Primary LLM "Key A" (gpt-4o) failed with RateLimitError. Switched to fallback "Key B" (claude-sonnet-4-5).',
        ]);
    });

    it('puts a fallback notice without a task into the default group', () => {
        const component = render([streamMessage(1, 'llm_fallback', fallbackData())]);

        const [group] = component.taskGroups();
        expect(group.key).toBe('__default__');
        expect(group.taskName).toBeNull();
        expect(group.notices).toHaveLength(1);
    });

    it('shows the model alone when a config name is missing, per side', () => {
        const component = render([
            streamMessage(1, 'llm_fallback', fallbackData({ primary: { config_name: null, model: 'gpt-4o' } })),
        ]);

        expect(component.taskGroups()[0].notices).toEqual([
            'Primary LLM gpt-4o failed with RateLimitError. Switched to fallback "Key B" (claude-sonnet-4-5).',
        ]);
    });

    it('shows the skipped message as is', () => {
        const component = render([
            streamMessage(1, 'llm_fallback_skipped', { message: 'Fallback LLM skipped: same as primary.' }),
        ]);

        expect(component.taskGroups()[0].notices).toEqual(['Fallback LLM skipped: same as primary.']);
    });

    it('renders a group that has only a notice', () => {
        const component = render([streamMessage(1, 'llm_fallback', fallbackData())]);

        expect(component.hasContent()).toBe(true);
        expect(noticeTexts()).toEqual([
            'Primary LLM "Key A" (gpt-4o) failed with RateLimitError. Switched to fallback "Key B" (claude-sonnet-4-5).',
        ]);
    });
});
