import { computed, inject, Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, shareReplay, tap } from 'rxjs/operators';

import { GetCrewTagRequest } from '../models/crew-tag.model';
import { ProjectTagsApiService } from './project-tags-api.service';

@Injectable({
    providedIn: 'root',
})
export class ProjectTagsStorageService {
    private readonly projectTagsApiService = inject(ProjectTagsApiService);

    // --- State Signals ---
    private tagsSignal = signal<GetCrewTagRequest[]>([]);
    private tagsLoaded = signal<boolean>(false);

    // --- Public State Accessors ---
    public readonly isTagsLoaded = this.tagsLoaded.asReadonly();
    public readonly allTags = computed(() => this.tagsSignal());

    // --- Computed helpers for mapping ---
    public readonly tagsById = computed(() => {
        const tags = this.tagsSignal();
        const map = new Map<number, GetCrewTagRequest>();
        tags.forEach((tag) => map.set(tag.id, tag));
        return map;
    });

    // --- State Mutators ---
    public setTags(tags: GetCrewTagRequest[]) {
        this.tagsSignal.set(tags);
        this.tagsLoaded.set(true);
    }

    // --- Data Fetching Methods ---
    public getTags(forceRefresh = false): Observable<GetCrewTagRequest[]> {
        if (this.tagsLoaded() && !forceRefresh) {
            return of(this.tagsSignal());
        }
        return this.projectTagsApiService.getCrewTags().pipe(
            tap((tags) => {
                this.setTags(tags);
            }),
            shareReplay(1),
            catchError(() => {
                this.tagsLoaded.set(false);
                return of([]);
            })
        );
    }

    // --- Helper Methods ---
    public getTagById(id: number): GetCrewTagRequest | undefined {
        return this.tagsById().get(id);
    }

    public getTagsByIds(ids: number[]): GetCrewTagRequest[] {
        const tagsMap = this.tagsById();
        return ids.map((id) => tagsMap.get(id)).filter((tag) => tag !== undefined) as GetCrewTagRequest[];
    }

    public getTagNames(ids: number[]): string[] {
        return this.getTagsByIds(ids).map((tag: GetCrewTagRequest) => tag.name);
    }

    public addTagToCache(newTag: GetCrewTagRequest) {
        const currentTags = this.tagsSignal();
        if (!currentTags.some((t) => t.id === newTag.id)) {
            this.tagsSignal.set([newTag, ...currentTags]);
        }
    }

    public updateTagInCache(updatedTag: GetCrewTagRequest) {
        const currentTags = this.tagsSignal();
        const index = currentTags.findIndex((t) => t.id === updatedTag.id);
        if (index !== -1) {
            const updatedTagsList = [...currentTags];
            updatedTagsList[index] = updatedTag;
            this.tagsSignal.set(updatedTagsList);
        }
    }

    public removeTagFromCache(tagId: number) {
        const currentTags = this.tagsSignal();
        this.tagsSignal.set(currentTags.filter((t) => t.id !== tagId));
    }

    // --- Utility Methods ---
    public ensureLoaded(): Observable<GetCrewTagRequest[]> {
        if (this.tagsLoaded()) {
            return of(this.tagsSignal());
        }
        return this.getTags();
    }

    public refreshTags(): void {
        this.tagsLoaded.set(false);
        this.getTags(true).subscribe();
    }
}
