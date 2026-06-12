import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--accent-dim)] focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-[var(--accent)] text-[var(--text-on-accent)]",
        secondary:
          "border-transparent bg-[var(--surface-3)] text-[var(--text-muted)]",
        destructive:
          "border-transparent bg-[var(--error)] text-[var(--text-on-accent)]",
        outline:
          "text-[var(--text)] border-[var(--border-color)]",
        success:
          "border-transparent bg-[rgba(var(--success-rgb),.15)] text-[var(--success)]",
        "new":
          "border-transparent bg-[var(--accent)] text-[var(--text-on-accent)] text-[9.5px] px-[7px] py-[1.5px] rounded-[10px]",
        feed:
          "border-transparent bg-[var(--surface-3)] text-[var(--text-muted)] text-[9.5px] px-[7px] py-[1.5px] rounded-[10px]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
