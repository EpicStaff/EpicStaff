import { ChangeDetectionStrategy, Component, forwardRef, input, signal } from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';

import { JsonEditorComponent } from '../json-editor/json-editor.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

interface KeyValueItem {
    name: string;
    value: string;
}

@Component({
    selector: 'app-key-value-list',
    imports: [TooltipComponent, FormsModule, JsonEditorComponent, MatTooltipModule],
    templateUrl: './key-value-list.component.html',
    styleUrls: ['./key-value-list.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => KeyValueListComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KeyValueListComponent implements ControlValueAccessor {
    label = input<string>('');
    tooltipText = input<string>('');
    icon = input<string>('help_outline');
    required = input<boolean>(false);
    namePlaceholder = input<string>('Name');
    valuePlaceholder = input<string>('Value');

    items = signal<KeyValueItem[]>([]);
    draftName = signal<string>('');
    draftValue = signal<string>('');
    editingIndex = signal<number | null>(null);
    isDisabled = signal<boolean>(false);
    jsonText = signal<string>('{}');

    editorOptions: Record<string, unknown> = {
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        lineNumbers: 'off',
        wordWrapBreakAfterCharacters: ',',
        wordWrapBreakBeforeCharacters: '}]',
        formatOnPaste: true,
        formatOnType: true,
        tabSize: 2,
        readOnly: false,
    };

    private isUpdatingFromJson = false;

    private onChange: (value: Record<string, string>) => void = () => {};
    private onTouched: () => void = () => {};

    confirm(): void {
        const name = this.draftName().trim();
        if (!name) return;

        const value = this.draftValue();
        const idx = this.editingIndex();

        if (idx !== null) {
            this.items.update((items) => items.map((item, i) => (i === idx ? { name, value } : item)));
        } else {
            this.items.update((items) => [...items, { name, value }]);
        }

        this.draftName.set('');
        this.draftValue.set('');
        this.editingIndex.set(null);
        this.syncJson();
        this.emit();
    }

    editCard(index: number): void {
        const item = this.items()[index];
        this.draftName.set(item.name);
        this.draftValue.set(item.value);
        this.editingIndex.set(index);
    }

    cancelEdit(): void {
        this.draftName.set('');
        this.draftValue.set('');
        this.editingIndex.set(null);
    }

    removeCard(index: number): void {
        if (this.editingIndex() === index) {
            this.cancelEdit();
        }
        this.items.update((items) => items.filter((_, i) => i !== index));
        this.syncJson();
        this.emit();
    }

    handleKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.confirm();
        }
        if (event.key === 'Escape') {
            this.cancelEdit();
        }
    }

    onJsonChange(json: string): void {
        this.jsonText.set(json);
        try {
            const parsed = JSON.parse(json || '{}');
            if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
                const items: KeyValueItem[] = Object.entries(parsed as Record<string, unknown>).map(
                    ([name, value]) => ({
                        name,
                        value: typeof value === 'string' ? value : String(value ?? ''),
                    })
                );
                this.isUpdatingFromJson = true;
                this.items.set(items);
                this.cancelEdit();
                this.emit();
                this.isUpdatingFromJson = false;
            }
        } catch {}
    }

    private syncJson(): void {
        if (this.isUpdatingFromJson) return;
        const obj = Object.fromEntries(this.items().map((i) => [i.name, i.value]));
        this.jsonText.set(JSON.stringify(obj, null, 2));
    }

    private emit(): void {
        const record = Object.fromEntries(this.items().map((i) => [i.name, i.value]));
        this.onChange(record);
        this.onTouched();
    }

    writeValue(value: Record<string, string> | null): void {
        const record = value ?? {};
        const items: KeyValueItem[] = Object.entries(record).map(([name, val]) => ({ name, value: val }));
        this.items.set(items);
        this.jsonText.set(JSON.stringify(record, null, 2));
        this.cancelEdit();
    }

    registerOnChange(fn: (value: Record<string, string>) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
