import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { Memory, MemoryType } from '../../models/memory.model';
import { MemoryItemComponent } from './memory-item/memory-item.component';

@Component({
    selector: 'app-memories-sidebar',
    standalone: true,
    imports: [CommonModule, MemoryItemComponent, AppSvgIconComponent],
    template: `
        <!-- Memories Sidebar Overlay -->
        <div
            class="sidebar-overlay"
            *ngIf="isOpen"
            (click)="close.emit()"
        ></div>

        <!-- Memories Sidebar -->
        <div
            class="memories-sidebar"
            [class.open]="isOpen"
        >
            <div class="sidebar-header">
                <h2>Session Memories ({{ memories.length }})</h2>
                <button
                    class="close-button"
                    (click)="close.emit()"
                >
                    <app-svg-icon
                        icon="x"
                        size="1rem"
                    />
                </button>
            </div>

            <div class="sidebar-content">
                <div class="memory-filters">
                    <div class="filter-chips">
                        <button
                            class="filter-chip"
                            [class.active]="activeFilter === 'all'"
                            (click)="setFilter('all')"
                        >
                            All ({{ memories.length }})
                        </button>
                        <button
                            class="filter-chip"
                            [class.active]="activeFilter === 'entity'"
                            (click)="setFilter('entity')"
                            *ngIf="getMemoriesByType('entity').length > 0"
                        >
                            Entity ({{ getMemoriesByType('entity').length }})
                        </button>
                        <button
                            class="filter-chip"
                            [class.active]="activeFilter === 'short_term'"
                            (click)="setFilter('short_term')"
                            *ngIf="getMemoriesByType('short_term').length > 0"
                        >
                            Short Term ({{ getMemoriesByType('short_term').length }})
                        </button>
                        <button
                            class="filter-chip"
                            [class.active]="activeFilter === 'long_term'"
                            (click)="setFilter('long_term')"
                            *ngIf="getMemoriesByType('long_term').length > 0"
                        >
                            Long Term ({{ getMemoriesByType('long_term').length }})
                        </button>
                        <button
                            class="filter-chip"
                            [class.active]="activeFilter === 'user'"
                            (click)="setFilter('user')"
                            *ngIf="getMemoriesByType('user').length > 0"
                        >
                            User ({{ getMemoriesByType('user').length }})
                        </button>
                    </div>
                </div>

                <div class="memories-list">
                    @for (memory of filteredMemories; track memory.id) {
                        <app-memory-item
                            [memory]="memory"
                            (deleteMemoryEvent)="deleteMemory($event)"
                            (toggleDetailsEvent)="toggleDetails($event)"
                        ></app-memory-item>
                    }
                    @if (filteredMemories.length === 0) {
                        <div class="no-memories">
                            <p>No memories found for the selected filter.</p>
                        </div>
                    }
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            /* Sidebar Overlay */
            .sidebar-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, 0.5);
                z-index: 100;
            }

            /* Memories Sidebar */
            .memories-sidebar {
                position: fixed;
                top: 0;
                right: -400px;
                width: 400px;
                height: 100%;
                background-color: var(--gray-900);
                border-left: 1px solid var(--gray-800);
                z-index: 101;
                transition: right 0.3s ease;
                display: flex;
                flex-direction: column;

                &.open {
                    right: 0;
                }
            }

            .sidebar-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                padding-bottom: 6px;
                h2 {
                    margin: 0;
                    font-size: 18px;
                    font-weight: 500;
                    color: var(--white);
                }

                .close-button {
                    background: none;
                    border: none;
                    color: var(--gray-400);
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;

                    &:hover {
                        color: var(--white);
                    }
                }
            }

            .sidebar-content {
                flex: 1;
                overflow-y: auto;
                padding: 0;
            }

            /* Memory Filters */
            .memory-filters {
                padding: 12px 20px;
                border-bottom: 1px solid var(--gray-800);

                .filter-chips {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                }

                .filter-chip {
                    background-color: var(--gray-800);
                    border: none;
                    border-radius: 16px;
                    padding: 6px 12px;
                    font-size: 13px;
                    color: var(--gray-300);
                    cursor: pointer;

                    &:hover {
                        background-color: var(--gray-700);
                    }

                    &.active {
                        background-color: var(--accent-color);
                        color: var(--white);
                    }
                }
            }

            /* Memories List */
            .memories-list {
                padding: 16px 20px;

                .no-memories {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    padding: 40px 0;
                    color: var(--gray-400);
                }
            }
        `,
    ],
})
export class MemoriesSidebarComponent {
    @Input() isOpen = false;
    @Input() memories: Memory[] = [];
    @Output() close = new EventEmitter<void>();
    @Output() deleteMemoryEvent = new EventEmitter<string>();

    public activeFilter: MemoryType | 'all' = 'all';
    private expandedMemories: Set<string> = new Set();

    get filteredMemories(): Memory[] {
        if (this.activeFilter === 'all') {
            return this.memories;
        }
        return this.memories.filter((memory) => memory.payload.type === this.activeFilter);
    }

    // Filter methods
    getMemoriesByType(type: MemoryType): Memory[] {
        return this.memories.filter((memory) => memory.payload.type === type);
    }

    setFilter(filter: MemoryType | 'all'): void {
        this.activeFilter = filter;
    }

    // Details toggle methods
    toggleDetails(memoryId: string): void {
        if (this.expandedMemories.has(memoryId)) {
            this.expandedMemories.delete(memoryId);
        } else {
            this.expandedMemories.add(memoryId);
        }
    }

    isExpanded(memoryId: string): boolean {
        return this.expandedMemories.has(memoryId);
    }

    // Delete memory method
    deleteMemory(memoryId: string): void {
        this.deleteMemoryEvent.emit(memoryId);
    }
}
