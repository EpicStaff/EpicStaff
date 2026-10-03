import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';

import { RuffDiagnosticsService } from '../../../../shared/ruff-linter/services/ruff-diagnostics.service';
import { RuffWasmService } from '../../../../shared/ruff-linter/services/ruff-wasm.service';
import { CodeEditorComponent } from './code-editor.component';

describe('CodeEditorComponent', () => {
    let fixture: ComponentFixture<CodeEditorComponent>;

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [CodeEditorComponent],
            providers: [
                { provide: RuffWasmService, useValue: { check: () => Promise.resolve([]) } },
                { provide: RuffDiagnosticsService, useValue: { setMarkers: () => {}, hasSyntaxErrors: () => false } },
            ],
        });
        // Monaco does not run in jsdom: render its host element as an unknown custom element instead.
        TestBed.overrideComponent(CodeEditorComponent, {
            remove: { imports: [MonacoEditorModule, FormsModule] },
            add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
        fixture = TestBed.createComponent(CodeEditorComponent);
    });

    function query(selector: string): HTMLElement | null {
        return fixture.debugElement.query(By.css(selector))?.nativeElement ?? null;
    }

    it('fills its host with no resize handle or expand icon by default', () => {
        fixture.detectChanges();

        expect(fixture.nativeElement.classList.contains('fixed-height')).toBe(false);
        expect(query('.editor-container')?.style.height).toBe('');
        expect(query('.editor-resize-handle')).toBeNull();
        expect(query('app-icon-button[icon="editor-expand"]')).toBeNull();
    });

    it('uses an opt-in fixed height with a resize handle', () => {
        fixture.componentRef.setInput('editorHeight', 220);
        fixture.detectChanges();

        expect(fixture.nativeElement.classList.contains('fixed-height')).toBe(true);
        expect(query('.editor-container')?.style.height).toBe('220px');
        expect(query('.editor-resize-handle')).not.toBeNull();
    });

    it('applies a dragged height and resets it when the input changes', () => {
        fixture.componentRef.setInput('editorHeight', 220);
        fixture.detectChanges();

        fixture.debugElement.query(By.css('.editor-resize-handle')).triggerEventHandler('heightChange', 340);
        fixture.detectChanges();
        expect(query('.editor-container')?.style.height).toBe('340px');

        fixture.componentRef.setInput('editorHeight', 180);
        fixture.detectChanges();
        expect(query('.editor-container')?.style.height).toBe('180px');
    });

    it('emits expand from the header icon when allowed', () => {
        const expand = vi.fn();
        fixture.componentInstance.expand.subscribe(expand);
        fixture.componentRef.setInput('allowExpand', true);
        fixture.detectChanges();

        fixture.debugElement.query(By.css('app-icon-button[icon="editor-expand"]')).triggerEventHandler('onClick');

        expect(expand).toHaveBeenCalledTimes(1);
    });

    it('renders the default header with the inline entrypoint and icon buttons', () => {
        fixture.componentRef.setInput('allowExpand', true);
        fixture.detectChanges();

        expect(query('.editor-header')?.classList.contains('editor-header--compact')).toBe(false);
        expect(query('.editor-title .entrypoint-main')?.textContent?.trim()).toBe('(entrypoint "main")');
        expect(query('.editor-subtitle')).toBeNull();
        expect(query('app-icon-button[icon="copy"]')).not.toBeNull();
        expect(query('app-icon-button[icon="editor-expand"]')).not.toBeNull();
        expect(query('button.action-icon')).toBeNull();
    });

    describe('compact header', () => {
        function actionButtons(): HTMLButtonElement[] {
            return fixture.debugElement
                .queryAll(By.css('.right-section button.action-icon'))
                .map((button) => button.nativeElement as HTMLButtonElement);
        }

        beforeEach(() => {
            fixture.componentRef.setInput('compactHeader', true);
        });

        it('renders the JSON editor header look: muted subtitle and bare svg action icons', () => {
            fixture.componentRef.setInput('allowExpand', true);
            fixture.detectChanges();

            expect(query('.editor-header')?.classList.contains('editor-header--compact')).toBe(true);
            expect(query('.editor-title')?.textContent?.trim()).toBe('Python3');
            expect(query('.left-section > .editor-subtitle')?.textContent?.trim()).toBe('(entrypoint "main")');
            expect(query('.entrypoint-main')).toBeNull();
            expect(query('app-icon-button')).toBeNull();

            const [copyButton, expandButton] = actionButtons();
            expect(copyButton.getAttribute('aria-label')).toBe('Copy code');
            expect(copyButton.querySelector('app-svg-icon[icon="copy"]')?.getAttribute('size')).toBe('1rem');
            expect(expandButton.getAttribute('aria-label')).toBe('Expand editor');
            expect(expandButton.querySelector('app-svg-icon[icon="editor-expand"]')?.getAttribute('size')).toBe(
                '0.875rem'
            );
        });

        it('keeps the actions as keyboard-reachable buttons that copy and expand', () => {
            const expand = vi.fn();
            const copyCode = vi.spyOn(fixture.componentInstance, 'copyCode').mockImplementation(() => {});
            fixture.componentInstance.expand.subscribe(expand);
            fixture.componentRef.setInput('allowExpand', true);
            fixture.componentRef.setInput('expandLabel', 'Swap with test payload');
            fixture.detectChanges();

            const [copyButton, expandButton] = actionButtons();
            expect(copyButton.type).toBe('button');
            expect(expandButton.getAttribute('aria-label')).toBe('Swap with test payload');

            copyButton.click();
            expandButton.click();

            expect(copyCode).toHaveBeenCalledTimes(1);
            expect(expand).toHaveBeenCalledTimes(1);
        });

        it('shows only the copy action unless expand is allowed, also when read-only', () => {
            fixture.componentInstance.readOnly = true;
            fixture.detectChanges();

            expect(actionButtons().map((button) => button.getAttribute('aria-label'))).toEqual(['Copy code']);
        });
    });
});
