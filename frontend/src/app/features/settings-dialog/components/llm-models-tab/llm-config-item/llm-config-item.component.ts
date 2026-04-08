import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { IconButtonComponent } from '../../../../../shared/components/buttons/icon-button/icon-button.component';
import { FullLLMConfig } from '../../../services/llms/full-llm-config.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';

@Component({
    selector: 'app-llm-config-item',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, IconButtonComponent, ButtonComponent],
    templateUrl: './llm-config-item.component.html',
    styleUrls: ['./llm-config-item.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmConfigItemComponent {
    @Input() config!: FullLLMConfig;

    @Output() favoriteToggled = new EventEmitter<{
        id: string | number;
        value: boolean;
    }>();
    @Output() enabledToggled = new EventEmitter<{
        id: string | number;
        value: boolean;
    }>();
    @Output() configureClicked = new EventEmitter<string | number>();
    @Output() deleteClicked = new EventEmitter<string | number>();

    public isFavorite: boolean = false;

    public getProviderIcon(): string {
        return getProviderIconPath(this.config.providerDetails?.name);
    }

    public toggleFavorite(): void {
        this.isFavorite = !this.isFavorite;
        this.favoriteToggled.emit({
            id: this.config.id,
            value: this.isFavorite,
        });
    }

    public getFavoriteButtonColor(): string {
        return this.isFavorite ? '#ffb800' : 'var(--color-text-secondary)';
    }

    public onEnabledToggle(value: boolean): void {
        this.enabledToggled.emit({ id: this.config.id, value });
    }

    public onConfigure(): void {
        this.configureClicked.emit(this.config.id);
    }

    public onDelete(): void {
        this.deleteClicked.emit(this.config.id);
    }

    public getFormattedTemperature(): string {
        if (this.config && typeof this.config.temperature === 'number') {
            const temp = Math.round(this.config.temperature * 100);
            return `${temp}°`;
        }
        return 'N/A';
    }
}
