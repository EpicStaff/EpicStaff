import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MemoriesSidebarComponent } from './memory-sidebar.component';

function renderOpen(): { fixture: ComponentFixture<MemoriesSidebarComponent>; closes: number[] } {
    const fixture = TestBed.createComponent(MemoriesSidebarComponent);
    fixture.componentRef.setInput('isOpen', true);
    fixture.detectChanges();
    const closes: number[] = [];
    fixture.componentInstance.close.subscribe(() => closes.push(1));
    return { fixture, closes };
}

function closeButton(fixture: ComponentFixture<MemoriesSidebarComponent>): HTMLButtonElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.close-button')!;
}

function escape(): KeyboardEvent {
    return new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
}

describe('MemoriesSidebarComponent Escape', () => {
    // The close button takes the focus on opening and shows its tooltip, which (listening on the body) would take
    // the first Escape before a document listener could see it: the sidebar closes on Escape inside itself.
    it('closes the sidebar on the first Escape from its focused close button, and keeps it from the page', () => {
        const { fixture, closes } = renderOpen();
        const reachedDocument: KeyboardEvent[] = [];
        const listener = (event: Event): void => void reachedDocument.push(event as KeyboardEvent);
        document.addEventListener('keydown', listener);

        closeButton(fixture).dispatchEvent(escape());
        document.removeEventListener('keydown', listener);

        expect(closes).toHaveLength(1);
        expect(reachedDocument).toEqual([]);
    });

    it('stays open when a control inside already used the Escape', () => {
        const { fixture, closes } = renderOpen();
        const event = escape();
        event.preventDefault();

        closeButton(fixture).dispatchEvent(event);

        expect(closes).toEqual([]);
    });
});
