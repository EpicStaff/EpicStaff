import { TestBed } from '@angular/core/testing';

import { AggregatedUser } from '../../../../models/aggregated-user.model';
import { StepUserDetailsComponent } from './step-user-details.component';

const EDITED_USER: AggregatedUser = {
    id: 5,
    email: 'user5@example.com',
    displayName: 'User 5',
    avatarUrl: null,
    isSuperadmin: false,
    isActive: true,
    memberships: [],
};

function render(editMode: boolean): HTMLElement {
    const fixture = TestBed.createComponent(StepUserDetailsComponent);
    fixture.componentRef.setInput('editMode', editMode);
    fixture.componentRef.setInput('userData', editMode ? EDITED_USER : null);
    fixture.detectChanges();
    return fixture.nativeElement;
}

describe('StepUserDetailsComponent', () => {
    it('shows the edited user email as text, with no email field', () => {
        const element = render(true);

        expect(element.querySelector('#user-details-email')).toBeNull();
        expect(element.querySelector('.readonly-value')?.textContent).toBe('user5@example.com');
    });

    it('offers an email field when creating a user', () => {
        const element = render(false);

        expect(element.querySelector('input#user-details-email')).not.toBeNull();
    });
});
