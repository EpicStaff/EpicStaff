import { OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, OnDestroy, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { getLabelColorOption, LabelDto } from '@shared/models';

import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolCardIcon, ToolCardMenuAction, ToolCardVM } from './tool-card.model';
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
export class ToolCardComponent implements OnDestroy {
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
    private readonly isMouseOnButton = signal<boolean>(false);
    private readonly isMouseOnMenu = signal<boolean>(false);
    private readonly isLabelsOpen = signal<boolean>(false);
    private closeTimeout: ReturnType<typeof setTimeout> | null = null;

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

    public onCheckboxHitClick(event: MouseEvent): void {
        const target = event.target as HTMLElement | null;
        if (target?.closest('app-checkbox')) return;
        this.onSelectToggle(!this.selected());
    }

    public onUsageChipClick(): void {
        this.menuAction.emit({ tool: this.tool(), action: 'show_used_places' });
    }

    public onStarClick(event: MouseEvent): void {
        event.stopPropagation();
        this.favoriteChange.emit({ tool: this.tool(), favorite: !this.tool().favorite });
    }

    public toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        const next = !this.menuOpen();
        this.menuOpen.set(next);
        if (next) {
            this.cancelCloseTimeout();
            this.isMouseOnButton.set(true);
            this.isMouseOnMenu.set(false);
        }
    }

    public closeMenu(): void {
        this.cancelCloseTimeout();
        this.menuOpen.set(false);
        this.isMouseOnButton.set(false);
        this.isMouseOnMenu.set(false);
    }

    public onButtonEnter(): void {
        this.isMouseOnButton.set(true);
        this.cancelCloseTimeout();
    }

    public onButtonLeave(): void {
        this.isMouseOnButton.set(false);
        this.scheduleClose();
    }

    public onMenuEnter(): void {
        this.isMouseOnMenu.set(true);
        this.cancelCloseTimeout();
    }

    public onMenuLeave(): void {
        this.isMouseOnMenu.set(false);
        this.scheduleClose();
    }

    public onOverlayOutsideClick(): void {
        if (this.isLabelsOpen()) return;
        this.closeMenu();
    }

    public onLabelsOpenChange(open: boolean): void {
        this.isLabelsOpen.set(open);
        if (open) {
            this.cancelCloseTimeout();
        } else {
            this.scheduleClose();
        }
    }

    private scheduleClose(): void {
        if (this.isLabelsOpen()) return;
        if (this.menuOpen() && !this.isMouseOnButton() && !this.isMouseOnMenu()) {
            this.closeTimeout = setTimeout(() => {
                if (!this.isLabelsOpen() && this.menuOpen() && !this.isMouseOnButton() && !this.isMouseOnMenu()) {
                    this.closeMenu();
                }
            }, 100);
        }
    }

    private cancelCloseTimeout(): void {
        if (this.closeTimeout) {
            clearTimeout(this.closeTimeout);
            this.closeTimeout = null;
        }
    }

    public ngOnDestroy(): void {
        this.cancelCloseTimeout();
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

    protected readonly ToolCardIcon = ToolCardIcon;
}
