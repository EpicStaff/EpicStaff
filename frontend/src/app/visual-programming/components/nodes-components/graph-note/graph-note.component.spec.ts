import { FocusMonitor, FocusOrigin } from '@angular/cdk/a11y';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LlmConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { KeyValueTablesStorageService } from '../../../../features/key-value-tables/services/key-value-tables-storage.service';
import { GraphNoteModel } from '../../../core/models/node.model';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { FieldChange, NodeDiffStatus } from '../../../utils/diff';
import { mapGraphNoteToModel } from '../../../utils/load/nodes/graph-note.mapper';
import { liveNote } from '../../../utils/testing/live-graph.fixture';
import { FlowBaseNodeComponent } from '../../flow-base-node/flow-base-node.component';

// The note is rendered as the canvas renders it, inside its canvas node, which reads the note's diff.

const NOTE: GraphNoteModel = { ...mapGraphNoteToModel(liveNote), ports: null, data: { content: 'Call the customer' } };

function contentChange(current: string, version: string): FieldChange {
    return { path: 'content', field: 'content', status: 'changed', current, version };
}

let fixture: ComponentFixture<FlowBaseNodeComponent>;

/** Renders the note on a diff canvas (`status` set) or off one (`null`: the Preview tab, the live editor). */
function render(status: NodeDiffStatus | null, fields: FieldChange[] = []): void {
    TestBed.configureTestingModule({
        providers: [
            { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(true) } },
            { provide: AgentDefinitionsApiService, useValue: { definitions: signal([]) } },
            { provide: LlmConfigStorageService, useValue: { isConfigsLoaded: signal(false), configs: signal([]) } },
            { provide: KeyValueTablesStorageService, useValue: { tables: signal([]), loadTables: () => of([]) } },
        ],
    });
    TestBed.inject(FlowDiffStateService).setState(
        status && {
            nodes: new Map([[NOTE.id, { status, fields, missingReferences: [] }]]),
            connections: new Map(),
            versionOnlyPortIds: new Set(),
            currentOnlyRoutePortIds: new Set(),
            nodeIdByKey: new Map(),
        }
    );
    fixture = TestBed.createComponent(FlowBaseNodeComponent);
    fixture.componentRef.setInput('node', NOTE);
    fixture.detectChanges();
}

const note = (): HTMLElement => fixture.nativeElement.querySelector('app-graph-note .note-container');
const tooltip = (): HTMLElement | null => document.querySelector('.diff-field-mark__tooltip');
/** The tooltip's current value, struck parts in brackets. */
const tooltipValue = (): string =>
    Array.from(tooltip()!.querySelectorAll<HTMLElement>('.diff-field-mark__tooltip-value > span'))
        .map((part) =>
            part.classList.contains('diff-field-mark__struck') ? `[${part.textContent}]` : part.textContent
        )
        .join('');
/** What a screen reader reads as the note's description. */
const description = (): string | null | undefined =>
    document.getElementById(note().getAttribute('aria-describedby') ?? '')?.textContent;

function dispatch(event: Event): void {
    note().dispatchEvent(event);
    fixture.detectChanges();
}

/** Focuses the note as the user would by `origin` (keyboard Tab, mouse click), as the CDK focus monitor tells them apart. */
function focusBy(origin: Exclude<FocusOrigin, null>): void {
    TestBed.inject(FocusMonitor).focusVia(note(), origin);
    fixture.detectChanges();
}

/** An event anywhere on the page outside the note, e.g. on the canvas or another node. */
function dispatchElsewhere(event: Event): void {
    document.body.dispatchEvent(event);
    fixture.detectChanges();
}

describe('GraphNoteComponent on a version diff canvas', () => {
    it('shows the current canvas text on hover of a changed note, the part a restore replaces struck', () => {
        render('changed', [contentChange('Call the customer today', 'Call the customer')]);

        dispatch(new Event('mouseenter'));

        expect(tooltip()!.querySelector('.diff-field-mark__tooltip-label')!.textContent).toBe('Current canvas');
        expect(tooltipValue()).toBe('Call the customer[ today]');
        dispatch(new Event('mouseleave'));
        expect(tooltip()).toBeNull();
    });

    it('makes a changed note focusable and describes it with the current canvas text', () => {
        render('changed', [contentChange('Call the customer today', 'Call the customer')]);

        expect(note().getAttribute('tabindex')).toBe('0');
        expect(description()).toBe('Current canvas: Call the customer today');
    });

    it('opens on keyboard focus and closes on blur', () => {
        render('changed', [contentChange('Old text', 'Call the customer')]);

        focusBy('keyboard');
        expect(tooltip()).not.toBeNull();
        note().blur();
        fixture.detectChanges();
        expect(tooltip()).toBeNull();
    });

    // A click focuses the note after pressing closed the tooltip; reopening it then would leave it behind while the
    // note is dragged, as the pointer never leaves the note.
    it('stays closed when a click on the hovered note focuses it', () => {
        render('changed', [contentChange('Old text', 'Call the customer')]);
        dispatch(new Event('mouseenter'));

        dispatch(new Event('pointerdown', { bubbles: true }));
        focusBy('mouse');

        expect(tooltip()).toBeNull();
    });

    it('closes on Esc without letting the key reach the canvas', () => {
        render('changed', [contentChange('Old text', 'Call the customer')]);
        const canvasKeydown = vi.fn();
        fixture.nativeElement.addEventListener('keydown', canvasKeydown);
        dispatch(new Event('mouseenter'));

        dispatch(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

        expect(tooltip()).toBeNull();
        expect(canvasKeydown).not.toHaveBeenCalled();
    });

    // The note moves under a still pointer when the canvas is dragged or zoomed: the tooltip would stay behind.
    it.each(['pointerdown', 'wheel'])('closes on %s on the hovered note', (type) => {
        render('changed', [contentChange('Old text', 'Call the customer')]);
        dispatch(new Event('mouseenter'));

        dispatch(new Event(type, { bubbles: true }));

        expect(tooltip()).toBeNull();
    });

    // Opened by the keyboard, the pointer may be anywhere: a drag or zoom of the canvas there moves the note away.
    it.each(['pointerdown', 'wheel'])('closes on %s anywhere on the page', (type) => {
        render('changed', [contentChange('Old text', 'Call the customer')]);
        focusBy('keyboard');

        dispatchElsewhere(new Event(type));

        expect(tooltip()).toBeNull();
    });

    it('trims a long text of many lines like the panel tooltips: the start, then the change in a little context', () => {
        const lines = Array.from({ length: 12 }, (_, index) => `Step ${index + 1}: check the order`);
        const current = lines.join('\n');
        const version = lines.map((line, index) => (index === 8 ? 'Step 9: refund the order' : line)).join('\n');
        render('changed', [contentChange(current, version)]);

        dispatch(new Event('mouseenter'));

        // The start of the text, then the struck part with a little context on each side, as in every diff tooltip.
        expect(tooltipValue()).toBe(
            'Step 1: check the order\nStep 2: check th…k the order\nStep 9: [check] the order\nStep 10: …'
        );
        expect(description()).toBe(
            'Current canvas: Step 1: check the order\nStep 2: check th…k the order\nStep 9: check the order\nStep 10: …'
        );
    });

    // The status gate itself: the diff never reports a field change on these, so each is given one here.
    it.each<{ kind: string; status: NodeDiffStatus | null }>([
        { kind: 'an unchanged note', status: 'unchanged' },
        { kind: 'a note a restore adds', status: 'added' },
        { kind: 'a note a restore removes', status: 'deleted' },
        { kind: 'a note off a diff canvas (Preview tab, live editor)', status: null },
    ])('shows no tooltip on $kind, and keeps it out of the tab order', ({ status }) => {
        render(status, [contentChange('Old text', 'Call the customer')]);

        dispatch(new Event('mouseenter'));
        focusBy('keyboard');

        expect(tooltip()).toBeNull();
        expect(note().hasAttribute('tabindex')).toBe(false);
        expect(note().hasAttribute('aria-describedby')).toBe(false);
    });
});
