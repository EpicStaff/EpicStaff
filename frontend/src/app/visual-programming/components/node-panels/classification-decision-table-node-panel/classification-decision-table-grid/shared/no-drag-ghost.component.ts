import { ChangeDetectionStrategy, Component } from '@angular/core';
import { IDragAndDropImageAngularComponent } from 'ag-grid-angular';
import { IDragAndDropImageParams } from 'ag-grid-community';

/**
 * Empty replacement for AG Grid's built-in `.ag-dnd-ghost` drag image, registered as
 * `gridOptions.dragAndDropImageComponent` on THIS grid instance only.
 *
 * Verified in the installed ag-grid-community 33.3.2 bundle
 * (dist/types/src/entities/gridOptions.d.ts / dist/package/main.cjs.js):
 * - `.ag-dnd-ghost` is rendered by AG Grid's default `agDragAndDropImage` user
 *   component (packages/ag-grid-community/src/dragAndDrop/dragAndDropImageComponent.ts —
 *   `cls: "ag-dnd-ghost ag-unselectable"`), which `gridOptions.dragAndDropImageComponent`
 *   replaces (`_getDragAndDropImageCompDetails` resolves it via
 *   `userCompFactory.getCompDetailsFromGridOptions(DragAndDropImageComponent,
 *   "agDragAndDropImage", params, true)`).
 * - `DragAndDropService.onDragStart()` calls `createDragAndDropImageComponent()`
 *   unconditionally for every `DragSourceType` (ToolPanel, HeaderCell, RowDrag,
 *   ChartPanel, AdvancedFilterBuilder) — it is NOT limited to row dragging, even
 *   though the gridOptions.d.ts doc comment tags it `@agModule RowDragModule`.
 *   Column-header drags register through `setDragSourceForHeader()` with
 *   `type: 1 /* HeaderCell *\/`, going through the exact same `addDragSource()` →
 *   `onDragStart()` path, so this option also governs the column-drag ghost.
 *
 * This makes the ghost image a genuine per-grid gridOption (scoped to this
 * component's own `gridOptions` object) rather than a global CSS override — it
 * cannot affect any other ag-grid instance in the app.
 */
@Component({
    selector: 'app-cdt-no-drag-ghost',
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: '',
    styles: [
        `
            :host {
                display: none;
            }
        `,
    ],
})
export class NoDragGhostComponent implements IDragAndDropImageAngularComponent {
    // No-op implementations — deliberately unused params (interface-mandated signatures) are
    // marked "used" via `void` so `@typescript-eslint/no-unused-vars` (no argsIgnorePattern
    // configured in this repo's eslint.config.js) doesn't flag them.
    agInit(params: IDragAndDropImageParams): void {
        void params;
    }

    setIcon(iconName: string | null, shake: boolean): void {
        void iconName;
        void shake;
    }

    setLabel(label: string): void {
        void label;
    }
}
