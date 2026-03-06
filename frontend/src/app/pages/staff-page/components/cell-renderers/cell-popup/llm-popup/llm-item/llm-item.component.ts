import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { NgClass, NgIf } from '@angular/common';
import { MergedConfig } from '../../../../../../../features/staff/services/full-agent.service';
import { AppIconComponent } from '../../../../../../../shared/components/app-icon/app-icon.component';
import { getProviderIconPath } from '../../../../../../../features/settings-dialog/constants/provider-icons.constants';

@Component({
  selector: 'app-llm-item',
  templateUrl: './llm-item.component.html',
  styleUrls: ['./llm-item.component.scss'],
  standalone: true,
  imports: [NgClass, NgIf, AppIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmItemComponent {
  @Input() public item!: MergedConfig;
  @Input() public isSelected: boolean = false;
  @Input() public itemType: 'llm' | 'realtime' = 'llm';

  @Output() public itemSelected = new EventEmitter<MergedConfig>();

  public onSelect(): void {
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
