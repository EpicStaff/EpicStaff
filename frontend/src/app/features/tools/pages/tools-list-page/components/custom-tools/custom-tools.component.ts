import {
  Component,
  ChangeDetectionStrategy,
  signal,
  inject,
  OnInit,
  DestroyRef,
  computed,
  Input,
} from '@angular/core';
import { GetPythonCodeToolRequest } from '../../../../models/python-code-tool.model';
import { LoadingSpinnerComponent } from '../../../../../../shared/components/loading-spinner/loading-spinner.component';
import { CustomToolCardComponent } from './components/custom-tool-card/custom-tool-card.component';
import { HttpErrorResponse } from '@angular/common/http';
import { CustomToolsService } from '../../../../services/custom-tools/custom-tools.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Dialog, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { CustomToolDialogComponent } from '../../../../../../user-settings-page/tools/custom-tool-editor/custom-tool-dialog.component';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import { ConfirmationDialogService } from '../../../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { ToolsEventsService } from '../../../../services/tools-events.service';
import { ToolsSearchService } from '../../../../services/tools-search.service';

@Component({
  selector: 'app-custom-tools',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './custom-tools.component.html',
  styleUrls: ['./custom-tools.component.scss'],
  imports: [
    LoadingSpinnerComponent,
    CustomToolCardComponent,
    DialogModule,
    CommonModule,
  ],
})
export class CustomToolsComponent implements OnInit {
  private readonly customToolsService = inject(CustomToolsService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly dialog = inject(Dialog);
  private readonly toastService = inject(ToastService);
  private readonly confirmationDialogService = inject(
    ConfirmationDialogService
  );
  private readonly toolsEventsService = inject(ToolsEventsService);
  private readonly toolsSearchService = inject(ToolsSearchService);

  public searchTerm = signal<string>('');

  // Local state management
  private readonly allTools = signal<GetPythonCodeToolRequest[]>([]);
  
  public readonly error = signal<string | null>(null);
  public readonly isLoaded = signal<boolean>(false);
  public readonly tools = computed(() => {
    const tools = this.allTools().slice().sort((a, b) => b.id - a.id);
    const term = this.searchTerm();
    
    if (!term || term.trim() === '') {
      return tools;
    }
    
    const searchLower = term.toLowerCase();
    return tools.filter(tool => 
      tool.name.toLowerCase().includes(searchLower) ||
      tool.description.toLowerCase().includes(searchLower)
    );
  });

  public ngOnInit(): void {
    this.loadTools();
    
    // Listen for new tool creation events
    this.toolsEventsService.customToolCreated$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((newTool) => {
        this.addNewTool(newTool);
      });
    
    // Listen for search term changes
    this.toolsSearchService.searchTerm$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((term) => {
        this.searchTerm.set(term);
      });
  }

  private loadTools(): void {
    this.customToolsService
      .getPythonCodeTools()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (tools) => {
          this.allTools.set(tools);
          this.isLoaded.set(true);
          console.log(
            `✅ Custom tools loaded: ${tools.length} tools available`
          );
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(
            'Failed to load custom tools. Please try again later.'
          );
          this.isLoaded.set(true);
          console.error('❌ Error loading custom tools:', err);
        },
      });
  }

  public onConfigure(tool: GetPythonCodeToolRequest): void {
    const dialogRef = this.dialog.open<GetPythonCodeToolRequest>(
      CustomToolDialogComponent,
      {
        data: {
          pythonTools: this.tools(),
          selectedTool: tool,
        },
      }
    );

    dialogRef.closed.subscribe((result) => {
      if (result) {
        // Update local state with the updated tool
        const currentTools = this.allTools();
        const index = currentTools.findIndex(t => t.id === result.id);
        if (index !== -1) {
          const updatedTools = [...currentTools];
          updatedTools[index] = result;
          this.allTools.set(updatedTools);
        }
      }
    });
  }

  public onDelete(tool: GetPythonCodeToolRequest): void {
    this.confirmationDialogService
      .confirmDelete(tool.name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result) => {
        // Only proceed if result is exactly true (user clicked confirm)
        if (result === true) {
          this.customToolsService
            .deletePythonCodeTool(tool.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: () => {
                // Remove from local state
                const currentTools = this.allTools();
                this.allTools.set(currentTools.filter(t => t.id !== tool.id));
                
                this.toastService.success(
                  `Tool "${tool.name}" has been deleted successfully.`
                );
                console.log(`✅ Tool "${tool.name}" deleted successfully`);
              },
              error: (err: HttpErrorResponse) => {
                this.toastService.error(
                  `Failed to delete tool "${tool.name}". Please try again.`
                );
                console.error('❌ Error deleting tool:', err);
              },
            });
        }
        // If result is false or 'close', the action is cancelled (do nothing)
      });
  }

  public addNewTool(tool: GetPythonCodeToolRequest): void {
    const currentTools = this.allTools();
    this.allTools.set([tool, ...currentTools]);
    console.log(`✅ New custom tool "${tool.name}" added to list`);
  }
}
