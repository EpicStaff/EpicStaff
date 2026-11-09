import { provideHttpClient } from '@angular/common/http';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { NOT_CONFIGURED_GRANTS_DISABLED_TOOLTIP } from '../../../../core/helpers/storage-grants.util';
import { StorageGrants } from '../../../../core/models/storage-grants.model';
import { StorageGrantsFieldComponent } from './storage-grants-field.component';

@Component({
    imports: [ReactiveFormsModule, StorageGrantsFieldComponent],
    template: `<app-storage-grants-field [formControl]="control" />`,
})
class HostComponent {
    control = new FormControl<StorageGrants | undefined>(undefined);
}

function boxes(fixture: ComponentFixture<HostComponent>): HTMLInputElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('input[type="checkbox"]'));
}

function render(files: ActionCode[], value: StorageGrants | undefined): ComponentFixture<HostComponent> {
    TestBed.configureTestingModule({ providers: [provideHttpClient()] });
    TestBed.inject(PermissionsService).setActivePermissions({
        org_id: 1,
        is_superadmin: false,
        role: { id: 1, name: 'Custom' },
        permissions: { [ResourceCode.Files]: files } as unknown as ActivePermissions['permissions'],
    });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.componentInstance.control.setValue(value);
    fixture.detectChanges();
    return fixture;
}

describe('StorageGrantsFieldComponent', () => {
    it('disables the boxes whose permission the role lacks', () => {
        const fixture = render([ActionCode.Read, ActionCode.Create], { read: true, write: false, delete: false });

        // Write needs Create and Update; the role has only Create.
        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, true, true]);
    });

    it('enables every box for a role that holds all the files permissions', () => {
        const fixture = render([ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete], {
            read: false,
            write: false,
            delete: false,
        });

        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, false, false]);
    });

    it('disables every box of a not-configured slot for a role missing any Files permission', () => {
        const fixture = render([ActionCode.Read, ActionCode.Create, ActionCode.Update], {
            read: null,
            write: null,
            delete: null,
        });

        expect(boxes(fixture).map((box) => box.disabled)).toEqual([true, true, true]);
        const tooltips = fixture.debugElement
            .queryAll(By.css('label.storage-grants__option'))
            .map((tip) => tip.injector.get(MatTooltip).message);
        expect(tooltips).toEqual(Array(3).fill(NOT_CONFIGURED_GRANTS_DISABLED_TOOLTIP));
        expect(fixture.componentInstance.control.value).toEqual({ read: null, write: null, delete: null });
    });

    it('enables every box of a not-configured slot for a role holding all four Files permissions', () => {
        const fixture = render([ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete], {
            read: null,
            write: null,
            delete: null,
        });

        expect(boxes(fixture).map((box) => box.disabled)).toEqual([false, false, false]);
    });

    it('says a stored all-null node is not configured and leaves the value alone', () => {
        const fixture = render([ActionCode.Read], { read: null, write: null, delete: null });

        expect(fixture.nativeElement.textContent).toContain('Not configured (current behaviour)');
        expect(fixture.componentInstance.control.value).toEqual({ read: null, write: null, delete: null });
    });

    it('makes the slot explicit when the user ticks a box of a not-configured node', () => {
        const fixture = render([ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete], {
            read: null,
            write: null,
            delete: null,
        });

        boxes(fixture)[0].click();
        fixture.detectChanges();

        expect(fixture.componentInstance.control.value).toEqual({ read: true, write: false, delete: false });
        expect(fixture.nativeElement.textContent).not.toContain('Not configured');
    });

    it('shows no not-configured note for a node the server has not stored', () => {
        const fixture = render([ActionCode.Read], undefined);

        expect(fixture.nativeElement.textContent).not.toContain('Not configured');
    });
});
