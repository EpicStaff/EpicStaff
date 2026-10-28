import { TestBed } from '@angular/core/testing';

import { AvatarUploadComponent } from './avatar-upload.component';

describe('AvatarUploadComponent existing avatar', () => {
    it('still offers removal when the current avatar fails to load', () => {
        const fixture = TestBed.createComponent(AvatarUploadComponent);
        fixture.componentRef.setInput('initialUrl', '/media/avatars/1.png?e=1&s=expired');
        fixture.detectChanges();
        const element: HTMLElement = fixture.nativeElement;

        element.querySelector('img')!.dispatchEvent(new Event('error'));
        fixture.detectChanges();

        expect(element.querySelector('img')).toBeNull();
        expect(element.querySelector('.name')?.textContent).toBe('Current avatar');
        expect(element.querySelector('button.clear')).not.toBeNull();
    });
});
