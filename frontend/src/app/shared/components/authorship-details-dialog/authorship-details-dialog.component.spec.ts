import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { UserSummary } from '@shared/models';

import {
    AuthorshipDetailsDialogComponent,
    AuthorshipDetailsDialogData,
    AuthorshipDetailsSource,
} from './authorship-details-dialog.component';
import { AuthorshipDetailsDialogService } from './authorship-details-dialog.service';

const OWNER: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: null };
const EDITOR: UserSummary = { id: 2, display_name: 'Olga Mageria', avatar_url: null };

const SOURCE: AuthorshipDetailsSource = {
    created_by: OWNER,
    created_at: '2026-03-12T13:28:23Z',
    last_edited_by: EDITOR,
    last_edited_at: '2026-03-13T09:00:00Z',
};

describe('AuthorshipDetailsDialogComponent', () => {
    let dialogRef: { close: ReturnType<typeof vi.fn> };

    function render(data: AuthorshipDetailsDialogData): ComponentFixture<AuthorshipDetailsDialogComponent> {
        dialogRef = { close: vi.fn() };
        TestBed.configureTestingModule({
            imports: [AuthorshipDetailsDialogComponent],
            providers: [
                { provide: DIALOG_DATA, useValue: data },
                { provide: DialogRef, useValue: dialogRef },
            ],
        });
        const fixture = TestBed.createComponent(AuthorshipDetailsDialogComponent);
        fixture.detectChanges();
        return fixture;
    }

    function text(fixture: ComponentFixture<AuthorshipDetailsDialogComponent>, selector: string): string[] {
        const host = fixture.nativeElement as HTMLElement;
        return Array.from(host.querySelectorAll(selector)).map((element) => element.textContent?.trim() ?? '');
    }

    it('renders the given title under the given heading id', () => {
        const fixture = render({ ...SOURCE, title: 'Tool Details', titleId: 'details-title-1' });

        expect(text(fixture, '.authorship-details-dialog__title')).toEqual(['Tool Details']);
        expect((fixture.nativeElement as HTMLElement).querySelector('.authorship-details-dialog__title')?.id).toBe(
            'details-title-1'
        );
    });

    it('shows the owner and the last editor from the dialog data', () => {
        const fixture = render({ ...SOURCE, title: 'Configuration Details', titleId: 'details-title-1' });

        expect(text(fixture, '.authorship-details__label')).toEqual(['Owner', 'Last editor']);
        expect(text(fixture, '.authorship-details__name')).toEqual(['Ivan Bohun', 'Olga Mageria']);
    });

    it('closes when the close button is clicked', () => {
        const fixture = render({ ...SOURCE, title: 'Tool Details', titleId: 'details-title-1' });

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('.authorship-details-dialog__close')!
            .click();

        expect(dialogRef.close).toHaveBeenCalledOnce();
    });
});

describe('AuthorshipDetailsDialogService', () => {
    function openDialog(): { dialog: { open: ReturnType<typeof vi.fn> }; service: AuthorshipDetailsDialogService } {
        const dialog = { open: vi.fn() };
        TestBed.configureTestingModule({ providers: [{ provide: Dialog, useValue: dialog }] });
        return { dialog, service: TestBed.inject(AuthorshipDetailsDialogService) };
    }

    it('opens the dialog with the title and only the authorship fields of the resource', () => {
        const { dialog, service } = openDialog();
        const resource = { ...SOURCE, id: 5, name: 'Super Test Tool', is_favorite: true };

        service.open('Tool Details', resource);

        expect(dialog.open).toHaveBeenCalledWith(AuthorshipDetailsDialogComponent, {
            ariaLabelledBy: expect.any(String),
            restoreFocus: true,
            data: { ...SOURCE, title: 'Tool Details', titleId: expect.any(String) },
        });
    });

    it('restores focus on close to the given element instead of the one focused on open', () => {
        const { dialog, service } = openDialog();
        const trigger = document.createElement('button');

        service.open('Tool Details', SOURCE, trigger);

        expect(dialog.open).toHaveBeenCalledWith(
            AuthorshipDetailsDialogComponent,
            expect.objectContaining({ restoreFocus: trigger })
        );
    });

    it('names the dialog by its heading, with a fresh heading id on every open', () => {
        const { dialog, service } = openDialog();

        service.open('Tool Details', SOURCE);
        service.open('Configuration Details', SOURCE);

        const [first, second] = dialog.open.mock.calls.map(
            ([, config]) => config as { ariaLabelledBy: string; data: AuthorshipDetailsDialogData }
        );
        expect(first.ariaLabelledBy).toBe(first.data.titleId);
        expect(second.ariaLabelledBy).toBe(second.data.titleId);
        expect(first.data.titleId).not.toBe(second.data.titleId);
    });
});
