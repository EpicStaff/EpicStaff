import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { EditorInfo } from '../../../../../../../features/flows/services/graph-collaboration.ws.service';
import { FakeObjectUrls } from '../../../../../../../shared/services/avatar-image/testing/fake-object-urls';
import { GraphPresenceAvatarComponent } from './graph-presence-avatar.component';

describe('GraphPresenceAvatarComponent', () => {
    let fixture: ComponentFixture<GraphPresenceAvatarComponent>;
    let httpMock: HttpTestingController;
    let objectUrls: FakeObjectUrls;

    beforeEach(() => {
        objectUrls = new FakeObjectUrls();
        objectUrls.install();
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        objectUrls.restore();
    });

    function render(editor: EditorInfo): HTMLElement {
        fixture = TestBed.createComponent(GraphPresenceAvatarComponent);
        fixture.componentRef.setInput('editor', editor);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it.each([
        ['Taras Shevchenko', 'TS'],
        ['  lesya   ukrainka  ', 'LU'],
        ['Ivan', 'I'],
        ['   ', 'U12'],
        ['', 'U12'],
        [null, 'U12'],
    ])('shows %j as the initials %s', (displayName, initials) => {
        const element = render({ user_id: 12, display_name: displayName });

        expect(element.querySelector('img')).toBeNull();
        expect(element.textContent?.trim()).toBe(initials);
    });

    it.each([
        [3, 'rgb(78, 205, 196)'],
        [11, 'rgb(78, 205, 196)'],
        [8, 'rgb(74, 144, 217)'],
    ])('colours the initials of user %i by their id', (userId, colour) => {
        const element = render({ user_id: userId, display_name: 'Ivan' });

        expect(element.style.backgroundColor).toBe(colour);
    });

    it('shows the avatar image on a transparent background once it has loaded, the initials until then', () => {
        const avatarUrl = '/api/users/3/avatar/?v=77aa';
        const element = render({ user_id: 3, display_name: 'Taras Shevchenko', avatar_url: avatarUrl });
        expect(element.textContent?.trim()).toBe('TS');
        expect(element.style.backgroundColor).toBe('rgb(78, 205, 196)');

        httpMock.expectOne(avatarUrl).flush(new Blob(['png'], { type: 'image/png' }));
        fixture.detectChanges();

        const image = element.querySelector('img');
        expect(image?.getAttribute('src')).toBe('blob:fake-1');
        expect(image?.getAttribute('alt')).toBe('TS');
        expect(element.style.backgroundColor).toBe('transparent');
    });

    it('keeps the coloured initials when the avatar cannot be loaded', () => {
        const avatarUrl = '/api/users/3/avatar/?v=77aa';
        const element = render({ user_id: 3, display_name: 'Taras Shevchenko', avatar_url: avatarUrl });

        httpMock.expectOne(avatarUrl).flush(null, { status: 404, statusText: 'Not Found' });
        fixture.detectChanges();

        expect(element.querySelector('img')).toBeNull();
        expect(element.textContent?.trim()).toBe('TS');
        expect(element.style.backgroundColor).toBe('rgb(78, 205, 196)');
    });
});
