import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';

@Component({
    selector: 'app-password-strength',
    imports: [CommonModule, MatIconModule],
    templateUrl: './password-strength.component.html',
    styleUrls: ['./password-strength.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class PasswordStrengthComponent {
    password = input<string>('');

    readonly bars = [0, 1, 2, 3, 4];

    get hasMinLength(): boolean { return this.password().length >= 8; }
    get hasUppercase(): boolean { return /[A-Z]/.test(this.password()); }
    get hasLowercase(): boolean { return /[a-z]/.test(this.password()); }
    get hasNumber(): boolean { return /[0-9]/.test(this.password()); }
    get hasSpecialChar(): boolean { return /[^A-Za-z0-9]/.test(this.password()); }

    get score(): number {
        return [this.hasMinLength, this.hasUppercase, this.hasLowercase, this.hasNumber, this.hasSpecialChar]
            .filter(Boolean).length;
    }

    get label(): string {
        const labels = ['', 'Very Weak', 'Weak', 'Medium', 'Strong', 'Excellent'];
        return labels[this.score] || '';
    }

    get color(): string {
        const colors = ['', '#f54242', '#ff653f', '#ff8f3f', '#99ff3f', '#2aba6b'];
        return colors[this.score] || '';
    }

    isBarFilled(index: number): boolean {
        return index < this.score;
    }
}
