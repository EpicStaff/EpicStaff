import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ToastService } from '../../../../services/notifications';
import { CollectionStats } from '../../helpers/collection-stats.util';
import { CollectionDetailsSummaryComponent } from './collection-details-summary.component';

const STATS: CollectionStats = {
    fileCount: 6,
    fileTypes: ['pdf', 'txt'],
    totalSize: '60 KB',
    largestFileSize: '10 KB',
    smallestFileSize: '2 KB',
};

function render(stats: CollectionStats = STATS): {
    fixture: ComponentFixture<CollectionDetailsSummaryComponent>;
    host: HTMLElement;
    toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
} {
    const toast = { success: vi.fn(), error: vi.fn() };
    TestBed.configureTestingModule({ providers: [{ provide: ToastService, useValue: toast }] });
    const fixture = TestBed.createComponent(CollectionDetailsSummaryComponent);
    fixture.componentRef.setInput('stats', stats);
    fixture.componentRef.setInput('collectionId', 42);
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, toast };
}

function texts(host: HTMLElement, selector: string): string[] {
    return Array.from(host.querySelectorAll(selector)).map((element) => element.textContent?.trim() ?? '');
}

describe('CollectionDetailsSummaryComponent', () => {
    afterEach(() => Reflect.deleteProperty(navigator, 'clipboard'));

    it('renders the quantitative parameters, memory capacity and knowledge source path sections', () => {
        const { host } = render();

        expect(texts(host, '.collection-summary__heading')).toEqual([
            'Quantitative parameters',
            'Memory capacity',
            'Knowledge source path',
        ]);
        expect(texts(host, '.collection-summary__label')).toEqual([
            'Number of files',
            'File types',
            'Size of collection',
            'Largest file',
            'Smallest file',
        ]);
        expect(texts(host, '.collection-summary__value')).toEqual(['6', '.pdf, .txt', '60 KB', '10 KB', '2 KB']);
        expect(texts(host, '.collection-summary__path-value')).toEqual(['42']);
    });

    it('shows a dash for the file types of an empty collection', () => {
        const { host } = render({ ...STATS, fileCount: 0, fileTypes: [] });

        expect(texts(host, '.collection-summary__value').slice(0, 2)).toEqual(['0', '—']);
    });

    it('copies the collection id with the app toast', async () => {
        const writeText = vi.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        const { host, toast } = render();

        host.querySelector<HTMLButtonElement>('app-copy-button button[aria-label="Copy collection ID"]')!.click();
        await Promise.resolve();
        await Promise.resolve();

        expect(writeText).toHaveBeenCalledWith('42');
        expect(toast.success).toHaveBeenCalledOnce();
    });
});
