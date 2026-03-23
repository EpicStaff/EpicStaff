import {
    Component,
    Input,
    ChangeDetectionStrategy,
    Output,
    EventEmitter,
    inject,
    computed,
    OnInit,
    OnChanges,
    SimpleChanges,
    signal,
    ChangeDetectorRef,
} from '@angular/core';
import { GetProjectRequest } from '../../models/project.model';
import { NgClass, NgIf, NgFor, NgStyle } from '@angular/common';
import { TagComponent } from './tag.component';
import { ProjectMenuComponent } from './project-menu/project-menu.component';
import { ProjectTagsStorageService } from '../../services/project-tags-storage.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-project-card',
    standalone: true,
    imports: [
        NgIf,
        NgFor,
        NgStyle,
        TagComponent,
        ProjectMenuComponent,
        AppSvgIconComponent,
    ],
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
    private readonly projectTagsStorageService = inject(
        ProjectTagsStorageService
    );
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

    public readonly projectTags = computed(() => {
        const project = this.projectSignal();
        if (project && project.tags && project.tags.length > 0) {
            const tagNames = this.projectTagsStorageService.getTagNames(
                project.tags
            );

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
