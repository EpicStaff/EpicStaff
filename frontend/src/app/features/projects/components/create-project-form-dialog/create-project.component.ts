import {
    Component,
    OnInit,
    ChangeDetectionStrategy,
    signal,
    Input,
} from '@angular/core';
import {
    FormBuilder,
    FormGroup,
    FormControl,
    Validators,
    ReactiveFormsModule,
} from '@angular/forms';
import { MATERIAL_FORMS } from '../../../../shared/material-forms';

import { DialogRef } from '@angular/cdk/dialog';
import { ErrorStateMatcher } from '@angular/material/core';
import { CustomErrorStateMatcher } from '../../../../shared/error-state-matcher/custom-error-state-matcher';
import {
    ProjectProcess,
    CreateProjectRequest,
} from '../../models/project.model';
import { ProjectsStorageService } from '../../services/projects-storage.service';

// Typed interface for the form data - all fields are non-nullable
interface ProjectFormData {
    name: string;
    description: string;
    process: ProjectProcess;
    memory: boolean;
    cache: boolean;
    max_rpm: number;
    search_limit: number;
    similarity_threshold: number;
}

@Component({
    selector: 'app-create-project',
    standalone: true,
    templateUrl: './create-project.component.html',
    styleUrls: ['./create-project.component.scss'],
    imports: [ReactiveFormsModule, ...MATERIAL_FORMS],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        {
            provide: ErrorStateMatcher,
            useClass: CustomErrorStateMatcher,
        },
    ],
})
export class CreateProjectComponent implements OnInit {
    public isTemplate: boolean = true;
    
    public projectForm!: FormGroup<{
        name: FormControl<string>;
        description: FormControl<string>;
        process: FormControl<ProjectProcess>;
        memory: FormControl<boolean>;
        cache: FormControl<boolean>;
        max_rpm: FormControl<number>;
        search_limit: FormControl<number>;
        similarity_threshold: FormControl<number>;
    }>;
    public isSubmitting = signal(false);
    public ProjectProcess = ProjectProcess;

    constructor(
        private fb: FormBuilder,
        private dialogRef: DialogRef<any>,
        private projectsStorageService: ProjectsStorageService
    ) {
        // Get isTemplate from dialog data, default to true if not provided
        this.isTemplate = this.dialogRef.config.data?.isTemplate ?? true;
    }

    ngOnInit(): void {
        this.initializeForm();
    }

    private initializeForm(): void {
        this.projectForm = new FormGroup({
            name: new FormControl<string>('', Validators.required),
            description: new FormControl<string>(''),
            process: new FormControl<ProjectProcess>(
                ProjectProcess.SEQUENTIAL,
                Validators.required
            ),
            memory: new FormControl<boolean>(false),
            cache: new FormControl<boolean>(false),
            max_rpm: new FormControl<number>(15, [
                Validators.min(1),
                Validators.max(50),
            ]),
            search_limit: new FormControl<number>(10, [
                Validators.min(1),
                Validators.max(1000),
            ]),
            similarity_threshold: new FormControl<number>(0.7, [
                Validators.min(0.0),
                Validators.max(1.0),
            ]),
        }) as FormGroup<{
            name: FormControl<string>;
            description: FormControl<string>;
            process: FormControl<ProjectProcess>;
            memory: FormControl<boolean>;
            cache: FormControl<boolean>;
            max_rpm: FormControl<number>;
            search_limit: FormControl<number>;
            similarity_threshold: FormControl<number>;
        }>;
    }

    get nameField(): FormControl<string> {
        return this.projectForm.controls.name;
    }

    get maxRpmField(): FormControl<number> {
        return this.projectForm.controls.max_rpm;
    }

    get searchLimitField(): FormControl<number> {
        return this.projectForm.controls.search_limit;
    }

    get thresholdField(): FormControl<number> {
        return this.projectForm.controls.similarity_threshold;
    }

    formatRpmLabel(value: number): string {
        return `${value}`;
    }

    formatSearchLimitLabel(value: number): string {
        return `${value}`;
    }

    formatThresholdLabel(value: number): string {
        return `${value}`;
    }

    onSubmit(): void {
        if (this.projectForm.invalid || this.isSubmitting()) {
            return;
        }

        this.isSubmitting.set(true);

        const formData = this.projectForm.value as ProjectFormData;
        console.log('Form submitted:', formData);

        const createProjectRequest: CreateProjectRequest = {
            name: formData.name,
            description: formData.description || null,
            process: formData.process,
            memory: formData.memory,
            cache: formData.cache,
            max_rpm: formData.max_rpm,
            search_limit: formData.search_limit,
            similarity_threshold: formData.similarity_threshold.toString(),
            is_template: this.isTemplate,
        };

        // Call the actual service
        this.projectsStorageService
            .createProject(createProjectRequest)
            .subscribe({
                next: (newProject) => {
                    console.log('Project created successfully:', newProject);
                    this.isSubmitting.set(false);
                    // Close dialog and return the created project
                    this.dialogRef.close(newProject);
                },
                error: (error) => {
                    console.error('Error creating project:', error);
                    this.isSubmitting.set(false);
                    // TODO: Show error message to user (snackbar, toast, etc.)
                    // For now, just log the error
                },
            });
    }

    onCancel(): void {
        console.log('Form cancelled');
        // Close dialog without returning data
        this.dialogRef.close();
    }
}
