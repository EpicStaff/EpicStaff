import { CdkTrapFocus } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { Language } from '@shared/constants';
import { ClickOutsideDirective } from '@shared/directives';

@Component({
    selector: 'app-language-selector',
    imports: [FormsModule, ReactiveFormsModule, ClickOutsideDirective, CdkTrapFocus, MatTooltip],
    templateUrl: './language-selector.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./language-selector.component.scss'],
})
export class LanguageSelectorComponent {
    @Input() selectedLanguage: string | null = 'auto';
    @Input() languages: Language[] = [];
    @Input() label: string = 'Language';
    @Input() disabled: boolean = false;

    @Output() languageChange = new EventEmitter<string | null>();

    isOpen = false;

    toggleDropdown(): void {
        if (!this.disabled) {
            this.isOpen = !this.isOpen;
        }
    }

    selectLanguage(langId: string | null): void {
        this.selectedLanguage = langId;
        this.languageChange.emit(langId);
        this.isOpen = false;
    }

    // Taken here, so the dialog around stays open; closing hands the focus back to the trigger.
    closeOnEscape(event: Event): void {
        event.preventDefault();
        event.stopPropagation();
        this.isOpen = false;
    }

    getSelectedLanguageName(): string {
        const selected = this.languages.find((lang) => lang.id === this.selectedLanguage);
        return selected ? selected.name : 'Select a language';
    }
}
