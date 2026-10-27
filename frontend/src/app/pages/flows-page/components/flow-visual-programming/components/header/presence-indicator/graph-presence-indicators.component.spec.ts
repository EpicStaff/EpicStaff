import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ProfileService } from '../../../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../../../services/config';
import { GraphPresenceIndicatorsComponent } from './graph-presence-indicators.component';

describe('GraphPresenceIndicatorsComponent', () => {
    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [GraphPresenceIndicatorsComponent],
            providers: [
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 1 }) } },
                { provide: ConfigService, useValue: { apiUrl: 'http://localhost/api/' } },
            ],
        });
    });

    const editor = { user_id: 2, display_name: 'Ivan Bohun', avatar_url: '/media/avatars/2.png?e=1&s=expired' };

    function renderWithFailedAvatar() {
        const fixture = TestBed.createComponent(GraphPresenceIndicatorsComponent);
        fixture.componentRef.setInput('editors', [editor]);
        fixture.detectChanges();
        const element: HTMLElement = fixture.nativeElement;
        element.querySelector('img')!.dispatchEvent(new Event('error'));
        fixture.detectChanges();
        return { fixture, element };
    }

    it("shows the editor's initials on their colour when their avatar image fails to load", () => {
        const { element } = renderWithFailedAvatar();
        const avatar = element.querySelector<HTMLElement>('.avatar')!;

        expect(element.querySelector('img')).toBeNull();
        expect(avatar.textContent?.trim()).toBe('IB');
        expect(avatar.style.backgroundColor).toBeTruthy();
        expect(avatar.style.backgroundColor).not.toBe('transparent');
    });

    it('shows the image again when the same editor arrives with a fresh avatar link', () => {
        const { fixture, element } = renderWithFailedAvatar();

        fixture.componentRef.setInput('editors', [{ ...editor, avatar_url: '/media/avatars/2.png?e=2&s=fresh' }]);
        fixture.detectChanges();

        expect(element.querySelector('img')?.getAttribute('src')).toBe(
            'http://localhost/media/avatars/2.png?e=2&s=fresh'
        );
    });
});
