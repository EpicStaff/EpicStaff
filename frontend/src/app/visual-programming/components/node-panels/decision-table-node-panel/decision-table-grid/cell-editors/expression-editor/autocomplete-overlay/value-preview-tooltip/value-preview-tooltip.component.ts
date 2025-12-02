import { Component, input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { JsonEditorComponent } from '../../../../../../../../../shared/components/json-editor/json-editor.component';

@Component({
    selector: 'app-value-preview-tooltip',
    standalone: true,
    imports: [CommonModule, JsonEditorComponent],
    templateUrl: './value-preview-tooltip.component.html',
    styleUrls: ['./value-preview-tooltip.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ValuePreviewTooltipComponent {
    public value = input.required<any>();

    public editorOptions = {
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        lineNumbers: 'off',
        folding: false,
        readOnly: true,
        domReadOnly: true,
        contextmenu: false,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12
    };

    public getType(): string {
        const val = this.value();
        if (val === null) return 'null';
        if (Array.isArray(val)) return 'array';
        return typeof val;
    }

    public isPrimitive(): boolean {
        const type = this.getType();
        return type === 'string' || type === 'number' || type === 'boolean' || type === 'undefined' || type === 'null';
    }

    public formatJson(): string {
        try {
            return JSON.stringify(this.value(), null, 2);
        } catch (e) {
            return String(this.value());
        }
    }

    public getDisplayValue(): string {
        const val = this.value();
        if (val === null) return 'null';
        if (val === undefined) return 'undefined';
        return String(val);
    }
}

