import {
  TextAlignLeftRegular,
  ArchiveRegular,
  BookOpenRegular,
  DataBarVerticalRegular,
  ErrorCircleRegular,
  ArrowCircleDownRegular,
  CheckmarkCircleRegular,
  InfoRegular,
  ClosedCaptionRegular,
  DocumentTextRegular,
  MailInboxRegular,
  KeyRegular,
  LinkRegular,
  ListRegular,
  WeatherMoonRegular,
  RssRegular,
  GlobeSearchRegular,
  SearchRegular,
  WeatherSunnyRegular,
  WarningRegular,
  SparkleRegular,
  SpinnerIosRegular,
  type FluentIcon,
} from "@fluentui/react-icons"

const iconMap: Record<string, FluentIcon> = {
  "i-align-left": TextAlignLeftRegular,
  "i-book-open": BookOpenRegular,
  "i-box-archive": ArchiveRegular,
  "i-chart-simple": DataBarVerticalRegular,
  "i-circle-check": CheckmarkCircleRegular,
  "i-circle-down": ArrowCircleDownRegular,
  "i-circle-exclamation": ErrorCircleRegular,
  "i-circle-info": InfoRegular,
  "i-closed-captioning": ClosedCaptionRegular,
  "i-file-lines": DocumentTextRegular,
  "i-inbox": MailInboxRegular,
  "i-key": KeyRegular,
  "i-link": LinkRegular,
  "i-list-ul": ListRegular,
  "i-magnifying-glass": SearchRegular,
  "i-moon": WeatherMoonRegular,
  "i-rss": RssRegular,
  "i-satellite-dish": GlobeSearchRegular,
  "i-sun": WeatherSunnyRegular,
  "i-triangle-exclamation": WarningRegular,
  "i-wand-magic-sparkles": SparkleRegular,
}

interface IconProps {
  name: string
  className?: string
}

/* Thin wrapper that maps the original SVG-sprite icon names to Lucide.
   The `name` prop accepts the same IDs (i-link, i-inbox, etc.) so no
   migration is needed in page code. */
export function Icon({ name, className = "" }: IconProps) {
  const LucideComponent = iconMap[name]
  if (!LucideComponent) return null
  return <LucideComponent className={className} />
}

/* Kept for backward compat; the inline sprite is no longer needed. */
export function IconSprite() {
  return null
}

export { SpinnerIosRegular as Loader2 }
