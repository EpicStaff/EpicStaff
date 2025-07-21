import {
  Component,
  ChangeDetectionStrategy,
  signal,
  inject,
  OnInit,
  computed,
  DestroyRef,
} from '@angular/core';
import { Tool } from '../../../../models/tool.model';
import { BuiltInToolCardComponent } from './components/built-in-tool-card/built-in-tool-card.component';
import { LoadingSpinnerComponent } from '../../../../../../shared/components/loading-spinner/loading-spinner.component';
import { NgIf, NgFor } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { CategoryButtonComponent } from './components/category-button/category-button.component';
import { TOOL_CATEGORIES_CONFIG } from '../../../../constants/built-in-tools-categories';
import { BuiltinToolsStorageService } from '../../../../services/builtin-tools/builtin-tools-storage.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Dialog } from '@angular/cdk/dialog';
import { ToolConfigurationDialogComponent } from '../../../../../../user-settings-page/tools/tool-configuration-dialog/tool-configuration-dialog.component';
import { ToastService } from '../../../../../../services/notifications/toast.service';

@Component({
  selector: 'app-built-in-tools',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './built-in-tools.component.html',
  styleUrls: ['./built-in-tools.component.scss'],
  imports: [
    BuiltInToolCardComponent,
    LoadingSpinnerComponent,
    CategoryButtonComponent,
  ],
})
export class BuiltInToolsComponent implements OnInit {
  private readonly builtinToolsStorageService = inject(
    BuiltinToolsStorageService
  );
  private readonly destroyRef = inject(DestroyRef);
  private readonly dialog = inject(Dialog);
  private readonly toastService = inject(ToastService);

  public readonly error = signal<string | null>(null);
  public readonly isLoaded = computed(() =>
    this.builtinToolsStorageService.isToolsLoaded()
  );
  public readonly selectedCategory = computed(
    () => this.builtinToolsStorageService.filters()?.category || null
  );
  public readonly filteredTools = computed(() =>
    this.builtinToolsStorageService.filteredTools()
  );
  public readonly TOOL_CATEGORIES_CONFIG = TOOL_CATEGORIES_CONFIG;

  public toggleCategory(category: string): void {
    const currentCategory = this.selectedCategory();
    if (currentCategory === category) {
      this.builtinToolsStorageService.setCategoryFilter(null);
    } else {
      this.builtinToolsStorageService.setCategoryFilter(category);
    }
  }

  public onToolConfigure(tool: Tool): void {
    console.log('Opening configuration dialog for tool:', tool);
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
    console.log(`Tool ${tool.name} enabled state changed to: ${enabled}`);

    // Create updated tool with new enabled status
    const updatedTool: Tool = {
      ...tool,
      enabled: enabled,
    };

    // Update tool in storage service
    this.builtinToolsStorageService
      .updateTool(updatedTool)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          console.log(
            `Tool ${updated.name} enabled state updated successfully`
          );

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
            `Failed to ${enabled ? 'activate' : 'deactivate'} tool "${
              tool.name
            }"`,
            5000,
            'bottom-right'
          );
        },
      });
  }

  public ngOnInit(): void {
    this.builtinToolsStorageService
      .getTools()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (tools) => {
          console.log(
            `✅ Built-in tools loaded: ${tools.length} tools available`
          );
        },
        error: (err: HttpErrorResponse) => {
          this.error.set('Failed to load tools. Please try again later.');
          console.error('❌ Error loading built-in tools:', err);
        },
      });
  }
}
