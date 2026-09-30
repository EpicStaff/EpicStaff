import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageDragService } from '../../../../../../services/storage-drag.service';
import { filterStorageItems } from '../../../../../../utils/storage-file.utils';
import { StorageTreeComponent } from './storage-tree.component';

type ContextActionEvent = Parameters<StorageTreeComponent['contextAction']['emit']>[0];

interface FakeDragEvent {
    event: DragEvent;
    preventDefault: ReturnType<typeof vi.fn>;
    stopPropagation: ReturnType<typeof vi.fn>;
    dataTransfer: { dropEffect: string; effectAllowed: string; setData: ReturnType<typeof vi.fn> };
}

function fakeDragEvent(): FakeDragEvent {
    const preventDefault = vi.fn();
    const stopPropagation = vi.fn();
    const dataTransfer = { dropEffect: '', effectAllowed: '', setData: vi.fn() };
    const event = { preventDefault, stopPropagation, dataTransfer } as unknown as DragEvent;
    return { event, preventDefault, stopPropagation, dataTransfer };
}

function leaveEvent(row: HTMLElement, relatedTarget: Element): DragEvent {
    return { currentTarget: row, relatedTarget } as unknown as DragEvent;
}

function click(modifiers: Partial<MouseEvent> = {}): MouseEvent {
    return { ctrlKey: false, metaKey: false, shiftKey: false, ...modifiers } as MouseEvent;
}

/**
 * reports/            (folder, expanded)
 *   reports/q1.csv
 *   reports/q2.csv
 * notes.txt
 * archive/            (folder, collapsed, loaded)
 *   archive/old.txt
 */
function buildTree(): { tree: StorageItem[]; nodes: Record<string, StorageItem> } {
    const q1: StorageItem = { id: 11, name: 'q1.csv', path: 'reports/q1.csv', type: 'file' };
    const q2: StorageItem = { id: 12, name: 'q2.csv', path: 'reports/q2.csv', type: 'file' };
    const reports: StorageItem = {
        id: 10,
        name: 'reports',
        path: 'reports',
        type: 'folder',
        isExpanded: true,
        children: [q1, q2],
    };
    const notes: StorageItem = { id: 20, name: 'notes.txt', path: 'notes.txt', type: 'file' };
    const old: StorageItem = { id: 31, name: 'old.txt', path: 'archive/old.txt', type: 'file' };
    const archive: StorageItem = {
        id: 30,
        name: 'archive',
        path: 'archive',
        type: 'folder',
        isExpanded: false,
        children: [old],
    };
    return { tree: [reports, notes, archive], nodes: { reports, q1, q2, notes, archive, old } };
}

describe('StorageTreeComponent drag and drop', () => {
    let fixture: ComponentFixture<StorageTreeComponent>;
    let component: StorageTreeComponent;
    let storageDrag: StorageDragService;
    let emitted: ContextActionEvent[];
    let nodes: Record<string, StorageItem>;

    beforeEach(() => {
        // jsdom has no ResizeObserver; TooltipOnOverflowDirective needs one once rows render.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        TestBed.configureTestingModule({
            imports: [StorageTreeComponent],
            providers: [{ provide: PermissionsService, useValue: { can: () => true, canAny: () => true } }],
        });
        fixture = TestBed.createComponent(StorageTreeComponent);
        component = fixture.componentInstance;
        storageDrag = TestBed.inject(StorageDragService);

        const built = buildTree();
        nodes = built.nodes;
        fixture.componentRef.setInput('items', built.tree);

        emitted = [];
        component.contextAction.subscribe((event) => emitted.push(event));
    });

    afterEach(() => vi.unstubAllGlobals());

    function startDrag(item: StorageItem): void {
        component.onDragStart(fakeDragEvent().event, item);
    }

    it('resolves a file row to its parent folder: highlights it and moves into it on drop', () => {
        startDrag(nodes['notes']);

        const over = fakeDragEvent();
        component.onDragOver(over.event, nodes['q1']);

        expect(over.stopPropagation).toHaveBeenCalled();
        expect(over.dataTransfer.dropEffect).toBe('move');
        expect(component.dropTarget()).toBe(nodes['reports']);
        expect(component.isDropTarget(nodes['reports'])).toBe(true);
        expect(component.dropTargetRoot()).toBe(false);

        const drop = fakeDragEvent();
        component.onDrop(drop.event, nodes['q1']);

        expect(drop.stopPropagation).toHaveBeenCalled();
        expect(emitted).toEqual([
            expect.objectContaining({ action: 'move', targetPath: 'reports', selectedItems: [nodes['notes']] }),
        ]);
        expect(storageDrag.isDragging()).toBe(false);
    });

    it('stops an invalid target from bubbling and marks it as not droppable (no false root outline)', () => {
        startDrag(nodes['q1']);

        const over = fakeDragEvent();
        component.onDragOver(over.event, nodes['q2']);

        expect(over.stopPropagation).toHaveBeenCalled();
        expect(over.preventDefault).toHaveBeenCalled();
        expect(over.dataTransfer.dropEffect).toBe('none');
        expect(component.dropTarget()).toBeNull();
        expect(component.dropTargetRoot()).toBe(false);

        component.onDrop(fakeDragEvent().event, nodes['q2']);
        expect(emitted).toEqual([]);
    });

    it('treats a root-level file row as the root and moves there', () => {
        startDrag(nodes['q1']);

        component.onDragOver(fakeDragEvent().event, nodes['notes']);
        expect(component.dropTargetRoot()).toBe(true);
        expect(component.dropTarget()).toBeNull();

        component.onDrop(fakeDragEvent().event, nodes['notes']);
        expect(emitted).toEqual([expect.objectContaining({ action: 'move', targetPath: '/' })]);
    });

    it('lets external (OS file) drags bubble past rows and the list to the upload area', () => {
        const over = fakeDragEvent();
        component.onDragOver(over.event, nodes['q1']);
        component.onDrop(over.event, nodes['q1']);
        component.onRootDragOver(over.event);
        component.onRootDrop(over.event);

        expect(over.preventDefault).not.toHaveBeenCalled();
        expect(over.stopPropagation).not.toHaveBeenCalled();
        expect(component.dropTargetRoot()).toBe(false);
        expect(emitted).toEqual([]);
    });

    it('keeps the folder highlight when moving between sibling file rows of that folder', () => {
        fixture.detectChanges();
        startDrag(nodes['notes']);
        component.onDragOver(fakeDragEvent().event, nodes['q1']);

        const host = fixture.nativeElement as HTMLElement;
        const q1Row = host.querySelector('[data-path="reports/q1.csv"]') as HTMLElement;
        const q2Row = host.querySelector('[data-path="reports/q2.csv"]') as HTMLElement;
        const notesRow = host.querySelector('[data-path="notes.txt"]') as HTMLElement;

        component.onDragLeave(leaveEvent(q1Row, q2Row.firstElementChild ?? q2Row), nodes['q1']);
        expect(component.dropTarget()).toBe(nodes['reports']);

        component.onDragLeave(leaveEvent(q1Row, notesRow), nodes['q1']);
        expect(component.dropTarget()).toBeNull();
    });

    it('keeps nested rows mounted when a refresh replaces the nodes with same-path copies', () => {
        fixture.detectChanges();
        const rowOf = (path: string): Element | null =>
            (fixture.nativeElement as HTMLElement).querySelector(`[data-path="${path}"]`);
        const nestedRow = rowOf('reports/q1.csv');
        expect(nestedRow).not.toBeNull();

        // What the facade's merge refresh produces: new objects, same paths, expansion kept.
        const refreshed = buildTree().tree.map((node) => ({
            ...node,
            children: node.children?.map((child) => ({ ...child })),
        }));
        fixture.componentRef.setInput('items', refreshed);
        fixture.detectChanges();

        expect(rowOf('reports/q1.csv')).toBe(nestedRow);
    });

    it('clears its own drag state when the drag service ends the drag (safety net)', () => {
        startDrag(nodes['notes']);
        component.onDragOver(fakeDragEvent().event, nodes['q1']);
        expect(component.dropTarget()).toBe(nodes['reports']);

        document.dispatchEvent(new Event('dragover'));
        document.dispatchEvent(Object.assign(new Event('pointermove'), { isPrimary: true, buttons: 0 }));
        TestBed.tick();

        expect(storageDrag.isDragging()).toBe(false);
        expect(component.draggedItems()).toEqual([]);
        expect(component.dropTarget()).toBeNull();
    });

    it('ends a drag it started when destroyed, since the lost row never fires dragend', () => {
        startDrag(nodes['notes']);
        expect(storageDrag.isDragging()).toBe(true);

        fixture.destroy();

        expect(storageDrag.isDragging()).toBe(false);
    });

    it('offers "Add to collection…" only when the host enables it', () => {
        const menuLabels = (): string[] => {
            component.onContextMenu(
                { preventDefault: vi.fn(), stopPropagation: vi.fn(), clientX: 0, clientY: 0 } as unknown as MouseEvent,
                nodes['notes']
            );
            fixture.detectChanges();
            const labels = Array.from(
                (fixture.nativeElement as HTMLElement).querySelectorAll('.storage-tree__context-menu-item')
            ).map((button) => button.textContent?.trim() ?? '');
            component.closeContextMenu();
            fixture.detectChanges();
            return labels;
        };

        expect(menuLabels()).not.toContain('Add to collection…');
        fixture.componentRef.setInput('enableKnowledgeImport', true);
        expect(menuLabels()).toContain('Add to collection…');
    });

    it('drags the whole selection, including items inside a folder collapsed after selecting', () => {
        component.onItemClick(click(), nodes['notes']);
        component.onItemClick(click({ ctrlKey: true }), nodes['q1']);
        // Collapse "reports": q1 is still selected but no longer visible.
        nodes['reports'].isExpanded = false;

        startDrag(nodes['notes']);

        expect(storageDrag.dragged()).toBe(nodes['notes']);
        expect(storageDrag.draggedItems()).toEqual(expect.arrayContaining([nodes['notes'], nodes['q1']]));
        expect(storageDrag.draggedItems()).toHaveLength(2);

        component.onDrop(fakeDragEvent().event, nodes['archive']);
        const moved = emitted[0]?.selectedItems ?? [];
        expect(moved).toHaveLength(2);
        expect(moved).toEqual(expect.arrayContaining([nodes['notes'], nodes['q1']]));
        expect(emitted[0]?.targetPath).toBe('archive');
    });

    it('prunes the selection to items the tree still has after the data changes', () => {
        const selectionChanges: StorageItem[][] = [];
        component.selectionChange.subscribe((items) => selectionChanges.push(items));
        component.onItemClick(click(), nodes['notes']);
        component.onItemClick(click({ ctrlKey: true }), nodes['q1']);

        // A refresh collapsed "reports" and dropped its children.
        const refreshed = buildTree().tree.map((node) =>
            node.path === 'reports' ? { ...node, isExpanded: false, children: undefined } : node
        );
        fixture.componentRef.setInput('items', refreshed);
        TestBed.tick();

        expect([...component.selectedPaths()]).toEqual(['notes.txt']);
        expect(selectionChanges.at(-1)?.map((selected) => selected.path)).toEqual(['notes.txt']);
    });

    it('keeps items hidden by a search selected, and still selected after the search is cleared', () => {
        const fullTree = component.items();
        fixture.componentRef.setInput('loadedItems', fullTree);
        component.onItemClick(click(), nodes['notes']);
        component.onItemClick(click({ ctrlKey: true }), nodes['q1']);

        // Search hides q1: the tree shows a filtered view, but the loaded data is unchanged.
        fixture.componentRef.setInput('items', filterStorageItems(fullTree, 'notes'));
        TestBed.tick();
        expect(new Set(component.selectedPaths())).toEqual(new Set(['notes.txt', 'reports/q1.csv']));

        fixture.componentRef.setInput('items', fullTree);
        TestBed.tick();
        expect(new Set(component.selectedPaths())).toEqual(new Set(['notes.txt', 'reports/q1.csv']));

        // The drag set still covers the item the search hid.
        fixture.componentRef.setInput('items', filterStorageItems(fullTree, 'notes'));
        startDrag(nodes['notes']);
        expect(
            storageDrag
                .draggedItems()
                .map((item) => item.path)
                .sort()
        ).toEqual(['notes.txt', 'reports/q1.csv']);
    });

    it('drags only the grabbed row when it is not part of the selection', () => {
        component.onItemClick(click(), nodes['notes']);
        component.onItemClick(click({ ctrlKey: true }), nodes['q1']);

        startDrag(nodes['old']);

        expect(storageDrag.draggedItems()).toEqual([nodes['old']]);
    });

    it('sends the selection with the "add-to-collection" context action', () => {
        component.onItemClick(click(), nodes['notes']);
        component.onItemClick(click({ ctrlKey: true }), nodes['q1']);
        component.onContextMenu(
            { preventDefault: vi.fn(), stopPropagation: vi.fn(), clientX: 0, clientY: 0 } as unknown as MouseEvent,
            nodes['notes']
        );

        component.onContextMenuAction('add-to-collection');

        expect(emitted).toHaveLength(1);
        expect(emitted[0].action).toBe('add-to-collection');
        expect(emitted[0].selectedItems).toEqual(expect.arrayContaining([nodes['notes'], nodes['q1']]));
    });
});
