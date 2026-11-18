import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ImportResult } from '../../../../core/models/import-result.model';
import { ImportResultDialogComponent } from './import-result-dialog.component';

// jsdom has no ResizeObserver; the summary slider only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('ImportResultDialogComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function render(importResult: ImportResult): HTMLElement {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: DIALOG_DATA, useValue: { importResult } },
            ],
        });
        const fixture = TestBed.createComponent(ImportResultDialogComponent);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    function summaryRows(element: HTMLElement): string[] {
        return [...element.querySelectorAll('.summary-item')].map((row) =>
            (row.textContent ?? '').replace(/\s+/g, ' ').trim()
        );
    }

    it('shows the imported knowledge collections as their own row', () => {
        const element = render({
            Flow: {
                total: 1,
                created: { count: 1, items: [{ id: 3, name: 'Orders' }] },
                reused: { count: 0, items: [] },
            },
            SourceCollection: {
                total: 2,
                created: { count: 1, items: [{ id: 8, name: 'Manuals' }] },
                reused: { count: 1, items: [{ id: 5, name: 'Policies' }] },
            },
        });

        expect(summaryRows(element)).toContain('2 Knowledge Collection');
        expect(element.querySelector('.entity-lists-section')?.textContent).toContain('Manuals');
    });
});
