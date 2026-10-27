import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA, Provider, signal, Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { JsonEditorComponent, RagTabComponent } from '@shared/components';
import { NodeType } from '@shared/models';

import { GraphSessionService } from '../../../features/flows/services/flows-sessions.service';
import { RunSessionSSEService } from '../../../pages/running-graph/services/graph-session-sse.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { provideLoadedExecutionTimeoutLimits } from '../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
import { CodeEditorComponent } from '../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { NodeModel } from '../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../core/providers/flow-editor-preview.token';
import { FlowService } from '../../services/flow.service';
import { KeyValueEntryDraftsService } from '../../services/key-value-entry-drafts.service';
import { PythonCodeRunService } from '../../services/python-code-run.service';
import { FieldChange, FieldName, NodeDiffStatus } from '../../utils/diff';
import { buildFlowModelFromGraphDto } from '../../utils/load';
import { liveGraph } from '../../utils/testing/live-graph.fixture';
import { renderCodeDiffViewWithStubEditor } from '../code-diff-view/code-diff-view.testing';
import { provideChangesTabDiff } from '../missing-reference-note/missing-reference-note.testing';
import { TestPayloadSectionComponent } from './shared/test-payload-section/test-payload-section.component';

/**
 * Everything a version diff shows on a field of a node panel: a field mark (element or row form), an Input List or
 * Key-Value row a restore adds or removes, the note that a restore reorders the Key-Value entries, and a code diff.
 */
export const SHOWN_DIFF_MARKS = [
    '.diff-field-mark--shown',
    '.readonly-row--added',
    '.readonly-row--removed',
    '.entry-row-mark--added',
    '.entry-row-mark--removed',
    '.entry-order-note',
    'app-code-diff-view',
].join(', ');

export interface ChangesTabOptions {
    status?: NodeDiffStatus;
    expanded?: boolean;
    /** `false`: no diff, as on the Preview tab and in the live editor. */
    onChangesTab?: boolean;
}

/** A change a restore makes to a field (not to one of its items). */
export function fieldChange(field: FieldName, current: unknown, version: unknown): FieldChange {
    return { path: field, field, status: 'changed', current, version };
}

/** The node of a type in the live graph fixture, as the canvas holds it: the node a panel shows (the version side). */
export function liveNodeOfType(type: NodeType): NodeModel {
    return buildFlowModelFromGraphDto(liveGraph).nodes.find((node) => node.type === type)!;
}

/**
 * Renders a panel's real template as the version preview shows it, read-only, with `fields` as the open node's
 * changes. The editors that need a browser runtime (Monaco: the code and JSON editors, also in the test payload
 * section, and the code diff) and the RAG search settings are left as their bare elements, so a mark around them still
 * shows.
 */
export function openPanelOnChangesTab<TPanel>(
    component: Type<TPanel>,
    node: NodeModel,
    fields: FieldChange[],
    { status = 'changed', expanded = false, onChangesTab = true }: ChangesTabOptions = {},
    providers: Provider[] = []
): ComponentFixture<TPanel> {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            provideLoadedExecutionTimeoutLimits(),
            { provide: FLOW_EDITOR_PREVIEW, useValue: true },
            { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => false } },
            // The flow graph provides these to the panels.
            KeyValueEntryDraftsService,
            { provide: PythonCodeRunService, useValue: {} },
            { provide: GraphSessionService, useValue: {} },
            { provide: RunSessionSSEService, useValue: { status: signal(null) } },
            ...(onChangesTab ? [provideChangesTabDiff({ status, fields })] : []),
            ...providers,
        ],
    });
    renderCodeDiffViewWithStubEditor();
    for (const host of [component, TestPayloadSectionComponent]) {
        TestBed.overrideComponent(host, {
            remove: { imports: [CodeEditorComponent, JsonEditorComponent, RagTabComponent] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });
    }
    TestBed.inject(FlowService).setFlow(buildFlowModelFromGraphDto(liveGraph));
    const fixture = TestBed.createComponent(component);
    fixture.componentRef.setInput('node', node);
    fixture.componentRef.setInput('isExpanded', expanded);
    fixture.detectChanges();
    return fixture;
}

/** Answers every pending request whose URL ends with `urlEnd`, as the backend would. */
export function respond(urlEnd: string, body: object): void {
    for (const request of TestBed.inject(HttpTestingController).match((candidate) => candidate.url.endsWith(urlEnd))) {
        request.flush(body);
    }
}

/** The marks shown under `root`, each named by the form control or the element it wraps. */
export function markedFields(root: HTMLElement): string[] {
    return Array.from(root.querySelectorAll('app-diff-field-mark.diff-field-mark--shown'), (mark) => {
        const field = mark.firstElementChild!;
        return field.getAttribute('formcontrolname') ?? fieldElementName(field);
    });
}

/** Hovers the mark around the element `wrapped` names; its tooltip's current value, struck parts in brackets. */
export function hoverTooltip(fixture: ComponentFixture<unknown>, wrapped: string): string {
    const mark = Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll('app-diff-field-mark.diff-field-mark--shown')
    ).find((candidate) => candidate.firstElementChild?.matches(wrapped));
    mark!.dispatchEvent(new Event('mouseenter'));
    fixture.detectChanges();
    return Array.from(document.querySelectorAll<HTMLElement>('.diff-field-mark__tooltip-value > span'))
        .map((part) =>
            part.classList.contains('diff-field-mark__struck') ? `[${part.textContent}]` : part.textContent
        )
        .join('');
}

function fieldElementName(element: Element): string {
    const tag = element.tagName.toLowerCase();
    return tag === 'div' ? `div.${element.classList[0]}` : tag;
}
