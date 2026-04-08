import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { ButtonComponent, IconButtonComponent } from '@shared/components';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GetNgrokConfigResponse } from '../../../models/ngrok-config.model';

@Component({
    selector: 'app-ngrok-config-item',
    imports: [CommonModule, AppSvgIconComponent, IconButtonComponent, ButtonComponent],
    templateUrl: './ngrok-config-item.component.html',
    styleUrls: ['./ngrok-config-item.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NgrokConfigItemComponent {
    config = input.required<GetNgrokConfigResponse>();

    configureClicked = output<void>();
    deleteClicked = output<void>();

    public onConfigure(): void {
        this.configureClicked.emit();
    }

    public onDelete(): void {
        this.deleteClicked.emit();
    }
}
