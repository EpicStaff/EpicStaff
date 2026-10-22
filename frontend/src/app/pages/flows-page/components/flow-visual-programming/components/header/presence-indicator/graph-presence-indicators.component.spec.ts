import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { EditorInfo } from '../../../../../../../features/flows/services/graph-collaboration.ws.service';
import { ProfileService } from '../../../../../../../services/auth/profile.service';
import { FakeObjectUrls } from '../../../../../../../shared/services/avatar-image/testing/fake-object-urls';
import { GraphPresenceIndicatorsComponent } from './graph-presence-indicators.component';

const EDITOR_AVATARS = '.avatar:not(.avatar--overflow)';
const ME: EditorInfo = { user_id: 1, display_name: 'Me Myself', avatar_url: '/api/users/1/avatar/?v=me' };

describe('GraphPresenceIndicatorsComponent', () => {
    let fixture: ComponentFixture<GraphPresenceIndicatorsComponent>;
    let httpMock: HttpTestingController;
    let objectUrls: FakeObjectUrls;

    beforeEach(() => {
        objectUrls = new FakeObjectUrls();
        objectUrls.install();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: ME.user_id }) } },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        objectUrls.restore();
    });

    function render(editors: EditorInfo[]): HTMLElement {
        fixture = TestBed.createComponent(GraphPresenceIndicatorsComponent);
        fixture.componentRef.setInput('editors', editors);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('loads the other editors’ avatars from the URL the backend sent, and initials for those without one', () => {
        const element = render([
            ME,
            { user_id: 2, display_name: 'Anna Yaroslavna', avatar_url: '/api/users/2/avatar/?v=a1' },
            { user_id: 3, display_name: 'Bohdan Khmelnytsky', avatar_url: null },
        ]);

        httpMock.expectOne('/api/users/2/avatar/?v=a1').flush(new Blob(['png'], { type: 'image/png' }));
        fixture.detectChanges();

        const avatars = Array.from(element.querySelectorAll(EDITOR_AVATARS));
        expect(avatars.length).toBe(2);
        expect(avatars[0].querySelector('img')?.getAttribute('src')).toBe('blob:fake-1');
        expect(avatars[1].querySelector('img')).toBeNull();
        expect(avatars[1].textContent?.trim()).toBe('BK');
    });

    it('shows three other editors and counts the rest', () => {
        const others: EditorInfo[] = [2, 3, 4, 5, 6].map((id) => ({ user_id: id, display_name: `User Number${id}` }));
        const element = render([ME, ...others]);

        expect(element.querySelectorAll(EDITOR_AVATARS).length).toBe(3);
        expect(element.querySelector('.avatar--overflow')?.textContent?.trim()).toBe('+2');
    });
});
