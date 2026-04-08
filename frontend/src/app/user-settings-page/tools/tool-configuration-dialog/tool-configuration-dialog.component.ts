import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgClass, NgFor, NgIf } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Inject, OnDestroy, OnInit } from '@angular/core';
import { forkJoin, Observable, Subject, Subscription } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import {
    FullEmbeddingConfig,
    FullEmbeddingConfigService,
} from '../../../features/settings-dialog/services/embeddings/full-embedding.service';
import {
    FullLLMConfig,
    FullLLMConfigService,
} from '../../../features/settings-dialog/services/llms/full-llm-config.service';
import { Tool } from '../../../features/tools/models/tool.model';
import { GetToolConfigRequest, ToolConfig } from '../../../features/tools/models/tool-config.model';
import { ToolConfigService } from '../../../features/tools/services/tool-config.service';
import { ToastService } from '../../../services/notifications/toast.service';
import { ConfirmationDialogService } from '../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ToolConfigFormComponent } from './tool-config-form/tool-config-form.component';

@Component({
    selector: 'app-tool-configuration-dialog',
    templateUrl: './tool-configuration-dialog.component.html',
    styleUrls: ['./tool-configuration-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [NgIf, NgFor, NgClass, ToolConfigFormComponent, AppSvgIconComponent],
})
export class ToolConfigurationDialogComponent implements OnInit, OnDestroy {
    tool: Tool;
    isLoading = true;

    llmConfigs: FullLLMConfig[] = [];
    embeddingConfigs: FullEmbeddingConfig[] = [];
    existingToolConfigs: ToolConfig[] = [];

    selectedConfig: ToolConfig | null = null;
    currentFilteredConfigs: ToolConfig[] = [];

    // Fields previously in tool-config-list.component
    filteredConfigs: ToolConfig[] = [];
    searchHasContent = false;
    private currentSearchQuery = '';

    private subscriptions = new Subscription();
    private _destroy$ = new Subject<void>();

    constructor(
        public dialogRef: DialogRef<unknown>,
        @Inject(DIALOG_DATA) public data: { tool: Tool },
        private toolConfigService: ToolConfigService,
        private fullLlmConfigService: FullLLMConfigService,
        private fullEmbeddingConfigService: FullEmbeddingConfigService,
        private _confirmationDialogService: ConfirmationDialogService,
        private cdr: ChangeDetectorRef,
        private toastService: ToastService
    ) {
        this.tool = data.tool;
    }

    ngOnInit(): void {
        this.fetchData();
    }

    ngOnDestroy(): void {
        this._destroy$.next();
        this._destroy$.complete();
        this.subscriptions.unsubscribe();
    }

    private fetchData(): void {
        this.isLoading = true;
        this.cdr.markForCheck();

        const llmConfigs$: Observable<FullLLMConfig[]> = this.fullLlmConfigService.getFullLLMConfigs();
        const embeddingConfigs$: Observable<FullEmbeddingConfig[]> =
            this.fullEmbeddingConfigService.getFullEmbeddingConfigs();
        const toolConfigs$: Observable<GetToolConfigRequest[]> = this.toolConfigService.getToolConfigs();

        this.subscriptions.add(
            forkJoin([llmConfigs$, embeddingConfigs$, toolConfigs$])
                .pipe(takeUntil(this._destroy$))
                .subscribe({
                    next: ([llmConfigs, embeddingConfigs, toolConfigs]) => {
                        this.llmConfigs = llmConfigs;
                        this.embeddingConfigs = embeddingConfigs;
                        this.existingToolConfigs = toolConfigs.filter((config) => config.tool === this.tool.id);

                        this.selectInitialConfig();
                        // Initialize filteredConfigs
                        this.filteredConfigs = [...this.existingToolConfigs];
                        this.onFilteredConfigsChange(this.filteredConfigs);
                        this.isLoading = false;
                        this.cdr.markForCheck();
                    },
                    error: (err) => {
                        console.error('Error fetching configurations:', err);
                        this.toastService.error(`Failed to load configurations: ${err.message || 'Unknown error'}`);
                        this.isLoading = false;
                        this.cdr.markForCheck();
                    },
                })
        );
    }

    private selectInitialConfig(): void {
        if (this.existingToolConfigs && this.existingToolConfigs.length > 0) {
            this.selectedConfig = this.existingToolConfigs[0];
        } else {
            this.selectedConfig = null; // No configs -> creation mode
        }
        this.cdr.detectChanges();
    }

    // Methods that were previously in the child component
    onSearch(event: Event): void {
        const inputElement = event.target as HTMLInputElement;
        this.currentSearchQuery = inputElement.value.toLowerCase().trim();
        this.searchHasContent = this.currentSearchQuery.length > 0;
        this.applyFilter();
    }

    private applyFilter(): void {
        if (this.currentSearchQuery === '') {
            this.filteredConfigs = [...this.existingToolConfigs];
        } else {
            this.filteredConfigs = this.existingToolConfigs.filter((config) =>
                config.name.toLowerCase().includes(this.currentSearchQuery)
            );
        }

        this.onFilteredConfigsChange(this.filteredConfigs);
    }

    onSelect(config: ToolConfig): void {
        this.onConfigSelected(config);
    }

    onCreateNew(): void {
        this.createNewConfig();
    }

    deleteFromList(config: ToolConfig): void {
        this.onDeleteConfig(config);
    }

    // Existing parent methods
    onFilteredConfigsChange(filteredConfigs: ToolConfig[]): void {
        this.currentFilteredConfigs = filteredConfigs;
        this.cdr.detectChanges();
    }

    onConfigSelected(config: ToolConfig): void {
        this.selectedConfig = config; // editing mode
        this.cdr.detectChanges();
    }

    createNewConfig(): void {
        this.selectedConfig = null; // creation mode
        this.cdr.detectChanges();
    }

    onFormSubmit(updatedConfig: ToolConfig): void {
        const index = this.existingToolConfigs.findIndex((c) => c.id === updatedConfig.id);

        if (index !== -1) {
            // Update existing config
            this.existingToolConfigs[index] = updatedConfig;
            this.toastService.success(`Configuration "${updatedConfig.name}" was updated successfully`);
        } else {
            // Add new config
            this.existingToolConfigs.push(updatedConfig);
            this.toastService.success(`Configuration "${updatedConfig.name}" was created successfully`);
        }

        this.selectedConfig = updatedConfig;
        this.applyFilter(); // Re-apply filter to update filteredConfigs
        this.cdr.markForCheck();
    }

    onDeleteConfig(config: ToolConfig): void {
        event?.stopPropagation(); // Prevent triggering the list item click

        this._confirmationDialogService
            .confirmDelete(config.name)
            .pipe(takeUntil(this._destroy$))
            .subscribe({
                next: (result) => {
                    // Only proceed if result is exactly true (user clicked confirm)
                    if (result === true) {
                        this.toolConfigService
                            .deleteToolConfig(config.id)
                            .pipe(takeUntil(this._destroy$))
                            .subscribe({
                                next: () => {
                                    // Remove the config from existing configs
                                    this.existingToolConfigs = this.existingToolConfigs.filter(
                                        (c) => c.id !== config.id
                                    );

                                    // Show success notification
                                    this.toastService.success(
                                        `Configuration "${config.name}" was deleted successfully`
                                    );

                                    // Re-apply filter to update filtered configs
                                    this.applyFilter();

                                    // If there are remaining configs, select the first one
                                    if (this.filteredConfigs.length > 0) {
                                        this.selectedConfig = this.filteredConfigs[0];
                                    } else {
                                        this.selectedConfig = null;
                                    }

                                    this.cdr.detectChanges();
                                },
                                error: (err) => {
                                    console.error('Error deleting configuration:', err);
                                    this.toastService.error(
                                        `Failed to delete configuration: ${err.message || 'Unknown error'}`
                                    );
                                },
                            });
                    }
                    // If result is false or 'close', the action is cancelled (do nothing)
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close();
    }
}
