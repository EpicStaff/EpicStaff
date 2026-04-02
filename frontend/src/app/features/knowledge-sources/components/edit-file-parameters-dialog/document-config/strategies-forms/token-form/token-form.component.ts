import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { InputNumberComponent, ValidationErrorsComponent } from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';

import { TokenStrategyModel } from '../../../../../models/strategy.model';
import { StrategyForm } from '../strategy-config-form.abstract';

@Component({
    selector: 'app-token-form',
    templateUrl: './token-form.component.html',
    styleUrls: ['../../document-config.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [InputNumberComponent, MATERIAL_FORMS, ReactiveFormsModule, ValidationErrorsComponent],
})
export class TokenFormComponent extends StrategyForm<TokenStrategyModel> {
    initializeForm(config: TokenStrategyModel): FormGroup {
        return this.fb.group({
            mainParams: this.fb.group({
                chunk_size: [config.chunk_size || 20, [Validators.required, Validators.min(20), Validators.max(8000)]],
                chunk_overlap: [
                    config.chunk_overlap || 0,
                    [Validators.required, Validators.min(0), Validators.max(1000)],
                ],
            }),
            additionalParams: this.fb.group({}),
        });
    }
}
