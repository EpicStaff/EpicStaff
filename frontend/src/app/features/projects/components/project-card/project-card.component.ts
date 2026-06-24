import { NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GetProjectRequest } from '../../models/project.model';
import { ProjectMenuComponent } from './project-menu/project-menu.component';

@Component({
    selector: 'app-project-card',
    standalone: true,
    imports: [NgStyle, ProjectMenuComponent, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './project-card.component.html',
    styleUrls: ['./project-card.component.scss'],
})
export class ProjectCardComponent {
    @Input() public project!: GetProjectRequest;
    @Output() public cardClick = new EventEmitter<void>();
    @Output() public actionClick = new EventEmitter<{
        action: string;
        project: GetProjectRequest;
    }>();

    public isMenuOpen = false;

    public getIconContainerStyle() {
        return {
            'background-color': '#333333',
        };
    }

    public onMenuToggle(isOpen: boolean): void {
        this.isMenuOpen = isOpen;
    }

    public onActionSelected(action: string): void {
        this.actionClick.emit({ action, project: this.project });
    }
}
