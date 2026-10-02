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
