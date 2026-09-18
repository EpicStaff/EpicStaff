import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-tree-search',
    imports: [FormsModule, AppSvgIconComponent],
    templateUrl: './tree-search.component.html',
    styleUrls: ['./tree-search.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TreeSearchComponent {
    value = input('');
    valueChange = output<string>();

    onInput(v: string): void {
        this.valueChange.emit(v);
    }

    onClear(): void {
        this.valueChange.emit('');
    }
}
