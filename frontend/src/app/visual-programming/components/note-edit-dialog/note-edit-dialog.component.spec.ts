import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { AuthorshipDetailsSource } from '@shared/components';
import { NodeType } from '@shared/models';
import { Subject } from 'rxjs';

import { GraphNoteModel } from '../../core/models/node.model';
import { NoteEditDialogComponent, NoteEditDialogData } from './note-edit-dialog.component';

const NOTE: GraphNoteModel = {
    id: 'note-1',
    backendId: 3,
    type: NodeType.NOTE,
    node_name: 'Note',
    data: { content: 'hello' },
    position: { x: 0, y: 0 },
    ports: [],
    color: '',
    icon: '',
    size: { width: 200, height: 100 },
    input_map: {},
    output_variable_path: null,
};

// Built from local-time parts so the expectation holds in any time zone the tests run in.
const AUTHORSHIP: AuthorshipDetailsSource = {
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: 'https://cdn.example/ivan.png' },
    created_at: new Date(2026, 2, 12, 13, 28, 23).toISOString(),
    last_edited_by: null,
    last_edited_at: new Date(2026, 2, 13, 9, 5, 0).toISOString(),
};

function render(data: NoteEditDialogData): HTMLElement {
    TestBed.configureTestingModule({
        providers: [
            { provide: DIALOG_DATA, useValue: data },
            { provide: DialogRef, useValue: { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() } },
        ],
    });
    const fixture = TestBed.createComponent(NoteEditDialogComponent);
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

describe('NoteEditDialogComponent', () => {
    it('shows who created and who last edited the note in a footer below the text', () => {
        const host = render({ node: NOTE, authorship: AUTHORSHIP });
        const footer = host.querySelector('.dialog-content + app-authorship-footer');

        expect(footer).not.toBeNull();
        expect(footerColumns(footer!)).toEqual([
            ['Created by Ivan Bohun', 'Mar 12, 2026, 13:28:23'],
            ['Edited by —', 'Mar 13, 2026, 09:05:00'],
        ]);
        expect(footer!.querySelector('app-user-avatar')).toBeNull();
    });
});
