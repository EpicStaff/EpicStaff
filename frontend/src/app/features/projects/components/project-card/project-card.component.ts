import { NgFor, NgIf, NgStyle } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    EventEmitter,
    inject,
    Input,
    OnChanges,
    OnInit,
    Output,
    signal,
    SimpleChanges,
} from '@angular/core';

import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { GetProjectRequest } from '../../models/project.model';
import { ProjectTagsStorageService } from '../../services/project-tags-storage.service';
import { ProjectMenuComponent } from './project-menu/project-menu.component';
import { TagComponent } from './tag.component';

@Component({
    selector: 'app-project-card',
    standalone: true,
    imports: [NgIf, NgFor, NgStyle, TagComponent, ProjectMenuComponent, AppIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './project-card.component.html',
    styleUrls: ['./project-card.component.scss'],
})
export class ProjectCardComponent implements OnInit, OnChanges {
    @Input() public project!: GetProjectRequest;
    @Output() public cardClick = new EventEmitter<void>();
    @Output() public actionClick = new EventEmitter<{
        action: string;
        project: GetProjectRequest;
    }>();
    private readonly projectTagsStorageService = inject(ProjectTagsStorageService);
    private readonly cdr = inject(ChangeDetectorRef);

    private readonly projectSignal = signal<GetProjectRequest | null>(null);

    public isMenuOpen = false;
    public readonly maxVisibleTags = 2;

    ngOnInit(): void {
        if (this.project) {
            this.projectSignal.set(this.project);
        }
    }

    public getIconContainerStyle() {
        return {
            'background-color': '#333333',
        };
    }

    public getIconStyle() {
        return {
            color: 'var(--accent-color)',
        };
    }

    public getProjectIconPath(): string {
        return 'ui/project';
    }

    public readonly projectTags = computed(() => {
        const project = this.projectSignal();
        if (project && project.tags && project.tags.length > 0) {
            const tagNames = this.projectTagsStorageService.getTagNames(project.tags);

            return tagNames;
        }
        return [];
    });

    public readonly displayedTags = computed(() => {
        const tags = this.projectTags();
        if (!tags.length) return [];
        return tags.slice(0, this.maxVisibleTags);
    });

    public readonly hasMoreTags = computed(() => {
        return this.projectTags().length > this.maxVisibleTags;
    });

    public readonly additionalTagsCount = computed(() => {
        return Math.max(0, this.projectTags().length - this.maxVisibleTags);
    });

    constructor() {
        this.projectTagsStorageService.ensureLoaded().subscribe();
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['project'] && this.project) {
            this.projectSignal.set(this.project);

            this.cdr.markForCheck();
        }
    }

    public onMenuToggle(isOpen: boolean): void {
        this.isMenuOpen = isOpen;
    }

    public onActionSelected(action: string): void {
        this.actionClick.emit({ action, project: this.project });
    }
}
