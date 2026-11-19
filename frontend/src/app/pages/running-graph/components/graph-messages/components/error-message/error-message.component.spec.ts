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
            details: 'Key-Value node "Save lead #3" has no table selected.',
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
