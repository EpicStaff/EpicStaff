// Pins the open-in picker's behaviour: opens on trigger click, renders one row per allowed target
// labelled with LINKED_TO_LABEL_BY_TYPE, clicking a row emits the picked type and closes the
// overlay, and pressing Escape closes without emitting.
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { LINKED_TO_LABEL_BY_TYPE, LinkedToTargetType } from '../graph-rag-linked-to-picker/linked-to-targets';
import { GraphRagOpenInPickerComponent } from './graph-rag-open-in-picker.component';

@Component({
    template: `
        <app-graph-rag-open-in-picker
            [allowedTargets]="allowed()"
            (picked)="picked.set($event)"
        />
    `,
    imports: [GraphRagOpenInPickerComponent],
})
class TestHostComponent {
    allowed = signal<readonly LinkedToTargetType[]>(['relationships', 'communities', 'documents']);
    picked = signal<LinkedToTargetType | null>(null);
}

describe('GraphRagOpenInPickerComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;
    let host: HTMLElement;

    function trigger(): HTMLButtonElement {
        return host.querySelector<HTMLButtonElement>('.open-in-trigger')!;
    }

    function overlayRoot(): HTMLElement | null {
        return document.body.querySelector<HTMLElement>('.open-in-popover');
    }

    function rowButtons(): HTMLButtonElement[] {
        return Array.from(document.body.querySelectorAll<HTMLButtonElement>('.open-in-popover__row'));
    }

    function openPicker(): void {
        trigger().click();
        fixture.detectChanges();
    }

    beforeEach(async () => {
        await TestBed.configureTestingModule({ imports: [TestHostComponent] }).compileComponents();
        fixture = TestBed.createComponent(TestHostComponent);
        host = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    it('opens the overlay when the trigger is clicked', () => {
        expect(overlayRoot()).toBeNull();

        openPicker();

        expect(overlayRoot()).not.toBeNull();
    });

    it('renders one row per allowed target with the correct label', () => {
        openPicker();

        const labels = rowButtons().map((button) => button.textContent?.trim() ?? '');
        expect(labels).toEqual([
            LINKED_TO_LABEL_BY_TYPE['relationships'],
            LINKED_TO_LABEL_BY_TYPE['communities'],
            LINKED_TO_LABEL_BY_TYPE['documents'],
        ]);
    });

    it('emits the picked type and closes the overlay when a row is clicked', () => {
        openPicker();

        rowButtons()[1].click();
        fixture.detectChanges();

        expect(fixture.componentInstance.picked()).toBe('communities');
        expect(overlayRoot()).toBeNull();
    });

    it('closes without emitting when Escape is pressed', () => {
        openPicker();

        const popover = overlayRoot()!;
        popover.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        fixture.detectChanges();

        expect(fixture.componentInstance.picked()).toBeNull();
        expect(overlayRoot()).toBeNull();
    });

    it('renders the no-options state when opened with an empty allowed list', () => {
        fixture.componentInstance.allowed.set([]);
        fixture.detectChanges();

        openPicker();

        expect(overlayRoot()?.textContent?.trim()).toBe('No options');
        expect(rowButtons().length).toBe(0);
    });
});
