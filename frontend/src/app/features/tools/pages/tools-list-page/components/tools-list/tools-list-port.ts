import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { BulkDeleteToolsResponse, GetBulkToolUsageItem, GetToolUsage } from '../../../../models/tool-config.model';
import { ToolFilterAdapter } from '../../../../utils/tools-cards.util';
import { ToolKind } from '../tool-card/tool-card.model';

/**
 * Adapter object that abstracts a single tool "kind" (custom python code tools
 * or MCP tools). One instance is provided per route; the unified
 * `ToolsListComponent` calls only into these methods so it stays kind-agnostic.
 */
export interface ToolsListPort<T extends { id: number; name: string; labels: number[]; is_favorite: boolean }> {
    // discriminators / labels
    readonly kind: ToolKind;
    readonly entityLabel: string;
    readonly entityLabelPlural: string;

    // filter/search adapter for the shared filter helpers
    readonly filterAdapter: ToolFilterAdapter<T>;

    // per-tool projections
    isBuiltIn(t: T): boolean;
    descriptionOf(t: T): string;
    exportFileName(toolName: string): string;
    bulkExportFileName(): string;

    // service delegates
    getAll(): Observable<T[]>;
    copy(id: number, body: { name: string }): Observable<T>;
    exportOne(id: number): Observable<Blob>;
    bulkExport(ids: number[]): Observable<Blob>;
    patchLabels(id: number, labelIds: number[]): Observable<T>;
    delete(id: number): Observable<void>;
    bulkDelete(ids: number[]): Observable<BulkDeleteToolsResponse>;
    addFav(id: number): Observable<void>;
    delFav(id: number): Observable<void>;
    importFile(file: File): Observable<unknown>;
    getBulkUsage(ids: number[]): Observable<GetBulkToolUsageItem[]>;
    getUsageDetail(id: number): Observable<GetToolUsage>;

    // configure/edit dialog
    openConfigureDialog(dialog: Dialog, tool: T, allTools: T[]): DialogRef<T>;

    // creation event stream (from ToolsEventsService)
    readonly createdEvent$: Observable<T>;
}

/**
 * Route-scoped injection token. Each route (`/tools/custom`, `/tools/mcp`)
 * provides a concrete `ToolsListPort` implementation.
 */
export const TOOLS_LIST_PORT = new InjectionToken<ToolsListPort<never>>('TOOLS_LIST_PORT');
