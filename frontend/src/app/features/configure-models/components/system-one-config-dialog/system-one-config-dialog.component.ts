import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ErrorBannerComponent, IconButtonComponent } from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';
import { SystemOneConfig } from '@shared/models';
import { SystemOneConfigStorageService } from '@shared/services';

import { SystemOneConfigFormComponent } from '../system-one-config-form/system-one-config-form.component';

/** Edits `config`, or the config with `configId` (opened from the secret usage list). New ones are created from "Add Configuration". */
export type SystemOneConfigDialogData = { config: SystemOneConfig } | { configId: number };

@Component({
    selector: 'app-system-one-config-dialog',
    templateUrl: './system-one-config-dialog.component.html',
    styleUrls: ['./system-one-config-dialog.component.scss'],
    imports: [
        ButtonComponent,
        ErrorBannerComponent,
        IconButtonComponent,
        EnterSubmitDirective,
        SystemOneConfigFormComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SystemOneConfigDialogComponent implements OnInit {
    private readonly form = viewChild(SystemOneConfigFormComponent);
    protected readonly config = signal<SystemOneConfig | null>(null);
    protected readonly isSaving = computed(() => this.form()?.isSubmitting() ?? false);
    protected readonly saveLabel = computed(() => (this.isSaving() ? 'Saving…' : 'Save Changes'));
    protected readonly saveError = computed(() => this.form()?.errorMessage() ?? null);

    private readonly data = inject<SystemOneConfigDialogData>(DIALOG_DATA);
    private readonly storage = inject(SystemOneConfigStorageService);
    private readonly dialogRef = inject(DialogRef);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        if ('config' in this.data) {
            this.config.set(this.data.config);
        } else {
            const configId = this.data.configId;
            this.storage
                .getAllConfigs()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (configs) => {
                        const match = configs.find((config) => config.id === configId);
                        if (match) this.config.set(match);
                        else this.dialogRef.close(null);
                    },
                    error: () => this.dialogRef.close(null),
                });
        }

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSave();
            }
        });
    }

    onSave(): void {
        this.form()?.submit();
    }

    onSaved(): void {
        this.dialogRef.close(true);
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
