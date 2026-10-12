import { ComponentFixture, TestBed } from '@angular/core/testing';
import { UserSummary } from '@shared/models';

import { AuthorshipDetailsComponent } from './authorship-details.component';

const IVAN: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: null };
const LOCAL_MOMENT = new Date(2026, 2, 12, 13, 28, 23).toISOString();

interface RenderedColumn {
    name: string;
    hasAvatar: boolean;
    timestamp: string;
}

function render(
    owner: UserSummary | null,
    createdAt: string | null,
    lastEditor: UserSummary | null,
    lastEditedAt: string | null
): RenderedColumn[] {
    const fixture: ComponentFixture<AuthorshipDetailsComponent> = TestBed.createComponent(AuthorshipDetailsComponent);
    fixture.componentRef.setInput('owner', owner);
    fixture.componentRef.setInput('createdAt', createdAt);
    fixture.componentRef.setInput('lastEditor', lastEditor);
    fixture.componentRef.setInput('lastEditedAt', lastEditedAt);
    fixture.detectChanges();
    const host = fixture.nativeElement as HTMLElement;
    return Array.from(host.querySelectorAll<HTMLElement>('.authorship-details__column')).map((column) => {
        const name = column.querySelector<HTMLElement>('.authorship-details__name')!;
        return {
            name: name.textContent?.trim() ?? '',
            hasAvatar: column.querySelector('app-user-avatar') !== null,
            timestamp:
                column.querySelector('.authorship-details__timestamp')?.textContent?.replace(/\s+/g, ' ').trim() ?? '',
        };
    });
}

describe('AuthorshipDetailsComponent', () => {
    it('shows both users with their avatars and moments', () => {
        expect(render(IVAN, LOCAL_MOMENT, IVAN, LOCAL_MOMENT)).toEqual([
            { name: 'Ivan Bohun', hasAvatar: true, timestamp: 'Mar 12, 2026, 13:28:23' },
            { name: 'Ivan Bohun', hasAvatar: true, timestamp: 'Mar 12, 2026, 13:28:23' },
        ]);
    });

    it('shows a dash without an avatar for a missing user, with the moment when it is known', () => {
        expect(render(null, LOCAL_MOMENT, null, LOCAL_MOMENT)).toEqual([
            { name: '—', hasAvatar: false, timestamp: 'Mar 12, 2026, 13:28:23' },
            { name: '—', hasAvatar: false, timestamp: 'Mar 12, 2026, 13:28:23' },
        ]);
    });

    it('shows a dash without an avatar when neither the user nor the moment is known', () => {
        expect(render(null, null, null, null)).toEqual([
            { name: '—', hasAvatar: false, timestamp: '—' },
            { name: '—', hasAvatar: false, timestamp: '—' },
        ]);
    });

    it('shows the user with a dash for a moment that was never recorded', () => {
        expect(render(IVAN, null, IVAN, null)).toEqual([
            { name: 'Ivan Bohun', hasAvatar: true, timestamp: '—' },
            { name: 'Ivan Bohun', hasAvatar: true, timestamp: '—' },
        ]);
    });
});
