import { NO_ERRORS_SCHEMA, Provider, signal, Type } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { NODE_PANEL_DIFF, NodePanelDiff } from '../../core/providers/node-panel-diff.token';
import { FieldName, MissingReference } from '../../utils/diff';
import { MissingReferenceNoteComponent } from './missing-reference-note.component';

/** A reference the version had in `field`, as the diff reports it. */
export function missingReference(
    field: FieldName,
    missing: number | string | null,
    path: string = field
): MissingReference {
    return { path, field, missing, source: field === 'key_value_table' ? 'keyValueTable' : 'warning' };
}

/**
 * The open node's diff on the Changes tab, as the panel shell gives it to the panel it renders: by default a
 * changed node with no field changes and no missing references.
 */
export function provideChangesTabDiff(diff: Partial<NodePanelDiff> = {}): Provider {
    const shown: NodePanelDiff = { status: 'changed', fields: [], missingReferences: [], ...diff };
    return { provide: NODE_PANEL_DIFF, useValue: signal(shown).asReadonly() };
}

/**
 * Renders a panel's own template with only the note component real: the fields around the notes stay as plain
 * elements (their tags and the panel's own markup), so a spec can check where each note sits without the
 * fields' own dependencies. Pass `realImports` for a child that renders a note itself.
 */
export function renderOnlyMissingReferenceNotes(panel: Type<unknown>, realImports: Type<unknown>[] = []): void {
    TestBed.overrideComponent(panel, {
        set: { imports: [MissingReferenceNoteComponent, ...realImports], schemas: [NO_ERRORS_SCHEMA] },
    });
}

/** Each note shown, as the user reads it, with the element it sits in. */
export function shownMissingReferenceNotes(root: HTMLElement): { text: string; note: HTMLElement }[] {
    return Array.from(root.querySelectorAll<HTMLElement>('app-missing-reference-note app-warning-note')).map(
        (note) => ({ text: note.textContent?.trim() ?? '', note })
    );
}
