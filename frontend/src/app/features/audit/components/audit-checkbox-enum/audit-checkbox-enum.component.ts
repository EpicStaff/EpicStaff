import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';

import { AuditEnumOption } from '../../models/audit-filter.models';

@Component({
    selector: 'app-audit-checkbox-enum',
    standalone: true,
    imports: [CheckboxComponent, AppSvgIconComponent],
    templateUrl: './audit-checkbox-enum.component.html',
    styleUrls: ['./audit-checkbox-enum.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditCheckboxEnumComponent {
    public options = input<AuditEnumOption[]>([]);
    public disabledValues = input<string[]>([]);
    public disabledHint = input<string>('');
    public value = model<string[]>([]);

    public isSelected(option: string): boolean {
        return this.value().includes(option);
    }

    public isDisabled(option: string): boolean {
        return this.disabledValues().includes(option);
    }

    public toggle(option: string): void {
        if (this.isDisabled(option)) {
            return;
        }
        this.value.update((current) =>
            current.includes(option) ? current.filter((item) => item !== option) : [...current, option]
        );
    }
}
