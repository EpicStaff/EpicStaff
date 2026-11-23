import { TestBed } from '@angular/core/testing';

import { GraphMessage, MessageType } from '../../../../models/graph-session-message.model';
import { ErrorMessageComponent } from './error-message.component';

function render(name: string): HTMLElement {
    const fixture = TestBed.createComponent(ErrorMessageComponent);
    fixture.componentInstance.message = {
        id: 1,
        session: 314,
        name,
        execution_order: 1,
        created_at: '2026-11-11T14:07:56Z',
        message_data: {
            message_type: MessageType.ERROR,
            error: {
                code: 'node_failed',
                detail: 'Key-Value node "Save lead #3" has no table selected.',
                attr: null,
                context: null,
            },
        },
        metadata: {},
    } as GraphMessage;
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('ErrorMessageComponent', () => {
    beforeEach(() => TestBed.configureTestingModule({ imports: [ErrorMessageComponent] }));

    it('names the node that failed in the heading', () => {
        expect(render('Save lead #3 #357').querySelector('h3')?.textContent?.trim()).toBe('Save lead #3 failed');
    });

    it('keeps the plain heading when the error belongs to no node', () => {
        expect(render('').querySelector('h3')?.textContent?.trim()).toBe('Error');
    });
});

describe('ErrorMessageComponent error text', () => {
    const UNKNOWN_ERROR_NOTE = '{\n  "error": "Unknown error"\n}';

    beforeEach(() => TestBed.configureTestingModule({ imports: [ErrorMessageComponent] }));

    function shownText(messageData: Record<string, unknown>): string | undefined {
        const fixture = TestBed.createComponent(ErrorMessageComponent);
        fixture.componentInstance.message = {
            id: 1,
            session: 314,
            name: 'Save lead #3 #357',
            execution_order: 1,
            created_at: '2026-11-11T14:07:56Z',
            message_data: { message_type: MessageType.ERROR, ...messageData },
            metadata: {},
        } as GraphMessage;
        fixture.detectChanges();
        return (fixture.nativeElement as HTMLElement).querySelector('pre')?.textContent?.trim();
    }

    it.each([
        {
            case: 'the detail of the error item',
            messageData: {
                error: { code: 'node_failed', detail: 'Node "Save lead" failed.', attr: null, context: null },
            },
            expected: 'Node "Save lead" failed.',
        },
        {
            case: 'the detail of the error item without its surrounding quotes',
            messageData: {
                error: { code: 'node_failed', detail: '"Division by zero"', attr: null, context: null },
            },
            expected: 'Division by zero',
        },
        {
            case: 'the unknown-error note for a message without an error item',
            messageData: { details: 'Node "Save lead" failed.' },
            expected: UNKNOWN_ERROR_NOTE,
        },
        {
            case: 'the unknown-error note for an error item without a detail',
            messageData: { error: { code: 'node_failed', attr: null, context: null } },
            expected: UNKNOWN_ERROR_NOTE,
        },
    ])('shows $case', ({ messageData, expected }) => {
        expect(shownText(messageData)).toBe(expected);
    });
});
