import {
  Component,
  Input,
  ChangeDetectionStrategy,
  OnInit,
  OnChanges,
  SimpleChanges,
  Output,
  EventEmitter,
  HostBinding,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  trigger,
  state,
  style,
  transition,
  animate,
} from '@angular/animations';
import { FullAgent } from '../../../../../services/full-agent.service';
import { AgentMenuComponent } from './header-sub-menu/header-sub-menu.component';
import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { getProviderIconPath } from '../../../../../features/settings-dialog/utils/get-provider-icon';

export type CardState = 'default' | 'adding' | 'removing';

interface SectionStates {
  goal: boolean;
  backstory: boolean;
  details: boolean;
}

@Component({
  selector: 'app-staff-agent-card',
  standalone: true,
  imports: [CommonModule, AgentMenuComponent, AppIconComponent],
  templateUrl: './staff-agent-card.component.html',
  styleUrls: ['./staff-agent-card.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  animations: [
    trigger('expandCollapse', [
      state(
        'collapsed',
        style({
          opacity: '0',
        })
      ),
      state(
        'expanded',
        style({
          opacity: '1',
        })
      ),
      transition('collapsed <=> expanded', [animate('300ms ease')]),
    ]),
  ],
})
export class StaffAgentCardComponent implements OnInit, OnChanges {
  @HostBinding('attr.size') @Input() size: 'small' | 'medium' | 'large' =
    'medium';
  @Input() agent!: FullAgent;
  @Input() cardState: CardState = 'default';

  @Output() public addAgent = new EventEmitter<FullAgent>();
  @Output() public showAdvancedSettings = new EventEmitter<void>();
  @Output() public addToFavorites = new EventEmitter<void>();
  @Output() public removeAgent = new EventEmitter<FullAgent>();
  @Output() public editAgent = new EventEmitter<FullAgent>();

  public goalExpanded = false;
  public backstoryExpanded = false;
  public toolsExpanded = false;
  public isMenuOpen = false;

  // Default state for sections (all collapsed)
  public sectionStates: SectionStates = {
    goal: false,
    backstory: false,
    details: false,
  };

  constructor(private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    // Initially collapse all sections
    this.sectionStates.goal = false;
    this.sectionStates.backstory = false;
    this.sectionStates.details = false;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['agent'] && !changes['agent'].firstChange) {
      console.log('Agent updated:', this.agent);
      console.log('Updated tools:', this.agent.mergedTools);

      // Ensure the details section is expanded when agent is updated
      // so the user can see the updated tools
      if (this.agent.mergedTools && this.agent.mergedTools.length > 0) {
        this.sectionStates.details = true;
        // Force change detection to update the view
        this.cdr.markForCheck();
      }
    }
  }

  public onAddAgentClick(): void {
    this.addAgent.emit(this.agent);
  }

  public onRemoveAgentClick(): void {
    console.log('Remove agent clicked:', this.agent.role);
    this.removeAgent.emit(this.agent);
  }

  public toggleMenu(event: Event): void {
    event.stopPropagation();
    this.isMenuOpen = !this.isMenuOpen;
  }

  public closeMenu(): void {
    this.isMenuOpen = false;
  }

  public onAdvancedSettings(): void {
    this.showAdvancedSettings.emit();
  }

  public onAddToFavorites(): void {
    this.addToFavorites.emit();
  }

  public onRemoveFromMenu(): void {
    console.log('Remove agent from menu clicked:', this.agent.role);
    this.removeAgent.emit(this.agent);
    this.closeMenu();
  }

  public onEditAgent(): void {
    console.log('Edit agent clicked:', this.agent.role);
    this.editAgent.emit(this.agent);
    this.closeMenu();
  }

  public toggleSection(section: keyof SectionStates): void {
    // Toggle the section's expanded state
    this.sectionStates[section] = !this.sectionStates[section];
  }

  public isTextTruncated(text?: string): boolean {
    return typeof text === 'string' && text.length > 200;
  }

  public getDisplayedTools(): { id: number; name: string; type: string }[] {
    if (!this.agent.mergedTools || this.agent.mergedTools.length === 0) {
      return [];
    }

    // if (this.toolsExpanded || this.agent.mergedTools.length <= 4) {
    //   return this.agent.mergedTools;
    // } else {
    //   return this.agent.mergedTools.slice(0, 4);
    // }
    return [];
  }

  public shouldShowToolsToggle(): boolean {
    return !!this.agent.mergedTools && this.agent.mergedTools.length > 4;
  }

  public toggleToolsExpanded(): void {
    this.toolsExpanded = !this.toolsExpanded;
    console.log('Tools expanded:', this.toolsExpanded);
    this.cdr.markForCheck();
  }

  public getProviderIcon(providerName: string | undefined | null): string {
    return getProviderIconPath(providerName);
  }
}
