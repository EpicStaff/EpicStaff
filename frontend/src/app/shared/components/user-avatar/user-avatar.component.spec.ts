import { TestBed } from '@angular/core/testing';

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
    function renderAvatar(avatarUrl: string) {
        const fixture = TestBed.createComponent(UserAvatarComponent);
        fixture.componentRef.setInput('name', 'John Smith');
        fixture.componentRef.setInput('avatarUrl', avatarUrl);
        fixture.detectChanges();
        return fixture;
    }

    it('shows the initials when the image fails to load', () => {
        const fixture = renderAvatar('/media/avatars/expired.png');
        const element: HTMLElement = fixture.nativeElement;

        element.querySelector('img')!.dispatchEvent(new Event('error'));
        fixture.detectChanges();

        expect(element.querySelector('img')).toBeNull();
        expect(element.querySelector('.initials')?.textContent).toBe('JS');
    });

    it('tries the image again when a new URL arrives after a failure', () => {
        const fixture = renderAvatar('/media/avatars/expired.png');
        const element: HTMLElement = fixture.nativeElement;
        element.querySelector('img')!.dispatchEvent(new Event('error'));
        fixture.detectChanges();

        fixture.componentRef.setInput('avatarUrl', '/media/avatars/fresh.png');
        fixture.detectChanges();

        expect(element.querySelector('img')?.getAttribute('src')).toBe('/media/avatars/fresh.png');
    });
});
