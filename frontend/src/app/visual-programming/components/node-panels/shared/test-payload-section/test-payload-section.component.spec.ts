import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { JsonEditorComponent } from '@shared/components';

import { checkTestPayloadText } from '../../../../utils/test-run';
import { TestPayloadSectionComponent } from './test-payload-section.component';

describe('TestPayloadSectionComponent', () => {
    let fixture: ComponentFixture<TestPayloadSectionComponent>;

    beforeEach(() => {
        TestBed.configureTestingModule({ imports: [TestPayloadSectionComponent] });
        // Monaco does not run in jsdom: render the JSON editor as an unknown element.
        TestBed.overrideComponent(TestPayloadSectionComponent, {
            remove: { imports: [JsonEditorComponent] },
            add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
        fixture = TestBed.createComponent(TestPayloadSectionComponent);
        showText('{}');
    });

    /** Binds `text` with its check, as the panel does (`TriggerTestPayloadState.check`). */
    function showText(text: string, ruleErrors: string[] = [], hints: string[] = []): void {
        fixture.componentRef.setInput('text', text);
        fixture.componentRef.setInput(
            'check',
            checkTestPayloadText(text, () => ({ errors: ruleErrors, hints }))
        );
    }

    function messageTexts(selector: string): string[] {
        return fixture.debugElement.queryAll(By.css(`${selector} li`)).map((item) => item.nativeElement.textContent);
    }

    function errorTexts(): string[] {
        return messageTexts('.payload-messages--error');
    }

    function hintTexts(): string[] {
        return messageTexts('.payload-messages--hint');
    }

    function editor() {
        return fixture.debugElement.query(By.css('app-json-editor'));
    }

    it('shows no errors for a JSON object', () => {
        fixture.detectChanges();

        expect(errorTexts()).toEqual([]);
        expect(fixture.nativeElement.querySelector('.payload-messages')).toBeNull();
    });

    it('shows why the text cannot be run', () => {
        showText('[1, 2]');
        fixture.detectChanges();

        expect(errorTexts()).toEqual(['Test payload must be a JSON object.']);
    });

    it('shows the rule errors of the check it is given, without checking the text itself', () => {
        fixture.componentRef.setInput('text', 'not even JSON');
        fixture.componentRef.setInput('check', {
            payload: { x: 1 },
            parseError: null,
            ruleErrors: ["'x': not a field parent selected on this node"],
            hints: [],
        });
        fixture.detectChanges();

        expect(errorTexts()).toEqual(["'x': not a field parent selected on this node"]);
    });

    it('shows the parse error instead of rule errors', () => {
        showText('{"x": ', ['never shown']);
        fixture.detectChanges();

        expect(errorTexts()).toEqual([expect.stringMatching(/^Invalid JSON: /)]);
    });

    it('announces the errors politely, not as an alert', () => {
        showText('nope');
        fixture.detectChanges();

        const list: HTMLElement = fixture.nativeElement.querySelector('.payload-messages--error');
        expect(list.getAttribute('role')).toBe('status');
        expect(list.getAttribute('aria-live')).toBe('polite');
    });

    it('shows rule hints apart from the errors, as a muted status', () => {
        showText('{}', ["'x': not a field parent selected on this node"], ['Select fields first.']);
        fixture.detectChanges();

        expect(hintTexts()).toEqual(['Select fields first.']);
        expect(errorTexts()).toEqual(["'x': not a field parent selected on this node"]);
        const hintList: HTMLElement = fixture.nativeElement.querySelector('.payload-messages--hint');
        expect(hintList.classList).not.toContain('payload-messages--error');
        expect(hintList.getAttribute('role')).toBe('status');
    });

    it('shows a hint alone without any error list', () => {
        showText('{}', [], ['Select fields first.']);
        fixture.detectChanges();

        expect(hintTexts()).toEqual(['Select fields first.']);
        expect(fixture.nativeElement.querySelector('.payload-messages--error')).toBeNull();
    });

    it('lists server errors after client errors', () => {
        showText('nope');
        fixture.componentRef.setInput('serverErrors', ["'message.text': field not selected on this node"]);
        fixture.detectChanges();

        expect(errorTexts()).toEqual([
            expect.stringMatching(/^Invalid JSON: /),
            "'message.text': field not selected on this node",
        ]);
    });

    it('writes editor changes back to the text model', () => {
        fixture.detectChanges();

        editor().triggerEventHandler('jsonChange', '{"id": 1}');

        expect(fixture.componentInstance.text()).toBe('{"id": 1}');
    });

    it('hides the editor but keeps the errors when collapsed', () => {
        showText('nope');
        fixture.detectChanges();

        fixture.debugElement.query(By.css('.section-toggle')).nativeElement.click();
        fixture.detectChanges();

        expect(editor()).toBeNull();
        expect(errorTexts().length).toBe(1);
    });

    it('moves the title into the editor header when not collapsible', () => {
        fixture.componentRef.setInput('collapsible', false);
        fixture.detectChanges();

        expect(fixture.debugElement.query(By.css('.section-toggle'))).toBeNull();
        expect(editor().properties['subtitle']).toBe('Test Input Payload');
    });

    it('names the expand icon "Expand editor" unless told what it does', () => {
        fixture.detectChanges();
        expect(editor().properties['expandLabel']).toBe('Expand editor');

        fixture.componentRef.setInput('expandLabel', 'Swap with code');
        fixture.detectChanges();
        expect(editor().properties['expandLabel']).toBe('Swap with code');
    });

    describe('editor header action', () => {
        function showAction(): void {
            fixture.componentRef.setInput('actionIcon', 'create-doc');
            fixture.componentRef.setInput('actionLabel', 'Insert example from selected fields');
        }

        it('gives the editor no action by default (the webhook panel)', () => {
            fixture.detectChanges();

            expect(editor().properties['actionIcon']).toBeNull();
        });

        it('forwards the icon, label and disabled reason to the editor header', () => {
            showAction();
            fixture.componentRef.setInput('actionDisabledReason', 'Select fields first');
            fixture.detectChanges();

            expect(editor().properties['actionIcon']).toBe('create-doc');
            expect(editor().properties['actionLabel']).toBe('Insert example from selected fields');
            expect(editor().properties['actionDisabledReason']).toBe('Select fields first');
        });

        it('is no longer a row of its own above the editor card', () => {
            showAction();
            fixture.detectChanges();

            const children = Array.from<HTMLElement>(fixture.nativeElement.children).map((child) => child.classList[0]);
            expect(children.slice(0, 2)).toEqual(['section-toggle', 'editor-card']);
            expect(fixture.nativeElement.querySelector('.editor-card > button')).toBeNull();
        });

        it('is forwarded in the non-collapsible (expanded) layout too', () => {
            showAction();
            fixture.componentRef.setInput('collapsible', false);
            fixture.componentRef.setInput('fullHeight', true);
            fixture.detectChanges();

            expect(editor().properties['actionIcon']).toBe('create-doc');
        });

        it('is hidden with the editor while the section is collapsed', () => {
            showAction();
            fixture.detectChanges();

            fixture.debugElement.query(By.css('.section-toggle')).nativeElement.click();
            fixture.detectChanges();

            expect(editor()).toBeNull();
        });

        it('is hidden while read-only', () => {
            showAction();
            fixture.componentRef.setInput('readonly', true);
            fixture.detectChanges();

            expect(editor().properties['actionIcon']).toBeNull();
        });

        it('forwards the action from the editor', () => {
            const action = vi.fn();
            fixture.componentInstance.action.subscribe(action);
            showAction();
            fixture.detectChanges();

            editor().triggerEventHandler('action');

            expect(action).toHaveBeenCalledTimes(1);
        });
    });

    it('forwards expand from the editor', () => {
        const expand = vi.fn();
        fixture.componentInstance.expand.subscribe(expand);
        fixture.detectChanges();

        editor().triggerEventHandler('expand');

        expect(expand).toHaveBeenCalledTimes(1);
    });
});
