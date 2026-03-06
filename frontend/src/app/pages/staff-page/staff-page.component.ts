import { Component, OnInit, ViewChild, HostListener  } from '@angular/core';
import { Dialog, DialogRef } from '@angular/cdk/dialog'; // Import from CDK instead of Material
import { PageHeaderComponent } from '../../shared/components/header/page-header.component';
import { FullAgent, FullAgentService } from '../../features/staff/services/full-agent.service';
import { CreateAgentFormComponent } from '../../shared/components/create-agent-form-dialog/create-agent-form-dialog.component';
import { AgentsTableComponent } from './components/agents-table/agents-table.component';
import { ButtonComponent } from '../../shared/components/buttons/button/button.component';
import { TabButtonComponent } from '../../shared/components/tab-button/tab-button.component';
import { FiltersListComponent } from '../../shared/components/filters-list/filters-list.component';
import { LoadingSpinnerComponent } from '../../shared/components/loading-spinner/loading-spinner.component';
import { NgIf } from '@angular/common';
import { CreateAgentRequest, GetAgentRequest } from '../../features/staff/models/agent.model';
import { SaveWithIndicatorComponent } from '../../shared/components/save-with-indicator/save-with-indicator.component';
import { UnsavedIndicatorComponent } from '../../shared/components/unsaved-indicator/unsaved-indicator.component';
import { Observable, of } from 'rxjs';
import { finalize, catchError, map, tap } from 'rxjs/operators';
import { UnsavedChangesDialogService } from '../../shared/components/unsaved-changes-dialog/unsaved-changes-dialog.service';
import { CanComponentDeactivate } from '../../core/guards/unsaved-changes.guard';
import { ToastService } from '../../services/notifications/toast.service';
import { AgentDialogResult } from '../../shared/components/create-agent-form-dialog/create-agent-form-dialog.component';

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
export class StaffPageComponent implements CanComponentDeactivate {
    public newlyCreatedAgent: FullAgent | null = null;
    public isLoadingAgent = false;

    constructor(
        private dialog: Dialog,
        private fullAgentService: FullAgentService,
        private unsavedChangesDialog: UnsavedChangesDialogService,
        private toastService: ToastService,
    ) {}

    @ViewChild(AgentsTableComponent) private agentsTable?: AgentsTableComponent;

    openCreateAgentDialog(): void {
        const dialogRef = this.dialog.open<AgentDialogResult>(
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

        dialogRef.closed.subscribe((result: AgentDialogResult | undefined) => {
            if (!result || !this.agentsTable) return;

            if (result.kind === 'create') {
                this.agentsTable.addPendingCreateFromDialog(result.payload);
                return;
            }

            // if (result.kind === 'update') {
            //     this.agentsTable.addPendingUpdateFromDialog(result.payload);
            // }
        });
    }

    public isSaving = false;
    public hasUnsavedChanges = false;

    public onSave(): void {
        if (this.isSaving || !this.agentsTable || !this.hasUnsavedChanges) return;

        if (!this.agentsTable.validateBeforeSave()) {
            this.toastService.warning('Please fill in all required fields.');
            return;
        }
        
        this.isSaving = true;

        this.agentsTable
            .flushPending()
            .pipe(finalize(() => (this.isSaving = false)))
            .subscribe(() => {
                if (!this.agentsTable?.hasPendingChanges) {
                    this.toastService.success('Agents saved successfully');
                }
            });
    }

    private savePendingForLeave(): Observable<boolean> {
        if (!this.agentsTable) return of(true);
        if (!this.hasUnsavedChanges) return of(true);

        if (!this.agentsTable.validateBeforeSave()) return of(false);
        this.isSaving = true;

        return this.agentsTable.flushPending().pipe(
            map(() => {
                const success = !this.agentsTable!.hasPendingChanges;
                if (success) {
                    this.toastService.success('Agents saved successfully');
                }   
                return success;
            }),
            catchError(() => of(false)),
            finalize(() => (this.isSaving = false)),
        );
    }

    public canDeactivate(): boolean | Observable<boolean> {
        if (!this.hasUnsavedChanges) return true;

        return this.unsavedChangesDialog
            .confirm({
                title: 'Unsaved Changes',
                message: 'You have unsaved changes on this page. What would you like to do?',
                saveText: 'Save & Leave',
                dontSaveText: "Don't Save & Leave",
                cancelText: 'Cancel',
                type: 'warning',
                onSave: () => this.savePendingForLeave(),
            })
            .pipe(
                tap((result) => {
                    if (result === 'dont-save') {
                        this.agentsTable?.discardPending();
                        this.hasUnsavedChanges = false;
                    }
                }),
                map((result) => result === 'save' || result === 'dont-save'),
            );
    }

    


    @HostListener('window:beforeunload', ['$event'])
    public onBeforeUnload(event: BeforeUnloadEvent): void {
        if (!this.hasUnsavedChanges) return;

        event.preventDefault();
        event.returnValue = '';
    }
}