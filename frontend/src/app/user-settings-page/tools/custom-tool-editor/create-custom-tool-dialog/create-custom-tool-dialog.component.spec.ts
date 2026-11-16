import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { CUSTOM_ELEMENTS_SCHEMA, EnvironmentProviders, Provider } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService, JsonEditorComponent } from '@shared/components';
import {
    CreatePythonCodeToolPayload,
    ExecutionTimeoutLimits,
    GetExecutionTimeoutLimitsResponse,
    GetPythonCodeToolRequest,
    ResourceCode,
} from '@shared/models';
import { ExecutionTimeoutLimitsApiService, SecretsStorageService } from '@shared/services';
import { of, Subject, throwError } from 'rxjs';

import { CustomToolsService } from '../../../../features/tools/services/custom-tools/custom-tools.service';
import { ToolsEventsService } from '../../../../features/tools/services/tools-events.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import {
    executionTimeoutLimitsResponse,
    provideLoadedExecutionTimeoutLimits,
    TEST_EXECUTION_TIMEOUT_LIMITS,
} from '../../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
import { NodeSecretsFieldComponent } from '../../../../visual-programming/components/node-secrets-field/node-secrets-field.component';
import { CodeEditorComponent } from '../code-editor/code-editor.component';
import { ParametersTableViewComponent } from './components/parameters-table-view/parameters-table-view.component';
import { CreateCustomToolDialogComponent } from './create-custom-tool-dialog.component';

const STORED_TOOL: GetPythonCodeToolRequest = {
    id: 7,
    python_code: {
        id: 70,
        code: 'def main():\n    return 1\n',
        entrypoint: 'main',
        secrets: [],
        execution_timeout: 300,
    },
    name: 'Fetch orders',
    description: 'Fetches the latest orders',
    args_schema: { title: 'ArgsSchema', type: 'object', properties: {} },
    built_in: false,
    variables: [],
    use_storage: false,
    is_favorite: false,
    labels: [],
    created_at: '2026-09-15T08:00:00Z',
    updated_at: '2026-10-01T09:30:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

const SECRET_USE_REFUSAL =
    'python_code: secret_ids: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
    'The existing selection was left unchanged. Ask an organization admin to grant it.';

/** A 400 in the backend's envelope: the message starts with the field path it is about. */
function badRequest(message: string): HttpErrorResponse {
    return new HttpErrorResponse({ status: 400, error: { status_code: 400, code: 'invalid', message } });
}

// jsdom has no ResizeObserver; the variables breadcrumb only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

interface CustomToolsFake {
    getPythonCodeTools: ReturnType<typeof vi.fn>;
    createPythonCodeToolV2: ReturnType<typeof vi.fn>;
    updatePythonCodeToolV2: ReturnType<typeof vi.fn>;
    copyPythonCodeTool: ReturnType<typeof vi.fn>;
}

interface ToastFake {
    success: ReturnType<typeof vi.fn>;
    error: ReturnType<typeof vi.fn>;
    warning: ReturnType<typeof vi.fn>;
}

interface OpenedDialog {
    fixture: ComponentFixture<CreateCustomToolDialogComponent>;
    customTools: CustomToolsFake;
    toast: ToastFake;
}

function openDialog(
    selectedTool: GetPythonCodeToolRequest | null,
    limitsProviders: (Provider | EnvironmentProviders)[] = [provideLoadedExecutionTimeoutLimits()],
    canUseSecrets = true
): OpenedDialog {
    const customTools: CustomToolsFake = {
        getPythonCodeTools: vi.fn().mockReturnValue(of([])),
        createPythonCodeToolV2: vi.fn().mockReturnValue(of(STORED_TOOL)),
        updatePythonCodeToolV2: vi.fn().mockReturnValue(of(STORED_TOOL)),
        copyPythonCodeTool: vi.fn().mockReturnValue(of({ ...STORED_TOOL, id: 8, name: 'Fetch orders (copy)' })),
    };
    const toast: ToastFake = { success: vi.fn(), error: vi.fn(), warning: vi.fn() };
    TestBed.configureTestingModule({
        imports: [CreateCustomToolDialogComponent],
        providers: [
            ...limitsProviders,
            {
                provide: DialogRef,
                useValue: {
                    disableClose: false,
                    backdropClick: new Subject(),
                    keydownEvents: new Subject(),
                    close: vi.fn(),
                },
            },
            { provide: DIALOG_DATA, useValue: selectedTool ? { selectedTool } : null },
            { provide: CustomToolsService, useValue: customTools },
            { provide: ToastService, useValue: toast },
            { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
            { provide: ToolsEventsService, useValue: { emitCustomToolCreated: vi.fn() } },
            { provide: SecretsStorageService, useValue: { namesForIds: () => [] } },
            {
                provide: PermissionsService,
                useValue: {
                    canEditSecrets: () => canUseSecrets,
                    can: (resource: ResourceCode) => resource !== ResourceCode.Secrets || canUseSecrets,
                    canAny: () => true,
                },
            },
        ],
    });
    // The editors run Monaco, which does not run in jsdom; none of them plays a part here.
    TestBed.overrideComponent(CreateCustomToolDialogComponent, {
        remove: {
            imports: [
                CodeEditorComponent,
                JsonEditorComponent,
                ParametersTableViewComponent,
                NodeSecretsFieldComponent,
            ],
        },
        add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
    });
    const fixture = TestBed.createComponent(CreateCustomToolDialogComponent);
    fixture.detectChanges();
    return { fixture, customTools, toast };
}

describe('CreateCustomToolDialogComponent execution timeout', () => {
    let fixture: ComponentFixture<CreateCustomToolDialogComponent>;

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());
    let customTools: CustomToolsFake;
    let toast: ToastFake;

    function open(
        selectedTool: GetPythonCodeToolRequest | null,
        limitsProviders: (Provider | EnvironmentProviders)[] = [provideLoadedExecutionTimeoutLimits()]
    ): void {
        ({ fixture, customTools, toast } = openDialog(selectedTool, limitsProviders));
    }

    function timeoutInput(): HTMLInputElement | null {
        return (fixture.nativeElement as HTMLElement).querySelector('app-execution-timeout-field input');
    }

    function typeTimeout(text: string): void {
        const input = timeoutInput()!;
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function sentPythonCode(spy: ReturnType<typeof vi.fn>): CreatePythonCodeToolPayload['python_code'] {
        const payload = spy.mock.calls.at(-1)!.at(-1) as CreatePythonCodeToolPayload;
        return payload.python_code;
    }

    it('shows the stored timeout of an existing tool, without a hint, and sends it back on save', () => {
        open(STORED_TOOL);

        expect(timeoutInput()?.value).toBe('00:05:00');
        expect((fixture.nativeElement as HTMLElement).querySelector('.execution-timeout__hint')).toBeNull();

        fixture.componentInstance.submit();

        expect(customTools.updatePythonCodeToolV2).toHaveBeenCalledOnce();
        expect(sentPythonCode(customTools.updatePythonCodeToolV2).execution_timeout).toBe(300);
    });

    it('shows the default for a new tool without sending it, so the backend applies its own', () => {
        open(null);
        fixture.componentInstance.form.patchValue({ name: 'New tool', description: 'Does things' });

        expect(timeoutInput()?.value).toBe('00:02:00');

        fixture.componentInstance.submit();

        expect(customTools.createPythonCodeToolV2).toHaveBeenCalledOnce();
        expect(sentPythonCode(customTools.createPythonCodeToolV2)).not.toHaveProperty('execution_timeout');
    });

    it('sends an edited timeout', () => {
        open(STORED_TOOL);

        typeTimeout('00:15:00');
        fixture.componentInstance.submit();

        expect(sentPythonCode(customTools.updatePythonCodeToolV2).execution_timeout).toBe(900);
    });

    it('refuses to save a timeout below the minimum, and says why', () => {
        open(STORED_TOOL);

        typeTimeout('00:00:03');
        fixture.componentInstance.submit();

        expect(customTools.updatePythonCodeToolV2).not.toHaveBeenCalled();
        expect(toast.warning).toHaveBeenCalledExactlyOnceWith(
            `Execution timeout must be at least ${TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds} seconds`
        );
    });

    it('counts an edited timeout as an unsaved change', () => {
        open(STORED_TOOL);
        const dialogRef = TestBed.inject(DialogRef) as unknown as { close: ReturnType<typeof vi.fn> };
        const confirm = TestBed.inject(ConfirmationDialogService).confirm as ReturnType<typeof vi.fn>;
        confirm.mockReturnValue(of(false));

        typeTimeout('00:15:00');
        fixture.componentInstance.close();

        expect(confirm).toHaveBeenCalledOnce();
        expect(dialogRef.close).not.toHaveBeenCalled();
    });

    it('shows the timeout of a built-in tool read-only', () => {
        open({ ...STORED_TOOL, built_in: true });

        expect(timeoutInput()?.disabled).toBe(true);
    });

    it('opens without the field when the limits cannot be loaded, and keeps the stored timeout on save', () => {
        open(STORED_TOOL, [
            {
                provide: ExecutionTimeoutLimitsApiService,
                useValue: { getExecutionTimeoutLimits: () => throwError(() => new Error('offline')) },
            },
        ]);

        expect(timeoutInput()).toBeNull();
        expect(toast.error).toHaveBeenCalledExactlyOnceWith(
            'Could not load the execution timeout limits, so the timeout cannot be edited.'
        );

        fixture.componentInstance.submit();

        expect(sentPythonCode(customTools.updatePythonCodeToolV2).execution_timeout).toBe(300);
    });

    it('forks a built-in tool whose stored timeout is below the minimum: the copy is made as it is', () => {
        open({
            ...STORED_TOOL,
            built_in: true,
            python_code: {
                ...STORED_TOOL.python_code,
                execution_timeout: TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds - 2,
            },
        });

        fixture.componentInstance.submit();

        expect(toast.warning).not.toHaveBeenCalled();
        expect(customTools.copyPythonCodeTool).toHaveBeenCalledExactlyOnceWith(STORED_TOOL.id);
    });

    describe('closing an untouched dialog', () => {
        function closesWithoutConfirm(): void {
            const dialogRef = TestBed.inject(DialogRef) as unknown as { close: ReturnType<typeof vi.fn> };
            const confirm = TestBed.inject(ConfirmationDialogService).confirm as ReturnType<typeof vi.fn>;

            fixture.componentInstance.close();

            expect(confirm).not.toHaveBeenCalled();
            expect(dialogRef.close).toHaveBeenCalledOnce();
        }

        /** Opens the dialog with limits that arrive only once `limits` emits, after the dialog is built. */
        function openWithLateLimits(
            selectedTool: GetPythonCodeToolRequest | null
        ): Subject<GetExecutionTimeoutLimitsResponse> {
            const limits = new Subject<GetExecutionTimeoutLimitsResponse>();
            open(selectedTool, [
                { provide: ExecutionTimeoutLimitsApiService, useValue: { getExecutionTimeoutLimits: () => limits } },
            ]);
            return limits;
        }

        function arrive(
            limits: Subject<GetExecutionTimeoutLimitsResponse>,
            value: ExecutionTimeoutLimits = TEST_EXECUTION_TIMEOUT_LIMITS
        ): void {
            limits.next(executionTimeoutLimitsResponse(value));
            limits.complete();
            fixture.detectChanges();
        }

        it('closes an existing tool without asking', () => {
            open(STORED_TOOL);

            closesWithoutConfirm();
        });

        it('closes an existing tool without asking when the limits arrive after the dialog opened', () => {
            const limits = openWithLateLimits(STORED_TOOL);
            expect(timeoutInput()).toBeNull();

            arrive(limits);

            expect(timeoutInput()?.value).toBe('00:05:00');
            closesWithoutConfirm();
        });

        it('closes a new tool without asking when the limits arrive after the dialog opened', () => {
            const limits = openWithLateLimits(null);

            arrive(limits);

            expect(timeoutInput()?.value).toBe('00:02:00');
            closesWithoutConfirm();
        });
    });
});

describe('CreateCustomToolDialogComponent save errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function bannerText(fixture: ComponentFixture<CreateCustomToolDialogComponent>): string {
        const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
        return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
    }

    function save(fixture: ComponentFixture<CreateCustomToolDialogComponent>): void {
        fixture.componentInstance.submit();
        fixture.detectChanges();
    }

    it('shows a secret Use refusal in the banner, with its field labels in words', () => {
        const { fixture, customTools, toast } = openDialog(STORED_TOOL);
        customTools.updatePythonCodeToolV2.mockReturnValueOnce(throwError(() => badRequest(SECRET_USE_REFUSAL)));

        save(fixture);

        expect(bannerText(fixture)).toBe(
            'Python code: Secret ids: Changing the secrets referenced here requires the "Use" permission on ' +
                'Secrets. The existing selection was left unchanged. Ask an organization admin to grant it.'
        );
        expect(toast.error).not.toHaveBeenCalled();
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('shows a duplicate name in the banner', () => {
        const { fixture, customTools } = openDialog(STORED_TOOL);
        customTools.updatePythonCodeToolV2.mockReturnValueOnce(
            throwError(() => badRequest('name: A tool with this name already exists.'))
        );

        save(fixture);

        expect(bannerText(fixture)).toBe('Name: A tool with this name already exists.');
    });

    it('clears the banner when the tool is saved again', () => {
        const { fixture, customTools } = openDialog(STORED_TOOL);
        customTools.updatePythonCodeToolV2.mockReturnValueOnce(
            throwError(() => badRequest('name: A tool with this name already exists.'))
        );
        save(fixture);
        expect(bannerText(fixture)).not.toBe('');

        save(fixture);

        expect(bannerText(fixture)).toBe('');
    });

    it('reports a server error in a toast, not in the banner', () => {
        const { fixture, customTools, toast } = openDialog(STORED_TOOL);
        customTools.updatePythonCodeToolV2.mockReturnValueOnce(
            throwError(() => new HttpErrorResponse({ status: 500, error: { message: 'Unpredictable error' } }))
        );

        save(fixture);

        expect(toast.error).toHaveBeenCalledExactlyOnceWith('Failed to update custom tool. Please try again.');
        expect(bannerText(fixture)).toBe('');
    });
});

describe('CreateCustomToolDialogComponent code that reads secrets', () => {
    const TOOL_READING_SECRET: GetPythonCodeToolRequest = {
        ...STORED_TOOL,
        python_code: { ...STORED_TOOL.python_code, venv_id: null, secrets: [{ id: 4, name: 'API_TOKEN' }] },
    };
    const LOCKED_HINT = 'This code reads secrets. Editing it requires the Use permission on Secrets.';

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    function element(fixture: ComponentFixture<CreateCustomToolDialogComponent>): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function codeEditorIsReadOnly(fixture: ComponentFixture<CreateCustomToolDialogComponent>): boolean {
        return (element(fixture).querySelector('app-code-editor') as HTMLElement & { readOnly: boolean }).readOnly;
    }

    function venvIsReadOnly(fixture: ComponentFixture<CreateCustomToolDialogComponent>): boolean {
        return element(fixture).querySelector('app-select .selector__readonly-value') !== null;
    }

    function makeCopyButton(fixture: ComponentFixture<CreateCustomToolDialogComponent>): HTMLButtonElement {
        return Array.from(element(fixture).querySelectorAll<HTMLButtonElement>('app-button button')).find((button) =>
            button.textContent?.includes('Make Copy')
        )!;
    }

    it('locks the code and venv and the copy for a user without Secrets:Use, and leaves the rest editable', () => {
        const { fixture, customTools } = openDialog(TOOL_READING_SECRET, undefined, false);

        makeCopyButton(fixture).click();

        expect(codeEditorIsReadOnly(fixture)).toBe(true);
        expect(venvIsReadOnly(fixture)).toBe(true);
        expect(element(fixture).querySelector('app-hint-message')?.textContent?.trim()).toBe(LOCKED_HINT);
        expect(makeCopyButton(fixture).getAttribute('aria-disabled')).toBe('true');
        expect(customTools.copyPythonCodeTool).not.toHaveBeenCalled();
        expect(element(fixture).querySelector<HTMLInputElement>('app-custom-input input')!.disabled).toBe(false);
    });

    it.each([
        ['to a user with Secrets:Use', TOOL_READING_SECRET, true],
        ['when the code reads no secret', STORED_TOOL, false],
    ])('leaves the code, venv and copy open %s', (_case, tool, canUseSecrets) => {
        const { fixture, customTools } = openDialog(tool, undefined, canUseSecrets);

        makeCopyButton(fixture).click();

        expect(codeEditorIsReadOnly(fixture)).toBe(false);
        expect(venvIsReadOnly(fixture)).toBe(false);
        expect(element(fixture).querySelector('app-hint-message')).toBeNull();
        expect(customTools.copyPythonCodeTool).toHaveBeenCalledOnce();
    });

    function copyButton(fixture: ComponentFixture<CreateCustomToolDialogComponent>, label: string): HTMLButtonElement {
        return Array.from(element(fixture).querySelectorAll<HTMLButtonElement>('app-button button')).find((button) =>
            button.textContent?.includes(label)
        )!;
    }

    function describedText(
        fixture: ComponentFixture<CreateCustomToolDialogComponent>,
        button: HTMLButtonElement
    ): string {
        const id = button.getAttribute('aria-describedby');
        return id ? (element(fixture).querySelector(`[id="${id}"]`)?.textContent?.trim() ?? '') : '';
    }

    function pressEnter(): void {
        const keydownEvents = TestBed.inject(DialogRef).keydownEvents as Subject<KeyboardEvent>;
        keydownEvents.next(new KeyboardEvent('keydown', { key: 'Enter', cancelable: true }));
    }

    it.each([
        ['Make Copy', TOOL_READING_SECRET],
        ['Create Editable Copy', { ...TOOL_READING_SECRET, built_in: true }],
    ])('tells keyboard and screen-reader users why "%s" is blocked', (label, tool) => {
        const { fixture } = openDialog(tool, undefined, false);

        expect(describedText(fixture, copyButton(fixture, label))).toBe(
            'This code reads secrets. Copying it requires the Use permission on Secrets.'
        );
    });

    it('leaves the copy button without a blocked reason when the copy is allowed', () => {
        const { fixture } = openDialog(TOOL_READING_SECRET);

        expect(copyButton(fixture, 'Make Copy').hasAttribute('aria-describedby')).toBe(false);
    });

    it.each([
        ['does not copy a built-in tool on Enter for a user without Secrets:Use', false, 0],
        ['copies a built-in tool on Enter for a user with Secrets:Use', true, 1],
    ])('%s', (_case, canUseSecrets, copies) => {
        const { customTools } = openDialog({ ...TOOL_READING_SECRET, built_in: true }, undefined, canUseSecrets);

        pressEnter();

        expect(customTools.copyPythonCodeTool).toHaveBeenCalledTimes(copies);
    });

    function parametersTableIsReadOnly(fixture: ComponentFixture<CreateCustomToolDialogComponent>): boolean {
        return (element(fixture).querySelector('app-parameters-table-view') as HTMLElement & { readOnly: boolean })
            .readOnly;
    }

    it.each([
        ['locks the variables for a user without Secrets:Use', false, true],
        ['leaves the variables editable for a user with Secrets:Use', true, false],
    ])('%s', (_case, canUseSecrets, locked) => {
        const { fixture } = openDialog(TOOL_READING_SECRET, undefined, canUseSecrets);

        expect(parametersTableIsReadOnly(fixture)).toBe(locked);
    });

    it('sends locked variables back exactly as loaded when the rest of the tool is saved', () => {
        // Stored without the fields the table adds when it writes a parameter back.
        const variables = [{ name: 'limit', type: 'integer' }];
        const { fixture, customTools } = openDialog({ ...TOOL_READING_SECRET, variables }, undefined, false);
        fixture.componentInstance.form.controls.description.setValue('Fetches the latest orders, newest first');

        fixture.componentInstance.submit();

        const payload = customTools.updatePythonCodeToolV2.mock.calls.at(-1)!.at(-1) as CreatePythonCodeToolPayload;
        expect(payload.variables).toEqual(variables);
    });

    it('shows the reason the backend gives for refusing a copy in the banner', () => {
        const reason = 'This contains code that reads secrets. This action requires the Use permission on secrets.';
        const { fixture, customTools, toast } = openDialog(TOOL_READING_SECRET);
        customTools.copyPythonCodeTool.mockReturnValueOnce(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 403,
                        error: {
                            status_code: 403,
                            code: 'code_with_secrets_requires_secrets_use_permission',
                            message: reason,
                        },
                    })
            )
        );
        vi.spyOn(console, 'error').mockImplementation(() => undefined);

        makeCopyButton(fixture).click();
        fixture.detectChanges();

        expect(element(fixture).querySelector('app-error-banner')?.textContent?.trim()).toBe(reason);
        expect(toast.error).not.toHaveBeenCalled();
    });
});
