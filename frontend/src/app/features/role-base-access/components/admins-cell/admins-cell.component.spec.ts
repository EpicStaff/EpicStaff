import { TestBed } from '@angular/core/testing';

import { AdminsCellComponent } from './admins-cell.component';

describe('AdminsCellComponent', () => {
    it('renders a neutral placeholder and no trigger when the admin list is empty (identities hidden)', () => {
        const fixture = TestBed.createComponent(AdminsCellComponent);
        fixture.componentRef.setInput('admins', []);
        fixture.detectChanges();
        const host = fixture.nativeElement as HTMLElement;

        expect(host.querySelector('.empty')?.textContent?.trim()).toBe('—');
        expect(host.querySelector('.admins-trigger')).toBeNull();
        expect(host.querySelector('app-user-avatar')).toBeNull();
    });
});
