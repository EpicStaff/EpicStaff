import { OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { getLabelColorOption, LabelDto } from '@shared/models';

import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolCardMenuAction, ToolCardVM } from './tool-card.model';
import { ToolCardMenuComponent } from './tool-card-menu.component';

@Component({
    selector: 'app-tool-card',
    imports: [
        CommonModule,
        AppSvgIconComponent,
        CheckboxComponent,
        MatTooltipModule,
        OverlayModule,
        ToolCardMenuComponent,
    ],
    templateUrl: './tool-card.component.html',
    styleUrls: ['./tool-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolCardComponent {
    public readonly tool = input.required<ToolCardVM>();
    public readonly selected = input<boolean>(false);
    public readonly showUsage = input<boolean>(false);

    public readonly configure = output<ToolCardVM>();
    public readonly selectedChange = output<{ tool: ToolCardVM; selected: boolean }>();
    public readonly favoriteChange = output<{ tool: ToolCardVM; favorite: boolean }>();
    public readonly menuAction = output<{ tool: ToolCardVM; action: ToolCardMenuAction }>();
    public readonly labelsChange = output<{ tool: ToolCardVM; labelIds: number[] }>();

    private readonly labelsStorage = inject(ToolsLabelsStorageService);

    public readonly menuOpen = signal<boolean>(false);

    public readonly labels = computed<LabelDto[]>(() => {
        const ids = new Set(this.tool().labelIds);
        return this.labelsStorage.labels().filter((l) => ids.has(l.id));
    });

    public onCardClick(): void {
        this.configure.emit(this.tool());
    }

    public onSelectToggle(next: boolean): void {
        this.selectedChange.emit({ tool: this.tool(), selected: next });
    }

    public onStarClick(event: MouseEvent): void {
        event.stopPropagation();
        this.favoriteChange.emit({ tool: this.tool(), favorite: !this.tool().favorite });
    }

    public toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menuOpen.update((v) => !v);
    }

    public closeMenu(): void {
        this.menuOpen.set(false);
    }

    public onMenuAction(action: ToolCardMenuAction): void {
        this.closeMenu();
        this.menuAction.emit({ tool: this.tool(), action });
    }

    public onMenuLabelsChanged(labelIds: number[]): void {
        this.closeMenu();
        this.labelsChange.emit({ tool: this.tool(), labelIds });
    }

    public onLabelsWheel(event: WheelEvent): void {
        const el = event.currentTarget as HTMLElement;
        if (event.deltaY === 0) return;
        el.scrollLeft += event.deltaY;
        event.preventDefault();
    }

    public chipBg(label: LabelDto): string {
        return getLabelColorOption(label.metadata?.color).chipBg;
    }

    public chipColor(label: LabelDto): string {
        return getLabelColorOption(label.metadata?.color).chipColor;
    }
}
