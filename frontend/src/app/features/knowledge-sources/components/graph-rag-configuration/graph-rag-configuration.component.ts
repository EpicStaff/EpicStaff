import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    inject,
    input,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { RadioButtonComponent, SelectItem } from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { EMPTY, merge, Observable, skip } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CollectionGraphRag, CreateGraphRagIndexConfigRequest, GraphRagFileType } from '../../models/graph-rag.model';
import { RagConfiguration } from '../../models/rag-configuration';
import { GraphRagService } from '../../services/graph-rag.service';
import { GraphRagFilesListComponent } from './files-list/files-list.component';
import { AppGraphRagParametersComponent } from './index-parameters/index-parameters.component';

@Component({
    selector: 'app-graph-rag-configuration',
    templateUrl: './graph-rag-configuration.component.html',
    styleUrls: ['./graph-rag-configuration.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        RadioButtonComponent,
        GraphRagFilesListComponent,
        MATERIAL_FORMS,
        AppGraphRagParametersComponent,
        AppSvgIconComponent,
    ],
})
export class GraphRagConfigurationComponent implements OnInit, AfterViewInit, RagConfiguration {
    private toastService = inject(ToastService);
    private graphRagService = inject(GraphRagService);
    private destroyRef = inject(DestroyRef);

    graphRag = input.required<CollectionGraphRag>();

    selectedFormat = signal<GraphRagFileType>('text');
    format$ = toObservable(this.selectedFormat);

    formatOptions: SelectItem[] = [
        {
            name: 'TXT',
            value: 'text',
        },
        {
            name: 'CSV',
            value: 'csv',
        },
        {
            name: 'JSON',
            value: 'json',
        },
    ];

    @ViewChild('indexParameters', { static: true }) indexParameters!: AppGraphRagParametersComponent;

    ngOnInit() {
        const format = this.graphRag().index_config.file_type;
        this.selectedFormat.set(format);
    }

    ngAfterViewInit(): void {
        merge(this.indexParameters.form.valueChanges, this.format$)
            .pipe(
                skip(1),
                distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
                debounceTime(300),
                switchMap(() => {
                    const data = this.getConfigurationData();
                    if (!data) return EMPTY;

                    return this.updateConfigurationData(data).pipe(
                        tap(() => this.toastService.success('Parameters updated')),
                        catchError(() => {
                            this.toastService.error('Parameters updating failed');
                            return EMPTY;
                        })
                    );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    getConfigurationData(): CreateGraphRagIndexConfigRequest | false {
        if (this.indexParameters.form.invalid) {
            this.toastService.error('Form value invalid');
            return false;
        }

        const formValue = this.indexParameters.form.value;
        const file_type = this.selectedFormat();

        return { ...formValue, file_type };
    }

    private updateConfigurationData(
        data: CreateGraphRagIndexConfigRequest
    ): Observable<CreateGraphRagIndexConfigRequest> {
        const id = this.graphRag().graph_rag_id;
        return this.graphRagService.updateRagIndexConfigs(id, data);
    }
}
