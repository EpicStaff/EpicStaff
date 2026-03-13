import { Dialog } from "@angular/cdk/dialog";
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from "@angular/core";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { ReactiveFormsModule } from "@angular/forms";
import { ButtonComponent, ConfirmationDialogService, ConfirmationResult } from "@shared/components";
import { LoadingState } from "../../../../core/enums/loading-state.enum";
import { ToastService } from "../../../../services/notifications";
import { GetNgrokConfigResponse } from "../../models/ngrok-config.model";
import { NgrokConfigStorageService } from "../../services/ngrok-config/ngrok-config-storage.service";
import { AddNgrokConfigDialogComponent } from "./add-ngrok-config-dialog/add-ngrok-config-dialog.component";
import { NgrokConfigItemComponent } from "./ngrok-config-item/ngrok-config-item.component";

@Component({
    selector: 'app-ngrok-config-tab',
    templateUrl: './ngrok-config-tab.component.html',
    styleUrls: ['./ngrok-config-tab.component.scss'],
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        NgrokConfigItemComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class NgrokConfigTabComponent implements OnInit {
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

        this.ngrokStorageService.getConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.status.set(LoadingState.LOADED),
                error: (err) => {
                    console.error('Failed to load Ngrok configurations:', err);
                    this.errorMessage.set(
                        'Failed to load configurations. Please try again.'
                    );
                    this.status.set(LoadingState.ERROR);
                },
            })
    }

    onAddConfig(): void {
        this.openConfigDialog('create');
    }

    onEditConfig(config: GetNgrokConfigResponse): void {
        this.openConfigDialog('update', config);
    }

    private openConfigDialog(
        action: 'create' | 'update',
        config?: GetNgrokConfigResponse
    ): void {
        this.dialog.open(AddNgrokConfigDialogComponent, {
            width: '500px',
            disableClose: true,
            data: { config, action },
        });
    }

    onRemoveConfig(config: GetNgrokConfigResponse): void {
        this.confirmationDialogService.confirmDelete(config.name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result: ConfirmationResult) => {
                if (result === true) {
                    this.ngrokStorageService.deleteConfigById(config.id)
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: () => this.toastService.success('Config deleted'),
                            error: (e) => this.toastService.error(`Config deletion failed: ${e.message}`),
                        });
                }
            });
    }
}
