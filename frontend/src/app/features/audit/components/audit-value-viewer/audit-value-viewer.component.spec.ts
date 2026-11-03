import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { JsonEditorComponent } from '@shared/components';

import { AuditValueViewerComponent } from './audit-value-viewer.component';

function render(): { fixture: ComponentFixture<AuditValueViewerComponent>; closes: number[] } {
    TestBed.overrideComponent(AuditValueViewerComponent, {
        remove: { imports: [JsonEditorComponent] },
        add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
    });
    const fixture = TestBed.createComponent(AuditValueViewerComponent);
    fixture.componentRef.setInput('field', 'input');
    fixture.componentRef.setInput('value', '{}');
    fixture.detectChanges();
    const closes: number[] = [];
    fixture.componentInstance.closed.subscribe(() => closes.push(1));
    return { fixture, closes };
}

function closeButton(fixture: ComponentFixture<AuditValueViewerComponent>): HTMLButtonElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.audit-value-viewer__close')!;
}

function escape(): KeyboardEvent {
    return new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
}

describe('AuditValueViewerComponent Escape', () => {
    // The close button takes the focus on opening and shows its tooltip, which (listening on the body) would take
    // the first Escape before a document listener could see it: the viewer closes on Escape inside itself.
    it('closes the viewer once on the first Escape from its close button, and keeps it from the page', () => {
        const { fixture, closes } = render();
        const reachedDocument: KeyboardEvent[] = [];
        const listener = (event: Event): void => void reachedDocument.push(event as KeyboardEvent);
        document.addEventListener('keydown', listener);

        closeButton(fixture).dispatchEvent(escape());
        document.removeEventListener('keydown', listener);

        expect(closes).toHaveLength(1);
        expect(reachedDocument).toEqual([]);
    });

    it('closes the viewer on Escape while the focus is outside it', () => {
        const { closes } = render();

        document.body.dispatchEvent(escape());

        expect(closes).toHaveLength(1);
    });

    it('stays open when a control already used the Escape', () => {
        const { fixture, closes } = render();
        const event = escape();
        event.preventDefault();

        closeButton(fixture).dispatchEvent(event);

        expect(closes).toEqual([]);
    });
});
