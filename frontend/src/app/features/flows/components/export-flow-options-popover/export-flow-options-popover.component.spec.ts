import { OverlayContainer } from '@angular/cdk/overlay';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ExportFlowOptionsPopoverComponent, FlowExportOptions } from './export-flow-options-popover.component';

// jsdom has no ResizeObserver; the button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    imports: [ExportFlowOptionsPopoverComponent],
    template: `
        <button
            #origin
            type="button"
        >
            Export 2 flows
        </button>
        <app-export-flow-options-popover
            [origin]="origin"
            [open]="open()"
            (closed)="open.set(false)"
            (exportRequested)="requested.push($event)"
        />
    `,
})
class HostComponent {
    readonly open = signal(true);
    readonly requested: FlowExportOptions[] = [];
}

describe('ExportFlowOptionsPopoverComponent', () => {
    let fixture: ComponentFixture<HostComponent>;
    let overlay: HTMLElement;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        fixture = TestBed.createComponent(HostComponent);
        overlay = TestBed.inject(OverlayContainer).getContainerElement();
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    function includeKnowledgeBox(): HTMLInputElement {
        const option = [...overlay.querySelectorAll('label')].find((label) =>
            label.textContent?.includes('Include knowledge data')
        );
        return option!.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    }

    function clickExport(): void {
        const exportButton = [...overlay.querySelectorAll('button')].find(
            (button) => button.textContent?.trim() === 'Export'
        );
        exportButton!.click();
        fixture.detectChanges();
    }

    it('includes knowledge data by default', () => {
        expect(includeKnowledgeBox().checked).toBe(true);

        clickExport();

        expect(fixture.componentInstance.requested).toEqual([{ includeKnowledge: true }]);
    });

    it('exports without knowledge data once the box is cleared', () => {
        includeKnowledgeBox().click();
        fixture.detectChanges();

        clickExport();

        expect(fixture.componentInstance.requested).toEqual([{ includeKnowledge: false }]);
    });

    it('does not remember a cleared box the next time it opens', () => {
        includeKnowledgeBox().click();
        fixture.componentInstance.open.set(false);
        fixture.detectChanges();

        fixture.componentInstance.open.set(true);
        fixture.detectChanges();

        expect(includeKnowledgeBox().checked).toBe(true);
    });
});
