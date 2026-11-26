import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { HelpTooltipComponent, InputNumberComponent, ValidationErrorsComponent } from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';

import {
    CSV_HEADERS_LEVEL_DEFAULT,
    CSV_HEADERS_LEVEL_MAX,
    CSV_HEADERS_LEVEL_MIN,
    CSV_ROWS_IN_CHUNK_DEFAULT,
    CSV_ROWS_IN_CHUNK_MAX,
    CSV_ROWS_IN_CHUNK_MIN,
} from '../../../../../constants/constants';
import { CsvStrategyModel } from '../../../../../models/strategy.model';
import { StrategyForm } from '../strategy-config-form.abstract';

const INTEGER_PATTERN = /^-?\d+$/;

@Component({
    selector: 'app-csv-form',
    templateUrl: './csv-form.component.html',
    styleUrls: ['../../document-config.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        InputNumberComponent,
        HelpTooltipComponent,
        MATERIAL_FORMS,
        ReactiveFormsModule,
        ValidationErrorsComponent,
    ],
})
export class CsvFormComponent extends StrategyForm<CsvStrategyModel> {
    // A document that was never configured has no stored csv params, so both fields can be undefined.
    protected readonly rowsInChunk = computed(() => this.params().rows_in_chunk ?? CSV_ROWS_IN_CHUNK_DEFAULT);
    protected readonly headersLevel = computed(() => this.params().headers_level ?? CSV_HEADERS_LEVEL_DEFAULT);

    protected readonly ROWS_IN_CHUNK_MIN = CSV_ROWS_IN_CHUNK_MIN;
    protected readonly ROWS_IN_CHUNK_MAX = CSV_ROWS_IN_CHUNK_MAX;
    protected readonly HEADERS_LEVEL_MIN = CSV_HEADERS_LEVEL_MIN;
    protected readonly HEADERS_LEVEL_MAX = CSV_HEADERS_LEVEL_MAX;

    initializeForm(config: CsvStrategyModel): FormGroup {
        return this.fb.group({
            mainParams: this.fb.group({}),
            additionalParams: this.fb.group({
                rows_in_chunk: [
                    config.rows_in_chunk ?? CSV_ROWS_IN_CHUNK_DEFAULT,
                    [
                        Validators.required,
                        Validators.min(CSV_ROWS_IN_CHUNK_MIN),
                        Validators.max(CSV_ROWS_IN_CHUNK_MAX),
                        Validators.pattern(INTEGER_PATTERN),
                    ],
                ],
                headers_level: [
                    config.headers_level ?? CSV_HEADERS_LEVEL_DEFAULT,
                    [
                        Validators.required,
                        Validators.min(CSV_HEADERS_LEVEL_MIN),
                        Validators.max(CSV_HEADERS_LEVEL_MAX),
                        Validators.pattern(INTEGER_PATTERN),
                    ],
                ],
            }),
        });
    }
}
