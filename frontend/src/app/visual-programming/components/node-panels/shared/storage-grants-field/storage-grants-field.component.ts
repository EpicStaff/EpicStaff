import { ChangeDetectionStrategy, Component, computed, forwardRef, inject, input, signal } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { CheckboxComponent } from '@shared/components';
import { StorageGrant } from '@shared/utils';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import {
    canEditStorageGrant,
    STORAGE_GRANT_KINDS,
    STORAGE_GRANT_LABELS,
    storageGrantDisabledTooltip,
    toggleStorageGrant,
} from '../../../../core/helpers/storage-grants.util';
import { StorageGrants } from '../../../../core/models/storage-grants.model';

interface StorageGrantOption {
    kind: StorageGrant;
    label: string;
    checked: boolean;
    disabled: boolean;
    tooltip: string;
}

/**
 * Read / Write / Delete boxes for what one slot of code may do with the flow's attached files in every run. The
 * value is the slot's grants: `undefined` for a node the server has not stored, shown as every box unticked.
 * A ticked box can always be unticked; an unticked one can be ticked only with the Files permission behind it.
 */
@Component({
    selector: 'app-storage-grants-field',
    imports: [CheckboxComponent, MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => StorageGrantsFieldComponent),
            multi: true,
        },
    ],
    styleUrl: './storage-grants-field.component.scss',
    template: `
        <fieldset class="storage-grants">
            <legend class="storage-grants__legend">{{ legend() }}</legend>
            <div class="storage-grants__options">
                @for (option of options(); track option.kind) {
                    <label
                        class="storage-grants__option"
                        [class.storage-grants__option--disabled]="option.disabled"
                        [matTooltip]="option.tooltip"
                        matTooltipPosition="above"
                    >
                        <app-checkbox
                            [checked]="option.checked"
                            [disabled]="option.disabled"
                            (changed)="onToggle(option.kind, $event)"
                        />
                        {{ option.label }}
                    </label>
                }
            </div>
        </fieldset>
    `,
})
export class StorageGrantsFieldComponent implements ControlValueAccessor {
    readonly legend = input('File access');
    /** Nothing may be changed, whatever the user's role allows. */
    readonly readonly = input(false);

    private readonly grants = signal<StorageGrants | undefined>(undefined);
    private readonly permissions = inject(PermissionsService);

    protected readonly options = computed<StorageGrantOption[]>(() => {
        const grants = this.grants();
        return STORAGE_GRANT_KINDS.map((kind) => {
            const permitted = canEditStorageGrant(grants, kind, (resource, action) =>
                this.permissions.can(resource, action)
            );
            return {
                kind,
                label: STORAGE_GRANT_LABELS[kind],
                checked: grants?.[kind] === true,
                disabled: this.readonly() || !permitted,
                tooltip: permitted ? '' : storageGrantDisabledTooltip(kind),
            };
        });
    });

    private onChange: (value: StorageGrants) => void = () => {};
    private onTouched = () => {};

    protected onToggle(kind: StorageGrant, checked: boolean): void {
        const next = toggleStorageGrant(this.grants(), kind, checked);
        this.grants.set(next);
        this.onChange(next);
        this.onTouched();
    }

    writeValue(value: StorageGrants | null | undefined): void {
        this.grants.set(value ?? undefined);
    }

    registerOnChange(fn: (value: StorageGrants) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }
}
