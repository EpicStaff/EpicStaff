import { ComponentFixture, TestBed } from '@angular/core/testing';

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
} {
    const fixture = TestBed.createComponent(CollectionDetailsSummaryComponent);
    fixture.componentRef.setInput('stats', stats);
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement };
}

function texts(host: HTMLElement, selector: string): string[] {
    return Array.from(host.querySelectorAll(selector)).map((element) => element.textContent?.trim() ?? '');
}

describe('CollectionDetailsSummaryComponent', () => {
    it('renders the quantitative parameters and memory capacity sections, ending with memory capacity', () => {
        const { host } = render();

        expect(texts(host, '.collection-summary__heading')).toEqual(['Quantitative parameters', 'Memory capacity']);
        expect(texts(host, '.collection-summary__label')).toEqual([
            'Number of files',
            'File types',
            'Size of collection',
            'Largest file',
            'Smallest file',
        ]);
        expect(texts(host, '.collection-summary__value')).toEqual(['6', '.pdf, .txt', '60 KB', '10 KB', '2 KB']);
        expect(host.querySelector('app-copy-button')).toBeNull();
    });

    it('shows a dash for the file types of an empty collection', () => {
        const { host } = render({ ...STATS, fileCount: 0, fileTypes: [] });

        expect(texts(host, '.collection-summary__value').slice(0, 2)).toEqual(['0', '—']);
    });
});
