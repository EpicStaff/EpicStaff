import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { ToggleSwitchComponent } from '../../../../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { TOOL_CATEGORIES_CONFIG } from '../../../../../../constants/built-in-tools-categories';
import { TOOL_PROVIDERS_AND_DESCRIPTIONS } from '../../../../../../constants/tool-providers-and-descriptions';
import { Tool } from '../../../../../../models/tool.model';

@Component({
    selector: 'app-built-in-tool-card',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, ToggleSwitchComponent, ButtonComponent],
    templateUrl: './built-in-tool-card.component.html',
    styleUrls: ['./built-in-tool-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BuiltInToolCardComponent {
    @Input() public tool!: Tool;
    @Input() public starred: boolean = false;
    @Output() public configure = new EventEmitter<Tool>();
    @Output() public enabledChange = new EventEmitter<{
        tool: Tool;
        enabled: boolean;
    }>();

    constructor(private cdr: ChangeDetectorRef) {}

    public getCategoryConfig(): {
        name: string;
        icon: string;
        toolIds: number[];
    } {
        return (
            TOOL_CATEGORIES_CONFIG.find((cat) => cat.toolIds.includes(this.tool.id)) ||
            TOOL_CATEGORIES_CONFIG.find((cat) => cat.name === 'Other')!
        );
    }

    public getCategory(): string {
        return this.getCategoryConfig().name;
    }

    public getIconName(): string {
        return this.getCategoryConfig().icon;
    }

    public get provider(): string {
        return TOOL_PROVIDERS_AND_DESCRIPTIONS[this.tool.id]?.provider || '';
    }

    public get toolDescription(): string {
        return TOOL_PROVIDERS_AND_DESCRIPTIONS[this.tool.id]?.description || '';
    }

    public get starIcon(): string {
        return this.starred ? 'star-filled' : 'star';
    }

    public onConfigure(): void {
        this.configure.emit(this.tool);
    }

    public onToggle(enabled: boolean): void {
        this.enabledChange.emit({ tool: this.tool, enabled });
    }

    public onStar(): void {
        this.starred = !this.starred;
        this.cdr.markForCheck();
    }
}