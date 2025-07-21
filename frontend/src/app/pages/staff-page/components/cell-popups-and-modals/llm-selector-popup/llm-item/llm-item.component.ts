import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  OnChanges,
  SimpleChanges,
} from '@angular/core';
import { NgClass, NgIf } from '@angular/common';
import { MergedConfig } from '../../../../../../services/full-agent.service';
import { AppIconComponent } from '../../../../../../shared/components/app-icon/app-icon.component';
import { getProviderIconPath } from '../../../../../../features/settings-dialog/utils/get-provider-icon';

@Component({
  selector: 'app-llm-item',
  standalone: true,
  imports: [NgClass, NgIf, AppIconComponent],
  template: `
    <div class="llm-item-container">
      <div
        class="llm-item"
        [ngClass]="{ 'selected-item': isSelected }"
        (click)="onSelect()"
      >
        <app-icon
          [icon]="getProviderIcon(item)"
          size="16px"
          [ariaLabel]="item.provider_name || ''"
          class="provider-icon"
        ></app-icon>

        <div class="llm-name">
          {{ getModelName(item) }}
          <span *ngIf="item.custom_name" class="custom-name">
            ({{ item.custom_name }})
          </span>
        </div>

        <input
          type="checkbox"
          [checked]="isSelected"
          (click)="onCheckboxClick($event)"
        />
      </div>
    </div>
  `,
  styleUrls: ['./llm-item.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmItemComponent implements OnChanges {
  @Input() public item!: MergedConfig;
  @Input() public isSelected: boolean = false;
  @Input() public itemType: 'llm' | 'realtime' = 'llm';

  @Output() public itemSelected = new EventEmitter<MergedConfig>();

  constructor(private cdr: ChangeDetectorRef) {}

  ngOnChanges(changes: SimpleChanges): void {
    console.log('item', this.item);
    if (changes['isSelected']) {
      this.cdr.markForCheck();
    }
  }

  public onSelect(): void {
    console.log('LLM Item clicked:', this.item);
    console.log('Current isSelected state:', this.isSelected);
    this.itemSelected.emit(this.item);
  }

  public onCheckboxClick(event: Event): void {
    event.stopPropagation();
    console.log('Checkbox clicked:', this.item);
    this.itemSelected.emit(this.item);
  }

  public getModelName(config: MergedConfig): string {
    if (!config) return 'Unknown Model';

    // For MergedConfig objects
    if (config.model_name) {
      return config.model_name;
    }

    return 'Unnamed Model';
  }

  public getProviderIcon(config: MergedConfig): string {
    if (!config || !config.provider_name) {
      return 'llm-providers-logos/default';
    }
    return getProviderIconPath(config.provider_name);
  }
}
