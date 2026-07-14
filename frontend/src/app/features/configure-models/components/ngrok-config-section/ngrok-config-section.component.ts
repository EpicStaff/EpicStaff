import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule } from '@angular/forms';
import {
    ButtonComponent,
    ConfirmationDialogService,
    ConfirmationResult,
    LoadingSpinnerComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, GetNgrokConfigResponse, ResourceCode } from '@shared/models';
import { NgrokConfigStorageService } from '@shared/services';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';
import { AddNgrokConfigDialogComponent } from '../add-ngrok-config-dialog/add-ngrok-config-dialog.component';
import { NgrokConfigItemComponent } from '../ngrok-config-item/ngrok-config-item.component';

@Component({
    selector: 'app-ngrok-config-section',
    templateUrl: './ngrok-config-section.component.html',
    styleUrls: ['./ngrok-config-section.component.scss'],
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        NgrokConfigItemComponent,
        LoadingSpinnerComponent,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppNgrokSectionComponent implements OnInit {
    private ngrokStorageService = inject(NgrokConfigStorageService);
    private destroyRef = inject(DestroyRef);
    private dialog = inject(Dialog);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private toastService = inject(ToastService);

    ngrokConfigs = this.ngrokStorageService.configs;
    status = signal<LoadingState>(LoadingState.IDLE);
    errorMessage = signal<string | null>(null);

    ngOnInit() {
        this.getConfigs();
    }

    refreshData(): void {
        this.status.set(LoadingState.LOADING);
        this.getConfigs();
    }

    private getConfigs(): void {
        this.status.set(LoadingState.LOADING);

        this.ngrokStorageService
            .getConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.status.set(LoadingState.LOADED),
                error: (err) => {
                    console.error('Failed to load Ngrok configurations:', err);
                    this.errorMessage.set('Failed to load configurations. Please try again.');
                    this.status.set(LoadingState.ERROR);
                },
            });
    }

    onAddConfig(): void {
        this.openConfigDialog('create');
    }

    onEditConfig(config: GetNgrokConfigResponse): void {
        this.openConfigDialog('update', config);
    }

    private openConfigDialog(action: 'create' | 'update', config?: GetNgrokConfigResponse): void {
        this.dialog.open(AddNgrokConfigDialogComponent, {
            width: '500px',
            disableClose: true,
            data: { config, action },
        });
    }

    onRemoveConfig(config: GetNgrokConfigResponse): void {
        this.confirmationDialogService
            .confirmDelete(config.name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result: ConfirmationResult) => {
                if (result === true) {
                    this.ngrokStorageService
                        .deleteConfigById(config.id)
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: () => this.toastService.success('Config deleted'),
                            error: (e) => this.toastService.error(`Config deletion failed: ${e.message}`),
                        });
                }
            });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
