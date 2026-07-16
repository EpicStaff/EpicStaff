import { CommonModule, NgStyle } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    EntityMemoryPayload,
    LongTermMemoryPayload,
    Memory,
    ShortTermMemoryPayload,
} from '../../../models/memory.model';

@Component({
    selector: 'app-memory-item',
    standalone: true,
    imports: [CommonModule, NgStyle, AppSvgIconComponent, MatTooltip],
    template: `
        <div class="memory-item">
            <div class="memory-header">
                <span class="memory-type">{{ memory.payload.type }}</span>
                <div class="memory-header-right">
                    <span class="memory-date">{{ memory.payload.created_at | date: 'short' }}</span>
                    <button
                        class="delete-button"
                        matTooltip="Delete memory"
                        (click)="onDelete()"
                    >
                        <app-svg-icon
                            icon="x"
                            size="1rem"
                        />
                    </button>
                </div>
            </div>

            <div
                class="memory-content"
                [ngStyle]="{
                    'margin-bottom': memory.payload.type === 'user' ? '0' : '',
                }"
            >
                {{ memory.payload.data }}
            </div>

            @if (memory.payload.type !== 'user') {
                <button
                    class="details-toggle"
                    (click)="toggleDetails(memory.id)"
                >
                    <div class="toggle-left">
                        <app-svg-icon
                            icon="player-play-filled"
                            size="1rem"
                            [ngClass]="{ expanded: isExpanded(memory.id) }"
                        />
                        <span>Details</span>
                    </div>
                </button>

                <!-- Expandable Details Section -->
                <div
                    class="memory-details"
                    *ngIf="isExpanded(memory.id)"
                >
                    <!-- Entity Memory Details -->
                    @if (memory.payload.type === 'entity') {
                        <div class="memory-relationships">
                            <p class="details-title">Relationships:</p>
                            <p class="details-content">{{ getEntityRelationships(memory) }}</p>
                        </div>
                    }

                    <!-- Short Term Memory Details -->
                    @if (memory.payload.type === 'short_term') {
                        <div class="memory-observation">
                            <p class="details-title">Observation:</p>
                            <p class="details-content">{{ getShortTermObservation(memory) }}</p>
                        </div>
                    }

                    <!-- Long Term Memory Details -->
                    @if (memory.payload.type === 'long_term') {
                        <div class="memory-quality">
                            <p class="details-title">Quality: {{ getLongTermQuality(memory) }}/10</p>
                            <p class="details-title">Expected output: {{ getLongTermExpectedOutput(memory) }}</p>

                            @if (hasLongTermSuggestions(memory)) {
                                <div class="suggestions">
                                    <p class="details-title">Suggestions:</p>
                                    <ul class="suggestions-list">
                                        @for (suggestion of getLongTermSuggestions(memory); track $index) {
                                            <li>{{ suggestion }}</li>
                                        }
                                    </ul>
                                </div>
                            }
                        </div>
                    }
                </div>
            }
        </div>
    `,
    styles: [
        `
            .memory-item {
                background: var(--gray-800);
                border: 1px solid var(--gray-700);
                border-radius: var(--radius-lg);
                padding: var(--space-lg);
                margin-bottom: var(--space-md);
            }

            .memory-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: var(--space-md);
            }

            .memory-header-right {
                display: flex;
                align-items: center;
                gap: var(--space-sm);
            }

            .memory-type {
                font-size: var(--font-size-xs);
                font-weight: var(--font-weight-semibold);
                text-transform: capitalize;
                color: var(--color-text-secondary);
                background: var(--gray-750);
                padding: var(--space-2xs) var(--space-sm);
                border-radius: var(--radius-sm);
            }

            .memory-date {
                font-size: var(--font-size-xs);
                color: var(--color-text-secondary);
            }

            .delete-button {
                display: flex;
                align-items: center;
                justify-content: center;
                background: transparent;
                border: none;
                color: var(--color-text-secondary);
                cursor: pointer;
                padding: 0;
            }

            .delete-button:hover {
                color: var(--color-text-primary);
            }

            .memory-content {
                margin-bottom: var(--space-md);
                font-size: var(--font-size-md);
                line-height: 1.5;
                color: var(--color-text-primary);
            }

            .details-toggle {
                display: flex;
                align-items: center;
                justify-content: space-between;
                width: 100%;
                background-color: var(--gray-750);
                border: none;
                border-radius: var(--radius-sm);
                padding: var(--space-sm) var(--space-md);
                color: var(--color-text-secondary);
                font-size: var(--font-size-sm);
                cursor: pointer;
                margin-top: var(--space-md);
            }

            .details-toggle:hover {
                background-color: var(--gray-700);
            }

            .toggle-left {
                display: flex;
                align-items: center;
                gap: var(--space-sm);
            }

            .toggle-left app-svg-icon {
                transition: transform 0.2s ease;
            }

            .toggle-left app-svg-icon.expanded {
                transform: rotate(90deg);
            }

            .memory-details {
                background-color: var(--gray-750);
                border-radius: var(--radius-sm);
                padding: var(--space-md);
                padding-bottom: var(--space-2xs);
                margin-top: var(--space-sm);
                font-size: var(--font-size-sm);
            }

            .memory-relationships,
            .memory-observation,
            .memory-quality {
                margin-bottom: var(--space-sm);
            }

            .details-title {
                margin: 0 0 var(--space-2xs) 0;
                font-weight: var(--font-weight-medium);
                color: var(--color-text-secondary);
            }

            .details-content {
                margin: 0;
                white-space: pre-line;
                color: var(--color-text-primary);
            }

            .suggestions {
                margin-top: var(--space-sm);
            }

            .suggestions-list {
                margin: var(--space-2xs) 0 0 0;
                padding-left: var(--space-xl);
                color: var(--color-text-primary);
            }

            .suggestions-list li {
                margin-bottom: var(--space-2xs);
            }
        `,
    ],
})
export class MemoryItemComponent {
    @Input() memory!: Memory;
    @Output() deleteMemoryEvent = new EventEmitter<string>();
    @Output() toggleDetailsEvent = new EventEmitter<string>();

    private expandedItems = new Set<string>();

    toggleDetails(memoryId: string): void {
        if (this.expandedItems.has(memoryId)) {
            this.expandedItems.delete(memoryId);
        } else {
            this.expandedItems.add(memoryId);
        }
        this.toggleDetailsEvent.emit(memoryId);
    }

    isExpanded(memoryId: string): boolean {
        return this.expandedItems.has(memoryId);
    }

    onDelete(): void {
        this.deleteMemoryEvent.emit(this.memory.id);
    }

    // Memory type-specific methods
    getEntityRelationships(memory: Memory): string {
        if (memory.payload.type === 'entity') {
            return (memory.payload as EntityMemoryPayload).relationships || 'No relationships defined';
        }
        return '';
    }

    getShortTermObservation(memory: Memory): string {
        if (memory.payload.type === 'short_term') {
            return (memory.payload as ShortTermMemoryPayload).observation || 'No observation recorded';
        }
        return '';
    }

    getLongTermQuality(memory: Memory): number {
        if (memory.payload.type === 'long_term') {
            return (memory.payload as LongTermMemoryPayload).quality || 0;
        }
        return 0;
    }

    getLongTermExpectedOutput(memory: Memory): string {
        if (memory.payload.type === 'long_term') {
            return (memory.payload as LongTermMemoryPayload).expected_output || 'No expected output defined';
        }
        return '';
    }

    hasLongTermSuggestions(memory: Memory): boolean {
        if (memory.payload.type === 'long_term') {
            const suggestions = (memory.payload as LongTermMemoryPayload).suggestions;
            return Array.isArray(suggestions) && suggestions.length > 0;
        }
        return false;
    }

    getLongTermSuggestions(memory: Memory): string[] {
        if (memory.payload.type === 'long_term') {
            return (memory.payload as LongTermMemoryPayload).suggestions || [];
        }
        return [];
    }
}
