import { ChangeDetectionStrategy, Component } from "@angular/core";
import { StrategyForm } from "../strategy-config-form.abstract";
import { FormGroup, ReactiveFormsModule, Validators } from "@angular/forms";
import { InputNumberComponent } from "@shared/components";
import { MATERIAL_FORMS } from "@shared/material-forms";
import { CsvStrategyModel } from "../../../../../models/strategy.model";

@Component({
    selector: 'app-csv-form',
    templateUrl: './csv-form.component.html',
    styleUrls: ['../../document-config.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        InputNumberComponent,
        MATERIAL_FORMS,
        ReactiveFormsModule
    ]
})
export class CsvFormComponent extends StrategyForm<CsvStrategyModel> {
    initializeForm(config: CsvStrategyModel): FormGroup {
        return this.fb.group({
            mainParams: this.fb.group({}),
            additionalParams: this.fb.group({
                rows_in_chunk: [config.rows_in_chunk || 0],
                headers_level: [config.headers_level || 0],
            })
        });
    }
}
