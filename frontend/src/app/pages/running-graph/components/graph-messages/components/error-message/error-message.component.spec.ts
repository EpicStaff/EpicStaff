import { TestBed } from '@angular/core/testing';

import { GraphMessage, MessageType } from '../../../../models/graph-session-message.model';
import { ErrorMessageComponent } from './error-message.component';

function renderHeader(name: string): HTMLElement {
    const message: GraphMessage = {
        id: 1,
        session: 1,
        name,
        execution_order: 1,
        created_at: '2026-11-03T00:00:00Z',
        metadata: {},
        message_data: { details: 'Connection refused', message_type: MessageType.ERROR },
    };
    const fixture = TestBed.createComponent(ErrorMessageComponent);
    fixture.componentRef.setInput('message', message);
    fixture.detectChanges();
    const header = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('.error-header');
    if (!header) throw new Error('error header not rendered');
    return header;
}

function headingText(header: HTMLElement): string {
    return header.querySelector('h3')?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

describe('ErrorMessageComponent heading', () => {
    it.each([
        { name: 'Save lead #3 #1742', heading: 'Save lead #3 failed' },
        { name: 'Save lead #1742', heading: 'Save lead failed' },
        { name: '', heading: 'Error' },
    ])('shows $heading for the runtime node name $name', ({ name, heading }) => {
        expect(headingText(renderHeader(name))).toBe(heading);
    });

    it('highlights only the node label', () => {
        const header = renderHeader('Save lead #3 #1742');

        expect(header.querySelector('.node-name')?.textContent?.trim()).toBe('Save lead #3');
    });
});
