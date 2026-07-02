import { inject, Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { finalize, map, shareReplay, tap } from 'rxjs/operators';

import { CollectionsApiService } from '../../knowledge-sources/services/collections-api.service';
import { McpToolsService } from '../../tools/services/mcp-tools/mcp-tools.service';
import { PythonCodeToolService } from '../../tools/services/python-code-tool.service';
import { SurfaceCollectionOption, SurfaceToolOption } from '../models/surface-card.model';

@Injectable()
export class SurfaceCatalogsStore {
    private readonly pythonToolService = inject(PythonCodeToolService);
    private readonly mcpToolService = inject(McpToolsService);
    private readonly collectionsService = inject(CollectionsApiService);

    private readonly pythonSignal = signal<SurfaceToolOption[]>([]);
    private readonly mcpSignal = signal<SurfaceToolOption[]>([]);
    private readonly collectionsSignal = signal<SurfaceCollectionOption[]>([]);

    readonly pythonTools = this.pythonSignal.asReadonly();
    readonly mcpTools = this.mcpSignal.asReadonly();
    readonly collections = this.collectionsSignal.asReadonly();

    private pythonLoaded = false;
    private mcpLoaded = false;
    private collectionsLoaded = false;

    private pythonRequest$?: Observable<SurfaceToolOption[]>;
    private mcpRequest$?: Observable<SurfaceToolOption[]>;
    private collectionsRequest$?: Observable<SurfaceCollectionOption[]>;

    loadPythonTools(): Observable<SurfaceToolOption[]> {
        if (this.pythonLoaded) return of(this.pythonSignal());
        if (this.pythonRequest$) return this.pythonRequest$;
        this.pythonRequest$ = this.pythonToolService.getPythonCodeTools().pipe(
            map((tools) =>
                tools.map<SurfaceToolOption>((t) => ({
                    id: t.id,
                    name: t.name,
                    description: t.description ?? '',
                    kind: 'python',
                }))
            ),
            tap((py) => {
                this.pythonSignal.set(py);
                this.pythonLoaded = true;
            }),
            finalize(() => (this.pythonRequest$ = undefined)),
            shareReplay(1)
        );
        return this.pythonRequest$;
    }

    loadMcpTools(): Observable<SurfaceToolOption[]> {
        if (this.mcpLoaded) return of(this.mcpSignal());
        if (this.mcpRequest$) return this.mcpRequest$;
        this.mcpRequest$ = this.mcpToolService.getMcpTools().pipe(
            map((tools) =>
                tools.map<SurfaceToolOption>((t) => ({ id: t.id, name: t.name, description: '', kind: 'mcp' }))
            ),
            tap((mcp) => {
                this.mcpSignal.set(mcp);
                this.mcpLoaded = true;
            }),
            finalize(() => (this.mcpRequest$ = undefined)),
            shareReplay(1)
        );
        return this.mcpRequest$;
    }

    loadCollections(): Observable<SurfaceCollectionOption[]> {
        if (this.collectionsLoaded) return of(this.collectionsSignal());
        if (this.collectionsRequest$) return this.collectionsRequest$;
        this.collectionsRequest$ = this.collectionsService.getCollections().pipe(
            map((cols) => cols.map<SurfaceCollectionOption>((c) => ({ id: c.collection_id, name: c.collection_name }))),
            tap((cols) => {
                this.collectionsSignal.set(cols);
                this.collectionsLoaded = true;
            }),
            finalize(() => (this.collectionsRequest$ = undefined)),
            shareReplay(1)
        );
        return this.collectionsRequest$;
    }

    addTool(tool: SurfaceToolOption): void {
        const target = tool.kind === 'python' ? this.pythonSignal : this.mcpSignal;
        target.update((cur) => [tool, ...cur.filter((t) => t.id !== tool.id)]);
    }
}
