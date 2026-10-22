import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { FakeObjectUrls } from '../../services/avatar-image/testing/fake-object-urls';
import { UserAvatarComponent } from './user-avatar.component';

function initialsFor(name: string): string {
    const fixture = TestBed.createComponent(UserAvatarComponent);
    fixture.componentRef.setInput('name', name);
    return fixture.componentInstance.initials();
}

describe('UserAvatarComponent initials', () => {
    it.each([
        ['John Smith', 'JS'],
        ['Mary Jane Watson', 'MJ'],
        ['Johnsmith', 'JO'],
        ['Org Admin', 'OA'],
        ['j0hn@gmail.com', 'JH'],
        ['john.doe@x.com', 'JD'],
        ['john_smith@gmail.com', 'JS'],
        ['123john@gmail.com', 'JO'],
        ['+john@gmail.com', 'JO'],
        ['j.smith@gmail.com', 'JS'],
        ['a@b.co', 'A'],
        ["O'brien", 'OB'],
        ['1.2.3', '1.'],
        ['007', '00'],
        ['---', '--'],
    ])('shows %s as %s', (name, initials) => {
        expect(initialsFor(name)).toBe(initials);
    });
});

describe('UserAvatarComponent image', () => {
    const AVATAR_URL = '/api/users/4/avatar/?v=5c2a';
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

    function render(avatarUrl: string | null): { element: HTMLElement; refresh: () => void } {
        const fixture = TestBed.createComponent(UserAvatarComponent);
        fixture.componentRef.setInput('name', 'Olena Pchilka');
        fixture.componentRef.setInput('avatarUrl', avatarUrl);
        fixture.detectChanges();
        return { element: fixture.nativeElement as HTMLElement, refresh: () => fixture.detectChanges() };
    }

    it('shows the initials while the avatar loads, then the loaded image', () => {
        const { element, refresh } = render(AVATAR_URL);
        expect(element.querySelector('img')).toBeNull();
        expect(element.querySelector('.initials')?.textContent).toBe('OP');

        httpMock.expectOne(AVATAR_URL).flush(new Blob(['png'], { type: 'image/png' }));
        refresh();

        expect(element.querySelector('img')?.getAttribute('src')).toBe('blob:fake-1');
        expect(element.querySelector('.initials')).toBeNull();
    });

    it('keeps the initials when the avatar cannot be loaded', () => {
        const { element, refresh } = render(AVATAR_URL);

        httpMock.expectOne(AVATAR_URL).flush(null, { status: 404, statusText: 'Not Found' });
        refresh();

        expect(element.querySelector('img')).toBeNull();
        expect(element.querySelector('.initials')?.textContent).toBe('OP');
    });
});
