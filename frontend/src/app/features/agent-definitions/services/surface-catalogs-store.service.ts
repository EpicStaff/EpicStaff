import { DestroyRef, effect, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SelectDropdownTreeNode } from '@shared/components';
import { Observable, of } from 'rxjs';
import { finalize, map, shareReplay, tap } from 'rxjs/operators';

import { StorageTreeNode } from '../../files/models/storage.models';
import { StorageApiService } from '../../files/services/storage-api.service';
import { CollectionsApiService } from '../../knowledge-sources/services/collections-api.service';
import { McpToolsService } from '../../tools/services/mcp-tools/mcp-tools.service';
import { PythonCodeToolService } from '../../tools/services/python-code-tool.service';
import { SurfaceCollectionOption, SurfaceToolOption } from '../models/surface-card.model';

export interface StorageFileMeta {
    name: string;
    path: string;
}

function toDropdownNode(node: StorageTreeNode, meta: Map<number, StorageFileMeta>): SelectDropdownTreeNode {
    const id: number | string = node.type === 'file' && node.id != null ? node.id : node.path;
    if (node.type === 'file' && typeof id === 'number') {
        meta.set(id, { name: node.name, path: node.path });
    }
    return {
        id,
        name: node.name,
        type: node.type,
        children: node.type === 'folder' ? (node.children ?? []).map((c) => toDropdownNode(c, meta)) : undefined,
    };
}

@Injectable()
export class SurfaceCatalogsStore {
    private readonly pythonToolService = inject(PythonCodeToolService);
    private readonly mcpToolService = inject(McpToolsService);
    private readonly collectionsService = inject(CollectionsApiService);
    private readonly storageApi = inject(StorageApiService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly pythonSignal = signal<SurfaceToolOption[]>([]);
    private readonly mcpSignal = signal<SurfaceToolOption[]>([]);
    private readonly collectionsSignal = signal<SurfaceCollectionOption[]>([]);
    private readonly storageTreeSignal = signal<SelectDropdownTreeNode[]>([]);
    private readonly storageFileMetaSignal = signal<ReadonlyMap<number, StorageFileMeta>>(new Map());

    readonly pythonTools = this.pythonSignal.asReadonly();
    readonly mcpTools = this.mcpSignal.asReadonly();
    readonly collections = this.collectionsSignal.asReadonly();
    readonly storageTree = this.storageTreeSignal.asReadonly();
    readonly storageFileMeta = this.storageFileMetaSignal.asReadonly();

    private pythonLoaded = false;
    private mcpLoaded = false;
    private collectionsLoaded = false;
    private storageTreeLoaded = false;

    private pythonRequest$?: Observable<SurfaceToolOption[]>;
    private mcpRequest$?: Observable<SurfaceToolOption[]>;
    private collectionsRequest$?: Observable<SurfaceCollectionOption[]>;
    private storageTreeRequest$?: Observable<SelectDropdownTreeNode[]>;

    constructor() {
        let seen = false;
        effect(() => {
            this.storageApi.refreshTick();
            if (!seen) {
                seen = true;
                return;
            }
            if (!this.storageTreeLoaded && !this.storageTreeRequest$) return;
            this.reloadStorageTree().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        });
    }

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

    loadStorageTree(): Observable<SelectDropdownTreeNode[]> {
        if (this.storageTreeLoaded) return of(this.storageTreeSignal());
        if (this.storageTreeRequest$) return this.storageTreeRequest$;
        this.storageTreeRequest$ = this.storageApi.tree().pipe(
            map((res) => {
                const meta = new Map<number, StorageFileMeta>();
                const nodes = (res.tree.children ?? []).map((n) => toDropdownNode(n, meta));
                return { nodes, meta };
            }),
            tap(({ nodes, meta }) => {
                this.storageTreeSignal.set(nodes);
                this.storageFileMetaSignal.set(meta);
                this.storageTreeLoaded = true;
            }),
            map(({ nodes }) => nodes),
            finalize(() => (this.storageTreeRequest$ = undefined)),
            shareReplay(1)
        );
        return this.storageTreeRequest$;
    }

    reloadStorageTree(): Observable<SelectDropdownTreeNode[]> {
        this.storageTreeLoaded = false;
        this.storageTreeRequest$ = undefined;
        return this.loadStorageTree();
    }

    addTool(tool: SurfaceToolOption): void {
        const target = tool.kind === 'python' ? this.pythonSignal : this.mcpSignal;
        target.update((cur) => [tool, ...cur.filter((t) => t.id !== tool.id)]);
    }

    /** Force a re-fetch of the collection catalog (e.g. after a new one is created). */
    reloadCollections(): Observable<SurfaceCollectionOption[]> {
        this.collectionsLoaded = false;
        this.collectionsRequest$ = undefined;
        return this.loadCollections();
    }

    reloadPythonTools(): Observable<SurfaceToolOption[]> {
        this.pythonLoaded = false;
        this.pythonRequest$ = undefined;
        return this.loadPythonTools();
    }

    reloadMcpTools(): Observable<SurfaceToolOption[]> {
        this.mcpLoaded = false;
        this.mcpRequest$ = undefined;
        return this.loadMcpTools();
    }

    reloadLoadedCatalogs(): void {
        if (this.pythonLoaded) this.reloadPythonTools().subscribe({ error: () => {} });
        if (this.mcpLoaded) this.reloadMcpTools().subscribe({ error: () => {} });
        if (this.collectionsLoaded) this.reloadCollections().subscribe({ error: () => {} });
        if (this.storageTreeLoaded) this.reloadStorageTree().subscribe({ error: () => {} });
    }
}
