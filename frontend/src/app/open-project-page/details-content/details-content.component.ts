import {
    Component,
    DestroyRef,
    EventEmitter,
    inject,
    Input,
    OnChanges,
    OnInit,
    Output,
    SimpleChanges,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { ProjectsStorageService } from '../../features/projects/services/projects-storage.service';
import { ToastService } from '../../services/notifications/toast.service';

@Component({
    selector: 'app-details-content',
    templateUrl: './details-content.component.html',
    styleUrls: ['./details-content.component.scss'],
    standalone: true,
    imports: [FormsModule],
})
export class DetailsContentComponent implements OnInit, OnChanges {
    @Input() public description!: string;
    @Input() public tags: string[] = [];
    @Input() public projectId!: number;
    @Output() public tagsUpdated: EventEmitter<string[]> = new EventEmitter<string[]>();
    @Output() public dirtyChange = new EventEmitter<boolean>();
    @Output() public detailsChange = new EventEmitter<{ description: string; tags: string[] }>();

    public internalDescription: string = '';
    public internalTags: string[] = [];
    public newTag: string = '';
    public duplicateTagName: string | null = null;
    public isEditingDescription: boolean = false;

    private readonly descriptionSubject: Subject<string> = new Subject();
    private readonly tagsSubject: Subject<string[]> = new Subject();

    private readonly destroyRef = inject(DestroyRef);

    constructor(
        private readonly projectsService: ProjectsStorageService,
        private readonly toastService: ToastService
    ) {}

    private initialDescription = '';
    private initialTags: string[] = [];

    public ngOnInit(): void {
        this.internalDescription = this.description ?? '';
        this.initialDescription = this.internalDescription;
        this.internalTags = [...this.tags];
        this.initialTags = [...this.internalTags];

        this.descriptionSubject
            .pipe(debounceTime(500), takeUntilDestroyed(this.destroyRef))
            .subscribe((updatedDescription: string) => {
                this.emitDetailsChange(updatedDescription, this.internalTags);
            });

        this.tagsSubject
            .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
            .subscribe((updatedTags: string[]) => {
                this.tagsUpdated.emit(updatedTags);
                this.emitDetailsChange(this.internalDescription, updatedTags);
            });
        this.emitDirty();
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['tags'] && !changes['tags'].firstChange) {
            this.internalTags = [...this.tags];
            this.initialTags = [...this.internalTags];
            this.emitDirty();
        }
        if (changes['description'] && !changes['description'].firstChange) {
            this.internalDescription = this.description ?? '';
            this.initialDescription = this.internalDescription;
            this.emitDirty();
        }
    }

    public onAddTag(): void {
        let trimmedTag = this.newTag.trim();

        if (trimmedTag.startsWith('#')) {
            trimmedTag = trimmedTag.substring(1);
        }

        if (trimmedTag) {
            const formattedTag = trimmedTag.charAt(0).toUpperCase() + trimmedTag.slice(1);

            const duplicate = this.internalTags.find((tag) => tag.toLowerCase() === formattedTag.toLowerCase());

            if (duplicate) {
                this.duplicateTagName = duplicate;
                setTimeout(() => {
                    this.duplicateTagName = null;
                }, 820);
            } else {
                this.duplicateTagName = null;
                this.internalTags = [...this.internalTags, formattedTag];
                this.newTag = '';
                this.tagsSubject.next(this.internalTags);
                this.emitDirty();
                this.detailsChange.emit({ description: this.internalDescription ?? '', tags: [...this.internalTags] });
            }
        }
    }

    public onRemoveTag(tag: string): void {
        this.internalTags = this.internalTags.filter((t) => t !== tag);
        this.tagsSubject.next(this.internalTags);
        this.emitDirty();
        this.detailsChange.emit({ description: this.internalDescription ?? '', tags: [...this.internalTags] });
    }

    public onFocusDescription(): void {
        this.isEditingDescription = true;
    }

    public onBlurDescription(): void {
        this.isEditingDescription = false;
    }

    public onDescriptionInput(): void {
        const desc = this.internalDescription ?? '';
        this.descriptionSubject.next(desc);
        const descDirty = desc !== (this.initialDescription ?? '');
        const tagsDirty = JSON.stringify(this.internalTags ?? []) !== JSON.stringify(this.initialTags ?? []);
        this.dirtyChange.emit(descDirty || tagsDirty);
        this.detailsChange.emit({ description: desc, tags: [...this.internalTags] });
    }

    public getTextareaRows(text: string): number {
        if (!text) return 2;
        const lineCount = text.split('\n').length;
        return Math.min(Math.max(lineCount, 2), 4);
    }

    public adjustTextareaHeight(textarea: HTMLTextAreaElement): void {
        textarea.style.height = 'auto';
        textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
    }

    private updateProjectDescription(description: string): void {
        if (!this.projectId) {
            console.error('Project ID is required for updating description');
            this.toastService.error('Project ID is required for updating description');
            return;
        }
        this.projectsService.patchUpdateProject(this.projectId, { description }).subscribe({
            next: () => {
                this.toastService.success('Project description updated successfully');
            },
            error: (error: unknown) => {
                console.error('Error updating description:', error);

                // Revert the description to the original value
                this.internalDescription = this.description || '';

                // Show error notification
                let errorMessage = 'Failed to update project description';
                if ((error as { error?: { message?: string } })?.error?.message) {
                    errorMessage = (error as { error: { message: string } }).error.message;
                } else if (
                    (error as { error?: unknown })?.error &&
                    typeof (error as { error: unknown }).error === 'string'
                ) {
                    errorMessage = (error as { error: string }).error;
                } else if ((error as { message?: string })?.message) {
                    errorMessage = (error as { message: string }).message;
                }

                this.toastService.error(`Error updating project description: ${errorMessage}`);
            },
        });
    }

    private emitDetailsChange(description: string, tags: string[]): void {
        this.detailsChange.emit({
            description: description ?? '',
            tags: [...(tags ?? [])],
        });
    }

    private emitDirty(): void {
        const descDirty = (this.internalDescription ?? '') !== (this.initialDescription ?? '');
        const tagsDirty = JSON.stringify(this.internalTags ?? []) !== JSON.stringify(this.initialTags ?? []);
        this.dirtyChange.emit(descDirty || tagsDirty);
    }
}
