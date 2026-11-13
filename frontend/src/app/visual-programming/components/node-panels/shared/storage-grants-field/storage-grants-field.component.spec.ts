import { provideHttpClient } from '@angular/common/http';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { StorageGrants } from '../../../../core/models/storage-grants.model';
import { StorageGrantsFieldComponent } from './storage-grants-field.component';

@Component({
    imports: [ReactiveFormsModule, StorageGrantsFieldComponent],
    template: `<app-storage-grants-field
        [formControl]="control"
        [readonly]="readonly"
    />`,
})
class HostComponent {
    control = new FormControl<StorageGrants | undefined>(undefined);
    readonly = false;
}

const ALL_FILES_ACTIONS = [ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete];
const EVERYTHING: StorageGrants = { read: true, write: true, delete: true };
const NOTHING: StorageGrants = { read: false, write: false, delete: false };

function boxes(fixture: ComponentFixture<HostComponent>): HTMLInputElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('input[type="checkbox"]'));
}

function render(
    files: ActionCode[],
    value: StorageGrants | undefined,
    readonly = false
): ComponentFixture<HostComponent> {
    TestBed.configureTestingModule({ providers: [provideHttpClient()] });
    TestBed.inject(PermissionsService).setActivePermissions({
        org_id: 1,
        is_superadmin: false,
        role: { id: 1, name: 'Custom' },
        permissions: { [ResourceCode.Files]: files } as unknown as ActivePermissions['permissions'],
    });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.componentInstance.readonly = readonly;
    fixture.componentInstance.control.setValue(value);
    fixture.detectChanges();
    return fixture;
}

describe('StorageGrantsFieldComponent', () => {
    it('allows unticking but not ticking when the node is locked', () => {
        // A Member-like role: Files read, create and update, but not delete, on a node with all three ticked.
        const fixture = render([ActionCode.Read, ActionCode.Create, ActionCode.Update], EVERYTHING);

        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, false, false]);

        boxes(fixture)[2].click();
        fixture.detectChanges();

        expect(fixture.componentInstance.control.value).toEqual({ read: true, write: true, delete: false });
        // Delete is false now and the role lacks Files:Delete: it cannot be ticked again.
        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, false, true]);
    });

    it('keeps every box that is false disabled when the role lacks its permission', () => {
        const fixture = render([ActionCode.Read, ActionCode.Create], NOTHING);

        // Write needs Create and Update; the role has only Create.
        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, true, true]);
    });

    it('lets a keyboard or screen reader user reach why a box cannot be ticked', () => {
        const fixture = render([ActionCode.Read], NOTHING);
        const options: HTMLLabelElement[] = Array.from(fixture.nativeElement.querySelectorAll('label'));

        expect(options.map((option) => option.getAttribute('tabindex'))).toEqual([null, '0', '0']);
        expect(options[0].querySelector('.visually-hidden')).toBeNull();
        expect(options[2].querySelector('.visually-hidden')?.textContent).toContain('Files: Delete');
    });

    it('enables every box for a role that holds all the files permissions', () => {
        const fixture = render(ALL_FILES_ACTIONS, NOTHING);

        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, false, false]);
    });

    it('ticks a box and reports the other two as they were', () => {
        const fixture = render(ALL_FILES_ACTIONS, { read: false, write: true, delete: false });

        boxes(fixture)[0].click();
        fixture.detectChanges();

        expect(fixture.componentInstance.control.value).toEqual({ read: true, write: true, delete: false });
    });

    it('treats a node the server has not stored as all boxes false', () => {
        const fixture = render(ALL_FILES_ACTIONS, undefined);

        expect(boxes(fixture).map((box) => box.checked)).toEqual([false, false, false]);
    });

    it('disables every box, ticked or not, when the editor is read-only', () => {
        const fixture = render(ALL_FILES_ACTIONS, EVERYTHING, true);

        expect(boxes(fixture).map((box) => box.disabled)).toEqual([true, true, true]);
    });
});
