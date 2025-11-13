import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnInit,
  Output,
  EventEmitter,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule, NgFor } from '@angular/common';
import { ProjectsStorageService } from '../../../../features/projects/services/projects-storage.service';
import { GetProjectRequest } from '../../../../features/projects/models/project.model';
import { NodeType } from '../../../core/enums/node-type';

@Component({
  selector: 'app-flow-projects-context-menu',
  imports: [CommonModule, NgFor],
  standalone: true,
  template: `
    <ul>
      <li
        *ngFor="let project of filteredProjects"
        (click)="onProjectClicked(project)"
      >
        <i class="ti ti-folder"></i>
        <span class="project-name">{{ project.name }}</span>
      </li>
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
export class FlowProjectsContextMenuComponent implements OnInit {
  @Input() public searchTerm: string = '';
  @Output() public nodeSelected: EventEmitter<{
    type: NodeType;
    data: any;
  }> = new EventEmitter();
  public projects: GetProjectRequest[] = [];

  constructor(
    private projectsService: ProjectsStorageService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.projectsService.getProjects().subscribe({
      next: (projects: GetProjectRequest[]) => {
        this.projects = projects;

        this.cdr.markForCheck();
      },
      error: (err) => console.error('Error fetching projects:', err),
    });
  }

  public get filteredProjects(): GetProjectRequest[] {
    return this.projects.filter((project) =>
      project.name.toLowerCase().includes(this.searchTerm.toLowerCase())
    );
  }

  public onProjectClicked(project: GetProjectRequest): void {
    this.nodeSelected.emit({ type: NodeType.PROJECT, data: project });
  }
}
