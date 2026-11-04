import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CollapseOnOverflowDirective } from './collapse-on-overflow.directive';

// jsdom lays nothing out. A fake flex row stands in: each button is a 36px icon, plus its label while shown; once
// they need more than their row has, the shown labels share the shortfall, as flex shrinks all of them. A label
// freed of its limits takes its full width.
const ICON_WIDTH = 36;
const LABEL_WIDTHS: Record<string, number> = { Settings: 40, Pause: 60, Test: 30, Run: 30 };

let rowWidths = new Map<Element, number>();
let resizeCallbacks: ResizeObserverCallback[] = [];

class ResizeObserverStub {
    constructor(callback: ResizeObserverCallback) {
        resizeCallbacks.push(callback);
    }
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    imports: [CollapseOnOverflowDirective],
    template: `
        @for (row of rows; track $index) {
            <div class="row">
                @for (label of row; track label) {
                    <button
                        [appCollapseOnOverflow]="label !== fixedLabel"
                        collapseOnOverflowTarget=".label"
                        collapseOnOverflowClass="icon-only"
                        (collapseOnOverflowChange)="changes.push(label + ':' + $event)"
                    >
                        <span class="label">{{ label }}</span>
                    </button>
                }
            </div>
        }
    `,
})
class HostComponent {
    rows = [['Settings', 'Pause', 'Test']];
    fixedLabel = '';
    changes: string[] = [];
}

function labelWidth(button: Element): number {
    return LABEL_WIDTHS[button.textContent!.trim()];
}

function rowsOf(fixture: ComponentFixture<HostComponent>): HTMLElement[] {
    return [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.row')];
}

function fakeLayout(fixture: ComponentFixture<HostComponent>): void {
    for (const row of rowsOf(fixture)) {
        const buttons = [...row.querySelectorAll('button')];
        const neededWidth = (): number =>
            buttons.reduce(
                (total, button) =>
                    total + ICON_WIDTH + (button.classList.contains('icon-only') ? 0 : labelWidth(button)),
                0
            );

        const shownCount = (): number => buttons.filter((button) => !button.classList.contains('icon-only')).length;

        for (const button of buttons) {
            const label = button.querySelector<HTMLElement>('.label')!;
            label.getBoundingClientRect = () => {
                const shortfall = Math.max(0, neededWidth() - (rowWidths.get(row) ?? 0));
                const squeeze = label.style.width === 'max-content' ? 0 : shortfall / shownCount();
                return { width: labelWidth(button) - squeeze } as DOMRect;
            };
        }
    }
}

function resizeRow(row: HTMLElement, width: number): void {
    rowWidths.set(row, width);
    const entries = [{ target: row } as unknown as ResizeObserverEntry];
    resizeCallbacks.forEach((callback) => callback(entries, {} as ResizeObserver));
}

function shownLabels(row: HTMLElement): string[] {
    return [...row.querySelectorAll('button:not(.icon-only)')].map((button) => button.textContent!.trim());
}

describe('CollapseOnOverflowDirective', () => {
    let fixture: ComponentFixture<HostComponent>;

    function render(configure: (host: HostComponent) => void = () => undefined): HTMLElement[] {
        fixture = TestBed.createComponent(HostComponent);
        configure(fixture.componentInstance);
        fixture.detectChanges();
        fakeLayout(fixture);
        return rowsOf(fixture);
    }

    beforeEach(() => {
        rowWidths = new Map();
        resizeCallbacks = [];
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        // Frames never come: whatever shows was settled in the resize callback itself.
        vi.stubGlobal('requestAnimationFrame', () => 1);
        vi.stubGlobal('cancelAnimationFrame', () => undefined);
    });

    afterEach(() => {
        fixture.destroy();
        vi.unstubAllGlobals();
    });

    it.each([
        { width: 1000, shown: ['Settings', 'Pause', 'Test'] },
        { width: 238, shown: ['Settings', 'Pause', 'Test'] },
        // A pixel short: each label a third of one short, already an ellipsis.
        { width: 237, shown: ['Pause', 'Test'] },
        { width: 198, shown: ['Pause', 'Test'] },
        // Settings alone would fit beside Test here; it stays an icon so no label shows before one.
        { width: 197, shown: ['Test'] },
        { width: 138, shown: ['Test'] },
        { width: 137, shown: [] },
    ])('at $width px, collapses from the first button and shows the labels that fit: $shown', ({ width, shown }) => {
        const [row] = render();

        resizeRow(row, width);

        expect(shownLabels(row)).toEqual(shown);
    });

    it('settles at the same labels whether the row grew or shrank to its width', () => {
        const [row] = render();
        resizeRow(row, 1000);
        resizeRow(row, 208);
        const afterShrinking = shownLabels(row);

        resizeRow(row, 100);
        resizeRow(row, 208);

        expect(afterShrinking).toEqual(['Pause', 'Test']);
        expect(shownLabels(row)).toEqual(['Pause', 'Test']);
    });

    it('keeps rows under different parents apart: one running short leaves the other as it is', () => {
        const [wide, narrow] = render(
            (host) =>
                (host.rows = [
                    ['Test', 'Run'],
                    ['Settings', 'Pause'],
                ])
        );
        resizeRow(wide, 1000);

        resizeRow(narrow, 100);

        expect(shownLabels(narrow)).toEqual([]);
        expect(shownLabels(wide)).toEqual(['Test', 'Run']);
    });

    it('keeps the label of a button that may not collapse, and gives the others what is left', () => {
        const [row] = render((host) => (host.fixedLabel = 'Settings'));

        resizeRow(row, 100);

        expect(shownLabels(row)).toEqual(['Settings']);
    });

    it('tells each change once, and nothing while the outcome stays the same', () => {
        const [row] = render();

        resizeRow(row, 1000);
        resizeRow(row, 900);
        resizeRow(row, 230);
        resizeRow(row, 220);

        expect(fixture.componentInstance.changes).toEqual(['Settings:true']);
    });
});
