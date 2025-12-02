import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit,
  ViewChild,
  signal,
} from '@angular/core';
import { NgFor, NgIf, CommonModule } from '@angular/common';
import { Subscription, forkJoin, finalize } from 'rxjs';
import {
  ScrollDispatcher,
  CdkScrollable,
  ScrollingModule,
} from '@angular/cdk/scrolling';
import { FormsModule } from '@angular/forms';

import { BuiltinToolsService } from '../../features/tools/services/builtin-tools/builtin-tools.service';
import { PythonCodeToolService } from './custom-tool-editor/services/pythonCodeToolService.service';
import { ToolConfigurationDialogComponent } from './tool-configuration-dialog/tool-configuration-dialog.component';
import { Dialog } from '@angular/cdk/dialog';
import { CustomToolDialogComponent } from './custom-tool-editor/custom-tool-dialog.component';
import { PythonCodeToolCard } from './models/pythonTool-card.model';
import { PageHeaderComponent } from '../../shared/components/header/page-header.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';

@Component({
  selector: 'app-tools',
  standalone: true,
  imports: [
    CommonModule,
    NgFor,
    NgIf,

    FormsModule,
    PageHeaderComponent,
    SpinnerComponent,
    ScrollingModule,
  ],
  templateUrl: './tools.component.html',
  styleUrls: ['./tools.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild(CdkScrollable) public scrollable!: CdkScrollable;

  public tools: any[] = []; // Standard tools
  public pythonTools: PythonCodeToolCard[] = []; // Python tools
  public searchTerm: string = '';
  public isLoading = signal<boolean>(true);
  public activeToolType: 'common' | 'python' = 'common'; // Track active tool type

  private subscriptions: Subscription = new Subscription();

  constructor(
    private readonly toolsService: BuiltinToolsService,
    private readonly pythonCodeToolService: PythonCodeToolService, // Inject Python service
    private readonly cdr: ChangeDetectorRef,
    private readonly scrollDispatcher: ScrollDispatcher,
    private readonly cdkDialog: Dialog
  ) {}

  public ngOnInit(): void {
    this.fetchTools();
  }

  public ngAfterViewInit(): void {
    if (this.scrollable) {
      const scrollSub: Subscription = this.scrollDispatcher
        .scrolled()
        .subscribe(() => {
          this.cdr.markForCheck();
        });
      this.subscriptions.add(scrollSub);
    }
  }

  public ngOnDestroy(): void {
    this.subscriptions.unsubscribe();
  }

  // Set active tool type
  public setActiveToolType(type: 'common' | 'python'): void {
    this.activeToolType = type;
    this.cdr.markForCheck();
  }

  // Filter standard tools
  public get filteredTools(): any[] {
    const query = this.searchTerm.toLowerCase().trim();
    return this.tools.filter(
      (tool: any) =>
        tool.name.toLowerCase().includes(query) ||
        tool.description.toLowerCase().includes(query)
    );
  }

  // Filter Python tools
  public get filteredPythonTools(): PythonCodeToolCard[] {
    const query = this.searchTerm.toLowerCase().trim();
    return this.pythonTools.filter(
      (tool: PythonCodeToolCard) =>
        tool.name.toLowerCase().includes(query) ||
        tool.description.toLowerCase().includes(query)
    );
  }

  // Update search term from header
  public onSearchInput(term: string): void {
    this.searchTerm = term;
    this.cdr.markForCheck();
  }

  public onToolEnabledUpdated(tool: any): void {
    // Store the original value in case we need to revert
    const originalEnabled = tool.enabled;
    // Create a new value (toggled)
    const newEnabledValue = originalEnabled;

    // Send only the enabled field to the backend via PATCH
    this.toolsService
      .patchTool(tool.id, { enabled: newEnabledValue })
      .subscribe({
        next: (updatedTool) => {
          console.log('Tool enabled status updated successfully:', updatedTool);

          // Update the tool in the array with the response from the server
          this.tools = this.tools.map((t) =>
            t.id === tool.id ? { ...t, enabled: newEnabledValue } : t
          );

          this.cdr.markForCheck();
        },
        error: (error: unknown) => {
          console.error('Error updating tool enabled status:', error);

          // No need to manually revert the local array - we never changed it
          // Just notify the user of the error
          alert('Failed to update tool. Please try again.');

          this.cdr.markForCheck();
        },
      });
  }
  public onPythonToolEnabledUpdated(tool: PythonCodeToolCard): void {}
  public openConfigurationDialog(tool: any): void {
    const dialogRef = this.cdkDialog.open(ToolConfigurationDialogComponent, {
      data: {
        tool: tool,
      },
    });

    dialogRef.closed.subscribe((result) => {
      if (result) {
        console.log(result);
      }
    });
  }
  public openPythonToolConfigurationDialog(tool: PythonCodeToolCard): void {
    const dialogRef = this.cdkDialog.open(CustomToolDialogComponent, {
      data: {
        pythonTools: this.pythonTools,
        selectedTool: tool, // pass the selected tool
      },
    });

    dialogRef.closed.subscribe((result) => {
      if (result) {
        // Add the extra fields to the updated tool
        const toolWithExtras: any = {
          ...result,
          label: 'python',
          enabled: true,
        };
        // Find the index of the tool to update (using the tool's id)
        const index = this.pythonTools.findIndex(
          (t) => t.id === toolWithExtras.id
        );
        if (index !== -1) {
          this.pythonTools[index] = toolWithExtras;
          console.log('Tool updated:', toolWithExtras);
        }
        this.cdr.markForCheck();
      }
    });
  }

  private fetchTools(): void {
    const labels: string[] = [
      'search',
      'files',
      'coding',
      'automation',
      'analysis',
    ];

    const loadStartTime = Date.now();

    const toolsSubscription: Subscription = forkJoin({
      standardTools: this.toolsService.getTools(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
    })
      .pipe(
        finalize(() => {
          // Ensure minimum loading time of 500ms
          const loadTime = Date.now() - loadStartTime;
          const remainingTime = Math.max(0, 500 - loadTime);

          setTimeout(() => {
            this.isLoading.set(false);
            this.cdr.markForCheck();
          }, remainingTime);
        })
      )
      .subscribe({
        next: ({ standardTools, pythonTools }) => {
          console.log('🛠️ Standard Tools:', standardTools);
          console.log('🐍 Python Code Tools:', pythonTools);

          // Assign a random label to each tool
          this.tools = standardTools
            .map((tool: any) => ({
              ...tool,
              label: labels[Math.floor(Math.random() * labels.length)],
            }))
            .sort((a, b) => b.id - a.id); // Sort by id descending

          this.pythonTools = pythonTools
            .map((tool: PythonCodeToolCard) => ({
              ...tool,
              label: 'python',
              enabled: true,
            }))
            .sort((a, b) => b.id - a.id); // Sort by id descending

          this.cdr.markForCheck();
        },
        error: (err: unknown) => {
          console.error('❌ Error fetching tools:', err);
          this.isLoading.set(false);
          this.cdr.markForCheck();
        },
      });

    this.subscriptions.add(toolsSubscription);
  }
  public openCustomToolDialog(): void {
    const dialogRef = this.cdkDialog.open(CustomToolDialogComponent, {
      data: { pythonTools: this.pythonTools },
    });

    dialogRef.closed.subscribe((result) => {
      if (result) {
        // Here, we assume that result is an object representing the created tool.
        // Add extra fields and then push the new tool to the array.
        const toolWithExtras: any = {
          ...result,
          label: 'python',
          enabled: true,
        };
        this.pythonTools.unshift(toolWithExtras);
        // Automatically switch to Python tools tab when creating a new Python tool
        this.activeToolType = 'python';
        console.log('New tool added:', toolWithExtras);
        this.cdr.markForCheck();
      }
    });
  }
  public onPythonToolDelete(tool: PythonCodeToolCard): void {
    this.pythonCodeToolService.deletePythonCodeTool(tool.id).subscribe({
      next: () => {
        // Remove the deleted tool from the array
        this.pythonTools = this.pythonTools.filter((t) => t.id !== tool.id);
        console.log('Deleted tool:', tool);
        this.cdr.markForCheck();
      },
      error: (error) => {
        console.error('Error deleting tool:', error);
      },
    });
  }

  public trackByToolId(index: number, tool: { id: number }): number {
    return tool.id;
  }
}
