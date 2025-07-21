import {
  Component,
  Input,
  Output,
  EventEmitter,
  OnChanges,
  SimpleChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { ToolConfig } from '../../../../features/tools/models/tool_config.model';
import { NgClass, NgFor, NgIf } from '@angular/common';

@Component({
  selector: 'app-tool-config-list',
  template: `
    <div class="config-list-wrapper">
      <!-- Search Input -->
      <div
        class="search-input-wrapper"
        [ngClass]="{ 'input-has-content': searchHasContent }"
      >
        <input
          type="text"
          class="search-input"
          placeholder="Search configurations"
          (input)="onSearch($event)"
        />
      </div>

      <!-- Scrollable content area -->
      <div class="list-content-wrapper">
        <div *ngIf="filteredConfigs.length === 0" class="no-configs-message">
          No configurations available. Please create a new one.
        </div>

        <ul class="config-list" *ngIf="filteredConfigs.length > 0">
          <li
            *ngFor="let config of filteredConfigs"
            (click)="onSelect(config)"
            [class.selected]="config === selectedConfig"
            tabindex="0"
            role="button"
            (keydown.enter)="onSelect(config)"
            (keydown.space)="onSelect(config)"
          >
            <div class="config-item">
              <span class="config-name">{{ config.name }}</span>
              <!-- Delete Icon -->
              <button
                class="delete-button"
                (click)="onDelete(config, $event)"
                aria-label="Delete Configuration"
              ></button>
            </div>
          </li>
        </ul>
      </div>

      <!-- "Create New" button stays at the bottom, outside the scrollable area -->
      <button class="create-config-button" (click)="onCreateNewConfig()">
        Create new form
      </button>
    </div>
  `,
  styles: [
    `
      :host {
        height: 100%;
        height: 600px;

        .config-list-wrapper {
          display: flex;
          flex-direction: column;
          height: 100%;
          min-height: 0;
          padding: 1.25rem;
          background-color: var(--gray-850);
          border-radius: 8px;
        }

        /* Search Input */
        .search-input-wrapper {
          flex-shrink: 0;
          display: flex;
          align-items: center;
          background-color: var(--gray-800);
          border: 1px solid var(--gray-750);
          border-radius: 6px;
          padding: 0.625rem 0.875rem;
          margin-bottom: 1.25rem;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
          transition: all 0.2s ease;

          &.input-has-content,
          &:focus-within {
            border-color: var(--gray-600);
            box-shadow: 0 0 0 1px var(--gray-600), 0 2px 4px rgba(0, 0, 0, 0.2);

            .search-icon {
              color: var(--gray-600);
            }

            .search-input {
              color: var(--white);
            }
          }

          .search-icon {
            color: var(--gray-500);
            margin-right: 0.75rem;
            font-size: 1.25rem;
            transition: color 0.2s ease;
          }

          .search-input {
            border: none;
            background: transparent;
            outline: none;
            font-size: 0.9375rem;
            color: var(--gray-200);
            width: 100%;
            transition: color 0.2s ease;

            &::placeholder {
              color: var(--gray-600);
            }
          }
        }

        /* List Content Wrapper */
        .list-content-wrapper {
          flex: 1 1 auto;
          overflow-y: auto;
          margin: 0 -0.25rem;
          padding: 0 0.25rem;

          &::-webkit-scrollbar {
            width: 6px;
          }

          &::-webkit-scrollbar-track {
            background: var(--gray-800);
            border-radius: 3px;
          }

          &::-webkit-scrollbar-thumb {
            background-color: var(--gray-700);
            border-radius: 3px;

            &:hover {
              background-color: var(--gray-600);
            }
          }

          .no-configs-message {
            color: var(--gray-400);
            font-size: 0.9375rem;
            margin: 1.5rem 0;
            text-align: center;
            font-style: italic;
          }

          /* Config List */
          .config-list {
            padding: 0;
            margin: 0;
            list-style: none;

            li {
              display: flex;
              align-items: center;
              padding: 0.75rem 0.875rem;
              margin-bottom: 0.5rem;
              cursor: pointer;
              border-radius: 6px;
              border-left: 2px solid transparent;
              background-color: var(--gray-800);
              color: var(--gray-300);
              transition: all 0.2s ease-in-out;
              animation: fadeIn 0.2s ease-out;
              animation-fill-mode: both;

              &:nth-child(1) {
                animation-delay: 0.05s;
              }
              &:nth-child(2) {
                animation-delay: 0.1s;
              }
              &:nth-child(3) {
                animation-delay: 0.15s;
              }
              &:nth-child(4) {
                animation-delay: 0.2s;
              }
              &:nth-child(5) {
                animation-delay: 0.25s;
              }

              &:hover {
                background-color: var(--gray-750);
                transform: translateX(2px);
              }

              &.selected {
                background-color: var(--gray-750);
                border-left: 2px solid var(--gray-600);
              }

              .config-item {
                display: flex;
                align-items: center;
                justify-content: space-between;
                width: 100%;

                .config-name {
                  flex-grow: 1;
                  font-size: 0.9375rem;
                  white-space: nowrap;
                  overflow: hidden;
                  text-overflow: ellipsis;
                  color: var(--gray-200);
                  padding-right: 0.5rem;
                }

                .delete-button {
                  background: transparent;
                  border: none;
                  cursor: pointer;
                  padding: 0.375rem;
                  margin-left: 0.25rem;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  border-radius: 4px;
                  transition: all 0.2s ease-in-out;

                  &:hover {
                    background-color: rgba(103, 103, 103, 0.2);

                    mat-icon {
                      color: var(--gray-400);
                    }
                  }

                  mat-icon {
                    font-size: 1.125rem;
                    color: var(--gray-500);
                    transition: color 0.2s ease;
                  }
                }
              }

              &:focus,
              .delete-button:focus {
                outline: 2px solid var(--gray-600);
                outline-offset: 2px;

                &:not(:focus-visible) {
                  outline: none;
                }
              }
            }
          }
        }

        /* Create New Button */
        .create-config-button {
          flex-shrink: 0;
          margin-top: 1.25rem;
          padding: 0.75rem 1rem;
          font-size: 0.9375rem;
          font-weight: 500;
          color: var(--white);
          background-color: var(--gray-600);
          border: none;
          border-radius: 6px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          transition: all 0.2s ease-in-out;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);

          &:hover {
            background-color: var(--gray-700);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.25);
          }

          &:active {
            background-color: var(--gray-750);
            transform: translateY(1px);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
          }

          &:disabled {
            background-color: var(--gray-700);
            opacity: 0.6;
            cursor: not-allowed;
            box-shadow: none;
          }

          &:focus {
            outline: 2px solid var(--gray-600);
            outline-offset: 2px;

            &:not(:focus-visible) {
              outline: none;
            }
          }

          mat-icon {
            font-size: 1.25rem;
          }
        }
      }

      @keyframes fadeIn {
        from {
          opacity: 0;
          transform: translateY(5px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgFor, NgIf, NgClass],
  standalone: true,
})
export class ToolConfigListComponent implements OnChanges {
  @Input() toolConfigs: ToolConfig[] = [];
  @Input() selectedConfig: ToolConfig | null = null;
  @Output() configFromListSelected = new EventEmitter<ToolConfig>();
  @Output() createNewConfig = new EventEmitter<void>();
  @Output() deleteConfig = new EventEmitter<ToolConfig>();

  // New output to notify parent about filtered configs
  @Output() filteredConfigsChange = new EventEmitter<ToolConfig[]>();

  filteredConfigs: ToolConfig[] = [];
  searchHasContent: boolean = false;
  private currentSearchQuery = '';

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['toolConfigs']) {
      this.applyFilter();
    }
  }

  onSelect(config: ToolConfig): void {
    this.configFromListSelected.emit(config);
  }

  onCreateNewConfig(): void {
    this.createNewConfig.emit();
  }

  onDelete(config: ToolConfig, event: MouseEvent): void {
    event.stopPropagation(); // Prevent list item click event
    this.deleteConfig.emit(config);
  }

  onSearch(event: Event): void {
    const inputElement = event.target as HTMLInputElement;
    this.currentSearchQuery = inputElement.value.toLowerCase().trim();
    this.searchHasContent = this.currentSearchQuery.length > 0;
    this.applyFilter();
  }

  private applyFilter(): void {
    if (this.currentSearchQuery === '') {
      this.filteredConfigs = [...this.toolConfigs];
    } else {
      this.filteredConfigs = this.toolConfigs.filter((config) =>
        config.name.toLowerCase().includes(this.currentSearchQuery)
      );
    }

    this.filteredConfigsChange.emit(this.filteredConfigs);
  }
}
