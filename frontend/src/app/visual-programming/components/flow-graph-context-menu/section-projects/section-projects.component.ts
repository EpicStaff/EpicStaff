import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';

import { GetProjectRequest } from '../../../../features/projects/models/project.model';
import { ProjectsStorageService } from '../../../../features/projects/services/projects-storage.service';
import { NodeType } from '../../../core/enums/node-type';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';

@Component({
    selector: 'app-flow-projects-context-menu',
    standalone: true,
    template: `
        <ul>
            @for (project of filteredProjects(); track project.id) {
                <li (click)="onProjectClicked(project)">
                    <i class="ti ti-folder"></i>
                    <span class="project-name">{{ project.name }}</span>
                </li>
            }
        </ul>
    `,
    styles: [
        `
            ul {
                list-style: none;
                padding: 0 16px;
                margin: 0;
            }
            li {
                display: flex;
                align-items: center;
                padding: 12px 16px;
                border-radius: 8px;
                cursor: pointer;
                transition: background 0.2s ease;
                gap: 16px;
                overflow: hidden;
                min-width: 0;
            }
            li:hover {
                background: #2a2a2a;
                color: #fff;
            }
            li i {
                font-size: 18px;
                color: #5672cd;
            }

            .project-name {
                flex: 1;
                overflow: hidden;
                white-space: nowrap;
                text-overflow: ellipsis;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowProjectsContextMenuComponent {
    public readonly searchTerm = input('');
    public readonly nodeSelected = output<CreateNodeRequest>();

    private readonly projectsService = inject(ProjectsStorageService);

    public readonly projects = toSignal(this.projectsService.getProjects(), {
        initialValue: [] as GetProjectRequest[],
    });
    public readonly filteredProjects = computed(() =>
        this.projects().filter((p) => p.name.toLowerCase().includes(this.searchTerm().toLowerCase()))
    );

    public onProjectClicked(project: GetProjectRequest): void {
        this.nodeSelected.emit({ type: NodeType.PROJECT, overrides: { data: project } });
    }
}
