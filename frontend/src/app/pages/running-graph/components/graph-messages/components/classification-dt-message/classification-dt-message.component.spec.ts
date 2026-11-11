import { TestBed } from '@angular/core/testing';

import {
    ClassificationPromptMessageData,
    GraphMessage,
    MessageType,
} from '../../../../models/graph-session-message.model';
import { ClassificationDtMessageComponent } from './classification-dt-message.component';

const BASE_DATA: ClassificationPromptMessageData = {
    prompt_id: 'p1',
    prompt_text: 'classify this',
    raw_response: '{"label": "a"}',
    parsed_result: { label: 'a' },
    result_variable: 'variables.label',
    usage: { total_tokens: 12, total_cost_usd: 0.000015834 },
    message_type: MessageType.CLASSIFICATION_PROMPT,
};

function render(overrides: Partial<ClassificationPromptMessageData>): HTMLElement {
    TestBed.configureTestingModule({ imports: [ClassificationDtMessageComponent] });
    const fixture = TestBed.createComponent(ClassificationDtMessageComponent);
    const message: GraphMessage = {
        id: 1,
        session: 1,
        name: 'classification',
        execution_order: 1,
        created_at: '2026-10-01T00:00:00Z',
        message_data: { ...BASE_DATA, ...overrides },
        metadata: {},
    };
    fixture.componentRef.setInput('message', message);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

function text(element: HTMLElement): string {
    return (element.textContent ?? '').replace(/\s+/g, ' ');
}

describe('ClassificationDtMessageComponent prompt message', () => {
    it('shows a System One step with provider, model version, "State sent" and the cost', () => {
        const content = text(render({ provider: 'typesafe', model_version: 'jev-1.14.0' }));

        expect(content).toContain('System One');
        expect(content).toContain('typesafe · jev-1.14.0');
        expect(content).toContain('State sent');
        expect(content).toContain('$0.000015834');
        expect(content).not.toContain('LLM Classification');
    });

    it('shows an LLM step as before when there is no provider', () => {
        const content = text(render({}));

        expect(content).toContain('LLM Classification');
        expect(content).toContain('Prompt');
        expect(content).not.toContain('System One');
        expect(content).not.toContain('State sent');
    });

    it('treats a null provider like an LLM step', () => {
        const content = text(render({ provider: null, model_version: null }));

        expect(content).toContain('LLM Classification');
        expect(content).not.toContain('System One');
    });
});
