import { TestBed } from '@angular/core/testing';
import { UserSummary } from '@shared/models';

import { AuthorshipFooterComponent } from './authorship-footer.component';

const IVAN: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: 'https://cdn.example/ivan.png' };
const OLGA: UserSummary = { id: 2, display_name: 'Olga Mageria', avatar_url: null };
// Built from local-time parts so the expectation holds in any time zone the tests run in.
const CREATED_AT = new Date(2026, 2, 12, 13, 28, 23).toISOString();
const EDITED_AT = new Date(2026, 2, 13, 9, 5, 0).toISOString();

function render(
    createdBy: UserSummary | null,
    createdAt: string | null,
    lastEditedBy: UserSummary | null,
    lastEditedAt: string | null
): HTMLElement {
    const fixture = TestBed.createComponent(AuthorshipFooterComponent);
    fixture.componentRef.setInput('createdBy', createdBy);
    fixture.componentRef.setInput('createdAt', createdAt);
    fixture.componentRef.setInput('lastEditedBy', lastEditedBy);
    fixture.componentRef.setInput('lastEditedAt', lastEditedAt);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

const textOf = (element: Element | null): string => element?.textContent?.replace(/\s+/g, ' ').trim() ?? '';

/** Each column as the viewer reads it: the label and name on one line, the date and time below. */
function columns(host: HTMLElement): string[][] {
    return Array.from(host.querySelectorAll('.authorship-footer__column')).map((column) => [
        textOf(column.querySelector('.authorship-footer__user')),
        textOf(column.querySelector('.authorship-footer__when')),
    ]);
}

describe('AuthorshipFooterComponent', () => {
    it('shows "Created" and "Edited" lines with the name, date and time of each', () => {
        const host = render(IVAN, CREATED_AT, OLGA, EDITED_AT);

        expect(columns(host)).toEqual([
            ['Created by Ivan Bohun', 'Mar 12, 2026, 13:28:23'],
            ['Edited by Olga Mageria', 'Mar 13, 2026, 09:05:00'],
        ]);
    });

    it('shows no avatar, even for a user who has one', () => {
        const host = render(IVAN, CREATED_AT, IVAN, EDITED_AT);

        expect(host.querySelector('app-user-avatar')).toBeNull();
        expect(host.querySelector('img')).toBeNull();
    });

    it('shows "Unnamed user" for a user without a display name', () => {
        const unnamed: UserSummary = { id: 3, display_name: null, avatar_url: null };

        expect(columns(render(unnamed, CREATED_AT, unnamed, EDITED_AT))).toEqual([
            ['Created by Unnamed user', 'Mar 12, 2026, 13:28:23'],
            ['Edited by Unnamed user', 'Mar 13, 2026, 09:05:00'],
        ]);
    });

    it('shows a dash for an unknown user, keeping the moment when it is known', () => {
        expect(columns(render(null, CREATED_AT, null, EDITED_AT))).toEqual([
            ['Created by —', 'Mar 12, 2026, 13:28:23'],
            ['Edited by —', 'Mar 13, 2026, 09:05:00'],
        ]);
    });

    it('shows a dash for a moment that was never recorded', () => {
        expect(columns(render(IVAN, null, OLGA, null))).toEqual([
            ['Created by Ivan Bohun', '—'],
            ['Edited by Olga Mageria', '—'],
        ]);
    });

    it('shows dashes when nothing is known, e.g. for a node not saved yet', () => {
        expect(columns(render(null, null, null, null))).toEqual([
            ['Created by —', '—'],
            ['Edited by —', '—'],
        ]);
    });
});
