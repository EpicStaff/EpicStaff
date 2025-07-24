import { Injectable, signal, computed, inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import { tap, delay, shareReplay, catchError, switchMap } from 'rxjs/operators';

import { Tool } from '../../models/tool.model';
import { BuiltinToolsApiService } from './builtin-tools-api.service';
import { TOOL_CATEGORIES_CONFIG } from '../../constants/built-in-tools-categories';

@Injectable({
  providedIn: 'root',
})
export class BuiltinToolsStorageService {
  private readonly builtinToolsApiService = inject(BuiltinToolsApiService);

  // --- State Signals ---
  private toolsSignal = signal<Tool[]>([]);
  private toolsLoaded = signal<boolean>(false);

  private filterSignal = signal<{
    searchTerm?: string;
    category?: string;
  } | null>(null);

  // --- Public State Accessors ---
  public readonly isToolsLoaded = this.toolsLoaded.asReadonly();

  public readonly allTools = computed(() => this.toolsSignal());

  public readonly filters = this.filterSignal.asReadonly();

  public readonly filteredTools = computed(() => {
    let tools = this.toolsSignal();
    const filter = this.filterSignal();

    if (filter) {
      // Filter by search term
      if (filter.searchTerm) {
        const searchTerm = filter.searchTerm.toLowerCase();
        tools = tools.filter(
          (tool) =>
            tool.name.toLowerCase().includes(searchTerm) ||
            tool.description.toLowerCase().includes(searchTerm)
        );
      }

      // Filter by category (toolIds)
      if (filter.category) {
        const categoryConfig = TOOL_CATEGORIES_CONFIG.find(
          (cat) => cat.name === filter.category
        );
        if (categoryConfig) {
          tools = tools.filter((tool) =>
            categoryConfig.toolIds.includes(tool.id)
          );
        }
      }
    }

    // Always sort by id descending
    return tools.slice().sort((a, b) => b.id - a.id);
  });

  // --- State Mutators ---
  public setTools(tools: Tool[]) {
    this.toolsSignal.set(tools);
    this.toolsLoaded.set(true);
  }

  public setFilter(filter: { searchTerm?: string; category?: string } | null) {
    if (!filter) {
      this.filterSignal.set(null);
      return;
    }

    // Merge with existing filter to preserve other filter options
    const currentFilter = this.filterSignal();
    const newFilter = {
      ...currentFilter,
      ...filter,
    };
    this.filterSignal.set(newFilter);
  }

  public setSearchTerm(searchTerm: string) {
    this.filterSignal.update((currentFilter) => ({
      ...currentFilter,
      searchTerm,
    }));
  }

  public setCategoryFilter(category: string | null) {
    this.filterSignal.update((currentFilter) => ({
      ...currentFilter,
      category: category || undefined,
    }));
  }

  public clearFilters() {
    this.filterSignal.set(null);
  }

  // --- Data Fetching Methods ---
  public getTools(forceRefresh = false): Observable<Tool[]> {
    if (this.toolsLoaded() && !forceRefresh) {
      return of(this.toolsSignal());
    }
    return this.builtinToolsApiService.getTools().pipe(
      tap((tools) => {
        this.setTools(tools);
      }),
      delay(this.toolsLoaded() ? 0 : 300),
      shareReplay(1),
      catchError(() => {
        this.toolsLoaded.set(false);
        return of([]);
      })
    );
  }

  public getToolById(id: number): Observable<Tool | undefined> {
    const cachedTool: Tool | undefined = this.toolsSignal().find(
      (tool) => tool.id === id
    );
    if (cachedTool) {
      return of(cachedTool);
    }
    return this.builtinToolsApiService.getToolsByIds([id]).pipe(
      tap((tools) => {
        if (tools.length > 0) {
          this.addToolToCache(tools[0]);
        }
      }),
      switchMap((tools) => of(tools[0])),
      catchError(() => of(undefined))
    );
  }

  // --- CRUD Methods ---
  public updateTool(tool: Tool): Observable<Tool> {
    return this.builtinToolsApiService.updateTool(tool).pipe(
      tap((updatedTool) => {
        const currentTools = this.toolsSignal();
        const index = currentTools.findIndex((t) => t.id === updatedTool.id);
        if (index !== -1) {
          const updatedToolsList = [...currentTools];
          updatedToolsList[index] = updatedTool;
          this.toolsSignal.set(updatedToolsList);
        }
      })
    );
  }

  public patchTool(toolId: number, updates: Partial<Tool>): Observable<Tool> {
    return this.builtinToolsApiService.patchTool(toolId, updates).pipe(
      tap((updatedTool) => {
        const currentTools = this.toolsSignal();
        const index = currentTools.findIndex((t) => t.id === updatedTool.id);
        if (index !== -1) {
          const updatedToolsList = [...currentTools];
          updatedToolsList[index] = updatedTool;
          this.toolsSignal.set(updatedToolsList);
        }
      })
    );
  }

  // --- Cache Management ---
  public addToolToCache(newTool: Tool) {
    const currentTools = this.toolsSignal();
    if (!currentTools.some((t) => t.id === newTool.id)) {
      this.toolsSignal.set([newTool, ...currentTools]);
    }
  }

  // --- Utility Methods ---
  public ensureLoaded(): Observable<Tool[]> {
    if (this.toolsLoaded()) {
      return of(this.toolsSignal());
    }
    return this.getTools();
  }
}
