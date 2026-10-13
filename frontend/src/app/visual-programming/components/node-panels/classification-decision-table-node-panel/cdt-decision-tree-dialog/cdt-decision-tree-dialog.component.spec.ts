import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FFlowModule, FZoomDirective } from '@foblex/flow';
import { NodeType } from '@shared/models';
import { Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { CDT_EXPLANATION_LIMITS } from '../../../../core/constants/cdt-explanation-limits';
import { CdtExplainRequest, CdtExplainResponse } from '../../../../core/models/cdt-explain-api.model';
import { CdtExplanation, CdtExplanations } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../../core/providers/flow-editor-preview.token';
import { CdtExplainApiService } from '../../../../services/cdt-explain-api.service';
import { FlowService } from '../../../../services/flow.service';
import { SidePanelService } from '../../../../services/side-panel.service';
import { CDT_TREE_COPY } from './cdt-decision-tree.constants';
import { CdtDecisionTreeInput } from './cdt-decision-tree.model';
import { CdtDecisionTreeBlockComponent } from './cdt-decision-tree-block/cdt-decision-tree-block.component';
import { CdtDecisionTreeDialogComponent } from './cdt-decision-tree-dialog.component';
import { buildExplainStepKeys, explainStepFingerprint } from './cdt-explain.identity';
import { buildCdtExplainBlocks } from './cdt-explain.payload';
import { explainErrorMessage } from './cdt-explain-error.util';

/**
 * The decision-tree dialog's Explain behaviour, through its real template: the
 * toolbar's Explain All, the canvas blocks' markers and the detail window.
 *
 * Foblex is stripped (its module and the zoom directive are removed and the
 * schema relaxed): jsdom cannot lay out its canvas, and nothing here depends on
 * one. So edges, fit-to-screen, zoom and centring a block are not covered. The
 * explanation store, `FlowService` and the read-only state are the real ones;
 * only the explain endpoint is a stub.
 */

const NODE_ID = 'table1';
const MODEL = 7;

function rule(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: 'Rule',
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        dock_visible: true,
        continue_flag: true,
        ...overrides,
    };
}

const SAVED_ROWS: ConditionGroup[] = [
    rule({ group_name: 'Spam', route_code: 'spam', expression: 'score > 0.9', order: 1 }),
    rule({ group_name: 'Refund', route_code: 'refund', expression: "intent == 'refund'", order: 2 }),
    rule({ group_name: 'Urgent', route_code: 'urgent', expression: 'priority > 3', order: 3 }),
];

function input(overrides: Partial<CdtDecisionTreeInput> = {}): CdtDecisionTreeInput {
    return {
        nodeId: NODE_ID,
        backendId: 21,
        nodeName: 'Triage',
        preCode: '',
        postCode: '',
        preInputMap: {},
        postInputMap: {},
        preLibraries: [],
        postLibraries: [],
        preOutputVariablePath: null,
        postOutputVariablePath: null,
        prompts: {},
        rows: SAVED_ROWS,
        canvasRows: SAVED_ROWS,
        defaultNextNode: null,
        errorNextNode: null,
        connections: [],
        nodes: [],
        defaultLlmConfig: MODEL,
        llmConfigOptions: [{ id: MODEL, label: 'Fast', modelName: 'gpt-4o-mini', providerIcon: '', hasApiKey: true }],
        readOnly: false,
        ...overrides,
    };
}

/** The table's model as the picker lists it when it has no credential. */
const KEYLESS_MODEL: CdtDecisionTreeInput['llmConfigOptions'][number] = {
    id: MODEL,
    label: 'Fast',
    modelName: 'gpt-4o-mini',
    providerIcon: '',
    hasApiKey: false,
};

/** Past the stored text length limit by one character. */
const TOO_LONG = 't'.repeat(CDT_EXPLANATION_LIMITS.maxTextLength + 1);

/** What the endpoint answers when every batch failed for a model with no key. */
function missingKeyError(): HttpErrorResponse {
    return new HttpErrorResponse({
        status: 422,
        error: {
            status_code: 422,
            code: 'cdt_explain_llm_config_missing_key',
            message: `LLM config ${MODEL} has no API key.`,
        },
    });
}

function withExpression(rows: readonly ConditionGroup[], name: string, expression: string): ConditionGroup[] {
    return rows.map((row) => (row.group_name === name ? { ...row, expression } : row));
}

/** The key and fingerprint the dialog files a rule's decision step under, for this input. */
function decisionStep(data: CdtDecisionTreeInput, name: string): { key: string; fingerprint: string } {
    const index = data.rows.findIndex((row) => row.group_name === name);
    const blockId = `row-${index}:decision`;
    const block = buildCdtExplainBlocks(data).get(blockId)!;
    return { key: buildExplainStepKeys(data).get(blockId)!, fingerprint: explainStepFingerprint(block) };
}

function stored(text: string, fingerprint: string): CdtExplanation {
    return { text, fingerprint, generatedBy: 'gpt-4o-mini' };
}

function explained(id: string, text: string): CdtExplainResponse['explanations'][number] {
    return { id, text, generated_by: 'gpt-4o-mini' };
}

describe('CdtDecisionTreeDialogComponent — explanations', () => {
    let fixture: ComponentFixture<CdtDecisionTreeDialogComponent>;
    let host: HTMLElement;
    let flowService: FlowService;
    let explainApi: { explain: ReturnType<typeof vi.fn> };
    let persistRequests: string[];

    beforeAll(() => {
        // The detail window measures its code block with a ResizeObserver; jsdom has none.
        const scope = globalThis as unknown as { ResizeObserver?: unknown };
        scope.ResizeObserver ??= class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        };
    });

    function mount(
        data: CdtDecisionTreeInput,
        nodeExplanations: CdtExplanations = {},
        options: { isPreview?: boolean } = {}
    ): void {
        TestBed.resetTestingModule();
        localStorage.clear();
        explainApi = { explain: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: DIALOG_DATA, useValue: data },
                {
                    provide: DialogRef,
                    useValue: { close: vi.fn(), backdropClick: new Subject(), keydownEvents: new Subject() },
                },
                { provide: CdtExplainApiService, useValue: explainApi },
                { provide: FLOW_EDITOR_PREVIEW, useValue: options.isPreview ?? false },
                { provide: PermissionsService, useValue: { can: () => !data.readOnly } },
            ],
        });
        TestBed.overrideComponent(CdtDecisionTreeDialogComponent, {
            remove: { imports: [FFlowModule, FZoomDirective] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });
        TestBed.overrideComponent(CdtDecisionTreeBlockComponent, {
            remove: { imports: [FFlowModule] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });

        flowService = TestBed.inject(FlowService);
        flowService.setFlow({
            nodes: [
                {
                    id: NODE_ID,
                    backendId: data.backendId,
                    type: NodeType.CLASSIFICATION_TABLE,
                    node_name: 'Triage',
                    data: { name: 'Triage', table: { condition_groups: [...data.rows] } },
                    explanations: nodeExplanations,
                } as unknown as ClassificationDecisionTableNodeModel,
            ],
            connections: [],
        });
        persistRequests = [];
        TestBed.inject(SidePanelService).cdtExplanationsSaveRequest$.subscribe((nodeId) =>
            persistRequests.push(nodeId)
        );

        fixture = TestBed.createComponent(CdtDecisionTreeDialogComponent);
        host = fixture.nativeElement;
        fixture.detectChanges();
    }

    afterEach(() => {
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
        localStorage.clear();
    });

    function render(): void {
        fixture.detectChanges();
    }

    function blockTitled(title: string): HTMLElement {
        const block = [...host.querySelectorAll<HTMLElement>('app-cdt-decision-tree-block')].find(
            (candidate) => candidate.querySelector('.cdt-tree-block__title')?.textContent?.trim() === title
        );
        if (!block) throw new Error(`no block titled ${title}`);
        return block;
    }

    function openBlock(title: string): void {
        blockTitled(title).querySelector<HTMLElement>('.cdt-tree-block__body')!.click();
        render();
    }

    function detail(): HTMLElement | null {
        return host.querySelector<HTMLElement>('app-cdt-decision-tree-detail');
    }

    function detailText(): string {
        return detail()?.querySelector('.cdt-tree-detail__explanation')?.textContent?.trim() ?? '';
    }

    function clickExplainStep(): void {
        detail()!.querySelector<HTMLButtonElement>('.cdt-tree-detail__explain')!.click();
        render();
    }

    function clickExplainAll(): void {
        host.querySelector<HTMLButtonElement>('.cdt-tree__explain-all-run')!.click();
        render();
    }

    function notice(): string {
        return host.querySelector('.cdt-tree__explain-all-notice')?.textContent?.trim() ?? '';
    }

    function isMarkedOutdated(title: string): boolean {
        return !!blockTitled(title).querySelector('.cdt-tree-block__outdated');
    }

    function isMarkedLoading(title: string): boolean {
        return !!blockTitled(title).querySelector('.cdt-tree-block__explaining');
    }

    function nodeExplanations(): CdtExplanations {
        return (flowService.nodes()[0] as ClassificationDecisionTableNodeModel).explanations ?? {};
    }

    function sentBlockIds(call = 0): string[] {
        const request = explainApi.explain.mock.calls[call][1] as CdtExplainRequest;
        return request.blocks.map((block) => block.id);
    }

    describe('a read-only editor', () => {
        it('shows stored explanations and offers nothing to generate one', () => {
            const data = input({ readOnly: true });
            const spam = decisionStep(data, 'Spam');
            mount(data, { [spam.key]: stored('Bins spam', spam.fingerprint) });

            openBlock('Spam');

            expect(host.querySelector('.cdt-tree__explain-all')).toBeNull();
            expect(detail()?.querySelector('.cdt-tree-detail__explain')).toBeNull();
            expect(detailText()).toBe('Bins spam');
        });
    });

    describe('Explain Step', () => {
        it('files the answer under the step, on the node, and asks for it to be persisted', () => {
            const data = input();
            mount(data);
            explainApi.explain.mockReturnValue(
                of({ explanations: [explained('row-0:decision', 'Bins spam')], failures: [] })
            );

            openBlock('Spam');
            clickExplainStep();

            expect(explainApi.explain).toHaveBeenCalledExactlyOnceWith(
                21,
                expect.objectContaining({ llm_config: MODEL })
            );
            expect(sentBlockIds()).toEqual(['row-0:decision']);
            expect(detailText()).toBe('Bins spam');
            const spam = decisionStep(data, 'Spam');
            expect(nodeExplanations()).toEqual({ [spam.key]: stored('Bins spam', spam.fingerprint) });
            expect(persistRequests).toEqual([NODE_ID]);
        });

        it('says to save first for a table the server has not got, and sends nothing', () => {
            mount(input({ backendId: null }));

            openBlock('Spam');
            clickExplainStep();

            expect(explainApi.explain).not.toHaveBeenCalled();
            expect(detailText()).toBe(CDT_TREE_COPY.explainUnsaved);
        });

        it('says to pick a model when neither the table nor a prompt names one', () => {
            mount(input({ defaultLlmConfig: null }));

            openBlock('Spam');
            clickExplainStep();

            expect(explainApi.explain).not.toHaveBeenCalled();
            expect(detailText()).toBe(CDT_TREE_COPY.explainNoModel);
        });

        it('shows an explanation too long to save as an error, and keeps it off the node', () => {
            mount(input());
            explainApi.explain.mockReturnValue(
                of({ explanations: [explained('row-0:decision', TOO_LONG)], failures: [] })
            );

            openBlock('Spam');
            clickExplainStep();

            expect(detailText()).toBe('This explanation is too long to save.');
            expect(nodeExplanations()).toEqual({});
            expect(persistRequests).toEqual([]);
        });

        it('reports a step the response left out as failed', () => {
            mount(input());
            explainApi.explain.mockReturnValue(of({ explanations: [], failures: [] }));

            openBlock('Spam');
            clickExplainStep();

            expect(detailText()).toBe(CDT_TREE_COPY.explainFailed);
            expect(nodeExplanations()).toEqual({});
        });

        it('shows a refusal over the text that was there, and keeps the stored copy', () => {
            const data = input();
            const spam = decisionStep(data, 'Spam');
            mount(data, { [spam.key]: stored('Bins spam', spam.fingerprint) });
            explainApi.explain.mockReturnValue(
                of({ explanations: [], failures: [{ id: 'row-0:decision', detail: 'Refused by the model.' }] })
            );

            openBlock('Spam');
            expect(detailText()).toBe('Bins spam');
            clickExplainStep();

            expect(detailText()).toBe('Refused by the model.');
            expect(nodeExplanations()[spam.key].text).toBe('Bins spam');
        });

        it('shows the reason a failed request gives', () => {
            mount(input());
            explainApi.explain.mockReturnValue(
                throwError(
                    () => new HttpErrorResponse({ status: 404, error: { code: 'cdt_explain_llm_config_not_found' } })
                )
            );

            openBlock('Spam');
            clickExplainStep();

            expect(detailText()).toBe(CDT_TREE_COPY.explainModelGone);
        });

        it('asks with a model that has no key — a keyless provider needs none — and names the key when the endpoint misses it', () => {
            mount(input({ llmConfigOptions: [KEYLESS_MODEL] }));
            explainApi.explain.mockReturnValue(throwError(() => missingKeyError()));

            openBlock('Spam');
            clickExplainStep();

            expect(explainApi.explain).toHaveBeenCalledExactlyOnceWith(
                21,
                expect.objectContaining({ llm_config: MODEL })
            );
            expect(detailText()).toBe('The selected model has no API key. Choose another model or add a key.');
        });

        it('asks about a model the picker does not list, and lets the endpoint say it is gone', () => {
            mount(input({ llmConfigOptions: [] }));
            explainApi.explain.mockReturnValue(
                throwError(
                    () => new HttpErrorResponse({ status: 404, error: { code: 'cdt_explain_llm_config_not_found' } })
                )
            );

            openBlock('Spam');
            clickExplainStep();

            expect(explainApi.explain).toHaveBeenCalledTimes(1);
            expect(detailText()).toBe('The selected model no longer exists. Choose another model.');
        });

        it('files an answer under the id it carries, not under whichever block is open', () => {
            const data = input();
            mount(data);
            const response = new Subject<CdtExplainResponse>();
            explainApi.explain.mockReturnValue(response);

            openBlock('Spam');
            clickExplainStep();
            openBlock('Refund');
            response.next({ explanations: [explained('row-0:decision', 'Bins spam')], failures: [] });
            response.complete();
            render();

            expect(detailText()).toBe(CDT_TREE_COPY.explanationEmpty);
            openBlock('Spam');
            expect(detailText()).toBe('Bins spam');
        });
    });

    describe('explainErrorMessage', () => {
        it.each([
            ['cdt_explain_llm_config_not_found', CDT_TREE_COPY.explainModelGone],
            ['cdt_explain_llm_config_missing_key', CDT_TREE_COPY.explainNoApiKey],
            ['cdt_explain_upstream_failed', CDT_TREE_COPY.explainUpstreamFailed],
            ['something_else', CDT_TREE_COPY.explainFailed],
            // Not a key of the lookup, however it is spelt.
            ['constructor', CDT_TREE_COPY.explainFailed],
        ])('maps %s to its message', (code, message) => {
            expect(explainErrorMessage(new HttpErrorResponse({ status: 400, error: { code } }))).toBe(message);
        });

        it('falls back to the generic message when the body has no code', () => {
            expect(explainErrorMessage(new HttpErrorResponse({ status: 500, error: null }))).toBe(
                CDT_TREE_COPY.explainFailed
            );
        });

        // The developer-approved wording, pinned: a rewording has to be a decision, not a drive-by.
        it('says the approved sentences for a missing key and a missing model', () => {
            expect(explainErrorMessage(missingKeyError())).toBe(
                'The selected model has no API key. Choose another model or add a key.'
            );
            expect(
                explainErrorMessage(
                    new HttpErrorResponse({ status: 404, error: { code: 'cdt_explain_llm_config_not_found' } })
                )
            ).toBe('The selected model no longer exists. Choose another model.');
        });
    });

    describe('Explain All', () => {
        /** Spam is current, Refund is outdated, Urgent has none; post-computation is drawn twice. */
        function mountMixed(): CdtDecisionTreeInput {
            const data = input({ postCode: 'result = 1' });
            const spam = decisionStep(data, 'Spam');
            const refund = decisionStep(data, 'Refund');
            mount(data, {
                [spam.key]: stored('Bins spam', spam.fingerprint),
                [refund.key]: stored('Old refund text', 'an-older-fingerprint'),
            });
            return data;
        }

        function toggleOutdatedOnly(): void {
            host.querySelector<HTMLElement>('.cdt-tree__explain-all-menu')!.click();
            render();
            const toggle = document.querySelector<HTMLElement>(
                '.cdt-tree-explain-menu__toggle input, .cdt-tree-explain-menu__toggle [role="checkbox"]'
            );
            if (!toggle) throw new Error('no outdated-only toggle in the menu');
            toggle.click();
            render();
        }

        /** Answered at once: the chunks run one after another, so a pending one would hide the next. */
        function answerEveryChunk(): void {
            explainApi.explain.mockImplementation(
                (_id: number, request: CdtExplainRequest): Observable<CdtExplainResponse> =>
                    of({ explanations: request.blocks.map((block) => explained(block.id, 'text')), failures: [] })
            );
        }

        function askedBlockIds(): string[] {
            return explainApi.explain.mock.calls.flatMap((_, call) => sentBlockIds(call)).sort();
        }

        it('asks about every step without an up-to-date explanation — missing or outdated — the twice-drawn one once', () => {
            mountMixed();
            answerEveryChunk();

            clickExplainAll();

            // Spam is current and left alone; Refund is outdated; Urgent and the post step have none.
            expect(askedBlockIds()).toEqual(['exit:default:post', 'row-1:decision', 'row-2:decision']);
        });

        it('leaves no step outdated once it has run, filing each answer under the step’s current fingerprint', () => {
            const data = mountMixed();
            answerEveryChunk();

            clickExplainAll();

            for (const name of ['Spam', 'Refund', 'Urgent']) expect(isMarkedOutdated(name)).toBe(false);
            const refund = decisionStep(data, 'Refund');
            expect(nodeExplanations()[refund.key]).toEqual(stored('text', refund.fingerprint));

            // And a second press finds nothing left to do.
            explainApi.explain.mockClear();
            clickExplainAll();
            expect(explainApi.explain).not.toHaveBeenCalled();
            expect(notice()).toBe(CDT_TREE_COPY.explainAllNothing);
        });

        it('with "outdated only", asks only about steps whose explanation went stale', () => {
            mountMixed();
            explainApi.explain.mockReturnValue(new Subject());

            toggleOutdatedOnly();
            clickExplainAll();

            expect(explainApi.explain).toHaveBeenCalledTimes(1);
            expect(sentBlockIds()).toEqual(['row-1:decision']);
        });

        it('says so when there is nothing to do', () => {
            const data = input();
            const keys = Object.fromEntries(
                ['Spam', 'Refund', 'Urgent'].map((name) => {
                    const step = decisionStep(data, name);
                    return [step.key, stored(`${name} text`, step.fingerprint)];
                })
            );
            mount(data, keys);

            clickExplainAll();

            expect(explainApi.explain).not.toHaveBeenCalled();
            expect(notice()).toBe(CDT_TREE_COPY.explainAllNothing);
        });

        it('does not claim nothing is left to do while one step is outdated', () => {
            const data = input();
            const keys = Object.fromEntries(
                ['Spam', 'Refund', 'Urgent'].map((name) => {
                    const step = decisionStep(data, name);
                    return [
                        step.key,
                        stored(`${name} text`, name === 'Refund' ? 'an-older-fingerprint' : step.fingerprint),
                    ];
                })
            );
            mount(data, keys);
            explainApi.explain.mockReturnValue(new Subject());

            clickExplainAll();

            expect(notice()).toBe('');
            expect(sentBlockIds()).toEqual(['row-1:decision']);
        });

        it('shows progress, marks the pending steps, and offers Stop while it runs', () => {
            mountMixed();
            const firstChunk = new Subject<CdtExplainResponse>();
            explainApi.explain.mockReturnValueOnce(firstChunk).mockReturnValueOnce(new Subject());

            clickExplainAll();
            const label = (): string => host.querySelector('.cdt-tree__explain-all-label')?.textContent?.trim() ?? '';

            expect(label()).toBe(CDT_TREE_COPY.explainAllBusy(0, 3));
            expect(isMarkedLoading('Urgent')).toBe(true);
            expect(isMarkedLoading('Spam')).toBe(false);
            expect(host.querySelector('.cdt-tree__explain-all-stop')).not.toBeNull();

            const [firstIds] = [sentBlockIds(0)];
            firstChunk.next({ explanations: firstIds.map((id) => explained(id, `text for ${id}`)), failures: [] });
            firstChunk.complete();
            render();

            expect(label()).toBe(CDT_TREE_COPY.explainAllBusy(1, 3));
        });

        it('on Stop, puts back what each pending step had: stored text stays, the rest clears', () => {
            mountMixed();
            explainApi.explain.mockReturnValue(new Subject());
            toggleOutdatedOnly();
            clickExplainAll();
            expect(isMarkedLoading('Refund')).toBe(true);

            host.querySelector<HTMLButtonElement>('.cdt-tree__explain-all-stop')!.click();
            render();

            expect(isMarkedLoading('Refund')).toBe(false);
            expect(isMarkedOutdated('Refund')).toBe(true);
            openBlock('Refund');
            expect(detailText()).toBe('Old refund text');
            expect(host.querySelector('.cdt-tree__explain-all-stop')).toBeNull();
        });

        it('on a failed request, says so and leaves no step spinning', () => {
            mountMixed();
            explainApi.explain.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 502 })));

            clickExplainAll();

            expect(notice()).toBe(CDT_TREE_COPY.explainFailed);
            expect(isMarkedLoading('Urgent')).toBe(false);
            openBlock('Urgent');
            expect(detailText()).toBe(CDT_TREE_COPY.explanationEmpty);
        });

        it.each([
            ['cdt_explain_llm_config_not_found', 404, CDT_TREE_COPY.explainModelGone],
            ['cdt_explain_llm_config_missing_key', 422, CDT_TREE_COPY.explainNoApiKey],
            ['cdt_explain_upstream_failed', 502, CDT_TREE_COPY.explainUpstreamFailed],
        ])('reads a failed request’s %s the way Explain Step does', (code, status, message) => {
            mountMixed();
            explainApi.explain.mockReturnValue(throwError(() => new HttpErrorResponse({ status, error: { code } })));

            clickExplainAll();

            expect(notice()).toBe(message);
        });

        it('keeps what the chunks before a failed one explained, and leaves nothing spinning', () => {
            mountMixed();
            explainApi.explain
                .mockImplementationOnce(
                    (_id: number, request: CdtExplainRequest): Observable<CdtExplainResponse> =>
                        of({
                            explanations: request.blocks.map((block) => explained(block.id, `text for ${block.id}`)),
                            failures: [],
                        })
                )
                .mockReturnValueOnce(
                    throwError(
                        () =>
                            new HttpErrorResponse({
                                status: 404,
                                error: { code: 'cdt_explain_llm_config_not_found' },
                            })
                    )
                );

            clickExplainAll();

            expect(explainApi.explain).toHaveBeenCalledTimes(2);
            const [firstId] = sentBlockIds(0);
            expect(notice()).toBe(CDT_TREE_COPY.explainModelGone);
            expect(host.querySelector('.cdt-tree-block__explaining')).toBeNull();
            expect(host.querySelector('.cdt-tree__explain-all-stop')).toBeNull();
            // The first chunk's answer was kept on the node; the failed chunk wrote nothing:
            // the outdated step keeps its old text, the missing one stays missing.
            const stepKeys = buildExplainStepKeys(input({ postCode: 'result = 1' }));
            expect(nodeExplanations()[stepKeys.get(firstId)!]?.text).toBe(`text for ${firstId}`);
            expect(sentBlockIds(1)).toEqual(['row-1:decision', 'row-2:decision']);
            expect(nodeExplanations()[stepKeys.get('row-1:decision')!]?.text).toBe('Old refund text');
            expect(nodeExplanations()[stepKeys.get('row-2:decision')!]).toBeUndefined();
        });

        it('asks with a model that has no key, and names the key when the endpoint misses it', () => {
            mount(input({ llmConfigOptions: [KEYLESS_MODEL] }));
            explainApi.explain.mockReturnValue(throwError(() => missingKeyError()));

            clickExplainAll();

            expect(explainApi.explain).toHaveBeenCalledTimes(1);
            expect(notice()).toBe('The selected model has no API key. Choose another model or add a key.');
        });

        it('counts an explanation too long to save among the steps that could not be explained', () => {
            mountMixed();
            explainApi.explain.mockImplementation(
                (_id: number, request: CdtExplainRequest): Observable<CdtExplainResponse> =>
                    of({ explanations: request.blocks.map((block) => explained(block.id, TOO_LONG)), failures: [] })
            );

            clickExplainAll();

            expect(notice()).toBe(CDT_TREE_COPY.explainAllFailed(3));
            openBlock('Urgent');
            expect(detailText()).toBe(CDT_TREE_COPY.explanationTooLarge);
        });

        it('counts the steps the model would not explain once the pass ends', () => {
            mountMixed();
            explainApi.explain.mockImplementation(
                (_id: number, request: CdtExplainRequest): Observable<CdtExplainResponse> =>
                    of({
                        explanations: [],
                        failures: request.blocks.map((block) => ({ id: block.id, detail: 'Refused.' })),
                    })
            );

            clickExplainAll();

            expect(notice()).toBe(CDT_TREE_COPY.explainAllFailed(3));
        });
    });

    // The developer's rule: an explanation keeps the fingerprint of the content it
    // explained. Generated against edits that never get saved, or against content
    // that changes later, it must read as outdated against what is there now.
    describe('outdated after the table moves on', () => {
        function explainSpam(data: CdtDecisionTreeInput): CdtExplanations {
            mount(data);
            explainApi.explain.mockReturnValue(
                of({ explanations: [explained('row-0:decision', 'Bins spam')], failures: [] })
            );
            openBlock('Spam');
            clickExplainStep();
            return nodeExplanations();
        }

        it('is not outdated when the dialog reopens over the content it explained', () => {
            const data = input();
            const persisted = explainSpam(data);

            mount(data, persisted);

            expect(isMarkedOutdated('Spam')).toBe(false);
        });

        it('is outdated once the unsaved edits it explained are discarded', () => {
            const unsaved = withExpression(SAVED_ROWS, 'Spam', 'score > 0.5');
            const persisted = explainSpam(input({ rows: unsaved }));

            // The edit is discarded: the table is back to what was saved.
            mount(input(), persisted);

            expect(isMarkedOutdated('Spam')).toBe(true);
            openBlock('Spam');
            expect(detailText()).toBe('Bins spam');
            expect(detail()?.querySelector('.cdt-tree-detail__outdated')?.textContent?.trim()).toBe(
                CDT_TREE_COPY.outdatedBadge
            );
        });

        it('is outdated once the step changes after it was explained', () => {
            const persisted = explainSpam(input());

            mount(input({ rows: withExpression(SAVED_ROWS, 'Spam', 'score > 0.99') }), persisted);

            expect(isMarkedOutdated('Spam')).toBe(true);
            expect(isMarkedOutdated('Refund')).toBe(false);
        });
    });
});
