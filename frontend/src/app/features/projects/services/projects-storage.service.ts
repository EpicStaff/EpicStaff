// src/app/services/projects.service.ts

import { Injectable, signal, computed, inject } from '@angular/core';
import { Observable, of, tap, catchError, map, delay } from 'rxjs';
import { shareReplay } from 'rxjs/operators';
import {
  GetProjectRequest,
  CreateProjectRequest,
  UpdateProjectRequest,
} from '../models/project.model';
import { ProjectsApiService } from './projects-api.service';
import { TEMPLATE_PROJECTS } from '../constants/mock-templates';
import { SearchFilterChange } from '../../../shared/components/filters-list/filters-list.component';

@Injectable({
  providedIn: 'root',
})
export class ProjectsStorageService {
  private readonly projectsApiService = inject(ProjectsApiService);

  // --- State Signals ---
  private projectsSignal = signal<GetProjectRequest[]>([]);
  private projectsLoaded = signal<boolean>(false);
  private templatesSignal = signal<GetProjectRequest[]>([]);
  private templatesLoaded = signal<boolean>(false);
  private filterSignal = signal<SearchFilterChange | null>(null);

  // --- Public State Accessors (Readonly Signals and Computed Values) ---
  public readonly projects = this.projectsSignal.asReadonly();
  public readonly isProjectsLoaded = this.projectsLoaded.asReadonly();

  public readonly templates = this.templatesSignal.asReadonly();
  public readonly isTemplatesLoaded = this.templatesLoaded.asReadonly();

  public readonly filteredProjects = computed(() => {
    const projects = this.projectsSignal();
    const filter = this.filterSignal();
    let filtered = projects;
    if (filter) {
      // Filter by search term
      if (filter.searchTerm) {
        filtered = filtered.filter((p) =>
          p.name.toLowerCase().includes(filter.searchTerm.toLowerCase())
        );
      }
      // Filter by selected tags
      if (filter.selectedTagIds && filter.selectedTagIds.length > 0) {
        filtered = filtered.filter((p) =>
          filter.selectedTagIds!.some((tagId) => p.tags.includes(tagId))
        );
      }
    }
    // Always sort by id descending
    return filtered.slice().sort((a, b) => b.id - a.id);
  });

  public readonly filteredTemplates = computed(() => {
    const templates = this.templatesSignal();
    const filter = this.filterSignal();
    if (!filter) return templates;
    let filtered = templates;
    if (filter.searchTerm) {
      filtered = filtered.filter((t) =>
        t.name.toLowerCase().includes(filter.searchTerm.toLowerCase())
      );
    }
    // Add more filter/sort logic here as needed
    return filtered;
  });

  // --- State Mutators ---
  setProjects(projects: GetProjectRequest[]) {
    this.projectsSignal.set(projects);
    this.projectsLoaded.set(true);
  }

  setTemplates(templates: GetProjectRequest[]) {
    this.templatesSignal.set(templates);
    this.templatesLoaded.set(true);
  }

  public setFilter(filter: SearchFilterChange | null) {
    // Only update filter if it's different from current filter
    const currentFilter = this.filterSignal();

    // Check if filter is the same as current filter
    if (currentFilter === null && filter === null) {
      return;
    }

    // If either is null but not both, they're different
    if (currentFilter === null || filter === null) {
      this.filterSignal.set(filter);
      return;
    }

    // Compare searchTerm and selectedTagIds
    const searchTermChanged = currentFilter.searchTerm !== filter.searchTerm;
    const tagsChanged =
      (!currentFilter.selectedTagIds && filter.selectedTagIds) ||
      (currentFilter.selectedTagIds && !filter.selectedTagIds) ||
      (currentFilter.selectedTagIds &&
        filter.selectedTagIds &&
        JSON.stringify(currentFilter.selectedTagIds.sort()) !==
          JSON.stringify(filter.selectedTagIds.sort()));

    // Only update if there's a change
    if (searchTermChanged || tagsChanged) {
      this.filterSignal.set(filter);
    }
  }

  // Get the current filter value
  public getCurrentFilter(): SearchFilterChange | null {
    return this.filterSignal();
  }

  // --- Data Fetching Methods (API Interactions) ---
  getProjects(forceRefresh = false): Observable<GetProjectRequest[]> {
    if (this.projectsLoaded() && !forceRefresh) {
      return of(this.projectsSignal());
    }
    return this.projectsApiService.getProjects().pipe(
      tap((projects) => {
        this.setProjects(projects);
      }),
      delay(this.projectsLoaded() ? 0 : 300),
      shareReplay(1),
      catchError(() => {
        this.projectsLoaded.set(false);
        return of([]);
      })
    );
  }

  getTemplates(forceRefresh = false): Observable<GetProjectRequest[]> {
    if (this.templatesLoaded() && !forceRefresh) {
      return of(this.templatesSignal());
    }
    return of(TEMPLATE_PROJECTS).pipe(
      delay(500),
      map((templates) =>
        templates.map(
          (template) =>
            ({
              ...template,
              tags: template.tags ? [] : [], // Convert string[] to number[] (empty for templates)
            } as GetProjectRequest)
        )
      ),
      tap((templates) => {
        this.setTemplates(templates);
      }),
      shareReplay(1)
    );
  }

  getProjectById(id: number): Observable<GetProjectRequest | undefined> {
    console.log('🎯 getProjectById called for ID:', id);

    const cachedProject = this.projectsSignal().find(
      (project) => project.id === id
    );

    if (cachedProject) {
      console.log('🎯 Found cached project:', cachedProject);
      console.log('🎯 Cached project memory:', cachedProject.memory);
      return of(cachedProject);
    }

    console.log('🎯 No cached project found, fetching from API');
    return this.projectsApiService.getProjectById(id).pipe(
      tap((project) => {
        if (project) {
          console.log('🎯 API returned project:', project);
          console.log('🎯 API project memory:', project.memory);
        }
      }),
      catchError(() => of(undefined))
    );
  }

  // --- Data Manipulation Methods (CRUD Operations) ---
  createProject(project: CreateProjectRequest): Observable<GetProjectRequest> {
    return this.projectsApiService.createProject(project).pipe(
      tap((newProject: GetProjectRequest) => {
        this.addProjectToCache(newProject);
      })
    );
  }

  updateProject(project: UpdateProjectRequest): Observable<GetProjectRequest> {
    return this.projectsApiService.updateProject(project).pipe(
      tap((updatedProject) => {
        const currentProjects = this.projectsSignal();
        const index = currentProjects.findIndex((p) => p.id === project.id);
        if (index !== -1) {
          const updatedProjects = [...currentProjects];
          updatedProjects[index] = updatedProject as GetProjectRequest;
          this.projectsSignal.set(updatedProjects);
        }
      })
    );
  }

  patchUpdateProject(
    id: number,
    updateData: Partial<GetProjectRequest>
  ): Observable<GetProjectRequest> {
    console.log('💫 patchUpdateProject called with:', { id, updateData });

    return this.projectsApiService.patchUpdateProject(id, updateData).pipe(
      tap((updatedProject) => {
        console.log('💫 TAP operator fired with:', updatedProject);
        console.log('💫 Memory in TAP:', updatedProject.memory);

        const currentProjects = this.projectsSignal();
        const index = currentProjects.findIndex((p) => p.id === id);
        console.log('💫 TAP - Found project at index:', index);

        if (index !== -1) {
          const oldProject = currentProjects[index];
          console.log('💫 TAP - Old project memory:', oldProject.memory);

          const updatedProjectsList = [...currentProjects];
          updatedProjectsList[index] = {
            ...updatedProjectsList[index],
            ...updatedProject,
          } as GetProjectRequest;

          console.log(
            '💫 TAP - New project memory:',
            updatedProjectsList[index].memory
          );

          this.projectsSignal.set(updatedProjectsList);

          // Verify TAP update
          const verifyTapUpdate = this.projectsSignal().find(
            (p) => p.id === id
          );
          console.log(
            '💫 TAP Verification - project in cache:',
            verifyTapUpdate
          );
          console.log(
            '💫 TAP Verification - memory field:',
            verifyTapUpdate?.memory
          );
        }
      })
    );
  }

  deleteProject(id: number): Observable<void> {
    return this.projectsApiService.deleteProject(id).pipe(
      tap(() => {
        const currentProjects = this.projectsSignal();
        const updatedProjects = currentProjects.filter((p) => p.id !== id);
        this.projectsSignal.set(updatedProjects);
      })
    );
  }

  public addProjectToCache(newProject: GetProjectRequest) {
    const currentProjects = this.projectsSignal();
    if (!currentProjects.some((p) => p.id === newProject.id)) {
      this.projectsSignal.set([newProject, ...currentProjects]);
    }
  }

  public updateProjectInCache(updatedProject: GetProjectRequest) {
    console.log('🚀 updateProjectInCache called with:', updatedProject);
    console.log('🚀 Memory field in update:', updatedProject.memory);

    const currentProjects = this.projectsSignal();
    console.log('🚀 Current projects in cache:', currentProjects.length);

    const index = currentProjects.findIndex((p) => p.id === updatedProject.id);
    console.log('🚀 Found project at index:', index);

    if (index !== -1) {
      const oldProject = currentProjects[index];
      console.log('🚀 Old project memory:', oldProject.memory);

      const updatedProjects = [...currentProjects];
      // Create a new object reference to ensure change detection works
      updatedProjects[index] = { ...updatedProject };

      console.log('🚀 New project memory:', updatedProjects[index].memory);

      this.projectsSignal.set(updatedProjects);

      // Verify the update
      const verifyUpdate = this.projectsSignal().find(
        (p) => p.id === updatedProject.id
      );
      console.log(
        '🚀 Verification - project in cache after set:',
        verifyUpdate
      );
      console.log('🚀 Verification - memory field:', verifyUpdate?.memory);

      console.log(
        'Updated project in cache:',
        updatedProject.id,
        'with memory:',
        updatedProject.memory
      );
    } else {
      console.log('🚀 Project not found in cache, adding it');
      // If project not found, add it
      this.addProjectToCache(updatedProject);
    }
  }

  public refreshProjects(): Observable<GetProjectRequest[]> {
    this.projectsLoaded.set(false);
    return this.getProjects(true);
  }

  public refreshTemplates(): Observable<GetProjectRequest[]> {
    this.templatesLoaded.set(false);
    return this.getTemplates(true);
  }
}
