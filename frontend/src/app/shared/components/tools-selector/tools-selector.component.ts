import {
  Component,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Input,
  Output,
  EventEmitter,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { forkJoin, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import {
  FullToolConfigService,
  FullToolConfig,
} from '../../../services/full-tool-config.service';
import { PythonCodeToolService } from '../../../user-settings-page/tools/custom-tool-editor/services/pythonCodeToolService.service';
import { GetPythonCodeToolRequest } from '../../../features/tools/models/python-code-tool.model';
import { GetToolConfigRequest } from '../../../features/tools/models/tool_config.model';
import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';
import { AppIconComponent } from '../app-icon/app-icon.component';

@Component({
  selector: 'app-tools-selector',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    IconButtonComponent,
    AppIconComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <!-- Tools Selection Button -->
    <div class="tools-selector">
      <div class="tools-display" (click)="openToolsDialog()">
        <div *ngIf="totalSelectedTools === 0" class="no-tools-selected">
          Select tools
        </div>
        <div *ngIf="totalSelectedTools > 0" class="tools-summary">
          {{ totalSelectedTools }} tool(s) selected
        </div>
        <div class="tools-selector-icon">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M19 9L12 16L5 9"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </div>
      </div>
    </div>

    <!-- Tools Dialog -->
    <div class="tools-dialog-overlay" *ngIf="showToolsDialog">
      <div class="tools-dialog">
        <!-- Header -->
        <div class="tools-dialog-header">
          <div class="header-title">
            <app-icon icon="ui/tools" size="1.25rem"></app-icon>
            <span>Select Tools</span>
          </div>
          <app-icon-button
            icon="ui/x"
            ariaLabel="Close dialog"
            size="1.5rem"
            (onClick)="closeToolsDialog()"
          ></app-icon-button>
        </div>

        <!-- Search and Tabs -->
        <div class="tools-header">
          <div class="search-bar">
            <input
              type="text"
              [(ngModel)]="toolsSearchTerm"
              placeholder="Search tools..."
            />
          </div>
          <div class="tools-tabs">
            <button
              [class.active]="!showPythonTools"
              (click)="toggleToolType(false)"
            >
              Built-in Tools
            </button>
            <button
              [class.active]="showPythonTools"
              (click)="toggleToolType(true)"
            >
              Custom Tools
            </button>
          </div>
        </div>

        <!-- Body -->
        <div class="tools-dialog-body">
          <!-- Loading State -->
          <div *ngIf="isLoadingTools" class="tools-loading">
            <div class="spinner">
              <div class="bounce1"></div>
              <div class="bounce2"></div>
              <div class="bounce3"></div>
            </div>
            <div class="loading-text">Loading tools...</div>
          </div>

          <!-- Built-in Tools List -->
          <div *ngIf="!isLoadingTools && !showPythonTools" class="tools-list">
            <!-- Empty State -->
            <div *ngIf="filteredBuiltinTools.length === 0" class="empty-state">
              No built-in tools found
            </div>

            <!-- Tools List -->
            <div *ngFor="let tool of filteredBuiltinTools" class="tool-group">
              <div
                class="tool-header"
                (click)="
                  tool.tool_fields.length > 0
                    ? toggleToolExpanded(tool)
                    : toggleSimpleTool(tool)
                "
              >
                <div class="tool-info">
                  <div class="tool-name">{{ tool.name }}</div>
                  <div class="tool-description">
                    {{ tool.description || 'No description available' }}
                  </div>
                </div>
                <!-- Show checkbox for tools with no tool_fields -->
                <div
                  *ngIf="tool.tool_fields.length === 0"
                  class="tool-checkbox"
                >
                  <input
                    type="checkbox"
                    [checked]="isSimpleToolSelected(tool)"
                    (click)="$event.stopPropagation(); toggleSimpleTool(tool)"
                  />
                </div>
                <!-- Show expansion icon for tools with tool_fields -->
                <div
                  *ngIf="tool.tool_fields.length > 0"
                  class="expansion-icon"
                  [class.expanded]="expandedTools.has(tool.id)"
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      d="M6 9L12 15L18 9"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                </div>
              </div>

              <!-- Tool configs -->
              <div *ngIf="expandedTools.has(tool.id)" class="tool-configs">
                <div
                  *ngIf="tool.toolConfigs.length === 0"
                  class="empty-configs"
                >
                  No configurations available
                </div>
                <div
                  *ngFor="let config of tool.toolConfigs"
                  class="tool-config-item"
                  [class.selected]="selectedToolConfigIds.has(config.id)"
                  (click)="toggleToolConfig(config)"
                >
                  <div class="config-info">
                    <div class="config-name">{{ config.name }}</div>
                  </div>
                  <div class="tool-checkbox">
                    <input
                      type="checkbox"
                      [checked]="selectedToolConfigIds.has(config.id)"
                      (click)="
                        $event.stopPropagation(); toggleToolConfig(config)
                      "
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Python Tools List -->
          <div *ngIf="!isLoadingTools && showPythonTools" class="tools-list">
            <!-- Empty State -->
            <div *ngIf="filteredPythonTools.length === 0" class="empty-state">
              No custom tools found
            </div>

            <!-- Tools List -->
            <div
              *ngFor="let tool of filteredPythonTools"
              class="tool-item"
              [class.selected]="selectedPythonToolIds.has(tool.id)"
              (click)="togglePythonTool(tool)"
            >
              <div class="tool-info">
                <div class="tool-name">{{ tool.name }}</div>
                <div class="tool-description">
                  {{ tool.description || 'No description available' }}
                </div>
              </div>
              <div class="tool-checkbox">
                <input
                  type="checkbox"
                  [checked]="selectedPythonToolIds.has(tool.id)"
                  (click)="$event.stopPropagation(); togglePythonTool(tool)"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="tools-dialog-footer">
          <button class="cancel-btn" (click)="closeToolsDialog()">
            Cancel
          </button>
          <button class="save-btn" (click)="saveToolSelection()">
            Save Selection
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      // Tools selector
      .tools-selector {
        width: 100%;

        .tools-display {
          background-color: var(--color-input-background);
          border: 1px solid var(--color-input-border);
          border-radius: 6px;
          padding: 0.625rem 0.75rem;
          display: flex;
          justify-content: space-between;
          align-items: center;
          cursor: pointer;
          transition: border-color 0.2s ease;

          &:hover {
            border-color: var(--accent-color);
          }

          .no-tools-selected {
            color: rgba(255, 255, 255, 0.3);
            font-size: 0.875rem;
          }

          .tools-summary {
            color: var(--color-text-primary);
            font-size: 0.875rem;
          }

          .tools-selector-icon {
            color: var(--color-text-primary);
            opacity: 0.6;
          }
        }
      }

      // Tools Dialog
      .tools-dialog-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.5);
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .tools-dialog {
        width: 550px;
        max-height: 80vh;
        background-color: var(--color-modals-background);
        border-radius: 12px;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
        display: flex;
        flex-direction: column;
        overflow: hidden;

        .tools-dialog-header {
          padding: 1rem 1.25rem;
          display: flex;
          justify-content: space-between;
          align-items: center;

          .header-title {
            display: flex;
            align-items: center;
            gap: 0.75rem;

            app-icon {
              color: var(--accent-color);
            }

            span {
              font-size: 1.125rem;
              font-weight: 600;
              color: var(--color-text-primary);
            }
          }
        }

        .tools-header {
          padding: 0rem 1.25rem;
          border-bottom: 1px solid var(--color-divider-subtle);

          .search-bar {
            margin-bottom: 1rem;

            input {
              width: 100%;
              background-color: var(--color-input-background);
              border: 1px solid var(--color-input-border);
              border-radius: 6px;
              padding: 0.625rem 0.75rem;
              color: #fff;
              font-size: 0.875rem;
              outline: none;
              transition: border-color 0.2s ease;

              &:focus {
                border-color: var(--accent-color);
              }

              &::placeholder {
                color: rgba(255, 255, 255, 0.3);
              }
            }
          }

          .tools-tabs {
            display: flex;
            justify-content: start;
            gap: 1rem;

            button {
              background: transparent;
              border: none;
              padding: 0.5rem 1rem;
              font-size: 0.875rem;
              color: var(--color-text-secondary);
              cursor: pointer;
              transition: all 0.2s ease;
              position: relative;
              border-radius: 4px;

              &:hover {
                color: var(--color-text-primary);
                background-color: rgba(255, 255, 255, 0.05);
              }

              &.active {
                color: var(--accent-color);
                font-weight: 500;

                &::after {
                  content: '';
                  position: absolute;
                  bottom: -1px;
                  left: 0;
                  width: 100%;
                  height: 2px;
                  background-color: var(--accent-color);
                }
              }
            }
          }
        }

        .tools-dialog-body {
          padding: 1rem 1.25rem;
          overflow-y: auto;
          flex: 1;
          max-height: 50vh;

          .tools-loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 150px;

            .spinner {
              display: flex;
              gap: 0.5rem;

              .bounce1,
              .bounce2,
              .bounce3 {
                width: 10px;
                height: 10px;
                background-color: var(--accent-color);
                border-radius: 100%;
                animation: bounce 1.4s infinite ease-in-out both;
              }

              .bounce1 {
                animation-delay: -0.32s;
              }

              .bounce2 {
                animation-delay: -0.16s;
              }
            }

            .loading-text {
              margin-top: 1rem;
              color: var(--color-text-secondary);
              font-size: 0.875rem;
            }
          }

          .empty-state {
            padding: 2rem 0;
            text-align: center;
            color: var(--color-text-secondary);
            font-size: 0.875rem;
          }

          .tools-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;

            .tool-group {
              border-radius: 6px;
              overflow: hidden;
              border: 1px solid var(--color-divider-subtle);
              background: var(--color-input-background);

              .tool-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 0.75rem 1rem;
                transition: all 0.2s ease;
                cursor: pointer;

                &:hover {
                  background: rgba(104, 95, 255, 0.08);
                }

                .tool-info {
                  flex: 1;
                  overflow: hidden;

                  .tool-name {
                    font-size: 0.875rem;
                    font-weight: 500;
                    color: var(--color-text-primary);
                    margin-bottom: 0.25rem;
                  }

                  .tool-description {
                    font-size: 0.75rem;
                    color: var(--color-text-secondary);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                  }
                }

                .expansion-icon {
                  color: var(--color-text-secondary);
                  transition: transform 0.3s ease;

                  &.expanded {
                    transform: rotate(-180deg);
                  }
                }
              }

              .tool-configs {
                border-top: 1px solid var(--color-divider-subtle);

                .empty-configs {
                  padding: 0.75rem 1rem;
                  font-size: 0.75rem;
                  color: var(--color-text-secondary);
                  font-style: italic;
                }

                .tool-config-item {
                  display: flex;
                  justify-content: space-between;
                  align-items: center;
                  padding: 0.625rem 1rem;
                  padding-left: 2rem;
                  cursor: pointer;
                  background: rgba(255, 255, 255, 0.02);
                  transition: all 0.2s ease;

                  &:hover {
                    background: rgba(104, 95, 255, 0.08);
                  }

                  &.selected {
                    background: rgba(104, 95, 255, 0.12);
                  }

                  .config-info {
                    .config-name {
                      font-size: 0.8125rem;
                      color: var(--color-text-secondary);
                    }
                  }

                  .tool-checkbox input {
                    width: 16px;
                    height: 16px;
                    cursor: pointer;
                  }
                }
              }
            }

            .tool-item {
              display: flex;
              justify-content: space-between;
              align-items: center;
              padding: 0.75rem 1rem;
              border-radius: 6px;
              background: var(--color-input-background);
              transition: all 0.2s ease;
              cursor: pointer;
              border: 1px solid transparent;

              &:hover {
                border-color: var(--accent-color);
                background: rgba(104, 95, 255, 0.08);
              }

              &.selected {
                border-color: var(--accent-color);
                background: rgba(104, 95, 255, 0.12);
              }

              .tool-info {
                flex: 1;
                overflow: hidden;

                .tool-name {
                  font-size: 0.875rem;
                  font-weight: 500;
                  color: var(--color-text-primary);
                  margin-bottom: 0.25rem;
                }

                .tool-description {
                  font-size: 0.75rem;
                  color: var(--color-text-secondary);
                  white-space: nowrap;
                  overflow: hidden;
                  text-overflow: ellipsis;
                }
              }

              .tool-checkbox input {
                width: 16px;
                height: 16px;
                cursor: pointer;
              }
            }
          }
        }

        .tools-dialog-footer {
          padding: 1rem 1.25rem;
          border-top: 1px solid var(--color-divider-subtle);
          display: flex;
          justify-content: flex-end;
          gap: 0.75rem;

          button {
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;

            &.cancel-btn {
              background-color: transparent;
              border: 1px solid var(--color-divider);
              color: var(--color-text-secondary);

              &:hover {
                border-color: var(--color-text-primary);
                color: var(--color-text-primary);
              }
            }

            &.save-btn {
              background-color: var(--accent-color);
              border: 1px solid var(--accent-color);
              color: white;

              &:hover:not(:disabled) {
                filter: brightness(1.1);
              }

              &:disabled {
                opacity: 0.5;
                cursor: not-allowed;
                filter: grayscale(50%);
              }
            }
          }
        }
      }

      @keyframes bounce {
        0%,
        80%,
        100% {
          transform: scale(0);
        }
        40% {
          transform: scale(1);
        }
      }
    `,
  ],
})
export class ToolsSelectorComponent implements OnInit, OnDestroy {
  @Input() selectedConfiguredTools: number[] = [];
  @Input() selectedPythonCodeTools: number[] = [];

  @Output() configuredToolsChange = new EventEmitter<number[]>();
  @Output() pythonCodeToolsChange = new EventEmitter<number[]>();

  public builtinTools: FullToolConfig[] = [];
  public pythonTools: GetPythonCodeToolRequest[] = [];
  public isLoadingTools = false;
  public showToolsDialog = false;
  public toolsSearchTerm = '';
  public showPythonTools = false;

  // Selection tracking
  public selectedToolConfigIds = new Set<number>();
  public selectedPythonToolIds = new Set<number>();
  public expandedTools = new Set<number>();

  private readonly destroy$ = new Subject<void>();

  constructor(
    private fullToolConfigService: FullToolConfigService,
    private pythonCodeToolService: PythonCodeToolService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.loadTools();

    // Initialize selections from inputs
    if (
      this.selectedConfiguredTools &&
      this.selectedConfiguredTools.length > 0
    ) {
      this.selectedToolConfigIds = new Set<number>(
        this.selectedConfiguredTools
      );
    }

    if (
      this.selectedPythonCodeTools &&
      this.selectedPythonCodeTools.length > 0
    ) {
      this.selectedPythonToolIds = new Set<number>(
        this.selectedPythonCodeTools
      );
    }
  }

  private loadTools(): void {
    this.isLoadingTools = true;

    forkJoin({
      builtinTools: this.fullToolConfigService.getFullToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
    })
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: ({ builtinTools, pythonTools }) => {
          this.builtinTools = builtinTools;
          this.pythonTools = pythonTools;
          this.isLoadingTools = false;
          this.cdr.markForCheck();

          // Auto expand tools with selected configs
          this.autoExpandSelectedTools();
        },
        error: (error) => {
          console.error('Error loading tools:', error);
          this.isLoadingTools = false;
          this.cdr.markForCheck();
        },
      });
  }

  private autoExpandSelectedTools(): void {
    if (this.selectedToolConfigIds.size === 0) return;

    // Find which tools have selected configs and expand them
    for (const tool of this.builtinTools) {
      for (const config of tool.toolConfigs) {
        if (this.selectedToolConfigIds.has(config.id)) {
          this.expandedTools.add(tool.id);
          break;
        }
      }
    }

    this.cdr.markForCheck();
  }

  public openToolsDialog(): void {
    this.showToolsDialog = true;
    this.cdr.markForCheck();
  }

  public closeToolsDialog(): void {
    this.showToolsDialog = false;
    this.cdr.markForCheck();
  }

  public toggleToolType(isPython: boolean): void {
    this.showPythonTools = isPython;
    this.cdr.markForCheck();
  }

  public toggleToolExpanded(tool: FullToolConfig): void {
    if (this.expandedTools.has(tool.id)) {
      this.expandedTools.delete(tool.id);
    } else {
      this.expandedTools.add(tool.id);
    }
    this.cdr.markForCheck();
  }

  // Handle selection of simple tools (tools with empty tool_fields)
  public toggleSimpleTool(tool: FullToolConfig): void {
    // For tools with no tool_fields, we select the tool config directly
    // These tools should have exactly one toolConfig
    if (tool.toolConfigs.length > 0) {
      const config = tool.toolConfigs[0];
      this.toggleToolConfig(config);
    }
  }

  // Check if a simple tool is selected (by checking if its config is selected)
  public isSimpleToolSelected(tool: FullToolConfig): boolean {
    return (
      tool.toolConfigs.length > 0 &&
      this.selectedToolConfigIds.has(tool.toolConfigs[0].id)
    );
  }

  public toggleToolConfig(config: GetToolConfigRequest): void {
    if (this.selectedToolConfigIds.has(config.id)) {
      this.selectedToolConfigIds.delete(config.id);
    } else {
      this.selectedToolConfigIds.add(config.id);
    }
    this.cdr.markForCheck();
  }

  public togglePythonTool(tool: GetPythonCodeToolRequest): void {
    if (this.selectedPythonToolIds.has(tool.id)) {
      this.selectedPythonToolIds.delete(tool.id);
    } else {
      this.selectedPythonToolIds.add(tool.id);
    }
    this.cdr.markForCheck();
  }

  public saveToolSelection(): void {
    this.configuredToolsChange.emit(Array.from(this.selectedToolConfigIds));
    this.pythonCodeToolsChange.emit(Array.from(this.selectedPythonToolIds));
    this.closeToolsDialog();
  }

  public get filteredBuiltinTools(): FullToolConfig[] {
    if (!this.toolsSearchTerm) return this.builtinTools;

    const search = this.toolsSearchTerm.toLowerCase();
    return this.builtinTools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(search) ||
        tool.description?.toLowerCase().includes(search) ||
        tool.toolConfigs.some((config) =>
          config.name.toLowerCase().includes(search)
        )
    );
  }

  public get filteredPythonTools(): GetPythonCodeToolRequest[] {
    if (!this.toolsSearchTerm) return this.pythonTools;

    const search = this.toolsSearchTerm.toLowerCase();
    return this.pythonTools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(search) ||
        tool.description?.toLowerCase().includes(search)
    );
  }

  public get totalSelectedTools(): number {
    return this.selectedToolConfigIds.size + this.selectedPythonToolIds.size;
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
