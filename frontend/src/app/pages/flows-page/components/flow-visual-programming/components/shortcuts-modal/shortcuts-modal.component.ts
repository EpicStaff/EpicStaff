import { Component, input, output, signal, inject, DestroyRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BreakpointObserver } from '@angular/cdk/layout';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { BREAKPOINTS } from 'src/app/core/constants/breakpoints';

export interface ShortcutRow {
  id: string;
  label: string;
  keys: string[];
  hidden?: boolean;
  dividerAfter?: boolean;
}

export interface ShortcutSection {
  id: string;
  title: string;
  rows: ShortcutRow[];
}

@Component({
  selector: 'app-shortcuts-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './shortcuts-modal.component.html',
  styleUrl: './shortcuts-modal.component.scss',
})
export class ShortcutsModalComponent {
  open = input<boolean>(false);
  pos = input<{ top: number; left: number } | null>(null);

  title = input<string>('');
  iconSrc = input<string | null>(null);
  showClose = input<boolean>(true);
  sections = input<ShortcutSection[]>([]);

  closed = output<void>();

  size = signal<'wide' | 'compact'>('wide');
  isMediaLocked = signal(false);

  private readonly breakpointObserver = inject(BreakpointObserver);
  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    this.breakpointObserver
      .observe(BREAKPOINTS.shortcuts)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ matches }) => {
        this.isMediaLocked.set(matches);

        if (matches) {
          this.size.set('compact');
        }
      });
  }

  toggleSize(): void {
    if (this.isMediaLocked()) return;
    this.size.update(s => (s === 'wide' ? 'compact' : 'wide'));
  }

  private readonly isMacPlatform =
    typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/i.test(
      ((navigator as any).userAgentData?.platform as string | undefined) ??
        (navigator.platform ?? navigator.userAgent)
    );

  public displayKey(key: string): string {
    if (!this.isMacPlatform) return key;

    switch (key) {
      case 'Ctrl':
        return 'Cmd';
      case 'Alt':
        return 'Opt';
      default:
        return key;
    }
  }
}