import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

import { ToastService } from '../../../services/notifications';
import { JsonEditorComponent } from './json-editor.component';

describe('JsonEditorComponent header action', () => {
    let fixture: ComponentFixture<JsonEditorComponent>;

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [JsonEditorComponent],
            providers: [{ provide: ToastService, useValue: { success: vi.fn() } }],
        });
        // Monaco does not run in jsdom: render its host element as an unknown custom element instead.
        TestBed.overrideComponent(JsonEditorComponent, {
            remove: { imports: [MonacoEditorModule, FormsModule] },
            add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
        fixture = TestBed.createComponent(JsonEditorComponent);
        fixture.componentInstance.allowCopy = true;
        fixture.componentInstance.allowExpand = true;
    });

    function headerIcons(): HTMLElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll('.right-section > .action-icon'));
    }

    /** The sprite icon each header action draws, in order. */
    function headerIconNames(): string[] {
        return headerIcons().map((icon) => icon.querySelector('use')!.getAttribute('href')!.replace('#icon-', ''));
    }

    function actionButton(): HTMLButtonElement | null {
        return fixture.nativeElement.querySelector('.right-section > button.action-icon');
    }

    function actionTooltip(): string {
        return fixture.debugElement.query(By.css('.right-section > button.action-icon')).injector.get(MatTooltip)
            .message;
    }

    function showAction(): void {
        fixture.componentRef.setInput('actionIcon', 'create-doc');
        fixture.componentRef.setInput('actionLabel', 'Insert example from selected fields');
    }

    it('shows the height drag handle by default and hides it when not resizable', () => {
        fixture.detectChanges();
        expect(fixture.debugElement.query(By.css('.editor-resize-handle'))).not.toBeNull();

        fixture.componentRef.setInput('resizable', false);
        fixture.detectChanges();
        expect(fixture.debugElement.query(By.css('.editor-resize-handle'))).toBeNull();
    });

    it('renders no action by default, leaving the copy and expand icons as they are', () => {
        fixture.detectChanges();

        expect(actionButton()).toBeNull();
        expect(headerIconNames()).toEqual(['copy', 'editor-expand']);
    });

    it('renders the action as an icon-only button before the copy icon, sized like it', () => {
        showAction();
        fixture.detectChanges();

        expect(headerIconNames()).toEqual(['create-doc', 'copy', 'editor-expand']);
        expect(headerIcons()[0]).toBe(actionButton());
        const button = actionButton()!;
        expect(button.type).toBe('button');
        expect(button.textContent!.trim()).toBe('');
        const actionSvg = button.querySelector('svg')!;
        const copySvg = headerIcons()[1].querySelector('svg')!;
        expect(actionSvg.style.width).toBe('1rem');
        expect(actionSvg.style.width).toBe(copySvg.style.width);
    });

    it('keeps the collapsible toggle first', () => {
        fixture.componentInstance.collapsible = true;
        showAction();
        fixture.detectChanges();

        expect(headerIconNames()).toEqual(['preview', 'create-doc', 'copy', 'editor-expand']);
    });

    it('names the action with its label, as aria-label and tooltip', () => {
        showAction();
        fixture.detectChanges();

        expect(actionButton()!.getAttribute('aria-label')).toBe('Insert example from selected fields');
        expect(actionButton()!.getAttribute('aria-disabled')).toBe('false');
        expect(actionTooltip()).toBe('Insert example from selected fields');
    });

    it('emits action on click', () => {
        const action = vi.fn();
        fixture.componentInstance.action.subscribe(action);
        showAction();
        fixture.detectChanges();

        actionButton()!.click();

        expect(action).toHaveBeenCalledTimes(1);
    });

    it('is aria-disabled but focusable while disabled, shows why, and does not emit', () => {
        const action = vi.fn();
        fixture.componentInstance.action.subscribe(action);
        showAction();
        fixture.componentRef.setInput('actionDisabledReason', 'Select fields first');
        fixture.detectChanges();

        const button = actionButton()!;
        button.click();

        expect(button.getAttribute('aria-disabled')).toBe('true');
        expect(button.disabled).toBe(false);
        expect(button.tabIndex).toBe(0);
        expect(button.getAttribute('aria-label')).toBe('Insert example from selected fields');
        expect(actionTooltip()).toBe('Select fields first');
        expect(action).not.toHaveBeenCalled();
    });
});
