import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { NgClass, NgFor, NgIf } from '@angular/common';
import { FullToolConfig } from '../../../../../../services/full-tool-config.service';
import { GetToolConfigRequest } from '../../../../../../features/tools/models/tool_config.model';
import { animate, style, transition, trigger } from '@angular/animations';
import { AppIconComponent } from '../../../../../../shared/components/app-icon/app-icon.component';

@Component({
  selector: 'app-tool-item',
  standalone: true,
  imports: [NgFor, NgIf, NgClass, AppIconComponent],
  template: `
    <div class="tool-item-container">
      <div
        class="tool-item"
        [ngClass]="{ 'selected-item': isSelected }"
        (click)="
          tool.tool_fields.length > 0 ? toggleToolConfigs() : onToolToggle()
        "
      >
        <app-icon icon="ui/tools" size="16px"></app-icon>
        <div class="tool-name">
          {{ tool.name }}
        </div>

        <!-- Chevron visible only for tools with non-empty tool_fields -->
        <span
          *ngIf="tool.tool_fields.length > 0"
          class="chevron-icon"
          [ngClass]="{ expanded: isExpanded }"
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
        </span>

        <!-- Checkbox visible only for tools with empty tool_fields -->
        <input
          *ngIf="tool.tool_fields.length === 0"
          type="checkbox"
          [checked]="isSelected"
          (click)="$event.stopPropagation(); onToolToggle()"
        />
      </div>

      <!-- Expanded tool configs section shown only for tools with non-empty tool_fields -->
      <div
        class="tool-configs"
        *ngIf="isExpanded && tool.tool_fields.length > 0"
        @expandCollapse
      >
        <div
          class="tool-config-item"
          *ngFor="let config of tool.toolConfigs"
          [ngClass]="{
            'selected-config': selectedConfigIds.has(config.id)
          }"
          (click)="onConfigToggle(config)"
        >
          <span class="config-name">{{ config.name }}</span>
          <span
            class="status-indicator"
            [ngClass]="config.is_completed ? 'green' : 'red'"
          ></span>
          <input
            type="checkbox"
            [checked]="selectedConfigIds.has(config.id)"
            (click)="$event.stopPropagation(); onConfigToggle(config)"
          />
        </div>
        <!-- Replace create config button with message -->
        <div *ngIf="tool.toolConfigs.length === 0" class="no-config-message">
          No configurations available
        </div>
      </div>
    </div>
  `,
  styleUrls: ['./tool-item.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  animations: [
    trigger('expandCollapse', [
      transition(':enter', [
        style({ height: '0', opacity: 0 }),
        animate(
          '300ms cubic-bezier(0.34, 1.56, 0.64, 1)',
          style({ height: '*', opacity: 1 })
        ),
      ]),
      transition(':leave', [
        style({ height: '*', opacity: 1 }),
        animate('200ms ease-out', style({ height: '0', opacity: 0 })),
      ]),
    ]),
  ],
})
export class ToolItemComponent {
  @Input() public tool!: FullToolConfig;
  @Input() public isSelected: boolean = false;
  @Input() public isExpanded: boolean = false;
  @Input() public selectedConfigIds: Set<number> = new Set<number>();

  @Output() public toolToggled = new EventEmitter<FullToolConfig>();
  @Output() public configToggled = new EventEmitter<GetToolConfigRequest>();
  @Output() public toolConfigsToggled = new EventEmitter<FullToolConfig>();

  public onToolToggle(): void {
    this.toolToggled.emit(this.tool);
  }

  public toggleToolConfigs(): void {
    this.toolConfigsToggled.emit(this.tool);
  }

  public onConfigToggle(config: GetToolConfigRequest): void {
    this.configToggled.emit(config);
  }
}
