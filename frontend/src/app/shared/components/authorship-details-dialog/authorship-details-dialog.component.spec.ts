import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, input } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { UserSummary } from '@shared/models';

import {
    AuthorshipDetailsDialogComponent,
    AuthorshipDetailsDialogData,
    AuthorshipDetailsExtraContent,
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

@Component({
    selector: 'app-test-extra-details',
    template: `<p class="extra-details">{{ fileCount() }} files</p>`,
})
class ExtraDetailsComponent {
    readonly fileCount = input.required<number>();
}

const EXTRA_CONTENT: AuthorshipDetailsExtraContent<ExtraDetailsComponent> = {
    component: ExtraDetailsComponent,
    inputs: { fileCount: 6 },
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

    it('renders the extra content, with its inputs, below the authorship block', () => {
        const fixture = render({ ...SOURCE, title: 'Collection Details', titleId: 'id', extraContent: EXTRA_CONTENT });
        const host = fixture.nativeElement as HTMLElement;

        expect(text(fixture, '.authorship-details-dialog__extra .extra-details')).toEqual(['6 files']);
        expect(host.querySelector('app-authorship-details + .authorship-details-dialog__extra')).not.toBeNull();
    });

    it('renders no extra section without extra content', () => {
        const fixture = render({ ...SOURCE, title: 'Tool Details', titleId: 'details-title-1' });

        expect((fixture.nativeElement as HTMLElement).querySelector('.authorship-details-dialog__extra')).toBeNull();
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

    it('passes the extra content into the dialog', () => {
        const { dialog, service } = openDialog();
        const trigger = document.createElement('button');

        service.open('Collection Details', SOURCE, trigger, EXTRA_CONTENT);

        expect(dialog.open).toHaveBeenCalledWith(AuthorshipDetailsDialogComponent, {
            ariaLabelledBy: expect.any(String),
            restoreFocus: trigger,
            data: { ...SOURCE, title: 'Collection Details', titleId: expect.any(String), extraContent: EXTRA_CONTENT },
        });
    });

    // Compile-time checks: the build fails if any `@ts-expect-error` below stops being an error.
    it('type-checks the extra content inputs against the signal inputs of the component', () => {
        const { dialog, service } = openDialog();
        const rejected: AuthorshipDetailsExtraContent<ExtraDetailsComponent>[] = [
            // @ts-expect-error -- wrong value type
            { component: ExtraDetailsComponent, inputs: { fileCount: '6' } },
            // @ts-expect-error -- unknown input
            { component: ExtraDetailsComponent, inputs: { fileCount: 6, fileTypes: [] } },
            // @ts-expect-error -- missing input
            { component: ExtraDetailsComponent, inputs: {} },
        ];

        service.open('Collection Details', SOURCE, undefined, {
            component: ExtraDetailsComponent,
            // @ts-expect-error -- the service infers the component from `component` and checks `inputs` against it
            inputs: { count: 6 },
        });

        expect(rejected).toHaveLength(3);
        expect(dialog.open).toHaveBeenCalledOnce();
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
