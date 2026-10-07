import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, input, output } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthorshipDetailsSource, JsonEditorComponent } from '@shared/components';
import { Subject } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { FLOW_EDITOR_PREVIEW } from '../../core/providers/flow-editor-preview.token';
import { DomainDialogComponent, DomainDialogData } from './domain-dialog.component';

// The real editor is Monaco, which jsdom cannot run; the footer is all this spec looks at.
@Component({ selector: 'app-json-editor', template: '' })
class JsonEditorStubComponent {
    readonly jsonData = input('');
    readonly readonly = input(false);
    readonly fullHeight = input(false);
    readonly jsonChange = output<string>();
    readonly validationChange = output<boolean>();
    readonly editorReady = output<unknown>();
}

// Built from local-time parts so the expectation holds in any time zone the tests run in.
const AUTHORSHIP: AuthorshipDetailsSource = {
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: 'https://cdn.example/ivan.png' },
    created_at: new Date(2026, 2, 12, 13, 28, 23).toISOString(),
    last_edited_by: { id: 2, display_name: 'Olga Mageria', avatar_url: null },
    last_edited_at: null,
};

function render(data: DomainDialogData, isPreview: boolean): HTMLElement {
    TestBed.configureTestingModule({
        providers: [
            { provide: DIALOG_DATA, useValue: data },
            {
                provide: DialogRef,
                useValue: {
                    close: vi.fn(),
                    backdropClick: new Subject<MouseEvent>(),
                    keydownEvents: new Subject<KeyboardEvent>(),
                },
            },
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => true } },
        ],
    });
    TestBed.overrideComponent(DomainDialogComponent, {
        remove: { imports: [JsonEditorComponent] },
        add: { imports: [JsonEditorStubComponent] },
    });
    const fixture = TestBed.createComponent(DomainDialogComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

const textOf = (element: Element | null): string => element?.textContent?.replace(/\s+/g, ' ').trim() ?? '';

/** Each footer column as the viewer reads it: the label and name on one line, the date and time below. */
const footerColumns = (footer: Element): string[][] =>
    Array.from(footer.querySelectorAll('.authorship-footer__column')).map((column) => [
        textOf(column.querySelector('.authorship-footer__user')),
        textOf(column.querySelector('.authorship-footer__when')),
    ]);

describe('DomainDialogComponent', () => {
    it.each([
        ['an editable flow', false],
        ['a version preview', true],
    ])('shows who created and who last edited the Start node in a footer below the editor, in %s', (_, isPreview) => {
        const host = render({ initialData: {}, authorship: AUTHORSHIP }, isPreview);
        const footer = host.querySelector('.dialog-container > .dialog-content + app-authorship-footer');

        expect(footer).not.toBeNull();
        expect(footerColumns(footer!)).toEqual([
            ['Created by Ivan Bohun', 'Mar 12, 2026, 13:28:23'],
            ['Edited by Olga Mageria', '—'],
        ]);
        expect(footer!.querySelector('app-user-avatar')).toBeNull();
    });
});
