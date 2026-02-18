import { Component, OnInit, ViewChild  } from '@angular/core';
import { Dialog, DialogRef } from '@angular/cdk/dialog'; // Import from CDK instead of Material
import { PageHeaderComponent } from '../../shared/components/header/page-header.component';
import { FullAgent, FullAgentService } from '../../services/full-agent.service';
import { CreateAgentFormComponent } from '../../shared/components/create-agent-form-dialog/create-agent-form-dialog.component';
import { AgentsTableComponent } from './components/agents-table/agents-table.component';
import { ButtonComponent } from '../../shared/components/buttons/button/button.component';
import { TabButtonComponent } from '../../shared/components/tab-button/tab-button.component';
import { FiltersListComponent } from '../../shared/components/filters-list/filters-list.component';
import { LoadingSpinnerComponent } from '../../shared/components/loading-spinner/loading-spinner.component';
import { NgIf } from '@angular/common';
import { GetAgentRequest } from '../../shared/models/agent.model';
import { SaveWithIndicatorComponent } from '../../shared/components/save-with-indicator/save-with-indicator.component';
import { UnsavedIndicatorComponent } from '../../shared/components/unsaved-indicator/unsaved-indicator.component';

@Component({
    selector: 'app-staff-page',
    standalone: true,
    imports: [
        AgentsTableComponent,
        ButtonComponent,
        LoadingSpinnerComponent,
        NgIf,
        SaveWithIndicatorComponent,
        UnsavedIndicatorComponent
    ],
    templateUrl: './staff-page.component.html',
    styleUrls: ['./staff-page.component.scss'],
})
export class StaffPageComponent {
    public newlyCreatedAgent: FullAgent | null = null;
    public isLoadingAgent = false;

    constructor(
        private dialog: Dialog,
        private fullAgentService: FullAgentService
    ) {}

    @ViewChild(AgentsTableComponent) private agentsTable?: AgentsTableComponent;

    openCreateAgentDialog(): void {
        const dialogRef = this.dialog.open<GetAgentRequest>(
            CreateAgentFormComponent,
            {
                maxWidth: '95vw',
                maxHeight: '90vh',
                autoFocus: true,

                data: {
                    toolConfigs: [],
                    toolsData: [],
                },
            }
        );

        dialogRef.closed.subscribe((result: GetAgentRequest | undefined) => {
            if (result) {
                this.isLoadingAgent = true;

                this.fullAgentService.getFullAgentById(result.id).subscribe({
                    next: (fullAgent) => {
                        if (fullAgent) {
                            this.newlyCreatedAgent = fullAgent;
                        } else {
                            console.error(
                                'Could not find newly created agent with ID:',
                                result.id
                            );
                        }
                        this.isLoadingAgent = false;
                    },
                    error: (error) => {
                        console.error(
                            'Error fetching newly created agent:',
                            error
                        );
                        this.isLoadingAgent = false;
                    },
                });
            }
        });
    }

    public isSaving = false;
    public hasUnsavedChanges = false;

    public onSave(): void {
        this.agentsTable?.flushPending();
    }
}