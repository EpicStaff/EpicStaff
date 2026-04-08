import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ToastService } from '../../../../../../services/notifications/toast.service';
import { LoadingSpinnerComponent } from '../../../../../../shared/components/loading-spinner/loading-spinner.component';
import { ToolConfigurationDialogComponent } from '../../../../../../user-settings-page/tools/tool-configuration-dialog/tool-configuration-dialog.component';
import { TOOL_CATEGORIES_CONFIG } from '../../../../constants/built-in-tools-categories';
import { Tool } from '../../../../models/tool.model';
import { BuiltinToolsService } from '../../../../services/builtin-tools/builtin-tools.service';
import { BuiltInToolCardComponent } from './components/built-in-tool-card/built-in-tool-card.component';
import { CategoryButtonComponent } from './components/category-button/category-button.component';

// hidden for now (EST-2215)
@Component({
    selector: 'app-built-in-tools',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './built-in-tools.component.html',
    styleUrls: ['./built-in-tools.component.scss'],
    imports: [BuiltInToolCardComponent, LoadingSpinnerComponent, CategoryButtonComponent],
})
export class BuiltInToolsComponent implements OnInit {
    private readonly builtinToolsService = inject(BuiltinToolsService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);

    // Local state management
    private readonly allTools = signal<Tool[]>([]);
    private readonly selectedCategorySignal = signal<string | null>(null);

    public readonly error = signal<string | null>(null);
    public readonly isLoaded = signal<boolean>(false);
    public readonly selectedCategory = computed(() => this.selectedCategorySignal());
    public readonly filteredTools = computed(() => {
        const tools = this.allTools();
        const category = this.selectedCategorySignal();

        if (!category) {
            return tools.slice().sort((a, b) => b.id - a.id);
        }

        const categoryConfig = TOOL_CATEGORIES_CONFIG.find((cat) => cat.name === category);
        if (!categoryConfig) {
            return tools.slice().sort((a, b) => b.id - a.id);
        }

        return tools.filter((tool) => categoryConfig.toolIds.includes(tool.id)).sort((a, b) => b.id - a.id);
    });
    public readonly TOOL_CATEGORIES_CONFIG = TOOL_CATEGORIES_CONFIG;

    public toggleCategory(category: string): void {
        const currentCategory = this.selectedCategory();
        if (currentCategory === category) {
            this.selectedCategorySignal.set(null);
        } else {
            this.selectedCategorySignal.set(category);
        }
    }

    public onToolConfigure(tool: Tool): void {
        const dialogRef = this.dialog.open(ToolConfigurationDialogComponent, {
            data: {
                tool: tool,
            },
        });

        dialogRef.closed.subscribe((result) => {
            if (result) {
                console.log('Tool configuration updated:', result);
            }
        });
    }

    public onToolEnabledChange(event: { tool: Tool; enabled: boolean }): void {
        const { tool, enabled } = event;

        // Create updated tool with new enabled status
        const updatedTool: Tool = {
            ...tool,
            enabled: enabled,
        };

        // Update tool directly via service
        this.builtinToolsService
            .updateTool(updatedTool)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (updated) => {
                    // Update local state
                    const currentTools = this.allTools();
                    const index = currentTools.findIndex((t) => t.id === updated.id);
                    if (index !== -1) {
                        const updatedTools = [...currentTools];
                        updatedTools[index] = updated;
                        this.allTools.set(updatedTools);
                    }

                    // Show success notification
                    const message = enabled
                        ? `Tool "${updated.name}" has been activated successfully`
                        : `Tool "${updated.name}" has been deactivated`;

                    this.toastService.success(message, 3000, 'bottom-right');
                },
                error: (err) => {
                    console.error('Error updating tool enabled state:', err);

                    // Show error notification
                    this.toastService.error(
                        `Failed to ${enabled ? 'activate' : 'deactivate'} tool "${tool.name}"`,
                        5000,
                        'bottom-right'
                    );
                },
            });
    }

    public ngOnInit(): void {
        this.loadTools();
    }

    private loadTools(): void {
        this.builtinToolsService
            .getTools()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (tools) => {
                    this.allTools.set(tools);
                    this.isLoaded.set(true);
                },
                error: (err: HttpErrorResponse) => {
                    this.error.set('Failed to load tools. Please try again later.');
                    this.isLoaded.set(true);
                    console.error('❌ Error loading built-in tools:', err);
                },
            });
    }
}
