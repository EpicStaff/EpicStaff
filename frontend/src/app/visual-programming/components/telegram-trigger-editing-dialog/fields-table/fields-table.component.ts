import {
    ChangeDetectionStrategy,
    Component,
    computed, input,
    model,
} from "@angular/core";
import {CheckboxComponent} from "@shared/components";
import {TableItem} from "../telegram-trigger-editing-dialog.component";
import {VariablesInputComponent} from "./variables-input/variables-input.component";

@Component({
    selector: 'app-telegram-fields-table',
    templateUrl: './fields-table.component.html',
    styleUrls: ['./fields-table.component.scss'],
    imports: [
        CheckboxComponent,
        VariablesInputComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class TelegramTriggerFieldsTableComponent {
    tableItems = model<TableItem[]>([]);
    searchTerm = input<string>('');

    messageTableItems = computed(() => {
        return this.tableItems().filter(item => {
            const term = this.searchTerm().toLowerCase();
            return item.parent === 'message' && item.field_name.toLowerCase().includes(term);
        });
    });
    callbackQueryTableItems = computed(() => {
        return this.tableItems().filter(item => {
            const term = this.searchTerm().toLowerCase();
            return item.parent === 'callback_query' && item.field_name.toLowerCase().includes(term);
        });
    });

    allChecked = computed(() => {
        const items = this.tableItems();
        return items.length > 0 && items.every(r => r.checked);
    });

    indeterminate = computed(() => {
        const items = this.tableItems();
        return items.some(i => i.checked) && !this.allChecked()
    });

    toggleAll() {
        const all = this.allChecked();
        this.tableItems.update(items => items.map(i => ({ ...i, checked: !all })));
    }

    toggleItem(item: TableItem) {
        this.tableItems.update(items => items.map(i => {
            return i === item ? { ...i, checked: !i.checked } : i
        }));
    }

    updatePath(item: TableItem, path: string) {
        this.tableItems.update(items => items.map(i => {
            return i === item ? { ...i, variable_path: path } : i
        }));
    }
}
