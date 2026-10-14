import { HugeiconsIcon } from "@hugeicons/react";
import type { IconSvgElement } from "@hugeicons/react";

/**
 * Icon system.
 *
 * Every icon in CodeMentor comes from one Hugeicons outlined set at one stroke
 * weight. Two rules make that stick:
 *
 * 1. Icons are imported through this barrel so the set cannot drift per-file.
 * 2. `AppIcon` is always `aria-hidden`. An icon never carries the accessible
 *    name — the control it sits in does. That keeps `aria-label` on buttons and
 *    `<label>` on inputs as the single source of truth, and stops screen
 *    readers announcing the same word twice.
 */

type AppIconProps = {
  icon: IconSvgElement;
  /** 12 compact metadata · 14 dense UI · 16 default · 18 controls · 20 nav · 24 feature. */
  size?: number;
  /** Optical weight. 1.5 is the house stroke; raise it only for tiny marks. */
  strokeWidth?: number;
  className?: string;
};

export function AppIcon({ icon, size = 16, strokeWidth = 1.5, className }: AppIconProps) {
  return (
    <HugeiconsIcon
      icon={icon}
      size={size}
      className={className}
      strokeWidth={strokeWidth}
      absoluteStrokeWidth
      aria-hidden
      focusable="false"
    />
  );
}

export {
  /* Brand */
  GraduationCapIcon,
  MentorIcon,

  /* Navigation & actions */
  Login01Icon,
  Logout01Icon,
  Delete02Icon,
  RefreshIcon,
  ArrowRight01Icon,
  ArrowUpRight01Icon,
  Search01Icon,

  /* Disclosure */
  ChevronDownIcon,
  ChevronUpIcon,

  /* Status */
  Alert01Icon,
  Alert02Icon,
  Tick02Icon,
  Cancel01Icon,
  CancelCircleIcon,
  CheckmarkCircle02Icon,
  HelpCircleIcon,
  InformationCircleIcon,
  WifiDisconnected01Icon,

  /* Learning surface */
  LightbulbIcon,
  SparklesIcon,
  StarIcon,
  EyeIcon,
  ClipboardListIcon,
  CodeIcon,
  PlayIcon,
  PauseIcon,
  SkipBackIcon,
  SkipForwardIcon,
  RepeatIcon,
  Bug01Icon,
  MagicWand01Icon,
  FlameIcon,

  /* Controls */
  GripVerticalIcon,
  ArrowUp01Icon,
  ArrowDown01Icon,

  /* Data */
  Coins01Icon,
  Timer01Icon,
  ChartBarLineIcon,
  AnalyticsUpIcon,
  Analytics01Icon,
  Layers01Icon,
  ActivityIcon,
  TrophyIcon,

  /* Settings */
  Settings02Icon,
  LanguagesIcon,
  TranslateIcon,
  MonitorIcon,
  Moon02Icon,
  Sun01Icon,
  ContrastIcon,
  UserIcon,
} from "@hugeicons/core-free-icons";