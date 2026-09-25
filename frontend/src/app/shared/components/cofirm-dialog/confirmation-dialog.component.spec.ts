import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfirmationDialogComponent, ConfirmationDialogData } from './confirmation-dialog.component';

const BASE_DATA: ConfirmationDialogData = {
    title: 'Delete organization',
    message: '<strong>Acme</strong> will be deleted.',
    type: 'danger',
};

let dialogRef: { close: ReturnType<typeof vi.fn> };

function render(data: ConfirmationDialogData): ComponentFixture<ConfirmationDialogComponent> {
    dialogRef = { close: vi.fn() };
    TestBed.configureTestingModule({
        imports: [ConfirmationDialogComponent],
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: DIALOG_DATA, useValue: data },
            { provide: DialogRef, useValue: dialogRef },
        ],
    });
    const fixture = TestBed.createComponent(ConfirmationDialogComponent);
    fixture.detectChanges();
    return fixture;
}

function query(fixture: ComponentFixture<ConfirmationDialogComponent>, selector: string): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector(selector);
}

describe('ConfirmationDialogComponent actions', () => {
    it('closes with confirm when the confirm button is clicked', () => {
        const fixture = render(BASE_DATA);

        (query(fixture, '.confirm-button') as HTMLButtonElement).click();

        expect(dialogRef.close).toHaveBeenCalledWith('confirm');
    });

    it('closes with cancel when the cancel button is clicked', () => {
        const fixture = render(BASE_DATA);

        (query(fixture, '.cancel-button') as HTMLButtonElement).click();

        expect(dialogRef.close).toHaveBeenCalledWith('cancel');
    });

    it('closes with close when the close button is clicked', () => {
        const fixture = render(BASE_DATA);

        (query(fixture, 'app-icon-button.close-button') as HTMLElement).click();

        expect(dialogRef.close).toHaveBeenCalledWith('close');
    });
});

describe('ConfirmationDialogComponent breakdown', () => {
    const breakdownData: ConfirmationDialogData = {
        ...BASE_DATA,
        breakdown: {
            title: 'Resources to delete',
            items: [
                { label: 'sessions', count: 20 },
                { label: 'knowledge documents', count: 12 },
                { label: 'agents', count: 6 },
            ],
        },
    };

    it('renders no breakdown when none is passed', () => {
        const fixture = render(BASE_DATA);

        expect(query(fixture, '.breakdown')).toBeNull();
    });

    it('renders no breakdown when it has no items', () => {
        const fixture = render({ ...BASE_DATA, breakdown: { title: 'Resources to delete', items: [] } });

        expect(query(fixture, '.breakdown')).toBeNull();
    });

    it('shows the title and the total of all counts in the header', () => {
        const fixture = render(breakdownData);

        expect(query(fixture, '.breakdown-title')?.textContent?.trim()).toBe('Resources to delete');
        expect(query(fixture, '.breakdown-total')?.textContent?.trim()).toBe('38');
    });

    it('points the toggle at the list it controls', () => {
        const fixture = render(breakdownData);
        const listId = query(fixture, '.breakdown-list')?.id;

        expect(listId).toBeTruthy();
        expect(query(fixture, '.breakdown-header')?.getAttribute('aria-controls')).toBe(listId);
    });

    it('is collapsed by default', () => {
        const fixture = render(breakdownData);

        expect(query(fixture, '.breakdown-header')?.getAttribute('aria-expanded')).toBe('false');
        expect(query(fixture, '.grid-collapsible')?.classList.contains('expanded')).toBe(false);
    });

    it('toggles open and closed when the header is clicked', () => {
        const fixture = render(breakdownData);
        const header = query(fixture, '.breakdown-header') as HTMLButtonElement;

        header.click();
        fixture.detectChanges();

        expect(header.getAttribute('aria-expanded')).toBe('true');
        expect(query(fixture, '.grid-collapsible')?.classList.contains('expanded')).toBe(true);

        header.click();
        fixture.detectChanges();

        expect(header.getAttribute('aria-expanded')).toBe('false');
        expect(query(fixture, '.grid-collapsible')?.classList.contains('expanded')).toBe(false);
    });

    it('lists every item with its label and count in the given order', () => {
        const fixture = render(breakdownData);
        const rows = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.breakdown-item'));

        expect(
            rows.map((row) => [
                row.querySelector('.breakdown-item-label')?.textContent?.trim(),
                row.querySelector('.breakdown-item-count')?.textContent?.trim(),
            ])
        ).toEqual([
            ['sessions', '20'],
            ['knowledge documents', '12'],
            ['agents', '6'],
        ]);
    });
});
